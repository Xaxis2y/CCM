# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON

# -*- coding: utf-8 -*-
# ccm_step3_advanced.py
# CCM Step 3 — Advanced Analysis
#
# Loads ccm_project.json from Step 1/2 and runs any combination of:
#   A. Reason Map        — why areas are blocked / slow
#   B. Reachability Map  — travel-time zones (isochrone) from a start point
#   C. Vehicle Compare   — side-by-side difference map for two vehicles
#   D. Obstacle Detect   — hidden barriers, slope breaks, gap crossings
#   E. Waypoint Route    — fastest route A → B
#
# VERSION = "0.54.1"
VERSION = "0.54.1"
# v0.54.1 — GPL-2.0-or-later relicense + CCM Tool by Son rebrand (see CHANGELOG_v0.54.md).
# v0.49.3 — Version bump to align all modules.
# v0.48 — Version bump for the toolbox-wide v0.48.0 release.
# v0.46 — Bug fixes:
#          1. Replaced unreliable `"iso_latlon" in dir()` / `"wp_start_latlon" in dir()`
#             variable-existence checks with explicit None-initialisation before each
#             conditional block and `is not None` checks.
#          2. Unified speed field default from "Speed_kph" → "SpeedKMH" to match
#             ccm_vehicle_compare.py and the main CCM tool output field name.
#          3. Removed dead Output-parameter search loop in Reason Map block
#             (CCMReasonMapTool has no Output parameter; the loop was a no-op).
#          4. Replaced print() import-error messages with arcpy.AddWarning() so
#             module load failures are visible in the ArcGIS Pro Messages pane.
# v0.46 — Rewrote start/end point FC creation:
#          1. Isochrone / Waypoint tools received "lat lon" (e.g. "45.64 -75.59")
#             which the DD regex rejected, silently skipping those analyses.
#             Fixed by passing hemisphere-formatted DD ("45.646590N 75.595659W").
#          2. Start/end point markers still placed incorrectly (too far north)
#             because SHAPE@XY insert was affected by env.outputCoordinateSystem.
#             Fixed by clearing env.outputCoordinateSystem around FC creation
#             and using arcpy.PointGeometry(Point(lon,lat), SR_4326) for insert.
#          3. ccm_coords.py DD regex updated to recognise "lat lon" with signed
#             second number (e.g. "45.64 -75.59") — the old regex consumed the
#             space separator before checking for hemisphere letter, leaving
#             nothing for [,\s] to match against the minus sign.

import arcpy
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# ── Companion modules ─────────────────────────────────────────────────────────
_cfg_mod = None
try:
    import ccm_project_config as _cfg_mod
except Exception as e:
    arcpy.AddWarning(f"[Step 3] ccm_project_config: {e}")

_coords_mod = None
try:
    import ccm_coords as _coords_mod
except Exception as e:
    arcpy.AddWarning(f"[Step 3] ccm_coords: {e}")

_CCMReasonMapTool      = None
_CCMIsochroneTool      = None
_CCMVehicleCompareTool = None
_CCMObstacleDetectTool = None
_CCMWaypointTool       = None

try:
    from ccm_reason_map      import CCMReasonMapTool      as _CCMReasonMapTool
except Exception as e:
    arcpy.AddWarning(f"[Step 3] ccm_reason_map: {e}")
try:
    from ccm_isochrone       import CCMIsochroneTool      as _CCMIsochroneTool
except Exception as e:
    arcpy.AddWarning(f"[Step 3] ccm_isochrone: {e}")
try:
    from ccm_vehicle_compare import CCMVehicleCompareTool as _CCMVehicleCompareTool
except Exception as e:
    arcpy.AddWarning(f"[Step 3] ccm_vehicle_compare: {e}")
try:
    from ccm_obstacle_detect import CCMObstacleDetectTool as _CCMObstacleDetectTool
except Exception as e:
    arcpy.AddWarning(f"[Step 3] ccm_obstacle_detect: {e}")
try:
    from ccm_waypoints       import CCMWaypointTool       as _CCMWaypointTool
except Exception as e:
    arcpy.AddWarning(f"[Step 3] ccm_waypoints: {e}")

_display_mod = None
try:
    import ccm_map_display as _display_mod
except Exception as e:
    arcpy.AddWarning(f"[Step 3] ccm_map_display: {e}")


# ── Minimal parameter shim ─────────────────────────────────────────────────────
class _P:
    def __init__(self, value, value_as_text=None, values=None, altered=True):
        self.value       = value
        self.valueAsText = (value_as_text if value_as_text is not None
                            else (str(value) if value is not None else None))
        self.values      = values
        self.altered     = altered

    def hasError(self):   return False
    def hasWarning(self): return False


# ── Speed-surface helpers (v0.50.2 — restored; were lost in a truncated write) ─

_SPEED_FC_PREFIX   = "speed_surface_"
_MOISTURE_SUFFIXES = ("dry", "moist", "wet")


def _list_speed_surfaces(project_gdb):
    """Full paths of Step-2 speed surfaces (speed_surface_*) in *project_gdb*."""
    out = []
    saved_ws = arcpy.env.workspace
    try:
        arcpy.env.workspace = project_gdb
        for fc in (arcpy.ListFeatureClasses() or []):
            name = fc.split(".")[-1] if "." in fc else fc
            if name.lower().startswith(_SPEED_FC_PREFIX):
                out.append(os.path.join(project_gdb, name))
    except Exception:
        pass
    finally:
        arcpy.env.workspace = saved_ws
    return sorted(out)


def _label_from_speed_fc(fc_path):
    """Human-readable vehicle label from a speed-surface FC path/name.

    'speed_surface_leopard_2_moist' → 'Leopard 2 (moist)'
    Names that do not follow the Step-2 convention pass through unchanged.
    """
    base = os.path.splitext(os.path.basename(str(fc_path)))[0]
    name = base
    if name.lower().startswith(_SPEED_FC_PREFIX):
        name = name[len(_SPEED_FC_PREFIX):]
    moisture = None
    for suf in _MOISTURE_SUFFIXES:
        if name.lower().endswith("_" + suf):
            moisture = suf
            name = name[: -(len(suf) + 1)]
            break
    label = name.replace("_", " ").strip()
    if not label:
        return base
    words = [w.upper() if any(c.isdigit() for c in w) else w.capitalize()
             for w in label.split()]
    label = " ".join(words)
    return f"{label} ({moisture})" if moisture else label


