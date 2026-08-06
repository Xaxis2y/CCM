# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
ccm_weather.py
==============
CCM Tool — Pillar 4: Live Weather Integration
---------------------------------------------
Connects to real-time rainfall data and adjusts soil RCI (Rating Cone Index)
values based on current precipitation, because wet ground is softer and less
trafficable than dry ground.

Data Sources
------------
  Primary  : ArcGIS Living Atlas — "Current Weather and Wind Station Data"
             Feature service URL (public, no token required):
             https://services9.arcgis.com/RHVPKKiFTONKtxq3/arcgis/rest/services/
               NOAA_METAR_current_wind_speed_direction_v1/FeatureServer/0

  Fallback : Open-Meteo (free, no API key, worldwide coverage)
             https://api.open-meteo.com/v1/forecast

Usage (inside ArcGIS Pro toolbox or standalone)
-----------------------------------------------
    from ccm_weather import get_rainfall_mm, adjust_rci_for_rainfall

    # Step 1 — get the latest hourly rainfall at a location
    rainfall_mm = get_rainfall_mm(lat=45.42, lon=-75.69)   # Ottawa, ON

    # Step 2 — apply the rainfall penalty to a soil RCI dict
    adjusted = adjust_rci_for_rainfall(rci_dict, rainfall_mm)

    # Step 3 — use adjusted RCI values in the CCM model instead of the defaults

Rainfall → RCI Adjustment Model
---------------------------------
  Source: NATO STANAG 4234 / US Army FM 5-170 trafficability guidelines

  The model applies a multiplicative penalty to RCI values:
    factor = 1.0                      # no rain
    factor = 0.90   @ ≥ 2 mm/hr      # light rain  — slightly softer
    factor = 0.75   @ ≥ 10 mm/hr     # moderate rain
    factor = 0.55   @ ≥ 25 mm/hr     # heavy rain
    factor = 0.35   @ ≥ 50 mm/hr     # very heavy / storm

  Fine-grained soils (clay, silt, organic) are penalised more aggressively
  than coarse soils (gravel, rock) via per-soil-class multipliers.

Dependencies
------------
    - arcpy     (optional — only for ArcGIS Living Atlas query)
    - urllib    (standard library)
    - json      (standard library)
    - math      (standard library)
