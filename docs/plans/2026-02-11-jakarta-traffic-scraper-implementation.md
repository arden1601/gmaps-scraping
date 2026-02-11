# Jakarta Traffic Scraper Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a scraper that collects traffic speed data for all roads in Jakarta Utara and Jakarta Barat during peak and off-peak hours, outputting to Shapefile format.

**Architecture:** Extract road network from OpenStreetMap, generate intersection-to-intersection routes, scrape Google Maps for time-aware travel times using Playwright with anti-detection, merge data and export as Shapefile.

**Tech Stack:** Python, OSMnx (OSM), NetworkX (routing), Playwright (scraping), GeoPandas (spatial), APScheduler (scheduling)

---

## Task 1: Project Setup and Configuration

**Files:**
- Create: `requirements.txt`
- Create: `config/areas.yaml`
- Create: `config/settings.yaml`
- Create: `src/__init__.py`

**Step 1: Create requirements.txt**

```txt
# OSM and geospatial
osmnx>=1.9.0
overpy>=0.5
networkx>=3.2
geopandas>=0.14.0
shapely>=2.0.0

# Scraping
playwright>=1.40.0
scrapy-rotating-proxies>=0.6.0

# Scheduling and storage
apscheduler>=3.10.0

# Configuration and utilities
pydantic>=2.5.0
pyyaml>=6.0
python-dotenv>=1.0.0
```

**Step 2: Create area configuration file**

Create `config/areas.yaml`:

```yaml
jakarta:
  # Jakarta Utara (North Jakarta)
  jakarta_utara:
    name: "Jakarta Utara"
    bounds:
      min_lat: -6.2250
      max_lat: -6.1000
      min_lon: 106.7000
      max_lon: 106.8500

  # Jakarta Barat (West Jakarta)
  jakarta_barat:
    name: "Jakarta Barat"
    bounds:
      min_lat: -6.2500
      max_lat: -6.1250
      min_lon: 106.7000
      max_lon: 106.8000
```

**Step 3: Create scraper settings configuration**

Create `config/settings.yaml`:

```yaml
scraping:
  # Time windows for data collection
  time_periods:
    peak_am:
      start: "07:00"
      end: "09:00"
    off_peak:
      start: "10:00"
      end: "17:00"
    peak_pm:
      start: "17:00"
      end: "20:00"

  # Anti-detection settings
  delays:
    min_seconds: 2
    max_seconds: 10

  workers:
    max_concurrent: 2

  # Proxy rotation
  proxies:
    rotate_after_requests: 50
    session_rotation: 200

  # Checkpointing
  checkpoint_interval: 50

  # Retry settings
  max_retries: 3
  backoff_multiplier: 2

output:
  projection: "EPSG:3857"  # Web Mercator (or EPSG:32748 for UTM Zone 48S)
  output_dir: "data/output"
```

**Step 4: Create package init file**

Create `src/__init__.py`:

```python
"""Jakarta Traffic Scraper

Extracts road network data from OpenStreetMap and scrapes Google Maps
for traffic speed data during peak and off-peak hours.
"""

__version__ = "0.1.0"
```

**Step 5: Install dependencies**

Run: `pip install -r requirements.txt`

**Step 6: Install Playwright browsers**

Run: `playwright install chromium`

**Step 7: Commit**

```bash
git add requirements.txt config/ src/__init__.py
git commit -m "feat: add project structure and configuration"
```

---

## Task 2: OSM Network Extractor

**Files:**
- Create: `src/osm_extractor.py`
- Create: `tests/test_osm_extractor.py`

**Step 1: Write the failing test**

Create `tests/test_osm_extractor.py`:

```python
import pytest
from src.osm_extractor import OSMExtractor


def test_extractor_initialization():
    """Test that OSMExtractor can be initialized with area bounds"""
    bounds = {
        "min_lat": -6.2,
        "max_lat": -6.1,
        "min_lon": 106.75,
        "max_lon": 106.85
    }
    extractor = OSMExtractor("test_area", bounds)

    assert extractor.name == "test_area"
    assert extractor.bounds == bounds


def test_download_road_network(mocker):
    """Test downloading road network from OSM"""
    bounds = {
        "min_lat": -6.2,
        "max_lat": -6.1,
        "min_lon": 106.75,
        "max_lon": 106.85
    }
    extractor = OSMExtractor("test_area", bounds)

    # Mock osmnx.graph_from_bbox
    mock_graph = mocker.patch("src.osm_extractor.osmnx.graph_from_bbox")

    extractor.download_road_network()

    mock_graph.assert_called_once()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_osm_extractor.py -v`
