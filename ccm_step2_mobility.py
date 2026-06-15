# -*- coding: utf-8 -*-
# ccm_step2_mobility.py
# CCM Step 2 — Mobility Map (Speed Surface) Engine
#
# This is the CORE Multi-Criteria Evaluation (MCE) engine of the toolbox.
# It consumes the pre-processed layers registered in ccm_project.json by
# Step 1 and produces a "speed surface" polygon feature class that every
# downstream tool (Reason Map, Isochrone, Waypoint Route, Vehicle Compare,
# Obstacle Detect) depends on.
#
# VERSION = "0.46"
VERSION = "0.46"
# v0.46 — Calibration & weather integration:
#          1. RCI table externalized: soil_rci.csv (next to this module) is
#             loaded at import; the built-in USCS_RCI values serve as fallback.
#             Analysts calibrate trafficability without touching code.
#          2. Live weather wired in: Step 2 can fetch current rainfall for the
#             AOI centroid (ccm_weather: METAR primary / Open-Meteo fallback)
#             and apply adjust_rci_for_rainfall() to the RCI table before the
#             F4/F5 soil factors are computed.  Includes USCS→sensitivity-key
#             mapping and a manual rainfall override parameter.
# v0.46 — Rebuilt the previously-missing Step 2 mobility engine from the
#          output contract required by the downstream Step 3 tools:
#            * Speed surface FC fields:
#                Mobility        TEXT  ("GO" / "RESTRICTED" / "NO GO")
#                SpeedKMH        FLOAT (predicted cross-country speed)
#                F1_slope        DOUBLE (0..1 slope factor)
#                F2_vegetation   DOUBLE (0..1 vegetation-density factor)
#                F3_veg_spacing  DOUBLE (0..1 manoeuvre/override factor)
#                F4_soil_dry     DOUBLE (0..1 soil factor, dry assumption)
#                F5_soil_wet     DOUBLE (0..1 soil factor, wet assumption)
#                F_hydro         DOUBLE (0..1 water-crossing factor)
#            * Writes mobility_map_fc + last_vehicles back to ccm_project.json
#              so Step 3 auto-fills.
#          The trafficability mathematics are isolated in pure-Python helper
#          functions (no arcpy import needed) so they are unit-testable and so
#          the original NRMM/VCI curves can be substituted without touching the
#          geoprocessing wrapper.

import os
import sys
import csv

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# arcpy is only needed for the toolbox wrapper / geoprocessing.  The pure-Python
# trafficability functions below import nothing from arcpy so they can be tested
# in a plain Python environment.
try:
    import arcpy
    _HAVE_ARCPY = True
except Exception:
    arcpy = None
    _HAVE_ARCPY = False

_cfg_mod = None
try:
    import ccm_project_config as _cfg_mod
except Exception as e:
    if _HAVE_ARCPY:
        arcpy.AddWarning(f"[Step 2] ccm_project_config: {e}")

_weather_mod = None
try:
    import ccm_weather as _weather_mod
except Exception as e:
    if _HAVE_ARCPY:
        arcpy.AddWarning(f"[Step 2] ccm_weather not loaded (live weather disabled): {e}")


# =============================================================================
# SECTION 1 — OUTPUT FIELD CONTRACT
# =============================================================================
# These names are consumed verbatim by the downstream Step 3 tools and the
# Mobility_Symbology_Final.lyrx layer file.  Do NOT rename without updating
# ccm_reason_map.py, ccm_isochrone.py, ccm_waypoints.py, ccm_vehicle_compare.py
# and the symbology .lyrx.
FIELD_MOBILITY = "Mobility"
FIELD_SPEED    = "SpeedKMH"
FIELD_F1       = "F1_slope"
FIELD_F2       = "F2_vegetation"
FIELD_F3       = "F3_veg_spacing"
FIELD_F4       = "F4_soil_dry"
FIELD_F5       = "F5_soil_wet"
FIELD_FHYDRO   = "F_hydro"

# Mobility class labels (must match the symbology .lyrx value list)
MOB_GO         = "GO"
MOB_RESTRICTED = "RESTRICTED"
MOB_NOGO       = "NO GO"

# A feature is NO GO below this fraction of max road speed; RESTRICTED between
# this and the GO threshold.
DEFAULT_GO_THRESHOLD_KMH        = 5.0
DEFAULT_RESTRICTED_FRACTION     = 0.50   # >=50% of max speed = full GO


