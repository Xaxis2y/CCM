# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# -*- coding: utf-8 -*-
# ccm_step2_mobility.py
# CCM Step 2 — Mobility Map (Speed Surface) Engine
#
# This is the CORE multi-criteria evaluation engine of the toolbox.
# It consumes the pre-processed layers registered in ccm_project.json by
# Step 1 and produces a "speed surface" polygon feature class that every
# downstream tool (Reason Map, Isochrone, Waypoint Route, Vehicle Compare,
# Obstacle Detect) depends on.
#
# VERSION = "0.55.0"
VERSION = "0.55.0"  # v0.55.0 -- merge release: reconciles the debranded/relicensed v0.54.1 line with all v0.54.2-v0.54.7 fixes (Union licence-limit crash, speed-surface symbology field, alpha scale, ERROR 160333 isochrone resilience, build.py packaging guards). See CHANGELOG_v0.55.md.
# v0.49 — Doctrinal modelling upgrades (NG-NRMM alignment):
#          1. Speed Made Good (SMG) + %NOGO area-weighted summary: after the
#             scoring cursor, collect (speed, area) pairs and compute the
#             doctrinal area-weighted speed CDF + %NOGO by area fraction.
#             The SMG summary is logged to arcpy messages and is the canonical
#             NG-NRMM output representation for a mapped area.
#          2. combine_speed: product → min-of-limiting-factors (doctrinal).
#             NRMM takes the minimum of the speeds each constraint independently
#             permits (limiting factor governs).  The old multiplicative product
#             compounded mild penalties (two ×0.7 factors → ×0.49, i.e. slower
#             than either constraint alone justifies).  The minimum is retained
#             in the new formula; backward-compat parameter `speed_model` is
#             provided but defaults to "min".
#          3. MMP metric: compute_mmp_estimate() derives Mean Maximum Pressure
#             (kPa) from VCI_50 using ERDC empirical coefficients (k_track=0.56,
#             k_wheel=0.18, Shoop 2000).  Logged in Step 2 completion summary and
#             read from the new `mmp_kpa` column in Vehicles_Can.csv when present.
#          4. Stochastic GO/NOGO: compute_stochastic_go() runs a Monte Carlo
#             (default 200 trials) perturbing RCI (CV=0.15) and slope (CV=0.10)
#             to output a P(GO) probability per polygon.  Opt-in via the new
#             `enable_stochastic` parameter (default False); writes P_GO field.
#          5. Spatial soil moisture: when use_spatial_moisture=True, a pre-pass
#             queries ccm_weather.get_spatial_soil_moisture() at a grid of points
#             across the AOI and assigns per-polygon moisture conditions before
#             the main scoring cursor.  Defaults to global moisture parameter.
# v0.48 — Modelling fixes:
#          1. Three-way moisture: the speed-driving soil factor is now computed
#             for the ACTUAL moisture condition (dry/moist/wet), so "moist" uses
#             the moist RCI column instead of collapsing onto wet.  F4_soil_dry /
#             F5_soil_wet are still written as the dry/wet endpoints for the
#             Reason Map (combine_speed gains a `soil_active` argument).
#          2. Slope units: build_speed_surface honours the slope field name and
#             units recorded by Step 1 (slope_field / slope_units in config);
#             degree-valued slope fields are converted to percent before F1.
# v0.47 — Calibration & weather integration:
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
import math
import random

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
# v0.49 optional field — written only when enable_stochastic=True
FIELD_P_GO     = "P_GO"

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
    # Calibrated to ERDC/GL TR-02-6 Table 2, FM 5-430-00-1 App E, and NRMM
    # soil-strength database (Turnage 1971).
    # Conditions: dry = w < PL-5%; moist = w ≈ optimum; wet = w > LL / saturated.
    # Validation matrix (vci1/vci50): M1(25/58), M113(17/40), M35A2(26/59), M151(19/44)
    "GW": (380, 300, 240),   # well-graded gravel — GO all conditions all vehicles
    "GP": (340, 260, 200),
    "GM": (280, 200, 120),   # silty gravel — GO all conditions
    "GC": (240, 160,  90),   # clayey gravel — GO all conditions
    "SW": (260, 200, 130),   # well-graded sand — GO all conditions
    "SP": (230, 170, 100),
    "SM": (200, 140,  65),   # silty sand — marginal GO heaviest vehicles when wet
    "SC": (175, 110,  48),   # clayey sand — RESTRICTED heavy vehicles when wet
    "ML": (150,  80,  32),   # silt — RESTRICTED all vehicles when wet
    "CL": (150,  75,  28),   # lean clay — RESTRICTED all vehicles when wet
    "OL": (110,  55,  14),   # organic silt — NOGO all vehicles when wet
    "MH": (120,  60,  16),   # elastic silt — NOGO all vehicles when wet
    "CH": (130,  65,  15),   # fat clay — NOGO all vehicles when wet
    "OH": ( 90,  42,  12),   # organic clay — NOGO all vehicles when wet
    "Pt": ( 50,  28,   8),   # peat — NOGO when wet; RESTRICTED dry/moist
    "RK": (500, 500, 500),   # rock — unlimited bearing capacity
    "NE": (None, None, None),  # not evaluated — unknown
}

RCI_CSV_NAME = "soil_rci.csv"


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


