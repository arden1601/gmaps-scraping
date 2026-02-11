"""Read and validate Shapefile output from Jakarta traffic scraper"""

import sys
import geopandas as gpd
import pandas as pd
from pathlib import Path


def validate_shapefile(shapefile_path: str):
    """
    Validate Shapefile output and print summary statistics

    Args:
        shapefile_path: Path to Shapefile (.shp)
    """
    print(f"\n{'='*60}")
    print(f"Validating: {shapefile_path}")
    print(f"{'='*60}\n")

    try:
        # Read Shapefile
        gdf = gpd.read_file(shapefile_path)

        print(f"✓ Successfully read Shapefile")
        print(f"  - CRS: {gdf.crs}")
        print(f"  - Total records: {len(gdf):,}")
        print(f"  - Geometry type: {gdf.geometry.geom_type.iloc[0] if len(gdf) > 0 else 'N/A'}")
        print()

        # Basic geometry validation
        invalid_geoms = gdf[~gdf.geometry.is_valid]
        if len(invalid_geoms) > 0:
            print(f"⚠ Warning: {len(invalid_geoms)} invalid geometries found")
        else:
            print(f"✓ All geometries are valid")

        # Column summary
        print(f"\n{'─'*60}")
        print("Column Summary:")
        print(f"{'─'*60}")

        for col in gdf.columns:
            if col == "geometry":
                continue

            null_count = gdf[col].isna().sum()
            null_pct = (null_count / len(gdf)) * 100

            dtype = str(gdf[col].dtype)

            # Show sample values for string columns
            sample = ""
            if dtype == "object" and null_count < len(gdf):
                unique_vals = gdf[col].dropna().unique()
                sample = f" | Sample: {list(unique_vals[:3])}"

            print(f"  {col:20s} | {dtype:10s} | Null: {null_count:6,} ({null_pct:5.1}%) {sample}")

        # Road type distribution
        if "highway" in gdf.columns:
            print(f"\n{'─'*60}")
            print("Road Type Distribution:")
            print(f"{'─'*60}")
            highway_counts = gdf["highway"].value_counts()
            for hw_type, count in highway_counts.items():
                pct = (count / len(gdf)) * 100
                print(f"  {hw_type:20s} | {count:6,} ({pct:5.1f}%)")

        # One-way road stats
        if "oneway" in gdf.columns:
            print(f"\n{'─'*60}")
            print("One-Way Road Statistics:")
            print(f"{'─'*60}")
            oneway_counts = gdf["oneway"].value_counts()
            for ow_type, count in oneway_counts.items():
                pct = (count / len(gdf)) * 100
                print(f"  {str(ow_type):20s} | {count:6,} ({pct:5.1f}%)")

        # Speed limit stats
        if "maxspeed" in gdf.columns:
            print(f"\n{'─'*60}")
            print("Speed Limit Statistics:")
            print(f"{'─'*60}")

            # Convert to numeric (handle string values like "50")
            speed_numeric = pd.to_numeric(gdf["maxspeed"], errors="coerce")
            print(f"  Min speed: {speed_numeric.min():.0f} km/h")
            print(f"  Max speed: {speed_numeric.max():.0f} km/h")
            print(f"  Avg speed: {speed_numeric.mean():.0f} km/h")
            print(f"  Roads with speed data: {speed_numeric.notna().sum():,} ({speed_numeric.notna().sum()/len(gdf)*100:.1f}%)")

        # Bounding box
        print(f"\n{'─'*60}")
        print("Spatial Extent:")
        print(f"{'─'*60}")
        bounds = gdf.total_bounds
        print(f"  Min X: {bounds[0]:.4f}")
        print(f"  Min Y: {bounds[1]:.4f}")
        print(f"  Max X: {bounds[2]:.4f}")
        print(f"  Max Y: {bounds[3]:.4f}")

        # Sample records
        print(f"\n{'─'*60}")
        print("Sample Records (first 3):")
        print(f"{'─'*60}")

        sample_cols = [c for c in gdf.columns if c != "geometry"]
        for idx, row in gdf[sample_cols].head(3).iterrows():
            print(f"\n  Record {idx}:")
            for col, val in row.items():
                val_str = str(val) if pd.notna(val) else "NULL"
                print(f"    {col:20s}: {val_str}")

        print(f"\n{'='*60}")
        print("✓ Validation complete")
        print(f"{'='*60}\n")

        return True

    except Exception as e:
        print(f"✗ Error reading Shapefile: {e}")
        return False


def main():
    """Main entry point"""
    if len(sys.argv) < 2:
        print("Usage: python validate_shapefile.py <path_to_shapefile>")
        print("\nExample:")
        print("  python validate_shapefile.py data/output/jakarta_utara_road_network_raw.shp")
        sys.exit(1)

    shapefile_path = sys.argv[1]

    if not Path(shapefile_path).exists():
        print(f"✗ File not found: {shapefile_path}")
        sys.exit(1)

    validate_shapefile(shapefile_path)


if __name__ == "__main__":
    main()