# =============================================================================
# SECTION 2 — SOIL STRENGTH (RCI) REFERENCE TABLE
# =============================================================================
# Rating Cone Index (RCI) by USCS two-letter code, as a (dry, moist, wet)
# tuple.  Values are nominal trafficability cone-index figures drawn from the
# standard USCS → soil-strength relationship used in cross-country mobility
# modelling; a vehicle can traverse the soil when RCI >= the vehicle's Vehicle
# Cone Index (VCI).
#
# v0.46: the operational table is loaded from soil_rci.csv (same folder as
# this module) so analysts can calibrate against FM 5-430-00-1 / NRMM data
# without code changes.  The built-in values below are the fallback when the
# CSV is absent or unreadable.
#
# Keyed by the USCS codes that ccm_soil_preprocess.py emits into the 'soilType'
# field.  'NE' = Not Evaluated, 'Pt' = peat, 'RK' = rock.
_BUILTIN_USCS_RCI = {
    # code : (dry, moist, wet)
    "GW": (300, 280, 250),   # well-graded gravel — very strong
    "GP": (290, 270, 240),
    "GM": (260, 220, 170),
    "GC": (240, 190, 140),
    "SW": (250, 220, 180),   # well-graded sand
    "SP": (230, 200, 160),
    "SM": (200, 150, 100),
    "SC": (180, 130, 85),
    "ML": (150, 95, 55),     # silt
    "CL": (160, 100, 60),    # lean clay
    "OL": (120, 75, 45),
    "MH": (130, 80, 45),
    "CH": (140, 85, 45),     # fat clay — weak when wet
    "OH": (100, 60, 35),
    "Pt": (70, 45, 25),      # peat — weakest
    "RK": (400, 400, 400),   # rock — effectively unlimited bearing
    "NE": (None, None, None),  # not evaluated — unknown
}

RCI_CSV_NAME = "soil_rci.csv"


def load_rci_csv(csv_path=None):
    """
    Load the calibratable RCI table from soil_rci.csv.

    Expected columns: uscs_code, rci_dry, rci_moist, rci_wet  (description
    optional).  Blank RCI cells become None (= not evaluated).

    Returns a dict {code: (dry, moist, wet)}.  Raises on a malformed file so
    the caller can decide to fall back to the built-ins.
    """
    if csv_path is None:
        csv_path = os.path.join(_HERE, RCI_CSV_NAME)
    table = {}
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            low = {str(k).strip().lower(): v for k, v in row.items() if k}
            code = (low.get("uscs_code") or "").strip()
            if not code:
                continue
            table[code] = (
                _to_float(low.get("rci_dry")),
                _to_float(low.get("rci_moist")),
                _to_float(low.get("rci_wet")),
            )
    if not table:
        raise ValueError(f"No RCI rows parsed from {csv_path}")
    return table


def _init_rci_table():
    """soil_rci.csv if present and valid, else the built-in defaults."""
    path = os.path.join(_HERE, RCI_CSV_NAME)
    if os.path.isfile(path):
        try:
            table = load_rci_csv(path)
            # Ensure every built-in code is at least present (CSV may extend)
            for code, vals in _BUILTIN_USCS_RCI.items():
                table.setdefault(code, vals)
            return table
        except Exception as exc:
            if _HAVE_ARCPY:
                arcpy.AddWarning(
                    f"[Step 2] soil_rci.csv unreadable ({exc}) — using built-in RCI values."
                )
    return dict(_BUILTIN_USCS_RCI)


USCS_RCI = _init_rci_table()

# Mapping from "moisture condition" string → tuple index in USCS_RCI values.
_MOISTURE_INDEX = {"dry": 0, "moist": 1, "wet": 2}


# =============================================================================
# SECTION 2b — WEATHER (RAINFALL → RCI) INTEGRATION
# =============================================================================
# ccm_weather.SOIL_SENSITIVITY is keyed by descriptive names; Step 2 works in
# USCS codes.  This mapping bridges the two so adjust_rci_for_rainfall() can
# scale the USCS-keyed RCI table.
USCS_TO_SENSITIVITY_KEY = {
    "GW": "wellGradedGravel",
    "GP": "poorlyGradedGravel",
    "GM": "siltyGravelSand",
    "GC": "clayeyGravel",
    "SW": "wellGradedSand",
    "SP": "poorlyGradedSand",
    "SM": "siltySand",
    "SC": "clayeySand",
    "ML": "siltAndFineSand",
    "CL": "leanClay",
    "OL": "organicSiltandClay",
    "MH": "micaceous",
    "CH": "fatClay",
    "OH": "organicClay",
    "Pt": "peat",
    "RK": "rock",
    "NE": "notEvaluated",
}


