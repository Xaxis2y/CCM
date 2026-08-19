# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CCM_Tool_v0.57.pyt — ArcGIS Python Toolbox entry point
====================================================
Cross-Country Mobility (CCM) Assessment Tool  v0.57

Toolbox exposes six tool steps:
  Step 0  — Load MGCP Data               (CCMStep0MGCPTool)
  Step 0b — Data Intelligence Scan       (CCMDataIntelligenceTool)
  Step 1  — Project Setup & Pre-process   (CCMStep1SetupTool)
  Step 2  — Generate Mobility Map         (CCMStep2MobilityTool)
  Step 3  — Advanced Analysis             (CCMStep3AdvancedTool)
  Step 4  — Compare Two Vehicles          (CCMVehicleCompareTool)

This file registers the toolbox only. There is no command-line / __main__
entry point — ArcGIS Pro never executes a .pyt as __main__, so a prior
CCMAssessment/main() "direct-run" path here was unreachable in normal use
and, if invoked, produced a summary.json echoing its inputs without running
any real analysis (a false-success trap). It was removed in the v0.57
post-review pass; see CHANGELOG_v0.57.md ("M-4"). Run the six registered
tools from the ArcGIS Pro Geoprocessing pane instead.

v0.57 post-review changes (this file):
  - Removed the dead CCMAssessment / main() / __main__ command-line path
    (~250 lines) and its four orphaned helper functions (_validate_distance,
    validate_feature_class, _create_unique_folder, _resolve_obstacle_source),
    none of which were used by the real Step 0-4 tool classes. See
    CHANGELOG_v0.57.md "M-4".

v0.57 changes (this file):
  - Integrated the validated Data Intelligence Step 0b tool between Step 0
    and Step 1. It adds factual inventory, metadata, duplicate, and CRS
    reporting while preserving the existing Steps 0-4 workflow. Data Quality,
    Fitness, and automatic source selection remain future scope.
    See CHANGELOG_v0.57.md and TOOLBOX_INTEGRATION.md.

v0.55.0 changes (this file):
  - Filename/version bump only. v0.55.0 reconciles two divergent copies of
    this project that had been edited on separate machines: one line had
    a name-cleanup pass applied but none of the v0.54.2-v0.54.7 fixes;
    the other had all of those fixes but the cleanup had not yet reached
    it. v0.55.0 merges the two: all v0.54.2-v0.54.7 fixes, on the cleaned
    naming and licensing. No functional / geoprocessing logic changed
    beyond what v0.54.2-v0.54.7 already shipped. See CHANGELOG_v0.57.md.

v0.54.7 changes (this file):
  - Filename/version bump only. The real fix this round is in
    tests/arcpy_smoke_test_step3.py: the diagnostic that reported which
    isochrone code path ran (Spatial Analyst raster vs. vector fallback)
    inspected msgs.warnings, but ccm_isochrone.py logs via the global
    arcpy.AddWarning(), not the messages object — so the check silently
    reported the wrong path. Fixed with a "gridcode" field-presence check.
    No logic in this entry-point file, nor in ccm_isochrone.py's actual
    isochrone generation, changed. See CHANGELOG_v0.54.md.

v0.54.6 changes (this file):
  - Filename/version bump only. A real ArcGIS Pro 3.7.1 re-run showed the
    v0.54.5 mitigation for ERROR 160333 fires but does not resolve it; the
    actual follow-up fix (in-memory Reclassify + vector-method fallback in
    generate_isochrones()) lives in ccm_isochrone.py, plus a smoke-test
    visibility improvement in tests/arcpy_smoke_test_step3.py; no logic in
    this entry-point file changed. See CHANGELOG_v0.54.md.

v0.54.5 changes (this file):
  - Filename/version bump only. The actual fix (ERROR 160333 on Reclassify
    in the Reachability Map / Isochrone tool, plus a vehicle-name bug in
    tests/arcpy_smoke_test_step1.py) lives in ccm_isochrone.py and the test
    suite; no logic in this entry-point file changed. See CHANGELOG_v0.54.md.

v0.54.1 changes (this file):
  - Renamed and standardized throughout (toolname, alias, filenames;
    toolbox and sidecars renamed to the CCM_Tool_v<ver> convention used
    from this point on; build.py, tests, docs, and the user manual
    updated to match).
  - Relicensed under SPDX-License-Identifier: GPL-2.0-or-later
    (previously "All Rights Reserved"). New copyright line:
    Copyright (c) 2026 Eui Soo SON.
  - No functional / geoprocessing logic changed. See CHANGELOG_v0.54.md.

v0.54.0 changes (this file):
  - Filename/version bump only — smart CRS/projection warnings were added
    to the imported step modules (ccm_step0_mgcp.py, ccm_step1_setup.py,
    ccm_step3_advanced.py, ccm_vehicle_compare.py) and the shared
    ccm_coords.py helper; no logic in this entry-point file changed.
    See CHANGELOG_v0.54.md.