Expected: ImportError/ModuleNotFoundError (src.osm_extractor not defined)

**Step 3: Write minimal implementation**

Create `src/osm_extractor.py`:

```python
"""Extract road network data from OpenStreetMap"""

import osmnx as ox
import geopandas as gpd
import networkx as nx
from typing import Dict, Any
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class OSMExtractor:
    """Extract road network from OpenStreetMap for a given area"""

    def __init__(self, name: str, bounds: Dict[str, float]):
        """
        Initialize OSM extractor

        Args:
            name: Area name
            bounds: Dict with min_lat, max_lat, min_lon, max_lon
        """
        self.name = name
        self.bounds = bounds
        self.graph = None
        self.nodes_gdf = None
        self.edges_gdf = None

    def download_road_network(self) -> nx.MultiDiGraph:
        """
        Download road network from OSM for the defined bounds

        Returns:
            NetworkX MultiDiGraph of the road network
        """
        logger.info(f"Downloading OSM road network for {self.name}")

        # Define bounding box
        north = self.bounds["max_lat"]
        south = self.bounds["min_lat"]
        east = self.bounds["max_lon"]
        west = self.bounds["min_lon"]

        # Download drive network
        self.graph = ox.graph_from_bbox(
            north, south, east, west,
            network_type="drive",
            simplify=True
        )

        logger.info(f"Downloaded {len(self.graph.nodes)} nodes, {len(self.graph.edges)} edges")

        # Convert to GeoDataFrames
        self.nodes_gdf, self.edges_gdf = ox.graph_to_gdfs(
            self.graph,
            nodes=True,
            edges=True
        )

        return self.graph

    def get_road_segments(self) -> gpd.GeoDataFrame:
        """
        Get road segments with attributes

        Returns:
            GeoDataFrame with road segment geometries and attributes
        """
        if self.edges_gdf is None:
            raise ValueError("Must call download_road_network() first")

        # Select relevant columns
        relevant_cols = [
            "osmid", "name", "highway", "oneway",
            "maxspeed", "length", "geometry"
        ]

        # Filter to available columns
        available_cols = [c for c in relevant_cols if c in self.edges_gdf.columns]

        return self.edges_gdf[available_cols].copy()

    def get_intersections(self) -> gpd.GeoDataFrame:
        """
        Get intersection points (nodes with degree >= 3)

        Returns:
            GeoDataFrame with intersection points
        """
        if self.nodes_gdf is None:
            raise ValueError("Must call download_road_network() first")

        # Calculate node degree
        degrees = dict(self.graph.degree())

        # Add degree to nodes GeoDataFrame
        self.nodes_gdf["degree"] = self.nodes_gdf.index.map(degrees)

        # Filter for intersections (3+ roads meeting)
        intersections = self.nodes_gdf[self.nodes_gdf["degree"] >= 3].copy()

        logger.info(f"Found {len(intersections)} intersections")

        return intersections

    def export_geojson(self, output_path: str):
        """
        Export road network to GeoJSON

        Args:
            output_path: Path to output GeoJSON file
        """
        if self.edges_gdf is None:
            raise ValueError("Must call download_road_network() first")

        self.edges_gdf.to_file(output_path, driver="GeoJSON")
        logger.info(f"Exported road network to {output_path}")
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_osm_extractor.py -v`
Expected: PASS (may need to adjust for osmnx mocking)

**Step 5: Commit**

```bash
git add src/osm_extractor.py tests/test_osm_extractor.py
git commit -m "feat: add OSM road network extractor"
```

---

## Task 3: Route Generator

**Files:**
- Create: `src/route_generator.py`
- Create: `tests/test_route_generator.py`

**Step 1: Write the failing test**

Create `tests/test_route_generator.py`:

```python
import pytest
from src.route_generator import RouteGenerator


def test_route_generator_initialization():
    """Test RouteGenerator initialization with graph"""
    graph = {"nodes": [], "edges": []}  # Mock graph
    generator = RouteGenerator(graph)

    assert generator.graph == graph


def test_generate_route_queue(mocker):
    """Test generating route queue from intersections"""
    graph = mocker.MagicMock()
    graph.nodes = [(0, {"y": -6.15, "x": 106.8}), (1, {"y": -6.16, "x": 106.81})]

    generator = RouteGenerator(graph)
    queue = generator.generate_route_queue()

    assert isinstance(queue, list)
    assert len(queue) > 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_route_generator.py -v`
