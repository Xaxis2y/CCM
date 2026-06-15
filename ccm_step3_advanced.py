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
# VERSION = "0.46"
VERSION = "0.46"
# v0.46 — Version bump aligned with toolbox-wide v0.46 release.
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

        _COORD_HINT = (
            "Any coordinate format: MGRS (18TVR1234567890), "
            "DD (37.1234N 127.5678E), "
            "DMS (37°07'24\"N 127°34'04\"E), "
            "DDM (37°07.408'N 127°34.068'E), "
            "or UTM (52S 612345 4112345)"
        )

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
        p_vc_run    = parameters[10]
        p_vc_fc_b   = parameters[11]
        p_wp_run    = parameters[17]
        p_wp_start  = parameters[18]
        p_wp_end    = parameters[20]

        # ── Validate coordinate inputs ────────────────────────────────────────
        if _coords_mod:
            for p_coord in (p_iso_start, p_wp_start, p_wp_end):
                raw = (p_coord.valueAsText or "").strip()
                if raw:
                    fmt = _coords_mod.detect_format(raw)
                    if fmt == "Unknown":
                        p_coord.setErrorMessage(
                            f"Cannot recognise coordinate format: {raw!r}\n"
                            "Accepted: MGRS, DD, DMS (deg min sec), DDM, UTM"
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
                    "No ccm_project.json found.  Run Steps 1 & 2 first."
                )

        # ── Isochrone needs start point ───────────────────────────────────────
        if p_iso_run.value and not (p_iso_start.valueAsText or "").strip():
            p_iso_start.setWarningMessage(
                "Reachability Map requires a Start Point coordinate."
            )

        # ── Vehicle Compare needs Vehicle B ───────────────────────────────────
        if p_vc_run.value and not (p_vc_fc_b.valueAsText or "").strip():
            p_vc_fc_b.setWarningMessage(
                "Vehicle Comparison requires a Vehicle B speed surface.  "
                "Run Step 2 with a second vehicle to populate the dropdown."
            )

        # ── Waypoints need start and end ──────────────────────────────────────
        if p_wp_run.value:
            if not (p_wp_start.valueAsText or "").strip():
                p_wp_start.setWarningMessage(
                    "Waypoint Routing requires a Start Point coordinate."
                )
            if not (p_wp_end.valueAsText or "").strip():
                p_wp_end.setWarningMessage(
                    "Waypoint Routing requires an End Point coordinate."
                )

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

        # Track all output FCs so we can load them into MCE_CCM_MAP at the end.
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
                        f"[Step 3] Reason Map complete — NO_GO_REASON and "
                        f"RESTRICT_CODE fields added to the Speed Surface layer."
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
                    intervals = [float(x.strip()) for x in intervals_str.split(",")
                                 if x.strip()]
                except Exception:
                    intervals = [15.0, 30.0, 60.0, 120.0]

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
                        arcpy.AddMessage(f"[Step 3] Waypoint Routing complete → {out_wp}")
                        _map_outputs.append(out_wp)
                    except Exception as exc:
                        arcpy.AddWarning(f"[Step 3] Waypoint Routing failed: {exc}")

        # ── Auto-load all outputs into MCE_CCM_MAP ────────────────────────────
        try:
            aprx = arcpy.mp.ArcGISProject("CURRENT")

            # ── Create or reuse MCE_CCM_MAP ───────────────────────────────────
            _existing = [m for m in aprx.listMaps() if m.name == "MCE_CCM_MAP"]
            if _existing:
                _ccm_map = _existing[0]
                arcpy.AddMessage("[Step 3] Found existing map: MCE_CCM_MAP")
            else:
                _ccm_map = aprx.createMap("MCE_CCM_MAP", "MAP")
                arcpy.AddMessage("[Step 3] Created new map: MCE_CCM_MAP")
                # Satellite imagery basemap — matches military/tactical look
                try:
                    _ccm_map.addBasemap("Imagery")
                    arcpy.AddMessage("[Step 3] Basemap: Satellite Imagery added.")
                except Exception as _bm_e:
                    arcpy.AddWarning(f"[Step 3] Basemap not added: {_bm_e}")

            # ── Locate CCM symbology lyrx ─────────────────────────────────────
            _tool_dir = os.path.dirname(os.path.abspath(__file__))
            _lyrx_path = None
            for _ln in ["Mobility_Symbology_Final.lyrx", "Mobility_Symbology.lyrx"]:
                _c = os.path.join(_tool_dir, "Symbology", _ln)
                if os.path.exists(_c):
                    _lyrx_path = _c
                    break

            # ── Derive GDB path for the start/end point feature classes ───────
            _gdb_for_pt = ""
            if speed_fc:
                _sp = speed_fc.replace("\\", "/")
                for _part in _sp.split("/"):
                    if _part.lower().endswith(".gdb"):
                        _gdb_for_pt = _sp[: _sp.lower().index(_part.lower()) + len(_part)]
                        break

            # ── Human-readable vehicle label ──────────────────────────────────
            _veh_label = (p[12].valueAsText or "").strip() or os.path.basename(speed_fc or "")

            # ── Collect existing datasources to prevent duplicates ────────────
            _already = set()
            for _lyr in _ccm_map.listLayers():
                try:
                    if hasattr(_lyr, "dataSource"):
                        _already.add(_lyr.dataSource.replace("\\", "/").lower())
                except Exception:
                    pass

            # ── Helper: check if a field exists and has non-null values ───────
            def _field_has_data(fc, field_name):
                try:
                    fields = [f.name for f in arcpy.ListFields(fc)]
                    if field_name not in fields:
                        return False
                    with arcpy.da.SearchCursor(fc, [field_name]) as _sc:
                        for _r in _sc:
                            if _r[0] is not None and _r[0] not in ("Unknown", -1):
                                return True
                    return False
                except Exception:
                    return False

            # ── Add each output layer with symbology ──────────────────────────
            _added = []
            for _fc in _map_outputs:
                if not _fc:
                    continue
                _fc_norm = str(_fc).replace("\\", "/").lower()
                if _fc_norm not in _already and arcpy.Exists(_fc):
                    try:
                        _ccm_map.addDataFromPath(_fc)
                        _added.append(os.path.basename(_fc))
                        _already.add(_fc_norm)

                        _new_lyr  = _ccm_map.listLayers()[0]
                        _fc_base  = os.path.basename(str(_fc)).lower()

                        # No per-feature auto-labels on polygons (clutters the map)
                        try:
                            _new_lyr.showLabels = False
                        except Exception:
                            pass

                        try:
                            # ── Speed Surface ──────────────────────────────────
                            if "speed_surface" in _fc_base:
                                _new_lyr.name         = f"Speed Surface — {_veh_label}"
                                _new_lyr.transparency = 55   # high transparency — satellite dominates

                                # UniqueValueRenderer on Condition_Number field
                                # CCM Condition Numbers: 1=No-Go → 5=Go (red→green)
                                _cond_colours = {
                                    "1": [139,  0,   0, 240],   # No-Go      — dark red
                                    "2": [220,  50,  20, 225],  # Poor       — red-orange
                                    "3": [255, 160,   0, 210],  # Marginal   — amber/orange
                                    "4": [180, 210,  40, 195],  # Fair       — yellow-green
                                    "5": [0,   160,  50, 180],  # Go         — green
                                    "default": [160, 160, 160, 150],
                                }
                                # Field may be stored as "Condition_Number" (GDB no-space convention)
                                _sp_field = "Condition_Number"
                                try:
                                    _fld_names = [f.name for f in arcpy.ListFields(_fc)]
                                    # Try common variants if exact name not found
                                    for _candidate in ["Condition_Number", "ConditionNumber",
                                                       "Condition Number", "CONDITION_NUMBER",
                                                       "cond_num", "CondNum"]:
                                        if _candidate in _fld_names:
                                            _sp_field = _candidate
                                            break
                                except Exception:
                                    pass

                                try:
                                    _sp_sym = _new_lyr.symbology
                                    _sp_sym.updateRenderer("UniqueValueRenderer")
                                    _sp_sym.renderer.fields = [_sp_field]
                                    _new_lyr.symbology = _sp_sym
                                    # Apply per-class colours
                                    _sp_sym2 = _new_lyr.symbology
                                    for _grp in _sp_sym2.renderer.groups:
                                        for _cls in (getattr(_grp, 'classes', None) or getattr(_grp, 'items', [])):
                                            _key = str(_cls.label).strip()
                                            _rgba = _cond_colours.get(_key, _cond_colours["default"])
                                            _cls.symbol.color        = {"RGB": _rgba[:3] + [_rgba[3]]}
                                            _cls.symbol.outlineColor = {"RGB": [0, 0, 0, 0]}  # no outline
                                    _new_lyr.symbology = _sp_sym2
                                    arcpy.AddMessage(f"[Step 3] Speed Surface: UniqueValues on '{_sp_field}' applied.")
                                except Exception as _sp_e:
                                    arcpy.AddWarning(f"[Step 3] Speed Surface symbology skipped: {_sp_e}")
                                    if _lyrx_path:
                                        try:
                                            arcpy.management.ApplySymbologyFromLayer(
                                                _new_lyr, _lyrx_path, None, "MAINTAIN"
                                            )
                                        except Exception:
                                            pass

                            # ── Reachability / Isochrone ───────────────────────
                            elif "isochrone" in _fc_base:
                                _new_lyr.name         = "Reachability Zones (15 / 30 / 60 / 120 min)"
                                _new_lyr.transparency = 30

                                # Warm orange/yellow palette matching tactical map style
                                # Map each time band keyword → fill colour (RGB)
                                _iso_colours = {
                                    "15":  [255, 238, 88,  230],   # bright yellow  (innermost)
                                    "30":  [255, 179, 0,   230],   # amber
                                    "60":  [255, 109, 0,   230],   # deep orange
                                    "1 hr":[255, 109, 0,   230],   # deep orange (alt label)
                                    "120": [204, 51,  0,   230],   # burnt orange-red
                                    "2 hr":[204, 51,  0,   230],   # burnt orange-red (alt label)
                                    "240": [139, 0,   0,   230],   # dark red (>2hr)
                                    "default": [180, 80, 0, 200],  # fallback
                                }

                                # Use TIME_BAND text field if populated; fall back to gridcode
                                _use_field = "TIME_BAND" if _field_has_data(_fc, "TIME_BAND") else "gridcode"
                                arcpy.AddMessage(f"[Step 3] Isochrone symbology field: {_use_field}")

                                # Step 1 — apply unique value renderer to populate class list
                                _iso_sym = _new_lyr.symbology
                                _iso_sym.updateRenderer("UniqueValueRenderer")
                                _iso_sym.renderer.fields = [_use_field]
                                _new_lyr.symbology = _iso_sym

                                # Step 2 — re-read and set per-class colours + white outline
                                try:
                                    _iso_sym2 = _new_lyr.symbology
                                    for _grp in _iso_sym2.renderer.groups:
                                        for _cls in (getattr(_grp, 'classes', None) or getattr(_grp, 'items', [])):
                                            _lbl = str(_cls.label)
                                            _rgba = _iso_colours["default"]
                                            for _key, _col in _iso_colours.items():
                                                if _key != "default" and _key in _lbl:
                                                    _rgba = _col
                                                    break
                                            _cls.symbol.color        = {"RGB": _rgba[:3] + [_rgba[3]]}
                                            _cls.symbol.outlineColor = {"RGB": [255, 255, 255, 200]}
                                            _cls.symbol.outlineWidth = 0.5
                                    _new_lyr.symbology = _iso_sym2
                                    arcpy.AddMessage("[Step 3] Isochrone: warm orange/yellow palette applied.")
                                except Exception as _col_e:
                                    arcpy.AddWarning(f"[Step 3] Isochrone colour assignment skipped: {_col_e}")

                                # Step 3 — enable time-band labels on rings
                                try:
                                    _new_lyr.showLabels = True
                                    _lc = _new_lyr.listLabelClasses()
                                    if _lc:
                                        _lc[0].expression = f"$feature.{_use_field}"
                                        _lc[0].SQLQuery   = ""
                                    arcpy.AddMessage("[Step 3] Isochrone time labels enabled.")
                                except Exception as _lbl_e:
                                    arcpy.AddWarning(f"[Step 3] Isochrone labels skipped: {_lbl_e}")

                            # ── Obstacle Areas ─────────────────────────────────
                            elif "obstacle" in _fc_base:
                                _new_lyr.name         = "Obstacle Areas"
                                _new_lyr.transparency = 10
                                _obs_sym = _new_lyr.symbology
                                if hasattr(_obs_sym, "renderer") and hasattr(_obs_sym.renderer, "symbol"):
                                    _obs_sym.renderer.symbol.color        = {"RGB": [180, 0, 0, 255]}
                                    _obs_sym.renderer.symbol.outlineColor = {"RGB": [255, 50, 50, 255]}
                                    _obs_sym.renderer.symbol.outlineWidth = 1.5
                                    _new_lyr.symbology = _obs_sym

                            # ── Vehicle Comparison ─────────────────────────────
                            elif "vehicle_compare" in _fc_base or "compare" in _fc_base:
                                _new_lyr.name         = "Vehicle Comparison"
                                _new_lyr.transparency = 25

                            # ── Waypoint / Optimal Route — glowing magenta line ─
                            elif "route" in _fc_base or "waypoint" in _fc_base:
                                _new_lyr.name = "Optimal Route"
                                # Use CIM to build a 2-layer glow symbol:
                                # Layer 0 — thick white halo
                                # Layer 1 — thin bright magenta on top
                                try:
                                    import json as _json
                                    _lyr_cim = _new_lyr.getDefinition("V3")
                                    _glow_sym = {
                                        "type": "CIMLineSymbol",
                                        "symbolLayers": [
                                            {   # white halo (drawn first = bottom)
                                                "type": "CIMSolidStroke",
                                                "enable": True,
                                                "width": 6,
                                                "color": {
                                                    "type": "CIMRGBColor",
                                                    "values": [255, 255, 255, 220]
                                                }
                                            },
                                            {   # magenta line on top
                                                "type": "CIMSolidStroke",
                                                "enable": True,
                                                "width": 2.5,
                                                "color": {
                                                    "type": "CIMRGBColor",
                                                    "values": [255, 0, 200, 255]
                                                }
                                            }
                                        ]
                                    }
                                    _lyr_cim.renderer.symbol.symbol = _glow_sym
                                    _new_lyr.setDefinition(_lyr_cim)
                                    arcpy.AddMessage("[Step 3] Route: magenta glow line applied.")
                                except Exception as _rt_cim_e:
                                    # Fallback — simple thick magenta line
                                    arcpy.AddWarning(f"[Step 3] Route glow fallback: {_rt_cim_e}")
                                    _rt_sym = _new_lyr.symbology
                                    if hasattr(_rt_sym, "renderer") and hasattr(_rt_sym.renderer, "symbol"):
                                        _rt_sym.renderer.symbol.color = {"RGB": [255, 0, 200, 255]}
                                        _rt_sym.renderer.symbol.size  = 3
                                        _new_lyr.symbology = _rt_sym

                        except Exception as _sym_e:
                            arcpy.AddWarning(f"[Step 3] Symbology skipped for {_fc_base}: {_sym_e}")

                    except Exception as _ae:
                        arcpy.AddWarning(
                            f"[Step 3] Could not add {os.path.basename(_fc)} to MCE_CCM_MAP: {_ae}"
                        )

            # ── Point marker helper ───────────────────────────────────────────
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

            # ── Add start point marker ────────────────────────────────────────
            # Resolve the best start lat/lon and the raw user input string.
            _start_ll_for_map  = None
            _start_input_raw   = ""
            # iso_latlon and wp_start_latlon are initialised to None inside their
            # respective `if run_iso:` / `if run_wp:` blocks above; use `is not None`
            # rather than `in dir()` which is fragile and implementation-dependent.
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

            if _start_ll_for_map and _gdb_for_pt:
                try:
                    _pt_fc = _make_point_marker(
                        "start_point",
                        _start_ll_for_map[0], _start_ll_for_map[1],
                        "Start", _start_input_raw,
                    )
                    _ccm_map.addDataFromPath(_pt_fc)
                    _pt_lyr            = _ccm_map.listLayers("start_point")[0]
                    _pt_lyr.name       = "★ Start Point"
                    _pt_lyr.showLabels = False
                    _pt_sym = _pt_lyr.symbology
                    if hasattr(_pt_sym, "renderer") and hasattr(_pt_sym.renderer, "symbol"):
                        try:
                            _pt_sym.renderer.symbol.applySymbolFromGallery("Circle 1")
                        except Exception:
                            pass
                        _pt_sym.renderer.symbol.color        = {"RGB": [255, 215, 0, 255]}
                        _pt_sym.renderer.symbol.outlineColor = {"RGB": [30,  30,  30, 255]}
                        _pt_sym.renderer.symbol.size         = 22
                        _pt_lyr.symbology = _pt_sym
                except Exception as _pt_e:
                    arcpy.AddWarning(f"[Step 3] Start point marker skipped: {_pt_e}")

            # ── Add end point marker ──────────────────────────────────────────
            # Shown whenever a value is entered — no need to run Waypoint Route.
            _wp_end_raw = (p[20].valueAsText or "").strip()
            if _wp_end_raw and _gdb_for_pt and _coords_mod:
                try:
                    _wp_end_ll = _coords_mod.any_to_latlon(_wp_end_raw)
                    if _wp_end_ll:
                        _ep_fc = _make_point_marker(
                            "end_point",
                            _wp_end_ll[0], _wp_end_ll[1],
                            "End", _wp_end_raw,
                        )
                        _ccm_map.addDataFromPath(_ep_fc)
                        _ep_lyr            = _ccm_map.listLayers("end_point")[0]
                        _ep_lyr.name       = "⬛ End Point"
                        _ep_lyr.showLabels = False
                        _ep_sym = _ep_lyr.symbology
                        if hasattr(_ep_sym, "renderer") and hasattr(_ep_sym.renderer, "symbol"):
                            try:
                                _ep_sym.renderer.symbol.applySymbolFromGallery("Circle 1")
                            except Exception:
                                pass
                            _ep_sym.renderer.symbol.color        = {"RGB": [255, 80, 0, 255]}
                            _ep_sym.renderer.symbol.outlineColor = {"RGB": [30, 30, 30, 255]}
                            _ep_sym.renderer.symbol.size         = 22
                            _ep_lyr.symbology = _ep_sym
                except Exception as _ep_e:
                    arcpy.AddWarning(f"[Step 3] End point marker skipped: {_ep_e}")

            if _added:
                arcpy.AddMessage(
                    f"[Step 3] Layers added to MCE_CCM_MAP: {', '.join(_added)}"
                )
            else:
                arcpy.AddMessage(
                    "[Step 3] MCE_CCM_MAP already contains all output layers."
                )
            arcpy.AddMessage(
                "[Step 3] MCE_CCM_MAP is ready — double-click it in the Contents panel to open."
            )

        except Exception as _map_exc:
            arcpy.AddWarning(
                f"[Step 3] Could not auto-load outputs into MCE_CCM_MAP: {_map_exc}"
            )

        arcpy.AddMessage("=" * 60)
        arcpy.AddMessage("  Step 3 complete.  Open MCE_CCM_MAP to see all results.")
        arcpy.AddMessage("=" * 60)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _list_speed_surfaces(project_gdb):
    """Return full paths to all speed_surface_* FCs inside *project_gdb*."""
    if not project_gdb or not arcpy.Exists(project_gdb):
        return []
    old_ws = arcpy.env.workspace
    try:
        arcpy.env.workspace = project_gdb
        fcs = arcpy.ListFeatureClasses("speed_surface_*") or []
        return [os.path.join(project_gdb, fc) for fc in sorted(fcs)]
    except Exception:
        return []
    finally:
        arcpy.env.workspace = old_ws


