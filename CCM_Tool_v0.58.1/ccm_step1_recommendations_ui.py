#!/usr/bin/env python3
"""
CCM Tool v0.58 — Step 1 Recommendations UI Module

Displays auto-selected recommendations at Step 1 startup.
Allows user to accept or override recommendations.

Usage in ccm_step1_setup.py:
  from ccm_step1_recommendations_ui import display_recommendations

  # At tool init/validate time:
  display_recommendations(project_folder, arcpy)

VERSION = "0.58"
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Any

VERSION = "0.58"


def display_recommendations(
    project_folder: Path,
    arcpy_module: Optional[Any] = None,
    verbose: bool = True
) -> Dict[str, Dict[str, str]]:
    """
    Load and display recommendations at Step 1 startup.

    Args:
        project_folder: Path to project output folder (where Step 0b wrote files)
        arcpy_module: arcpy module (for arcpy.AddMessage/AddWarning); optional
        verbose: Print to console if arcpy not available

    Returns:
        recommendations dict for programmatic access
    """

    recommendations_path = Path(project_folder) / "ccm_recommendations.json"

    if not recommendations_path.exists():
        msg = "ℹ No recommendations found. Step 0b may not have run, or was from v0.57."
        if arcpy_module:
            arcpy_module.AddMessage(msg)
        if verbose:
            print(f"[Step 1] {msg}")

        return {}

    try:
        with open(recommendations_path) as f:
            recommendations = json.load(f)
    except Exception as e:
        msg = f"⚠ Could not load recommendations: {e}"
        if arcpy_module:
            arcpy_module.AddWarning(msg)
        if verbose:
            print(f"[Step 1] {msg}")

        return {}

    # Display model-level status
    model_conf = recommendations.get("model_confidence", "Unknown")
    readiness = recommendations.get("readiness", "Unknown")

    header = f"\n{'='*70}\nCCM v0.58 Data Intelligence Recommendations\n{'='*70}\n"
    if arcpy_module:
        arcpy_module.AddMessage(header)
    if verbose:
        print(header)

    status_msg = f"Model Confidence: {model_conf} | Readiness: {readiness}\n"
    if arcpy_module:
        arcpy_module.AddMessage(status_msg)
    if verbose:
        print(status_msg)

    # Display role-by-role recommendations
    selections = recommendations.get("selections", {})

    for role in ["DEM", "Soil", "Vegetation", "Hydrology", "Contours", "Extent", "Vehicle"]:
        if role not in selections:
            continue

        sel = selections[role]
        recommended = sel.get("recommended", "UNKNOWN")
        score = sel.get("score")
        reason = sel.get("reason", "No reason provided")
        alts = sel.get("alternatives", [])

        if recommended == "MANUAL_SELECTION_REQUIRED":
            # Warning for manual selection
            msg = f"\n⚠ {role}: MANUAL SELECTION REQUIRED"
            if arcpy_module:
                arcpy_module.AddWarning(msg)
            if verbose:
                print(msg)

            msg2 = f"  Reason: {reason}"
            if arcpy_module:
                arcpy_module.AddMessage(msg2)
            if verbose:
                print(msg2)

        else:
            # Recommendation with score
            if score:
                msg = f"\n✓ {role}: {recommended} (score: {score:.1f}/10)"
            else:
                msg = f"\n✓ {role}: {recommended}"

            if arcpy_module:
                arcpy_module.AddMessage(msg)
            if verbose:
                print(msg)

            msg2 = f"  {reason}"
            if arcpy_module:
                arcpy_module.AddMessage(msg2)
            if verbose:
                print(msg2)

            # Show alternatives
            if alts:
                msg3 = f"  Alternatives:"
                if arcpy_module:
                    arcpy_module.AddMessage(msg3)
                if verbose:
                    print(msg3)

                for alt in alts:
                    alt_name = alt.get("name", "Unknown")
                    alt_score = alt.get("score", "?")
                    msg_alt = f"    • {alt_name} (score: {alt_score}/10)"
                    if arcpy_module:
                        arcpy_module.AddMessage(msg_alt)
                    if verbose:
                        print(msg_alt)

    # Display warnings
    warnings = recommendations.get("warnings", [])

    if warnings:
        warn_header = "\n⚠ Warnings & Considerations:\n"
        if arcpy_module:
            arcpy_module.AddWarning(warn_header)
        if verbose:
            print(warn_header)

        for warning in warnings:
            clean_warn = warning.replace("⚠ ", "  • ")
            if arcpy_module:
                arcpy_module.AddWarning(clean_warn)
            if verbose:
                print(clean_warn)

    # Display next steps
    next_steps = recommendations.get("next_steps", [])

    if next_steps:
        steps_header = "\n→ Next Steps:\n"
        if arcpy_module:
            arcpy_module.AddMessage(steps_header)
        if verbose:
            print(steps_header)

        for step in next_steps:
            msg_step = f"  {step}"
            if arcpy_module:
                arcpy_module.AddMessage(msg_step)
            if verbose:
                print(msg_step)

    footer = f"\n{'='*70}\n"
    if arcpy_module:
        arcpy_module.AddMessage(footer)
    if verbose:
        print(footer)

    return recommendations


def get_recommended_source(
    role: str,
    recommendations: Dict[str, Any]
) -> Optional[str]:
    """
    Get recommended source for a specific role.

    Args:
        role: "DEM", "Soil", "Vegetation", etc.
        recommendations: Dict from load_recommendations()

    Returns:
        Recommended dataset name, or None if manual selection required
    """

    selections = recommendations.get("selections", {})

    if role not in selections:
        return None

    recommended = selections[role].get("recommended")

    if recommended == "MANUAL_SELECTION_REQUIRED":
        return None

    return recommended


def get_alternatives(
    role: str,
    recommendations: Dict[str, Any]
) -> List[str]:
    """
    Get alternative sources for a role.

    Args:
        role: "DEM", "Soil", "Vegetation", etc.
        recommendations: Dict from load_recommendations()

    Returns:
        List of alternative dataset names
    """

    selections = recommendations.get("selections", {})

    if role not in selections:
        return []

    alternatives = selections[role].get("alternatives", [])

    return [alt.get("name") for alt in alternatives]


def log_override(
    role: str,
    recommended: str,
    chosen: str,
    project_folder: Path,
    reason: Optional[str] = None
) -> None:
    """
    Log a user override decision for audit trail.

    Args:
        role: "DEM", "Soil", etc.
        recommended: What was recommended
        chosen: What user chose instead
        project_folder: Where to write log
        reason: Optional reason for override
    """

    log_path = Path(project_folder) / "ccm_recommendations_overrides.log"

    from datetime import datetime

    timestamp = datetime.now().isoformat()
    override_entry = (
        f"{timestamp} | {role}: recommended={recommended}, chosen={chosen}"
    )

    if reason:
        override_entry += f", reason={reason}"

    with open(log_path, "a") as f:
        f.write(override_entry + "\n")


if __name__ == "__main__":
    # Quick test
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create a test recommendations file
        test_rec = {
            "model_confidence": "Acceptable",
            "readiness": "Ready",
            "selections": {
                "DEM": {
                    "recommended": "ASTER_30m.tif",
                    "score": 7.8,
                    "reason": "ASTER_30m: Quality 8/10, Fitness 8/10, 95% coverage, High confidence",
                    "alternatives": [
                        {
                            "name": "SRTM_30m.tif",
                            "score": 6.2,
                            "reason": "Geographic CRS; requires reprojection",
                        }
                    ],
                },
                "Soil": {
                    "recommended": "MANUAL_SELECTION_REQUIRED",
                    "reason": "No soil dataset meets fitness threshold",
                },
            },
            "warnings": ["⚠ Soil: No suitable dataset found"],
            "next_steps": ["Accept DEM", "Select Soil manually", "Proceed to Step 2"],
        }

        rec_path = tmpdir / "ccm_recommendations.json"
        with open(rec_path, "w") as f:
            json.dump(test_rec, f)

        # Test display
        recommendations = display_recommendations(tmpdir, verbose=True)

        print("\n--- Programmatic access test ---")
        print(f"DEM recommended: {get_recommended_source('DEM', recommendations)}")
        print(f"DEM alternatives: {get_alternatives('DEM', recommendations)}")
        print(f"Soil recommended: {get_recommended_source('Soil', recommendations)}")

        # Test override logging
        log_override("DEM", "ASTER_30m.tif", "SRTM_30m.tif", tmpdir, "Local validation")
        print(f"\nOverride logged to: {tmpdir / 'ccm_recommendations_overrides.log'}")
