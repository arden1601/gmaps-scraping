"""Generate routes from random origin points to hospitals/puskesmas.

Each hospital in the CSV becomes a destination. For each hospital,
N random intersection nodes (≥1 km away) are selected as origins.
Origins are reverse-geocoded to kelurahan/desa via Nominatim.
Route geometry follows the actual OSM road network (shortest path).
"""

import csv
import json
import math
import random
import time as _time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import networkx as nx
import osmnx as ox
from geopy.geocoders import Nominatim
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Straight-line distance in metres between two lat/lon points."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _round_coords(lat: float, lon: float, decimals: int = 3) -> Tuple[float, float]:
    """Round coordinates for cache key (≈111 m resolution at equator)."""
    return round(lat, decimals), round(lon, decimals)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class HospitalRouteGenerator:
    """Generate origin→hospital route pairs.

    Hospitals are loaded from a CSV.  Origin points are randomly sampled
    from OSM road-network intersections that are at least
    ``min_distance_km`` away from the target hospital.
    Route geometry follows the actual shortest path on the OSM road network.
    """

    def __init__(
        self,
        graph: nx.MultiDiGraph,
        csv_path: str = "config/RS_Puskesmas.csv",
        origins_per_hospital: int = 5,
        min_distance_km: float = 1.0,
        max_routes: Optional[int] = None,
        geocode_cache_path: str = "cache/kelurahan_cache.json",
    ):
        self.graph = graph
        self.csv_path = csv_path
        self.origins_per_hospital = origins_per_hospital
        self.min_distance_m = min_distance_km * 1000
        self.max_routes = max_routes
        self.geocode_cache_path = geocode_cache_path

        # Nominatim geocoder (1 req/s policy)
        self._geocoder = Nominatim(user_agent="jakarta_traffic_scraper")
        self._kelurahan_cache: Dict[Tuple[float, float], str] = {}
        self._load_geocode_cache()

        # Pre-compute edges GeoDataFrame for geometry extraction
        self._nodes_gdf, self._edges_gdf = ox.graph_to_gdfs(graph)

        logger.info(
            f"HospitalRouteGenerator: {origins_per_hospital} origins/hospital, "
            f"min distance {min_distance_km} km, graph has {len(graph.nodes)} nodes"
        )

    # --- cache ----------------------------------------------------------

    def _load_geocode_cache(self):
        """Load previously resolved kelurahan names from disk."""
        path = Path(self.geocode_cache_path)
        if path.exists():
            with open(path) as f:
                raw = json.load(f)
            self._kelurahan_cache = {
                tuple(map(float, k.split(","))): v for k, v in raw.items()
            }
            logger.info(f"Loaded {len(self._kelurahan_cache)} cached kelurahan entries")

    def _save_geocode_cache(self):
        """Persist kelurahan cache to disk."""
        path = Path(self.geocode_cache_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        serialisable = {f"{k[0]},{k[1]}": v for k, v in self._kelurahan_cache.items()}
        with open(path, "w") as f:
            json.dump(serialisable, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved {len(self._kelurahan_cache)} kelurahan entries to cache")

    # --- hospital loading -----------------------------------------------

    def _load_hospitals(self) -> List[Dict]:
        """Load hospitals from CSV (no filtering — data is already in-area)."""
        hospitals = []
        with open(self.csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    lat = float(row["latitude"])
                    lon = float(row["longitude"])
                except (ValueError, KeyError):
                    continue
                hospitals.append({
                    "fid": row.get("fid", ""),
                    "name": row.get("name", "").strip(),
                    "lat": lat,
                    "lon": lon,
                    "city": row.get("city", "").strip(),
                    "subdistrict": row.get("subdistrict", "").strip(),
                })
        logger.info(f"Loaded {len(hospitals)} hospitals from {self.csv_path}")
        return hospitals

    # --- intersection extraction ----------------------------------------

    def _get_intersections(self) -> List[Tuple[int, Dict]]:
        """Return intersection nodes (degree ≥ 3) with their attributes."""
        degrees = dict(self.graph.degree())
        intersections = [
            (n, attrs)
            for n, attrs in self.graph.nodes(data=True)
            if degrees.get(n, 0) >= 3
        ]
        logger.info(f"Found {len(intersections)} intersections in graph")
        return intersections

    # --- shortest path geometry -----------------------------------------

    def _get_path_geometry(self, origin_node: int, dest_node: int) -> Optional[List[List[float]]]:
        """Compute shortest path on the graph and extract road geometry.

        Returns a list of [lon, lat] coordinate pairs tracing the actual
        road network, or None if no path exists.
        """
        try:
            path_nodes = nx.shortest_path(
                self.graph, origin_node, dest_node, weight="length"
            )
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None

        # Build geometry from consecutive edges
        coords = []
        for i in range(len(path_nodes) - 1):
            u, v = path_nodes[i], path_nodes[i + 1]
            # Get edge geometry (may have multiple keys; take key=0)
            try:
                edge_data = self._edges_gdf.loc[(u, v, 0)]
                geom = edge_data["geometry"]
                edge_coords = list(geom.coords)  # [(lon, lat), ...]
            except KeyError:
                # Try any key
                try:
                    for key in range(5):
                        try:
                            edge_data = self._edges_gdf.loc[(u, v, key)]
                            geom = edge_data["geometry"]
                            edge_coords = list(geom.coords)
                            break
                        except KeyError:
                            continue
                    else:
                        # Fallback: straight line between nodes
                        n1 = self.graph.nodes[u]
                        n2 = self.graph.nodes[v]
                        edge_coords = [(n1["x"], n1["y"]), (n2["x"], n2["y"])]
                except Exception:
                    n1 = self.graph.nodes[u]
                    n2 = self.graph.nodes[v]
                    edge_coords = [(n1["x"], n1["y"]), (n2["x"], n2["y"])]

            # Avoid duplicating the junction point between consecutive edges
            if coords and edge_coords:
                # Check if we need to reverse this edge's coords
                # (edge geometry might go v→u instead of u→v)
                last_coord = coords[-1]
                first_of_edge = edge_coords[0]
                last_of_edge = edge_coords[-1]

                dist_to_first = (last_coord[0] - first_of_edge[0])**2 + (last_coord[1] - first_of_edge[1])**2
                dist_to_last = (last_coord[0] - last_of_edge[0])**2 + (last_coord[1] - last_of_edge[1])**2

                if dist_to_last < dist_to_first:
                    edge_coords = list(reversed(edge_coords))

                coords.extend(edge_coords[1:])  # skip first (= last of previous)
            else:
                coords.extend(edge_coords)

        if len(coords) < 2:
            return None

        # Convert to [lon, lat] format
        return [[c[0], c[1]] for c in coords]

    # --- reverse geocoding ----------------------------------------------

    def _reverse_geocode_kelurahan(self, lat: float, lon: float) -> str:
        """Resolve a lat/lon to its kelurahan/desa name via Nominatim."""
        key = _round_coords(lat, lon)
        if key in self._kelurahan_cache:
            return self._kelurahan_cache[key]

        kelurahan = "Unknown"
        try:
            _time.sleep(1.1)  # respect Nominatim rate limit
            location = self._geocoder.reverse(
                (lat, lon), exactly_one=True, language="id",
                addressdetails=True, zoom=16,
            )
            if location and location.raw.get("address"):
                addr = location.raw["address"]
                kelurahan = (
                    addr.get("village")
                    or addr.get("suburb")
                    or addr.get("neighbourhood")
                    or addr.get("city_district")
                    or addr.get("town")
                    or addr.get("county")
                    or "Unknown"
                )
        except Exception as e:
            logger.warning(f"Reverse geocode failed for ({lat}, {lon}): {e}")

        self._kelurahan_cache[key] = kelurahan
        return kelurahan

    # --- route generation -----------------------------------------------

    def generate_route_queue(self) -> List[Dict]:
        """Generate origin→hospital route pairs.

        Returns a list of route dicts ready for the scraper.
        Each route includes the actual road geometry as a coordinate list.
        """
        hospitals = self._load_hospitals()
        intersections = self._get_intersections()

        if not intersections:
            logger.warning("No intersections found — cannot generate routes")
            return []

        route_queue: List[Dict] = []
        total_skipped = 0
        no_path_count = 0

        # Find nearest OSM node for each hospital
        hosp_lats = [h["lat"] for h in hospitals]
        hosp_lons = [h["lon"] for h in hospitals]
        hosp_nearest_nodes = ox.nearest_nodes(self.graph, hosp_lons, hosp_lats)

        for hosp_idx, hosp in enumerate(hospitals):
            if self.max_routes and len(route_queue) >= self.max_routes:
                break

            h_lat, h_lon = hosp["lat"], hosp["lon"]
            dest_node = hosp_nearest_nodes[hosp_idx]

            # Filter intersections ≥ min_distance_m from this hospital
            candidates = []
            for node, attrs in intersections:
                dist = _haversine_m(attrs["y"], attrs["x"], h_lat, h_lon)
                if dist >= self.min_distance_m:
                    candidates.append((node, attrs, dist))

            if not candidates:
                logger.warning(f"No valid origins for hospital '{hosp['name']}' (all too close)")
                total_skipped += 1
                continue

            # Randomly sample N origins
            n_pick = min(self.origins_per_hospital, len(candidates))
            chosen = random.sample(candidates, n_pick)

            for node, attrs, dist in chosen:
                if self.max_routes and len(route_queue) >= self.max_routes:
                    break

                # Compute shortest path geometry on the road network
                path_coords = self._get_path_geometry(node, dest_node)
                if path_coords is None:
                    no_path_count += 1
                    continue

                route_queue.append({
                    "origin_node": node,
                    "origin_coords": (attrs["y"], attrs["x"]),
                    "origin_kelurahan": None,  # filled in below
                    "dest_node": int(dest_node),
                    "dest_coords": (h_lat, h_lon),
                    "dest_hospital": hosp["name"],
                    "dest_hospital_id": hosp["fid"],
                    "dest_city": hosp["city"],
                    "straight_line_m": round(dist, 1),
                    "path_geometry": path_coords,  # [[lon, lat], ...]
                })

        if no_path_count:
            logger.info(f"Skipped {no_path_count} pairs with no path on the graph")
        logger.info(
            f"Generated {len(route_queue)} routes to {len(hospitals)} hospitals "
            f"({total_skipped} hospitals had no valid origins)"
        )

        # --- Reverse geocode all unique origin coords -------------------
        unique_origins = list({r["origin_coords"] for r in route_queue})
        logger.info(f"Reverse-geocoding {len(unique_origins)} unique origin points to kelurahan …")

        for i, (lat, lon) in enumerate(unique_origins):
            self._reverse_geocode_kelurahan(lat, lon)
            if (i + 1) % 20 == 0:
                logger.info(f"  geocoded {i + 1}/{len(unique_origins)} origins …")

        # Apply cached values to routes
        for route in route_queue:
            lat, lon = route["origin_coords"]
            key = _round_coords(lat, lon)
            route["origin_kelurahan"] = self._kelurahan_cache.get(key, "Unknown")

        # Persist cache
        self._save_geocode_cache()

        # Export route queue JSON + preview Shapefile
        self._export_route_queue(route_queue)
        self._export_preview_shapefile(route_queue)

        return route_queue

    # --- export ---------------------------------------------------------

    def _export_route_queue(
        self, route_queue: List[Dict], output_path: str = "data/hospital_routes_queue.json"
    ):
        """Save generated routes to JSON for inspection."""
        from datetime import datetime

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        # Make a serialisable copy (without heavy geometry)
        routes_light = []
        for r in route_queue:
            r_copy = {k: v for k, v in r.items() if k != "path_geometry"}
            r_copy["path_coords_count"] = len(r.get("path_geometry", []))
            routes_light.append(r_copy)

        export_data = {
            "generated_at": datetime.now().isoformat(),
            "total_routes": len(route_queue),
            "origins_per_hospital": self.origins_per_hospital,
            "min_distance_m": self.min_distance_m,
            "routes": routes_light,
        }
        with open(output_path, "w") as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)
        logger.info(f"Exported {len(route_queue)} hospital routes to {output_path}")

    def _export_preview_shapefile(
        self, route_queue: List[Dict], output_dir: str = "data/output"
    ):
        """Export a preview Shapefile with road-network route geometries.

        This allows visual validation of routes BEFORE running the scraper.
        """
        import geopandas as gpd
        from shapely.geometry import LineString

        Path(output_dir).mkdir(parents=True, exist_ok=True)

        records = []
        for r in route_queue:
            coords = r.get("path_geometry", [])
            if len(coords) < 2:
                continue
            geom = LineString(coords)  # coords are already [lon, lat]
            records.append({
                "origin_kel": str(r.get("origin_kelurahan", ""))[:80],
                "dest_hosp": str(r.get("dest_hospital", ""))[:80],
                "dest_city": str(r.get("dest_city", ""))[:40],
                "dist_sl_m": r.get("straight_line_m", 0),
                "geometry": geom,
            })

        gdf = gpd.GeoDataFrame(records, crs="EPSG:4326")
        output_path = Path(output_dir) / "hospital_routes_preview.shp"
        gdf.to_file(output_path, driver="ESRI Shapefile")
        logger.info(f"📍 Preview Shapefile: {output_path}  ({len(gdf)} routes)")
        logger.info("   Open this in QGIS/GIS to validate routes before scraping.")
