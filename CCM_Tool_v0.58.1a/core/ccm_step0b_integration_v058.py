#!/usr/bin/env python3
"""
CCM Tool v0.58 — Step 0b Integration Module

Orchestrates all Phase 1 scoring engines + auto-selection into Step 0b workflow.

Flow:
  1. Build catalog (existing Step 0b)
  2. Compute quality scores (NEW)
  3. Compute fitness scores (NEW)
  4. Compute confidence scores (NEW)
  5. Compute readiness scores (NEW)
  6. Generate auto-recommendations (NEW)
  7. Write all reports and recommendations (NEW)

All existing v0.57 outputs preserved; v0.58 adds new JSON files and enhanced HTML.

VERSION = "0.58"
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any

VERSION = "0.58"


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

        # State
        self.catalog = None
        self.quality_scores = None
        self.fitness_scores = None
        self.confidence_scores = None
        self.readiness_scores = None
        self.recommendations = None

    def run(self, verbose: bool = True) -> Dict[str, Any]:
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

        def log(msg):
            if verbose:
                print(f"[CCM 0b v0.58] {msg}")

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

            log("✓ Step 0b v0.58 complete")

            return {
                "status": "success",
                **outputs,
            }

        except Exception as e:
            log(f"✗ Error: {e}")

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

        self.catalog = cat_engine.build_catalog(
            str(self.data_root),
            aoi_path=str(self.aoi_path) if self.aoi_path else None,
            project_folder=str(self.project_folder),
        )

        if self.catalog.get("error"):
            raise RuntimeError(f"Catalog build failed: {self.catalog.get('error')}")

        log(f"  Catalogued {len(self.catalog.get('datasets', []))} datasets")

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

        # Build role-confidence dict from fitness scores
        role_confs = {}

        for score in self.fitness_scores.get("scores", []):
            role = score.get("role")

            if role not in role_confs:
                # Score this role based on best fitness
                best_fitness = score["fitness_score"]
                quality = next(
                    (s["quality_score"] for s in self.quality_scores.get("scores", [])
                     if s["dataset"] == score["dataset"]),
                    5.0
                )

                scorer = ConfidenceScorer()
                score.pop("dataset", None)
                score.pop("fitness_score", None)

                role_conf = scorer.score_role_confidence(
                    role,
                    quality,
                    best_fitness,
                    self.catalog.get("datasets", [{}])[0].get("coverage_pct", 50),
                )

                role_confs[role] = role_conf

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

        try:
            from ccm_data_readiness import ReadinessChecker
        except ImportError:
            raise ImportError("ccm_data_readiness not found; ensure it's in PYTHONPATH")

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

        log(f"  Readiness: not yet run (checked after Step 1)")

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

            report_paths = report_engine.write_reports(
                self.catalog,
                str(self.project_folder),
            )

            outputs["catalog_json"] = str(self.project_folder / "ccm_data_catalog.json")
            outputs["html_report"] = str(self.project_folder / "CCM_Data_Intelligence_Report.html")
            outputs["txt_report"] = str(self.project_folder / "CCM_Data_Intelligence_Report.txt")

            log(f"  v0.57 reports written to {self.project_folder}")

        except ImportError:
            log("  ⚠ ccm_data_report not found; skipping v0.57 report generation")

        # 2. Write v0.58 scoring reports (NEW)
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
            log(f"  ⚠ Could not write recommendations HTML: {e}")

        # 5. Update project config (if available)
        try:
            import ccm_project_config as cfg

            config_path = self.project_folder / "ccm_project.json"

            if config_path.exists():
                with open(config_path) as f:
                    project_config = json.load(f)
            else:
                project_config = {}

            # Add v0.58 keys
            project_config.update({
                "data_root": str(self.data_root),
                "data_catalog_json": str(self.project_folder / "ccm_data_catalog.json"),
                "data_quality_scores": str(quality_path),
                "data_fitness_scores": str(fitness_path),
                "data_confidence_scores": str(confidence_path),
                "data_recommendations": str(rec_path),
                "v058_timestamp": datetime.now().isoformat(),
            })

            with open(config_path, "w") as f:
                json.dump(project_config, f, indent=2)

            outputs["project_config"] = str(config_path)
            log(f"  Project config updated: {config_path}")

        except Exception as e:
            log(f"  ⚠ Could not update project config: {e}")

        return outputs


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="CCM Step 0b v0.58 integration test")
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
