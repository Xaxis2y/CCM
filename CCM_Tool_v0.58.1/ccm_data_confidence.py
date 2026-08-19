#!/usr/bin/env python3
"""
CCM Tool v0.58 — Data Confidence Scoring Engine

Estimates modeling confidence given quality + fitness scores and limitations.

Confidence levels: High / Moderate / Low / Unvetted

Rules per role:
  High: quality >= 8 AND fitness >= 8 AND coverage >= 95%
  Moderate: quality >= 6 AND fitness >= 6 AND coverage >= 80%
  Low: quality >= 3 AND fitness >= 3 AND coverage >= 50%
  Unvetted: below Low threshold

Model-level confidence depends on critical roles (DEM mandatory) and
presence of workarounds.

VERSION = "0.58"
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any

VERSION = "0.58"

# Critical roles that block model if unvetted
CRITICAL_ROLES = {"DEM", "Extent", "Vehicle"}

# Semi-critical roles (warn if Low)
WARN_ROLES = {"Soil", "Vegetation"}


class ConfidenceScorer:
    """
    Evaluate modeling confidence for a CCM analysis.

    Per-role confidence is based on quality score, fitness score, and coverage.
    Model-level confidence depends on critical role status and available workarounds.
    """

    def __init__(self):
        self.role_confidence: Dict[str, Dict[str, Any]] = {}
        self.model_confidence = "Unvetted"
        self.confidence_reasons: List[str] = []

    def score_role_confidence(
        self,
        role: str,
        quality_score: float,
        fitness_score: float,
        coverage_pct: float,
        limitations: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Compute confidence level for a single role.

        Args:
            role: "DEM", "Soil", "Vegetation", "Hydrology", "Contours", "Extent", "Vehicle"
            quality_score: 1–10
            fitness_score: 1–10
            coverage_pct: 0–100
            limitations: List of limitation strings from catalog

        Returns:
            {
              "role": "DEM",
              "confidence_level": "High",
              "quality": 8,
              "fitness": 8,
              "coverage": 95.0,
              "reasoning": "..."
            }
        """

        # Average quality and fitness
        avg_score = (quality_score + fitness_score) / 2

        # Determine confidence level
        if avg_score >= 8 and coverage_pct >= 95:
            level = "High"
        elif avg_score >= 6 and coverage_pct >= 80:
            level = "Moderate"
        elif avg_score >= 3 and coverage_pct >= 50:
            level = "Low"
        else:
            level = "Unvetted"

        # Apply limitations as downgrades
        limitations = limitations or []
        lim_lower = [str(l).lower() for l in limitations]

        if level == "High" and any("void" in l for l in lim_lower):
            # DEM with voids downgrades from High → Moderate
            if role == "DEM":
                level = "Moderate"

        if level == "Moderate" and any("duplicate" in l for l in lim_lower):
            # Duplicates downgrade from Moderate → Low
            level = "Low"

        reasoning = self._build_confidence_reasoning(
            role, level, quality_score, fitness_score, coverage_pct
        )

        result = {
            "role": role,
            "confidence_level": level,
            "quality": round(quality_score, 1),
            "fitness": round(fitness_score, 1),
            "coverage_pct": round(coverage_pct, 1),
            "reasoning": reasoning,
        }

        self.role_confidence[role] = result
        return result

    def compute_model_confidence(
        self, role_confidences: Dict[str, Dict[str, str]]
    ) -> Dict[str, Any]:
        """
        Compute model-level confidence given per-role confidence.

        Args:
            role_confidences: {
              "DEM": {"confidence_level": "High", ...},
              "Soil": {"confidence_level": "Low", ...},
              ...
            }

        Returns:
            {
              "model_confidence": "Conditional",
              "model_confidence_level_numeric": 7,
              "critical_issues": [...],
              "warnings": [...],
              "recommendations": [...]
            }
        """

        self.role_confidence = role_confidences

        critical_ok = all(
            role_confidences.get(role, {}).get("confidence_level") in ("High", "Moderate")
            for role in CRITICAL_ROLES
            if role in role_confidences
        )

        critical_missing = [
            role for role in CRITICAL_ROLES if role not in role_confidences
        ]

        warn_issues = [
            role
            for role in WARN_ROLES
            if role in role_confidences
            and role_confidences[role].get("confidence_level") == "Low"
        ]

        unvetted_any = any(
            conf.get("confidence_level") == "Unvetted"
            for conf in role_confidences.values()
        )

        # Determine model-level status
        critical_issues = []
        warnings = []
        recommendations = []

        if critical_missing:
            self.model_confidence = "Incomplete"
            critical_issues.append(f"Missing critical roles: {', '.join(critical_missing)}")

        elif unvetted_any:
            self.model_confidence = "At-Risk"
            unvetted_roles = [
                r
                for r, c in role_confidences.items()
                if c.get("confidence_level") == "Unvetted"
            ]
            critical_issues.append(f"Unvetted datasets: {', '.join(unvetted_roles)}")

        elif not critical_ok:
            self.model_confidence = "At-Risk"
            low_crit = [
                r
                for r in CRITICAL_ROLES
                if r in role_confidences
                and role_confidences[r].get("confidence_level") not in ("High", "Moderate")
            ]
            critical_issues.append(f"Critical roles below Moderate: {', '.join(low_crit)}")

        elif warn_issues:
            self.model_confidence = "Conditional"
            for role in warn_issues:
                warnings.append(
                    f"⚠ {role} data unvetted; verify RCI/species classification manually"
                )
                recommendations.append(f"Validate {role} data before Step 2")

        else:
            self.model_confidence = "Acceptable"
            recommendations.append("All critical data High or Moderate confidence; proceed")

        # Numeric confidence (avg of all role confidences)
        confidence_values = {"High": 10, "Moderate": 7, "Low": 3, "Unvetted": 1}
        numeric_val = (
            sum(
                confidence_values.get(c.get("confidence_level", "Unvetted"), 1)
                for c in role_confidences.values()
            )
            / len(role_confidences)
            if role_confidences
            else 1
        )

        return {
            "model_confidence": self.model_confidence,
            "model_confidence_level_numeric": round(numeric_val),
            "critical_issues": critical_issues,
            "warnings": warnings,
            "recommendations": recommendations,
            "role_summary": {
                role: {
                    "confidence": conf.get("confidence_level"),
                    "quality": conf.get("quality"),
                    "fitness": conf.get("fitness"),
                    "coverage": conf.get("coverage_pct"),
                }
                for role, conf in role_confidences.items()
            },
        }

    def _build_confidence_reasoning(
        self,
        role: str,
        level: str,
        quality: float,
        fitness: float,
        coverage: float,
    ) -> str:
        """Build human-readable reasoning for confidence level."""

        parts = [role, f"confidence={level}"]

        if quality >= 8:
            parts.append("high-quality")
        elif quality < 3:
            parts.append("low-quality")

        if fitness >= 8:
            parts.append("good-fit")
        elif fitness < 3:
            parts.append("poor-fit")

        if coverage >= 95:
            parts.append("full-coverage")
        elif coverage < 50:
            parts.append("partial-coverage")

        return " → ".join(parts)


def write_confidence_scores(scores: Dict[str, Any], output_path: Path) -> None:
    """Write confidence scores to JSON file."""

    output_dict = {
        "version": VERSION,
        "timestamp": datetime.now().isoformat(),
        **scores,
    }

    with open(output_path, "w") as f:
        json.dump(output_dict, f, indent=2)


if __name__ == "__main__":
    # Quick test
    role_confs = {
        "DEM": {
            "confidence_level": "High",
            "quality": 8,
            "fitness": 8,
            "coverage_pct": 95,
        },
        "Soil": {
            "confidence_level": "Low",
            "quality": 5,
            "fitness": 4,
            "coverage_pct": 85,
        },
        "Vehicle": {
            "confidence_level": "High",
            "quality": 9,
            "fitness": 9,
            "coverage_pct": 100,
        },
    }

    scorer = ConfidenceScorer()
    model_conf = scorer.compute_model_confidence(role_confs)

    print(json.dumps(model_conf, indent=2))