def _label_from_speed_fc(fc_path):
    """
    Derive a readable label from a speed surface FC path.
    speed_surface_T62_T72_moist  →  T62 / T72 (moist)
    speed_surface_M151_dry       →  M151 (dry)
    """
    name = os.path.basename(fc_path)
    if name.lower().startswith("speed_surface_"):
        rest = name[len("speed_surface_"):]
        for moisture in ("dry", "moist", "wet"):
            if rest.endswith("_" + moisture):
                vehicles = rest[: -(len(moisture) + 1)].replace("_", " / ")
                return f"{vehicles} ({moisture})"
        return rest.replace("_", " / ")
    return name


def _derive_output_path(speed_fc_path, project_folder, suffix):
    """
    Derive an output FC path.
    If the speed surface is inside a .gdb, place the output there.
    Otherwise, fall back to <project_folder>/CCM_Project.gdb.
    """
    if not speed_fc_path:
        speed_fc_path = ""

    parts = speed_fc_path.replace("\\", "/").split("/")
    for i, part in enumerate(parts):
        if part.lower().endswith(".gdb"):
            gdb = "/".join(parts[: i + 1])
            return os.path.join(gdb, suffix)

    gdb = os.path.join(project_folder, "CCM_Project.gdb")
    if not arcpy.Exists(gdb):
        try:
            arcpy.management.CreateFileGDB(project_folder, "CCM_Project.gdb")
        except Exception as e:
            arcpy.AddWarning(f"Could not create GDB: {e}")
    return gdb

# <<< END OF FILE >>>