def _derive_output_path(speed_fc, folder_path, suffix):
    """Output path for a Step-3 result derived from *speed_fc*.

    Results live next to the speed surface (same GDB) and are named
    '<vehicle-tag>_<suffix>':
        speed_surface_m1a2_moist + 'isochrone' → <gdb>\\m1a2_moist_isochrone
    Falls back to the project GDB (CCM_Project.gdb in *folder_path*) or the
    scratch GDB when the speed surface has no usable workspace.
    """
    speed_fc = str(speed_fc)
    ws   = os.path.dirname(speed_fc)
    base = os.path.splitext(os.path.basename(speed_fc))[0]
    if base.lower().startswith(_SPEED_FC_PREFIX):
        base = base[len(_SPEED_FC_PREFIX):]
    if not ws or not arcpy.Exists(ws):
        gdb = os.path.join(str(folder_path or ""), "CCM_Project.gdb")
        ws  = gdb if arcpy.Exists(gdb) else arcpy.env.scratchGDB
    name = f"{base}_{suffix}"
    try:
        name = arcpy.ValidateTableName(name, ws)
    except Exception:
        pass
    return os.path.join(ws, name)


# =============================================================================
class CCMStep3AdvancedTool:
    """Step 3 — Advanced Analysis.

    Runs post-mobility analyses using the speed surface created in Step 2.
    Select the project folder to auto-load all settings.

    ── What each analysis does ──────────────────────────────────────────────
    A. Reason Map       : Shows WHY each area is slow or blocked — which
                          factor (slope, soil, vegetation, etc.) is limiting
                          speed the most.  Good for briefings & obstacle reports.

    B. Reachability Map : Starting from a point, draws rings showing how far
                          a vehicle can travel in 15 / 30 / 60 / 120 minutes.
                          Also called an Isochrone map.

    C. Vehicle Compare  : Overlays two speed surfaces and highlights where
                          Vehicle A is faster, slower, or equal to Vehicle B.
                          Use this to pick the right vehicle for the mission.

    D. Obstacle Detect  : Scans the terrain for hidden barriers — steep
                          slope breaks, uncrossable water features, and
                          gaps too narrow for the vehicle.

    E. Waypoint Route   : Finds the time-optimal (fastest) route between
                          a Start and End point, respecting terrain speed.
    ─────────────────────────────────────────────────────────────────────────
    """

    def __init__(self):
        self.label              = "Step 3.  Advanced Analysis"
        self.description        = (
            "Run post-mobility analyses: Reason Map, Reachability Map "
            "(Isochrone), Vehicle Comparison, Obstacle Detection, and "
            "Waypoint Routing.  Select the project folder from Step 1/2 "
            "to auto-load the speed surface and project settings."
        )
        self.canRunInBackground = False

    # =========================================================================
    def getParameterInfo(self):


        # ── Core inputs ───────────────────────────────────────────────────────
        p_folder = arcpy.Parameter(
            displayName   = "Project Folder  (folder created in Step 1/2)",
            name          = "project_folder",
            datatype      = "DEFolder",
            parameterType = "Required",
            direction     = "Input",
        )

        p_speed_fc = arcpy.Parameter(
            displayName   = "Speed Surface FC  (auto-filled from project config)",
            name          = "speed_surface_fc",
            datatype      = "DEFeatureClass",
            parameterType = "Required",
            direction     = "Input",
        )

        p_moisture = arcpy.Parameter(
            displayName   = "Soil Moisture Condition",
            name          = "soil_moisture",
            datatype      = "GPString",
            parameterType = "Required",
            direction     = "Input",
        )
        p_moisture.filter.type = "ValueList"
        p_moisture.filter.list = ["dry", "moist", "wet"]
        p_moisture.value       = "moist"

        # ── A. Reason Map ─────────────────────────────────────────────────────
        _CAT_A = "A.  Reason Map — Why Are Areas Blocked or Slow?"

        p_rm_run = arcpy.Parameter(
            displayName   = (
                "Run Reason Map\n"
                "(Shows which terrain factor — slope, soil, vegetation, etc. — "
                "is limiting speed in each area.  Use for obstacle reports and briefings.)"
            ),
            name          = "run_reason_map",
            datatype      = "GPBoolean",
            parameterType = "Optional",
            direction     = "Input",
            category      = _CAT_A,
        )
        p_rm_run.value = False

        p_rm_mobility_field = arcpy.Parameter(
            displayName   = "Mobility Field Name  (field in Speed Surface that stores mobility score)",
            name          = "rm_mobility_field",
            datatype      = "GPString",
            parameterType = "Optional",
            direction     = "Input",
            category      = _CAT_A,
        )
        p_rm_mobility_field.value = "Mobility"

        # ── B. Reachability Map (Isochrone) ───────────────────────────────────
        _CAT_B = "B.  Reachability Map — How Far Can I Get? (Isochrone)"

        p_iso_run = arcpy.Parameter(
            displayName   = (
                "Run Reachability Map\n"
                "(Draws rings showing how far a vehicle can travel in 15, 30, 60, "
                "and 120 minutes from a start point.  Also called an Isochrone map.)"
            ),
            name          = "run_isochrone",
            datatype      = "GPBoolean",
            parameterType = "Optional",
            direction     = "Input",
            category      = _CAT_B,
        )
        p_iso_run.value = False

        p_iso_start = arcpy.Parameter(
            displayName   = "Start Point  — enter in any coordinate format",
            name          = "iso_start_point",
            datatype      = "GPString",
            parameterType = "Optional",
            direction     = "Input",
            category      = _CAT_B,
        )
        p_iso_start.value = ""

        p_iso_start_display = arcpy.Parameter(
            displayName   = "↳ Coordinate Equivalents  (auto-computed — all formats)",
            name          = "iso_start_display",
            datatype      = "GPString",
            parameterType = "Optional",
            direction     = "Input",
            category      = _CAT_B,
        )

        p_iso_intervals = arcpy.Parameter(
            displayName   = "Time Intervals  (minutes, comma-separated — e.g. 15,30,60,120)",
            name          = "iso_time_intervals",
            datatype      = "GPString",
            parameterType = "Optional",
            direction     = "Input",
            category      = _CAT_B,
        )
        p_iso_intervals.value = "15,30,60,120"

        p_iso_speed_field = arcpy.Parameter(
            displayName   = "Speed Field  (km/h field name in Speed Surface)",
            name          = "iso_speed_field",
            datatype      = "GPString",
            parameterType = "Optional",
            direction     = "Input",
            category      = _CAT_B,
        )
        p_iso_speed_field.value = "SpeedKMH"

        # ── C. Vehicle Comparison ─────────────────────────────────────────────
        _CAT_C = "C.  Vehicle Comparison — Which Vehicle Performs Better?"

        p_vc_run = arcpy.Parameter(
            displayName   = (
                "Run Vehicle Comparison\n"
                "(Overlays two speed surfaces and highlights where Vehicle A is "
                "faster, slower, or equal to Vehicle B.  Use this to pick the "
                "right vehicle for the mission.)"
            ),
            name          = "run_vehicle_compare",
            datatype      = "GPBoolean",
            parameterType = "Optional",
            direction     = "Input",
            category      = _CAT_C,
        )
        p_vc_run.value = False

        p_vc_fc_b = arcpy.Parameter(
            displayName   = (
                "Vehicle B — Speed Surface\n"
                "(Auto-populated from project database.  "
                "Vehicle A is the Speed Surface FC selected above.)"
            ),
            name          = "vc_fc_b",
            datatype      = "GPString",
            parameterType = "Optional",
            direction     = "Input",
            category      = _CAT_C,
        )
        p_vc_fc_b.filter.type = "ValueList"
        p_vc_fc_b.filter.list = []

        p_vc_name_a = arcpy.Parameter(
            displayName   = "Vehicle A Label  (auto-derived from Speed Surface A name)",
            name          = "vc_name_a",
            datatype      = "GPString",
            parameterType = "Optional",
            direction     = "Input",
            category      = _CAT_C,
        )

        p_vc_name_b = arcpy.Parameter(
            displayName   = "Vehicle B Label  (auto-derived from Speed Surface B name)",
            name          = "vc_name_b",
            datatype      = "GPString",
            parameterType = "Optional",
            direction     = "Input",
            category      = _CAT_C,
        )

        # ── D. Obstacle Detection ─────────────────────────────────────────────
        _CAT_D = "D.  Obstacle Detection — Find Hidden Barriers"

        p_obs_run = arcpy.Parameter(
            displayName   = (
                "Run Obstacle Detection\n"
                "(Scans the terrain for hidden barriers: steep slope breaks, "
                "uncrossable water features, and gaps too narrow for the vehicle.  "
                "Contour and Hydro FCs are auto-filled from the project config.)"
            ),
            name          = "run_obstacle_detect",
            datatype      = "GPBoolean",
            parameterType = "Optional",
            direction     = "Input",
            category      = _CAT_D,
        )
        p_obs_run.value = False

        p_obs_contours = arcpy.Parameter(
            displayName   = "Contour Lines FC  (auto-filled from project config — slope breaks)",
            name          = "obs_contours_fc",
            datatype      = "DEFeatureClass",
            parameterType = "Optional",
            direction     = "Input",
            category      = _CAT_D,
        )

        p_obs_hydro = arcpy.Parameter(
            displayName   = "Hydro / Water Feature FC  (auto-filled from project config — stream crossings)",
            name          = "obs_hydro_fc",
            datatype      = "DEFeatureClass",
            parameterType = "Optional",
            direction     = "Input",
            category      = _CAT_D,
        )

        # ── E. Waypoint Routing ───────────────────────────────────────────────
        _CAT_E = "E.  Waypoint Routing — Find Fastest Route A to B"

        p_wp_run = arcpy.Parameter(
            displayName   = (
                "Run Waypoint Routing\n"
                "(Finds the time-optimal route from a Start Point to an End Point, "
                "choosing paths where the vehicle can travel fastest.  "
                "Enter coordinates in any format below.)"
            ),
            name          = "run_waypoint_route",
            datatype      = "GPBoolean",
            parameterType = "Optional",
            direction     = "Input",
            category      = _CAT_E,
        )
        p_wp_run.value = False

        p_wp_start = arcpy.Parameter(
            displayName   = "Start Point (A)  — enter in any coordinate format",
            name          = "wp_start_point",
            datatype      = "GPString",
            parameterType = "Optional",
            direction     = "Input",
            category      = _CAT_E,
        )

        p_wp_start_display = arcpy.Parameter(
            displayName   = "↳ Start Point — Coordinate Equivalents  (auto-computed)",
            name          = "wp_start_display",
            datatype      = "GPString",
            parameterType = "Optional",
            direction     = "Input",
            category      = _CAT_E,
        )

        p_wp_end = arcpy.Parameter(
            displayName   = "End Point (B)  — enter in any coordinate format",
            name          = "wp_end_point",
            datatype      = "GPString",
            parameterType = "Optional",
            direction     = "Input",
            category      = _CAT_E,
        )

        p_wp_end_display = arcpy.Parameter(
            displayName   = "↳ End Point — Coordinate Equivalents  (auto-computed)",
            name          = "wp_end_display",
            datatype      = "GPString",
            parameterType = "Optional",
            direction     = "Input",
            category      = _CAT_E,
        )

        p_wp_speed_field = arcpy.Parameter(
            displayName   = "Speed Field  (km/h field name in Speed Surface)",
            name          = "wp_speed_field",
            datatype      = "GPString",
            parameterType = "Optional",
            direction     = "Input",
            category      = _CAT_E,
        )
        p_wp_speed_field.value = "SpeedKMH"

        # Parameter index reference:
        #  0  p_folder
        #  1  p_speed_fc
        #  2  p_moisture
        #  3  p_rm_run          (cat A)
        #  4  p_rm_mobility_field (cat A)
        #  5  p_iso_run         (cat B)
        #  6  p_iso_start       (cat B)
        #  7  p_iso_start_display (cat B) ← NEW
        #  8  p_iso_intervals   (cat B)
        #  9  p_iso_speed_field (cat B)
        # 10  p_vc_run          (cat C)
        # 11  p_vc_fc_b         (cat C)
        # 12  p_vc_name_a       (cat C)
        # 13  p_vc_name_b       (cat C)
        # 14  p_obs_run         (cat D)
        # 15  p_obs_contours    (cat D)
        # 16  p_obs_hydro       (cat D)
        # 17  p_wp_run          (cat E)
        # 18  p_wp_start        (cat E)
        # 19  p_wp_start_display (cat E) ← NEW
        # 20  p_wp_end          (cat E)
        # 21  p_wp_end_display  (cat E) ← NEW
        # 22  p_wp_speed_field  (cat E)

        return [
            p_folder,             # 0
            p_speed_fc,           # 1
            p_moisture,           # 2
            p_rm_run,             # 3
            p_rm_mobility_field,  # 4
            p_iso_run,            # 5
            p_iso_start,          # 6
            p_iso_start_display,  # 7
            p_iso_intervals,      # 8
            p_iso_speed_field,    # 9
            p_vc_run,             # 10
            p_vc_fc_b,            # 11
            p_vc_name_a,          # 12
            p_vc_name_b,          # 13
            p_obs_run,            # 14
            p_obs_contours,       # 15
            p_obs_hydro,          # 16
            p_wp_run,             # 17
            p_wp_start,           # 18
            p_wp_start_display,   # 19
            p_wp_end,             # 20
            p_wp_end_display,     # 21
            p_wp_speed_field,     # 22
        ]

    def isLicensed(self):
        return True

    # =========================================================================
    def updateParameters(self, parameters):
        p_folder            = parameters[0]
        p_speed_fc          = parameters[1]
        p_moisture          = parameters[2]
        p_iso_start         = parameters[6]
        p_iso_start_display = parameters[7]
        p_vc_fc_b           = parameters[11]
        p_vc_name_a         = parameters[12]
        p_vc_name_b         = parameters[13]
        p_obs_contours      = parameters[15]
        p_obs_hydro         = parameters[16]
        p_wp_start          = parameters[18]
        p_wp_start_display  = parameters[19]
        p_wp_end            = parameters[20]
        p_wp_end_display    = parameters[21]

        # ── Load config ───────────────────────────────────────────────────────
        cfg = {}
        project_gdb = ""
        if p_folder.value and _cfg_mod:
            try:
                cfg = _cfg_mod.load_config(p_folder.valueAsText)
                project_gdb = cfg.get("project_gdb") or ""
            except Exception:
                pass

        # ── Auto-fill Speed Surface A from last run ───────────────────────────
        if not p_speed_fc.altered:
            mob_fc = cfg.get("mobility_map_fc")
            if mob_fc and arcpy.Exists(mob_fc):
                p_speed_fc.value = mob_fc

        # ── Auto-fill moisture ────────────────────────────────────────────────
        if not p_moisture.altered or not p_moisture.value:
            p_moisture.value = cfg.get("moisture_default", "moist")

        # ── Populate Vehicle B dropdown from project GDB ──────────────────────
        if project_gdb and arcpy.Exists(project_gdb):
            speed_fcs = _list_speed_surfaces(project_gdb)
            if speed_fcs:
                p_vc_fc_b.filter.type = "ValueList"
                p_vc_fc_b.filter.list = speed_fcs

        # ── Auto-derive Vehicle A / B display names ───────────────────────────
        if p_speed_fc.value and not p_vc_name_a.altered:
            p_vc_name_a.value = _label_from_speed_fc(str(p_speed_fc.value))

        if p_vc_fc_b.value and not p_vc_name_b.altered:
            p_vc_name_b.value = _label_from_speed_fc(str(p_vc_fc_b.value))

        # ── Auto-fill Obstacle Detection inputs from config ───────────────────
        if not p_obs_contours.altered:
            contours_fc = cfg.get("contours_fc")
            if contours_fc and arcpy.Exists(contours_fc):
                p_obs_contours.value = contours_fc

        if not p_obs_hydro.altered:
            hydro_fcs = cfg.get("hydro_fcs") or []
            if isinstance(hydro_fcs, str):
                hydro_fcs = [hydro_fcs]
            for hfc in hydro_fcs:
                if hfc and arcpy.Exists(hfc):
                    p_obs_hydro.value = hfc
                    break

        # ── Coordinate display fields (all-format equivalents) ────────────────
        if _coords_mod:
            for p_coord, p_display in [
                (p_iso_start, p_iso_start_display),
                (p_wp_start,  p_wp_start_display),
                (p_wp_end,    p_wp_end_display),
            ]:
                raw = (p_coord.valueAsText or "").strip()
                if raw:
                    try:
                        lat, lon = _coords_mod.any_to_latlon(raw)
                        fmt = _coords_mod.detect_format(raw)
                        p_display.value = _coords_mod.format_coord_display(lat, lon, fmt)
                    except Exception as e:
                        p_display.value = f"(Cannot convert: {e})"
                else:
                    p_display.value = ""

    # =========================================================================
    def updateMessages(self, parameters):
        p_folder    = parameters[0]
        p_speed_fc  = parameters[1]
        p_iso_run   = parameters[5]
        p_iso_start = parameters[6]
        p_iso_ivls  = parameters[8]
        p_vc_run    = parameters[10]
        p_vc_fc_b   = parameters[11]
        p_wp_run    = parameters[17]
        p_wp_start  = parameters[18]
        p_wp_end    = parameters[20]

        # ── Coordinate format hints ───────────────────────────────────────────
        _COORD_FORMATS = (
            "Accepted coordinate formats:\n"
            "  • MGRS      — 18TVR1234567890\n"
            "  • DD        — 45.6466N 75.5957W  or  45.6466 -75.5957\n"
            "  • DMS       — 45°38'47\"N 75°35'44\"W\n"
            "  • DDM       — 45°38.783'N 75°35.740'W\n"
            "  • UTM       — 18T 448765 5057890"
        )
        if _coords_mod:
            for p_coord in (p_iso_start, p_wp_start, p_wp_end):
                raw = (p_coord.valueAsText or "").strip()
                if raw:
                    fmt = _coords_mod.detect_format(raw)
                    if fmt == "Unknown":
                        p_coord.setErrorMessage(
                            f"Cannot recognise coordinate: {raw!r}\n\n"
                            + _COORD_FORMATS
                        )

        # ── Project config check ──────────────────────────────────────────────
        if p_folder.value:
            cfg = {}
            if _cfg_mod:
                try:
                    cfg = _cfg_mod.load_config(p_folder.valueAsText)
                except Exception:
                    pass
            if not cfg:
                p_folder.setWarningMessage(
                    "No ccm_project.json found in this folder.\n\n"
                    "Complete Steps 1 and 2 first:\n"
                    "  Step 1 — Project Setup creates ccm_project.json and "
                    "pre-processes soil and vegetation layers.\n"
                    "  Step 2 — Generate Mobility Map creates the speed surface "
                    "that Step 3 analyses depend on.\n"
                    "Then select the same Project Folder here."
                )

        # ── Speed Surface check ───────────────────────────────────────────────
        _speed_fc_warnings = []
        if p_speed_fc.value and not p_speed_fc.hasError():
            fc = str(p_speed_fc.valueAsText)
            if arcpy.Exists(fc):
                # Check required output-contract fields are present
                try:
                    fld_names = {f.name for f in arcpy.ListFields(fc)}
                    required  = {"Mobility", "SpeedKMH", "F1_slope",
                                 "F2_vegetation", "F4_soil_dry"}
                    missing   = required - fld_names
                    if missing:
                        _speed_fc_warnings.append(
                            f"Speed Surface FC is missing expected fields: "
                            f"{', '.join(sorted(missing))}\n"
                            "This FC may not have been created by Step 2 — "
                            "some analyses (Reason Map, Vehicle Compare) may fail.\n"
                            "Re-run Step 2 to regenerate the speed surface."
                        )
                except Exception:
                    pass

            # v0.54.0 — smart CRS warning (see User Manual Section 3.4).
            # Speed Surface FC is normally auto-filled from Step 1's already-
            # validated Projected CRS, but a manual override could point at
            # anything.
            _sf_typ = _sf_name = _sf_code = None
            if _coords_mod:
                _sf_typ, _sf_name, _sf_code = \
                    _coords_mod.describe_spatial_reference(fc)
                if _sf_typ == "Geographic":
                    _speed_fc_warnings.append(
                        _coords_mod.geographic_crs_warning("Speed Surface FC", _sf_name)
                    )

            if _speed_fc_warnings:
                p_speed_fc.setWarningMessage("\n\n".join(_speed_fc_warnings))

            # Obstacle-detection layers (auto-filled from project config)
            # should match the Speed Surface CRS.
            if _coords_mod:
                p_obs_contours = parameters[15]
                p_obs_hydro    = parameters[16]
                for _p, _label in ((p_obs_contours, "Contour Lines FC"),
                                    (p_obs_hydro, "Hydro / Water Feature FC")):
                    _path = str(_p.valueAsText or "").strip()
                    if not _path or _p.hasError():
                        continue
                    _typ, _name, _code = _coords_mod.describe_spatial_reference(_path)
                    if _typ is None:
                        continue
                    if _typ == "Geographic":
                        _p.setWarningMessage(
                            _coords_mod.geographic_crs_warning(_label, _name))
                    elif _sf_code and _code and _code != _sf_code:
                        _p.setWarningMessage(
                            _coords_mod.crs_mismatch_warning(
                                _label, _name, "Speed Surface FC", _sf_name))

        # ── Isochrone checks ──────────────────────────────────────────────────
        if p_iso_run.value:
            if not (p_iso_start.valueAsText or "").strip():
                p_iso_start.setWarningMessage(
                    "Reachability Map requires a Start Point.\n\n"
                    + _COORD_FORMATS
                )
            if p_iso_ivls.value:
                try:
                    ivls = [float(x.strip()) for x in
                            str(p_iso_ivls.valueAsText).split(",") if x.strip()]
                    if not ivls:
                        raise ValueError
                    if any(i <= 0 for i in ivls):
                        p_iso_ivls.setErrorMessage(
                            "Time intervals must all be positive numbers (minutes)."
                        )
                    elif max(ivls) > 480:
                        p_iso_ivls.setWarningMessage(
                            f"Largest interval is {max(ivls):.0f} min — very long travel times "
                            "may produce large polygons and slow analysis."
                        )
                except Exception:
                    p_iso_ivls.setErrorMessage(
                        "Enter comma-separated minutes, e.g. 15,30,60,120"
                    )

        # ── Vehicle Compare checks ────────────────────────────────────────────
        if p_vc_run.value:
            if not (p_vc_fc_b.valueAsText or "").strip():
                p_vc_fc_b.setWarningMessage(
                    "Vehicle Comparison requires a Vehicle B speed surface.\n\n"
                    "How to populate this list:\n"
                    "  1. Run Step 2 with a second vehicle (different from the one "
                    "used for the Speed Surface FC above).\n"
                    "  2. Both surfaces must be in the same project GDB.\n"
                    "  3. Return here — Vehicle B will appear in the dropdown."
                )
            elif p_speed_fc.value:
                # Warn if A and B are the same FC
                fc_a = str(p_speed_fc.valueAsText or "").strip().lower()
                fc_b = str(p_vc_fc_b.valueAsText or "").strip().lower()
                if fc_a and fc_b and fc_a == fc_b:
                    p_vc_fc_b.setWarningMessage(
                        "Vehicle A and Vehicle B are the same speed surface — "
                        "the comparison output will be all zeros.  "
                        "Select a different vehicle for Vehicle B."
                    )

        # ── Waypoint Routing checks ───────────────────────────────────────────
        if p_wp_run.value:
            if not (p_wp_start.valueAsText or "").strip():
                p_wp_start.setWarningMessage(
                    "Waypoint Routing requires a Start Point (A).\n\n"
                    + _COORD_FORMATS
                )
            if not (p_wp_end.valueAsText or "").strip():
                p_wp_end.setWarningMessage(
                    "Waypoint Routing requires an End Point (B).\n\n"
                    + _COORD_FORMATS
                )
            # Warn if start == end
            if (_coords_mod
                    and (p_wp_start.valueAsText or "").strip()
                    and (p_wp_end.valueAsText or "").strip()):
                try:
                    ll_s = _coords_mod.any_to_latlon(p_wp_start.valueAsText.strip())
                    ll_e = _coords_mod.any_to_latlon(p_wp_end.valueAsText.strip())
                    import math as _math
                    dist = _math.hypot(ll_s[0] - ll_e[0], ll_s[1] - ll_e[1])
                    if dist < 1e-4:   # ~ <10 m
                        p_wp_end.setWarningMessage(
                            "Start Point and End Point appear to be the same location — "
                            "the route will have zero length."
                        )
                except Exception:
                    pass

    # =========================================================================
    def execute(self, parameters, messages):
        arcpy.SetLogMetadata(False)  # Prevent GDB history metadata accumulation (perf)

        p           = parameters
        folder_path = p[0].valueAsText
        speed_fc    = p[1].valueAsText
        moisture    = p[2].valueAsText

        run_rm   = bool(p[3].value)
        run_iso  = bool(p[5].value)
        run_vc   = bool(p[10].value)
        run_obs  = bool(p[14].value)
        run_wp   = bool(p[17].value)

        if not any([run_rm, run_iso, run_vc, run_obs, run_wp]):
            arcpy.AddWarning(
                "[Step 3] No analysis selected.  "
                "Enable at least one analysis in the category sections above."
            )
            return

        # ── Load project config ───────────────────────────────────────────────
        cfg = {}
        if _cfg_mod:
            cfg = _cfg_mod.load_config(folder_path)

        extent_fc   = cfg.get("extent_fc",   None)
        contours_fc = cfg.get("contours_fc", None)

        arcpy.AddMessage("[Step 3] ── Advanced Analysis ─────────────────────────")

        # Track all output FCs so we can load them into CCM_TOOL_BY_SON_MAP at the end.
        # Always include the speed surface itself as the base layer.
        _map_outputs = []
        if speed_fc and arcpy.Exists(speed_fc):
            _map_outputs.append(speed_fc)

        # ── A. Reason Map ─────────────────────────────────────────────────────
        if run_rm:
            if _CCMReasonMapTool is None:
                arcpy.AddWarning("[Step 3] Reason Map: ccm_reason_map.py not loaded.")
            else:
                arcpy.AddMessage("[Step 3] Running Reason Map...")
                mobility_field = p[4].valueAsText or "Mobility"
                try:
                    rm_tool = _CCMReasonMapTool()
                    rm_params = rm_tool.getParameterInfo()
                    rm_params[0].value = speed_fc
                    rm_params[1].value = mobility_field
                    rm_params[2].value = moisture
                    # NOTE: CCMReasonMapTool modifies the speed surface in-place and has
                    # no Output parameter — no output path assignment needed here.
                    rm_tool.execute(rm_params, messages)
                    arcpy.AddMessage(
                        "[Step 3] Reason Map complete — NO_GO_REASON and "
                        "RESTRICT_CODE fields added to the Speed Surface layer."
                    )
                    # Reason Map updates the speed surface in-place (no separate output FC).
                    # The speed surface is already tracked in _map_outputs.
                except Exception as exc:
                    arcpy.AddWarning(f"[Step 3] Reason Map failed: {exc}")

        # ── B. Reachability Map (Isochrone) ───────────────────────────────────
        # Initialise here so the variable always exists for the point-marker logic below,
        # regardless of whether run_iso is True or whether coordinate conversion succeeds.
        iso_latlon = None
        if run_iso:
            if _CCMIsochroneTool is None:
                arcpy.AddWarning("[Step 3] Reachability Map: ccm_isochrone.py not loaded.")
            elif not (p[6].valueAsText or "").strip():
                arcpy.AddWarning("[Step 3] Reachability Map: no Start Point — skipping.")
            else:
                arcpy.AddMessage("[Step 3] Running Reachability Map (Isochrone)...")
                speed_field   = p[9].valueAsText or "SpeedKMH"
                intervals_str = p[8].valueAsText or "15,30,60,120"
                try:
                    # Isochrone time bands are whole minutes — int keeps the
                    # band labels clean ("15-30 min", not "15.0-30.0 min").
                    intervals = [int(round(float(x.strip())))
                                 for x in intervals_str.split(",") if x.strip()]
                except Exception:
                    intervals = [15, 30, 60, 120]

                iso_raw = (p[6].valueAsText or "").strip()
                try:
                    iso_latlon = _coords_mod.any_to_latlon(iso_raw)
                    fmt = _coords_mod.detect_format(iso_raw)
                    arcpy.AddMessage(
                        f"[Step 3] Isochrone start [{fmt}]: {iso_raw} "
                        f"→ {iso_latlon[0]:.6f}°N  {iso_latlon[1]:.6f}°E"
                    )
                except Exception as _me:
                    arcpy.AddWarning(
                        f"[Step 3] Isochrone: cannot convert coordinate '{iso_raw}': {_me}"
                    )
                    iso_latlon = None

                if iso_latlon is None:
                    arcpy.AddWarning("[Step 3] Isochrone skipped — coordinate conversion failed.")
                else:
                    try:
                        iso_tool = _CCMIsochroneTool()
                        iso_params = iso_tool.getParameterInfo()
                        iso_params[0].value = speed_fc
                        iso_params[1].value = speed_field
                        # Use hemisphere-formatted DD string so ccm_coords
                        # detect_format() unambiguously recognises it as DD.
                        _iso_lat, _iso_lon = iso_latlon
                        iso_params[2].value = (
                            f"{abs(_iso_lat):.6f}{'N' if _iso_lat >= 0 else 'S'} "
                            f"{abs(_iso_lon):.6f}{'E' if _iso_lon >= 0 else 'W'}"
                        )
                        for ip in iso_params:
                            if "interval" in ip.name.lower() or "time" in ip.name.lower():
                                # ccm_isochrone uses semicolon-separated intervals
                                _semi = ";".join(str(int(float(x))) for x in intervals)
                                ip.value = _semi
                                break
                        out_iso = _derive_output_path(speed_fc, folder_path, "isochrone")
                        for ip in reversed(iso_params):
                            if ip.direction == "Output":
                                ip.value = out_iso
                                break
                        iso_tool.execute(iso_params, messages)
                        arcpy.AddMessage(f"[Step 3] Reachability Map complete → {out_iso}")
                        _map_outputs.append(out_iso)
                    except Exception as exc:
                        arcpy.AddWarning(f"[Step 3] Reachability Map failed: {exc}")

        # ── C. Vehicle Comparison ─────────────────────────────────────────────
        if run_vc:
            if _CCMVehicleCompareTool is None:
                arcpy.AddWarning("[Step 3] Vehicle Compare: ccm_vehicle_compare.py not loaded.")
            elif not (p[11].valueAsText or "").strip():
                arcpy.AddWarning("[Step 3] Vehicle Compare: no Vehicle B FC — skipping.")
            else:
                arcpy.AddMessage("[Step 3] Running Vehicle Comparison...")
                fc_b   = p[11].valueAsText
                name_a = p[12].valueAsText or "Vehicle A"
                name_b = p[13].valueAsText or "Vehicle B"
                try:
                    vc_tool = _CCMVehicleCompareTool()
                    vc_params = vc_tool.getParameterInfo()
                    vc_params[0].value = speed_fc
                    vc_params[1].value = name_a
                    vc_params[2].value = fc_b
                    vc_params[3].value = name_b
                    out_vc = _derive_output_path(speed_fc, folder_path, "vehicle_compare")
                    for vp in reversed(vc_params):
                        if vp.direction == "Output":
                            vp.value = out_vc
                            break
                    vc_tool.execute(vc_params, messages)
                    arcpy.AddMessage(f"[Step 3] Vehicle Comparison complete → {out_vc}")
                    _map_outputs.append(out_vc)
                except Exception as exc:
                    arcpy.AddWarning(f"[Step 3] Vehicle Comparison failed: {exc}")

        # ── D. Obstacle Detection ─────────────────────────────────────────────
        if run_obs:
            if _CCMObstacleDetectTool is None:
                arcpy.AddWarning("[Step 3] Obstacle Detection: ccm_obstacle_detect.py not loaded.")
            elif not extent_fc:
                arcpy.AddWarning("[Step 3] Obstacle Detection: extent_fc not in config — skipping.")
            else:
                arcpy.AddMessage("[Step 3] Running Obstacle Detection...")
                obs_contours = p[15].valueAsText or contours_fc
                obs_hydro    = p[16].valueAsText
                vehicle_csv  = cfg.get("vehicle_csv")
                try:
                    obs_tool = _CCMObstacleDetectTool()
                    obs_params = obs_tool.getParameterInfo()
                    obs_params[0].value = extent_fc
                    obs_params[1].value = obs_contours
                    obs_params[2].value = obs_hydro
                    obs_params[3].value = None
                    obs_params[4].value = vehicle_csv
                    out_obs = _derive_output_path(speed_fc, folder_path, "obstacles")
                    for op in reversed(obs_params):
                        if op.direction == "Output":
                            op.value = out_obs
                            break
                    obs_tool.execute(obs_params, messages)
                    arcpy.AddMessage(f"[Step 3] Obstacle Detection complete → {out_obs}")
                    _map_outputs.append(out_obs)
                except Exception as exc:
                    arcpy.AddWarning(f"[Step 3] Obstacle Detection failed: {exc}")

        # ── E. Waypoint Routing ───────────────────────────────────────────────
        # Initialise here so the variables always exist for the point-marker logic below.
        wp_start_latlon = None
        wp_end_latlon   = None
        if run_wp:
            if _CCMWaypointTool is None:
                arcpy.AddWarning("[Step 3] Waypoint Routing: ccm_waypoints.py not loaded.")
            elif not (p[18].valueAsText or "").strip() or not (p[20].valueAsText or "").strip():
                arcpy.AddWarning(
                    "[Step 3] Waypoint Routing: Start and End Points are required — skipping."
                )
            else:
                arcpy.AddMessage("[Step 3] Running Waypoint Routing...")
                speed_field_wp = p[22].valueAsText or "SpeedKMH"

                wp_start_latlon = wp_end_latlon = None
                for label, raw, is_start in [
                    ("Start (A)", (p[18].valueAsText or "").strip(), True),
                    ("End (B)",   (p[20].valueAsText or "").strip(), False),
                ]:
                    try:
                        ll  = _coords_mod.any_to_latlon(raw)
                        fmt = _coords_mod.detect_format(raw)
                        arcpy.AddMessage(
                            f"[Step 3] Waypoint {label} [{fmt}]: {raw} "
                            f"→ {ll[0]:.6f}°N  {ll[1]:.6f}°E"
                        )
                        if is_start:
                            wp_start_latlon = ll
                        else:
                            wp_end_latlon = ll
                    except Exception as _me:
                        arcpy.AddWarning(
                            f"[Step 3] Waypoint Routing: cannot convert '{raw}' "
                            f"({label}): {_me}"
                        )

                if wp_start_latlon is None or wp_end_latlon is None:
                    arcpy.AddWarning(
                        "[Step 3] Waypoint Routing skipped — coordinate conversion failed."
                    )
                else:
                    try:
                        wp_tool = _CCMWaypointTool()
                        wp_params = wp_tool.getParameterInfo()
                        wp_params[0].value = speed_fc
                        wp_params[1].value = speed_field_wp
                        # Hemisphere-formatted DD strings — unambiguous for detect_format()
                        def _fmt_dd(lat, lon):
                            return (
                                f"{abs(lat):.6f}{'N' if lat >= 0 else 'S'} "
                                f"{abs(lon):.6f}{'E' if lon >= 0 else 'W'}"
                            )
                        wp_params[2].value = _fmt_dd(*wp_start_latlon)
                        # [3] = start_display (skip), [4] = end_point
                        wp_params[4].value = _fmt_dd(*wp_end_latlon)
                        out_wp     = _derive_output_path(speed_fc, folder_path, "route")
                        out_wp_pts = _derive_output_path(speed_fc, folder_path, "route_points")
                        wp_params[9].value  = out_wp
                        wp_params[10].value = out_wp_pts
                        wp_tool.execute(wp_params, messages)
                        if arcpy.Exists(out_wp):
                            arcpy.AddMessage(f"[Step 3] Waypoint Routing complete → {out_wp}")
                            _map_outputs.append(out_wp)
                        else:
                            arcpy.AddWarning(
                                "[Step 3] Waypoint Routing produced no route output "
                                "(no passable path found) — nothing added to the map."
                            )
                    except Exception as exc:
                        arcpy.AddWarning(f"[Step 3] Waypoint Routing failed: {exc}")

        # ── Auto-load all outputs into CCM_TOOL_BY_SON_MAP (v0.51 — ccm_map_display) ──
        # One visual language, enforced by the shared display module:
        #   * speed surface = the ONLY filled layer (red reserved for No-Go)
        #   * isochrones    = hollow blue→purple rings
        #   * compare       = fills only where the two vehicles differ
        #   * obstacles     = red hatching
        #   * per-run group "CCM — <vehicle> (<moisture>)"; add order gives
        #     draw order points > route > obstacles > rings > compare > surface
        try:
            aprx = arcpy.mp.ArcGISProject("CURRENT")

            # ── Human-readable vehicle label ──────────────────────────────────
            _veh_label = (p[12].valueAsText or "").strip() or os.path.basename(speed_fc or "")

            # ── Derive GDB path for the start/end point feature classes ───────
            _gdb_for_pt = ""
            if speed_fc:
                _sp = speed_fc.replace("\\", "/")
                for _part in _sp.split("/"):
                    if _part.lower().endswith(".gdb"):
                        _gdb_for_pt = _sp[: _sp.lower().index(_part.lower()) + len(_part)]
                        break

            def _make_point_marker(fc_name, lat, lon, label, input_raw):
                """
                Create a single-point FC in the same projected CRS as the
                speed surface.  Building on arcpy.PointGeometry.projectAs()
                is the same method ccm_isochrone uses — it's guaranteed correct
                regardless of arcpy.env.outputCoordinateSystem.

                Attributes stored in the FC so the user can inspect values:
                  LABEL       — "Start" / "End"
                  COORD_INPUT — original coordinate string the user typed
                  LAT_DD      — decimal degrees latitude  (WGS84)
                  LON_DD      — decimal degrees longitude (WGS84)
                """
                out_fc = os.path.join(_gdb_for_pt, fc_name)
                if arcpy.Exists(out_fc):
                    arcpy.management.Delete(out_fc)

                # 1. Build an explicit WGS84 point geometry (X=lon, Y=lat)
                _sr_wgs84 = arcpy.SpatialReference(4326)
                _pt_wgs   = arcpy.PointGeometry(
                    arcpy.Point(float(lon), float(lat)), _sr_wgs84
                )

                # 2. Project to the speed surface CRS — same approach used by
                #    ccm_isochrone._snap_point_to_feature_class(), which is
                #    confirmed to place points correctly (the blue reference dots).
                #    This avoids any env.outputCoordinateSystem interference.
                try:
                    _sr_proj  = arcpy.Describe(speed_fc).spatialReference
                    _pt_final = _pt_wgs.projectAs(_sr_proj)
                except Exception as _prj_e:
                    arcpy.AddWarning(
                        f"[Step 3] Could not project {fc_name} to speed surface CRS "
                        f"({_prj_e}); using WGS84."
                    )
                    _sr_proj  = _sr_wgs84
                    _pt_final = _pt_wgs

                # 3. Create FC in the projected CRS
                arcpy.management.CreateFeatureclass(
                    _gdb_for_pt, fc_name, "POINT", spatial_reference=_sr_proj
                )
                arcpy.management.AddField(out_fc, "LABEL",       "TEXT",   field_length=50)
                arcpy.management.AddField(out_fc, "COORD_INPUT", "TEXT",   field_length=100)
                arcpy.management.AddField(out_fc, "LAT_DD",      "DOUBLE")
                arcpy.management.AddField(out_fc, "LON_DD",      "DOUBLE")

                # 4. Insert — geometry already in the correct projected CRS
                with arcpy.da.InsertCursor(
                    out_fc,
                    ["SHAPE@", "LABEL", "COORD_INPUT", "LAT_DD", "LON_DD"]
                ) as _ic:
                    _ic.insertRow((
                        _pt_final,
                        str(label),
                        str(input_raw),
                        float(lat),
                        float(lon),
                    ))

                arcpy.AddMessage(
                    f"[Step 3] {label} Point FC created: {fc_name}  |  "
                    f"lat={lat:.6f}  lon={lon:.6f}  input='{input_raw}'"
                )
                return out_fc

            # ── Resolve the best start lat/lon and raw input string ───────────
            _start_ll_for_map = None
            _start_input_raw  = ""
            if run_iso and iso_latlon is not None:
                _start_ll_for_map = iso_latlon
                _start_input_raw  = (p[6].valueAsText or "").strip()
            elif run_wp and wp_start_latlon is not None:
                _start_ll_for_map = wp_start_latlon
                _start_input_raw  = (p[18].valueAsText or "").strip()
            elif _coords_mod:
                for _raw_fb in [
                    (p[6].valueAsText or "").strip(),
                    (p[18].valueAsText or "").strip(),
                ]:
                    if _raw_fb:
                        try:
                            _start_ll_for_map = _coords_mod.any_to_latlon(_raw_fb)
                            _start_input_raw  = _raw_fb
                            break
                        except Exception:
                            pass

            if _display_mod is None:
                # ── Fallback: unstyled layers into the active map ─────────────
                arcpy.AddWarning(
                    "[Step 3] ccm_map_display.py not loaded — adding unstyled "
                    "layers to the active map."
                )
                _ccm_map = aprx.activeMap
                if _ccm_map is None:
                    _maps    = aprx.listMaps()
                    _ccm_map = _maps[0] if _maps else None
                if _ccm_map is not None:
                    for _fc in _map_outputs:
                        if _fc and arcpy.Exists(_fc):
                            try:
                                _ccm_map.addDataFromPath(_fc)
                            except Exception as _ae:
                                arcpy.AddWarning(
                                    f"[Step 3] Could not add "
                                    f"{os.path.basename(str(_fc))}: {_ae}"
                                )
            else:
                _ccm_map = _display_mod.get_ccm_map(aprx)
                _grp = _display_mod.ensure_group(
                    _ccm_map, f"CCM — {_veh_label} ({moisture or 'moist'})"
                )
                _already = _display_mod.existing_sources(_ccm_map)
                _lyrx_path = _display_mod.find_lyrx(
                    os.path.dirname(os.path.abspath(__file__))
                )

                _added = []
                # sort_for_draw_order: bottom→top so the LAST-added layer
                # (points/route) lands on top of the group.
                for _fc in _display_mod.sort_for_draw_order(_map_outputs):
                    _fc_norm = str(_fc).replace("\\", "/").lower()
                    if _fc_norm in _already or not arcpy.Exists(_fc):
                        continue
                    _new_lyr = _display_mod.add_layer(_ccm_map, _fc, group=_grp)
                    if _new_lyr is None:
                        continue
                    _already.add(_fc_norm)
                    _added.append(os.path.basename(str(_fc)))
                    _kind = _display_mod.kind_of(_fc)
                    try:
                        if _kind == "surface":
                            _display_mod.style_speed_surface(
                                _new_lyr, _fc, _veh_label, _lyrx_path)
                        elif _kind == "isochrone":
                            _display_mod.style_isochrone_rings(_new_lyr, _fc)
                        elif _kind == "compare":
                            _display_mod.style_compare(
                                _new_lyr,
                                (p[12].valueAsText or "Vehicle A").strip(),
                                (p[13].valueAsText or "Vehicle B").strip())
                        elif _kind == "obstacles":
                            _display_mod.style_obstacles(_new_lyr)
                        elif _kind == "route":
                            _display_mod.style_route(_new_lyr)
                    except Exception as _sym_e:
                        arcpy.AddWarning(
                            f"[Step 3] Symbology skipped for "
                            f"{os.path.basename(str(_fc))}: {_sym_e}"
                        )
                if _added:
                    arcpy.AddMessage(
                        f"[Step 3] Added to CCM_TOOL_BY_SON_MAP: {', '.join(_added)}"
                    )

                # ── Start / End point markers (added last → drawn on top) ─────
                if _start_ll_for_map and _gdb_for_pt:
                    try:
                        _pt_fc = _make_point_marker(
                            "start_point",
                            _start_ll_for_map[0], _start_ll_for_map[1],
                            "Start", _start_input_raw,
                        )
                        _pt_lyr = _display_mod.add_layer(_ccm_map, _pt_fc, group=_grp)
                        if _pt_lyr is not None:
                            _display_mod.style_point(_pt_lyr, "start")
                    except Exception as exc:
                        arcpy.AddWarning(
                            f"[Step 3] Could not add start point marker: {exc}"
                        )

                if run_wp and wp_end_latlon is not None and _gdb_for_pt:
                    try:
                        _pt_end_fc = _make_point_marker(
                            "end_point",
                            wp_end_latlon[0], wp_end_latlon[1],
                            "End", (p[19].valueAsText or "").strip(),
                        )
                        _pt_end_lyr = _display_mod.add_layer(
                            _ccm_map, _pt_end_fc, group=_grp)
                        if _pt_end_lyr is not None:
                            _display_mod.style_point(_pt_end_lyr, "end")
                    except Exception as exc:
                        arcpy.AddWarning(
                            f"[Step 3] Could not add end point marker: {exc}"
                        )

            # ── Save project ──────────────────────────────────────────────────
            try:
                aprx.save()
                arcpy.AddMessage("[Step 3] Project saved.")
            except Exception as save_exc:
                arcpy.AddWarning(f"[Step 3] Could not save project: {save_exc}")

        except Exception as exc:
            arcpy.AddWarning(
                f"[Step 3] Could not auto-load outputs into CCM_TOOL_BY_SON_MAP: {exc}"
            )


        arcpy.AddMessage("[Step 3] \u2500\u2500 Advanced Analysis Complete \u2500\u2500")

# <<< END OF FILE >>>
