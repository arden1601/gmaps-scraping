"""Scrape Google Maps for travel time data"""

import asyncio
import random
import json
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

    async def start_browser(self):
        """Initialize browser with anti-detection measures"""
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
        logger.info("Browser initialized")

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

        # Build URL with departure time if provided
        url = f"https://www.google.com/maps/dir/{origin_str}/{dest_str}"
        if departure_time:
            timestamp = int(departure_time.timestamp())
            url += f"?departure_time={timestamp}"

        logger.debug(f"Navigating to: {url}")

        try:
            await self.page.goto(url, wait_until="networkidle", timeout=30000)

            # Wait for directions to load
            await asyncio.sleep(3)

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
        Extract directions data from the page

        Returns:
            Dict with duration, distance, duration_in_traffic
        """
        try:
            # Look for duration elements in the page
            duration_selectors = [
                "div[class*='duration']",
                "span[class*='duration']",
                "[data-duration]",
            ]

            for selector in duration_selectors:
                elements = await self.page.query_selector_all(selector)
                if elements:
                    logger.debug(f"Found {len(elements)} duration elements")
                    # Extract data - implementation depends on actual DOM structure
                    return {
                        "duration": {"text": "placeholder", "value": 0},
                        "distance": {"text": "placeholder", "value": 0},
                        "duration_in_traffic": {"text": "placeholder", "value": 0}
                    }

            return None

        except Exception as e:
            logger.error(f"Error extracting data: {e}")
            return None

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
