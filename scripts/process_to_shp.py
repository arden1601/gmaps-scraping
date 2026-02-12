"""
Convert raw scraped JSON results + OSM road network into a Shapefile
matching the target schema:

  road_id, road_name, road_type, oneway, length_m,
  speed_peak_am, speed_offpeak, speed_peak_pm, speed_limit, geometry

Usage:
    python scripts/process_to_shp.py
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict

import yaml
import numpy as np
import pandas as pd
import geopandas as gpd
import osmnx as ox

RAW_DIR = Path("data/raw")
OUTPUT_DIR = Path("data/output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PERIODS = ["peak_am", "off_peak", "peak_pm"]

# Minimum thresholds to filter unreliable short-distance data.
# Google Maps rounds durations to the nearest minute (60s), so very
# short routes produce wildly inaccurate speeds.
MIN_DISTANCE_M = 200   # skip routes shorter than 200m
MIN_DURATION_S = 120   # skip routes shorter than 2 minutes


# ── helpers ──────────────────────────────────────────────────────────

def load_results(period: str) -> list:
    """Load *_results.json for a time period."""
    path = RAW_DIR / f"{period}_results.json"
    if not path.exists():
        print(f"  ⚠ {path} not found, skipping")
        return []
    with open(path) as f:
        data = json.load(f)
    print(f"  ✓ {path.name}: {len(data)} routes")
    return data


def calc_speed_kmh(duration_sec, distance_m):
    if not duration_sec or not distance_m or duration_sec <= 0 or distance_m <= 0:
        return None
    return round((distance_m / duration_sec) * 3.6, 2)


def load_osm_networks() -> tuple:
    """
    Load OSM road networks for all configured areas.
    Returns (combined_graph, edges_gdf).
    """
    with open("config/areas.yaml") as f:
        areas_cfg = yaml.safe_load(f)

    all_edges = []
    graphs = []

    for city, city_areas in areas_cfg.items():
        for area_name, area_cfg in city_areas.items():
            bounds = area_cfg["bounds"]
            bbox = (
                bounds["min_lon"],
                bounds["min_lat"],
                bounds["max_lon"],
                bounds["max_lat"],
            )
            print(f"  📡 Downloading OSM network: {area_cfg['name']} ...")
            G = ox.graph_from_bbox(bbox, network_type="drive")
            nodes, edges = ox.graph_to_gdfs(G)
            graphs.append(G)
            all_edges.append(edges)
            print(f"     {len(nodes)} nodes, {len(edges)} edges")

    # Combine all edges
    combined_edges = pd.concat(all_edges, ignore_index=False)
    # Remove duplicates (overlapping areas might share edges)
    combined_edges = combined_edges[~combined_edges.index.duplicated(keep="first")]

    return graphs, combined_edges


def match_routes_to_edges(all_data: list, graphs: list, edges_gdf) -> gpd.GeoDataFrame:
    """
    Match each scraped route (origin_node → dest_node) to an OSM edge.
    Aggregate speeds per edge per time period.
    Returns a GeoDataFrame with the target schema.
    """

    # Build a lookup: (u, v) → edge index in edges_gdf
    # edges_gdf index is (u, v, key)
    edge_lookup = {}
    for idx in edges_gdf.index:
        u, v, key = idx
        if (u, v) not in edge_lookup:
            edge_lookup[(u, v)] = idx
        # Also add reverse for undirected roads
        if (v, u) not in edge_lookup:
            edge_lookup[(v, u)] = idx

    # Collect speeds per edge per period
    # edge_key → {period → [speeds]}
    edge_speeds = defaultdict(lambda: defaultdict(list))
    matched = 0
    unmatched = 0
    filtered_short = 0

    for item in all_data:
        origin = item.get("origin_node")
        dest = item.get("dest_node")
        period = item.get("time_period", "")

        sd = item.get("scraped_data", {})
        dur_traffic = sd.get("duration_in_traffic", {})
        dur_normal = sd.get("duration", {})
        dist = sd.get("distance", {})
        duration_sec = dur_traffic.get("value") or dur_normal.get("value") or 0
        distance_m = dist.get("value", 0)

        # Filter out unreliable short-distance routes
        if distance_m < MIN_DISTANCE_M or duration_sec < MIN_DURATION_S:
            filtered_short += 1
            continue

        speed = calc_speed_kmh(duration_sec, distance_m)

        if speed is None:
            continue

        # Try to find matching edge
        edge_key = edge_lookup.get((origin, dest))
        if edge_key is None:
            # Try finding the closest edge via graph shortest path
            for G in graphs:
                if G.has_node(origin) and G.has_node(dest):
                    try:
                        import networkx as nx
                        path = nx.shortest_path(G, origin, dest, weight="length")
                        # Use the first edge in the path
                        for i in range(len(path) - 1):
                            ek = edge_lookup.get((path[i], path[i + 1]))
                            if ek is not None:
                                edge_key = ek
                                break
                    except (nx.NetworkXNoPath, nx.NodeNotFound):
                        pass
                    break

        if edge_key is not None:
            edge_speeds[edge_key][period].append(speed)
            matched += 1
        else:
            unmatched += 1

    print(f"\n  ✅ Matched: {matched} routes → OSM edges")
    if filtered_short:
        print(f"  🔽 Filtered: {filtered_short} routes (distance < {MIN_DISTANCE_M}m or duration < {MIN_DURATION_S}s)")
    if unmatched:
        print(f"  ⚠ Unmatched: {unmatched} routes (no direct edge found)")

    # Build output GeoDataFrame: one row per edge that has data
    records = []
    for edge_idx, period_speeds in edge_speeds.items():
        edge = edges_gdf.loc[edge_idx]

        # Extract OSM attributes
        osmid = edge.get("osmid", "")
        if isinstance(osmid, list):
            osmid = osmid[0]

        name = edge.get("name", "")
        if isinstance(name, list):
            name = ", ".join(str(n) for n in name)
        if pd.isna(name):
            name = ""

        highway = edge.get("highway", "")
        if isinstance(highway, list):
            highway = highway[0]
        if pd.isna(highway):
            highway = ""

        oneway = edge.get("oneway", "no")
        if isinstance(oneway, bool):
            oneway = "yes" if oneway else "no"
        if pd.isna(oneway):
            oneway = "no"

        length_m = edge.get("length", 0)
        if pd.isna(length_m):
            length_m = 0

        maxspeed = edge.get("maxspeed", None)
        if isinstance(maxspeed, list):
            maxspeed = maxspeed[0]
        if isinstance(maxspeed, str):
            try:
                maxspeed = float(maxspeed.replace(" km/h", "").replace(" mph", ""))
            except ValueError:
                maxspeed = None
        if maxspeed is not None and pd.isna(maxspeed):
            maxspeed = None

        # Calculate average speed per period
        spd_peak_am = None
        spd_offpeak = None
        spd_peak_pm = None

        if "peak_am" in period_speeds:
            spd_peak_am = round(np.mean(period_speeds["peak_am"]), 2)
        if "off_peak" in period_speeds:
            spd_offpeak = round(np.mean(period_speeds["off_peak"]), 2)
        if "peak_pm" in period_speeds:
            spd_peak_pm = round(np.mean(period_speeds["peak_pm"]), 2)

        records.append({
            "road_id": str(osmid),
            "road_name": str(name),
            "road_type": str(highway),
            "oneway": str(oneway),
            "length_m": round(float(length_m), 2),
            "spd_pk_am": spd_peak_am,
            "spd_offpk": spd_offpeak,
            "spd_pk_pm": spd_peak_pm,
            "spd_limit": float(maxspeed) if maxspeed else None,
            "geometry": edge["geometry"],
        })

    gdf = gpd.GeoDataFrame(records, crs="EPSG:4326")
    return gdf


# ── main ─────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  Traffic Data → Shapefile Processor (with OSM attributes)")
    print("=" * 60)

    # 1. Load scraped data
    print("\n📂 Loading raw scraped data...")
    all_data = []
    for p in PERIODS:
        data = load_results(p)
        all_data.extend(data)

    if not all_data:
        print("\n❌ No data found in data/raw/. Run the scraper first.")
        sys.exit(1)

    print(f"\n📊 Total routes loaded: {len(all_data)}")
    for p in PERIODS:
        count = sum(1 for d in all_data if d.get("time_period") == p)
        if count:
            print(f"   {p}: {count} routes")

    # 2. Load OSM network
    print("\n🗺️  Loading OSM road networks...")
    graphs, edges_gdf = load_osm_networks()

    # 3. Match routes to edges and build GeoDataFrame
    print("\n🔧 Matching scraped routes to OSM edges...")
    result_gdf = match_routes_to_edges(all_data, graphs, edges_gdf)

    if result_gdf.empty:
        print("\n❌ No routes could be matched to OSM edges.")
        sys.exit(1)

    print(f"\n📊 Result: {len(result_gdf)} road segments with traffic data")

    # 4. Export
    datestamp = datetime.now().strftime("%Y%m%d")
    output_path = OUTPUT_DIR / f"jakarta_traffic_{datestamp}.shp"
    result_gdf.to_file(output_path, driver="ESRI Shapefile")
    print(f"\n✅ Shapefile exported: {output_path}")

    # 5. Summary
    print("\n" + "=" * 60)
    print("  Summary")
    print("=" * 60)

    print(f"\n  Road segments:  {len(result_gdf)}")
    print(f"  With road name: {(result_gdf['road_name'] != '').sum()}")

    # Road type breakdown
    print("\n  Road types:")
    for rtype, count in result_gdf["road_type"].value_counts().items():
        print(f"    {rtype}: {count}")

    # Speed stats
    speed_map = {
        "spd_pk_am": "peak_am (07-09)",
        "spd_offpk": "off_peak (10-17)",
        "spd_pk_pm": "peak_pm (17-20)",
    }
    for col, label in speed_map.items():
        valid = result_gdf[col].dropna()
        if not valid.empty:
            print(f"\n  {label}:")
            print(f"    Avg speed: {valid.mean():.1f} km/h")
            print(f"    Min speed: {valid.min():.1f} km/h")
            print(f"    Max speed: {valid.max():.1f} km/h")
            print(f"    Segments:  {len(valid)}")

    # Attribute table
    print("\n  Shapefile attribute table:")
    print("  " + "-" * 50)
    print(f"  {'Field':<12} {'Type':<10} {'Description'}")
    print("  " + "-" * 50)
    schema = [
        ("road_id",   "String",  "OSM way ID"),
        ("road_name", "String",  "Street name"),
        ("road_type", "String",  "Highway classification"),
        ("oneway",    "String",  "One-way flag"),
        ("length_m",  "Float",   "Segment length (m)"),
        ("spd_pk_am", "Float",   "Avg speed 07-09 (km/h)"),
        ("spd_offpk", "Float",   "Avg speed 10-17 (km/h)"),
        ("spd_pk_pm", "Float",   "Avg speed 17-20 (km/h)"),
        ("spd_limit", "Float",   "Posted speed limit"),
        ("geometry",  "Line",    "Road geometry"),
    ]
    for name, dtype, desc in schema:
        print(f"  {name:<12} {dtype:<10} {desc}")

    print(f"\n📁 Output: {OUTPUT_DIR.resolve()}")


if __name__ == "__main__":
    main()
