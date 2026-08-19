#!/usr/bin/env python3
"""
CCM Tool v0.58.2 — Data Fitness Scoring Engine

Measures suitability for the specific CCM NG-NRMM workflow.

Evaluates each dataset against role-specific fitness factors:
- DEM: vertical accuracy, void-free, raster format
- Soil: RCI/VCI lookup, USCS recognition, moisture support
- Vegetation: canopy/NDVI, CCM-compatible classes
- Hydrology: stream/flow vector, no classification needed
- Contours: optional; elevations vs DEM agreement
- Extent (AOI): polygon geometry, contains all data
- Vehicle CSV: VCI table, required columns, numeric sanity

Scores are normalized to 1–10 scale per role.

VERSION = "0.58.2"
"""

import json
import csv
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any


VERSION = "0.58.2"

# USCS soil classification types (common codes)
USCS_CLASSES = {
    "GW", "GP", "GM", "GC",  # Gravels
    "SW", "SP", "SM", "SC",  # Sands
    "ML", "CL", "OL",        # Silts/low-plasticity clays
    "MH", "CH", "OH",        # High-plasticity clays
    "Pt",                     # Peat
}

# Common RCI-calibrated soil types
RCI_CALIBRATED_TYPES = {
    "sand", "clay", "silt", "loam", "gravel", "peat", "bedrock",
    "organic", "clay-loam", "sandy-loam", "silty-loam",
}