Expected: ModuleNotFoundError

**Step 3: Write minimal implementation**

Create `src/route_generator.py`:

```python
"""Generate route queries from road network graph"""

import networkx as nx
from typing import List, Dict, Tuple
import logging

logger = logging.getLogger(__name__)


class RouteGenerator:
    """Generate route queries from road network intersections"""

    def __init__(self, graph: nx.MultiDiGraph, max_routes: int = None):
        """
        Initialize route generator

        Args:
            graph: NetworkX graph of road network
            max_routes: Maximum number of routes to generate (None = all)
        """
        self.graph = graph
        self.max_routes = max_routes

    def get_intersections(self) -> List[Tuple[int, Dict]]:
        """
        Get intersection nodes (degree >= 3)

        Returns:
            List of (node_id, attributes) tuples
        """
        intersections = []
        degrees = dict(self.graph.degree())

        for node, attrs in self.graph.nodes(data=True):
            if degrees[node] >= 3:
                intersections.append((node, attrs))

        logger.info(f"Found {len(intersections)} intersection nodes")
        return intersections

    def generate_route_queue(self) -> List[Dict]:
        """
        Generate origin-destination route queries

        Returns:
            List of route dicts with origin/destination coordinates
        """
        intersections = self.get_intersections()

        route_queue = []

        # Generate routes between adjacent intersections
        for i, (node1, attrs1) in enumerate(intersections):
            if self.max_routes and len(route_queue) >= self.max_routes:
                break

            # Find nearby intersections (within graph distance)
            for j, (node2, attrs2) in enumerate(intersections[i+1:], start=i+1):
                if self.max_routes and len(route_queue) >= self.max_routes:
                    break

                # Try to find shortest path between nodes
                try:
                    path = nx.shortest_path(
                        self.graph,
                        source=node1,
                        target=node2,
                        weight="length"
                    )

                    if len(path) > 1:  # Valid path exists
                        route_queue.append({
                            "origin_node": node1,
                            "dest_node": node2,
                            "origin_coords": (attrs1["y"], attrs1["x"]),  # lat, lon
                            "dest_coords": (attrs2["y"], attrs2["x"]),
                            "path": path
                        })

                except nx.NetworkXNoPath:
                    continue

        logger.info(f"Generated {len(route_queue)} route queries")
        return route_queue

    def export_route_queue(self, route_queue: List[Dict], output_path: str):
        """
        Export route queue to JSON

        Args:
            route_queue: List of route dictionaries
            output_path: Path to output JSON file
        """
        import json

        with open(output_path, "w") as f:
            json.dump(route_queue, f, indent=2)

        logger.info(f"Exported {len(route_queue)} routes to {output_path}")
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_route_generator.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/route_generator.py tests/test_route_generator.py
git commit -m "feat: add route generator from road network"
```

---

## Task 4: Google Maps Scraper - Browser Setup

**Files:**
- Create: `src/gmaps_scraper.py`
- Create: `tests/test_gmaps_scraper.py`

**Step 1: Write the failing test**

Create `tests/test_gmaps_scraper.py`:

```python
import pytest
from src.gmaps_scraper import GMapsScraper


@pytest.mark.asyncio
async def test_scraper_initialization():
    """Test scraper initialization"""
    scraper = GMapsScraper(headless=True)

    assert scraper.headless is True
    assert scraper.browser is None


@pytest.mark.asyncio
async def test_browser_start(mocker):
    """Test browser initialization"""
    scraper = GMapsScraper(headless=True)

    await scraper.start_browser()
    assert scraper.browser is not None

    await scraper.stop_browser()
    assert scraper.browser is None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_gmaps_scraper.py -v`
Expected: ModuleNotFoundError

**Step 3: Write minimal implementation**

Create `src/gmaps_scraper.py`:

```python
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
            # This is a simplified version - actual selectors may vary
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
                    # For now, return a placeholder
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
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_gmaps_scraper.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/gmaps_scraper.py tests/test_gmaps_scraper.py
git commit -m "feat: add Google Maps scraper with Playwright"
```

---

## Task 5: Data Processor

**Files:**
- Create: `src/data_processor.py`
- Create: `tests/test_data_processor.py`