def apply_weather_to_rci(rci_table, rainfall_mm, manual_override=None):
    """
    Return a copy of *rci_table* with rainfall penalties applied.

    Re-keys the USCS table to ccm_weather's sensitivity names, delegates to
    ccm_weather.adjust_rci_for_rainfall(), and maps the result back to USCS
    codes.  If ccm_weather is unavailable the table is returned unchanged.

    Parameters
    ----------
    rci_table : dict {uscs_code: (dry, moist, wet)}
    rainfall_mm : float — current rainfall in mm/hr (0.0 = no rain)
    manual_override : float, optional — 0.0–1.0 factor that overrides the
        calculated penalty (commander's local knowledge).
    """
    if _weather_mod is None:
        return dict(rci_table)
    keyed = {
        USCS_TO_SENSITIVITY_KEY.get(code, code): vals
        for code, vals in rci_table.items()
    }
    adjusted = _weather_mod.adjust_rci_for_rainfall(
        keyed, rainfall_mm, manual_override=manual_override
    )
    back = {v: k for k, v in USCS_TO_SENSITIVITY_KEY.items()}
    return {back.get(k, k): v for k, v in adjusted.items()}


def get_rainfall_for_extent(extent_fc):
    """
    Fetch current rainfall (mm/hr) for the centroid of *extent_fc* via
    ccm_weather (METAR primary, Open-Meteo fallback).

    Returns (rainfall_mm, source_description).  Returns (0.0, reason) when
    weather cannot be determined — callers then proceed with dry-table values.
    """
    if _weather_mod is None:
        return 0.0, "ccm_weather module not available"
    try:
        lat, lon = _weather_mod.get_area_centroid(extent_fc)
        mm = _weather_mod.get_rainfall_mm(lat, lon)
        if mm is None:
            return 0.0, "no weather data returned"
        return float(mm), f"live weather @ {lat:.4f}, {lon:.4f}"
    except Exception as exc:
        return 0.0, f"weather lookup failed: {exc}"


# =============================================================================
# SECTION 3 — VEHICLE PARSING
# =============================================================================

class Vehicle(object):
    """Lightweight container for one row of the vehicle definitions CSV."""

    __slots__ = (
        "name", "max_road_spd_kph", "max_on_road_grad", "max_off_road_grad",
        "vehicle_width_m", "max_override_diameter_m", "vci_1", "vci_50",
        "min_turning_radius_m", "locomotion_type",
    )

    def __init__(self, **kw):
        for s in self.__slots__:
            setattr(self, s, kw.get(s))

    def __repr__(self):
        return f"<Vehicle {self.name} road={self.max_road_spd_kph}kph vci50={self.vci_50}>"


def _to_float(val, default=None):
    """Parse a CSV cell to float, tolerating blanks and stray whitespace."""
    if val is None:
        return default
    s = str(val).strip()
    if s == "":
        return default
    try:
        return float(s)
    except ValueError:
        return default


def parse_vehicle_record(row):
    """
    Build a Vehicle from a dict-like CSV row (DictReader row).

    Recognised columns (case-insensitive):
        name, max_road_spd_kph, max_on_road_grad, max_off_road_grad,
        vehicle_width_m, max_override_diameter_m, vci_1, vci_50,
        min_turning_radius_m, locomotion_type
    """
    # Normalise keys to lower-case for tolerant matching
    low = {str(k).strip().lower(): v for k, v in row.items()}

    def g(*names):
        for n in names:
            if n in low:
                return low[n]
        return None

    return Vehicle(
        name                    = (g("name", "vehicle", "vehicle_name") or "Vehicle"),
        max_road_spd_kph        = _to_float(g("max_road_spd_kph", "max_road_speed_kph", "road_speed"), 50.0),
        max_on_road_grad        = _to_float(g("max_on_road_grad", "max_on_road_gradient"), 60.0),
        max_off_road_grad       = _to_float(g("max_off_road_grad", "max_off_road_gradient"), 45.0),
        vehicle_width_m         = _to_float(g("vehicle_width_m", "width_m", "width"), 2.5),
        max_override_diameter_m = _to_float(g("max_override_diameter_m", "override_diam_m"), 0.0),
        vci_1                   = _to_float(g("vci_1", "vci1"), None),
        vci_50                  = _to_float(g("vci_50", "vci50"), None),
        min_turning_radius_m    = _to_float(g("min_turning_radius_m", "turning_radius_m"), None),
        locomotion_type         = int(_to_float(g("locomotion_type", "locomotion"), 1) or 1),
    )


