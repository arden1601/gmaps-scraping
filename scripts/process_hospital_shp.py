"""
Convert hospital-mode scraped JSON results into a Shapefile with
the hospital-accessibility schema:

  origin_kel, origin_lat, origin_lon,
  dest_hosp, dest_lat, dest_lon,
  dist_m,
  dur_pk_am, dur_offpk, dur_pk_pm,
  spd_pk_am, spd_offpk, spd_pk_pm,
  geometry  (straight line origin→hospital)

Usage:
    python scripts/process_hospital_shp.py
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict

import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import LineString

RAW_DIR = Path("data/raw")
OUTPUT_DIR = Path("data/output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PERIODS = ["peak_am", "off_peak", "peak_pm"]

# Minimum thresholds to filter unreliable short-distance data.
MIN_DISTANCE_M = 200
MIN_DURATION_S = 60


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


# ── core processing ─────────────────────────────────────────────────

def build_route_key(item: dict) -> str:
    """Unique key for an origin→hospital pair."""
    o = item.get("origin_coords", [0, 0])
    d = item.get("dest_coords", [0, 0])
    return f"{o[0]:.6f},{o[1]:.6f}→{d[0]:.6f},{d[1]:.6f}"


def process_hospital_data(all_data: list) -> gpd.GeoDataFrame:
    """
    Aggregate scraped data into one row per origin→hospital pair,
    with speed/duration per time period.
    """
    # Group by route key
    route_groups = defaultdict(lambda: {
        "meta": None,
        "periods": defaultdict(list),  # period → [(dur, dist), ...]
    })

    filtered_count = 0

    for item in all_data:
        key = build_route_key(item)
        period = item.get("time_period", "")

        sd = item.get("scraped_data", {})
        dur_traffic = sd.get("duration_in_traffic", {})
        dur_normal = sd.get("duration", {})
        dist = sd.get("distance", {})
        duration_sec = dur_traffic.get("value") or dur_normal.get("value") or 0
        distance_m = dist.get("value", 0)

        # Filter unreliable data
        if distance_m < MIN_DISTANCE_M or duration_sec < MIN_DURATION_S:
            filtered_count += 1
            continue

        # Store metadata once
        if route_groups[key]["meta"] is None:
            route_groups[key]["meta"] = item

        route_groups[key]["periods"][period].append({
            "duration_sec": duration_sec,
            "distance_m": distance_m,
        })

    if filtered_count:
        print(f"  🔽 Filtered: {filtered_count} entries (too short/fast)")

    # Build output records
    records = []
    for key, group in route_groups.items():
        meta = group["meta"]
        if meta is None:
            continue

        origin = meta.get("origin_coords", [0, 0])
        dest = meta.get("dest_coords", [0, 0])
        origin_kel = meta.get("origin_kelurahan", "Unknown")
        dest_hosp = meta.get("dest_hospital", "Unknown")

        # Average distance across all periods
        all_dists = []
        for pdata in group["periods"].values():
            all_dists.extend([d["distance_m"] for d in pdata])
        avg_dist = round(np.mean(all_dists), 1) if all_dists else 0

        # Duration and speed per period
        dur_pk_am = None
        dur_offpk = None
        dur_pk_pm = None
        spd_pk_am = None
        spd_offpk = None
        spd_pk_pm = None

        for period, entries in group["periods"].items():
            avg_dur = round(np.mean([e["duration_sec"] for e in entries]), 1)
            avg_d = round(np.mean([e["distance_m"] for e in entries]), 1)
            speed = calc_speed_kmh(avg_dur, avg_d)

            if period == "peak_am":
                dur_pk_am = avg_dur
                spd_pk_am = speed
            elif period == "off_peak":
                dur_offpk = avg_dur
                spd_offpk = speed
            elif period == "peak_pm":
                dur_pk_pm = avg_dur
                spd_pk_pm = speed

        # Geometry: use actual road path if available, else straight line
        meta_path = meta.get("path_geometry")
        if meta_path and len(meta_path) >= 2:
            geom = LineString(meta_path)  # [[lon, lat], ...]
        else:
            geom = LineString([(origin[1], origin[0]), (dest[1], dest[0])])

        records.append({
            "origin_kel": str(origin_kel)[:80],   # Shapefile 80-char limit
            "origin_lat": round(origin[0], 6),
            "origin_lon": round(origin[1], 6),
            "dest_hosp": str(dest_hosp)[:80],
            "dest_lat": round(dest[0], 6),
            "dest_lon": round(dest[1], 6),
            "dist_m": avg_dist,
            "dur_pk_am": dur_pk_am,
            "dur_offpk": dur_offpk,
            "dur_pk_pm": dur_pk_pm,
            "spd_pk_am": spd_pk_am,
            "spd_offpk": spd_offpk,
            "spd_pk_pm": spd_pk_pm,
            "geometry": geom,
        })

    gdf = gpd.GeoDataFrame(records, crs="EPSG:4326")
    return gdf


# ── main ─────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  Hospital Accessibility → Shapefile Processor")
    print("=" * 60)

    # 1. Load scraped data
    print("\n📂 Loading raw scraped data...")
    all_data = []
    for p in PERIODS:
        data = load_results(p)
        all_data.extend(data)

    if not all_data:
        print("\n❌ No data found in data/raw/. Run the scraper first with --mode hospital.")
        sys.exit(1)

    # Check this is hospital-mode data
    has_hospital = any(d.get("dest_hospital") for d in all_data)
    if not has_hospital:
        print("\n⚠ Data does not appear to be from hospital mode (no 'dest_hospital' field).")
        print("  Make sure you ran: python -m src.main --mode hospital")
        sys.exit(1)

    print(f"\n📊 Total route entries loaded: {len(all_data)}")
    for p in PERIODS:
        count = sum(1 for d in all_data if d.get("time_period") == p)
        if count:
            print(f"   {p}: {count} entries")

    # 2. Process into GeoDataFrame
    print("\n🔧 Processing hospital accessibility data...")
    result_gdf = process_hospital_data(all_data)

    if result_gdf.empty:
        print("\n❌ No valid routes after processing.")
        sys.exit(1)

    print(f"\n📊 Result: {len(result_gdf)} origin→hospital routes")

    # 3. Export Shapefile
    datestamp = datetime.now().strftime("%Y%m%d")
    output_path = OUTPUT_DIR / f"hospital_accessibility_{datestamp}.shp"
    result_gdf.to_file(output_path, driver="ESRI Shapefile")
    print(f"\n✅ Shapefile exported: {output_path}")

    # 4. Summary
    print("\n" + "=" * 60)
    print("  Summary")
    print("=" * 60)

    print(f"\n  Total routes:       {len(result_gdf)}")
    print(f"  Unique origins:     {result_gdf['origin_kel'].nunique()} kelurahan")
    print(f"  Unique hospitals:   {result_gdf['dest_hosp'].nunique()}")

    # Top hospitals
    print("\n  Routes per hospital (top 10):")
    for hosp, count in result_gdf["dest_hosp"].value_counts().head(10).items():
        print(f"    {hosp}: {count}")

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
            print(f"    Routes:    {len(valid)}")

    # Attribute table
    print("\n  Shapefile attribute table:")
    print("  " + "-" * 55)
    print(f"  {'Field':<12} {'Type':<10} {'Description'}")
    print("  " + "-" * 55)
    schema = [
        ("origin_kel", "String",  "Origin kelurahan/desa"),
        ("origin_lat", "Float",   "Origin latitude"),
        ("origin_lon", "Float",   "Origin longitude"),
        ("dest_hosp",  "String",  "Hospital name"),
        ("dest_lat",   "Float",   "Hospital latitude"),
        ("dest_lon",   "Float",   "Hospital longitude"),
        ("dist_m",     "Float",   "Route distance (m)"),
        ("dur_pk_am",  "Float",   "Duration 07-09 (sec)"),
        ("dur_offpk",  "Float",   "Duration 10-17 (sec)"),
        ("dur_pk_pm",  "Float",   "Duration 17-20 (sec)"),
        ("spd_pk_am",  "Float",   "Speed 07-09 (km/h)"),
        ("spd_offpk",  "Float",   "Speed 10-17 (km/h)"),
        ("spd_pk_pm",  "Float",   "Speed 17-20 (km/h)"),
        ("geometry",   "Line",    "Origin → hospital line"),
    ]
    for name, dtype, desc in schema:
        print(f"  {name:<12} {dtype:<10} {desc}")

    print(f"\n📁 Output: {OUTPUT_DIR.resolve()}")


if __name__ == "__main__":
    main()