**Step 1: Write the failing test**

Create `tests/test_data_processor.py`:

```python
import pytest
from src.data_processor import DataProcessor


def test_calculate_speed():
    """Test speed calculation from duration and distance"""
    processor = DataProcessor()

    # 10 km in 20 minutes = 30 km/h
    duration_seconds = 20 * 60  # 20 minutes
    distance_meters = 10000  # 10 km
    speed = processor.calculate_speed(duration_seconds, distance_meters)

    assert speed == 30.0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_data_processor.py -v`
Expected: ModuleNotFoundError

**Step 3: Write minimal implementation**

Create `src/data_processor.py`:

```python
"""Process scraped data and merge with OSM attributes"""

import json
import pandas as pd
import geopandas as gpd
from typing import List, Dict, Optional
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class DataProcessor:
    """Process scraped traffic data and merge with OSM road attributes"""

    @staticmethod
    def calculate_speed(duration_seconds: int, distance_meters: float) -> float:
        """
        Calculate speed in km/h from duration and distance

        Args:
            duration_seconds: Travel time in seconds
            distance_meters: Distance in meters

        Returns:
            Speed in km/h
        """
        if duration_seconds <= 0 or distance_meters <= 0:
            return 0.0

        speed_mps = distance_meters / duration_seconds
        speed_kmh = speed_mps * 3.6
        return round(speed_kmh, 2)

    def load_scraped_data(self, input_path: str) -> List[Dict]:
        """
        Load scraped JSON data

        Args:
            input_path: Path to JSON file

        Returns:
            List of scraped route results
        """
        with open(input_path, "r") as f:
            data = json.load(f)

        logger.info(f"Loaded {len(data)} scraped routes")
        return data

    def aggregate_speeds_by_time_period(
        self,
        scraped_data: List[Dict],
        time_period: str
    ) -> pd.DataFrame:
        """
        Aggregate speeds by time period

        Args:
            scraped_data: List of scraped results
            time_period: 'peak_am', 'off_peak', or 'peak_pm'

        Returns:
            DataFrame with aggregated speeds by segment
        """
        # Filter by time period
        period_data = [
            d for d in scraped_data
            if d.get("time_period") == time_period
        ]

        # Group by road segment and calculate average speed
        records = []
        for item in period_data:
            scraped = item.get("scraped_data", {})
            duration = scraped.get("duration_in_traffic", {}).get("value", 0)
            distance = scraped.get("distance", {}).get("value", 0)

            if duration and distance:
                speed = self.calculate_speed(duration, distance)
                records.append({
                    "road_id": item.get("road_id"),
                    "speed": speed,
                    "time_period": time_period
                })

        df = pd.DataFrame(records)

        if not df.empty:
            # Calculate average speed per road segment
            avg_speeds = df.groupby("road_id")["speed"].mean().reset_index()
            avg_speeds.columns = ["road_id", f"speed_{time_period}"]
            return avg_speeds

        return pd.DataFrame()

    def merge_with_osm(
        self,
        osm_gdf: gpd.GeoDataFrame,
        scraped_dfs: Dict[str, pd.DataFrame]
    ) -> gpd.GeoDataFrame:
        """
        Merge scraped speed data with OSM road attributes

        Args:
            osm_gdf: GeoDataFrame with OSM road segments
            scraped_dfs: Dict of DataFrames by time period

        Returns:
            Merged GeoDataFrame
        """
        result_gdf = osm_gdf.copy()

        # Add index as road_id for merging
        result_gdf["road_id"] = result_gdf.index.astype(str)

        # Merge each time period's speeds
        for period, df in scraped_dfs.items():
            result_gdf = result_gdf.merge(
                df,
                on="road_id",
                how="left"
            )

        return result_gdf

    def validate_data(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """
        Validate and flag data quality issues

        Args:
            gdf: Input GeoDataFrame

        Returns:
            GeoDataFrame with validation flags
        """
        # Flag speeds outside reasonable range
        speed_cols = [c for c in gdf.columns if c.startswith("speed_")]

        for col in speed_cols:
            gdf.loc[gdf[col] < 5, f"{col}_flag"] = "too_low"
            gdf.loc[gdf[col] > 120, f"{col}_flag"] = "too_high"

        # Peak should be slower than off-peak
        if "speed_peak_am" in gdf.columns and "speed_off_peak" in gdf.columns:
            mask = gdf["speed_peak_am"] > gdf["speed_off_peak"]
            gdf.loc[mask, "data_quality"] = "suspicious"

        return gdf
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_data_processor.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/data_processor.py tests/test_data_processor.py
git commit -m "feat: add data processor for speed calculations"
```

