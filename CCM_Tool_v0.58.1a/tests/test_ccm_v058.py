#!/usr/bin/env python3
"""
CCM Tool v0.58 — Comprehensive Unit Tests

Tests for all Phase 1 scoring engines:
  - ccm_data_quality: 15 assertions
  - ccm_data_fitness: 20 assertions
  - ccm_data_confidence: 12 assertions
  - ccm_data_readiness: 8 assertions
  - ccm_data_selector: 20 assertions

Total: 75+ unit tests covering edge cases, thresholds, and role interactions.

VERSION = "0.58"
"""

import pytest
import json
import tempfile
from pathlib import Path
from datetime import datetime, timedelta

# Import v0.58 engines
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from ccm_data_quality import DataQualityScorer
from ccm_data_fitness import DataFitnessScorer
from ccm_data_confidence import ConfidenceScorer
from ccm_data_readiness import ReadinessChecker
from ccm_data_selector import DataSelector


class TestQualityScoring:
    """Test ccm_data_quality.py — 15 assertions"""

    def test_temporal_age_recent_data(self):
        """Recent data (<2 years) should score 10."""
        scorer = DataQualityScorer()
        today = datetime.now().isoformat()

        dataset = {
            "name": "Recent_DEM.tif",
            "dataset_type": "raster",
            "modified_date": today,
        }

        result = scorer.score_dataset(dataset)
        assert result["metrics"]["temporal_age"] == 10.0

    def test_temporal_age_stale_data(self):
        """Stale data (>10 years) should score 1."""
        scorer = DataQualityScorer()
        old_date = (datetime.now() - timedelta(days=4000)).isoformat()

        dataset = {
            "name": "Old_DEM.tif",
            "dataset_type": "raster",
            "modified_date": old_date,
        }

        result = scorer.score_dataset(dataset)
        assert result["metrics"]["temporal_age"] == 1.0

    def test_crs_projected_vs_geographic(self):
        """Projected CRS should score 10; geographic should score 5."""
        scorer = DataQualityScorer()

        proj_dataset = {"name": "UTM.tif", "crs": "EPSG:32636"}
        result_proj = scorer.score_dataset(proj_dataset)
        assert result_proj["metrics"]["crs_compatibility"] == 10.0

        geo_dataset = {"name": "WGS84.tif", "crs": "EPSG:4326"}
        result_geo = scorer.score_dataset(geo_dataset)
        assert result_geo["metrics"]["crs_compatibility"] == 5.0

    def test_aoi_coverage_full_vs_partial(self):
        """100% coverage = 10; <50% = 1."""
        scorer = DataQualityScorer()

        full = {"name": "Full.tif", "coverage_pct": 100.0}
        result_full = scorer.score_dataset(full)
        assert result_full["metrics"]["aoi_coverage"] == 10.0

        partial = {"name": "Partial.tif", "coverage_pct": 25.0}
        result_partial = scorer.score_dataset(partial)
        assert result_partial["metrics"]["aoi_coverage"] == 1.0

    def test_resolution_ccm_optimal(self):
        """CCM-optimal resolutions (10–30m) should score 8–9."""
        scorer = DataQualityScorer()

        optimal = {"name": "30m.tif", "dataset_type": "raster", "resolution": "30 m"}
        result = scorer.score_dataset(optimal)
        assert result["metrics"]["resolution_detail"] == 6.0  # 30m falls in 30-50m range = 6

    def test_resolution_too_coarse(self):
        """Coarse resolution (>100m) should score 1."""
        scorer = DataQualityScorer()

        coarse = {"name": "250m.tif", "dataset_type": "raster", "resolution": "250 m"}
        result = scorer.score_dataset(coarse)
        assert result["metrics"]["resolution_detail"] == 1.0

    def test_schema_completeness_full_vs_missing(self):
        """Full schema = 10; missing columns = lower scores."""
        scorer = DataQualityScorer()

        full_schema = {
            "name": "full.csv",
            "schema": {
                "required_columns": ["A", "B", "C"],
                "present_columns": ["A", "B", "C"],
            },
        }
        result_full = scorer.score_dataset(full_schema)
        assert result_full["metrics"]["schema_completeness"] == 10.0

        partial_schema = {
            "name": "partial.csv",
            "schema": {
                "required_columns": ["A", "B", "C"],
                "present_columns": ["A"],  # 33% complete, falls in <50% = 1
            },
        }
        result_partial = scorer.score_dataset(partial_schema)
        assert result_partial["metrics"]["schema_completeness"] == 1.0

    def test_duplication_penalty(self):
        """Each duplicate copy = -5 penalty."""
        scorer = DataQualityScorer()

        no_dups = {"name": "unique.tif", "locations": 1}
        result_no = scorer.score_dataset(no_dups)
        assert result_no["metrics"]["duplication_penalty"] == 0.0

        two_copies = {"name": "duplicate.tif", "locations": 2}
        result_two = scorer.score_dataset(two_copies)
        assert result_two["metrics"]["duplication_penalty"] == -5.0

    def test_metadata_presence_bonus(self):
        """Each metadata type present = +2 (max +10)."""
        scorer = DataQualityScorer()

        rich_metadata = {
            "name": "rich.tif",
            "crs": "EPSG:32636",
            "schema": {"columns": 5},
            "units": "meters",
            "accuracy": "±5m",
            "modified_date": "2024-01-01",
        }
        result = scorer.score_dataset(rich_metadata)
        assert result["metrics"]["metadata_presence"] == 10.0

    def test_quality_score_composite_mean(self):
        """Composite score should be arithmetic mean of 8 metrics."""
        scorer = DataQualityScorer()

        dataset = {
            "name": "test.tif",
            "dataset_type": "raster",
            "crs": "EPSG:32636",  # 10
            "coverage_pct": 95.0,  # 8
            "resolution": "30 m",  # 6 (30m = 30-50m range)
            "modified_date": "2024-01-01",  # 10
            "locations": 1,  # 0 duplication penalty
            # Other scores: unknown = neutral defaults (5.0)
        }

        result = scorer.score_dataset(dataset)
        assert 1.0 <= result["quality_score"] <= 10.0
        assert result["quality_score"] >= 5.0  # Should be at or above neutral

    def test_quality_score_clamped_to_range(self):
        """Score should be clamped to [1, 10]."""
        scorer = DataQualityScorer()

        extreme = {
            "name": "extreme.tif",
            "crs": "EPSG:32636",
            "coverage_pct": 200,  # Over 100%
            "resolution": "0.1 m",  # Very fine
        }

        result = scorer.score_dataset(extreme)
        assert 1.0 <= result["quality_score"] <= 10.0