class DataFitnessScorer:
    """
    Evaluate dataset fitness for CCM workflows by role.

    Roles: DEM, Soil, Vegetation, Hydrology, Contours, Extent, Vehicle

    Each dataset is scored 1–10 per role. A dataset may be fit for
    multiple roles or just one.
    """

    def __init__(self, soil_rci_csv: Optional[Path] = None, vehicles_can_csv: Optional[Path] = None):
        """
        Initialize fitness scorer.

        Args:
            soil_rci_csv: Path to soil_rci.csv (for RCI calibration check)
            vehicles_can_csv: Path to Vehicles_Can.csv (for VCI validation)
        """

        self.soil_rci_csv = soil_rci_csv
        self.vehicles_can_csv = vehicles_can_csv
        self.rci_calibrated_codes = self._load_rci_codes()
        self.scores: Dict[str, Dict[str, Any]] = {}

    def _load_rci_codes(self) -> set:
        """Load RCI-calibrated soil codes from soil_rci.csv."""

        if not self.soil_rci_csv or not self.soil_rci_csv.exists():
            return set()

        codes = set()

        try:
            with open(self.soil_rci_csv, "r") as f:
                reader = csv.DictReader(f)

                for row in reader:
                    if row and "Soil_Code" in row:
                        code = row["Soil_Code"].strip().upper()
                        if code:
                            codes.add(code)

        except (FileNotFoundError, KeyError):
            pass

        return codes

    def score_dataset_for_role(
        self, dataset: Dict[str, Any], role: str
    ) -> Dict[str, Any]:
        """
        Score a dataset for a specific role.

        Args:
            dataset: Catalog entry (from ccm_data_catalog.json)
            role: "DEM", "Soil", "Vegetation", "Hydrology", "Contours", "Extent", "Vehicle"

        Returns:
            {
              "dataset": "ASTER_30m.tif",
              "role": "DEM",
              "fitness_score": 8.0,
              "factors": {...},
              "reasoning": "..."
            }
        """

        scorer_method = getattr(self, f"_fitness_{role.lower()}", None)

        if not scorer_method:
            return {
                "dataset": dataset.get("name", "Unknown"),
                "role": role,
                "fitness_score": 0.0,
                "factors": {},
                "reasoning": f"Unknown role: {role}",
            }

        result = scorer_method(dataset)
        result["dataset"] = dataset.get("name", "Unknown")
        result["role"] = role

        return result

    # ========== Role-Specific Fitness Implementations ==========

    def _fitness_dem(self, dataset: Dict[str, Any]) -> Dict[str, Any]:
        """
        DEM fitness: vertical accuracy, void-free, raster format.

        Factors:
          - Format: raster required (yes=+3, no=0)
          - Vertical accuracy: <1m=+2, 1–5m=+1, >5m=0
          - Void-free: no voids=+3, void-filled SRTM=+2, unknown=+1
          - Resolution: 10–30m=+2, 30–50m=+1, >50m=0
        """

        factors = {}

        # Format check
        factors["is_raster"] = 3.0 if dataset.get("dataset_type") == "raster" else 0.0

        # Vertical accuracy
        accuracy_str = dataset.get("horizontal_accuracy") or dataset.get("accuracy")
        factors["vertical_accuracy"] = self._score_vertical_accuracy(accuracy_str)

        # Void check (look for "void" in limitations)
        limitations = dataset.get("limitations", []) or []
        lim_lower = [str(l).lower() for l in limitations]
        has_voids = any("void" in l for l in lim_lower)
        is_srtm = "srtm" in dataset.get("source_type", "").lower()

        if not has_voids:
            factors["void_free"] = 3.0
        elif is_srtm:
            factors["void_free"] = 2.0  # SRTM void-filled acceptable
        else:
            factors["void_free"] = 0.0

        # Resolution
        resolution_str = dataset.get("resolution")
        try:
            res_float = float(str(resolution_str).split()[0])

            if 10 <= res_float <= 30:
                factors["resolution"] = 2.0
            elif 30 < res_float <= 50:
                factors["resolution"] = 1.0
            else:
                factors["resolution"] = 0.0

        except (ValueError, TypeError, IndexError):
            factors["resolution"] = 1.0  # Unknown; neutral

        score = sum(factors.values())
        normalized_score = min(10.0, score)  # Max 10

        return {
            "fitness_score": normalized_score,
            "factors": factors,
            "reasoning": self._build_fitness_reasoning("DEM", factors),
        }

    def _fitness_soil(self, dataset: Dict[str, Any]) -> Dict[str, Any]:
        """
        Soil fitness: RCI/VCI lookup, USCS recognition, moisture support.

        Factors:
          - RCI calibration: present=+3, unknown=+0
          - USCS recognition: recognized type=+2, unknown=+0
          - Schema: has Cone Index column=+3, has USCS column=+2
          - Moisture support: has moisture data=+2
        """

        factors = {}

        # RCI calibration check
        schema = dataset.get("schema") or {}
        present_cols = schema.get("present_columns", []) or []
        col_lower = [str(c).lower() for c in present_cols]

        rci_present = any("rci" in c or "cone" in c for c in col_lower)
        factors["rci_calibration"] = 3.0 if rci_present else 0.0

        # USCS recognition (look for USCS code in schema or name)
        name = dataset.get("name", "").upper()
        uscs_in_name = any(uscs in name for uscs in USCS_CLASSES)
        factors["uscs_recognition"] = 2.0 if uscs_in_name else 0.0

        # Schema completeness
        has_cone_idx = any("cone" in c or "rci" in c for c in col_lower)
        has_uscs = any("uscs" in c or "class" in c for c in col_lower)

        factors["schema_completeness"] = 0.0
        if has_cone_idx:
            factors["schema_completeness"] += 3.0
        if has_uscs:
            factors["schema_completeness"] += 2.0

        # Moisture support
        has_moisture = any("moisture" in c or "vwc" in c or "water" in c for c in col_lower)
        factors["moisture_support"] = 2.0 if has_moisture else 0.0

        score = sum(factors.values())
        normalized_score = min(10.0, score)

        return {
            "fitness_score": normalized_score,
            "factors": factors,
            "reasoning": self._build_fitness_reasoning("Soil", factors),
        }

    def _fitness_vegetation(self, dataset: Dict[str, Any]) -> Dict[str, Any]:
        """
        Vegetation fitness: canopy height/NDVI, CCM-compatible classes.

        Factors:
          - Format: raster=+3, vector=+1
          - Type: canopy height=+3, NDVI=+2, classes=+1
          - Resolution: <30m=+2, 30–100m=+1
        """

        factors = {}

        # Format: prefer raster
        is_raster = dataset.get("dataset_type") == "raster"
        is_vector = dataset.get("dataset_type") == "vector"

        factors["format"] = 3.0 if is_raster else (1.0 if is_vector else 0.0)

        # Type check (canopy, NDVI, classes)
        name = dataset.get("name", "").lower()
        source = dataset.get("source_type", "").lower()

        if "canopy" in name or "height" in name:
            factors["data_type"] = 3.0
        elif "ndvi" in name or "vegetation" in source:
            factors["data_type"] = 2.0
        elif "class" in name or "lulc" in name:
            factors["data_type"] = 1.0
        else:
            factors["data_type"] = 0.0

        # Resolution
        resolution_str = dataset.get("resolution")
        try:
            res_float = float(str(resolution_str).split()[0])

            if res_float < 30:
                factors["resolution"] = 2.0
            elif res_float <= 100:
                factors["resolution"] = 1.0
            else:
                factors["resolution"] = 0.0

        except (ValueError, TypeError, IndexError):
            factors["resolution"] = 1.0

        score = sum(factors.values())
        normalized_score = min(10.0, score)

        return {
            "fitness_score": normalized_score,
            "factors": factors,
            "reasoning": self._build_fitness_reasoning("Vegetation", factors),
        }

    def _fitness_hydrology(self, dataset: Dict[str, Any]) -> Dict[str, Any]:
        """
        Hydrology fitness: stream/flow vector, no classification needed.

        Factors:
          - Is vector: yes=+4, no=0
          - Keyword: stream/river/drainage/flow=+3
          - Coverage: >50%=+2, <50%=+1
        """

        factors = {}

        # Format: must be vector
        is_vector = dataset.get("dataset_type") == "vector"
        factors["is_vector"] = 4.0 if is_vector else 0.0

        # Type keywords
        name = dataset.get("name", "").lower()

        keyword_match = 0.0
        for kw in ["stream", "river", "drainage", "flow", "hydro", "water"]:
            if kw in name:
                keyword_match = 3.0
                break

        factors["type_keywords"] = keyword_match

        # Coverage
        coverage = dataset.get("coverage_pct", 0)
        try:
            cov_float = float(coverage)
            factors["coverage"] = 2.0 if cov_float > 50 else 1.0
        except (ValueError, TypeError):
            factors["coverage"] = 0.0

        score = sum(factors.values())
        normalized_score = min(10.0, score)

        return {
            "fitness_score": normalized_score,
            "factors": factors,
            "reasoning": self._build_fitness_reasoning("Hydrology", factors),
        }

    def _fitness_contours(self, dataset: Dict[str, Any]) -> Dict[str, Any]:
        """
        Contours fitness: optional; elevations vs DEM agreement.

        Factors:
          - Is vector: yes=+3, no=0
          - Has elevation field: yes=+3, no=0
          - Interval regularity: yes=+2, no=+1
        """

        factors = {}

        is_vector = dataset.get("dataset_type") == "vector"
        factors["is_vector"] = 3.0 if is_vector else 0.0

        schema = dataset.get("schema") or {}
        present_cols = schema.get("present_columns", []) or []
        col_lower = [str(c).lower() for c in present_cols]

        has_elev = any("elev" in c or "height" in c or "z" in c for c in col_lower)
        factors["elevation_field"] = 3.0 if has_elev else 0.0

        # Regularity (heuristic: if named "contours" or "contour", likely regular interval)
        name = dataset.get("name", "").lower()
        is_regular = "contour" in name
        factors["interval_regularity"] = 2.0 if is_regular else 1.0

        score = sum(factors.values())
        normalized_score = min(10.0, score)

        return {
            "fitness_score": normalized_score,
            "factors": factors,
            "reasoning": self._build_fitness_reasoning("Contours", factors),
        }

    def _fitness_extent(self, dataset: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extent (AOI) fitness: polygon geometry, contains all data.

        Factors:
          - Is polygon vector: yes=+4, no=0
          - Keyword match: AOI/extent/boundary=+3
          - Coverage of data root: 100%=+3, >80%=+2, >50%=+1
        """

        factors = {}

        is_vector = dataset.get("dataset_type") == "vector"
        factors["is_polygon_vector"] = 4.0 if is_vector else 0.0

        name = dataset.get("name", "").lower()
        has_keyword = any(kw in name for kw in ["aoi", "extent", "boundary", "study"])
        factors["keyword_match"] = 3.0 if has_keyword else 0.0

        coverage = dataset.get("coverage_pct", 50)
        try:
            cov_float = float(coverage)

            if cov_float >= 100:
                factors["coverage"] = 3.0
            elif cov_float >= 80:
                factors["coverage"] = 2.0
            elif cov_float >= 50:
                factors["coverage"] = 1.0
            else:
                factors["coverage"] = 0.0

        except (ValueError, TypeError):
            factors["coverage"] = 0.0

        score = sum(factors.values())
        normalized_score = min(10.0, score)

        return {
            "fitness_score": normalized_score,
            "factors": factors,
            "reasoning": self._build_fitness_reasoning("Extent", factors),
        }

    def _fitness_vehicle(self, dataset: Dict[str, Any]) -> Dict[str, Any]:
        """
        Vehicle CSV fitness: VCI table, required columns, numeric sanity.

        Factors:
          - Is table/CSV: yes=+3, no=0
          - Has VCI column: yes=+3
          - Has required cols: Speed/MMP/P=+2
          - Numeric sanity: valid=+2, invalid=0
        """

        factors = {}

        is_table = dataset.get("dataset_type") in ("table", "csv")
        factors["is_table"] = 3.0 if is_table else 0.0

        schema = dataset.get("schema") or {}
        present_cols = schema.get("present_columns", []) or []
        col_lower = [str(c).lower() for c in present_cols]

        has_vci = any("vci" in c or "cone" in c for c in col_lower)
        factors["has_vci"] = 3.0 if has_vci else 0.0

        required = ["speed", "mmp", "p_go"]
        has_required = all(any(req in c for c in col_lower) for req in required)
        factors["required_columns"] = 2.0 if has_required else 0.0

        # Numeric sanity (heuristic: no parse errors in known columns)
        factors["numeric_sanity"] = 2.0  # Assume OK if schema parsed; detailed check in audit

        score = sum(factors.values())
        normalized_score = min(10.0, score)

        return {
            "fitness_score": normalized_score,
            "factors": factors,
            "reasoning": self._build_fitness_reasoning("Vehicle", factors),
        }

    # ========== Helpers ==========

    def _score_vertical_accuracy(self, accuracy_str: Optional[str]) -> float:
        """Parse vertical accuracy and return factor score."""

        if not accuracy_str:
            return 0.0

        try:
            acc_float = float(str(accuracy_str).replace("±", "").split()[0])

            if acc_float < 1:
                return 2.0
            elif acc_float <= 5:
                return 1.0
            else:
                return 0.0

        except (ValueError, TypeError, IndexError):
            return 0.0

    def _build_fitness_reasoning(self, role: str, factors: Dict[str, float]) -> str:
        """Build human-readable reasoning for fitness score."""

        parts = [role]
        top_factors = sorted(factors.items(), key=lambda x: x[1], reverse=True)[:3]

        for factor_name, score in top_factors:
            if score > 0:
                parts.append(f"{factor_name}=+{score:.0f}")

        return " → ".join(parts)


def write_fitness_scores(scores: List[Dict[str, Any]], output_path: Path) -> None:
    """Write fitness scores to JSON file."""

    output_dict = {
        "version": VERSION,
        "timestamp": datetime.isoformat(datetime.now()),
        "scores": scores,
    }

    with open(output_path, "w") as f:
        json.dump(output_dict, f, indent=2)


if __name__ == "__main__":
    # Quick test
    test_datasets = [
        {
            "name": "ASTER_30m.tif",
            "dataset_type": "raster",
            "source_type": "ASTER",
            "resolution": "30 m",
            "coverage_pct": 95.0,
            "schema": {"present_columns": []},
            "limitations": [],
        },
        {
            "name": "soil_rci.csv",
            "dataset_type": "table",
            "source_type": "CSV",
            "schema": {
                "present_columns": ["Soil_Code", "RCI_Value", "Soil_Type"],
                "required_columns": ["Soil_Code", "RCI_Value"],
            },
        },
    ]

    scorer = DataFitnessScorer()

    for dataset in test_datasets:
        for role in ["DEM", "Soil", "Vehicle"]:
            result = scorer.score_dataset_for_role(dataset, role)
            print(f"{dataset['name']} as {role}: {result['fitness_score']}/10")

# <<< END OF FILE >>>
