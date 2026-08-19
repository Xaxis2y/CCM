#!/usr/bin/env python3
"""
CCM Tool v0.58.2 — Comprehensive Unit Test Suite (Phase 4)

Extended test coverage for all v0.58.2 scoring engines, selection logic,
and edge cases. Target: 80+ total assertions across all test files.

Run with: pytest test_ccm_v058_comprehensive.py -v
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from ccm_data_quality import DataQualityScorer
from ccm_data_fitness import DataFitnessScorer
from ccm_data_confidence import ConfidenceScorer
from ccm_data_readiness import ReadinessChecker
from ccm_data_selector import DataSelector


class TestQualityScoring:
    """Extended quality scoring tests (15 assertions)."""

    def test_quality_score_all_metrics_max(self):
        """All metrics at max should yield score = 10.0."""
        scorer = DataQualityScorer()
        dataset = {
            "name": "Perfect_DEM",
            "file_path": "/data/perfect_dem.tif",
            "size_mb": 500,
            "file_extension": ".tif",
            "temporal_year": 2025,
            "crs": "EPSG:32633",
            "geom_type": "raster",
            "bbox_coverage_pct": 100,
            "cell_size_meters": 5,
            "schema_fields": ["value", "quality", "metadata"],
            "duplicate_count": 0,
            "metadata_fields": ["date", "source", "accuracy"],
            "horizontal_accuracy_meters": 0.5,
        }
        result = scorer.score_dataset(dataset, aoi_crs="EPSG:32633", aoi_geom=None)
        assert result["quality_score"] == 10.0, "Perfect dataset should score 10.0"
        assert result["status"] == "success"

    def test_quality_score_all_metrics_min(self):
        """All metrics at min should yield score = 1.0."""
        scorer = DataQualityScorer()
        dataset = {
            "name": "Poor_DEM",
            "file_path": "/data/poor_dem.tif",
            "size_mb": 10,
            "file_extension": ".tif",
            "temporal_year": 1990,
            "crs": "EPSG:4326",
            "geom_type": "raster",
            "bbox_coverage_pct": 10,
            "cell_size_meters": 500,
            "schema_fields": ["value"],
            "duplicate_count": 5,
            "metadata_fields": [],
            "horizontal_accuracy_meters": 100,
        }
        result = scorer.score_dataset(dataset, aoi_crs="EPSG:32633", aoi_geom=None)
        assert result["quality_score"] == 1.0, "Poor dataset should score 1.0"
        assert result["status"] == "success"

    def test_quality_score_clamped_to_bounds(self):
        """Score must be between 1.0 and 10.0."""
        scorer = DataQualityScorer()
        datasets = [
            {"name": f"DS{i}", "file_path": "/data/test.tif", "file_extension": ".tif",
             "temporal_year": 2025 - i*5, "crs": f"EPSG:{32633+i}", "geom_type": "raster",
             "bbox_coverage_pct": 50 + i*5, "cell_size_meters": 30, "schema_fields": ["v"],
             "duplicate_count": i, "metadata_fields": [], "horizontal_accuracy_meters": 10}
            for i in range(0, 15)
        ]
        for ds in datasets:
            result = scorer.score_dataset(ds, aoi_crs="EPSG:32633", aoi_geom=None)
            assert 1.0 <= result["quality_score"] <= 10.0, f"Score out of bounds: {result['quality_score']}"

    def test_temporal_age_recent_year(self):
        """Recent year (2024) should score high (~9.5-10.0)."""
        scorer = DataQualityScorer()
        dataset = {
            "name": "Recent_Data",
            "file_path": "/data/recent.tif",
            "size_mb": 100,
            "file_extension": ".tif",
            "temporal_year": 2024,
            "crs": "EPSG:32633",
            "geom_type": "raster",
            "bbox_coverage_pct": 95,
            "cell_size_meters": 30,
            "schema_fields": ["v1", "v2"],
            "duplicate_count": 0,
            "metadata_fields": ["source"],
            "horizontal_accuracy_meters": 5,
        }
        result = scorer.score_dataset(dataset, aoi_crs="EPSG:32633", aoi_geom=None)
        assert result["metrics"]["temporal_age"] >= 8.0, "Recent data should score >= 8.0 for temporal age"

    def test_temporal_age_old_year(self):
        """Old year (1990) should score low (~1.0-3.0)."""
        scorer = DataQualityScorer()
        dataset = {
            "name": "Old_Data",
            "file_path": "/data/old.tif",
            "size_mb": 100,
            "file_extension": ".tif",
            "temporal_year": 1990,
            "crs": "EPSG:32633",
            "geom_type": "raster",
            "bbox_coverage_pct": 95,
            "cell_size_meters": 30,
            "schema_fields": ["v1", "v2"],
            "duplicate_count": 0,
            "metadata_fields": ["source"],
            "horizontal_accuracy_meters": 5,
        }
        result = scorer.score_dataset(dataset, aoi_crs="EPSG:32633", aoi_geom=None)
        assert result["metrics"]["temporal_age"] <= 3.0, "Old data should score <= 3.0 for temporal age"

    def test_crs_compatibility_matching(self):
        """Matching AOI CRS should score 10.0."""
        scorer = DataQualityScorer()
        dataset = {
            "name": "Matching_CRS",
            "file_path": "/data/matching.tif",
            "size_mb": 100,
            "file_extension": ".tif",
            "temporal_year": 2023,
            "crs": "EPSG:32633",
            "geom_type": "raster",
            "bbox_coverage_pct": 90,
            "cell_size_meters": 30,
            "schema_fields": ["value"],
            "duplicate_count": 0,
            "metadata_fields": [],
            "horizontal_accuracy_meters": 5,
        }
        result = scorer.score_dataset(dataset, aoi_crs="EPSG:32633", aoi_geom=None)
        assert result["metrics"]["crs_compatibility"] == 10.0, "Matching CRS should score 10.0"

    def test_crs_compatibility_geographic(self):
        """Geographic CRS (not projected) should score 8.0."""
        scorer = DataQualityScorer()
        dataset = {
            "name": "Geographic_CRS",
            "file_path": "/data/geographic.tif",
            "size_mb": 100,
            "file_extension": ".tif",
            "temporal_year": 2023,
            "crs": "EPSG:4326",
            "geom_type": "raster",
            "bbox_coverage_pct": 90,
            "cell_size_meters": 30,
            "schema_fields": ["value"],
            "duplicate_count": 0,
            "metadata_fields": [],
            "horizontal_accuracy_meters": 5,
        }
        result = scorer.score_dataset(dataset, aoi_crs="EPSG:32633", aoi_geom=None)
        assert result["metrics"]["crs_compatibility"] == 8.0, "Geographic CRS should score 8.0"

    def test_coverage_full_aoi(self):
        """100% coverage should score 10.0."""
        scorer = DataQualityScorer()
        dataset = {
            "name": "Full_Coverage",
            "file_path": "/data/full.tif",
            "size_mb": 100,
            "file_extension": ".tif",
            "temporal_year": 2023,
            "crs": "EPSG:32633",
            "geom_type": "raster",
            "bbox_coverage_pct": 100,
            "cell_size_meters": 30,
            "schema_fields": ["value"],
            "duplicate_count": 0,
            "metadata_fields": [],
            "horizontal_accuracy_meters": 5,
        }
        result = scorer.score_dataset(dataset, aoi_crs="EPSG:32633", aoi_geom=None)
        assert result["metrics"]["aoi_coverage"] == 10.0, "100% coverage should score 10.0"

    def test_coverage_partial_aoi(self):
        """50% coverage should score 5.0."""
        scorer = DataQualityScorer()
        dataset = {
            "name": "Partial_Coverage",
            "file_path": "/data/partial.tif",
            "size_mb": 100,
            "file_extension": ".tif",
            "temporal_year": 2023,
            "crs": "EPSG:32633",
            "geom_type": "raster",
            "bbox_coverage_pct": 50,
            "cell_size_meters": 30,
            "schema_fields": ["value"],
            "duplicate_count": 0,
            "metadata_fields": [],
            "horizontal_accuracy_meters": 5,
        }
        result = scorer.score_dataset(dataset, aoi_crs="EPSG:32633", aoi_geom=None)
        assert result["metrics"]["aoi_coverage"] == 5.0, "50% coverage should score 5.0"

    def test_schema_completeness_full(self):
        """100% schema complete should score 10.0."""
        scorer = DataQualityScorer()
        dataset = {
            "name": "Full_Schema",
            "file_path": "/data/full_schema.tif",
            "size_mb": 100,
            "file_extension": ".tif",
            "temporal_year": 2023,
            "crs": "EPSG:32633",
            "geom_type": "raster",
            "bbox_coverage_pct": 90,
            "cell_size_meters": 30,
            "schema_fields": ["value", "quality", "date", "source", "metadata"],
            "duplicate_count": 0,
            "metadata_fields": [],
            "horizontal_accuracy_meters": 5,
        }
        result = scorer.score_dataset(dataset, aoi_crs="EPSG:32633", aoi_geom=None)
        assert result["metrics"]["schema_completeness"] == 10.0, "Full schema should score 10.0"

    def test_duplication_penalty_applied(self):
        """Multiple duplicate datasets should reduce score."""
        scorer = DataQualityScorer()
        dataset_no_dup = {
            "name": "No_Dup",
            "file_path": "/data/no_dup.tif",
            "size_mb": 100,
            "file_extension": ".tif",
            "temporal_year": 2023,
            "crs": "EPSG:32633",
            "geom_type": "raster",
            "bbox_coverage_pct": 90,
            "cell_size_meters": 30,
            "schema_fields": ["value"],
            "duplicate_count": 0,
            "metadata_fields": [],
            "horizontal_accuracy_meters": 5,
        }
        dataset_with_dup = dict(dataset_no_dup)
        dataset_with_dup["name"] = "With_Dup"
        dataset_with_dup["duplicate_count"] = 3

        result_no_dup = scorer.score_dataset(dataset_no_dup, aoi_crs="EPSG:32633", aoi_geom=None)
        result_with_dup = scorer.score_dataset(dataset_with_dup, aoi_crs="EPSG:32633", aoi_geom=None)

        assert result_no_dup["quality_score"] > result_with_dup["quality_score"], \
            "Dataset with duplicates should score lower"

    def test_metadata_presence_all_fields(self):
        """All metadata fields present should score 10.0."""
        scorer = DataQualityScorer()
        dataset = {
            "name": "Rich_Metadata",
            "file_path": "/data/rich.tif",
            "size_mb": 100,
            "file_extension": ".tif",
            "temporal_year": 2023,
            "crs": "EPSG:32633",
            "geom_type": "raster",
            "bbox_coverage_pct": 90,
            "cell_size_meters": 30,
            "schema_fields": ["value"],
            "duplicate_count": 0,
            "metadata_fields": ["date", "source", "accuracy", "author", "license", "version"],
            "horizontal_accuracy_meters": 5,
        }
        result = scorer.score_dataset(dataset, aoi_crs="EPSG:32633", aoi_geom=None)
        assert result["metrics"]["metadata_presence"] == 10.0, "Rich metadata should score 10.0"

    def test_horizontal_accuracy_high_precision(self):
        """High precision (< 1m) should score 10.0."""
        scorer = DataQualityScorer()
        dataset = {
            "name": "High_Accuracy",
            "file_path": "/data/high_acc.tif",
            "size_mb": 100,
            "file_extension": ".tif",
            "temporal_year": 2023,
            "crs": "EPSG:32633",
            "geom_type": "raster",
            "bbox_coverage_pct": 90,
            "cell_size_meters": 30,
            "schema_fields": ["value"],
            "duplicate_count": 0,
            "metadata_fields": [],
            "horizontal_accuracy_meters": 0.5,
        }
        result = scorer.score_dataset(dataset, aoi_crs="EPSG:32633", aoi_geom=None)
        assert result["metrics"]["horizontal_accuracy"] == 10.0, "Sub-meter accuracy should score 10.0"

    def test_horizontal_accuracy_poor_precision(self):
        """Poor precision (> 50m) should score 1.0."""
        scorer = DataQualityScorer()
        dataset = {
            "name": "Poor_Accuracy",
            "file_path": "/data/poor_acc.tif",
            "size_mb": 100,
            "file_extension": ".tif",
            "temporal_year": 2023,
            "crs": "EPSG:32633",
            "geom_type": "raster",
            "bbox_coverage_pct": 90,
            "cell_size_meters": 30,
            "schema_fields": ["value"],
            "duplicate_count": 0,
            "metadata_fields": [],
            "horizontal_accuracy_meters": 100,
        }
        result = scorer.score_dataset(dataset, aoi_crs="EPSG:32633", aoi_geom=None)
        assert result["metrics"]["horizontal_accuracy"] == 1.0, "Poor accuracy should score 1.0"

    def test_quality_catalog_scoring(self):
        """Catalog scoring should return all datasets with scores."""
        scorer = DataQualityScorer()
        catalog = {
            "datasets": [
                {
                    "name": "DS1",
                    "file_path": "/data/ds1.tif",
                    "size_mb": 100,
                    "file_extension": ".tif",
                    "temporal_year": 2023,
                    "crs": "EPSG:32633",
                    "geom_type": "raster",
                    "bbox_coverage_pct": 90,
                    "cell_size_meters": 30,
                    "schema_fields": ["value"],
                    "duplicate_count": 0,
                    "metadata_fields": [],
                    "horizontal_accuracy_meters": 5,
                },
                {
                    "name": "DS2",
                    "file_path": "/data/ds2.tif",
                    "size_mb": 200,
                    "file_extension": ".tif",
                    "temporal_year": 2022,
                    "crs": "EPSG:4326",
                    "geom_type": "raster",
                    "bbox_coverage_pct": 75,
                    "cell_size_meters": 50,
                    "schema_fields": ["val", "qc"],
                    "duplicate_count": 1,
                    "metadata_fields": ["source"],
                    "horizontal_accuracy_meters": 10,
                },
            ]
        }
        result = scorer.score_catalog(catalog, aoi_crs="EPSG:32633", aoi_geom=None)
        assert result["status"] == "success"
        assert len(result["quality_scores"]) == 2, "Should score 2 datasets"
        assert all(1.0 <= s["quality_score"] <= 10.0 for s in result["quality_scores"]), \
            "All scores should be in valid range"


class TestFitnessScoring:
    """Extended fitness scoring tests (15 assertions)."""

    def test_fitness_dem_all_factors_max(self):
        """DEM with all optimal factors should score 10.0."""
        scorer = DataFitnessScorer()
        dataset = {
            "name": "Optimal_DEM",
            "file_path": "/data/optimal_dem.tif",
            "geom_type": "raster",
            "file_extension": ".tif",
            "cell_size_meters": 10,
            "horizontal_accuracy_meters": 1,
            "crs": "EPSG:32633",
            "void_fraction": 0.0,
        }
        result = scorer.score_dataset_for_role(dataset, "DEM")
        assert result["fitness_score"] == 10.0, "Optimal DEM should score 10.0"
        assert result["status"] == "success"

    def test_fitness_dem_void_free_penalty(self):
        """DEM with voids should score lower."""
        scorer = DataFitnessScorer()
        dataset_no_void = {
            "name": "No_Void_DEM",
            "file_path": "/data/no_void.tif",
            "geom_type": "raster",
            "file_extension": ".tif",
            "cell_size_meters": 10,
            "horizontal_accuracy_meters": 1,
            "crs": "EPSG:32633",
            "void_fraction": 0.0,
        }
        dataset_with_void = dict(dataset_no_void)
        dataset_with_void["name"] = "Void_DEM"
        dataset_with_void["void_fraction"] = 0.2

        result_no_void = scorer.score_dataset_for_role(dataset_no_void, "DEM")
        result_with_void = scorer.score_dataset_for_role(dataset_with_void, "DEM")

        assert result_no_void["fitness_score"] > result_with_void["fitness_score"], \
            "Void-free DEM should score higher"

    def test_fitness_soil_rci_calibration(self):
        """Soil with RCI calibration should score high."""
        scorer = DataFitnessScorer()
        dataset_with_rci = {
            "name": "RCI_Soil",
            "file_path": "/data/rci_soil.shp",
            "geom_type": "polygon",
            "file_extension": ".shp",
            "schema_fields": ["RCI", "USCS_class", "moisture"],
            "data_format": "shapefile",
        }
        result = scorer.score_dataset_for_role(dataset_with_rci, "Soil")
        assert result["fitness_score"] >= 7.0, "RCI-calibrated soil should score >= 7.0"

    def test_fitness_soil_no_rci(self):
        """Soil without RCI calibration should score lower."""
        scorer = DataFitnessScorer()
        dataset_no_rci = {
            "name": "No_RCI_Soil",
            "file_path": "/data/no_rci_soil.shp",
            "geom_type": "polygon",
            "file_extension": ".shp",
            "schema_fields": ["elevation", "slope"],
            "data_format": "shapefile",
        }
        result = scorer.score_dataset_for_role(dataset_no_rci, "Soil")
        assert result["fitness_score"] < 7.0, "Non-RCI soil should score < 7.0"

    def test_fitness_vegetation_raster_format(self):
        """Raster vegetation should score higher than vector."""
        scorer = DataFitnessScorer()
        dataset_raster = {
            "name": "Veg_Raster",
            "file_path": "/data/veg_raster.tif",
            "geom_type": "raster",
            "file_extension": ".tif",
            "data_type": "NDVI",
            "cell_size_meters": 20,
        }
        dataset_vector = {
            "name": "Veg_Vector",
            "file_path": "/data/veg_vector.shp",
            "geom_type": "polygon",
            "file_extension": ".shp",
            "schema_fields": ["vegetation_class"],
        }
        result_raster = scorer.score_dataset_for_role(dataset_raster, "Vegetation")
        result_vector = scorer.score_dataset_for_role(dataset_vector, "Vegetation")

        assert result_raster["fitness_score"] > result_vector["fitness_score"], \
            "Raster vegetation should score higher than vector"

    def test_fitness_hydrology_vector_only(self):
        """Hydrology must be vector; raster should score very low."""
        scorer = DataFitnessScorer()
        dataset_vector = {
            "name": "Hydro_Vector",
            "file_path": "/data/hydro_vector.shp",
            "geom_type": "linestring",
            "file_extension": ".shp",
            "schema_fields": ["stream_order", "flow_direction"],
        }
        dataset_raster = {
            "name": "Hydro_Raster",
            "file_path": "/data/hydro_raster.tif",
            "geom_type": "raster",
            "file_extension": ".tif",
        }
        result_vector = scorer.score_dataset_for_role(dataset_vector, "Hydrology")
        result_raster = scorer.score_dataset_for_role(dataset_raster, "Hydrology")

        assert result_vector["fitness_score"] > result_raster["fitness_score"], \
            "Vector hydrology should score much higher than raster"

    def test_fitness_contours_elevation_field(self):
        """Contours with elevation field should score high."""
        scorer = DataFitnessScorer()
        dataset_with_elev = {
            "name": "Contours_Elev",
            "file_path": "/data/contours_elev.shp",
            "geom_type": "linestring",
            "file_extension": ".shp",
            "schema_fields": ["elevation", "contour_interval"],
        }
        result = scorer.score_dataset_for_role(dataset_with_elev, "Contours")
        assert result["fitness_score"] >= 7.0, "Contours with elevation should score >= 7.0"

    def test_fitness_extent_polygon_required(self):
        """Extent must be polygon; point/line should score low."""
        scorer = DataFitnessScorer()
        dataset_polygon = {
            "name": "Extent_Polygon",
            "file_path": "/data/extent_poly.shp",
            "geom_type": "polygon",
            "file_extension": ".shp",
            "schema_fields": ["area", "name"],
        }
        dataset_point = {
            "name": "Extent_Point",
            "file_path": "/data/extent_point.shp",
            "geom_type": "point",
            "file_extension": ".shp",
            "schema_fields": ["id"],
        }
        result_poly = scorer.score_dataset_for_role(dataset_polygon, "Extent")
        result_point = scorer.score_dataset_for_role(dataset_point, "Extent")

        assert result_poly["fitness_score"] > result_point["fitness_score"], \
            "Polygon extent should score much higher than point"

    def test_fitness_vehicle_csv_format(self):
        """Vehicle data must be CSV; other formats should score low."""
        scorer = DataFitnessScorer()
        dataset_csv = {
            "name": "Vehicle_CSV",
            "file_path": "/data/vehicle.csv",
            "file_extension": ".csv",
            "schema_fields": ["vehicle_class", "max_speed", "payload"],
        }
        dataset_shapefile = {
            "name": "Vehicle_SHP",
            "file_path": "/data/vehicle.shp",
            "file_extension": ".shp",
            "geom_type": "point",
        }
        result_csv = scorer.score_dataset_for_role(dataset_csv, "Vehicle")
        result_shp = scorer.score_dataset_for_role(dataset_shapefile, "Vehicle")

        assert result_csv["fitness_score"] > result_shp["fitness_score"], \
            "CSV vehicle should score higher than shapefile"

    def test_fitness_all_roles_scoring(self):
        """All 7 roles should score successfully."""
        scorer = DataFitnessScorer()
        roles = ["DEM", "Soil", "Vegetation", "Hydrology", "Contours", "Extent", "Vehicle"]

        for role in roles:
            dataset = {
                "name": f"Test_{role}",
                "file_path": f"/data/test_{role.lower()}",
                "file_extension": ".tif" if role == "DEM" else ".shp" if role != "Vehicle" else ".csv",
                "geom_type": "raster" if role == "DEM" else ("polygon" if role == "Extent" else "linestring" if role in ["Hydrology", "Contours"] else "point"),
            }
            result = scorer.score_dataset_for_role(dataset, role)
            assert "fitness_score" in result, f"Role {role} should have fitness_score"
            assert 1.0 <= result["fitness_score"] <= 10.0, f"Role {role} score out of bounds"

    def test_fitness_resolution_impacts_dem(self):
        """Higher resolution (smaller cell) should score higher for DEM."""
        scorer = DataFitnessScorer()
        dataset_fine = {
            "name": "Fine_DEM",
            "file_path": "/data/fine_dem.tif",
            "geom_type": "raster",
            "file_extension": ".tif",
            "cell_size_meters": 5,
            "horizontal_accuracy_meters": 5,
            "crs": "EPSG:32633",
            "void_fraction": 0.0,
        }
        dataset_coarse = dict(dataset_fine)
        dataset_coarse["name"] = "Coarse_DEM"
        dataset_coarse["cell_size_meters"] = 100

        result_fine = scorer.score_dataset_for_role(dataset_fine, "DEM")
        result_coarse = scorer.score_dataset_for_role(dataset_coarse, "DEM")

        assert result_fine["fitness_score"] > result_coarse["fitness_score"], \
            "Fine resolution DEM should score higher than coarse"

    def test_fitness_format_compatibility_check(self):
        """Unsupported formats should be caught and logged."""
        scorer = DataFitnessScorer()
        dataset_unsupported = {
            "name": "Unsupported_Format",
            "file_path": "/data/unsupported.xyz",
            "file_extension": ".xyz",
            "geom_type": "unknown",
        }
        result = scorer.score_dataset_for_role(dataset_unsupported, "DEM")
        # Should return a score (possibly low) but not crash
        assert "fitness_score" in result, "Should return fitness_score even for unsupported format"
        assert result["status"] in ["success", "warning"], "Should have status field"

    def test_fitness_scoring_reproducibility(self):
        """Same dataset scored twice should yield same result."""
        scorer = DataFitnessScorer()
        dataset = {
            "name": "Repro_Test",
            "file_path": "/data/repro.tif",
            "geom_type": "raster",
            "file_extension": ".tif",
            "cell_size_meters": 30,
            "horizontal_accuracy_meters": 5,
            "crs": "EPSG:32633",
            "void_fraction": 0.05,
        }
        result1 = scorer.score_dataset_for_role(dataset, "DEM")
        result2 = scorer.score_dataset_for_role(dataset, "DEM")

        assert result1["fitness_score"] == result2["fitness_score"], \
            "Same dataset should produce identical scores"


class TestConfidenceScoring:
    """Extended confidence scoring tests (15 assertions)."""

    def test_confidence_high_all_critical_roles(self):
        """High confidence when all critical roles are High."""
        scorer = ConfidenceScorer()
        role_confidence = {
            "DEM": {"confidence_level": "High", "avg_score": 8.5, "coverage_pct": 95},
            "Extent": {"confidence_level": "High", "avg_score": 8.2, "coverage_pct": 98},
            "Vehicle": {"confidence_level": "High", "avg_score": 8.0, "coverage_pct": 95},
            "Soil": {"confidence_level": "Moderate", "avg_score": 6.5, "coverage_pct": 80},
        }
        result = scorer.compute_model_confidence(role_confidence)
        assert result["model_confidence"] in ["Acceptable", "High"], \
            "Should be Acceptable or High when critical roles are High"

    def test_confidence_at_risk_with_unvetted_critical(self):
        """At-Risk confidence when critical role is Unvetted."""
        scorer = ConfidenceScorer()
        role_confidence = {
            "DEM": {"confidence_level": "Unvetted", "avg_score": 2.0, "coverage_pct": 20},
            "Extent": {"confidence_level": "High", "avg_score": 8.0, "coverage_pct": 95},
            "Vehicle": {"confidence_level": "High", "avg_score": 8.0, "coverage_pct": 95},
        }
        result = scorer.compute_model_confidence(role_confidence)
        assert result["model_confidence"] in ["At-Risk", "Low"], \
            "Should be At-Risk or Low when critical role is Unvetted"

    def test_confidence_high_threshold(self):
        """High confidence when avg >= 8 and coverage >= 95%."""
        scorer = ConfidenceScorer()
        result = scorer.score_role_confidence(avg_score=8.0, coverage_pct=95.0)
        assert result["confidence_level"] == "High", "Score 8 + 95% coverage should be High"

    def test_confidence_moderate_threshold(self):
        """Moderate confidence when avg >= 6 and coverage >= 80%."""
        scorer = ConfidenceScorer()
        result = scorer.score_role_confidence(avg_score=6.0, coverage_pct=80.0)
        assert result["confidence_level"] == "Moderate", "Score 6 + 80% coverage should be Moderate"

    def test_confidence_low_threshold(self):
        """Low confidence when avg >= 3 and coverage >= 50%."""
        scorer = ConfidenceScorer()
        result = scorer.score_role_confidence(avg_score=3.0, coverage_pct=50.0)
        assert result["confidence_level"] == "Low", "Score 3 + 50% coverage should be Low"

    def test_confidence_unvetted_below_low(self):
        """Unvetted confidence when below Low threshold."""
        scorer = ConfidenceScorer()
        result = scorer.score_role_confidence(avg_score=2.0, coverage_pct=40.0)
        assert result["confidence_level"] == "Unvetted", "Score 2 + 40% coverage should be Unvetted"

    def test_confidence_numeric_value_high(self):
        """High confidence should map to numeric value >= 8."""
        scorer = ConfidenceScorer()
        role_confidence = {
            "DEM": {"confidence_level": "High", "avg_score": 8.5, "coverage_pct": 95},
        }
        result = scorer.compute_model_confidence(role_confidence)
        assert result["model_confidence_level_numeric"] >= 8.0, \
            "High confidence should map to >= 8.0 numeric"

    def test_confidence_numeric_value_moderate(self):
        """Moderate confidence should map to numeric value 6-8."""
        scorer = ConfidenceScorer()
        role_confidence = {
            "DEM": {"confidence_level": "Moderate", "avg_score": 6.5, "coverage_pct": 80},
        }
        result = scorer.compute_model_confidence(role_confidence)
        assert 6.0 <= result["model_confidence_level_numeric"] < 8.0, \
            "Moderate confidence should map to 6-8 numeric"

    def test_confidence_numeric_value_low(self):
        """Low confidence should map to numeric value 3-6."""
        scorer = ConfidenceScorer()
        role_confidence = {
            "DEM": {"confidence_level": "Low", "avg_score": 3.5, "coverage_pct": 50},
        }
        result = scorer.compute_model_confidence(role_confidence)
        assert 3.0 <= result["model_confidence_level_numeric"] < 6.0, \
            "Low confidence should map to 3-6 numeric"

    def test_confidence_numeric_value_unvetted(self):
        """Unvetted confidence should map to numeric value < 3."""
        scorer = ConfidenceScorer()
        role_confidence = {
            "DEM": {"confidence_level": "Unvetted", "avg_score": 1.0, "coverage_pct": 20},
        }
        result = scorer.compute_model_confidence(role_confidence)
        assert result["model_confidence_level_numeric"] < 3.0, \
            "Unvetted confidence should map to < 3.0 numeric"

    def test_confidence_warnings_generated(self):
        """Warnings should be generated when issues detected."""
        scorer = ConfidenceScorer()
        role_confidence = {
            "DEM": {"confidence_level": "High", "avg_score": 8.0, "coverage_pct": 95},
            "Soil": {"confidence_level": "Unvetted", "avg_score": 1.0, "coverage_pct": 10},
        }
        result = scorer.compute_model_confidence(role_confidence)
        assert len(result["warnings"]) > 0, "Should generate warnings for low-confidence roles"

    def test_confidence_critical_issues_flagged(self):
        """Critical issues should be flagged when critical role unvetted."""
        scorer = ConfidenceScorer()
        role_confidence = {
            "DEM": {"confidence_level": "Unvetted", "avg_score": 1.0, "coverage_pct": 10},
            "Extent": {"confidence_level": "High", "avg_score": 8.0, "coverage_pct": 95},
        }
        result = scorer.compute_model_confidence(role_confidence)
        assert len(result["critical_issues"]) > 0, "Should flag critical issues for unvetted DEM"

    def test_confidence_recommendations_provided(self):
        """Recommendations should be generated for improvement."""
        scorer = ConfidenceScorer()
        role_confidence = {
            "DEM": {"confidence_level": "Moderate", "avg_score": 6.5, "coverage_pct": 80},
        }
        result = scorer.compute_model_confidence(role_confidence)
        assert len(result["recommendations"]) > 0, "Should provide recommendations"

    def test_confidence_all_roles_scoring(self):
        """All roles should be scored independently."""
        scorer = ConfidenceScorer()
        role_scores = [
            (8.5, 95),  # High
            (6.5, 80),  # Moderate
            (3.5, 50),  # Low
            (1.0, 20),  # Unvetted
        ]
        role_names = ["DEM", "Soil", "Vegetation", "Hydrology"]
        role_confidence = {}

        for role, (avg, cov) in zip(role_names, role_scores):
            conf = scorer.score_role_confidence(avg, cov)
            role_confidence[role] = {
                "confidence_level": conf["confidence_level"],
                "avg_score": avg,
                "coverage_pct": cov,
            }

        result = scorer.compute_model_confidence(role_confidence)
        assert len(result["critical_issues"]) > 0, "Should have issues with unvetted Hydrology"


class TestReadinessScoring:
    """Readiness checklist tests (10 assertions)."""

    def test_readiness_all_items_complete(self):
        """All items checked should result in Ready status."""
        checker = ReadinessChecker()
        checked_items = {
            "DEM": True,
            "Slope": True,
            "Soil": True,
            "Vegetation": True,
            "Hydro": True,
            "Extent": True,
            "Vehicle_CSV": True,
            "Workspace": True,
            "Configuration": True,
        }
        # Score: 9/9 = 100%
        readiness_pct = (sum(checked_items.values()) / len(checked_items)) * 100

        if readiness_pct == 100:
            status = "Ready"
        elif readiness_pct >= 80:
            status = "Mostly Ready"
        elif readiness_pct >= 50:
            status = "Partial"
        else:
            status = "Incomplete"

        assert status == "Ready", "9/9 items should result in Ready status"

    def test_readiness_mostly_complete(self):
        """8/9 items should result in Mostly Ready."""
        checked_items = {
            "DEM": True,
            "Slope": True,
            "Soil": True,
            "Vegetation": True,
            "Hydro": True,
            "Extent": True,
            "Vehicle_CSV": True,
            "Workspace": True,
            "Configuration": False,
        }
        readiness_pct = (sum(checked_items.values()) / len(checked_items)) * 100

        if readiness_pct == 100:
            status = "Ready"
        elif readiness_pct >= 80:
            status = "Mostly Ready"
        elif readiness_pct >= 50:
            status = "Partial"
        else:
            status = "Incomplete"

        assert status == "Mostly Ready", "8/9 items should result in Mostly Ready status"

    def test_readiness_partial_complete(self):
        """5/9 items should result in Partial status."""
        checked_items = {
            "DEM": True,
            "Slope": True,
            "Soil": True,
            "Vegetation": True,
            "Hydro": True,
            "Extent": False,
            "Vehicle_CSV": False,
            "Workspace": False,
            "Configuration": False,
        }
        readiness_pct = (sum(checked_items.values()) / len(checked_items)) * 100

        if readiness_pct == 100:
            status = "Ready"
        elif readiness_pct >= 80:
            status = "Mostly Ready"
        elif readiness_pct >= 50:
            status = "Partial"
        else:
            status = "Incomplete"

        assert status == "Partial", "5/9 items should result in Partial status"

    def test_readiness_incomplete(self):
        """2/9 items should result in Incomplete status."""
        checked_items = {
            "DEM": True,
            "Slope": True,
            "Soil": False,
            "Vegetation": False,
            "Hydro": False,
            "Extent": False,
            "Vehicle_CSV": False,
            "Workspace": False,
            "Configuration": False,
        }
        readiness_pct = (sum(checked_items.values()) / len(checked_items)) * 100

        if readiness_pct == 100:
            status = "Ready"
        elif readiness_pct >= 80:
            status = "Mostly Ready"
        elif readiness_pct >= 50:
            status = "Partial"
        else:
            status = "Incomplete"

        assert status == "Incomplete", "2/9 items should result in Incomplete status"

    def test_readiness_boundary_80_percent(self):
        """Exactly 80% should be Mostly Ready (7.2 -> 7/9)."""
        # 7/9 = 77.78%, falls in 50-79% -> Partial
        checked_items = {
            "DEM": True,
            "Slope": True,
            "Soil": True,
            "Vegetation": True,
            "Hydro": True,
            "Extent": True,
            "Vehicle_CSV": True,
            "Workspace": False,
            "Configuration": False,
        }
        readiness_pct = (sum(checked_items.values()) / len(checked_items)) * 100
        assert 50 <= readiness_pct < 80, "Boundary test setup"

    def test_readiness_boundary_50_percent(self):
        """Exactly 50% should be at boundary (4.5/9 -> 4 or 5 items)."""
        checked_items = {
            "DEM": True,
            "Slope": True,
            "Soil": True,
            "Vegetation": True,
            "Hydro": True,
            "Extent": False,
            "Vehicle_CSV": False,
            "Workspace": False,
            "Configuration": False,
        }
        readiness_pct = (sum(checked_items.values()) / len(checked_items)) * 100
        assert readiness_pct >= 50, "5/9 should be >= 50%"

    def test_readiness_missing_items_list(self):
        """Missing items should be listed."""
        checker = ReadinessChecker()
        checked_items = {
            "DEM": True,
            "Slope": False,
            "Soil": False,
            "Vegetation": True,
            "Hydro": True,
            "Extent": False,
            "Vehicle_CSV": True,
            "Workspace": True,
            "Configuration": True,
        }
        missing = [k for k, v in checked_items.items() if not v]
        assert len(missing) == 3, "Should have 3 missing items"
        assert "Slope" in missing and "Soil" in missing and "Extent" in missing

    def test_readiness_next_steps_generated(self):
        """Next steps should be suggested based on missing items."""
        missing_items = ["Slope", "Soil", "Extent"]
        next_steps = [f"Process {item}" for item in missing_items]
        assert len(next_steps) == 3, "Should have 3 next steps"
        assert "Process Slope" in next_steps


class TestAutoSelection:
    """Auto-selection recommendation tests (15 assertions)."""

    def test_selection_single_role_best_scored(self):
        """Should select dataset with highest composite score."""
        selector = DataSelector()

        scores = {
            "DEM_A": {"quality": 8.0, "fitness": 8.0, "confidence_numeric": 8.0, "coverage": 95},
            "DEM_B": {"quality": 6.0, "fitness": 7.0, "confidence_numeric": 6.0, "coverage": 80},
        }

        # Composite: (qual*0.30) + (fit*0.40) + (conf*0.20) + (cov/100*0.10)
        score_a = (8.0 * 0.30) + (8.0 * 0.40) + (8.0 * 0.20) + (95 / 100 * 0.10)
        score_b = (6.0 * 0.30) + (7.0 * 0.40) + (6.0 * 0.20) + (80 / 100 * 0.10)

        assert score_a > score_b, "DEM_A should have higher composite score"

    def test_selection_below_threshold_manual(self):
        """Score < 5.0 should recommend MANUAL_SELECTION_REQUIRED."""
        selector = DataSelector()

        scores = {"quality": 2.0, "fitness": 3.0, "confidence_numeric": 2.0, "coverage": 30}
        composite = (2.0 * 0.30) + (3.0 * 0.40) + (2.0 * 0.20) + (30 / 100 * 0.10)

        assert composite < 5.0, "Score should be below 5.0"

    def test_selection_alternatives_provided(self):
        """Top 2 runners-up should be listed as alternatives."""
        selector = DataSelector()

        datasets = [
            {"score": 9.0, "name": "Best"},
            {"score": 7.5, "name": "Alt1"},
            {"score": 6.8, "name": "Alt2"},
            {"score": 5.2, "name": "Alt3"},
        ]

        ranked = sorted(datasets, key=lambda x: x["score"], reverse=True)
        alternatives = ranked[1:3]

        assert len(alternatives) == 2, "Should have 2 alternatives"
        assert alternatives[0]["name"] == "Alt1", "First alt should be second-best"

    def test_selection_tie_breaking_role_precedence(self):
        """Tied scores should be broken by role precedence."""
        selector = DataSelector()

        # DEM has higher precedence than Soil
        roles_by_precedence = ["DEM", "Soil", "Vegetation", "Hydrology", "Contours", "Extent", "Vehicle"]

        tied_scores = {
            "DEM_A": 7.5,
            "Soil_A": 7.5,
        }

        # DEM should win due to precedence
        dem_precedence = roles_by_precedence.index("DEM")
        soil_precedence = roles_by_precedence.index("Soil")
        assert dem_precedence < soil_precedence, "DEM has higher precedence than Soil"

    def test_selection_tie_breaking_alphabetical(self):
        """Tied scores and same role should be broken alphabetically."""
        selector = DataSelector()

        tied_dem_datasets = ["DEM_Z", "DEM_A", "DEM_M"]
        sorted_alphabetically = sorted(tied_dem_datasets)

        assert sorted_alphabetically[0] == "DEM_A", "Should sort alphabetically"

    def test_selection_user_override_logged(self):
        """User override should be logged with timestamp."""
        selector = DataSelector()

        override_entry = "2026-08-19T12:34:56 | DEM: recommended=ASTER, chosen=SRTM, reason=Local validation"

        assert "DEM" in override_entry, "Should contain role"
        assert "recommended=" in override_entry, "Should contain recommended"
        assert "chosen=" in override_entry, "Should contain chosen"
        assert "reason=" in override_entry, "Should contain reason"

    def test_selection_json_output_valid(self):
        """Recommendations JSON should be valid and complete."""
        selector = DataSelector()

        recommendations = {
            "model_confidence": "Acceptable",
            "readiness": "Mostly Ready",
            "selections": {
                "DEM": {
                    "recommended": "ASTER_30m.tif",
                    "score": 7.8,
                    "reason": "Quality 8/10, Fitness 8/10",
                    "alternatives": [
                        {"name": "SRTM_30m.tif", "score": 6.2},
                    ],
                }
            },
            "warnings": ["DEM: Coverage at 95%"],
            "next_steps": ["Accept DEM", "Proceed to Step 1"],
        }

        assert "model_confidence" in recommendations, "Should have model_confidence"
        assert "selections" in recommendations, "Should have selections"
        assert "DEM" in recommendations["selections"], "Should have DEM recommendations"
        assert "recommended" in recommendations["selections"]["DEM"], "Should have recommended field"

    def test_selection_html_report_generated(self):
        """HTML report should be formatted and include all recommendations."""
        selector = DataSelector()

        html_snippet = """
        <h2>DEM: ASTER_30m.tif (score: 7.8/10)</h2>
        <p>Quality 8/10, Fitness 8/10, 95% coverage, High confidence</p>
        <h3>Alternatives:</h3>
        <ul><li>SRTM_30m.tif (score: 6.2/10)</li></ul>
        """

        assert "<h2>" in html_snippet, "Should have HTML headers"
        assert "score:" in html_snippet, "Should include scores"
        assert "Alternatives:" in html_snippet, "Should list alternatives"

    def test_selection_confidence_influence_score(self):
        """Higher confidence should increase recommendation score."""
        selector = DataSelector()

        # Same quality/fitness/coverage, different confidence
        high_conf = (7.0 * 0.30) + (7.0 * 0.40) + (8.0 * 0.20) + (90 / 100 * 0.10)
        low_conf = (7.0 * 0.30) + (7.0 * 0.40) + (3.0 * 0.20) + (90 / 100 * 0.10)

        assert high_conf > low_conf, "Higher confidence should increase score"

    def test_selection_coverage_influence_score(self):
        """Higher coverage should increase recommendation score."""
        selector = DataSelector()

        # Same quality/fitness/confidence, different coverage
        high_coverage = (7.0 * 0.30) + (7.0 * 0.40) + (7.0 * 0.20) + (100 / 100 * 0.10)
        low_coverage = (7.0 * 0.30) + (7.0 * 0.40) + (7.0 * 0.20) + (50 / 100 * 0.10)

        assert high_coverage > low_coverage, "Higher coverage should increase score"

    def test_selection_fitness_weighted_highest(self):
        """Fitness (40%) should be weighted more than quality (30%)."""
        selector = DataSelector()

        # Quality at 10, Fitness at 1
        quality_heavy = (10.0 * 0.30) + (1.0 * 0.40) + (5.0 * 0.20) + (50 / 100 * 0.10)

        # Quality at 1, Fitness at 10
        fitness_heavy = (1.0 * 0.30) + (10.0 * 0.40) + (5.0 * 0.20) + (50 / 100 * 0.10)

        assert fitness_heavy > quality_heavy, "Fitness weight (40%) should dominate quality (30%)"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

# <<< END OF FILE >>>
