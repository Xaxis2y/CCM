#!/usr/bin/env python3
"""
CCM Tool v0.58.2 — Step 0b Integration Module

Orchestrates all Phase 1 scoring engines + auto-selection into Step 0b workflow.

Flow:
  1. Build catalog (existing Step 0b)
  2. Compute quality scores (NEW)
  3. Compute fitness scores (NEW)
  4. Compute confidence scores (NEW)
  5. Compute readiness scores (NEW)
  6. Generate auto-recommendations (NEW)
  7. Write all reports and recommendations (NEW)

All existing factual inventory outputs are preserved; v0.58.2 adds scoring,
readiness, and recommendation artifacts.

VERSION = "0.58.2"
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Any

VERSION = "0.58.2"


class Step0bIntegrator:
    """
    Orchestrate complete Step 0b workflow: catalog + scoring + recommendations.

    Usage:
      integrator = Step0bIntegrator(data_root, aoi_path, project_folder)
      results = integrator.run()
      # outputs: catalog.json, quality_scores.json, fitness_scores.json,
      #          confidence_scores.json, readiness_scores.json,
      #          recommendations.json, all HTML reports
    """

    def __init__(
        self,
        data_root: Path,
        aoi_path: Optional[Path] = None,
        project_folder: Optional[Path] = None,
        soil_rci_csv: Optional[Path] = None,
        vehicles_can_csv: Optional[Path] = None,
        log_callback=None,
    ):
        """
        Initialize Step 0b integrator.

        Args:
            data_root: Data root folder to scan
            aoi_path: Optional AOI/extent file for coverage measurement
            project_folder: Output folder for all reports
            soil_rci_csv: Path to soil_rci.csv for calibration check
            vehicles_can_csv: Path to Vehicles_Can.csv for vehicle validation
        """

        self.data_root = Path(data_root)
        self.aoi_path = Path(aoi_path) if aoi_path else None
        self.project_folder = Path(project_folder) if project_folder else self.data_root.parent
        self.soil_rci_csv = Path(soil_rci_csv) if soil_rci_csv else None
        self.vehicles_can_csv = Path(vehicles_can_csv) if vehicles_can_csv else None
        self.log_callback = log_callback

        # State
        self.catalog = None
        self.quality_scores = None
        self.fitness_scores = None
        self.confidence_scores = None
        self.readiness_scores = None
        self.recommendations = None

    def run(self, verbose: bool = True, log_callback=None) -> Dict[str, Any]:
        """
        Run complete Step 0b workflow.

        Args:
            verbose: Print progress messages

        Returns:
            {
              "status": "success" or "error",
              "catalog_path": "...",
              "quality_scores_path": "...",
              "fitness_scores_path": "...",
              "confidence_scores_path": "...",
              "readiness_scores_path": "...",
              "recommendations_path": "...",
              "html_reports": [...]
            }
        """

        callback = log_callback or self.log_callback

        def log(msg):
            if callback:
                callback(f"[CCM 0b v{VERSION}] {msg}")
            elif verbose:
                print(f"[CCM 0b v{VERSION}] {msg}")

        try:
            log("Phase 1: Building catalog...")
            self._build_catalog(log)

            log("Phase 2: Computing quality scores...")
            self._compute_quality_scores(log)

            log("Phase 3: Computing fitness scores...")
            self._compute_fitness_scores(log)

            log("Phase 4: Computing confidence scores...")
            self._compute_confidence_scores(log)

            log("Phase 5: Computing readiness scores...")
            self._compute_readiness_scores(log)

            log("Phase 6: Generating recommendations...")
            self._generate_recommendations(log)

            log("Phase 7: Writing reports...")
            outputs = self._write_all_reports(log)

            log("[OK] Step 0b v0.58.2 complete")

            return {
                "status": "success",
                "version": VERSION,
                "catalog": self.catalog,
                **outputs,
            }

        except Exception as e:
            log(f"[ERROR] {e}")

            return {
                "status": "error",
                "error": str(e),
            }

    # ========== Phase Implementations ==========

    def _build_catalog(self, log):
        """Phase 1: Build catalog using existing Step 0b engine."""

        try:
            import ccm_data_catalog as cat_engine
        except ImportError:
            raise ImportError("ccm_data_catalog not found; ensure it's in PYTHONPATH")

        catalog = cat_engine.build_catalog(
            str(self.data_root),
            aoi_path=str(self.aoi_path) if self.aoi_path else None,
            project_folder=str(self.project_folder),
        )

        if catalog.get("error"):
            raise RuntimeError(f"Catalog build failed: {catalog.get('error')}")

        self.catalog = self._normalise_catalog(catalog)
        self.catalog["inventory_version"] = VERSION
        self.catalog["ccm_version"] = VERSION

        log(f"  Catalogued {len(self.catalog.get('datasets', []))} datasets")

    @staticmethod
    def _normalise_dataset(record, role=None):
        """Adapt the factual catalog record to the scoring-engine contract."""
        item = dict(record or {})
        path = str(item.get("path") or item.get("file_path") or "")
        resolution = item.get("resolution") or {}
        crs = item.get("crs") or {}
        acquired = item.get("acquired") or {}
        schema = item.get("schema") or {}
        role_name = role or item.get("role") or item.get("ccm_role") or "Vehicle"
        role_name = {
            "dem": "DEM", "soil": "Soil", "veg": "Vegetation",
            "hydro": "Hydrology", "contours": "Contours",
            "extent": "Extent", "vehicle": "Vehicle",
            "moisture": "Soil Moisture", "mgcp": "MGCP",
        }.get(str(role_name).lower(), str(role_name))

        item["role"] = role_name
        item["ccm_role"] = role_name.lower()
        item.setdefault("file_path", path)
        item.setdefault("file_extension", Path(path.split("::", 1)[0]).suffix.lower())
        item.setdefault("geom_type", item.get("geometry") or item.get("dataset_type", "unknown"))
        item.setdefault("temporal_year", str(acquired.get("date", ""))[:4] or None)
        item["created_date"] = item.get("created_date") or acquired.get("date")
        item["modified_date"] = item.get("modified_date") or acquired.get("date")

        # The factual scanner stores structured metadata while the scoring
        # engines consume scalar compatibility fields. Keep both forms.
        if isinstance(item.get("crs"), dict):
            item["crs"] = crs.get("name") or crs.get("epsg") or ""
        else:
            item["crs"] = item.get("crs") or crs.get("name") or crs.get("epsg") or ""
        item["coverage_pct"] = item.get("coverage_pct")
        if item["coverage_pct"] is None:
            item["coverage_pct"] = item.get("coverage_aoi_pct")
        if item["coverage_pct"] is None:
            item["coverage_pct"] = 50.0
        item["bbox_coverage_pct"] = item.get("coverage_pct")

        if isinstance(item.get("resolution"), dict):
            item["resolution"] = (
                resolution.get("display")
                or (f"{resolution['cell_size_m']} m" if resolution.get("cell_size_m") is not None else None)
                or ""
            )
        item["cell_size_meters"] = resolution.get("cell_size_m")

        if isinstance(item.get("schema"), dict):
            item["schema"] = {
                **schema,
                "required_columns": schema.get("required_columns") or schema.get("required") or [],
                "present_columns": schema.get("present_columns") or schema.get("present") or [],
            }
        item["schema_fields"] = (
            (item.get("schema") or {}).get("present_columns")
            or item.get("fields")
            or []
        )
        item["duplicate_count"] = max(len(item.get("locations") or []) - 1, 0)
        item["metadata_fields"] = item.get("basis") or []
        item["horizontal_accuracy_meters"] = item.get("horizontal_accuracy_meters")
        item["role_basis"] = item.get("role_basis") or role_name
        return item

    @classmethod
    def _normalise_catalog(cls, catalog):
        """Add a stable flat dataset list while preserving factual catalog keys."""
        result = dict(catalog)
        if result.get("datasets"):
            result["datasets"] = [cls._normalise_dataset(item) for item in result["datasets"]]
            return result

        role_names = {
            "dem": "DEM", "soil": "Soil", "veg": "Vegetation",
            "hydro": "Hydrology", "contours": "Contours",
            "extent": "Extent", "vehicle": "Vehicle",
            "moisture": "Soil Moisture", "mgcp": "MGCP",
        }
        datasets = []
        seen = set()
        for raw_role, bucket in (result.get("roles") or {}).items():
            role = role_names.get(str(raw_role).lower(), str(raw_role))
            for record in (bucket or {}).get("records", []):
                item = cls._normalise_dataset(record, role=role)
                key = (item.get("role"), item.get("path"), item.get("name"))
                if key in seen:
                    continue
                seen.add(key)
                datasets.append(item)
        result["datasets"] = datasets
        return result

    def _compute_quality_scores(self, log):
        """Phase 2: Compute quality scores."""

        try:
            from ccm_data_quality import DataQualityScorer
        except ImportError:
            raise ImportError("ccm_data_quality not found; ensure it's in PYTHONPATH")

        scorer = DataQualityScorer()
        scores = scorer.score_catalog(self.catalog)

        # Convert to dict for lookups
        score_dict = {s["dataset"]: s["quality_score"] for s in scores}

        self.quality_scores = {
            "version": VERSION,
            "timestamp": datetime.now().isoformat(),
            "scores": scores,
            "summary": {
                "total": len(scores),
                "avg": round(sum(score_dict.values()) / len(score_dict), 2) if score_dict else 0,
                "min": round(min(score_dict.values()), 2) if score_dict else 0,
                "max": round(max(score_dict.values()), 2) if score_dict else 0,
            },
        }

        log(f"  Quality scores: avg={self.quality_scores['summary']['avg']}/10")

    def _compute_fitness_scores(self, log):
        """Phase 3: Compute fitness scores."""

        try:
            from ccm_data_fitness import DataFitnessScorer
        except ImportError:
            raise ImportError("ccm_data_fitness not found; ensure it's in PYTHONPATH")

        scorer = DataFitnessScorer(
            soil_rci_csv=self.soil_rci_csv,
            vehicles_can_csv=self.vehicles_can_csv,
        )

        all_scores = []

        for dataset in self.catalog.get("datasets", []):
            for role in ["DEM", "Soil", "Vegetation", "Hydrology", "Contours", "Extent", "Vehicle"]:
                score = scorer.score_dataset_for_role(dataset, role)

                if score["fitness_score"] > 0:  # Only include non-zero scores
                    all_scores.append({
                        "dataset": dataset.get("name"),
                        **score,
                    })

        self.fitness_scores = {
            "version": VERSION,
            "timestamp": datetime.now().isoformat(),
            "scores": all_scores,
            "summary": {
                "total_evaluations": len(all_scores),
                "roles_evaluated": ["DEM", "Soil", "Vegetation", "Hydrology", "Contours", "Extent", "Vehicle"],
            },
        }

        log(f"  Fitness scores: {len(all_scores)} role-dataset pairs evaluated")

    def _compute_confidence_scores(self, log):
        """Phase 4: Compute confidence scores."""

        try:
            from ccm_data_confidence import ConfidenceScorer
        except ImportError:
            raise ImportError("ccm_data_confidence not found; ensure it's in PYTHONPATH")

        # Build role-confidence dict from the best candidate in each role.
        role_confs = {}
        quality_by_dataset = {
            item["dataset"]: item["quality_score"]
            for item in self.quality_scores.get("scores", [])
        }
        datasets_by_name = {
            item.get("name"): item for item in self.catalog.get("datasets", [])
        }
        by_role = {}
        for score in self.fitness_scores.get("scores", []):
            by_role.setdefault(score.get("role"), []).append(score)

        scorer = ConfidenceScorer()
        for role, candidates in by_role.items():
            best = max(candidates, key=lambda item: item.get("fitness_score", 0))
            dataset = datasets_by_name.get(best.get("dataset"), {})
            coverage = dataset.get("coverage_aoi_pct")
            try:
                coverage = float(coverage) if coverage is not None else 50.0
            except (TypeError, ValueError):
                coverage = 50.0
            role_confs[role] = scorer.score_role_confidence(
                role,
                quality_by_dataset.get(best.get("dataset"), 5.0),
                best.get("fitness_score", 1.0),
                coverage,
                limitations=dataset.get("limitations") or [],
            )

        # Compute model-level confidence
        scorer = ConfidenceScorer()
        model_conf = scorer.compute_model_confidence(role_confs)

        self.confidence_scores = {
            "version": VERSION,
            "timestamp": datetime.now().isoformat(),
            "role_confidence": role_confs,
            **model_conf,
        }

        log(f"  Model confidence: {model_conf['model_confidence']}")

    def _compute_readiness_scores(self, log):
        """Phase 5: Compute readiness scores."""

        # Readiness check assumes Step 1 output exists; for now, report as "Not Yet Run"
        # In v0.58, Step 1 will call this after preprocessing

        self.readiness_scores = {
            "version": VERSION,
            "timestamp": datetime.now().isoformat(),
            "readiness_status": "Not Yet Run",
            "readiness_pct": 0,
            "note": "Readiness is checked after Step 1 preprocessing",
            "checked_items": {},
            "missing_items": [],
            "next_steps": ["Complete Step 1 preprocessing to enable readiness check"],
        }

        log("  Readiness: not yet run (checked after Step 1)")

    def _generate_recommendations(self, log):
        """Phase 6: Generate auto-recommendations."""

        try:
            from ccm_data_selector import DataSelector
        except ImportError:
            raise ImportError("ccm_data_selector not found; ensure it's in PYTHONPATH")

        selector = DataSelector()

        # Prepare score dicts
        quality_dict = {
            s["dataset"]: s["quality_score"]
            for s in self.quality_scores.get("scores", [])
        }

        fitness_dict = {}

        for score in self.fitness_scores.get("scores", []):
            dataset = score["dataset"]

            if dataset not in fitness_dict:
                fitness_dict[dataset] = {}

            fitness_dict[dataset][score["role"]] = score["fitness_score"]

        # Generate recommendations
        self.recommendations = selector.recommend_all_roles(
            self.catalog,
            quality_dict,
            fitness_dict,
            self.confidence_scores.get("role_confidence", {}),
            self.readiness_scores,
            user_prefs={},  # User can override in Step 1
        )

        log(f"  Recommendations: {sum(1 for s in self.recommendations['selections'].values() if s['recommended'] != 'MANUAL_SELECTION_REQUIRED')}/7 auto-selected")

    def _write_all_reports(self, log) -> Dict[str, Any]:
        """Phase 7: Write all reports and recommendations."""

        self.project_folder.mkdir(parents=True, exist_ok=True)

        outputs = {}

        # 1. Write existing v0.57 reports (via ccm_data_report)
        try:
            import ccm_data_report as report_engine

            report_paths = report_engine.write_all(
                self.catalog,
                str(self.project_folder),
            )

            outputs["catalog_json"] = report_paths["json"]
            outputs["html_report"] = report_paths["html"]
            outputs["txt_report"] = report_paths["text"]

            log(f"  Factual inventory reports written to {self.project_folder}")

        except Exception as exc:
            raise RuntimeError(f"Factual report generation failed: {exc}") from exc

        # 2. Write v0.58.2 scoring reports (NEW)
        quality_path = self.project_folder / "ccm_quality_scores.json"
        with open(quality_path, "w") as f:
            json.dump(self.quality_scores, f, indent=2)
        outputs["quality_scores_json"] = str(quality_path)

        fitness_path = self.project_folder / "ccm_fitness_scores.json"
        with open(fitness_path, "w") as f:
            json.dump(self.fitness_scores, f, indent=2)
        outputs["fitness_scores_json"] = str(fitness_path)

        confidence_path = self.project_folder / "ccm_confidence_scores.json"
        with open(confidence_path, "w") as f:
            json.dump(self.confidence_scores, f, indent=2)
        outputs["confidence_scores_json"] = str(confidence_path)

        readiness_path = self.project_folder / "ccm_readiness_scores.json"
        with open(readiness_path, "w") as f:
            json.dump(self.readiness_scores, f, indent=2)
        outputs["readiness_scores_json"] = str(readiness_path)

        # 3. Write recommendations (NEW)
        rec_path = self.project_folder / "ccm_recommendations.json"
        with open(rec_path, "w") as f:
            json.dump(self.recommendations, f, indent=2)
        outputs["recommendations_json"] = str(rec_path)

        # 4. Write recommendations HTML (NEW)
        rec_html_path = self.project_folder / "CCM_Recommendations_Report.html"

        try:
            from ccm_data_selector import write_recommendations_html

            write_recommendations_html(self.recommendations, rec_html_path)
            outputs["recommendations_html"] = str(rec_html_path)

        except Exception as e:
            log(f"  [WARN] Could not write recommendations HTML: {e}")

        # 5. Update project config (if available)
        try:
            config_path = self.project_folder / "ccm_project.json"

            if config_path.exists():
                with open(config_path) as f:
                    project_config = json.load(f)
            else:
                project_config = {}

            # Add v0.58.2 keys
            project_config.update({
                "data_root": str(self.data_root),
                "data_catalog_json": str(self.project_folder / "ccm_data_catalog.json"),
                "data_quality_scores": str(quality_path),
                "data_fitness_scores": str(fitness_path),
                "data_confidence_scores": str(confidence_path),
                "data_readiness_scores": str(self.project_folder / "ccm_readiness_scores.json"),
                "data_recommendations": str(rec_path),
                "data_recommendations_report": str(rec_html_path),
                "ccm_version": VERSION,
                "v058_timestamp": datetime.now().isoformat(),
            })

            with open(config_path, "w") as f:
                json.dump(project_config, f, indent=2)

            outputs["project_config"] = str(config_path)
            log(f"  Project config updated: {config_path}")

        except Exception as e:
            log(f"  [WARN] Could not update project config: {e}")

        return outputs


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="CCM Step 0b v0.58.2 integration test")
    parser.add_argument("--data-root", required=True, help="Data root folder")
    parser.add_argument("--aoi", help="AOI/extent file")
    parser.add_argument("--project", help="Project output folder")
    parser.add_argument("--soil-rci", help="soil_rci.csv path")
    parser.add_argument("--vehicles-can", help="Vehicles_Can.csv path")
    parser.add_argument("--quiet", action="store_true", help="Suppress progress messages")

    args = parser.parse_args()

    integrator = Step0bIntegrator(
        args.data_root,
        aoi_path=args.aoi,
        project_folder=args.project,
        soil_rci_csv=args.soil_rci,
        vehicles_can_csv=args.vehicles_can,
    )

    result = integrator.run(verbose=not args.quiet)

    print(json.dumps(result, indent=2))

# <<< END OF FILE >>>