---

## Task 6: Shapefile Exporter

**Files:**
- Create: `src/exporter.py`
- Create: `tests/test_exporter.py`

**Step 1: Write the failing test**

Create `tests/test_exporter.py`:

```python
import pytest
from src.exporter import ShapefileExporter


def test_exporter_initialization(tmp_path):
    """Test exporter initialization"""
    exporter = ShapefileExporter(output_dir=str(tmp_path))

    assert exporter.output_dir == tmp_path
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_exporter.py -v`
Expected: ModuleNotFoundError

**Step 3: Write minimal implementation**

Create `src/exporter.py`:

```python
"""Export processed data to Shapefile format"""

import geopandas as gpd
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class ShapefileExporter:
    """Export GeoDataFrame to Shapefile"""

    def __init__(self, output_dir: str = "data/output"):
        """
        Initialize exporter

        Args:
            output_dir: Directory for output files
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def export(
        self,
        gdf: gpd.GeoDataFrame,
        filename: str,
        crs: Optional[str] = None
    ) -> str:
        """
        Export GeoDataFrame to Shapefile

        Args:
            gdf: GeoDataFrame to export
            filename: Output filename (without extension)
            crs: Optional CRS to reproject to (e.g., "EPSG:3857")

        Returns:
            Path to exported file
        """
        # Reproject if requested
        if crs:
            gdf = gdf.to_crs(crs)

        # Build output path
        output_path = self.output_dir / f"{filename}.shp"

        # Export to Shapefile
        gdf.to_file(output_path, driver="ESRI Shapefile")

        logger.info(f"Exported {len(gdf)} records to {output_path}")

        return str(output_path)

    def get_layer_schema(self, gdf: gpd.GeoDataFrame) -> dict:
        """
        Get schema/field information for the GeoDataFrame

        Args:
            gdf: Input GeoDataFrame

        Returns:
            Dict with field names and types
        """
        schema = {
            "geometry_type": gdf.geometry.geom_type.iloc[0] if len(gdf) > 0 else None,
            "crs": str(gdf.crs),
            "fields": []
        }

        for col in gdf.columns:
            if col != "geometry":
                dtype = str(gdf[col].dtype)
                schema["fields"].append({
                    "name": col,
                    "type": dtype
                })

        return schema
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_exporter.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/exporter.py tests/test_exporter.py
git commit -m "feat: add Shapefile exporter"
```

---

## Task 7: Main Pipeline Orchestration

**Files:**
- Create: `src/main.py`
- Create: `tests/test_main.py`

**Step 1: Write the failing test**

Create `tests/test_main.py`:

```python
import pytest
from src.main import TrafficScraperPipeline


def test_pipeline_initialization():
    """Test pipeline initialization"""
    pipeline = TrafficScraperPipeline()

    assert pipeline is not None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_main.py -v`
Expected: ModuleNotFoundError

**Step 3: Write minimal implementation**

Create `src/main.py`:

```python
"""Main pipeline orchestration for Jakarta traffic scraper"""

import asyncio
import yaml
from pathlib import Path
from datetime import datetime, time
from typing import Dict, List

from src.osm_extractor import OSMExtractor
from src.route_generator import RouteGenerator
from src.gmaps_scraper import GMapsScraper
from src.data_processor import DataProcessor
from src.exporter import ShapefileExporter
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class TrafficScraperPipeline:
    """Main pipeline for traffic data collection"""

    def __init__(self, config_path: str = "config/settings.yaml"):
        """
        Initialize pipeline

        Args:
            config_path: Path to settings configuration file
        """
        with open(config_path, "r") as f:
            self.config = yaml.safe_load(f)

        self.extractor = None
        self.route_generator = None
        self.scraper = None
        self.processor = DataProcessor()
        self.exporter = ShapefileExporter(
            self.config.get("output", {}).get("output_dir", "data/output")
        )

    def extract_road_networks(self, areas_config: Dict) -> Dict[str, gpd.GeoDataFrame]:
        """
        Extract road networks for all defined areas

        Args:
            areas_config: Dict of area configurations

        Returns:
            Dict of area name to road network GeoDataFrame
        """
        networks = {}

        for area_id, area_config in areas_config.items():
            logger.info(f"Extracting road network for {area_id}")

            self.extractor = OSMExtractor(
                area_config["name"],
                area_config["bounds"]
            )
            self.extractor.download_road_network()

            # Get road segments
            segments = self.extractor.get_road_segments()
            networks[area_id] = segments

            # Export raw GeoJSON
            self.exporter.export(
                segments,
                f"{area_id}_road_network_raw",
                crs=self.config.get("output", {}).get("projection")
            )

        return networks

    def generate_routes(self, networks: Dict[str, gpd.GeoDataFrame]) -> List[Dict]:
        """
        Generate route queries from road networks

        Args:
            networks: Dict of road network GeoDataFrames

        Returns:
            List of route queries
        """
        all_routes = []

        for area_id, network in networks.items():
            logger.info(f"Generating routes for {area_id}")

            # Convert GeoDataFrame edges back to graph for routing
            import osmnx as ox
            graph = ox.graph_from_gdfs(network, network.edges)

            self.route_generator = RouteGenerator(graph)
            routes = self.route_generator.generate_route_queue()

            all_routes.extend(routes)

            logger.info(f"Generated {len(routes)} routes for {area_id}")

        return all_routes

    async def scrape_time_period(
        self,
        routes: List[Dict],
        time_period: str,
        date: datetime
    ) -> List[Dict]:
        """
        Scrape routes for a specific time period

        Args:
            routes: List of route queries
            time_period: 'peak_am', 'off_peak', 'peak_pm'
            date: Date for scraping

        Returns:
            List of scraped results
        """
        time_config = self.config["scraping"]["time_periods"][time_period]
        start_time = time.fromisoformat(time_config["start"])
        end_time = time.fromisoformat(time_config["end"])

        # Create departure time in the middle of the period
        departure_time = datetime.combine(date.date(), start_time)

        logger.info(f"Scraping {len(routes)} routes for {time_period} at {departure_time}")

        self.scraper = GMapsScraper(
            headless=True,
            min_delay=self.config["scraping"]["delays"]["min_seconds"],
            max_delay=self.config["scraping"]["delays"]["max_seconds"]
        )

        await self.scraper.start_browser()

        try:
            results = await self.scraper.scrape_routes(
                routes,
                departure_time,
                progress_file=f"data/raw/{time_period}_progress.json"
            )

            # Add time period to results
            for result in results:
                result["time_period"] = time_period

            # Save raw results
            import json
            with open(f"data/raw/{time_period}_results.json", "w") as f:
                json.dump(results, f, indent=2)

            return results

        finally:
            await self.scraper.stop_browser()

    def process_and_export(
        self,
        networks: Dict[str, gpd.GeoDataFrame],
        scraped_data: List[Dict]
    ):
        """
        Process scraped data and export to Shapefile

        Args:
            networks: Dict of road network GeoDataFrames
            scraped_data: List of scraped results
        """
        # Combine all networks
        import geopandas as gpd
        combined_network = gpd.GeoDataFrame(
            pd.concat([n for n in networks.values()], ignore_index=True)
        )

        # Process by time period
        time_periods = ["peak_am", "off_peak", "peak_pm"]
        period_dfs = {}

        for period in time_periods:
            df = self.processor.aggregate_speeds_by_time_period(scraped_data, period)
            period_dfs[period] = df

        # Merge with OSM
        result_gdf = self.processor.merge_with_osm(combined_network, period_dfs)

        # Validate
        result_gdf = self.processor.validate_data(result_gdf)

        # Export
        output_path = self.exporter.export(
            result_gdf,
            f"jakarta_traffic_{datetime.now().strftime('%Y%m%d')}",
            crs=self.config.get("output", {}).get("projection")
        )

        logger.info(f"Exported final Shapefile to {output_path}")

    async def run(self, areas_config: Dict, scrape_date: datetime = None):
        """
        Run full pipeline

        Args:
            areas_config: Dict of area configurations
            scrape_date: Date for scraping (default: today)
        """
        if scrape_date is None:
            scrape_date = datetime.now()

        logger.info(f"Starting Jakarta traffic scraper for {scrape_date}")

        # Step 1: Extract road networks
        networks = self.extract_road_networks(areas_config)

        # Step 2: Generate routes
        routes = self.generate_routes(networks)

        # Step 3: Scrape each time period
        all_scraped = []
        for period in ["peak_am", "off_peak", "peak_pm"]:
            results = await self.scrape_time_period(routes, period, scrape_date)
            all_scraped.extend(results)

        # Step 4: Process and export
        self.process_and_export(networks, all_scraped)

        logger.info("Pipeline complete")


async def main():
    """Main entry point"""
    # Load area configuration
    with open("config/areas.yaml", "r") as f:
        areas_config = yaml.safe_load(f)["jakarta"]

    pipeline = TrafficScraperPipeline()
    await pipeline.run(areas_config)


if __name__ == "__main__":
    asyncio.run(main())
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_main.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/main.py tests/test_main.py
git commit -m "feat: add main pipeline orchestration"
```

