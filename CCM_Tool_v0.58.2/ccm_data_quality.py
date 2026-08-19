#!/usr/bin/env python3
"""
CCM Tool v0.58.2 — Data Quality Scoring Engine

Measures inherent dataset fitness for CCM mobility modeling across eight dimensions:
- Temporal age
- CRS compatibility
- AOI coverage
- Resolution/detail
- Schema completeness
- Duplication penalty
- Metadata presence
- Horizontal accuracy

Scores are normalized to 1–10 scale; composite score is arithmetic mean.

VERSION = "0.58.2"
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any


VERSION = "0.58.2"


class DataQualityScorer:
    """
    Evaluate dataset quality across eight metrics.

    Metrics:
      - temporal_age: 1–10, based on dataset creation/modification date
      - crs_compatibility: 1–10, projected vs geographic
      - aoi_coverage: 1–10, % of AOI bounding box covered
      - resolution_detail: 1–10, raster pixel size vs CCM typical (10–30m)
      - schema_completeness: 1–10, CSV column presence
      - duplication_penalty: -5 per identical copy
      - metadata_presence: +2 per type (CRS, schema, units, accuracy)
      - horizontal_accuracy: 1–10, if known (RMSE or stated accuracy)
    """

    def __init__(self):
        self.scores: Dict[str, Dict[str, Any]] = {}

    def score_dataset(self, dataset: Dict[str, Any]) -> Dict[str, Any]:
        """
        Compute quality score for a single dataset.

        Args:
            dataset: Catalog entry (from ccm_data_catalog.json)
                Keys: name, dataset_type, source_type, resolution, crs,
                      coverage_pct, schema, limitation, created_date, modified_date

        Returns:
            {
              "dataset": "ASTER_30m.tif",
              "quality_score": 7.8,
              "metrics": {
                "temporal_age": 8,
                "crs_compatibility": 10,
                "aoi_coverage": 7,
                "resolution_detail": 8,
                "schema_completeness": 10,
                "duplication_penalty": -5,
                "metadata_presence": 2,
                "horizontal_accuracy": 0
              },
              "reasoning": "..."
            }
        """

        metrics = {
            "temporal_age": self._score_temporal_age(dataset),
            "crs_compatibility": self._score_crs_compatibility(dataset),
            "aoi_coverage": self._score_aoi_coverage(dataset),
            "resolution_detail": self._score_resolution_detail(dataset),
            "schema_completeness": self._score_schema_completeness(dataset),
            "duplication_penalty": self._score_duplication_penalty(dataset),
            "metadata_presence": self._score_metadata_presence(dataset),
            "horizontal_accuracy": self._score_horizontal_accuracy(dataset),
        }

        # Composite: mean of all metrics
        valid_scores = [v for v in metrics.values() if v is not None]
        composite = sum(valid_scores) / len(valid_scores) if valid_scores else 0.0
        composite = max(1.0, min(10.0, composite))  # Clamp to [1, 10]

        result = {
            "dataset": dataset.get("name", "Unknown"),
            "dataset_type": dataset.get("dataset_type", "Unknown"),
            "source_type": dataset.get("source_type", "Unknown"),
            "quality_score": round(composite, 2),
            "metrics": metrics,
            "reasoning": self._build_reasoning(dataset, metrics, composite),
        }

        self.scores[result["dataset"]] = result
        return result

    def score_catalog(self, catalog: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Score all datasets in a catalog.

        Args:
            catalog: Full catalog from ccm_data_catalog.json
                     Keys: data_root, datasets: [...]

        Returns:
            List of quality scores, one per dataset
        """

        results = []
        for dataset in catalog.get("datasets", []):
            result = self.score_dataset(dataset)
            results.append(result)

        return results

    # ========== Metric Implementations ==========

    def _score_temporal_age(self, dataset: Dict[str, Any]) -> float:
        """
        Score based on dataset age.

        Recent (< 2 years) = 10
        2–5 years = 7
        5–10 years = 4
        > 10 years = 1
        Unknown = 5 (neutral)
        """

        modified_str = dataset.get("modified_date") or dataset.get("created_date")

        if not modified_str:
            return 5.0  # Unknown; neutral

        try:
            # Parse ISO 8601 or common date formats
            if "T" in modified_str:
                mod_date = datetime.fromisoformat(modified_str.replace("Z", "+00:00"))
            else:
                mod_date = datetime.strptime(modified_str, "%Y-%m-%d")

            age_years = (datetime.now() - mod_date).days / 365.25

            if age_years < 2:
                return 10.0
            elif age_years < 5:
                return 7.0
            elif age_years < 10:
                return 4.0
            else:
                return 1.0

        except (ValueError, TypeError):
            return 5.0  # Parse error; neutral

    def _score_crs_compatibility(self, dataset: Dict[str, Any]) -> float:
        """
        Score CRS compatibility.

        Projected CRS (UTM, etc.) = 10
        Geographic CRS (WGS84, etc.) = 5
        Unknown = 0
        """

        crs = dataset.get("crs", "").upper()

        if not crs:
            return 0.0

        # Projected: EPSG 32xxx (UTM), 3xxx (regional projections)
        if "EPSG:32" in crs or "EPSG:3" in crs.split(":")[0]:
            return 10.0

        # Geographic: EPSG 4xxx (lat/lon)
        if "EPSG:4" in crs or "WGS" in crs or "LAT/LON" in crs:
            return 5.0

        # Assumed projected if "UTM", "MERCATOR", "TRANSVERSE", etc.
        if any(keyword in crs for keyword in ["UTM", "MERCATOR", "TRANSVERSE"]):
            return 10.0

        # Assumed geographic if "WGS", "NAD", "GCS", "GEOGRAPHIC"
        if any(keyword in crs for keyword in ["WGS", "NAD", "GCS", "GEOGRAPHIC"]):
            return 5.0

        return 0.0

    def _score_aoi_coverage(self, dataset: Dict[str, Any]) -> float:
        """
        Score AOI coverage.

        100% coverage = 10
        90–99% = 8
        70–89% = 6
        50–69% = 4
        <50% = 1
        Unknown = 5
        """

        coverage = dataset.get("coverage_pct")

        if coverage is None:
            return 5.0

        try:
            cov_float = float(coverage)
        except (ValueError, TypeError):
            return 5.0

        if cov_float >= 100:
            return 10.0
        elif cov_float >= 90:
            return 8.0
        elif cov_float >= 70:
            return 6.0
        elif cov_float >= 50:
            return 4.0
        else:
            return 1.0

    def _score_resolution_detail(self, dataset: Dict[str, Any]) -> float:
        """
        Score resolution for rasters.

        Typical CCM resolutions: 10–30m (optimal), 5m–50m (good), >100m (coarse)
        Vector or unknown type: 5 (neutral)

        Finer = higher:
        < 5m = 10
        5–15m = 9
        15–30m = 8
        30–50m = 6
        50–100m = 3
        > 100m = 1
        Unknown = 5
        """

        if dataset.get("dataset_type") != "raster":
            return 5.0  # Vector; neutral

        resolution_str = dataset.get("resolution")

        if not resolution_str:
            return 5.0

        try:
            # Extract numeric value (e.g., "30 m" → 30)
            res_float = float(str(resolution_str).split()[0])
        except (ValueError, TypeError, IndexError):
            return 5.0

        if res_float < 5:
            return 10.0
        elif res_float < 15:
            return 9.0
        elif res_float < 30:
            return 8.0
        elif res_float < 50:
            return 6.0
        elif res_float < 100:
            return 3.0
        else:
            return 1.0

    def _score_schema_completeness(self, dataset: Dict[str, Any]) -> float:
        """
        Score schema completeness for tabular data (CSV, GeoPackage tables).

        This is primarily for calibration data (soil_rci.csv, Vehicles_Can.csv).

        All required columns = 10
        Missing <20% of required = 7
        Missing 20–50% = 3
        Missing >50% = 1
        Not tabular = 5 (neutral)
        Unknown = 5
        """

        schema = dataset.get("schema")

        if not schema or not isinstance(schema, dict):
            return 5.0

        required_cols = schema.get("required_columns", [])
        present_cols = schema.get("present_columns", [])

        if not required_cols:
            return 5.0  # Not a tabular validation

        if not present_cols:
            return 1.0  # Required columns but none present

        coverage = len(present_cols) / len(required_cols)

        if coverage >= 0.95:
            return 10.0
        elif coverage >= 0.80:
            return 7.0
        elif coverage >= 0.50:
            return 3.0
        else:
            return 1.0

    def _score_duplication_penalty(self, dataset: Dict[str, Any]) -> float:
        """
        Penalty for duplicate datasets.

        No duplicates = 0
        Each additional identical copy = -5
        """

        locations = dataset.get("locations", 1)

        try:
            loc_int = int(locations) if locations else 1
        except (ValueError, TypeError):
            return 0.0

        if loc_int <= 1:
            return 0.0

        return -5.0 * (loc_int - 1)

    def _score_metadata_presence(self, dataset: Dict[str, Any]) -> float:
        """
        Bonus for metadata presence.

        Each present metadata type = +2
        Types: crs, schema, units, accuracy, temporal

        Max bonus: +10 (5 types)
        """

        bonus = 0

        if dataset.get("crs"):
            bonus += 2
        if dataset.get("schema"):
            bonus += 2
        if dataset.get("units"):
            bonus += 2
        if dataset.get("accuracy") or dataset.get("horizontal_accuracy"):
            bonus += 2
        if dataset.get("modified_date") or dataset.get("created_date"):
            bonus += 2

        return float(min(bonus, 10))

    def _score_horizontal_accuracy(self, dataset: Dict[str, Any]) -> float:
        """
        Score horizontal accuracy if known.

        < 1m = 10
        1–5m = 8
        5–10m = 6
        10–25m = 3
        > 25m = 1
        Unknown = 0
        """

        accuracy_str = dataset.get("horizontal_accuracy") or dataset.get("accuracy")

        if not accuracy_str:
            return 0.0

        try:
            # Extract numeric value (e.g., "±2m" → 2)
            acc_float = float(str(accuracy_str).replace("±", "").split()[0])
        except (ValueError, TypeError, IndexError):
            return 0.0

        if acc_float < 1:
            return 10.0
        elif acc_float < 5:
            return 8.0
        elif acc_float < 10:
            return 6.0
        elif acc_float < 25:
            return 3.0
        else:
            return 1.0

    # ========== Reasoning & Output ==========

    def _build_reasoning(
        self, dataset: Dict[str, Any], metrics: Dict[str, float], composite: float
    ) -> str:
        """Build human-readable reasoning for quality score."""

        parts = []

        if metrics["temporal_age"] >= 8:
            parts.append("recent data")
        elif metrics["temporal_age"] < 3:
            parts.append("outdated")

        if metrics["crs_compatibility"] >= 9:
            parts.append("projected CRS")
        elif metrics["crs_compatibility"] <= 5:
            parts.append("requires CRS conversion")

        if metrics["aoi_coverage"] >= 9:
            parts.append("complete coverage")
        elif metrics["aoi_coverage"] < 5:
            parts.append("partial coverage")

        if metrics["resolution_detail"] >= 8:
            parts.append("fine resolution")

        if metrics["duplication_penalty"] < 0:
            parts.append("duplicates found")

        reasoning = ", ".join(parts) if parts else "standard quality"

        return f"{dataset.get('name', 'Unknown')}: {reasoning} → {composite}/10"


def write_quality_scores(scores: List[Dict[str, Any]], output_path: Path) -> None:
    """Write quality scores to JSON file."""

    output_dict = {
        "version": VERSION,
        "timestamp": datetime.now().isoformat(),
        "scores": scores,
        "summary": {
            "total_datasets": len(scores),
            "avg_quality": round(
                sum(s["quality_score"] for s in scores) / len(scores), 2
            ) if scores else 0.0,
        },
    }

    with open(output_path, "w") as f:
        json.dump(output_dict, f, indent=2)


if __name__ == "__main__":
    # Quick test: score a synthetic dataset
    test_dataset = {
        "name": "ASTER_30m.tif",
        "dataset_type": "raster",
        "source_type": "ASTER",
        "resolution": "30 m",
        "crs": "EPSG:32636",
        "coverage_pct": 95.0,
        "schema": None,
        "created_date": "2024-03-15T00:00:00Z",
        "modified_date": "2024-06-20T00:00:00Z",
        "horizontal_accuracy": "±30m",
        "limitations": ["None"],
        "locations": 1,
    }

    scorer = DataQualityScorer()
    result = scorer.score_dataset(test_dataset)

    print(json.dumps(result, indent=2))

# <<< END OF FILE >>>
