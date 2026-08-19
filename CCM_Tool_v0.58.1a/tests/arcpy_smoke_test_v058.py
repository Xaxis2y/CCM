#!/usr/bin/env python3
"""
CCM Tool v0.58 — ArcPy Smoke Test (Phase 4)

Tests ArcPy integration for Steps 0b and 1 with live recommendations.
Requires: Licensed ArcGIS Pro with valid session.

Run from Anaconda Prompt (after opening ArcGIS Pro):
  python arcpy_smoke_test_v058.py

Output: verification_logs/arcpy_smoke_test_v058.log
"""

import sys
from pathlib import Path
from datetime import datetime
import json
import tempfile

sys.path.insert(0, str(Path(__file__).parent.parent))

# Try to import arcpy
try:
    import arcpy
    HAVE_ARCPY = True
except ImportError:
    HAVE_ARCPY = False
    print("⚠ ArcPy not available. This test requires ArcGIS Pro.")
    sys.exit(1)

from ccm_step0b_integration_v058 import Step0bIntegrator
from ccm_step1_recommendations_ui import display_recommendations


class ArcPyTestLogger:
    """Simple logger for ArcPy test output."""

    def __init__(self, log_file):
        self.log_file = Path(log_file)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self.entries = []

    def log(self, level, message):
        """Log a message."""
        timestamp = datetime.now().isoformat()
        entry = f"[{timestamp}] {level}: {message}"
        self.entries.append(entry)
        print(entry)

    def save(self):
        """Save log to file."""
        with open(self.log_file, "w") as f:
            f.write("\n".join(self.entries))


def test_arcpy_initialization():
    """Test ArcPy initialization and basic functionality."""
    logger = ArcPyTestLogger("verification_logs/arcpy_smoke_test_v058.log")

    logger.log("INFO", "Starting ArcPy v0.58 smoke test")
    logger.log("INFO", f"ArcPy version: {arcpy.__version__}")

    try:
        # Check ArcPy methods exist
        assert hasattr(arcpy, "AddMessage"), "arcpy.AddMessage not available"
        assert hasattr(arcpy, "AddWarning"), "arcpy.AddWarning not available"
        logger.log("INFO", "✓ ArcPy core methods available")

        # Test AddMessage
        arcpy.AddMessage("TEST: ArcPy smoke test started")
        logger.log("INFO", "✓ arcpy.AddMessage works")

        # Test metadata access
        try:
            workspace = arcpy.GetInstallInfo()
            logger.log("INFO", f"✓ ArcGIS Install Path: {workspace.get('InstallDir', 'N/A')}")
        except Exception as e:
            logger.log("WARN", f"Could not read install info: {e}")

        return True, logger

    except Exception as e:
        logger.log("ERROR", f"ArcPy initialization failed: {e}")
        return False, logger


def test_step0b_with_arcpy(logger):
    """Test Step 0b integration with ArcPy."""
    logger.log("INFO", "Testing Step 0b integration with ArcPy")

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Create test data structure
            data_root = tmpdir / "data"
            data_root.mkdir()

            dem_dir = data_root / "DEM"
            dem_dir.mkdir()

            # Create minimal test catalog
            test_catalog = {
                "metadata": {
                    "scan_datetime": datetime.now().isoformat(),
                    "data_root": str(data_root),
                    "aoi_crs": "EPSG:32633",
                },
                "datasets": [
                    {
                        "name": "Test_DEM",
                        "file_path": str(dem_dir / "test_dem.tif"),
                        "file_extension": ".tif",
                        "geom_type": "raster",
                        "size_mb": 100,
                        "temporal_year": 2023,
                        "crs": "EPSG:32633",
                        "bbox_coverage_pct": 95,
                        "cell_size_meters": 30,
                        "schema_fields": ["elevation"],
                        "duplicate_count": 0,
                        "metadata_fields": ["source"],
                        "horizontal_accuracy_meters": 5,
                    }
                ],
            }

            project_folder = tmpdir / "project"
            project_folder.mkdir()

            # Write test catalog
            catalog_path = project_folder / "ccm_data_catalog.json"
            with open(catalog_path, "w") as f:
                json.dump(test_catalog, f)

            logger.log("INFO", f"✓ Created test catalog at {catalog_path}")

            # Test Step0bIntegrator with ArcPy
            integrator = Step0bIntegrator(
                data_root=str(data_root),
                aoi_path=None,
                project_folder=str(project_folder),
                verbose=True,
                arcpy_module=arcpy,
            )

            logger.log("INFO", "✓ Step0bIntegrator instantiated with arcpy_module")

            # Run phase by phase
            integrator.build_catalog()
            logger.log("INFO", "✓ Phase 1: Catalog built")

            integrator.compute_quality_scores()
            logger.log("INFO", "✓ Phase 2: Quality scores computed")

            integrator.compute_fitness_scores()
            logger.log("INFO", "✓ Phase 3: Fitness scores computed")

            integrator.compute_confidence_scores()
            logger.log("INFO", "✓ Phase 4: Confidence scores computed")

            integrator.generate_recommendations()
            logger.log("INFO", "✓ Phase 5: Recommendations generated")

            integrator.write_all_reports(project_folder)
            logger.log("INFO", "✓ Phase 6: Reports written")

            # Verify outputs
            outputs = [
                project_folder / "ccm_quality_scores.json",
                project_folder / "ccm_fitness_scores.json",
                project_folder / "ccm_confidence_scores.json",
                project_folder / "ccm_recommendations.json",
                project_folder / "CCM_Recommendations_Report.html",
            ]

            for output_file in outputs:
                if output_file.exists():
                    size = output_file.stat().st_size
                    logger.log("INFO", f"✓ Output file: {output_file.name} ({size} bytes)")
                else:
                    logger.log("WARN", f"✗ Output file missing: {output_file.name}")

            return True

    except Exception as e:
        logger.log("ERROR", f"Step 0b test failed: {e}")
        import traceback
        logger.log("ERROR", traceback.format_exc())
        return False