def apply_weather_to_rci(rci_table, rainfall_mm, manual_override=None,
                         antecedent_multiplier=1.0):
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
    antecedent_multiplier : float, optional — amplifies rain_penalty for
        historical saturation scenarios (see ANTECEDENT_SCENARIOS).
        Default 1.0 = standard instantaneous-rain behaviour.
    """
    if _weather_mod is None:
        return dict(rci_table)
    keyed = {
        USCS_TO_SENSITIVITY_KEY.get(code, code): vals
        for code, vals in rci_table.items()
    }
    adjusted = _weather_mod.adjust_rci_for_rainfall(
        keyed, rainfall_mm,
        manual_override=manual_override,
        antecedent_multiplier=antecedent_multiplier,
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
        result = _weather_mod.get_rainfall_mm(lat, lon)
        # get_rainfall_mm returns a dict: {"rainfall_mm": float, "source": str, "message": str}
        mm = result.get("rainfall_mm") if isinstance(result, dict) else result
        if mm is None:
            return 0.0, "no weather data returned"
        src = result.get("source", f"{lat:.4f}, {lon:.4f}") if isinstance(result, dict) else f"{lat:.4f}, {lon:.4f}"
        return float(mm), f"live weather ({src}): {float(mm):.1f} mm/hr"
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


def combine_speed(max_road_spd_kph, f1, f2, f3, f4, f5, f_hydro, moisture,
                  soil_active=None, speed_model="min"):
    """
    Combine the individual factors into a predicted cross-country speed (km/h).

    v0.49 default: speed_model="min" — NRMM/NG-NRMM doctrine.
        The terrain constraint that independently limits speed the most governs
        the final speed.  Equivalent to: speed = max_speed × min(all factors).
        This avoids the compound-penalty problem of the multiplicative product
        (two mild ×0.7 factors → ×0.49 with product vs ×0.70 with min).

    speed_model="product" restores the previous multiplicative behaviour for
        backward-compatibility comparison.

    Soil factor: if soil_active is given it is used directly (lets the caller
    pass the factor for the ACTUAL moisture, incl. "moist"); otherwise the
    legacy F4(dry)/F5(else) selection applies.

    A single zero factor → 0.0 km/h (NO GO) under both models.
    """
    if soil_active is not None:
        soil_f = soil_active
    else:
        soil_f = f4 if (moisture or "moist").lower() == "dry" else f5
    factors = [f1, f2, f3, soil_f, f_hydro]
    # Treat None as 1.0 (no data → no penalty); hard zero anywhere = NO GO
    clean = [1.0 if x is None else float(x) for x in factors]
    if any(x <= 0.0 for x in clean):
        return 0.0
    base = max_road_spd_kph if max_road_spd_kph and max_road_spd_kph > 0 else 50.0
    if speed_model == "product":
        scalar = 1.0
        for x in clean:
            scalar *= x
    else:
        # "min" — limiting factor governs (NG-NRMM doctrine)
        scalar = min(clean)
    return round(base * scalar, 1)


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
# SECTION 4b — SPEED MADE GOOD, MMP, AND STOCHASTIC MOBILITY  (v0.49)
# =============================================================================

def compute_speed_made_good(speed_area_pairs, go_threshold=DEFAULT_GO_THRESHOLD_KMH,
                            max_road_spd_kph=50.0, n_bins=20):
    """
    Compute the Speed Made Good (SMG) area-weighted CDF — the NG-NRMM
    doctrinal summary for a mapped area.

    Parameters
    ----------
    speed_area_pairs : list of (speed_kmh, area_m2)
        One entry per polygon from the speed-surface FC.  Area 0 / None is
        silently ignored.
    go_threshold : float
        Speed at or below which a polygon is classified NO GO.
    max_road_spd_kph : float
        Vehicle's maximum road speed — used to classify the GO boundary.
    n_bins : int
        Number of speed bins for the CDF (default 20).

    Returns
    -------
    dict with keys:
        total_area_m2    : float
        nogo_area_m2     : float
        pct_nogo         : float  (% of total area that is NO GO by area)
        pct_restricted   : float
        pct_go           : float
        mean_speed_kmh   : float  (area-weighted mean speed, excl. NO GO)
        median_speed_kmh : float  (area-weighted median speed, excl. NO GO)
        cdf              : list of (speed_kmh, pct_area_at_or_above)
            Speed Made Good curve: for each speed threshold, % of total
            area traversable at >= that speed.  This is the canonical NRMM
            "Speed Made Good" plot.
    """
    if not speed_area_pairs:
        return {"total_area_m2": 0, "nogo_area_m2": 0, "pct_nogo": 100.0,
                "pct_restricted": 0.0, "pct_go": 0.0,
                "mean_speed_kmh": 0.0, "median_speed_kmh": 0.0, "cdf": []}

    valid = [(float(s), float(a)) for s, a in speed_area_pairs
             if a is not None and a > 0 and s is not None]
    if not valid:
        return {"total_area_m2": 0, "nogo_area_m2": 0, "pct_nogo": 100.0,
                "pct_restricted": 0.0, "pct_go": 0.0,
                "mean_speed_kmh": 0.0, "median_speed_kmh": 0.0, "cdf": []}

    total_area = sum(a for _, a in valid)
    nogo_area  = sum(a for s, a in valid if s <= go_threshold)
    rest_thresh = DEFAULT_RESTRICTED_FRACTION * max_road_spd_kph
    rest_area   = sum(a for s, a in valid if go_threshold < s < rest_thresh)
    go_area     = sum(a for s, a in valid if s >= rest_thresh)

    pct_nogo  = 100.0 * nogo_area / total_area if total_area else 100.0
    pct_rest  = 100.0 * rest_area / total_area if total_area else 0.0
    pct_go    = 100.0 * go_area   / total_area if total_area else 0.0

    # Area-weighted mean (exclude NO GO polygons to get a "traversable" mean)
    mobile = [(s, a) for s, a in valid if s > go_threshold]
    if mobile:
        mob_area  = sum(a for _, a in mobile)
        mean_spd  = sum(s * a for s, a in mobile) / mob_area if mob_area else 0.0
        # Median: sort by speed, find 50th-percentile cumulative area
        mobile_sorted = sorted(mobile, key=lambda x: x[0])
        cumul = 0.0
        median_spd = mobile_sorted[-1][0]
        for spd, area in mobile_sorted:
            cumul += area
            if cumul >= mob_area * 0.5:
                median_spd = spd
                break
    else:
        mean_spd = median_spd = 0.0

    # CDF: for each bin speed v, pct of TOTAL area with speed >= v
    # (the "Speed Made Good" curve: x-axis = speed, y-axis = % area achievable)
    max_speed = max(s for s, _ in valid)
    bin_size = max(1.0, max_speed / n_bins) if max_speed > 0 else 1.0
    cdf = []
    for i in range(n_bins + 1):
        v = i * bin_size
        area_at_or_above = sum(a for s, a in valid if s >= v)
        cdf.append((round(v, 1), round(100.0 * area_at_or_above / total_area, 1)
                    if total_area else 0.0))

    return {
        "total_area_m2":    round(total_area, 1),
        "nogo_area_m2":     round(nogo_area, 1),
        "pct_nogo":         round(pct_nogo, 1),
        "pct_restricted":   round(pct_rest, 1),
        "pct_go":           round(pct_go, 1),
        "mean_speed_kmh":   round(mean_spd, 1),
        "median_speed_kmh": round(median_spd, 1),
        "cdf":              cdf,
    }


def compute_mmp_estimate(vci_50, locomotion_type=1):
    """
    Estimate Mean Maximum Pressure (kPa) from VCI_50 using the ERDC empirical
    relationship (Shoop 2000, ERDC/CRREL TR-00-20).

    Tracked vehicles  (locomotion_type=1): VCI_50 ≈ 0.56 × MMP_kPa
    Wheeled vehicles  (locomotion_type=0): VCI_50 ≈ 0.18 × MMP_kPa
      (wheeled vehicles require much higher soil strength because of localised
      point loading vs. tracked vehicles' distributed ground contact)

    Returns MMP in kPa, or None if vci_50 is None.
    """
    if vci_50 is None:
        return None
    v = float(vci_50)
    if locomotion_type == 0:
        k = 0.18   # wheeled
    else:
        k = 0.56   # tracked (default)
    return round(v / k, 1) if k > 0 else None


def compute_stochastic_go(soil_code, moisture, vci_1, vci_50, slope_pct,
                          max_grad, rci_table=None, n_trials=200,
                          rci_cv=0.15, slope_cv=0.10):
    """
    Reliability-based probability of GO via Monte Carlo.

    Perturbs the two largest sources of uncertainty:
      - Soil RCI: drawn from Normal(mu=rci_base, sigma=rci_base × rci_cv)
        clamped to [0, ∞).  CV=0.15 is consistent with ERDC field-variability
        data for cone-index measurements.
      - Slope: drawn from Normal(mu=slope_pct, sigma=slope_pct × slope_cv)
        clamped to [0, ∞).  CV=0.10 reflects DEM vertical accuracy (2–5 m
        RMSE translates to ~10% slope uncertainty at typical polygon sizes).

    Vegetation and hydro factors are held at their deterministic values since
    their uncertainty is captured by the mapping classification, not by
    parameter variation.

    Parameters
    ----------
    soil_code : str   — USCS code
    moisture  : str   — "dry"/"moist"/"wet"
    vci_1, vci_50 : float  — vehicle VCI values
    slope_pct : float or None — slope in percent
    max_grad  : float  — vehicle max off-road gradient (percent)
    rci_table : dict, optional — calibrated RCI table; defaults to module USCS_RCI
    n_trials  : int   — Monte Carlo sample count (default 200)
    rci_cv    : float — RCI coefficient of variation (default 0.15)
    slope_cv  : float — slope coefficient of variation (default 0.10)

    Returns
    -------
    float in [0.0, 1.0] — proportion of trials that are GO
      (i.e., soil factor > 0 AND slope factor > 0)
    """
    table  = rci_table or USCS_RCI
    rci_t  = table.get(soil_code)
    idx    = _MOISTURE_INDEX.get((moisture or "moist").lower(), 1)

    rci_base   = rci_t[idx] if rci_t else None
    slope_base = max(0.0, float(slope_pct)) if slope_pct is not None else 0.0

    # If no soil data: uncertain but not penalised — treat as 100% GO
    if rci_base is None:
        return 1.0

    v1  = vci_1  if vci_1  is not None else 25.0
    v50 = vci_50 if vci_50 is not None else 50.0
    if v50 < v1:
        v50 = v1

    max_g = max_grad if max_grad and max_grad > 0 else 45.0

    go_count = 0
    for _ in range(n_trials):
        # Perturb RCI (Normal, clamp ≥ 0)
        rci_pert   = max(0.0, random.gauss(rci_base, rci_base * rci_cv))
        # Perturb slope (Normal, clamp ≥ 0; zero base → no slope perturbation)
        slope_pert = max(0.0, random.gauss(slope_base, slope_base * slope_cv + 0.01))

        # Soil factor with perturbed RCI
        orig = rci_t
        pert_tuple = list(orig)
        pert_tuple[idx] = rci_pert
        f_soil = soil_factor(soil_code, moisture, v1, v50,
                             rci_table={soil_code: tuple(pert_tuple)})

        # Slope factor with perturbed slope
        f_slope = slope_factor(slope_pert, max_g)

        if f_soil > 0.0 and f_slope > 0.0:
            go_count += 1

    return round(go_count / n_trials, 4)


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


def _slope_to_percent(value, units):
    # Normalise a raw slope value to PERCENT (what slope_factor expects).
    # units "degrees" -> tan(theta)*100 (clamped <90 deg); "percent" -> as-is;
    # None / unparsable -> None (slope_factor treats None as "no penalty").
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if (units or "percent").lower().startswith("deg"):
        return math.tan(math.radians(min(max(v, 0.0), 89.9))) * 100.0
    return v


def _union_license_safe(inputs, out_fc, join_attrs="ALL", scratch_ws=None):
    """
    Union any number of polygon feature classes without requiring an
    Advanced ArcGIS licence.

    v0.54.4 fix.  build_speed_surface() used to call
    ``arcpy.analysis.Union(union_inputs, unioned, "ALL")`` with all of
    soil_fc / veg_fc / slope_fc in a single call.  On a Basic or Standard
    licence this raises:

        ERROR 000384: Cannot have more than 2 inputs with a Basic or
        Standard license.

    confirmed against a real ArcGIS Pro 3.7.1 / Standard-tier install via
    tests/arcpy_smoke_test.py, which failed at this exact line. Union (and
    Intersect) are capped at two inputs below the Advanced tier; Esri's own
    documented fix is to run the tool consecutively, two inputs at a time
    (see the "000384" tool-errors-and-warnings page). This is the CORE
    output of the whole toolbox — every Step 2 run with all three criteria
    layers present failed outright for any user without an Advanced
    licence, with no fallback and no earlier warning.

    This helper folds *inputs* left-to-right, two at a time, so it issues
    ONLY 2-input Union calls and never trips the limit. It does NOT attempt
    to detect the licence tier first (arcpy.ProductInfo() naming is a legacy
    ArcMap holdover and licence policy is Esri's to change) — pairwise
    unioning is unconditional and therefore correct on Basic, Standard, AND
    Advanced alike. On Advanced this costs a few extra intermediate
    Union calls versus a single N-way one; that is a fair trade for never
    failing outright on the tiers below it.

    Parameters
    ----------
    inputs : list[str]
        Paths to the feature classes to union. Must contain at least one.
    out_fc : str
        Path the final unioned feature class is written to.
    join_attrs : str
        Passed through to arcpy.analysis.Union's join_attributes parameter.
    scratch_ws : str, optional
        Workspace for intermediate unions. Defaults to arcpy.env.scratchGDB.

    Returns
    -------
    str
        *out_fc*, for convenient chaining.
    """
    if not inputs:
        raise ValueError("_union_license_safe() requires at least one input.")

    scratch_ws = scratch_ws or arcpy.env.scratchGDB

    if len(inputs) == 1:
        # Nothing to union — Union's single-input behaviour is unverified
        # and unnecessary here; just materialise the one input at out_fc.
        if arcpy.Exists(out_fc):
            arcpy.management.Delete(out_fc)
        arcpy.management.CopyFeatures(inputs[0], out_fc)
        return out_fc

    # 2, 3, 4, ... inputs: fold left, two at a time. Every Union call below
    # receives exactly 2 inputs, so this never raises ERROR 000384 on any
    # licence tier.
    running = inputs[0]
    n_pairs = len(inputs) - 1
    intermediates = []
    try:
        for i, nxt in enumerate(inputs[1:], start=1):
            is_last = (i == n_pairs)
            dest = out_fc if is_last else os.path.join(
                scratch_ws, f"_ccm_union_chain_{i}")
            if arcpy.Exists(dest):
                arcpy.management.Delete(dest)
            arcpy.analysis.Union([running, nxt], dest, join_attrs)
            if running != inputs[0]:
                intermediates.append(running)   # a chain temp, safe to drop
            running = dest
    finally:
        for tmp in intermediates:
            try:
                arcpy.management.Delete(tmp)
            except Exception:
                pass
    return out_fc


def build_speed_surface(project_folder, vehicle_name, moisture=None,
                        go_threshold=DEFAULT_GO_THRESHOLD_KMH,
                        use_live_weather=False, rainfall_override_mm=None,
                        moisture_scenario=None,
                        enable_stochastic=False, stochastic_trials=200,
                        use_spatial_moisture=False,
                        messages=None):
    """
    Generate a mobility speed-surface FC for one vehicle from the project config.

    use_live_weather      — fetch current rainfall for the AOI centroid and apply
                            the rainfall→RCI penalty before computing soil factors.
    rainfall_override_mm  — manual rainfall rate (mm/hr); takes precedence over
                            all other weather settings.
    moisture_scenario     — named antecedent scenario (see ccm_weather.SCENARIO_NAMES).
                            Takes precedence over live weather fetch.
                            "Live Weather" or None = use live fetch if enabled.
    enable_stochastic     — if True, runs compute_stochastic_go() per polygon and
                            writes P_GO (DOUBLE [0..1]) to the speed surface FC.
                            Default False.
    stochastic_trials     — Monte Carlo trials per polygon (default 200).
    use_spatial_moisture  — if True, queries Open-Meteo VWC at a 3x3 grid across
                            the AOI and assigns per-polygon moisture conditions.

    Priority order for RCI adjustment:
        rainfall_override_mm  (highest — analyst-supplied mm/hr)
        → moisture_scenario ≠ "Live Weather"  (strategic planning preset)
        → use_live_weather = True  (real-time METAR/Open-Meteo fetch)
        → no adjustment  (dry tabulated values)

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
    slope_field_cfg = cfg.get("slope_field")           # explicit field name (Step 1)
    slope_units = (cfg.get("slope_units") or "percent").lower()  # "percent" | "degrees"
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

    # ── Effective RCI table (calibrated CSV ± weather/scenario adjustment) ──
    rci_table = dict(USCS_RCI)
    rainfall_mm           = 0.0
    antecedent_multiplier = 1.0

    if rainfall_override_mm is not None:
        # Highest priority: analyst-supplied numeric mm/hr value
        rainfall_mm = max(0.0, float(rainfall_override_mm))
        arcpy.AddMessage(f"[Step 2] Rainfall override: {rainfall_mm} mm/hr.")

    elif (moisture_scenario
          and moisture_scenario != "Live Weather"
          and _weather_mod is not None
          and hasattr(_weather_mod, "ANTECEDENT_SCENARIOS")):
        # Strategic scenario selected — use preset values, skip live fetch
        preset = _weather_mod.ANTECEDENT_SCENARIOS.get(moisture_scenario, {})
        rainfall_mm           = float(preset.get("rainfall_mm_equiv") or 0.0)
        antecedent_multiplier = float(preset.get("antecedent_multiplier", 1.0))
        arcpy.AddMessage(
            f"[Step 2] Scenario '{moisture_scenario}': "
            f"{rainfall_mm:.1f} mm/hr equiv, ×{antecedent_multiplier:.2f} antecedent."
        )

    elif use_live_weather:
        # Live weather fetch (METAR → Open-Meteo fallback)
        rainfall_mm, src = get_rainfall_for_extent(extent_fc)
        arcpy.AddMessage(f"[Step 2] Live rainfall: {rainfall_mm} mm/hr ({src})")

    if rainfall_mm > 0.0 or antecedent_multiplier > 1.0:
        rci_table = apply_weather_to_rci(
            rci_table, rainfall_mm, antecedent_multiplier=antecedent_multiplier
        )
        arcpy.AddMessage(
            "[Step 2] Rainfall/scenario penalty applied to soil RCI values "
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
    # v0.54.4: unions pairwise so this never hits ERROR 000384 on a Basic
    # or Standard licence (see _union_license_safe docstring).
    n_in = len(union_inputs)
    arcpy.AddMessage(
        f"[Step 2] Unioning {n_in} criteria layer(s) "
        f"({'single pass' if n_in <= 2 else f'{n_in - 1} pairwise passes — licence-safe'}) …"
    )
    _union_license_safe(union_inputs, unioned, "ALL", scratch_ws=scratch)

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
    _core_fields = [
        (FIELD_MOBILITY, "TEXT"), (FIELD_SPEED, "FLOAT"),
        (FIELD_F1, "DOUBLE"), (FIELD_F2, "DOUBLE"), (FIELD_F3, "DOUBLE"),
        (FIELD_F4, "DOUBLE"), (FIELD_F5, "DOUBLE"), (FIELD_FHYDRO, "DOUBLE"),
    ]
    if enable_stochastic:
        _core_fields.append((FIELD_P_GO, "DOUBLE"))
    for fname, ftype in _core_fields:
        if ftype == "TEXT":
            arcpy.management.AddField(out_fc, fname, ftype, field_length=20)
        else:
            arcpy.management.AddField(out_fc, fname, ftype)

    # ── Resolve source attribute fields on the unioned FC ────────────────────
    soil_field  = _find_field(out_fc, ["soilType"])
    vti_field   = _find_field(out_fc, ["vegetationTrafficImpact", "VTI"])
    space_field = _find_field(out_fc, ["treeSpacing"])
    stem_field  = _find_field(out_fc, ["stemDiameter"])
    slope_field = None
    if slope_field_cfg:
        slope_field = _find_field(out_fc, [slope_field_cfg])
    if not slope_field:
        slope_field = _find_field(out_fc, _SLOPE_FIELD_CANDIDATES)

    arcpy.AddMessage(
        f"[Step 2] Source fields → soil={soil_field}, VTI={vti_field}, "
        f"spacing={space_field}, stem={stem_field}, "
        f"slope={slope_field} (units={slope_units})"
    )

    # ── Optional: spatial per-polygon moisture pre-pass (v0.49) ─────────────
   # When use_spatial_moisture=True, query Open-Meteo VWC at a 3×3 grid across
    # the AOI and assign a per-polygon moisture condition based on the nearest
    # sample point.  Result stored in a temporary _moist_zone TEXT field so the
    # main cursor can read it without repeating centroid projections.
    _moist_zone_field = None
    if use_spatial_moisture and _weather_mod is not None and extent_fc and arcpy.Exists(extent_fc):
        try:
            if hasattr(_weather_mod, "get_spatial_soil_moisture") and hasattr(_weather_mod, "moisture_vwc_to_condition"):
                desc_ext = arcpy.Describe(extent_fc)
                ext_bb = desc_ext.extent
                sr_wgs84 = arcpy.SpatialReference(4326)
                def _proj(x, y):
                    pt = arcpy.PointGeometry(arcpy.Point(x, y), desc_ext.spatialReference)
                    return pt.projectAs(sr_wgs84).centroid
                ll = _proj(ext_bb.XMin, ext_bb.YMin)
                ur = _proj(ext_bb.XMax, ext_bb.YMax)
                bbox = (ll.X, ll.Y, ur.X, ur.Y)
                moisture_grid = _weather_mod.get_spatial_soil_moisture(bbox, n_grid=3)
                if moisture_grid:
                    _moist_zone_field = "_moist_zone"
                    arcpy.management.AddField(out_fc, _moist_zone_field, "TEXT",
                                             field_length=10)
                    arcpy.management.CalculateField(
                        out_fc, _moist_zone_field, f'"{moisture}"', "PYTHON3"
                    )
                    sr_fc = arcpy.Describe(out_fc).spatialReference
                    with arcpy.da.UpdateCursor(
                        out_fc, ["SHAPE@CENTROID", _moist_zone_field]
                    ) as _pre:
                        for _row in _pre:
                            cx = _row[0].X
                            cy = _row[0].Y
                            _pt = arcpy.PointGeometry(
                                arcpy.Point(cx, cy), sr_fc
                            ).projectAs(sr_wgs84).centroid
                            best_d, best_cond = math.inf, moisture
                            for (glat, glon), vwc in moisture_grid.items():
                                d = math.hypot(glon - _pt.X, glat - _pt.Y)
                                if d < best_d:
                                    best_d = d
                                    best_cond = _weather_mod.moisture_vwc_to_condition(vwc)
                            _row[1] = best_cond
                            _pre.updateRow(_row)
                    arcpy.AddMessage(
                        f"[Step 2] Spatial moisture: {len(moisture_grid)} grid "
                        "samples applied (Open-Meteo VWC -> dry/moist/wet per polygon)."
                    )
        except Exception as _sm_exc:
            arcpy.AddWarning(f"[Step 2] Spatial moisture pre-pass failed ({_sm_exc}); "
                             "using global moisture setting.")
            _moist_zone_field = None

    cursor_fields = [
        FIELD_MOBILITY, FIELD_SPEED, FIELD_F1, FIELD_F2, FIELD_F3,
        FIELD_F4, FIELD_F5, FIELD_FHYDRO, water_flag_field,
        "SHAPE@AREA",   # v0.49: collect polygon area for Speed Made Good CDF
    ]
    if enable_stochastic:
        cursor_fields.append(FIELD_P_GO)
    if _moist_zone_field:
        cursor_fields.append(_moist_zone_field)

    src_fields = [soil_field, vti_field, space_field, stem_field, slope_field]
    cursor_fields += [f for f in src_fields if f]

    def _src_idx(field):
        if not field:
            return None
        return cursor_fields.index(field)

    i_soil, i_vti, i_space, i_stem, i_slope = (
        _src_idx(soil_field), _src_idx(vti_field), _src_idx(space_field),
        _src_idx(stem_field), _src_idx(slope_field),
    )
    i_water    = cursor_fields.index(water_flag_field)
    i_area     = cursor_fields.index("SHAPE@AREA")
    i_p_go     = cursor_fields.index(FIELD_P_GO) if enable_stochastic else None
    i_mz       = cursor_fields.index(_moist_zone_field) if _moist_zone_field else None

    n_go = n_restricted = n_nogo = 0
    speed_area_pairs = []

    with arcpy.da.UpdateCursor(out_fc, cursor_fields) as cur:
        for row in cur:
            soil_code  = row[i_soil]  if i_soil  is not None else None
            vti        = row[i_vti]   if i_vti   is not None else None
            spacing    = row[i_space] if i_space is not None else None
            stem       = row[i_stem]  if i_stem  is not None else None
            slope      = row[i_slope] if i_slope is not None else None
            in_water   = bool(row[i_water])
            poly_area  = row[i_area]  or 0.0
            poly_moist = (row[i_mz] if i_mz is not None else None) or moisture

            slope_pct = _slope_to_percent(slope, slope_units)
            f1 = slope_factor(slope_pct, veh.max_off_road_grad)
            f2 = veg_density_factor(vti)
            f3 = veg_spacing_factor(spacing, stem, veh.vehicle_width_m,
                                    veh.max_override_diameter_m)
            f4 = soil_factor(soil_code, "dry",  veh.vci_1, veh.vci_50, rci_table)
            f5 = soil_factor(soil_code, "wet",  veh.vci_1, veh.vci_50, rci_table)
            f_soil_active = soil_factor(soil_code, poly_moist,
                                        veh.vci_1, veh.vci_50, rci_table)
            fh = hydro_factor(in_water)

            speed = combine_speed(veh.max_road_spd_kph, f1, f2, f3, f4, f5, fh,
                                  poly_moist, soil_active=f_soil_active)
            mob   = classify_mobility(speed, veh.max_road_spd_kph, go_threshold)

            row[0] = mob
            row[1] = speed
            row[2], row[3], row[4] = f1, f2, f3
            row[5], row[6], row[7] = f4, f5, fh

            if enable_stochastic and i_p_go is not None:
                p_go = compute_stochastic_go(
                    soil_code, poly_moist, veh.vci_1, veh.vci_50,
                    slope_pct, veh.max_off_road_grad,
                    rci_table=rci_table, n_trials=stochastic_trials,
                )
                row[i_p_go] = p_go

            cur.updateRow(row)
            speed_area_pairs.append((speed, poly_area))

            if   mob == MOB_GO:         n_go += 1
            elif mob == MOB_RESTRICTED: n_restricted += 1
            else:                       n_nogo += 1

    # Clean up temporary flag fields
    for _tmp_fld in [water_flag_field, _moist_zone_field]:
        if _tmp_fld:
            try:
                arcpy.management.DeleteField(out_fc, _tmp_fld)
            except Exception:
                pass

    # ── v0.49 — Speed Made Good (SMG) doctrinal area-weighted summary ─────────
    smg = compute_speed_made_good(
        speed_area_pairs, go_threshold=go_threshold,
        max_road_spd_kph=veh.max_road_spd_kph
    )
    mmp_display = compute_mmp_estimate(veh.vci_50, veh.locomotion_type)

    # ── Completion summary ────────────────────────────────────────────────────
    total = n_go + n_restricted + n_nogo
    _BAR_WIDTH = 30

    def _bar(count, total, char):
        filled = round(_BAR_WIDTH * count / total) if total > 0 else 0
        return char * filled + "." * (_BAR_WIDTH - filled)

    pct_go   = 100.0 * n_go         / total if total else 0
    pct_res  = 100.0 * n_restricted / total if total else 0
    pct_nogo = 100.0 * n_nogo       / total if total else 0

    arcpy.AddMessage("=" * 62)
    arcpy.AddMessage(f"  STEP 2 COMPLETE — Mobility Surface: {vehicle_name}  [{moisture}]")
    arcpy.AddMessage("=" * 62)
    arcpy.AddMessage(f"  Output      : {out_fc}")
    arcpy.AddMessage("  Speed model : min-of-factors (NG-NRMM doctrine)")
    if mmp_display:
        arcpy.AddMessage(
            f"  Vehicle MMP : {mmp_display:.0f} kPa  "
            f"(VCI_50={veh.vci_50}, "
            f"{'tracked' if veh.locomotion_type else 'wheeled'})"
        )
    arcpy.AddMessage(f"  Polygons    : {total:,}")
    arcpy.AddMessage(f"  GO          [{_bar(n_go,         total, '#')}] {n_go:>7,}  ({pct_go:5.1f}%)")
    arcpy.AddMessage(f"  RESTRICTED  [{_bar(n_restricted, total, '+')}] {n_restricted:>7,}  ({pct_res:5.1f}%)")
    arcpy.AddMessage(f"  NO GO       [{_bar(n_nogo,       total, '-')}] {n_nogo:>7,}  ({pct_nogo:5.1f}%)")
    arcpy.AddMessage("-" * 62)
    arcpy.AddMessage("  NG-NRMM SPEED MADE GOOD (area-weighted):")
    arcpy.AddMessage(f"  %NOGO by area  : {smg['pct_nogo']:5.1f}%  "
                     f"({smg['nogo_area_m2'] / 1e6:.3f} km2)")
    arcpy.AddMessage(f"  Mean speed     : {smg['mean_speed_kmh']:.1f} km/h  (mobile terrain)")
    arcpy.AddMessage(f"  Median speed   : {smg['median_speed_kmh']:.1f} km/h")
    if smg['cdf']:
        arcpy.AddMessage("  SMG CDF (speed -> % area achievable at >= that speed):")
        step = max(1, len(smg['cdf']) // 5)
        for spd, pct in smg['cdf'][::step]:
            bar = "#" * int(pct / 5) + "." * (20 - int(pct / 5))
            arcpy.AddMessage(f"    {spd:5.1f} km/h  [{bar}]  {pct:5.1f}%")
    if enable_stochastic:
        arcpy.AddMessage(
            f"  Stochastic P(GO): written to {FIELD_P_GO} "
            f"({stochastic_trials} trials/polygon)."
        )
    arcpy.AddMessage("=" * 62)
    arcpy.AddMessage("  >>> Open Step 3 for Reason Map, Isochrone, or Route analysis.")
    arcpy.AddMessage("=" * 62)

    # ── Register the result in the project config so Step 3 auto-fills ───────
    last_vehicles = cfg.get("last_vehicles") or []
    if vehicle_name not in last_vehicles:
        last_vehicles.append(vehicle_name)
    _cfg_mod.save_config(
        project_folder,
        mobility_map_fc   = out_fc,
        last_run_output   = out_fc,
        last_vehicles     = last_vehicles,
        moisture_default  = moisture,
        moisture_scenario = moisture_scenario or "Live Weather",
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
            "the input for every Step 3 analysis.\n\n"
            "v0.49: speed model changed to min-of-factors (NG-NRMM doctrine); "
            "Speed Made Good area-weighted CDF + %NOGO logged; MMP estimate "
            "shown in summary; optional stochastic P(GO) field (Monte Carlo); "
            "optional spatial per-polygon moisture (Open-Meteo grid)."
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
                        "over live weather and scenario]",
            name="rainfall_override_mm",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input",
            category="Weather",
        )

        p_scenario = arcpy.Parameter(
            displayName="Antecedent Moisture Scenario",
            name="moisture_scenario",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
            category="Weather",
        )
        p_scenario.filter.type = "ValueList"
        _scen_names = ["Live Weather", "Summer Dry Baseline",
                       "3-Day Continuous Rainfall",
                       "Spring Thaw / Freeze-Thaw Cycle"]
        if _weather_mod is not None and hasattr(_weather_mod, "SCENARIO_NAMES"):
            _scen_names = _weather_mod.SCENARIO_NAMES
        p_scenario.filter.list = _scen_names
        p_scenario.value = "Live Weather"

        p_spatial_moist = arcpy.Parameter(
            displayName="Use Spatial Soil Moisture  (3x3 Open-Meteo grid, "
                        "per-polygon moisture conditions)",
            name="use_spatial_moisture",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input",
            category="Weather",
        )
        p_spatial_moist.value = False

        p_stochastic = arcpy.Parameter(
            displayName="Enable Stochastic P(GO)  (Monte Carlo, writes P_GO field)",
            name="enable_stochastic",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input",
            category="Advanced",
        )
        p_stochastic.value = False

        p_trials = arcpy.Parameter(
            displayName="Monte Carlo Trials  (stochastic mode)",
            name="stochastic_trials",
            datatype="GPLong",
            parameterType="Optional",
            direction="Input",
            category="Advanced",
        )
        p_trials.value = 200

        p_out = arcpy.Parameter(
            displayName="Output Speed Surface  (set automatically in project GDB)",
            name="output_fc",
            datatype="DEFeatureClass",
            parameterType="Derived",
            direction="Output",
        )
        # v0.50.0: apply the CCM mobility symbology automatically when ArcGIS
        # Pro adds the derived output to the map (previously the speed surface
        # appeared with random default symbology).
        try:
            _here = os.path.dirname(os.path.abspath(__file__))
            for _ln in ("Mobility_Symbology_Final.lyrx", "Mobility_Symbology.lyrx"):
                _lyrx = os.path.join(_here, "Symbology", _ln)
                if os.path.exists(_lyrx):
                    p_out.symbology = _lyrx
                    break
        except Exception:
            pass
        # indices: 0=folder, 1=vehicle, 2=moisture, 3=thresh,
        #          4=weather, 5=rain, 6=scenario, 7=spatial_moist,
        #          8=stochastic, 9=trials, 10=out
        return [p_folder, p_vehicle, p_moisture, p_thresh,
                p_weather, p_rain, p_scenario, p_spatial_moist,
                p_stochastic, p_trials, p_out]

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        p_folder, p_vehicle, p_moisture = parameters[0], parameters[1], parameters[2]
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
        p_folder  = parameters[0]
        p_thresh  = parameters[3]
        p_rain    = parameters[5]
        p_trials  = parameters[9]

        if p_folder.value:
            cfg_path = os.path.join(str(p_folder.valueAsText), "ccm_project.json")
            if not os.path.isfile(cfg_path):
                p_folder.setErrorMessage(
                    "No ccm_project.json found in this folder.\n\n"
                    "Run Step 1 (Project Setup & Pre-process) first to create the "
                    "project configuration, then return here.\n"
                    "The config file is written to the Project Output Folder you "
                    "specified in Step 1."
                )
            else:
                # Warn if key layers are missing from the config
                if _cfg_mod:
                    try:
                        cfg = _cfg_mod.load_config(p_folder.valueAsText)
                        missing_layers = []
                        if not cfg.get("soil_fc"):
                            missing_layers.append("Soil FC (soil bearing-capacity factors F4/F5 will be 1.0)")
                        if not cfg.get("veg_fc"):
                            missing_layers.append("Vegetation FC (F2 density + F3 spacing will be 1.0)")
                        if not cfg.get("slope_fc") and not cfg.get("dem_path"):
                            missing_layers.append("Slope data (F1 slope factor will be 1.0 — flat terrain assumed)")
                        if missing_layers:
                            p_folder.setWarningMessage(
                                "Project config loaded but some layers are missing:\n"
                                + "\n".join(f"  • {m}" for m in missing_layers)
                                + "\n\nMissing layers default to factor = 1.0 (no penalty). "
                                "Re-run Step 1 with the missing layers to include "
                                "them in the analysis."
                            )
                    except Exception:
                        pass

        if p_thresh.value is not None:
            try:
                if float(p_thresh.value) < 0:
                    p_thresh.setErrorMessage("GO Threshold must be \u2265 0 km/h.")
            except (TypeError, ValueError):
                p_thresh.setErrorMessage("GO Threshold must be a number.")

        if p_rain.value is not None:
            try:
                if float(p_rain.value) < 0:
                    p_rain.setErrorMessage("Rainfall override must be \u2265 0 mm/hr.")
            except (TypeError, ValueError):
                p_rain.setErrorMessage("Rainfall override must be a number.")

        if p_trials.value is not None:
            try:
                if int(p_trials.value) < 1:
                    p_trials.setErrorMessage("Monte Carlo trials must be \u2265 1.")
            except (TypeError, ValueError):
                p_trials.setErrorMessage("Monte Carlo trials must be an integer.")

    def execute(self, parameters, messages):
        arcpy.SetLogMetadata(False)

        project_folder    = parameters[0].valueAsText
        vehicle_name      = parameters[1].valueAsText
        moisture          = parameters[2].valueAsText
        go_threshold      = parameters[3].value
        use_live_weather  = bool(parameters[4].value)
        rainfall_override = parameters[5].value
        moisture_scenario = parameters[6].valueAsText
        use_spatial_moist = bool(parameters[7].value)
        enable_stochastic = bool(parameters[8].value)
        stochastic_trials = int(parameters[9].value or 200)

        if go_threshold is None:
            go_threshold = DEFAULT_GO_THRESHOLD_KMH

        arcpy.AddMessage(
            f"\n{'='*60}\n"
            f"  Step 2 \u2014 Generate Mobility Map\n"
            f"  Vehicle : {vehicle_name}\n"
            f"  Moisture: {moisture}\n"
            f"{'='*60}"
        )

        try:
            out_fc = build_speed_surface(
                project_folder       = project_folder,
                vehicle_name         = vehicle_name,
                moisture             = moisture,
                go_threshold         = float(go_threshold),
                use_live_weather     = use_live_weather,
                rainfall_override_mm = (float(rainfall_override)
                                        if rainfall_override is not None else None),
                moisture_scenario    = moisture_scenario,
                enable_stochastic    = enable_stochastic,
                stochastic_trials    = stochastic_trials,
                use_spatial_moisture = use_spatial_moist,
                messages             = messages,
            )
            parameters[10].value = out_fc
            arcpy.AddMessage(f"[Step 2] Speed surface created \u2192 {out_fc}")
        except Exception as exc:
            arcpy.AddError(f"[Step 2] Mobility map generation failed: {exc}")
            raise

# <<< END OF FILE >>>