---

## Task 8: Documentation and README

**Files:**
- Create: `README.md`
- Create: `data/raw/.gitkeep`
- Create: `data/processed/.gitkeep`
- Create: `data/output/.gitkeep`

**Step 1: Create README**

Create `README.md`:

```markdown
# Jakarta Traffic Scraper

Extracts road network data from OpenStreetMap and scrapes Google Maps for traffic speed data during peak and off-peak hours.

## Coverage

- **Areas:** Jakarta Utara and Jakarta Barat, Indonesia
- **Time periods:**
  - Morning peak: 07:00-09:00
  - Off-peak: 10:00-17:00
  - Evening peak: 17:00-20:00

## Installation

```bash
pip install -r requirements.txt
playwright install chromium
```

## Usage

### Full Pipeline

```python
python -m src.main
```

### Individual Components

```python
from src.osm_extractor import OSMExtractor
from src.gmaps_scraper import GMapsScraper
```

## Output

Shapefile with attributes:
- `road_id`: OSM way identifier
- `road_name`: Street name
- `road_type`: Highway classification
- `oneway`: One-way flag
- `speed_peak_am`: Average speed 07:00-09:00
- `speed_off_peak`: Average speed 10:00-17:00
- `speed_peak_pm`: Average speed 17:00-20:00
- `speed_limit`: Posted speed limit
- `geometry`: LineString geometry

## Configuration

Edit `config/areas.yaml` for area boundaries and `config/settings.yaml` for scraping parameters.
```

**Step 2: Create data directories**

```bash
mkdir -p data/raw data/processed data/output
touch data/raw/.gitkeep data/processed/.gitkeep data/output/.gitkeep
```

**Step 3: Commit**

```bash
git add README.md data/
git commit -m "docs: add README and data directory structure"
```

---

## Task 9: Final Integration Tests

**Files:**
- Modify: `tests/test_integration.py`

**Step 1: Create integration test**

Create `tests/test_integration.py`:

```python
import pytest
import asyncio
from src.main import TrafficScraperPipeline


@pytest.mark.integration
async def test_full_pipeline_small_area():
    """Test full pipeline on a small area"""
    areas_config = {
        "test_area": {
            "name": "Test Area",
            "bounds": {
                "min_lat": -6.2,
                "max_lat": -6.18,
                "min_lon": 106.8,
                "max_lon": 106.82
            }
        }
    }

    pipeline = TrafficScraperPipeline()

    # Test road network extraction
    networks = pipeline.extract_road_networks(areas_config)
    assert len(networks) > 0

    # Test route generation (limit to 10 routes)
    routes = pipeline.generate_routes(networks)
    assert len(routes) > 0

    # Note: Skipping actual scraping in unit tests
    # In production, this would call:
    # results = await pipeline.scrape_time_period(routes[:10], "off_peak", datetime.now())
```

**Step 2: Run test**

Run: `pytest tests/test_integration.py -v -m integration`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: add integration test for full pipeline"
```

---

## Completion Checklist

- [x] Project structure and configuration
- [x] OSM road network extractor
- [x] Route generator from intersections
- [x] Google Maps scraper with Playwright
- [x] Data processor for speed calculations
- [x] Shapefile exporter
- [x] Main pipeline orchestration
- [x] Documentation and README
- [x] Integration tests

## Running the Scraper

```bash
# Install dependencies
pip install -r requirements.txt
playwright install chromium

# Run full pipeline
python -m src.main
```

## Notes

- Scraping should be done during the actual time periods for accurate traffic data
- Use residential proxies to avoid IP blocking
- Progress is saved every 50 routes for resumability
- Adjust `config/settings.yaml` for delays and worker counts
