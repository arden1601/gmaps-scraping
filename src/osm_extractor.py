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

        # Define bounding box as (west, south, east, north)
        bbox = (
            self.bounds["min_lon"],  # west
            self.bounds["min_lat"],  # south
            self.bounds["max_lon"],  # east
            self.bounds["max_lat"]    # north
        )

        # Download drive network
        self.graph = ox.graph_from_bbox(
            bbox,
            network_type="drive"
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
