# Implementation Plan: Real Duration in Traffic Extraction from Google Maps

## Current State Analysis

The current implementation in `/home/yaomoel/Coding/gmaps-scraping/src/gmaps_scraper.py` (lines 155-185) contains placeholder logic:

```python
async def _extract_directions_data(self) -> Optional[Dict]:
    """Extract directions data from the page"""
    try:
        # Look for duration elements in page
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
                # For now, return a placeholder (Lines 175-179)
                return {
                    "duration": {"text": "placeholder", "value": 0},
                    "distance": {"text": "placeholder", "value": 0},
                    "duration_in_traffic": {"text": "placeholder", "value": 0}  # PLACEHOLDER
                }
        return None
```

The data is consumed in `/home/yaomoel/Coding/gmaps-scraping/src/data_processor.py` (line 76):
```python
duration = scraped.get("duration_in_traffic", {}).get("value", 0)
```

## Recommended Approach: Network Request Interception with JavaScript Evaluation Fallback

Based on analysis of Google Maps architecture and available Playwright features, I recommend a **hybrid approach** that prioritizes network interception (most reliable) with JavaScript evaluation as fallback.

### Why This Approach?

1. **Network Interception** (Primary): Google Maps makes API calls that return structured JSON containing both `duration` and `duration_in_traffic` fields. This is the most reliable method as it captures the exact data structure Google uses.

2. **JavaScript Evaluation** (Fallback): Google Maps stores route data in JavaScript objects (typically `window.APP_INITIALIZATION_STATE` or similar). This provides a backup when network requests are encrypted or use WebSocket.

3. **DOM Scraping** (Last Resort): Only for visual verification, not reliable for exact values.

---

## Detailed Implementation Plan

### Phase 1: Add Network Request Interception

**Location:** Modify `start_browser()` method (lines 44-79) and `_extract_directions_data()` method (lines 155-185)

**Changes to `start_browser()`:**
Add request/response interception to capture Google Maps API calls:

```python
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
                        import json
                        data = json.loads(body)
                        self._captured_api_data = data
                        logger.debug(f"Captured API response from {url[:100]}...")
            except Exception as e:
                logger.debug(f"Could not capture response: {e}")

    self.page.on('response', handle_response)

    logger.info("Browser initialized with network interception")
```

**Changes to `_extract_directions_data()`:**
Implement actual extraction logic using captured API data:

```python
async def _extract_directions_data(self) -> Optional[Dict]:
    """
    Extract directions data from the page using network interception
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
```

### Phase 2: Enhanced Waiting Strategy

**Location:** Modify `get_directions()` method (lines 104-153)

Add robust waiting for dynamic content:

```python
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
```

---

## Summary of Changes

### Critical Files for Implementation

1. **`/home/yaomoel/Coding/gmaps-scraping/src/gmaps_scraper.py`** - Core modifications needed
   - `start_browser()`: Add network interception handler
   - `get_directions()`: Enhanced waiting strategy
   - `_extract_directions_data()`: Complete rewrite with multi-method approach
   - Add new methods: `_parse_api_response()`, `_extract_from_javascript()`, `_extract_from_dom()`, `_wait_for_route_data()`, `_ensure_valid_result()`, `_parse_duration_text()`, `_parse_distance_text()`

2. **`/home/yaomoel/Coding/gmaps-scraping/src/data_processor.py`** - Already compatible (line 76 expects format we will provide)

3. **`/home/yaomoel/Coding/gmaps-scraping/config/settings.yaml`** - May need tuning for new timeouts

### Implementation Strategy

The approach uses a **three-tier extraction strategy**:

1. **Network Interception** (Primary): Captures API responses directly from Google's internal calls. Most reliable as it gets the exact data structure Google uses.

2. **JavaScript Evaluation** (Secondary): Accesses Google's internal state objects. Works when network responses are encrypted or use WebSocket.

3. **DOM Parsing** (Tertiary): Extracts visible text from the page UI. Least reliable but provides a fallback.

### Graceful Degradation

When traffic data is not available:
- Falls back to regular `duration` value
- Logs the fallback for debugging
- Ensures data processor always receives valid values

### Verification Steps

To test the implementation:

1. **Manual Testing**: Run a single route query and inspect the output
2. **Comparison Test**: Run same route during peak and off-peak hours to verify traffic data differs
3. **Data Validation**: Ensure `duration_in_traffic.value >= duration.value` (traffic should always be >= normal duration)
4. **Log Analysis**: Check logs for which extraction method succeeded

### Expected Output Format

The returned data structure matches what `data_processor.py` expects:

```python
{
    "duration": {"text": "15 min", "value": 900},
    "distance": {"text": "5.2 km", "value": 5200},
    "duration_in_traffic": {"text": "25 min", "value": 1500}
}
```

This implementation plan provides a robust, multi-layered approach to extracting real traffic data from Google Maps, with graceful fallbacks when primary method fails.
