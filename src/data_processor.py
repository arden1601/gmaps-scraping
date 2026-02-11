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
