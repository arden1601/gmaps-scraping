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
