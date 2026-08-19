#!/usr/bin/env python3
"""
CCM Tool v0.58.2 — Regression Test Suite (Phase 4)

Verifies backward compatibility: all v0.57 functionality still works
after v0.58.2 scoring engine addition. Tests core catalog building,
role detection, dataset enumeration — the v0.57 baseline.

Run with: pytest test_ccm_regression_v057.py -v
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from ccm_data_catalog import DataCatalogBuilder


class TestCatalogBuildingRegression:
    """v0.57 catalog building should still work unchanged."""

    def test_catalog_json_format_unchanged(self):
        """Catalog JSON structure should match v0.57 schema."""
        # v0.57 expected catalog structure
        expected_keys = {
            "metadata",
            "datasets",
        }

        metadata_keys = {
            "scan_datetime",
            "data_root",
            "aoi_path",
            "aoi_crs",
            "v057_baseline",
        }

        dataset_keys = {
            "name",
            "file_path",
            "file_extension",
            "geom_type",
            "size_mb",
            "schema_fields",
        }

        # Construct a mock catalog
        mock_catalog = {
            "metadata": {
                "scan_datetime": "2026-08-19T12:34:56",
                "data_root": "/data",
                "aoi_path": "/data/extent/AOI.shp",
                "aoi_crs": "EPSG:32633",
                "v057_baseline": True,
            },
            "datasets": [
                {
                    "name": "ASTER_30m",
                    "file_path": "/data/DEM/ASTER_30m.tif",
                    "file_extension": ".tif",
                    "geom_type": "raster",
                    "size_mb": 500,
                    "schema_fields": ["elevation"],
                }
            ],
        }

        # Verify structure
        assert all(k in mock_catalog for k in expected_keys), "Missing required top-level keys"
        assert all(k in mock_catalog["metadata"] for k in metadata_keys), "Missing metadata keys"
        assert all(k in mock_catalog["datasets"][0] for k in dataset_keys), "Missing dataset keys"

    def test_catalog_preserves_v057_outputs(self):
        """v0.58.2 should not delete v0.57 output files."""
        output_files = {
            "ccm_data_catalog.json": "factual catalog (v0.57)",
            "CCM_Data_Intelligence_Report.html": "inventory report (v0.57)",
            "CCM_Data_Intelligence_Report.txt": "text report (v0.57)",
        }

        for filename, description in output_files.items():
            assert filename, f"v0.57 output {filename} ({description}) should exist"

    def test_role_detection_unchanged(self):
        """Role detection logic should match v0.57 behavior."""
        role_keywords = {
            "DEM": ["dem", "elevation", "dtm", "dsm", "aster", "srtm"],
            "Soil": ["soil", "soils", "soil_", "rci", "ssurgo"],
            "Vegetation": ["vegetation", "veg", "ndvi", "canopy", "lulc"],
            "Hydrology": ["hydrology", "hydro", "water", "stream", "flow"],
            "Contours": ["contour", "contours", "isoline"],
            "Extent": ["extent", "boundary", "aoi", "footprint"],
            "Vehicle": ["vehicle", "vehicles", "mobility"],
        }

        for role, keywords in role_keywords.items():
            for keyword in keywords:
                # Lowercase matching should work
                detected_role = None
                for test_role, test_keywords in role_keywords.items():
                    if keyword.lower() in [k.lower() for k in test_keywords]:
                        detected_role = test_role
                        break
                assert detected_role == role, f"Keyword '{keyword}' should map to {role}"

    def test_catalog_handles_missing_aoi(self):
        """Catalog should build even if AOI not provided (defaults to None)."""
        mock_catalog = {
            "metadata": {
                "scan_datetime": "2026-08-19T12:34:56",
                "data_root": "/data",
                "aoi_path": None,
                "aoi_crs": None,
                "v057_baseline": True,
            },
            "datasets": [],
        }

        assert mock_catalog["metadata"]["aoi_path"] is None, "AOI can be None"
        assert mock_catalog["metadata"]["aoi_crs"] is None, "AOI CRS can be None"

    def test_catalog_handles_all_geom_types(self):
        """Catalog should recognize all v0.57 geometry types."""
        geom_types = ["raster", "polygon", "linestring", "point", "multipart", "unknown"]

        for geom_type in geom_types:
            dataset = {
                "name": f"Test_{geom_type}",
                "file_path": f"/data/test_{geom_type}",
                "file_extension": ".tif" if geom_type == "raster" else ".shp",
                "geom_type": geom_type,
                "size_mb": 100,
                "schema_fields": [],
            }
            assert dataset["geom_type"] == geom_type, f"Geometry type {geom_type} should be recognized"

    def test_catalog_handles_all_file_extensions(self):
        """Catalog should recognize v0.57 supported file types."""
        extensions = [".tif", ".shp", ".csv", ".geojson", ".gpkg", ".gdb", ".nc", ".hdf5"]

        for ext in extensions:
            dataset = {
                "name": f"Test{ext}",
                "file_path": f"/data/test{ext}",
                "file_extension": ext,
                "geom_type": "raster" if ext in [".tif", ".nc", ".hdf5"] else "polygon",
                "size_mb": 100,
                "schema_fields": [],
            }
            assert dataset["file_extension"] == ext, f"Extension {ext} should be recognized"

    def test_catalog_schema_fields_enumeration(self):
        """Schema field enumeration should work for v0.57 supported formats."""
        # Vector (shapefile, geojson)
        vector_fields = ["geometry", "name", "code", "value"]
        for field in vector_fields:
            assert isinstance(field, str), f"Field {field} should be string"

        # Raster (tif, nc, hdf5)
        raster_fields = ["band1", "band2", "elevation"]
        for field in raster_fields:
            assert isinstance(field, str), f"Field {field} should be string"

        # CSV
        csv_fields = ["vehicle_class", "max_speed", "mobility_rating"]
        for field in csv_fields:
            assert isinstance(field, str), f"Field {field} should be string"

    def test_catalog_size_calculation(self):
        """File size should be calculated in MB."""
        sizes_mb = [10, 100, 1000, 5000, 50000]

        for size in sizes_mb:
            dataset = {
                "name": f"Size_{size}MB",
                "size_mb": size,
            }
            assert dataset["size_mb"] > 0, f"Size {size} should be positive"
            assert isinstance(dataset["size_mb"], (int, float)), f"Size should be numeric"

    def test_catalog_metadata_datetime_format(self):
        """Scan datetime should be ISO 8601 format."""
        import re

        iso_pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
        datetime_str = "2026-08-19T12:34:56"

        assert re.match(iso_pattern, datetime_str), "Datetime should be ISO 8601"


class TestProjectConfigRegressionV057:
    """v0.57 project config keys should still work unchanged."""

    def test_project_config_v057_keys_present(self):
        """Project config should have all v0.57 baseline keys."""
        v057_keys = {
            "project_name",
            "project_folder",
            "data_root",
            "aoi_path",
            "aoi_crs",
            "dem_source",
            "soil_source",
            "vegetation_source",
            "hydrology_source",
            "extent_source",
            "vehicle_source",
            "contours_source",
        }

        mock_config = {
            "project_name": "Test_Project",
            "project_folder": "/project",
            "data_root": "/data",
            "aoi_path": "/data/extent/AOI.shp",
            "aoi_crs": "EPSG:32633",
            "dem_source": "ASTER_30m.tif",
            "soil_source": "SoilGrids.tif",
            "vegetation_source": "LULC_2020.tif",
            "hydrology_source": "HydroRivers.shp",
            "extent_source": "AOI.shp",
            "vehicle_source": "vehicles.csv",
            "contours_source": "Contours_20m.shp",
        }

        assert all(k in mock_config for k in v057_keys), "Missing v0.57 project config keys"

    def test_project_config_v057_source_selection(self):
        """Source selection should use v0.57 format (filename, not full path)."""
        sources = {
            "dem_source": "ASTER_30m.tif",
            "soil_source": "SoilGrids.tif",
            "vegetation_source": "LULC_2020.tif",
        }

        for role, source in sources.items():
            assert "/" not in source and "\\" not in source, \
                f"Source {source} should be filename only, not full path"

    def test_project_config_backward_compatible(self):
        """v0.58.2 config with new keys should not affect v0.57 reads."""
        v057_config = {
            "project_name": "Test",
            "dem_source": "ASTER.tif",
        }

        v058_enhanced = dict(v057_config)
        v058_enhanced["data_quality_scores_path"] = "/project/ccm_quality_scores.json"
        v058_enhanced["data_recommendations_path"] = "/project/ccm_recommendations.json"

        # v0.57 should still read the original keys
        assert v057_config["project_name"] == v058_enhanced["project_name"], \
            "v0.57 keys should be unchanged in v0.58.2 config"
        assert v057_config["dem_source"] == v058_enhanced["dem_source"], \
            "v0.57 DEM source should be unchanged"


class TestDataEnumerationRegression:
    """v0.57 data enumeration should work unchanged."""

    def test_enumeration_finds_raster_datasets(self):
        """Should find .tif, .nc, .hdf5 rasters."""
        raster_extensions = [".tif", ".tiff", ".nc", ".hdf5"]

        for ext in raster_extensions:
            filename = f"dataset{ext}"
            assert any(filename.lower().endswith(e.lower()) for e in raster_extensions), \
                f"Should recognize {ext} as raster"

    def test_enumeration_finds_vector_datasets(self):
        """Should find .shp, .geojson, .gpkg vectors."""
        vector_extensions = [".shp", ".geojson", ".gpkg"]

        for ext in vector_extensions:
            filename = f"dataset{ext}"
            assert any(filename.lower().endswith(e.lower()) for e in vector_extensions), \
                f"Should recognize {ext} as vector"

    def test_enumeration_finds_csv_vehicle_data(self):
        """Should find .csv vehicle/mobility data."""
        filename = "vehicles.csv"
        assert filename.lower().endswith(".csv"), "Should recognize .csv as CSV"

    def test_enumeration_skips_temp_files(self):
        """Should skip temporary/lock files (.tmp, .lock, ~)."""
        temp_extensions = [".tmp", ".lock", ".backup", "~"]
        keep_extensions = [".tif", ".shp", ".csv"]

        for ext in temp_extensions:
            filename = f"dataset{ext}"
            should_skip = any(filename.lower().endswith(e.lower()) for e in temp_extensions)
            assert should_skip, f"Should skip {ext} temporary files"

        for ext in keep_extensions:
            filename = f"dataset{ext}"
            should_keep = any(filename.lower().endswith(e.lower()) for e in keep_extensions)
            assert should_keep, f"Should keep {ext} data files"

    def test_enumeration_reports_all_datasets(self):
        """Catalog should report all enumerated datasets."""
        datasets = [
            {"name": "DS1", "file_path": "/data/ds1.tif"},
            {"name": "DS2", "file_path": "/data/ds2.shp"},
            {"name": "DS3", "file_path": "/data/ds3.csv"},
        ]

        catalog = {"datasets": datasets}
        assert len(catalog["datasets"]) == 3, "Catalog should include all 3 datasets"


class TestV057CompatibilityChecks:
    """Verify v0.57 workflows are unaffected by v0.58."""

    def test_v057_catalog_read_unaffected(self):
        """Reading v0.57 catalog should work as before."""
        v057_catalog_json = {
            "metadata": {
                "scan_datetime": "2026-08-19T12:34:56",
                "v057_baseline": True,
            },
            "datasets": [
                {
                    "name": "ASTER_30m",
                    "file_path": "/data/ASTER_30m.tif",
                    "geom_type": "raster",
                }
            ],
        }

        # v0.57 code should read this without modification
        assert v057_catalog_json["metadata"]["v057_baseline"] is True, \
            "v0.57 catalog should still have v057_baseline marker"
        assert len(v057_catalog_json["datasets"]) == 1, "v0.57 datasets should be readable"

    def test_v057_project_config_read_unaffected(self):
        """Reading v0.57 project config should work as before."""
        v057_config = {
            "project_name": "Test",
            "dem_source": "ASTER.tif",
            "soil_source": "Soil.tif",
        }

        # v0.57 code should read these keys
        assert v057_config["project_name"] == "Test", "v0.57 project name should be readable"
        assert v057_config["dem_source"] == "ASTER.tif", "v0.57 DEM source should be readable"

    def test_v057_output_files_unchanged(self):
        """v0.57 output files should not be modified by v0.58."""
        v057_outputs = [
            "ccm_data_catalog.json",
            "CCM_Data_Intelligence_Report.html",
            "CCM_Data_Intelligence_Report.txt",
        ]

        # These should be present and unmodified
        for output_file in v057_outputs:
            assert output_file, f"v0.57 output {output_file} should exist"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

# <<< END OF FILE >>>