def load_vehicles_csv(csv_path):
    """Return {vehicle_name: Vehicle} parsed from a vehicle-definitions CSV."""
    vehicles = {}
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if not row:
                continue
            v = parse_vehicle_record(row)
            if v.name:
                vehicles[v.name] = v
    return vehicles


# =============================================================================
# SECTION 4 — PURE-PYTHON TRAFFICABILITY FACTORS  (unit-testable)
# =============================================================================
# Every factor returns a float in [0.0, 1.0]:
#   1.0 = no impediment, full speed
#   0.0 = NO GO (impassable for this vehicle)
# Intermediate values reduce speed proportionally.

def slope_factor(slope_pct, max_off_road_grad_pct):
    """
    F1 — slope/gradient factor.

    Passable up to ~60% of the vehicle's max gradient at full speed, then a
    linear taper to 0 at the vehicle's maximum off-road gradient.  Beyond the
    maximum gradient the slope is a hard NO GO.
    """
    if slope_pct is None:
        return 1.0  # unknown slope — do not penalise (flagged elsewhere)
    if max_off_road_grad_pct is None or max_off_road_grad_pct <= 0:
        max_off_road_grad_pct = 45.0
    s = max(0.0, float(slope_pct))
    if s >= max_off_road_grad_pct:
        return 0.0
    full_speed_limit = 0.6 * max_off_road_grad_pct
    if s <= full_speed_limit:
        return 1.0
    # Linear taper between full_speed_limit and max gradient
    span = max_off_road_grad_pct - full_speed_limit
    return max(0.0, 1.0 - (s - full_speed_limit) / span)


def veg_density_factor(vti):
    """
    F2 — vegetation-density factor from the Vegetation Traffic Impact (VTI).

    VTI is 0.0 (open ground) .. 1.0 (impenetrable canopy).  The factor is the
    complement, floored just above 0 for very dense (but not fully blocking)
    vegetation so density alone rarely produces an outright NO GO; spacing /
    stem override (F3) governs hard blocking.
    """
    if vti is None:
        return 1.0
    v = min(1.0, max(0.0, float(vti)))
    return max(0.05, 1.0 - v)


def veg_spacing_factor(tree_spacing_m, stem_diameter_cm,
                       vehicle_width_m, override_diameter_m):
    """
    F3 — manoeuvre / stem-override factor.

    Logic:
      * If the average gap between stems is wider than the vehicle, the vehicle
        threads between trees → passable (1.0).
      * If the gap is narrower than the vehicle, the vehicle must override
        (push over / drive through) stems.  It can do so only if stem diameter
        is at or below its override capability; otherwise NO GO (0.0).
      * A narrow-but-overridable stand is RESTRICTED → 0.5.
    """
    if tree_spacing_m is None:
        return 1.0
    width = vehicle_width_m if vehicle_width_m and vehicle_width_m > 0 else 2.5
    if tree_spacing_m >= width:
        return 1.0  # threads between stems
    # Must override stems to pass
    if stem_diameter_cm is None:
        return 0.5  # unknown stem size, narrow spacing — treat as restricted
    override_cm = (override_diameter_m or 0.0) * 100.0
    if stem_diameter_cm <= override_cm:
        return 0.5  # can push through but slowly
    return 0.0      # stems too large and gap too narrow — blocked


def soil_factor(uscs_code, moisture, vci_1, vci_50, rci_table=None):
    """
    Soil bearing-capacity factor from USCS code vs vehicle VCI.

    Compares the soil's Rating Cone Index (RCI) for the given moisture
    condition against the vehicle's one-pass (vci_1) and fifty-pass (vci_50)
    Vehicle Cone Index:
        RCI <  vci_1   → 0.0  (immobilised on first pass — NO GO)
        RCI >= vci_50  → 1.0  (sustained traffic OK — full speed)
        between        → linear ramp (RESTRICTED)
    Unknown soil (NE / unmapped) returns 1.0 but the caller should flag it as
    missing data.

    rci_table (optional) lets callers pass a weather-adjusted or calibrated
    table; defaults to the module-level USCS_RCI (soil_rci.csv or built-ins).
    """
    rci_tuple = (rci_table or USCS_RCI).get(uscs_code)
    if not rci_tuple:
        return 1.0  # unknown soil — not penalised here (data-gap, flagged upstream)
    idx = _MOISTURE_INDEX.get((moisture or "moist").lower(), 1)
    rci = rci_tuple[idx]
    if rci is None:
        return 1.0  # NE / not evaluated
    v1  = vci_1  if vci_1  is not None else 25.0
    v50 = vci_50 if vci_50 is not None else 50.0
    if v50 < v1:
        v50 = v1
    if rci < v1:
        return 0.0
    if rci >= v50:
        return 1.0
    if v50 == v1:
        return 1.0
    return max(0.0, min(1.0, (rci - v1) / (v50 - v1)))