"""

VERSION = "0.55.1"  # v0.55.1 -- version bump only: added QUICK_START.html and CCM_anaconda_environment.bat (Anaconda Prompt environment setup script); no code/logic changes. See CHANGELOG_v0.55.md.
# v0.49 — Spatial soil moisture grid: get_spatial_soil_moisture() queries
#          Open-Meteo VWC at an n×n grid across the AOI; moisture_vwc_to_condition()
#          maps VWC to dry/moist/wet.  Wired into Step 2 via use_spatial_moisture flag.
#          See SECTION 5 for full notes and SMAP substitution guidance.
# v0.48 — Version bump for the toolbox-wide v0.48.0 release.
# v0.46+ — New: ANTECEDENT_SCENARIOS presets (Spring Thaw, 3-Day Rainfall,
#           Summer Dry) and antecedent_multiplier param in adjust_rci_for_rainfall()
#           for strategic beyond-live-weather scenario planning.
# v0.46 — Bug fixes:
#          1. _query_living_atlas: distance formula now latitude-corrected —
#             longitude degree length shrinks with cos(lat); old formula was
#             accurate only at the equator.
#          2. test_factor_never_below_0_1: assertion now checks the computed
#             factor directly (>= 0.10) instead of an incorrect absolute-value
#             comparison against 9% of the original RCI value.
#          3. VERSION bumped to align with full toolbox release.

import json
import math
import urllib.request
import urllib.error
from typing import Optional

# ---------------------------------------------------------------------------
# SECTION 1 — RAINFALL THRESHOLDS & RCI PENALTY FACTORS
# ---------------------------------------------------------------------------

# (min_mm_per_hour, rci_factor)  — sorted ascending by threshold
RAINFALL_THRESHOLDS = [
    (0.0,   1.00),   # Dry / trace
    (2.0,   0.90),   # Light rain
    (10.0,  0.75),   # Moderate rain
    (25.0,  0.55),   # Heavy rain
    (50.0,  0.35),   # Very heavy / storm
]

# Per-soil-class sensitivity multipliers.
# Fine / cohesive soils are more sensitive to rainfall than coarse soils.
# Applied as:  final_factor = base_factor * soil_sensitivity
SOIL_SENSITIVITY = {
    # Very sensitive — fine-grained cohesive soils
    "fatClay":             0.80,
    "leanClay":            0.82,
    "organicClay":         0.78,
    "organicSiltandClay":  0.76,
    "peat":                0.70,
    "micaceous":           0.85,
    # Moderately sensitive — silts and mixed soils
    "siltAndFineSand":     0.88,
    "siltFineSandLeanClay":0.85,
    "clayeySand":          0.87,
    "siltySand":           0.90,
    "siltyGravelSand":     0.92,
    "clayeyGravel":        0.90,
    # Low sensitivity — coarse soils
    "wellGradedSand":      0.95,
    "poorlyGradedSand":    0.97,
    "wellGradedGravel":    0.98,
    "poorlyGradedGravel":  0.99,
    # Insensitive — rock / evaporite
    "rock":                1.00,
    "evaporite":           1.00,
    "notEvaluated":        1.00,
}

_DEFAULT_SENSITIVITY = 0.88   # fallback for unrecognised soil types


# ---------------------------------------------------------------------------
# SECTION 1b — ANTECEDENT MOISTURE SCENARIOS
# ---------------------------------------------------------------------------
# Presets for strategic planning when a single hourly METAR reading is
# insufficient.  Each scenario combines a simulated rainfall-equivalent
# (mm/hr) — representing the soil moisture state — with an antecedent
# multiplier that amplifies the rain_penalty beyond what the instantaneous
# rate alone would imply.
#
# How the multiplier works:
#   rain_penalty = 1.0 - base_rainfall_factor(rainfall_mm_equiv)
#   effective_penalty = rain_penalty * antecedent_multiplier
#   per-soil factor = 1.0 - effective_penalty * (2.0 - soil_sensitivity)
#
# A multiplier of 1.0 (default) is identical to the standard live-weather
# path.  Values > 1.0 represent accumulated saturation that exceeds what
# the instantaneous rate alone would produce.
#
# Penalty derivations (lean clay, sensitivity=0.82):
#   Summer Dry Baseline      : 0 mm, ×1.00  → factor ≈ 1.00  (no penalty)
#   3-Day Continuous Rainfall: 10 mm, ×1.40 → factor ≈ 0.59  (41% RCI loss)
#   Spring Thaw              : 25 mm, ×1.50 → factor ≈ 0.20  (80% RCI loss)
#
# Source: NATO STANAG 4234 Table B-3, FM 5-170 soil moisture conditioning.

ANTECEDENT_SCENARIOS = {
    "Live Weather": {
        "description": (
            "Fetch real-time METAR/Open-Meteo rainfall for the AOI centroid "
            "and apply standard instantaneous penalty (default)."
        ),
        "rainfall_mm_equiv":    None,   # None = fetch live data
        "antecedent_multiplier": 1.00,
    },
    "Summer Dry Baseline": {
        "description": (
            "Dry-season conditions; soil at or below field capacity. "
            "Equivalent to no rainfall — standard tabulated RCI values used."
        ),
        "rainfall_mm_equiv":    0.0,
        "antecedent_multiplier": 1.00,
    },
    "3-Day Continuous Rainfall": {
        "description": (
            "72+ hours of sustained precipitation; soil at or near saturation. "
            "Cohesive soils (clay, silt, peat) will be severely degraded."
        ),
        "rainfall_mm_equiv":    10.0,   # moderate sustained rain
        "antecedent_multiplier": 1.40,  # 40% extra penalty for saturation
    },
    "Spring Thaw / Freeze-Thaw Cycle": {
        "description": (
            "Active thaw period (해빙기): near-surface soils waterlogged, "
            "sub-surface layer still frozen.  Worst-case for cohesive soils. "
            "RCI of fine-grained soils may fall to ≤20% of tabulated dry values."
        ),
        "rainfall_mm_equiv":    25.0,   # heavy-rain equivalent soil moisture
        "antecedent_multiplier": 1.50,  # 50% extra — thaw is more severe than rain
    },
}

# Ordered list for UI dropdowns (preserves insertion order, Python 3.7+)
SCENARIO_NAMES = list(ANTECEDENT_SCENARIOS.keys())


# ---------------------------------------------------------------------------
# SECTION 2 — RAINFALL RETRIEVAL
# ---------------------------------------------------------------------------

# ArcGIS Living Atlas METAR service (public)
_LIVING_ATLAS_URL = (
    "https://services9.arcgis.com/RHVPKKiFTONKtxq3/arcgis/rest/services/"
    "NOAA_METAR_current_wind_speed_direction_v1/FeatureServer/0/query"
)

# Open-Meteo free weather API (fallback, no key required)
_OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


def _query_living_atlas(lat: float, lon: float, radius_km: float = 100) -> Optional[float]:
    """
    Query the ArcGIS Living Atlas METAR service for the nearest weather station
    within *radius_km* of (lat, lon) and return its precipitation (mm/hr).

    Returns None if the service is unreachable or no stations are found.
    """
    try:
        # Build geometry filter — a rough bounding box
        deg_offset = radius_km / 111.0
        xmin = lon - deg_offset
        ymin = lat - deg_offset
        xmax = lon + deg_offset
        ymax = lat + deg_offset

        params = {
            "where":         "1=1",
            "geometry":      f"{xmin},{ymin},{xmax},{ymax}",
            "geometryType":  "esriGeometryEnvelope",
            "inSR":          "4326",
            "outFields":     "STATION_NAME,TEMP,WIND_SPEED,PRECIP",
            "returnGeometry":"false",
            "orderByFields": "",
            "f":             "json",
        }
        query_str = "&".join(f"{k}={urllib.request.quote(str(v))}" for k, v in params.items())
        url = f"{_LIVING_ATLAS_URL}?{query_str}"

        with urllib.request.urlopen(url, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        features = data.get("features", [])
        if not features:
            return None

        # Find the nearest station with a PRECIP value
        best_precip = None
        best_dist   = math.inf

        for feat in features:
            attrs = feat.get("attributes", {})
            precip = attrs.get("PRECIP")
            if precip is None:
                continue
            # Distance (approximate, degrees → km)
            geom  = feat.get("geometry", {})
            fx, fy = geom.get("x", lon), geom.get("y", lat)
            dist  = math.hypot((fx - lon) * 111.0 * math.cos(math.radians(lat)),
                               (fy - lat) * 111.0)
            if dist < best_dist:
                best_dist   = dist
                best_precip = float(precip)

        return best_precip

    except Exception:
        return None


def _query_open_meteo(lat: float, lon: float) -> Optional[float]:
    """
    Query the Open-Meteo free API for the current hourly precipitation at
    (lat, lon).  Returns mm/hr or None on failure.

    Open-Meteo is used as a fallback when Living Atlas is unavailable.
    """
    try:
        params = (
            f"latitude={lat}&longitude={lon}"
            "&hourly=precipitation"
            "&forecast_days=1"
            "&timezone=UTC"
        )
        url = f"{_OPEN_METEO_URL}?{params}"

        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        hourly = data.get("hourly", {})
        precip_list = hourly.get("precipitation", [])

        # Return the most recent non-null hourly value
        for val in reversed(precip_list):
            if val is not None:
                return float(val)
        return 0.0

    except Exception:
        return None


def get_rainfall_mm(
    lat: float,
    lon: float,
    prefer_living_atlas: bool = True,
) -> dict:
    """
    Retrieve the current hourly precipitation (mm/hr) for a given location.

    Parameters
    ----------
    lat, lon : float
        WGS84 decimal degrees.
    prefer_living_atlas : bool
        Try the ArcGIS Living Atlas METAR service first (default True).
        Falls back to Open-Meteo automatically.

    Returns
    -------
    dict with keys:
        "rainfall_mm"  : float  — precipitation in mm/hr (0.0 if none detected)
        "source"       : str    — "living_atlas", "open_meteo", or "unavailable"
        "message"      : str    — human-readable status description
    """
    rainfall_mm: Optional[float] = None
    source = "unavailable"
    message = "No weather data retrieved."

    if prefer_living_atlas:
        rainfall_mm = _query_living_atlas(lat, lon)
        if rainfall_mm is not None:
            source  = "living_atlas"
            message = (
                f"Live rainfall from ArcGIS Living Atlas METAR: "
                f"{rainfall_mm:.1f} mm/hr at ({lat:.4f}, {lon:.4f})."
            )

    if rainfall_mm is None:
        rainfall_mm = _query_open_meteo(lat, lon)
        if rainfall_mm is not None:
            source  = "open_meteo"
            message = (
                f"Live rainfall from Open-Meteo: "
                f"{rainfall_mm:.1f} mm/hr at ({lat:.4f}, {lon:.4f})."
            )

    if rainfall_mm is None:
        rainfall_mm = 0.0
        source  = "unavailable"
        message = (
            "WARNING: Could not retrieve live weather data. "
            "Using dry-condition RCI values (no rainfall adjustment). "
            "Check your internet connection or use manual override."
        )

    return {
        "rainfall_mm": rainfall_mm,
        "source":      source,
        "message":     message,
    }


# ---------------------------------------------------------------------------
# SECTION 3 — RCI ADJUSTMENT
# ---------------------------------------------------------------------------

def _base_rainfall_factor(rainfall_mm: float) -> float:
    """
    Return the base RCI penalty factor for a given rainfall rate.
    Interpolates linearly between threshold levels.
    """
    if rainfall_mm <= 0.0:
        return 1.00

    # Find the bracket this rainfall falls in
    for i in range(len(RAINFALL_THRESHOLDS) - 1):
        lo_mm, lo_f = RAINFALL_THRESHOLDS[i]
        hi_mm, hi_f = RAINFALL_THRESHOLDS[i + 1]
        if lo_mm <= rainfall_mm < hi_mm:
            t = (rainfall_mm - lo_mm) / (hi_mm - lo_mm)
            return lo_f + t * (hi_f - lo_f)

    # Beyond the last threshold — clamp to the lowest factor
    return RAINFALL_THRESHOLDS[-1][1]


def adjust_rci_for_rainfall(
    rci_dict: dict,
    rainfall_mm: float,
    manual_override: Optional[float] = None,
    antecedent_multiplier: float = 1.0,
) -> dict:
    """
    Apply a rainfall penalty to an RCI soil dictionary.

    Parameters
    ----------
    rci_dict : dict
        Dictionary mapping soil type keys to (dry_rci, moist_rci, wet_rci)
        tuples or similar numeric values.  The structure matches the
        ``rci_soils_dict`` used internally in CCM_Tool_V1.pyt.
    rainfall_mm : float
        Current rainfall in mm/hr (from get_rainfall_mm()).
    manual_override : float, optional
        If supplied, this factor (0.0–1.0) overrides all calculated factors.
        Useful for field commanders who know local conditions better than
        automated weather data.
    antecedent_multiplier : float, optional
        Amplifies the rain_penalty beyond the instantaneous rate to account
        for accumulated ground saturation.  1.0 = standard (default).
        Values > 1.0 represent historical moisture load (e.g. spring thaw,
        multi-day rainfall).  Set by ANTECEDENT_SCENARIOS presets.
        Has no effect when base_factor = 1.0 (no rain) or manual_override
        is supplied.

    Returns
    -------
    dict
        New RCI dictionary with adjusted values.  Original dict is unchanged.

    Notes
    -----
    The adjustment is applied to ALL moisture conditions (dry, moist, wet)
    because even "wet" tabulated values assume standard field conditions,
    not active precipitation on the current day.
    """
    base_factor = _base_rainfall_factor(rainfall_mm)
    _antecedent = max(1.0, float(antecedent_multiplier))  # clamp to ≥ 1.0

    # Soils that are completely immune to rainfall — always full strength.
    # Rock and evaporite have stable bearing capacity regardless of precipitation.
    _IMMUNE_SOILS = {"rock", "evaporite", "notEvaluated"}

    adjusted = {}
    for soil_key, rci_values in rci_dict.items():
        sensitivity = SOIL_SENSITIVITY.get(soil_key, _DEFAULT_SENSITIVITY)

        if manual_override is not None:
            factor = float(manual_override)
        elif soil_key in _IMMUNE_SOILS:
            # Rock / evaporite: rainfall has no effect on bearing capacity
            factor = 1.0
        elif base_factor >= 1.0:
            # No rain detected — no penalty for any soil
            factor = 1.0
        else:
            # Rain is present.  Apply penalty scaled by soil sensitivity
            # and the antecedent multiplier (accumulated ground saturation).
            #
            # Formula:  factor = 1.0 - effective_penalty × (2.0 - sensitivity)
            #   effective_penalty = (1.0 - base_factor) × antecedent_multiplier
            #
            # Derivation:
            #   base_factor ≈ 0.75 at 10 mm/hr → rain_penalty = 0.25
            #   antecedent_multiplier=1.40 (3-day rain) → eff. penalty = 0.35
            #   sensitivity ≈ 1.0 for coarse soils (barely affected)
            #   sensitivity ≈ 0.70 for fine soils (most affected)
            #   (2.0 - sensitivity) amplifies the penalty for sensitive soils:
            #     gravel (0.98) → ×1.02  →  barely more than base penalty
            #     clay   (0.82) → ×1.18  →  18% more penalty than base
            #     peat   (0.70) → ×1.30  →  30% more penalty than base
            #
            # Boundary checks:
            #   No rain (base_factor=1.0) → factor = 1.0 ✓
            #   Rock (immune, handled above) → factor = 1.0 ✓
            rain_penalty = (1.0 - base_factor) * _antecedent
            factor = 1.0 - rain_penalty * (2.0 - sensitivity)
            # Clamp: never reduce RCI by more than 90%; never exceed 1.0
            factor = max(0.10, min(1.00, factor))

        # Handle both tuple/list values and plain numeric values
        if isinstance(rci_values, (list, tuple)):
            adjusted[soil_key] = tuple(
                round(v * factor, 1) if v is not None else None
                for v in rci_values
            )
        elif isinstance(rci_values, (int, float)) and rci_values is not None:
            adjusted[soil_key] = round(rci_values * factor, 1)
        else:
            adjusted[soil_key] = rci_values  # pass through None / unknown types

    return adjusted


def apply_antecedent_scenario(rci_dict: dict, scenario_name: str) -> dict:
    """
    Apply a named antecedent moisture scenario to an RCI dictionary.

    Convenience wrapper around adjust_rci_for_rainfall() that looks up the
    rainfall_mm_equiv and antecedent_multiplier from ANTECEDENT_SCENARIOS.
    Intended for use by Step 2 when the analyst selects a strategic scenario
    rather than (or in addition to) live weather data.

    Parameters
    ----------
    rci_dict : dict
        USCS-keyed RCI table in ccm_weather sensitivity-key format.
    scenario_name : str
        One of SCENARIO_NAMES.  Unknown names fall back to "Live Weather"
        (i.e. no penalty — caller should fetch live data separately).

    Returns
    -------
    dict — adjusted RCI table.
    """
    preset = ANTECEDENT_SCENARIOS.get(scenario_name)
    if preset is None or preset.get("rainfall_mm_equiv") is None:
        # "Live Weather" or unrecognised — return unchanged (caller handles live fetch)
        return dict(rci_dict)
    rainfall_mm = float(preset["rainfall_mm_equiv"])
    multiplier  = float(preset.get("antecedent_multiplier", 1.0))
    return adjust_rci_for_rainfall(
        rci_dict, rainfall_mm, antecedent_multiplier=multiplier
    )


def get_area_centroid(extent_fc: str) -> tuple:
    """
    Return the (lat, lon) centroid of an ArcGIS extent polygon feature class
    in WGS84 decimal degrees.

    Parameters
    ----------
    extent_fc : str
        Path to the extent / AOI polygon feature class.

    Returns
    -------
    (lat, lon) tuple of floats.
    """
    try:
        import arcpy
        desc = arcpy.Describe(extent_fc)
        ext  = desc.extent
        sr_wgs84 = arcpy.SpatialReference(4326)

        # Project the centroid point to WGS84 for weather lookup
        cx = (ext.XMin + ext.XMax) / 2.0
        cy = (ext.YMin + ext.YMax) / 2.0
        pt = arcpy.PointGeometry(
            arcpy.Point(cx, cy),
            desc.spatialReference
        )
        pt_wgs84 = pt.projectAs(sr_wgs84)
        return (pt_wgs84.centroid.Y, pt_wgs84.centroid.X)

    except Exception:
        # Fallback: assume already in WGS84
        desc = __import__("arcpy").Describe(extent_fc)
        ext  = desc.extent
        cx   = (ext.XMin + ext.XMax) / 2.0
        cy   = (ext.YMin + ext.YMax) / 2.0
        return (cy, cx)


# ---------------------------------------------------------------------------
# SECTION 4 — NOTES
# --------------------------------------------------------------------------------------------
# Weather integration is consumed directly
#   build_speed_surface() calls get_rainfall_for_extent() -> get_rainfall_mm()
#   -> adjust_rci_for_rainfall() / apply_antecedent_scenario() as needed.
# No separate toolbox-helper shim is required here.


# ---------------------------------------------------------------------------
# SECTION 5 — SPATIAL SOIL MOISTURE  (v0.49 / NG-NRMM upgrade)
# ---------------------------------------------------------------------------
# Replaces the single centroid rainfall reading with a spatial grid of soil
# moisture values.  Each grid point is queried via Open-Meteo's hourly ERA5
# soil moisture product (free, no API key, global coverage, ~9 km resolution).
#
# SMAP substitution note: replace _query_open_meteo_soil() with a SMAP L4
# OPeNDAP client when NASA Earthdata credentials are available.  SMAP L4
# provides 3-hourly, 9 km, global soil moisture with a freeze/thaw product
# that maps directly onto the Spring Thaw antecedent scenario.
#
# VWC thresholds (USDA Soil Science, conservative for mobility modelling):
#   < 0.15 m3/m3 -- dry   (below wilting point for most soils)
#   0.15-0.30    -- moist (between wilting point and field capacity)
#   >= 0.30      -- wet   (at or above field capacity; trafficability degrades)

_VWC_DRY_THRESHOLD   = 0.15   # m3/m3
_VWC_MOIST_THRESHOLD = 0.30   # m3/m3


def moisture_vwc_to_condition(vwc: Optional[float]) -> str:
    """
    Convert volumetric water content (m3/m3) to "dry", "moist", or "wet".

    Thresholds are conservative (wet-biased) for mobility modelling.
    Returns "moist" for None/unknown VWC (neutral fallback).
    """
    if vwc is None:
        return "moist"
    v = float(vwc)
    if v < _VWC_DRY_THRESHOLD:
        return "dry"
    if v < _VWC_MOIST_THRESHOLD:
        return "moist"
    return "wet"


def _query_open_meteo_soil(lat: float, lon: float) -> Optional[float]:
    """
    Query Open-Meteo for the most recent hourly soil moisture (0-7 cm layer)
    at (lat, lon).  Returns VWC in m3/m3, or None on failure.

    Uses the ERA5-based reanalysis product (~9 km resolution, hourly, global,
    no API key required).

    SMAP substitution: replace this function with a SMAP L4 OPeNDAP query
    when NASA Earthdata credentials are available.
    """
    try:
        params = (
            f"latitude={lat:.5f}&longitude={lon:.5f}"
            "&hourly=soil_moisture_0_to_7cm"
            "&forecast_days=1"
            "&timezone=UTC"
        )
        url = f"{_OPEN_METEO_URL}?{params}"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        sm_list = data.get("hourly", {}).get("soil_moisture_0_to_7cm", [])
        for val in reversed(sm_list):
            if val is not None:
                return float(val)
        return None
    except Exception:
        return None


def get_spatial_soil_moisture(
    bbox_wgs84: tuple,
    n_grid: int = 3,
) -> dict:
    """
    Query Open-Meteo soil moisture at an n x n grid across the AOI.

    Parameters
    ----------
    bbox_wgs84 : (xmin, ymin, xmax, ymax) in WGS84 decimal degrees.
    n_grid     : grid dimension (default 3 -> 3x3 = 9 sample points).

    Returns
    -------
    dict {(lat, lon): vwc_m3_m3}  -- volumetric water content per point.
    Empty dict on total failure.

    Notes
    -----
    Each grid point requires one HTTP request (~0.3 s).
    3x3 grid => ~3 s; 5x5 => ~8 s.
    Pair with moisture_vwc_to_condition() to classify each point.
    """
    xmin, ymin, xmax, ymax = bbox_wgs84
    if n_grid < 1:
        n_grid = 1

    results = {}
    lons = [xmin + (xmax - xmin) * i / max(n_grid - 1, 1) for i in range(n_grid)]
    lats = [ymin + (ymax - ymin) * i / max(n_grid - 1, 1) for i in range(n_grid)]

    for lat in lats:
        for lon in lons:
            vwc = _query_open_meteo_soil(lat, lon)
            results[(round(lat, 5), round(lon, 5))] = vwc

    return results

# <<< END OF FILE >>>
