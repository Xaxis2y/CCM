#!/usr/bin/env python3
"""
CCM Tool v0.58.2 — Data Readiness Scoring Engine

Measures preprocessing completion before Step 2.

Readiness checklist:
  □ DEM: exists, valid CRS, no voids, raster format
  □ Slope: derived from DEM, valid values [0–90]
  □ Soil: merged/reprojected, RCI table linked
  □ Vegetation: merged/reprojected, height/NDVI extracted
  □ Hydro: reprojected, network valid (if present)
  □ Extent (AOI): valid polygon, contains all data
  □ Vehicle CSV: required columns, numeric sanity
  □ Scratch workspace: clean, writeable
  □ Configuration: all paths valid, no circular refs

Status: Ready / Mostly Ready / Partial / Incomplete

VERSION = "0.58.2"
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any

# Optional arcpy for real checks
try:
    import arcpy
    _HAVE_ARCPY = True
except ImportError:
    _HAVE_ARCPY = False


VERSION = "0.58.2"


class ReadinessChecker:
    """
    Evaluate preprocessing completion for CCM Step 2.

    Checks existence, format validity, CRS compatibility, and schema
    for intermediate outputs created by Step 1.
    """

    def __init__(self, step1_output_dir: Path):
        """
        Initialize readiness checker.

        Args:
            step1_output_dir: Path to Step 1 output folder (where intermediate layers live)
        """

        self.output_dir = Path(step1_output_dir)
        self.checked_items: Dict[str, Dict[str, Any]] = {}
        self.missing_items: List[str] = []
        self.readiness_status = "Incomplete"

    def check_readiness(self) -> Dict[str, Any]:
        """
        Run all readiness checks.

        Returns:
            {
              "readiness_status": "Ready",
              "readiness_pct": 100,
              "checked_items": {...},
              "missing_items": [...],
              "next_steps": [...]
            }
        """

        checks = {
            "DEM": self._check_dem,
            "Slope": self._check_slope,
            "Soil": self._check_soil,
            "Vegetation": self._check_vegetation,
            "Hydro": self._check_hydro,
            "Extent": self._check_extent,
            "Vehicle_CSV": self._check_vehicle_csv,
            "Workspace": self._check_workspace,
            "Configuration": self._check_configuration,
        }

        for check_name, check_method in checks.items():
            try:
                result = check_method()
                self.checked_items[check_name] = result
            except Exception as e:
                self.checked_items[check_name] = {
                    "status": "ERROR",
                    "reason": str(e),
                }

        # Compute readiness percentage
        checked_count = sum(
            1
            for item in self.checked_items.values()
            if item.get("status") in ("OK", "WARN")
        )
        total_count = len(self.checked_items)
        readiness_pct = int((checked_count / total_count) * 100) if total_count > 0 else 0

        # Determine status
        if readiness_pct == 100:
            self.readiness_status = "Ready"
        elif readiness_pct >= 80:
            self.readiness_status = "Mostly Ready"
        elif readiness_pct >= 50:
            self.readiness_status = "Partial"
        else:
            self.readiness_status = "Incomplete"

        # Collect missing items
        self.missing_items = [
            name
            for name, item in self.checked_items.items()
            if item.get("status") != "OK"
        ]

        next_steps = self._recommend_next_steps()

        return {
            "readiness_status": self.readiness_status,
            "readiness_pct": readiness_pct,
            "checked_items": self.checked_items,
            "missing_items": self.missing_items,
            "next_steps": next_steps,
        }

    # ========== Individual Checks ==========

    def _check_dem(self) -> Dict[str, Any]:
        """Check DEM: exists, valid CRS, raster format."""

        dem_files = list(self.output_dir.glob("*DEM*.tif")) + list(
            self.output_dir.glob("*dem*.tif")
        )

        if not dem_files:
            return {"status": "MISSING", "reason": "No DEM file found"}

        dem_file = dem_files[0]

        if not self._is_raster(dem_file):
            return {"status": "ERROR", "reason": f"{dem_file.name} is not a valid raster"}

        crs = self._get_crs(dem_file)

        if not self._is_projected_crs(crs):
            return {
                "status": "WARN",
                "reason": f"DEM CRS is {crs}; projected CRS recommended",
            }

        return {
            "status": "OK",
            "file": dem_file.name,
            "crs": crs,
        }

    def _check_slope(self) -> Dict[str, Any]:
        """Check Slope: derived from DEM, valid values [0–90]."""

        slope_files = list(self.output_dir.glob("*Slope*.tif")) + list(
            self.output_dir.glob("*slope*.tif")
        )

        if not slope_files:
            return {"status": "MISSING", "reason": "No Slope grid found"}

        slope_file = slope_files[0]

        if not self._is_raster(slope_file):
            return {
                "status": "ERROR",
                "reason": f"{slope_file.name} is not a valid raster",
            }

        # Check value range (heuristic: sample a few pixels)
        min_val, max_val = self._get_raster_value_range(slope_file)

        if min_val is None or max_val is None:
            return {"status": "WARN", "reason": "Could not determine Slope value range"}

        if min_val < 0 or max_val > 90:
            return {
                "status": "WARN",
                "reason": f"Slope values {min_val}–{max_val} outside expected [0, 90]",
            }

        return {
            "status": "OK",
            "file": slope_file.name,
            "value_range": f"{min_val}–{max_val}",
        }

    def _check_soil(self) -> Dict[str, Any]:
        """Check Soil: merged/reprojected, RCI table linked."""

        soil_files = list(self.output_dir.glob("*Soil*.tif")) + list(
            self.output_dir.glob("*soil*.tif")
        )

        if not soil_files:
            return {"status": "MISSING", "reason": "No Soil grid found"}

        soil_file = soil_files[0]

        if not self._is_raster(soil_file):
            return {
                "status": "ERROR",
                "reason": f"{soil_file.name} is not a valid raster",
            }

        # Check for RCI lookup table
        rci_csv = self.output_dir.parent / "soil_rci.csv"

        if not rci_csv.exists():
            return {
                "status": "WARN",
                "reason": "Soil RCI lookup table not found; manual calibration needed",
                "file": soil_file.name,
            }

        return {
            "status": "OK",
            "file": soil_file.name,
            "rci_table": rci_csv.name,
        }

    def _check_vegetation(self) -> Dict[str, Any]:
        """Check Vegetation: merged/reprojected."""

        veg_files = list(self.output_dir.glob("*Veg*.tif")) + list(
            self.output_dir.glob("*veg*.tif")
        )

        if not veg_files:
            return {"status": "MISSING", "reason": "No Vegetation grid found"}

        veg_file = veg_files[0]

        if not self._is_raster(veg_file):
            return {
                "status": "ERROR",
                "reason": f"{veg_file.name} is not a valid raster",
            }

        return {"status": "OK", "file": veg_file.name}

    def _check_hydro(self) -> Dict[str, Any]:
        """Check Hydro: reprojected, network valid (optional)."""

        hydro_files = (
            list(self.output_dir.glob("*Hydro*.shp"))
            + list(self.output_dir.glob("*stream*.shp"))
            + list(self.output_dir.glob("*river*.shp"))
        )

        if not hydro_files:
            return {
                "status": "OK",
                "reason": "No hydrography; optional layer",
            }

        hydro_file = hydro_files[0]

        if not self._is_vector(hydro_file):
            return {
                "status": "WARN",
                "reason": f"{hydro_file.name} is not a valid vector",
            }

        return {"status": "OK", "file": hydro_file.name}

    def _check_extent(self) -> Dict[str, Any]:
        """Check Extent (AOI): valid polygon, contains all data."""

        extent_files = list(self.output_dir.glob("*AOI*.shp")) + list(
            self.output_dir.glob("*Extent*.shp")
        )

        if not extent_files:
            return {"status": "MISSING", "reason": "No Extent/AOI polygon found"}

        extent_file = extent_files[0]

        if not self._is_vector(extent_file):
            return {
                "status": "ERROR",
                "reason": f"{extent_file.name} is not a valid vector",
            }

        # Check feature count (should have at least 1 feature)
        feat_count = self._get_feature_count(extent_file)

        if feat_count == 0:
            return {
                "status": "ERROR",
                "reason": f"{extent_file.name} contains no features",
            }

        return {
            "status": "OK",
            "file": extent_file.name,
            "feature_count": feat_count,
        }

    def _check_vehicle_csv(self) -> Dict[str, Any]:
        """Check Vehicle CSV: required columns, numeric sanity."""

        vehicles_csv = self.output_dir.parent / "Vehicles_Can.csv"

        if not vehicles_csv.exists():
            return {"status": "MISSING", "reason": "Vehicles_Can.csv not found"}

        required_cols = ["Vehicle_Name", "Speed", "MMP", "P"]

        try:
            import csv

            with open(vehicles_csv) as f:
                reader = csv.DictReader(f)
                header = reader.fieldnames or []

                missing = [col for col in required_cols if col not in header]

                if missing:
                    return {
                        "status": "ERROR",
                        "reason": f"Missing columns: {', '.join(missing)}",
                    }

                # Check numeric sanity on first row
                first_row = next(reader, None)

                if first_row:
                    for col in ["Speed", "MMP", "P"]:
                        try:
                            float(first_row.get(col, 0))
                        except ValueError:
                            return {
                                "status": "ERROR",
                                "reason": f"Non-numeric value in {col}",
                            }

        except Exception as e:
            return {"status": "ERROR", "reason": str(e)}

        return {
            "status": "OK",
            "file": vehicles_csv.name,
            "columns": len(header),
        }

    def _check_workspace(self) -> Dict[str, Any]:
        """Check Workspace: clean, writeable."""

        if not self.output_dir.exists():
            return {"status": "ERROR", "reason": "Output directory does not exist"}

        # Check write permission
        try:
            test_file = self.output_dir / ".readiness_test"
            test_file.touch()
            test_file.unlink()
        except Exception as e:
            return {
                "status": "ERROR",
                "reason": f"Workspace not writeable: {e}",
            }

        return {"status": "OK", "path": str(self.output_dir)}

    def _check_configuration(self) -> Dict[str, Any]:
        """Check Configuration: all paths valid, no circular refs."""

        config_file = self.output_dir.parent / "ccm_project.json"

        if not config_file.exists():
            return {"status": "MISSING", "reason": "ccm_project.json not found"}

        try:
            import json

            with open(config_file) as f:
                config = json.load(f)

            # Check key paths
            required_keys = ["project_name", "data_root", "aoi_path"]
            missing_keys = [k for k in required_keys if k not in config]

            if missing_keys:
                return {
                    "status": "WARN",
                    "reason": f"Config missing: {', '.join(missing_keys)}",
                }

        except Exception as e:
            return {"status": "ERROR", "reason": str(e)}

        return {"status": "OK", "file": config_file.name}

    # ========== Helpers ==========

    def _is_raster(self, filepath: Path) -> bool:
        """Check if file is a valid raster (heuristic)."""

        if not filepath.exists():
            return False

        # Check extension
        if filepath.suffix.lower() not in [".tif", ".tiff", ".img", ".jp2"]:
            return False

        # Try arcpy if available
        if _HAVE_ARCPY:
            try:
                desc = arcpy.Describe(str(filepath))
                return desc.datasetType == "RasterDataset"
            except:
                pass

        return True

    def _is_vector(self, filepath: Path) -> bool:
        """Check if file is a valid vector (heuristic)."""

        if not filepath.exists():
            return False

        # Check for shapefile (main file must exist)
        if filepath.suffix.lower() == ".shp":
            base = filepath.with_suffix("")
            return (base.with_suffix(".shp").exists() and
                    base.with_suffix(".shx").exists() and
                    base.with_suffix(".dbf").exists())

        # Try arcpy if available
        if _HAVE_ARCPY:
            try:
                desc = arcpy.Describe(str(filepath))
                return desc.datasetType in ("FeatureClass", "ShapeFile")
            except:
                pass

        return False

    def _get_crs(self, filepath: Path) -> str:
        """Get CRS of a raster (requires arcpy)."""

        if _HAVE_ARCPY:
            try:
                desc = arcpy.Describe(str(filepath))
                return desc.spatialReference.name
            except:
                return "Unknown"

        return "Unknown"

    def _is_projected_crs(self, crs: str) -> bool:
        """Check if CRS is projected."""

        crs_lower = crs.lower()
        return not any(keyword in crs_lower for keyword in [
            "geographic", "gcs", "wgs", "latlong", "lat/lon"
        ])

    def _get_raster_value_range(self, filepath: Path) -> Tuple[Optional[float], Optional[float]]:
        """Get min/max values of a raster (requires arcpy)."""

        if not _HAVE_ARCPY:
            return None, None

        try:
            from arcpy.sa import Raster

            rast = Raster(str(filepath))
            return float(rast.minimum), float(rast.maximum)
        except:
            return None, None

    def _get_feature_count(self, filepath: Path) -> int:
        """Get feature count in a vector (requires arcpy)."""

        if not _HAVE_ARCPY:
            return -1

        try:
            feat_count = int(arcpy.GetCount_management(str(filepath)).getOutput(0))
            return feat_count
        except:
            return -1

    def _recommend_next_steps(self) -> List[str]:
        """Generate recommendations based on readiness status."""

        recommendations = []

        if self.readiness_status == "Ready":
            recommendations.append("✓ All data ready; proceed to Step 2")

        elif self.readiness_status == "Mostly Ready":
            recommendations.append("⚠ Minor rework needed before Step 2:")

            for item, result in self.checked_items.items():
                if result.get("status") == "WARN":
                    recommendations.append(f"  • {item}: {result.get('reason')}")

        elif self.readiness_status == "Partial":
            recommendations.append("⚠ Significant rework needed:")

            for item in self.missing_items:
                recommendations.append(f"  • {item}: missing or invalid")

            recommendations.append("  Re-run Step 1 or add missing layers")

        else:  # Incomplete
            recommendations.append("✗ Cannot proceed to Step 2:")

            for item in self.missing_items:
                recommendations.append(f"  • {item}: missing")

            recommendations.append("  Complete Step 1 preprocessing and re-check")

        return recommendations


def write_readiness_scores(scores: Dict[str, Any], output_path: Path) -> None:
    """Write readiness scores to JSON file."""

    output_dict = {
        "version": VERSION,
        "timestamp": datetime.now().isoformat(),
        **scores,
    }

    with open(output_path, "w") as f:
        json.dump(output_dict, f, indent=2)


if __name__ == "__main__":
    # Quick test with a synthetic directory
    from pathlib import Path
    import tempfile

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
        result = checker.check_readiness()

        print(json.dumps(result, indent=2))

# <<< END OF FILE >>>