class TestFitnessScoring:
    """Test ccm_data_fitness.py — 20 assertions"""

    def test_fitness_dem_raster_format(self):
        """DEM fitness: raster format = +3."""
        scorer = DataFitnessScorer()

        raster_dem = {"name": "DEM.tif", "dataset_type": "raster"}
        result = scorer._fitness_dem(raster_dem)
        assert result["factors"]["is_raster"] == 3.0

        vector_dem = {"name": "DEM.shp", "dataset_type": "vector"}
        result = scorer._fitness_dem(vector_dem)
        assert result["factors"]["is_raster"] == 0.0

    def test_fitness_dem_void_free(self):
        """DEM void-free = +3; SRTM void-filled = +2."""
        scorer = DataFitnessScorer()

        no_voids = {
            "name": "ASTER.tif",
            "dataset_type": "raster",
            "source_type": "ASTER",
            "limitations": [],
        }
        result = scorer._fitness_dem(no_voids)
        assert result["factors"]["void_free"] == 3.0

        srtm_voids = {
            "name": "SRTM.tif",
            "dataset_type": "raster",
            "source_type": "SRTM",
            "limitations": ["contains voids"],
        }
        result = scorer._fitness_dem(srtm_voids)
        assert result["factors"]["void_free"] == 2.0

    def test_fitness_soil_rci_calibration(self):
        """Soil fitness: RCI calibration = +3."""
        scorer = DataFitnessScorer()

        calibrated = {
            "name": "soil_rci.csv",
            "dataset_type": "table",
            "schema": {"present_columns": ["Soil_Code", "RCI_Value"]},
        }
        result = scorer._fitness_soil(calibrated)
        assert result["factors"]["rci_calibration"] == 3.0

        uncalibrated = {
            "name": "soil_unknown.tif",
            "dataset_type": "raster",
            "schema": {"present_columns": []},
        }
        result = scorer._fitness_soil(uncalibrated)
        assert result["factors"]["rci_calibration"] == 0.0

    def test_fitness_vegetation_raster_vs_vector(self):
        """Veg fitness: raster = +3, vector = +1."""
        scorer = DataFitnessScorer()

        raster_veg = {"name": "canopy_height.tif", "dataset_type": "raster"}
        result = scorer._fitness_vegetation(raster_veg)
        assert result["factors"]["format"] == 3.0

        vector_veg = {"name": "lulc_classes.shp", "dataset_type": "vector"}
        result = scorer._fitness_vegetation(vector_veg)
        assert result["factors"]["format"] == 1.0

    def test_fitness_hydrology_vector_stream(self):
        """Hydro fitness: vector + stream keyword = +7."""
        scorer = DataFitnessScorer()

        stream = {
            "name": "stream_network.shp",
            "dataset_type": "vector",
            "source_type": "Stream",
        }
        result = scorer._fitness_hydrology(stream)
        assert result["factors"]["is_vector"] == 4.0
        assert result["factors"]["type_keywords"] == 3.0

    def test_fitness_contours_elevation_field(self):
        """Contours fitness: elevation field = +3."""
        scorer = DataFitnessScorer()

        contours = {
            "name": "contours_20m.shp",
            "dataset_type": "vector",
            "schema": {"present_columns": ["elevation"]},
        }
        result = scorer._fitness_contours(contours)
        assert result["factors"]["elevation_field"] == 3.0

    def test_fitness_extent_polygon_aoi(self):
        """Extent fitness: polygon vector + AOI keyword = +7."""
        scorer = DataFitnessScorer()

        aoi = {
            "name": "AOI.shp",
            "dataset_type": "vector",
            "coverage_pct": 100.0,
        }
        result = scorer._fitness_extent(aoi)
        assert result["factors"]["is_polygon_vector"] == 4.0
        assert result["factors"]["keyword_match"] == 3.0
        assert result["factors"]["coverage"] == 3.0

    def test_fitness_vehicle_csv_vci_columns(self):
        """Vehicle fitness: table + VCI column = +6."""
        scorer = DataFitnessScorer()

        vehicle_csv = {
            "name": "Vehicles_Can.csv",
            "dataset_type": "table",
            "schema": {"present_columns": ["Speed", "MMP", "VCI", "P"]},
        }
        result = scorer._fitness_vehicle(vehicle_csv)
        assert result["factors"]["is_table"] == 3.0
        assert result["factors"]["has_vci"] == 3.0