def hydro_factor(in_water):
    """F_hydro — water-crossing factor. Open water = NO GO (0.0)."""
    return 0.0 if in_water else 1.0


def combine_speed(max_road_spd_kph, f1, f2, f3, f4, f5, f_hydro, moisture):
    """
    Combine the individual factors into a predicted cross-country speed (km/h).

    A single zero factor forces 0 km/h (NO GO).  Otherwise the off-road speed
    is the maximum road speed scaled by the product of the governing factors.
    The soil factor used is selected by moisture (F4 dry vs F5 wet/moist).
    """
    soil_f = f4 if (moisture or "moist").lower() == "dry" else f5
    factors = [f1, f2, f3, soil_f, f_hydro]
    # Treat None as 1.0 (no data → no penalty); hard zero anywhere = NO GO
    clean = [1.0 if x is None else float(x) for x in factors]
    if any(x <= 0.0 for x in clean):
        return 0.0
    product = 1.0
    for x in clean:
        product *= x
    base = max_road_spd_kph if max_road_spd_kph and max_road_spd_kph > 0 else 50.0
    return round(base * product, 1)


def classify_mobility(speed_kmh, max_road_spd_kph,
                      go_threshold=DEFAULT_GO_THRESHOLD_KMH,
                      restricted_fraction=DEFAULT_RESTRICTED_FRACTION):
    """
    Map a predicted speed to a Mobility class label.

        speed <= go_threshold                        → "NO GO"
        speed >= restricted_fraction * max_speed     → "GO"
        otherwise                                    → "RESTRICTED"
    """
    if speed_kmh is None or speed_kmh <= go_threshold:
        return MOB_NOGO
    base = max_road_spd_kph if max_road_spd_kph and max_road_spd_kph > 0 else 50.0
    if speed_kmh >= restricted_fraction * base:
        return MOB_GO
    return MOB_RESTRICTED


# =============================================================================
# SECTION 5 — ARCGIS GEOPROCESSING WRAPPER
# =============================================================================
# Field-name candidates for the slope value carried on the slope-regions FC.
_SLOPE_FIELD_CANDIDATES = [
    "slope_pct", "SlopePct", "slope", "Slope", "SLOPE",
    "gridcode", "GRIDCODE", "slope_deg", "SlopeDeg", "MEAN_slope",
]


def _find_field(fc, candidates):
    """Return the first existing field on fc (case-insensitive) from candidates."""
    existing = {f.name.lower(): f.name for f in arcpy.ListFields(fc)}
    for c in candidates:
        if c.lower() in existing:
            return existing[c.lower()]
    return None


