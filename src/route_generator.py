"""Generate route queries from road network graph"""

import networkx as nx
from typing import List, Dict, Tuple
import logging
from datetime import datetime
import sys

logger = logging.getLogger(__name__)


class RouteGenerator:
    """Generate route queries from road network intersections - optimized for large networks"""

    def __init__(self, graph: nx.MultiDiGraph, max_routes: int = None):
        """
        Initialize route generator

        Args:
            graph: NetworkX graph of road network
            max_routes: Maximum number of routes to generate (None = all, but careful!)
        """
        self.graph = graph
        self.max_routes = max_routes
        self.total_possible_pairs = 0
        self.route_queue = []

        logger.info(f"RouteGenerator initialized with {len(graph.nodes)} nodes, {len(graph.edges)} edges")

    def get_intersections(self) -> List[Tuple[int, Dict]]:
        """
        Get intersection nodes (degree >= 3)

        Returns:
            List of (node_id, attributes) tuples
        """
        logger.info("Finding intersection nodes (degree >= 3)...")
        intersections = []
        degrees = dict(self.graph.degree())

        for node, attrs in self.graph.nodes(data=True):
            if degrees[node] >= 3:
                intersections.append((node, attrs))

        logger.info(f"Found {len(intersections)} intersection nodes out of {len(self.graph.nodes)} total nodes")

        # Calculate total possible pairs for context
        n = len(intersections)
        self.total_possible_pairs = n * (n - 1) // 2
        logger.info(f"Total possible route pairs: {self.total_possible_pairs:,}")

        return intersections

    def _sample_nearby_intersections(
        self,
        intersections: List[Tuple[int, Dict]],
        max_neighbors: int = 50
    ) -> List[Dict]:
        """
        Sample intersections and find only nearby connections

        This avoids O(n²) problem by limiting each node
        to only connect to nearby intersections.
        """
        route_queue = []
        connected_pairs = set()
        intersection_set = {n for n, _ in intersections}
        intersection_attrs = {n: attrs for n, attrs in intersections}

        for i, (node, attrs) in enumerate(intersections):
            if self.max_routes and len(route_queue) >= self.max_routes:
                break

            # Find neighbors within 2-3 hops
            nearby_nodes = []
            try:
                neighbors = nx.single_source_shortest_path_length(
                    self.graph,
                    source=node,
                    cutoff=3,
                )
                for neighbor in neighbors.keys():
                    if neighbor != node and neighbor in intersection_set:
                        nearby_nodes.append(neighbor)
            except nx.NetworkXError:
                continue

            # Connect to this node's nearby intersections
            for target in nearby_nodes[:max_neighbors]:
                if self.max_routes and len(route_queue) >= self.max_routes:
                    break

                pair_id = tuple(sorted([node, target]))
                if pair_id not in connected_pairs:
                    route_queue.append({
                        "origin_node": node,
                        "dest_node": target,
                        "origin_coords": (attrs["y"], attrs["x"]),
                        "dest_coords": (
                            self.graph.nodes[target]["y"],
                            self.graph.nodes[target]["x"]
                        ),
                    })
                    connected_pairs.add(pair_id)

            if i % 100 == 0 and i > 0:
                logger.info(f"Processed {i}/{len(intersections)} intersections, {len(route_queue)} routes so far...")

        return route_queue

    def generate_route_queue(self) -> List[Dict]:
        """
        Generate origin-destination route queries using optimized sampling

        Returns:
            List of route dicts with origin/destination coordinates
        """
        logger.info("Generating route queries (optimized)...")

        intersections = self.get_intersections()

        if not intersections:
            logger.warning("No intersections found in graph!")
            return []

        # Use nearby sampling to avoid O(n²) explosion
        route_queue = self._sample_nearby_intersections(intersections)

        logger.info(f"Generated {len(route_queue)} route queries (sampled from {len(intersections)} intersections)")
        logger.info(f"Sampling rate: {len(route_queue)/self.total_possible_pairs*100:.2f}% of possible pairs")

        # Also export immediately for use in scraper
        self.export_route_queue(route_queue, "data/routes_queue.json")

        return route_queue

    def export_route_queue(self, route_queue: List[Dict], output_path: str = "data/routes_queue.json"):
        """
        Export route queue to JSON with progress info

        Args:
            route_queue: List of route dictionaries
            output_path: Path to output JSON file
        """
        import json
        from pathlib import Path

        # Create parent directory if needed
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w") as f:
            # Add metadata
            export_data = {
                "generated_at": datetime.now().isoformat(),
                "total_routes": len(route_queue),
                "sampling_method": "nearby_optimized",
                "intersection_count": len(self.get_intersections()),
                "routes": route_queue
            }
            json.dump(export_data, f, indent=2)

        logger.info(f"Exported {len(route_queue)} routes to {output_path}")


def main():
    """Test route generator with sample data"""
    import osmnx as ox

    # Create small test graph
    G = nx.MultiDiGraph()

    # Add some nodes and edges
    G.add_nodes_from([
        (1, {"x": 106.76, "y": -6.23}),
        (2, {"x": 106.78, "y": -6.22}),
        (3, {"x": 106.80, "y": -6.21}),
        (4, {"x": 106.82, "y": -6.17}),
    ])

    G.add_edges_from([
        (1, 2, {"length": 100}),
        (2, 3, {"length": 150}),
        (3, 4, {"length": 200}),
        (4, 1, {"length": 120}),
    ])

    # Test route generator
    generator = RouteGenerator(G, max_routes=100)
    routes = generator.generate_route_queue()

    print(f"\nGenerated {len(routes)} routes:")
    for route in routes[:5]:  # Show first 5
        print(f"  {route['origin_node']} -> {route['dest_node']} ({route.get('sampling_method', 'unknown')})")

    print(f"\nExported to data/routes_queue.json")

    # Export routes
    generator.export_route_queue(routes, "data/test_routes.json")


if __name__ == "__main__":
    main()