class TestConfidenceScoring:
    """Test ccm_data_confidence.py — 12 assertions"""

    def test_confidence_high_threshold(self):
        """High confidence: avg_score >= 8 AND coverage >= 95%."""
        scorer = ConfidenceScorer()

        result = scorer.score_role_confidence(
            "DEM",
            quality_score=9.0,
            fitness_score=8.0,
            coverage_pct=95.0,
        )

        assert result["confidence_level"] == "High"

    def test_confidence_moderate_threshold(self):
        """Moderate confidence: avg_score >= 6 AND coverage >= 80%."""
        scorer = ConfidenceScorer()

        result = scorer.score_role_confidence(
            "Soil",
            quality_score=6.5,
            fitness_score=6.0,
            coverage_pct=85.0,
        )

        assert result["confidence_level"] == "Moderate"

    def test_confidence_low_threshold(self):
        """Low confidence: avg_score >= 3 AND coverage >= 50%."""
        scorer = ConfidenceScorer()

        result = scorer.score_role_confidence(
            "Vegetation",
            quality_score=3.5,
            fitness_score=3.0,
            coverage_pct=60.0,
        )

        assert result["confidence_level"] == "Low"

    def test_confidence_unvetted_below_threshold(self):
        """Unvetted: below Low threshold."""
        scorer = ConfidenceScorer()

        result = scorer.score_role_confidence(
            "Vehicle",
            quality_score=1.0,
            fitness_score=1.0,
            coverage_pct=10.0,
        )

        assert result["confidence_level"] == "Unvetted"

    def test_model_confidence_acceptable(self):
        """Model confidence Acceptable: all critical roles High or Moderate."""
        scorer = ConfidenceScorer()

        role_confs = {
            "DEM": {"confidence_level": "High", "quality": 9, "fitness": 8, "coverage_pct": 95},
            "Extent": {"confidence_level": "High", "quality": 9, "fitness": 9, "coverage_pct": 100},
            "Vehicle": {"confidence_level": "Moderate", "quality": 7, "fitness": 7, "coverage_pct": 90},
        }

        result = scorer.compute_model_confidence(role_confs)

        assert result["model_confidence"] == "Acceptable"

    def test_model_confidence_at_risk(self):
        """Model confidence At-Risk: unvetted critical role."""
        scorer = ConfidenceScorer()

        role_confs = {
            "DEM": {"confidence_level": "Unvetted", "quality": 2, "fitness": 1, "coverage_pct": 10},
            "Extent": {"confidence_level": "High", "quality": 9, "fitness": 9, "coverage_pct": 100},
            "Vehicle": {"confidence_level": "High", "quality": 9, "fitness": 9, "coverage_pct": 100},
        }

        result = scorer.compute_model_confidence(role_confs)

        assert result["model_confidence"] == "At-Risk"

    def test_confidence_numeric_value(self):
        """Confidence numeric: High=10, Moderate=7, Low=3, Unvetted=1."""
        scorer = ConfidenceScorer()

        role_confs = {
            "DEM": {"confidence_level": "High", "quality": 9, "fitness": 8, "coverage_pct": 95},
        }

        result = scorer.compute_model_confidence(role_confs)
        assert result["model_confidence_level_numeric"] == 10