v0.46 changes (this file):
  - Added proper Toolbox class so ArcGIS Pro discovers all six tools.
  - Fixed module imports: all sub-tool classes now imported by their real
    names (CCMStep1SetupTool, CCMStep3AdvancedTool, CCMVehicleCompareTool).
  - Replaced all print() calls with arcpy.AddMessage() / arcpy.AddError().
  - Added _validate_distance() — warns on missing/invalid distance, detects units.
  - Added validate_feature_class() — checks existence, data type, geometry.
  - Added _create_unique_folder() — handles simultaneous-run race condition.
  - Added _resolve_obstacle_source() — auto-detects raster / FC / CSV input.
  - Added arcpy.SetLogMetadata(False) in CCMAssessment.execute() for perf.
  - Timestamps on all log messages via _log() helper.
  - summary.json uses UTC ISO-8601 timestamp.
"""

import arcpy
import os
import sys

# ── Ensure the toolbox directory is on sys.path ───────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# Tool metadata
toolname    = "CCM_Tool"
toolversion = "0.57"


# ── Stub-tool factory ─────────────────────────────────────────────────────────
def _make_stub_tool(label, import_error):
    """
    Build a placeholder tool class for a step whose module failed to import.

    Instead of silently dropping the tool from the toolbox (so the user never
    learns why it vanished), we register a stub that appears in the toolbox and
    reports the underlying import error when opened or run.
    """
    class _StubTool(object):
        def __init__(self):
            self.label = f"{label}  [UNAVAILABLE — failed to load]"
            self.description = (
                f"This tool could not be loaded due to an import error:\n\n"
                f"{import_error}\n\n"
                "Fix the underlying module (see the error above) and reload "
                "the toolbox."
            )
            self.canRunInBackground = False

        def getParameterInfo(self):
            return []

        def isLicensed(self):
            return True

        def updateParameters(self, parameters):
            pass

        def updateMessages(self, parameters):
            pass

        def execute(self, parameters, messages):
            arcpy.AddError(
                f"'{label}' is unavailable — module failed to import:\n{import_error}"
            )
            raise arcpy.ExecuteError(f"{label} failed to load: {import_error}")

    return _StubTool


# ── Import step tool classes (register a stub if any import fails) ────────────
try:
    from ccm_step0_mgcp import CCMStep0MGCPTool
except Exception as _e:
    CCMStep0MGCPTool = _make_stub_tool("Step 0.  Load MGCP Data", _e)
    arcpy.AddWarning(f"[CCM_Tool] ccm_step0_mgcp not loaded: {_e}")

try:
    from ccm_step0b_intelligence import CCMDataIntelligenceTool
except Exception as _e:
    CCMDataIntelligenceTool = _make_stub_tool(
        "Step 0b.  Data Intelligence Scan", _e)
    arcpy.AddWarning(
        f"[CCM_Tool] ccm_step0b_intelligence not loaded: {_e}")

try:
    from ccm_step1_setup import CCMStep1SetupTool
except Exception as _e:
    CCMStep1SetupTool = _make_stub_tool("Step 1.  Project Setup & Pre-process", _e)
    arcpy.AddWarning(f"[CCM_Tool] ccm_step1_setup not loaded: {_e}")

try:
    from ccm_step2_mobility import CCMStep2MobilityTool
except Exception as _e:
    CCMStep2MobilityTool = _make_stub_tool("Step 2.  Generate Mobility Map", _e)
    arcpy.AddWarning(f"[CCM_Tool] ccm_step2_mobility not loaded: {_e}")

try:
    from ccm_step3_advanced import CCMStep3AdvancedTool
except Exception as _e:
    CCMStep3AdvancedTool = _make_stub_tool("Step 3.  Advanced Analysis", _e)
    arcpy.AddWarning(f"[CCM_Tool] ccm_step3_advanced not loaded: {_e}")

try:
    from ccm_vehicle_compare import CCMVehicleCompareTool
except Exception as _e:
    CCMVehicleCompareTool = _make_stub_tool("Step 4.  Compare Two Vehicles", _e)
    arcpy.AddWarning(f"[CCM_Tool] ccm_vehicle_compare not loaded: {_e}")


# =============================================================================
# TOOLBOX DEFINITION
# =============================================================================

class Toolbox(object):
    """ArcGIS Python Toolbox container — registers all CCM tool steps."""

    def __init__(self):
        self.label   = f"{toolname} v{toolversion}"
        self.alias   = "CCMTool"
        # All steps are registered.  Steps whose module failed to import are
        # represented by a stub tool that reports the error (see _make_stub_tool)
        # rather than silently disappearing from the toolbox.
        self.tools   = [
            CCMStep0MGCPTool,
            CCMDataIntelligenceTool,
            CCMStep1SetupTool,
            CCMStep2MobilityTool,
            CCMStep3AdvancedTool,
            CCMVehicleCompareTool,
        ]

# <<< END OF FILE >>>