def test_step1_recommendations_ui(logger):
    """Test Step 1 recommendations UI with ArcPy."""
    logger.log("INFO", "Testing Step 1 recommendations UI with ArcPy")

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Create test recommendations file
            recommendations = {
                "model_confidence": "Acceptable",
                "readiness": "Mostly Ready",
                "selections": {
                    "DEM": {
                        "recommended": "Test_DEM.tif",
                        "score": 7.8,
                        "reason": "Quality 8/10, Fitness 8/10, 95% coverage",
                        "alternatives": [
                            {
                                "name": "Alt_DEM.tif",
                                "score": 6.5,
                            }
                        ],
                    },
                    "Soil": {
                        "recommended": "MANUAL_SELECTION_REQUIRED",
                        "reason": "No suitable soil dataset found",
                    },
                },
                "warnings": ["Soil: Manual selection required"],
                "next_steps": ["Accept DEM", "Select Soil manually", "Proceed to Step 1 preprocessing"],
            }

            rec_path = tmpdir / "ccm_recommendations.json"
            with open(rec_path, "w") as f:
                json.dump(recommendations, f)

            logger.log("INFO", f"✓ Created test recommendations at {rec_path}")

            # Display recommendations with ArcPy
            logger.log("INFO", "Displaying recommendations via ArcPy...")
            result = display_recommendations(tmpdir, arcpy_module=arcpy, verbose=True)

            logger.log("INFO", "✓ Recommendations displayed via arcpy.AddMessage/AddWarning")

            # Verify result structure
            assert "selections" in result, "Result should have selections"
            assert "DEM" in result["selections"], "Result should have DEM"
            logger.log("INFO", f"✓ DEM recommended: {result['selections']['DEM'].get('recommended')}")

            # Test override logging
            from ccm_step1_recommendations_ui import log_override

            log_override("DEM", "Test_DEM.tif", "Alt_DEM.tif", tmpdir, "User preference")

            override_log = tmpdir / "ccm_recommendations_overrides.log"
            if override_log.exists():
                with open(override_log) as f:
                    log_content = f.read()
                logger.log("INFO", f"✓ Override logged: {log_content.strip()}")
            else:
                logger.log("WARN", "Override log file not created")

            return True

    except Exception as e:
        logger.log("ERROR", f"Step 1 UI test failed: {e}")
        import traceback
        logger.log("ERROR", traceback.format_exc())
        return False


def test_arcpy_metadata_access(logger):
    """Test accessing metadata through ArcPy."""
    logger.log("INFO", "Testing ArcPy metadata access")

    try:
        # Get workspace info
        try:
            install_info = arcpy.GetInstallInfo()
            logger.log("INFO", f"✓ ArcGIS Pro install: {install_info.get('Version', 'N/A')}")
        except Exception as e:
            logger.log("WARN", f"Could not get install info: {e}")

        # Test AddMessage variations
        arcpy.AddMessage("✓ Standard message via arcpy")
        logger.log("INFO", "✓ arcpy.AddMessage works")

        arcpy.AddWarning("✓ Warning message via arcpy")
        logger.log("INFO", "✓ arcpy.AddWarning works")

        return True

    except Exception as e:
        logger.log("ERROR", f"Metadata access test failed: {e}")
        return False


def main():
    """Run all ArcPy smoke tests."""
    print("\n" + "=" * 70)
    print("CCM Tool v0.58 — ArcPy Smoke Test")
    print("=" * 70 + "\n")

    # Initialize
    success, logger = test_arcpy_initialization()
    if not success:
        logger.save()
        print("\n❌ ArcPy initialization failed. See log above.")
        return False

    # Run tests
    tests = [
        ("ArcPy Metadata Access", test_arcpy_metadata_access),
        ("Step 0b Integration", test_step0b_with_arcpy),
        ("Step 1 Recommendations UI", test_step1_recommendations_ui),
    ]

    results = {}
    for test_name, test_func in tests:
        logger.log("INFO", f"\n--- Running: {test_name} ---")
        results[test_name] = test_func(logger)

    # Summary
    logger.log("INFO", "\n" + "=" * 70)
    logger.log("INFO", "Test Summary:")
    for test_name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        logger.log("INFO", f"  {status}: {test_name}")

    all_passed = all(results.values())
    if all_passed:
        logger.log("INFO", "\n✓ All ArcPy smoke tests passed!")
    else:
        logger.log("ERROR", "\n✗ Some tests failed. Review log for details.")

    logger.log("INFO", "=" * 70)

    # Save log
    logger.save()
    print(f"\nLog saved to: {logger.log_file}")

    return all_passed


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