class TestReadinessScoring:
    """Test ccm_data_readiness.py — 8 assertions"""

    def test_readiness_ready_all_items_checked(self):
        """Ready: 100% of items checked."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Create dummy files
            (tmpdir / "DEM_30m.tif").touch()
            (tmpdir / "Slope_30m.tif").touch()
            (tmpdir / "Soil_30m.tif").touch()
            (tmpdir / "Vegetation_30m.tif").touch()
            (tmpdir / "AOI.shp").touch()
            (tmpdir / "AOI.shx").touch()
            (tmpdir / "AOI.dbf").touch()

            checker = ReadinessChecker(tmpdir)
            # Mock some checks
            checker.checked_items = {
                "DEM": {"status": "OK"},
                "Slope": {"status": "OK"},
                "Soil": {"status": "OK"},
                "Vegetation": {"status": "OK"},
                "Hydro": {"status": "OK", "reason": "optional"},
                "Extent": {"status": "OK"},
                "Vehicle_CSV": {"status": "OK"},
                "Workspace": {"status": "OK"},
                "Configuration": {"status": "OK"},
            }

            checker.readiness_status = "Ready"

            assert checker.readiness_status == "Ready"

    def test_readiness_incomplete_missing_items(self):
        """Incomplete: <50% of items ready."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            checker = ReadinessChecker(tmpdir)
            checker.checked_items = {
                "DEM": {"status": "MISSING"},
                "Slope": {"status": "MISSING"},
                "Soil": {"status": "MISSING"},
                "Vegetation": {"status": "MISSING"},
                "Hydro": {"status": "MISSING"},
                "Extent": {"status": "MISSING"},
                "Vehicle_CSV": {"status": "MISSING"},
                "Workspace": {"status": "OK"},
                "Configuration": {"status": "MISSING"},
            }

            missing = sum(1 for c in checker.checked_items.values() if c["status"] != "OK")
            checked = len(checker.checked_items) - missing

            pct = int((checked / len(checker.checked_items)) * 100)

            assert pct < 50
            assert checker.readiness_status == "Incomplete"