def build_speed_surface(project_folder, vehicle_name, moisture=None,
                        go_threshold=DEFAULT_GO_THRESHOLD_KMH,
                        use_live_weather=False, rainfall_override_mm=None,
                        messages=None):
    """
    Generate a mobility speed-surface FC for one vehicle from the project config.

    use_live_weather    — fetch current rainfall for the AOI centroid and apply
                          the rainfall→RCI penalty before computing soil factors.
    rainfall_override_mm — manual rainfall rate (mm/hr); takes precedence over
                          the live lookup (use for exercises / known conditions).

    Returns the full path to the created feature class.
    Requires arcpy and a valid ccm_project.json written by Step 1.
    """
    if not _HAVE_ARCPY:
        raise RuntimeError("arcpy is required to build a speed surface.")
    if _cfg_mod is None:
        raise RuntimeError("ccm_project_config.py not loaded — cannot read config.")

    cfg = _cfg_mod.load_config(project_folder)
    if not cfg:
        raise RuntimeError(f"No ccm_project.json found in {project_folder}.")

    extent_fc   = cfg.get("extent_fc")
    soil_fc     = cfg.get("soil_fc")
    veg_fc      = cfg.get("veg_fc")
    slope_fc    = cfg.get("slope_fc")
    hydro_fcs   = cfg.get("hydro_fcs") or []
    vehicle_csv = cfg.get("vehicle_csv")
    project_gdb = cfg.get("project_gdb")
    moisture    = (moisture or cfg.get("moisture_default") or "moist").lower()

    if isinstance(hydro_fcs, str):
        hydro_fcs = [hydro_fcs]

    if not project_gdb or not arcpy.Exists(project_gdb):
        raise RuntimeError(f"Project GDB not found: {project_gdb}")
    if not vehicle_csv or not os.path.isfile(vehicle_csv):
        raise RuntimeError(f"Vehicle CSV not found: {vehicle_csv}")

    vehicles = load_vehicles_csv(vehicle_csv)
    if vehicle_name not in vehicles:
        raise RuntimeError(
            f"Vehicle '{vehicle_name}' not in CSV. Available: {', '.join(vehicles)}"
        )
    veh = vehicles[vehicle_name]
    arcpy.AddMessage(f"[Step 2] Vehicle: {veh!r}")

    # ── Effective RCI table (calibrated CSV ± weather adjustment) ────────────
    rci_table = dict(USCS_RCI)
    rainfall_mm = 0.0
    if rainfall_override_mm is not None:
        rainfall_mm = max(0.0, float(rainfall_override_mm))
        arcpy.AddMessage(f"[Step 2] Rainfall override: {rainfall_mm} mm/hr")
    elif use_live_weather:
        rainfall_mm, src = get_rainfall_for_extent(extent_fc)
        arcpy.AddMessage(f"[Step 2] Live rainfall: {rainfall_mm} mm/hr ({src})")
    if rainfall_mm > 0.0:
        rci_table = apply_weather_to_rci(rci_table, rainfall_mm)
        arcpy.AddMessage(
            "[Step 2] Rainfall penalty applied to soil RCI values "
            "(see ccm_weather thresholds)."
        )

    arcpy.env.overwriteOutput = True

    # ── Union the available criteria layers within the extent ────────────────
    union_inputs = [fc for fc in (soil_fc, veg_fc, slope_fc) if fc and arcpy.Exists(fc)]
    if not union_inputs:
        raise RuntimeError("None of soil_fc / veg_fc / slope_fc exist — run Step 1 first.")

    scratch = arcpy.env.scratchGDB
    unioned = os.path.join(scratch, "ccm_s2_union")
    if arcpy.Exists(unioned):
        arcpy.management.Delete(unioned)
    arcpy.AddMessage(f"[Step 2] Unioning {len(union_inputs)} criteria layer(s) …")
    arcpy.analysis.Union(union_inputs, unioned, "ALL")

    # Clip to extent if provided
    work_fc = unioned
    if extent_fc and arcpy.Exists(extent_fc):
        clipped = os.path.join(scratch, "ccm_s2_clip")
        if arcpy.Exists(clipped):
            arcpy.management.Delete(clipped)
        arcpy.analysis.Clip(unioned, extent_fc, clipped)
        work_fc = clipped

    # ── Flag features that intersect open water (hydro) ──────────────────────
    water_flag_field = "_inWater"
    arcpy.management.AddField(work_fc, water_flag_field, "SHORT")
    arcpy.management.CalculateField(work_fc, water_flag_field, 0, "PYTHON3")
    valid_hydro = [h for h in hydro_fcs if h and arcpy.Exists(h)]
    if valid_hydro:
        lyr = "ccm_s2_lyr"
        arcpy.management.MakeFeatureLayer(work_fc, lyr)
        for h in valid_hydro:
            arcpy.management.SelectLayerByLocation(
                lyr, "INTERSECT", h, selection_type="NEW_SELECTION"
            )
            if int(arcpy.management.GetCount(lyr)[0]) > 0:
                arcpy.management.CalculateField(lyr, water_flag_field, 1, "PYTHON3")
        arcpy.management.SelectLayerByAttribute(lyr, "CLEAR_SELECTION")
        arcpy.management.Delete(lyr)

    # ── Copy to the project GDB as the output speed surface ──────────────────
    veh_tag = vehicle_name.lower().replace(" ", "_")
    out_name = f"speed_surface_{veh_tag}_{moisture}"
    out_fc = os.path.join(project_gdb, out_name)
    if arcpy.Exists(out_fc):
        arcpy.management.Delete(out_fc)
    arcpy.management.CopyFeatures(work_fc, out_fc)

    # ── Add the output contract fields ───────────────────────────────────────
    for fname, ftype in [
        (FIELD_MOBILITY, "TEXT"), (FIELD_SPEED, "FLOAT"),
        (FIELD_F1, "DOUBLE"), (FIELD_F2, "DOUBLE"), (FIELD_F3, "DOUBLE"),
        (FIELD_F4, "DOUBLE"), (FIELD_F5, "DOUBLE"), (FIELD_FHYDRO, "DOUBLE"),
    ]:
        if ftype == "TEXT":
            arcpy.management.AddField(out_fc, fname, ftype, field_length=20)
        else:
            arcpy.management.AddField(out_fc, fname, ftype)

    # ── Resolve source attribute fields on the unioned FC ────────────────────
    soil_field  = _find_field(out_fc, ["soilType"])
    vti_field   = _find_field(out_fc, ["vegetationTrafficImpact", "VTI"])
    space_field = _find_field(out_fc, ["treeSpacing"])
    stem_field  = _find_field(out_fc, ["stemDiameter"])
    slope_field = _find_field(out_fc, _SLOPE_FIELD_CANDIDATES)

    arcpy.AddMessage(
        f"[Step 2] Source fields → soil={soil_field}, VTI={vti_field}, "
        f"spacing={space_field}, stem={stem_field}, slope={slope_field}"
    )

    cursor_fields = [
        FIELD_MOBILITY, FIELD_SPEED, FIELD_F1, FIELD_F2, FIELD_F3,
        FIELD_F4, FIELD_F5, FIELD_FHYDRO, water_flag_field,
    ]
    src_fields = [soil_field, vti_field, space_field, stem_field, slope_field]
    cursor_fields += [f for f in src_fields if f]

    # Index helper: position of each source field within the row
    def _src_idx(field):
        if not field:
            return None
        return cursor_fields.index(field)

    i_soil, i_vti, i_space, i_stem, i_slope = (
        _src_idx(soil_field), _src_idx(vti_field), _src_idx(space_field),
        _src_idx(stem_field), _src_idx(slope_field),
    )
    i_water = cursor_fields.index(water_flag_field)

    n_go = n_restricted = n_nogo = 0
    with arcpy.da.UpdateCursor(out_fc, cursor_fields) as cur:
        for row in cur:
            soil_code = row[i_soil]  if i_soil  is not None else None
            vti       = row[i_vti]   if i_vti   is not None else None
            spacing   = row[i_space] if i_space is not None else None
            stem      = row[i_stem]  if i_stem  is not None else None
            slope     = row[i_slope] if i_slope is not None else None
            in_water  = bool(row[i_water])

            f1 = slope_factor(slope, veh.max_off_road_grad)
            f2 = veg_density_factor(vti)
            f3 = veg_spacing_factor(spacing, stem, veh.vehicle_width_m,
                                    veh.max_override_diameter_m)
            f4 = soil_factor(soil_code, "dry",  veh.vci_1, veh.vci_50, rci_table)
            f5 = soil_factor(soil_code, "wet",  veh.vci_1, veh.vci_50, rci_table)
            fh = hydro_factor(in_water)

            speed = combine_speed(veh.max_road_spd_kph, f1, f2, f3, f4, f5, fh, moisture)
            mob   = classify_mobility(speed, veh.max_road_spd_kph, go_threshold)

            row[0] = mob
            row[1] = speed
            row[2], row[3], row[4] = f1, f2, f3
            row[5], row[6], row[7] = f4, f5, fh
            cur.updateRow(row)

            if   mob == MOB_GO:         n_go += 1
            elif mob == MOB_RESTRICTED: n_restricted += 1
            else:                       n_nogo += 1

    # Clean up the temporary water-flag field
    try:
        arcpy.management.DeleteField(out_fc, water_flag_field)
    except Exception:
        pass

    arcpy.AddMessage(
        f"[Step 2] Speed surface complete → {out_fc}\n"
        f"          GO={n_go:,}  RESTRICTED={n_restricted:,}  NO GO={n_nogo:,}"
    )

    # ── Register the result in the project config so Step 3 auto-fills ───────
    last_vehicles = cfg.get("last_vehicles") or []
    if vehicle_name not in last_vehicles:
        last_vehicles.append(vehicle_name)
    _cfg_mod.save_config(
        project_folder,
        mobility_map_fc = out_fc,
        last_run_output = out_fc,
        last_vehicles   = last_vehicles,
        moisture_default = moisture,
    )
    arcpy.AddMessage("[Step 2] Project config updated (mobility_map_fc, last_vehicles).")
    return out_fc


