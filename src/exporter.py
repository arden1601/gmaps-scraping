"""Export processed data to Shapefile format"""

import geopandas as gpd
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class ShapefileExporter:
    """Export GeoDataFrame to Shapefile"""

    def __init__(self, output_dir: str = "data/output"):
        """
        Initialize exporter

        Args:
            output_dir: Directory for output files
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def export(
        self,
        gdf: gpd.GeoDataFrame,
        filename: str,
        crs: Optional[str] = None
    ) -> str:
        """
        Export GeoDataFrame to Shapefile

        Args:
            gdf: GeoDataFrame to export
            filename: Output filename (without extension)
            crs: Optional CRS to reproject to (e.g., "EPSG:3857")

        Returns:
            Path to exported file
        """
        # Reproject if requested
        if crs:
            gdf = gdf.to_crs(crs)

        # Build output path
        output_path = self.output_dir / f"{filename}.shp"

        # Export to Shapefile
        gdf.to_file(output_path, driver="ESRI Shapefile")

        logger.info(f"Exported {len(gdf)} records to {output_path}")

        return str(output_path)

    def get_layer_schema(self, gdf: gpd.GeoDataFrame) -> dict:
        """
        Get schema/field information for GeoDataFrame

        Args:
            gdf: Input GeoDataFrame

        Returns:
            Dict with field names and types
        """
        schema = {
            "geometry_type": gdf.geometry.geom_type.iloc[0] if len(gdf) > 0 else None,
            "crs": str(gdf.crs),
            "fields": []
        }

        for col in gdf.columns:
            if col != "geometry":
                dtype = str(gdf[col].dtype)
                schema["fields"].append({
                    "name": col,
                    "type": dtype
                })

        return schema