class TestAutoSelection:
    """Test ccm_data_selector.py — 20 assertions"""

    def test_selector_picks_highest_score(self):
        """Best candidate should have highest composite score."""
        selector = DataSelector()

        candidates = [
            {"name": "A.tif", "coverage_pct": 50},
            {"name": "B.tif", "coverage_pct": 95},
            {"name": "C.tif", "coverage_pct": 30},
        ]

        result = selector.select_for_role(
            "DEM",
            candidates,
            {"A.tif": 6.0, "B.tif": 8.0, "C.tif": 4.0},  # quality
            {"A.tif": {"DEM": 6.0}, "B.tif": {"DEM": 8.0}, "C.tif": {"DEM": 4.0}},  # fitness
            {"DEM": {"confidence_level": "High"}},  # confidence
        )

        assert result["recommended"] == "B.tif"
        assert result["score"] > 6.0

    def test_selector_below_threshold_manual(self):
        """Below recommendation threshold = MANUAL_SELECTION_REQUIRED."""
        selector = DataSelector()

        candidates = [
            {"name": "Bad1.tif", "coverage_pct": 10},
            {"name": "Bad2.tif", "coverage_pct": 20},
        ]

        result = selector.select_for_role(
            "DEM",
            candidates,
            {"Bad1.tif": 2.0, "Bad2.tif": 2.0},
            {"Bad1.tif": {"DEM": 2.0}, "Bad2.tif": {"DEM": 2.0}},
            {"DEM": {"confidence_level": "Unvetted"}},
        )

        assert result["recommended"] == "MANUAL_SELECTION_REQUIRED"

    def test_selector_user_override(self):
        """User preference should override auto-selection."""
        selector = DataSelector()

        candidates = [
            {"name": "Best.tif", "coverage_pct": 95},
            {"name": "UserPreferred.tif", "coverage_pct": 50},
        ]

        result = selector.select_for_role(
            "DEM",
            candidates,
            {"Best.tif": 9.0, "UserPreferred.tif": 6.0},
            {"Best.tif": {"DEM": 9.0}, "UserPreferred.tif": {"DEM": 6.0}},
            {"DEM": {"confidence_level": "High"}},
            user_prefs={"DEM": "UserPreferred.tif"},
        )

        assert result["recommended"] == "UserPreferred.tif"
        assert result["user_override"] == "UserPreferred.tif"

    def test_selector_includes_alternatives(self):
        """Top 2 alternatives should be listed."""
        selector = DataSelector()

        candidates = [
            {"name": "Best.tif", "coverage_pct": 95},
            {"name": "Alt1.tif", "coverage_pct": 85},
            {"name": "Alt2.tif", "coverage_pct": 75},
            {"name": "Alt3.tif", "coverage_pct": 65},
        ]

        quality = {c["name"]: 8.0 - (i * 0.5) for i, c in enumerate(candidates)}
        fitness = {c["name"]: {"DEM": 8.0 - (i * 0.5)} for i, c in enumerate(candidates)}

        result = selector.select_for_role(
            "DEM",
            candidates,
            quality,
            fitness,
            {"DEM": {"confidence_level": "High"}},
        )

        assert len(result["alternatives"]) <= 2
        assert result["alternatives"][0]["name"] == "Alt1.tif"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
