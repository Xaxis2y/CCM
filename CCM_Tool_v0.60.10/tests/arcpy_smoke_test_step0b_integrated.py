# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""ArcGIS Pro smoke test for the v0.59.2 Step 0b integration."""

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent
for candidate in (ROOT, TESTS):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))


VERSION = "0.60.10"


def main(argv=None):
    parser = argparse.ArgumentParser(description="CCM v0.59.2 ArcPy smoke test")
    parser.add_argument("--artifact-dir", default=str(ROOT / "arcpy_smoke_artifacts"))
    args = parser.parse_args(argv)

    try:
        import arcpy
    except Exception as exc:
        print("ARCPY_SMOKE_BLOCKED: ArcPy is unavailable: %s" % exc)
        return 2

    from make_fake_data import build
    from ccm_step0b_integration import Step0bIntegrator
    from ccm_step0b_intelligence import CCMDataIntelligenceTool
    from ccm_step1_recommendations_ui import display_recommendations

    artifact_dir = Path(args.artifact_dir).resolve()
    data_root = artifact_dir / "fake_data"
    project = artifact_dir / "project"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    build(str(data_root))

    tool = CCMDataIntelligenceTool()
    parameters = tool.getParameterInfo()
    if len(parameters) != 5:
        raise AssertionError("Step 0b should expose five parameters")

    def log(message):
        arcpy.AddMessage(str(message))

    result = Step0bIntegrator(
        data_root,
        aoi_path=data_root / "Extent" / "AOI_Lebanon.shp",
        project_folder=project,
        log_callback=log,
    ).run(verbose=False, log_callback=log)
    if result.get("status") != "success":
        raise RuntimeError(result.get("error", "Step 0b integration failed"))

    display_recommendations(project, arcpy_module=arcpy, verbose=False)

    # v0.60.0 -- Step0bIntegrator now writes these into
    # <project>/02_Scan_Index/ instead of directly into project (see
    # ccm_step0b_integration.py's report_dir separation); ccm_project.json
    # alone stays directly in project.
    scan_index = project / "02_Scan_Index"
    required = [
        "ccm_data_catalog.json",
        "ccm_quality_scores.json",
        "ccm_fitness_scores.json",
        "ccm_confidence_scores.json",
        "ccm_readiness_scores.json",
        "ccm_recommendations.json",
        "CCM_Recommendations_Report.html",
    ]
    missing = [name for name in required if not (scan_index / name).is_file()]
    if not (project / "ccm_project.json").is_file():
        missing.append("ccm_project.json")
    if missing:
        raise AssertionError("Missing ArcPy smoke outputs: %s" % ", ".join(missing))

    with (scan_index / "ccm_recommendations.json").open(encoding="utf-8") as stream:
        recommendations = json.load(stream)
    if recommendations.get("version") != VERSION:
        raise AssertionError("Recommendation version mismatch")

    print("ARCPY_SMOKE_PASS: v%s Step 0b integration and recommendation display" % VERSION)
    print("PROJECT: %s" % project)
    return 0


if __name__ == "__main__":
    sys.exit(main())

# <<< END OF FILE >>>
