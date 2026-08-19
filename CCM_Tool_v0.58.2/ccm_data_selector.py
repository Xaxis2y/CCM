#!/usr/bin/env python3
"""
CCM Tool v0.58.2 — Data Auto-Selection Engine

Recommends the best dataset source for each role based on composite scores.

Algorithm:
  For each role (DEM, Soil, Vegetation, Hydrology, Contours, Extent, Vehicle):
    candidates = [dataset for dataset in catalog if matches_role]

    For each candidate:
      score = (
        quality_score * 0.30 +       # base data quality
        fitness_score * 0.40 +       # CCM-specific fit
        confidence_numeric * 0.20 +  # modeling confidence
        coverage_pct / 100 * 0.10    # AOI coverage
      )

    best = max(candidates, key=score)

    IF best.score < 5.0:
      recommendation = "MANUAL_SELECTION_REQUIRED"
    ELSE:
      recommendation = best

Outputs: ccm_recommendations.json + HTML report

VERSION = "0.58.2"
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

VERSION = "0.58.2"

# Weighting factors for composite recommendation score
WEIGHTS = {
    "quality": 0.30,
    "fitness": 0.40,
    "confidence": 0.20,
    "coverage": 0.10,
}

# Minimum score threshold for automatic recommendation
MIN_RECOMMENDATION_SCORE = 5.0

# Role precedence (higher priority for recommendations if tied)
ROLE_PRECEDENCE = {
    "DEM": 10,
    "Extent": 9,
    "Vehicle": 8,
    "Soil": 7,
    "Vegetation": 6,
    "Hydrology": 5,
    "Contours": 4,
}


class DataSelector:
    """
    Auto-selection engine: ranks datasets per role and recommends best source.

    Combines quality, fitness, confidence, and coverage scores into a single
    recommendation score. Handles ties, thresholds, and fallback strategies.
    """

    def __init__(self):
        self.recommendations: Dict[str, Any] = {}
        self.model_confidence = "Unvetted"
        self.readiness = "Incomplete"

    def select_for_role(
        self,
        role: str,
        candidates: List[Dict[str, Any]],
        quality_scores: Dict[str, float],
        fitness_scores: Dict[str, Dict[str, float]],
        confidence_scores: Dict[str, Dict[str, Any]],
        user_prefs: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Select best dataset for a role from candidates.

        Args:
            role: "DEM", "Soil", "Vegetation", etc.
            candidates: List of dataset dicts from catalog
            quality_scores: {dataset_name: quality_score}
            fitness_scores: {dataset_name: {role: fitness_score}}
            confidence_scores: {role: {confidence_level: ...}}
            user_prefs: {role: preferred_dataset_name} (overrides recommendations)

        Returns:
            {
              "role": "DEM",
              "recommended": "ASTER_30m.tif",
              "score": 7.8,
              "metrics": {
                "quality": 8,
                "fitness": 8,
                "confidence": "High",
                "coverage_pct": 95.0
              },
              "alternatives": [...],
              "reason": "...",
              "user_override": None
            }
        """

        # Check user preference first
        if user_prefs and user_prefs.get(role):
            preferred = user_prefs[role]
            preferred_cand = next((c for c in candidates if c.get("name") == preferred), None)

            if preferred_cand:
                return {
                    "role": role,
                    "recommended": preferred,
                    "score": None,
                    "metrics": {},
                    "alternatives": [],
                    "reason": f"User override: {preferred}",
                    "user_override": preferred,
                }

        # Score all candidates
        scored_candidates = []

        for candidate in candidates:
            dataset_name = candidate.get("name", "Unknown")

            quality = quality_scores.get(dataset_name, 5.0)
            fitness = fitness_scores.get(dataset_name, {}).get(role, 5.0)
            coverage = candidate.get("coverage_pct", 50.0)

            # Confidence numeric: map text level to number
            conf_level = confidence_scores.get(role, {}).get("confidence_level", "Unvetted")
            conf_numeric = {
                "High": 10,
                "Moderate": 7,
                "Low": 3,
                "Unvetted": 1,
            }.get(conf_level, 1)

            # Composite score
            composite = (
                quality * WEIGHTS["quality"]
                + fitness * WEIGHTS["fitness"]
                + conf_numeric * WEIGHTS["confidence"]
                + (coverage / 100.0) * WEIGHTS["coverage"]
            )

            scored_candidates.append(
                {
                    "name": dataset_name,
                    "dataset": candidate,
                    "score": round(composite, 2),
                    "quality": quality,
                    "fitness": fitness,
                    "confidence": conf_level,
                    "coverage_pct": coverage,
                }
            )

        # Sort by score (descending), then by precedence, then alphabetically
        scored_candidates.sort(
            key=lambda c: (
                -c["score"],
                -ROLE_PRECEDENCE.get(role, 0),
                c["name"],
            )
        )

        # Best candidate
        if not scored_candidates:
            return {
                "role": role,
                "recommended": "MANUAL_SELECTION_REQUIRED",
                "score": None,
                "metrics": {},
                "alternatives": [],
                "reason": f"No datasets found for role {role}",
                "user_override": None,
            }

        best = scored_candidates[0]

        # Determine if recommendation meets threshold
        if best["score"] < MIN_RECOMMENDATION_SCORE:
            recommendation = "MANUAL_SELECTION_REQUIRED"
            reason = f"Best candidate ({best['name']}) scores {best['score']}/10; below recommendation threshold {MIN_RECOMMENDATION_SCORE}"
        else:
            recommendation = best["name"]
            reason = self._build_reason(best, role)

        # Alternatives (next 2 candidates)
        alternatives = []

        for alt in scored_candidates[1:3]:
            alternatives.append(
                {
                    "name": alt["name"],
                    "score": alt["score"],
                    "reason": f"{alt['name']}: Quality {alt['quality']:.0f}/10, Fitness {alt['fitness']:.0f}/10, {alt['coverage_pct']:.0f}% coverage, {alt['confidence']} confidence",
                }
            )

        result = {
            "role": role,
            "recommended": recommendation,
            "score": best["score"] if recommendation != "MANUAL_SELECTION_REQUIRED" else None,
            "metrics": {
                "quality": round(best["quality"], 1),
                "fitness": round(best["fitness"], 1),
                "confidence": best["confidence"],
                "coverage_pct": round(best["coverage_pct"], 1),
            },
            "alternatives": alternatives,
            "reason": reason,
            "user_override": None,
        }

        return result

    def recommend_all_roles(
        self,
        catalog: Dict[str, Any],
        quality_scores: Dict[str, float],
        fitness_scores: Dict[str, Dict[str, float]],
        confidence_scores: Dict[str, Dict[str, Any]],
        readiness_result: Dict[str, Any],
        user_prefs: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Generate recommendations for all roles.

        Args:
            catalog: Full catalog from Step 0b
            quality_scores: {dataset_name: quality_score}
            fitness_scores: {dataset_name: {role: fitness_score}}
            confidence_scores: {role: {confidence_level, ...}}
            readiness_result: Output from readiness checker
            user_prefs: User-provided overrides

        Returns:
            {
              "version": "0.58.2",
              "timestamp": "...",
              "data_root": "...",
              "model_confidence": "Acceptable",
              "readiness": "Ready",
              "selections": {
                "DEM": {...},
                "Soil": {...},
                ...
              },
              "warnings": [...],
              "next_steps": [...]
            }
        """

        datasets = catalog.get("datasets", [])
        user_prefs = user_prefs or {}

        # Group datasets by detected role
        role_candidates = self._group_by_role(datasets)

        # Generate recommendations for each role
        selections = {}

        for role in ["DEM", "Soil", "Vegetation", "Hydrology", "Contours", "Extent", "Vehicle"]:
            candidates = role_candidates.get(role, [])

            selection = self.select_for_role(
                role, candidates, quality_scores, fitness_scores, confidence_scores, user_prefs
            )

            selections[role] = selection

        # Compute model-level warnings and recommendations
        warnings = self._compute_warnings(selections, readiness_result)
        next_steps = self._compute_next_steps(selections, warnings, readiness_result)

        # Overall model confidence
        critical_ok = all(
            selections[role]["recommended"] != "MANUAL_SELECTION_REQUIRED"
            for role in ["DEM", "Extent", "Vehicle"]
            if role in selections
        )

        if critical_ok:
            model_conf = "Acceptable"
        else:
            model_conf = "At-Risk"

        result = {
            "version": VERSION,
            "timestamp": datetime.now().isoformat(),
            "data_root": catalog.get("data_root", "Unknown"),
            "aoi_file": catalog.get("aoi_file", "Unknown"),
            "model_confidence": model_conf,
            "readiness": readiness_result.get("readiness_status", "Unknown"),
            "selections": selections,
            "warnings": warnings,
            "next_steps": next_steps,
        }

        self.recommendations = result
        return result

    def _group_by_role(self, datasets: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Group datasets by likely role.

        Heuristic: use 'role_basis' field if present, else infer from name/source.
        """

        role_candidates: Dict[str, List] = {
            "DEM": [],
            "Soil": [],
            "Vegetation": [],
            "Hydrology": [],
            "Contours": [],
            "Extent": [],
            "Vehicle": [],
        }

        for dataset in datasets:
            detected_role = self._detect_role(dataset)

            if detected_role in role_candidates:
                role_candidates[detected_role].append(dataset)

        return role_candidates

    def _detect_role(self, dataset: Dict[str, Any]) -> str:
        """
        Detect likely role for a dataset.

        Heuristic: folder name, source type, file name.
        """

        name = dataset.get("name", "").lower()
        source = dataset.get("source_type", "").lower()
        role_basis = dataset.get("role_basis", "").lower()

        # Explicit role_basis
        if "dem" in role_basis or "elevation" in role_basis:
            return "DEM"
        if "soil" in role_basis or "rci" in role_basis:
            return "Soil"
        if "vegetation" in role_basis or "veg" in role_basis:
            return "Vegetation"
        if "hydro" in role_basis or "stream" in role_basis:
            return "Hydrology"
        if "contour" in role_basis:
            return "Contours"
        if "aoi" in role_basis or "extent" in role_basis:
            return "Extent"
        if "vehicle" in role_basis or "csv" in role_basis:
            return "Vehicle"

        # Source type
        if any(s in source for s in ["srtm", "aster", "dem", "elevation"]):
            return "DEM"
        if any(s in source for s in ["soil", "rci", "usda", "ssurgo"]):
            return "Soil"
        if any(s in source for s in ["vegetation", "lulc", "ndvi", "canopy"]):
            return "Vegetation"
        if any(s in source for s in ["hydro", "stream", "river", "water"]):
            return "Hydrology"
        if "contour" in source:
            return "Contours"

        # File name
        if any(kw in name for kw in ["dem", "elevation", "srtm", "aster"]):
            return "DEM"
        if any(kw in name for kw in ["soil", "rci", "ssurgo", "soilgrids"]):
            return "Soil"
        if any(kw in name for kw in ["vegetation", "veg", "lulc", "ndvi", "canopy"]):
            return "Vegetation"
        if any(kw in name for kw in ["hydro", "stream", "river", "water"]):
            return "Hydrology"
        if "contour" in name:
            return "Contours"
        if any(kw in name for kw in ["aoi", "extent", "boundary", "study"]):
            return "Extent"
        if "vehicle" in name or "csv" in name:
            return "Vehicle"

        # Default: no clear match
        return "Vehicle"  # Fallback to Vehicle (catch-all for CSVs)

    def _build_reason(self, best: Dict[str, Any], role: str) -> str:
        """Build human-readable reason for recommendation."""

        return (
            f"{best['name']}: Quality {best['quality']:.0f}/10, "
            f"Fitness {best['fitness']:.0f}/10, "
            f"{best['coverage_pct']:.0f}% coverage, "
            f"{best['confidence']} confidence"
        )

    def _compute_warnings(
        self, selections: Dict[str, Any], readiness_result: Dict[str, Any]
    ) -> List[str]:
        """Generate warnings based on selections and readiness."""

        warnings = []

        # Critical roles requiring manual selection
        for role in ["DEM", "Extent", "Vehicle"]:
            if role in selections and selections[role]["recommended"] == "MANUAL_SELECTION_REQUIRED":
                warnings.append(f"⚠ {role}: {selections[role]['reason']}")

        # Semi-critical roles with low confidence
        for role in ["Soil", "Vegetation"]:
            if role in selections:
                conf = selections[role]["metrics"].get("confidence")

                if conf == "Low" or conf == "Unvetted":
                    warnings.append(
                        f"⚠ {role}: {conf} confidence; recommend manual validation"
                    )

        # Readiness issues
        missing_items = readiness_result.get("missing_items", [])

        if missing_items:
            warnings.append(f"⚠ Readiness: {len(missing_items)} items incomplete")

        return warnings

    def _compute_next_steps(
        self, selections: Dict[str, Any], warnings: List[str], readiness_result: Dict[str, Any]
    ) -> List[str]:
        """Generate recommended next steps."""

        steps = []

        # Step 1: Accept/override recommendations
        manual_roles = [
            s["role"]
            for s in selections.values()
            if s["recommended"] == "MANUAL_SELECTION_REQUIRED"
        ]

        if manual_roles:
            steps.append(f"1. Manually select sources for: {', '.join(manual_roles)}")
        else:
            steps.append("1. Review and accept (or override) recommended sources in Step 1")

        # Step 2: Address warnings
        if warnings:
            steps.append("2. Address warnings:")

            for warning in warnings[:3]:  # Top 3 warnings
                clean_warn = warning.replace("⚠ ", "  • ").strip()
                steps.append(clean_warn)

        # Step 3: Complete readiness
        readiness_status = readiness_result.get("readiness_status", "Incomplete")

        if readiness_status != "Ready":
            missing = readiness_result.get("missing_items", [])

            if missing:
                steps.append(f"3. Complete preprocessing: {', '.join(missing[:3])}")
            else:
                steps.append(f"3. {readiness_result.get('next_steps', ['Complete preprocessing'])[0]}")

        # Step 4: Proceed
        steps.append("4. Proceed to Step 2 (Generate Mobility Map)")

        return steps


def write_recommendations(recommendations: Dict[str, Any], output_path: Path) -> None:
    """Write recommendations to JSON file."""

    with open(output_path, "w") as f:
        json.dump(recommendations, f, indent=2)


def _render_role_recommendations(selections: Dict[str, Any]) -> str:
    """Render role recommendations for the standalone HTML writer."""
    html_parts = []
    roles = ["DEM", "Soil", "Vegetation", "Hydrology", "Contours", "Extent", "Vehicle"]
    for role in roles:
        if role not in selections:
            continue
        selection = selections[role]
        recommended = selection.get("recommended", "UNKNOWN")
        score = selection.get("score")
        metrics = selection.get("metrics", {})
        reason = selection.get("reason", "No reason provided")
        alternatives = selection.get("alternatives", [])
        if recommended == "MANUAL_SELECTION_REQUIRED":
            html_parts.append(
                "<section class='role-section'><div class='role-name'>%s</div>"
                "<div style='color:var(--red);font-weight:600'>Manual Selection Required</div>"
                "<p>%s</p></section>" % (role, reason)
            )
            continue
        score_badge = "<span class='score-badge'>%s/10</span>" % score if score else ""
        html_parts.append(
            "<section class='role-section'><div class='role-name'>%s</div>"
            "<div class='recommended'>%s</div>%s"
            "<div class='metrics'>"
            "<div class='metric'><div class='metric-label'>Quality</div><div class='metric-value'>%s/10</div></div>"
            "<div class='metric'><div class='metric-label'>Fitness</div><div class='metric-value'>%s/10</div></div>"
            "<div class='metric'><div class='metric-label'>Confidence</div><div class='metric-value'>%s</div></div>"
            "<div class='metric'><div class='metric-label'>Coverage</div><div class='metric-value'>%s%%</div></div>"
            "</div><p>%s</p>" % (
                role,
                recommended,
                score_badge,
                metrics.get("quality", "N/A"),
                metrics.get("fitness", "N/A"),
                metrics.get("confidence", "N/A"),
                metrics.get("coverage_pct", "N/A"),
                reason,
            )
        )
        if alternatives:
            html_parts.append("<div><strong>Alternatives:</strong>")
            for alternative in alternatives:
                html_parts.append(
                    "<div class='alternative'>%s (%s/10) - %s</div>" % (
                        alternative.get("name", "Unknown"),
                        alternative.get("score", "?"),
                        alternative.get("reason", ""),
                    )
                )
            html_parts.append("</div>")
        html_parts.append("</section>")
    return "".join(html_parts)


def _render_warnings_section(warnings: List[str]) -> str:
    """Render recommendation warnings for the standalone HTML writer."""
    if not warnings:
        return ""
    items = "".join(
        "<div class='warning'><strong>Warning</strong> %s</div>" % str(warning).replace("⚠ ", "")
        for warning in warnings
    )
    return "<h2 class='section'>Warnings &amp; Considerations</h2>" + items


def write_recommendations_html(recommendations: Dict[str, Any], output_path: Path) -> None:
    """Write recommendations to HTML report."""

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CCM Data Recommendations v0.58.2</title>
<style>
:root{{--navy:#102a43;--blue:#1769aa;--teal:#0f766e;--ink:#243b53;--muted:#627d98;--paper:#f7fafc;--line:#d9e2ec;--gold:#f0b429;--red:#c05621}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 "Segoe UI",Arial,sans-serif}}
.hero{{background:linear-gradient(135deg,var(--navy),#1f6f8b);color:white;padding:42px calc((100% - 1080px)/2) 36px}}
.hero h1{{margin:0 0 6px;font-size:34px;letter-spacing:.2px}}.hero p{{margin:0;color:#d9f0f5;font-size:17px}}
main{{max-width:1080px;margin:0 auto;padding:28px 24px 54px}}
.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:24px}}
.card{{background:white;border:1px solid var(--line);border-radius:12px;padding:18px;box-shadow:0 3px 12px rgba(16,42,67,.06)}}
.card h2{{margin:0 0 7px;color:var(--navy);font-size:18px}}.card p{{margin:0;color:var(--muted)}}
.role-section{{background:white;border:1px solid var(--line);border-radius:12px;padding:24px;margin-bottom:20px;box-shadow:0 3px 12px rgba(16,42,67,.06)}}
.role-name{{color:var(--navy);font-weight:600;font-size:16px;margin-bottom:8px}}
.recommended{{color:var(--teal);font-size:18px;font-weight:600}}
.score-badge{{display:inline-block;background:#e6f9f7;border:1px solid #81e6d9;padding:6px 12px;border-radius:6px;font-size:13px;color:var(--teal);margin-top:8px}}
.metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:12px;font-size:13px}}
.metric{{background:var(--paper);padding:8px;border-radius:6px}}
.metric-label{{color:var(--muted);font-size:12px}}.metric-value{{font-weight:600;color:var(--navy);margin-top:4px}}
.alternative{{background:#f9f9f9;border-left:3px solid var(--line);padding:12px;margin-top:8px;border-radius:4px;font-size:13px}}
.warning{{background:#fffaf0;border:1px solid #f6d365;border-radius:9px;padding:15px 18px;margin:16px 0;color:#975a16}}
.warning strong{{color:#975a16}}
.callout{{padding:15px 18px;border-radius:9px;background:#e6fffa;border:1px solid #81e6d9;margin:16px 0}}
.callout strong{{color:var(--teal)}}
h2.section{{margin:30px 0 12px;color:var(--navy);font-size:22px;border-bottom:2px solid var(--line);padding-bottom:7px}}
.next-steps{{list-style:none;padding-left:0}}
.next-steps li{{margin:10px 0;padding-left:28px;position:relative}}
.next-steps li:before{{content:'→';position:absolute;left:0;color:var(--blue);font-weight:600}}
.footer{{margin-top:34px;padding-top:18px;border-top:1px solid var(--line);color:var(--muted);font-size:13px}}
</style>
</head>
<body>
<header class="hero">
<h1>CCM Data Recommendations v0.58.2</h1>
<p>Reviewable source guidance for mobility modeling</p>
</header>
<main>

<h2 class="section">Recommendations Summary</h2>
<div class="grid">
<div class="card">
<h2>Model Confidence</h2>
<p style="font-size:24px;color:var(--navy);font-weight:600">{recommendations.get('model_confidence', 'Unknown')}</p>
</div>
<div class="card">
<h2>Readiness Status</h2>
<p style="font-size:24px;color:var(--navy);font-weight:600">{recommendations.get('readiness', 'Unknown')}</p>
</div>
<div class="card">
<h2>Data Root</h2>
<p style="font-size:13px">{Path(recommendations.get('data_root', 'Unknown')).name}</p>
</div>
</div>

{_render_role_recommendations(recommendations.get('selections', {}))}

{_render_warnings_section(recommendations.get('warnings', []))}

<h2 class="section">Next Steps</h2>
<ol class="next-steps">
{''.join(f'<li>{step}</li>' for step in recommendations.get('next_steps', []))}
</ol>

<div class="footer">Generated {recommendations.get('timestamp', 'Unknown')} | CCM Tool v0.58.2 | Data Intelligence & Auto-Selection</div>
</main>
</body>
</html>
"""

    with open(output_path, "w") as f:
        f.write(html)

    return html

    def _legacy_render_role_recommendations(self, selections: Dict[str, Any]) -> str:
        """Render role-by-role recommendations."""

        html_parts = []

        for role in ["DEM", "Soil", "Vegetation", "Hydrology", "Contours", "Extent", "Vehicle"]:
            if role not in selections:
                continue

            sel = selections[role]
            rec = sel.get("recommended", "UNKNOWN")
            score = sel.get("score")
            metrics = sel.get("metrics", {})
            reason = sel.get("reason", "No reason provided")
            alts = sel.get("alternatives", [])

            score_badge = (
                f'<span class="score-badge">{score}/10</span>' if score else ""
            )

            if rec == "MANUAL_SELECTION_REQUIRED":
                html_parts.append(f"""
<div class="role-section">
<div class="role-name">⚠ {role}</div>
<div style="color:var(--red);font-weight:600">Manual Selection Required</div>
<p style="margin:8px 0;font-size:13px">{reason}</p>
</div>
""")
            else:
                html_parts.append(f"""
<div class="role-section">
<div class="role-name">{role}</div>
<div class="recommended">{rec}</div>
{score_badge}
<div class="metrics">
<div class="metric"><div class="metric-label">Quality</div><div class="metric-value">{metrics.get('quality', 'N/A')}/10</div></div>
<div class="metric"><div class="metric-label">Fitness</div><div class="metric-value">{metrics.get('fitness', 'N/A')}/10</div></div>
<div class="metric"><div class="metric-label">Confidence</div><div class="metric-value">{metrics.get('confidence', 'N/A')}</div></div>
<div class="metric"><div class="metric-label">Coverage</div><div class="metric-value">{metrics.get('coverage_pct', 'N/A')}%</div></div>
</div>
<p style="margin:12px 0 0;font-size:13px;color:var(--muted)">{reason}</p>
""")

            # Alternatives
            if alts:
                html_parts.append('<div style="margin-top:12px"><strong>Alternatives:</strong>')

                for alt in alts:
                    html_parts.append(
                        f'<div class="alternative">{alt.get("name")} ({alt.get("score")}/10) — {alt.get("reason")}</div>'
                    )

                html_parts.append("</div>")

            html_parts.append("</div>")

        return "".join(html_parts)

    def _legacy_render_warnings_section(self, warnings: List[str]) -> str:
        """Render warnings section."""

        if not warnings:
            return ""

        return f"""
<h2 class="section">Warnings & Considerations</h2>
{''.join(f'<div class="warning"><strong>⚠</strong> {w.replace("⚠ ", "")}</div>' for w in warnings)}
"""


if __name__ == "__main__":
    # Quick test
    test_catalog = {
        "data_root": "/data/test",
        "aoi_file": "/data/test/AOI.shp",
        "datasets": [
            {
                "name": "ASTER_30m.tif",
                "dataset_type": "raster",
                "source_type": "ASTER",
                "resolution": "30 m",
                "coverage_pct": 95.0,
                "role_basis": "DEM",
            },
            {
                "name": "soil_rci.csv",
                "dataset_type": "table",
                "source_type": "CSV",
                "role_basis": "Soil",
            },
        ],
    }

    test_quality = {"ASTER_30m.tif": 8.0, "soil_rci.csv": 9.0}
    test_fitness = {
        "ASTER_30m.tif": {"DEM": 8.0},
        "soil_rci.csv": {"Soil": 9.0},
    }
    test_confidence = {
        "DEM": {"confidence_level": "High"},
        "Soil": {"confidence_level": "High"},
    }
    test_readiness = {
        "readiness_status": "Ready",
        "readiness_pct": 100,
        "missing_items": [],
    }

    selector = DataSelector()
    result = selector.recommend_all_roles(
        test_catalog,
        test_quality,
        test_fitness,
        test_confidence,
        test_readiness,
    )

    print(json.dumps(result, indent=2))

# <<< END OF FILE >>>
