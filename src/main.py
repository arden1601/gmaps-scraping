"""Main pipeline orchestration for Jakarta traffic scraper"""

import asyncio
import yaml
from pathlib import Path
from datetime import datetime, time
from typing import Dict, List
import pandas as pd
import geopandas as gpd

from src.osm_extractor import OSMExtractor
from src.route_generator import RouteGenerator
from src.gmaps_scraper import GMapsScraper
from src.data_processor import DataProcessor
from src.exporter import ShapefileExporter
from src.hospital_route_generator import HospitalRouteGenerator
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
            graph = self.extractor.download_road_network()

            # Get road segments for export
            segments = self.extractor.get_road_segments()
            # Store both graph and segments
            networks[area_id] = {"graph": graph, "segments": segments}

            # Export raw GeoJSON
            self.exporter.export(
                segments,
                f"{area_id}_road_network_raw",
                crs=self.config.get("output", {}).get("projection")
            )

        return networks

    def generate_routes(self, networks: Dict[str, Dict]) -> List[Dict]:
        """
        Generate route queries from road networks

        Args:
            networks: Dict with "graph" and "segments" keys

        Returns:
            List of route queries
        """
        all_routes = []

        for area_id, data in networks.items():
            logger.info(f"Generating routes for {area_id}")

            # Use the stored graph directly
            graph = data["graph"]

            # Limit routes for performance (default: 5000 per area)
            max_routes = self.config.get("scraping", {}).get("max_routes_per_area", 5000)

            self.route_generator = RouteGenerator(graph, max_routes=max_routes)
            routes = self.route_generator.generate_route_queue()

            all_routes.extend(routes)

            logger.info(f"Generated {len(routes)} routes for {area_id}")

        return all_routes

    def generate_hospital_routes(self, networks: Dict[str, Dict]) -> List[Dict]:
        """
        Generate routes from random origins to hospitals using HospitalRouteGenerator.

        Args:
            networks: Dict with "graph" and "segments" keys

        Returns:
            List of hospital route queries
        """
        hosp_cfg = self.config.get("hospital_mode", {})
        csv_path = hosp_cfg.get("csv_path", "config/RS_Puskesmas.csv")
        origins_per_hospital = hosp_cfg.get("origins_per_hospital", 5)
        min_distance_km = hosp_cfg.get("min_distance_km", 1.0)
        geocode_cache = hosp_cfg.get("geocode_cache", "cache/kelurahan_cache.json")
        max_routes = self.config.get("scraping", {}).get("max_routes_per_area", None)

        all_routes = []
        for area_id, data in networks.items():
            logger.info(f"Generating hospital routes for {area_id}")
            graph = data["graph"]

            gen = HospitalRouteGenerator(
                graph=graph,
                csv_path=csv_path,
                origins_per_hospital=origins_per_hospital,
                min_distance_km=min_distance_km,
                max_routes=max_routes,
                geocode_cache_path=geocode_cache,
            )
            routes = gen.generate_route_queue()
            all_routes.extend(routes)
            logger.info(f"Generated {len(routes)} hospital routes for {area_id}")

        return all_routes

    async def scrape_time_period(
        self,
        routes: List[Dict],
        time_period: str,
        date: datetime,
        time_limit_seconds: int = None
    ) -> List[Dict]:
        """
        Scrape routes for a specific time period

        Args:
            routes: List of route queries
            time_period: 'peak_am', 'off_peak', 'peak_pm'
            date: Date for scraping
            time_limit_seconds: Optional max duration in seconds

        Returns:
            List of scraped results
        """
        time_config = self.config["scraping"]["time_periods"][time_period]
        start_time = time.fromisoformat(time_config["start"])
        end_time = time.fromisoformat(time_config["end"])

        # Create departure time in middle of period
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
                progress_file=f"data/raw/{time_period}_progress.json",
                time_limit_seconds=time_limit_seconds
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
        networks: Dict[str, Dict],
        scraped_data: List[Dict]
    ):
        """
        Process scraped data and export to Shapefile

        Args:
            networks: Dict with "graph" and "segments" keys
            scraped_data: List of scraped results
        """
        # Combine all segments from networks
        import geopandas as gpd
        combined_network = gpd.GeoDataFrame(
            pd.concat([n["segments"] for n in networks.values()], ignore_index=True)
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

    async def run(
        self,
        areas_config: Dict,
        scrape_date: datetime = None,
        time_limit_seconds: int = None,
        periods: List[str] = None,
        mode: str = "road",
    ):
        """
        Run full pipeline

        Args:
            areas_config: Dict of area configurations
            scrape_date: Date for scraping (default: today)
            time_limit_seconds: Optional max scraping duration per period
            periods: List of time periods to scrape (default: all)
            mode: 'road' (intersection pairs) or 'hospital' (origins → hospitals)
        """
        if scrape_date is None:
            scrape_date = datetime.now()
        if periods is None:
            periods = ["peak_am", "off_peak", "peak_pm"]

        logger.info(f"Starting Jakarta traffic scraper for {scrape_date} (mode={mode})")
        if time_limit_seconds:
            logger.info(f"Time limit: {time_limit_seconds}s per period")
        logger.info(f"Time periods: {periods}")

        # Step 1: Extract road networks
        networks = self.extract_road_networks(areas_config)

        # Step 2: Generate routes (depends on mode)
        if mode == "hospital":
            routes = self.generate_hospital_routes(networks)
        else:
            routes = self.generate_routes(networks)

        # Step 3: Scrape each time period
        all_scraped = []
        for period in periods:
            results = await self.scrape_time_period(
                routes, period, scrape_date,
                time_limit_seconds=time_limit_seconds
            )
            all_scraped.extend(results)

        # Step 4: Process and export (only if we have data)
        if all_scraped:
            if mode == "hospital":
                # Hospital mode: save raw JSON only; use process_hospital_shp.py for Shapefile
                logger.info("Hospital mode: raw results saved. Run scripts/process_hospital_shp.py to generate Shapefile.")
            else:
                self.process_and_export(networks, all_scraped)
        else:
            logger.warning("No data scraped, skipping export")

        # Summary
        logger.info(f"\n{'='*50}")
        logger.info(f"Pipeline complete! (mode={mode})")
        logger.info(f"Total routes scraped: {len(all_scraped)}")
        for period in periods:
            period_count = sum(1 for r in all_scraped if r.get('time_period') == period)
            logger.info(f"  {period}: {period_count} routes")
        logger.info(f"Data saved to: data/raw/")
        logger.info(f"{'='*50}")


async def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="Jakarta Traffic Scraper")
    parser.add_argument(
        "--duration", type=str, default=None,
        help="Max scraping duration, e.g. '5m', '30m', '1h', '24h'. Default: no limit (run all routes)"
    )
    parser.add_argument(
        "--routes", type=int, default=None,
        help="Override max routes per area (default: from config, usually 100)"
    )
    parser.add_argument(
        "--period", type=str, default=None,
        choices=["peak_am", "off_peak", "peak_pm"],
        help="Scrape only a specific time period. Default: all three periods"
    )
    parser.add_argument(
        "--mode", type=str, default="road",
        choices=["road", "hospital"],
        help="Routing mode: 'road' (intersection pairs) or 'hospital' (random origins → hospitals)"
    )
    args = parser.parse_args()

    # Parse duration string to seconds
    time_limit = None
    if args.duration:
        time_limit = _parse_duration_arg(args.duration)
        logger.info(f"Time limit set to {time_limit} seconds ({args.duration})")

    # Load area configuration
    with open("config/areas.yaml", "r") as f:
        areas_config = yaml.safe_load(f)["jakarta"]

    pipeline = TrafficScraperPipeline()

    # Override max routes if specified
    if args.routes:
        pipeline.config.setdefault("scraping", {})["max_routes_per_area"] = args.routes

    # Override time periods if specified
    periods = ["peak_am", "off_peak", "peak_pm"]
    if args.period:
        periods = [args.period]

    await pipeline.run(
        areas_config,
        time_limit_seconds=time_limit,
        periods=periods,
        mode=args.mode,
    )


def _parse_duration_arg(s: str) -> int:
    """Parse duration string like '5m', '1h', '24h', '30m' to seconds"""
    import re
    s = s.strip().lower()
    match = re.match(r'^(\d+(?:\.\d+)?)\s*(s|m|h|min|sec|hr|hour|hours|mins|minutes|seconds)?$', s)
    if not match:
        raise ValueError(f"Invalid duration format: '{s}'. Use e.g. '5m', '1h', '30m', '24h'")

    value = float(match.group(1))
    unit = match.group(2) or 'm'  # default to minutes

    if unit in ('s', 'sec', 'seconds'):
        return int(value)
    elif unit in ('m', 'min', 'mins', 'minutes'):
        return int(value * 60)
    elif unit in ('h', 'hr', 'hour', 'hours'):
        return int(value * 3600)
    else:
        return int(value * 60)


if __name__ == "__main__":
    asyncio.run(main())
