"""Scrape Google Maps for travel time data"""

import asyncio
import random
import json
import re
import time
from typing import Dict, Optional, List
from datetime import datetime
from playwright.async_api import async_playwright, Browser, Page, BrowserContext
import logging

logger = logging.getLogger(__name__)


class GMapsScraper:
    """Scrape Google Maps directions for travel time data"""

    def __init__(
        self,
        headless: bool = True,
        min_delay: float = 2.0,
        max_delay: float = 10.0,
        proxy: Optional[str] = None
    ):
        """
        Initialize Google Maps scraper

        Args:
            headless: Run browser in headless mode
            min_delay: Minimum delay between requests (seconds)
            max_delay: Maximum delay between requests (seconds)
            proxy: Optional proxy URL
        """
        self.headless = headless
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.proxy = proxy
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.requests_count = 0
        self._captured_api_data = None  # For network interception

    async def start_browser(self):
        """Initialize browser with anti-detection measures and network interception"""
        self.playwright = await async_playwright().start()

        browser_args = {
            "headless": self.headless,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-setuid-sandbox",
            ]
        }

        if self.proxy:
            browser_args["proxy"] = {"server": self.proxy}

        self.browser = await self.playwright.chromium.launch(**browser_args)

        # Create context with stealth settings
        self.context = await self.browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="id-ID",
            timezone_id="Asia/Jakarta"
        )

        # Add init script to avoid detection
        await self.context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

        self.page = await self.context.new_page()

        # NEW: Add response interception for Google Maps API
        self._captured_api_data = None

        async def handle_response(response):
            """Capture responses from Google Maps Directions API"""
            # Google Maps uses several endpoint patterns for directions
            url = response.url
            if any(pattern in url for pattern in [
                '/maps/api/directions/json',
                '/maps/dir/',
                '/maps/rbt',
                '/maps/vt'
            ]):
                try:
                    if response.status == 200:
                        # Try to parse JSON response
                        content_type = response.headers.get('content-type', '')
                        if 'application/json' in content_type:
                            body = await response.text()
                            data = json.loads(body)
                            self._captured_api_data = data
                            logger.debug(f"Captured API response from {url[:100]}...")
                except Exception as e:
                    logger.debug(f"Could not capture response: {e}")

        self.page.on('response', handle_response)

        logger.info("Browser initialized with network interception")

    async def stop_browser(self):
        """Close browser and cleanup"""
        if self.page:
            await self.page.close()
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

        self.page = None
        self.context = None
        self.browser = None
        self.playwright = None
        logger.info("Browser closed")

    def _random_delay(self):
        """Random delay between requests"""
        delay = random.uniform(self.min_delay, self.max_delay)
        logger.debug(f"Delaying for {delay:.2f} seconds")
        time.sleep(delay)

    async def get_directions(
        self,
        origin: tuple[float, float],
        destination: tuple[float, float],
        departure_time: Optional[datetime] = None
    ) -> Optional[Dict]:
        """
        Get directions between two points

        Args:
            origin: (lat, lon) of origin
            destination: (lat, lon) of destination
            departure_time: Optional datetime for traffic-aware routing

        Returns:
            Dict with duration, distance, and route info
        """
        if not self.page:
            raise RuntimeError("Browser not started. Call start_browser() first")

        origin_str = f"{origin[0]},{origin[1]}"
        dest_str = f"{destination[0]},{destination[1]}"

        # Reset captured data
        self._captured_api_data = None

        # Build URL with departure time if provided
        url = f"https://www.google.com/maps/dir/{origin_str}/{dest_str}"
        if departure_time:
            timestamp = int(departure_time.timestamp())
            url += f"?departure_time={timestamp}"

        logger.debug(f"Navigating to: {url}")

        try:
            # Navigate with extended timeout for dynamic content
            await self.page.goto(url, wait_until="domcontentloaded", timeout=45000)

            # Wait for route panel to appear (multiple indicators)
            await self._wait_for_route_data()

            # Additional wait for traffic data to load
            await asyncio.sleep(2)

            # Try to extract data from page
            result = await self._extract_directions_data()

            if result:
                self.requests_count += 1
                self._random_delay()
                return result

            return None

        except Exception as e:
            logger.error(f"Error getting directions: {e}")
            return None

    async def _extract_directions_data(self) -> Optional[Dict]:
        """
        Extract directions data from page using network interception
        with JavaScript evaluation as fallback

        Returns:
            Dict with duration, distance, duration_in_traffic
        """
        try:
            # Method 1: Try to get data from intercepted network requests
            if hasattr(self, '_captured_api_data') and self._captured_api_data:
                result = self._parse_api_response(self._captured_api_data)
                if result:
                    logger.info("Successfully extracted data from network interception")
                    return result

            # Method 2: JavaScript evaluation to access window objects
            js_result = await self._extract_from_javascript()
            if js_result:
                logger.info("Successfully extracted data from JavaScript objects")
                return js_result

            # Method 3: DOM-based extraction (least reliable)
            dom_result = await self._extract_from_dom()
            if dom_result:
                logger.info("Extracted data from DOM (less reliable)")
                return dom_result

            logger.warning("Could not extract duration data from any method")
            return None

        except Exception as e:
            logger.error(f"Error extracting data: {e}")
            return None

    def _parse_api_response(self, data: dict) -> Optional[Dict]:
        """Parse captured API response for duration data"""
        try:
            # Google Maps API responses vary, check common structures
            routes = data.get('routes', [])
            if not routes:
                # Try nested structure
                if 'data' in data:
                    routes = data['data'].get('routes', [])

            if routes:
                route = routes[0]
                leg = route.get('legs', [{}])[0]

                duration = leg.get('duration', {})
                duration_in_traffic = leg.get('duration_in_traffic', duration)
                distance = leg.get('distance', {})

                if duration_in_traffic and distance:
                    return {
                        "duration": {
                            "text": duration.get('text', ''),
                            "value": duration.get('value', 0)
                        },
                        "distance": {
                            "text": distance.get('text', ''),
                            "value": distance.get('value', 0)
                        },
                        "duration_in_traffic": {
                            "text": duration_in_traffic.get('text', ''),
                            "value": duration_in_traffic.get('value', 0)
                        }
                    }
            return None
        except Exception as e:
            logger.debug(f"Could not parse API response: {e}")
            return None

    async def _extract_from_javascript(self) -> Optional[Dict]:
        """Extract data from Google's internal JavaScript objects"""
        try:
            # Try multiple approaches to access Google's data
            js_code = """
            () => {
                // Try various locations where Google stores route data
                const possibleLocations = [
                    () => window.wiz_progress,
                    () => window.APP_INITIALIZATION_STATE,
                    () => window.wizInitData,
                    () => typeof google !== 'undefined' ? google.maps : null,
                    () => typeof _foot !== 'undefined' ? _foot : null
                ];

                for (const getter of possibleLocations) {
                    try {
                        const data = getter();
                        if (data) {
                            return JSON.stringify(data);
                        }
                    } catch (e) {}
                }

                // Fallback: Try to find data in script tags
                const scripts = Array.from(document.querySelectorAll('script'));
                for (const script of scripts) {
                    const text = script.textContent;
                    if (text && (text.includes('duration_in_traffic') || text.includes('"duration"'))) {
                        // Try to extract JSON from inline script
                        const match = text.match(/\{[\s\S]*"duration"[\s\S]*\}/);
                        if (match) {
                            return match[0];
                        }
                    }
                }

                return null;
            }
            """

            result = await self.page.evaluate(js_code)

            if result:
                import json
                data = json.loads(result)
                return self._parse_api_response(data)

            return None

        except Exception as e:
            logger.debug(f"JavaScript extraction failed: {e}")
            return None

    async def _extract_from_dom(self) -> Optional[Dict]:
        """Extract data from visible DOM elements"""
        try:
            # More specific selectors for Google Maps current UI
            selectors = {
                'duration_text': [
                    'div[role="text"] span:first-child',
                    '.xlkXcd .mDr44d',  # Current GMaps class
                    'div[class*="duration"] span',
                    'span[class*="duration"]'
                ],
                'distance_text': [
                    'div[role="text"] span:nth-child(2)',
                    '.xlkXcd .ivN21e',  # Current GMaps class
                    'div[class*="distance"] span'
                ]
            }

            duration_text = None
            distance_text = None

            for selector in selectors['duration_text']:
                el = await self.page.query_selector(selector)
                if el:
                    duration_text = await el.inner_text()
                    break

            for selector in selectors['distance_text']:
                el = await self.page.query_selector(selector)
                if el:
                    distance_text = await el.inner_text()
                    break

            # Parse text to get values (approximate)
            if duration_text and distance_text:
                duration_val = self._parse_duration_text(duration_text)
                distance_val = self._parse_distance_text(distance_text)

                # If there's traffic info, it often shows as range "20-35 min"
                if '-' in duration_text:
                    duration_val_traffic = self._parse_duration_text(duration_text.split('-')[1].strip())
                else:
                    duration_val_traffic = duration_val

                return {
                    "duration": {
                        "text": duration_text,
                        "value": duration_val
                    },
                    "distance": {
                        "text": distance_text,
                        "value": distance_val
                    },
                    "duration_in_traffic": {
                        "text": duration_text,
                        "value": duration_val_traffic
                    }
                }

            return None

        except Exception as e:
            logger.debug(f"DOM extraction failed: {e}")
            return None

    def _parse_duration_text(self, text: str) -> int:
        """Parse duration text like '25 min' to seconds"""
        try:
            # Handle formats: "25 min", "1 hr 30 min", "1h 30m"
            import re
            total_seconds = 0

            # Extract hours
            hr_match = re.search(r'(\d+)\s*hr?', text, re.IGNORECASE)
            if hr_match:
                total_seconds += int(hr_match.group(1)) * 3600

            # Extract minutes
            min_match = re.search(r'(\d+)\s*min?', text, re.IGNORECASE)
            if min_match:
                total_seconds += int(min_match.group(1)) * 60

            return total_seconds if total_seconds > 0 else 0
        except:
            return 0

    def _parse_distance_text(self, text: str) -> float:
        """Parse distance text like '12.5 km' to meters"""
        try:
            import re
            # Handle formats: "12.5 km", "1.2 km", "500 m"
            match = re.search(r'([\d.]+)\s*(km|m)?', text, re.IGNORECASE)
            if match:
                value = float(match.group(1))
                unit = (match.group(2) or '').lower()
                if unit.startswith('km'):
                    return value * 1000
                return value
            return 0
        except:
            return 0

    async def _wait_for_route_data(self) -> bool:
        """Wait for route data to be loaded on the page"""
        try:
            # Try multiple selectors that indicate route data is ready
            selectors = [
                'div[role="text"]',  # Route info panel
                'div[class*="directions"]',
                'div[class*="route"]',
                '.mDr44d',  # Current GMaps duration class
                '.ivN21e'   # Current GMaps distance class
            ]

            for selector in selectors:
                try:
                    await self.page.wait_for_selector(
                        selector,
                        state="visible",
                        timeout=15000
                    )
                    logger.debug(f"Route data loaded (found: {selector})")
                    return True
                except:
                    continue

            # Fallback: wait for network idle
            await self.page.wait_for_load_state("networkidle", timeout=15000)
            return True

        except Exception as e:
            logger.warning(f"Wait for route data timeout: {e}")
            return True  # Proceed anyway

    async def scrape_routes(
        self,
        routes: List[Dict],
        departure_time: datetime,
        progress_file: Optional[str] = None
    ) -> List[Dict]:
        """
        Scrape multiple routes

        Args:
            routes: List of route dicts with origin_coords and dest_coords
            departure_time: Time for traffic-aware routing
            progress_file: Optional file to save progress

        Returns:
            List of results with scraped data
        """
        results = []
        completed = set()

        # Load progress if exists
        if progress_file:
            try:
                with open(progress_file, "r") as f:
                    progress = json.load(f)
                    completed = set(progress.get("completed", []))
                    results = progress.get("results", [])
                logger.info(f"Loaded progress: {len(completed)} completed")
            except FileNotFoundError:
                pass

        for i, route in enumerate(routes):
            if i in completed:
                continue

            origin = route["origin_coords"]
            dest = route["dest_coords"]

            result = await self.get_directions(origin, dest, departure_time)

            if result:
                results.append({
                    **route,
                    "scraped_data": result,
                    "departure_time": departure_time.isoformat(),
                    "scraped_at": datetime.now().isoformat()
                })
                completed.add(i)

            # Save progress periodically
            if progress_file and len(results) % 50 == 0:
                with open(progress_file, "w") as f:
                    json.dump({
                        "completed": list(completed),
                        "results": results
                    }, f)
                logger.info(f"Saved progress: {len(results)} routes completed")

        return results