# =============================================================================
# SECTION 6 — TOOLBOX TOOL CLASS
# =============================================================================

class CCMStep2MobilityTool(object):
    """Step 2 — Generate Mobility Map (speed surface) for one vehicle."""

    def __init__(self):
        self.label = "Step 2.  Generate Mobility Map"
        self.description = (
            "Runs the cross-country mobility model on the layers registered by "
            "Step 1 and produces a speed-surface feature class (SpeedKMH + "
            "Mobility + F-factor fields) for a chosen vehicle.  This output is "
            "the input for every Step 3 analysis."
        )
        self.canRunInBackground = False

    def getParameterInfo(self):
        p_folder = arcpy.Parameter(
            displayName="Project Folder  (contains ccm_project.json)",
            name="project_folder",
            datatype="DEFolder",
            parameterType="Required",
            direction="Input",
        )
        p_vehicle = arcpy.Parameter(
            displayName="Vehicle",
            name="vehicle_name",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
        )
        p_moisture = arcpy.Parameter(
            displayName="Soil Moisture Condition",
            name="moisture",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
        )
        p_moisture.filter.type = "ValueList"
        p_moisture.filter.list = ["dry", "moist", "wet"]
        p_moisture.value = "moist"

        p_thresh = arcpy.Parameter(
            displayName="GO Threshold (km/h) — at or below this = NO GO",
            name="go_threshold",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input",
        )
        p_thresh.value = DEFAULT_GO_THRESHOLD_KMH

        p_weather = arcpy.Parameter(
            displayName="Use Live Weather  (fetch current rainfall for the AOI "
                        "and penalise soil RCI)",
            name="use_live_weather",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input",
            category="Weather",
        )
        p_weather.value = False

        p_rain = arcpy.Parameter(
            displayName="Manual Rainfall Override (mm/hr)  [takes precedence "
                        "over live weather]",
            name="rainfall_override_mm",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input",
            category="Weather",
        )

        p_out = arcpy.Parameter(
            displayName="Output Speed Surface  (set automatically in project GDB)",
            name="output_fc",
            datatype="DEFeatureClass",
            parameterType="Derived",
            direction="Output",
        )
        return [p_folder, p_vehicle, p_moisture, p_thresh, p_weather, p_rain, p_out]

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        p_folder, p_vehicle, p_moisture = parameters[0], parameters[1], parameters[2]
        # Populate the vehicle dropdown + default moisture from the config / CSV
        if p_folder.value and _cfg_mod:
            try:
                cfg = _cfg_mod.load_config(p_folder.valueAsText)
            except Exception:
                cfg = {}
            if cfg:
                if (not p_moisture.altered) and cfg.get("moisture_default"):
                    p_moisture.value = cfg["moisture_default"]
                csv_path = cfg.get("vehicle_csv")
                if csv_path and os.path.isfile(csv_path):
                    try:
                        names = list(load_vehicles_csv(csv_path).keys())
                        if names:
                            p_vehicle.filter.type = "ValueList"
                            p_vehicle.filter.list = names
                    except Exception:
                        pass

    def updateMessages(self, parameters):
        p_folder = parameters[0]
        if p_folder.value:
            cfg_path = os.path.join(str(p_folder.valueAsText), "ccm_project.json")
            if not os.path.isfile(cfg_path):
                p_folder.setErrorMessage(
                    "No ccm_project.json here — run Step 1 first."
                )

    def execute(self, parameters, messages):
        arcpy.SetLogMetadata(False)
        project_folder = parameters[0].valueAsText
        vehicle_name   = parameters[1].valueAsText
        moisture       = parameters[2].valueAsText
        go_threshold   = float(parameters[3].value or DEFAULT_GO_THRESHOLD_KMH)
        use_weather    = bool(parameters[4].value)
        rain_override  = (float(parameters[5].value)
                          if parameters[5].value not in (None, "") else None)

        out_fc = build_speed_surface(
            project_folder        = project_folder,
            vehicle_name          = vehicle_name,
            moisture              = moisture,
            go_threshold          = go_threshold,
            use_live_weather      = use_weather,
            rainfall_override_mm  = rain_override,
            messages              = messages,
        )
        arcpy.SetParameterAsText(6, out_fc)
        arcpy.AddMessage("=" * 60)
        arcpy.AddMessage("  Step 2 complete.  Open Step 3 for advanced analysis.")
        arcpy.AddMessage("=" * 60)

    # Decoupled programmatic entry point (no fragile positional parameter list).
    def run(self, messages=None, **kwargs):
        """Call the engine directly with keyword arguments (used by callers
        that do not have an arcpy parameter list)."""
        return build_speed_surface(messages=messages, **kwargs)

# <<< END OF FILE >>>
