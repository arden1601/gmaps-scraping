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
