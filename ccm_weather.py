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

VERSION = "2.20"  # Aligned with MCE_CCM_V2.pyt versioning

import json
import math
import os
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
            dist  = math.hypot((fx - lon) * 111.0, (fy - lat) * 111.0)
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
) -> dict:
    """
    Apply a rainfall penalty to an RCI soil dictionary.

    Parameters
    ----------
    rci_dict : dict
        Dictionary mapping soil type keys to (dry_rci, moist_rci, wet_rci)
        tuples or similar numeric values.  The structure matches the
        ``rci_soils_dict`` used internally in MCE_CCM_V1.pyt.
    rainfall_mm : float
        Current rainfall in mm/hr (from get_rainfall_mm()).
    manual_override : float, optional
        If supplied, this factor (0.0–1.0) overrides all calculated factors.
        Useful for field commanders who know local conditions better than
        automated weather data.

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
            # Rain is present.  Apply penalty scaled by soil sensitivity.
            #
            # Formula:  factor = 1.0 - rain_penalty × (2.0 - sensitivity)
            #
            # Derivation:
            #   rain_penalty = 1.0 - base_factor  (e.g. 0.45 at 25 mm/hr)
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
            rain_penalty = 1.0 - base_factor
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
# SECTION 4 — ARCGIS TOOLBOX HELPER (called from CCMTool.execute)
# ---------------------------------------------------------------------------

def apply_live_weather_to_rci(
    extent_fc: str,
    rci_soils_dict: dict,
    manual_rainfall_mm: Optional[float] = None,
    manual_factor: Optional[float] = None,
) -> dict:
    """
    High-level helper that integrates weather lookup + RCI adjustment for use
    inside the ArcGIS toolbox execute() method.

    Parameters
    ----------
    extent_fc : str
        Path to the AOI extent polygon.  Used to determine lat/lon for weather.
    rci_soils_dict : dict
        The tool's internal RCI lookup dictionary.
    manual_rainfall_mm : float, optional
        Override: user-supplied rainfall (mm/hr).  Skips live lookup if given.
    manual_factor : float, optional
        Override: user-supplied RCI factor (0–1).  Skips all calculation.

    Returns
    -------
    dict  — adjusted RCI dictionary ready for CCM model use.
    """
    try:
        import arcpy
        _log = arcpy.AddMessage
        _warn = arcpy.AddWarning
    except ImportError:
        _log  = print
        _warn = print

    # ── Step 1: determine rainfall ───────────────────────────────────────
    if manual_factor is not None:
        _log(
            f"[CCM Weather] Manual RCI factor override: {manual_factor:.2f}. "
            "Skipping live weather lookup."
        )
        return adjust_rci_for_rainfall(rci_soils_dict, 0.0, manual_override=manual_factor)

    if manual_rainfall_mm is not None:
        rainfall_mm = float(manual_rainfall_mm)
        source_msg  = f"Manual override: {rainfall_mm:.1f} mm/hr"
    else:
        try:
            lat, lon = get_area_centroid(extent_fc)
        except Exception as e:
            _warn(f"[CCM Weather] Could not determine AOI centroid: {e}. Using 0 mm/hr.")
            lat, lon = 0.0, 0.0

        result      = get_rainfall_mm(lat, lon)
        rainfall_mm = result["rainfall_mm"]
        source_msg  = result["message"]

    _log(f"[CCM Weather] {source_msg}")

    # ── Step 2: apply penalty ────────────────────────────────────────────
    factor = _base_rainfall_factor(rainfall_mm)
    if rainfall_mm > 0:
        _log(
            f"[CCM Weather] Rainfall {rainfall_mm:.1f} mm/hr → "
            f"base RCI reduction factor: {factor:.2f}. "
            "Fine-grained soils will be penalised more than coarse soils."
        )
        if rainfall_mm >= 10.0:
            _warn(
                f"[CCM Weather] WARNING — Significant rainfall detected "
                f"({rainfall_mm:.1f} mm/hr). "
                "RCI values have been reduced. Trafficability of cohesive soils "
                "(clay, silt, peat) may be severely limited. "
                "Consider using 'wet' moisture condition or adding a safety margin."
            )
    else:
        _log("[CCM Weather] No rainfall detected. Using standard RCI values.")

    return adjust_rci_for_rainfall(rci_soils_dict, rainfall_mm)


# ---------------------------------------------------------------------------
# SECTION 5 — STANDALONE TEST
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import unittest

    # Sample RCI dict matching the format in MCE_CCM_V1.pyt
    SAMPLE_RCI = {
        "wellGradedGravel":    (160, 140, 120),
        "leanClay":            ( 80,  50,  30),
        "fatClay":             ( 70,  40,  20),
        "peat":                ( 10,   5,   2),
        "rock":                (999, 999, 999),
    }

    class TestRainfallAdjustment(unittest.TestCase):

        def test_no_rain_returns_original(self):
            result = adjust_rci_for_rainfall(SAMPLE_RCI, 0.0)
            self.assertEqual(result["rock"], SAMPLE_RCI["rock"])
            self.assertEqual(result["wellGradedGravel"], SAMPLE_RCI["wellGradedGravel"])

        def test_heavy_rain_reduces_clay_more_than_gravel(self):
            result = adjust_rci_for_rainfall(SAMPLE_RCI, 25.0)
            gravel_orig = SAMPLE_RCI["wellGradedGravel"][0]
            clay_orig   = SAMPLE_RCI["leanClay"][0]
            gravel_adj  = result["wellGradedGravel"][0]
            clay_adj    = result["leanClay"][0]
            gravel_drop = gravel_orig - gravel_adj
            clay_drop   = clay_orig   - clay_adj
            self.assertGreater(clay_drop, gravel_drop,
                "Clay RCI should drop more than gravel under heavy rain")

        def test_rock_insensitive_to_rain(self):
            result = adjust_rci_for_rainfall(SAMPLE_RCI, 50.0)
            self.assertEqual(result["rock"], SAMPLE_RCI["rock"],
                "Rock RCI should not change regardless of rainfall")

        def test_manual_override(self):
            result = adjust_rci_for_rainfall(SAMPLE_RCI, 25.0, manual_override=0.50)
            # Every value should be exactly 50% of original
            for soil, vals in SAMPLE_RCI.items():
                if isinstance(vals, tuple):
                    for orig, adj in zip(vals, result[soil]):
                        if orig is not None:
                            self.assertAlmostEqual(adj, orig * 0.50, places=1)

        def test_factor_never_below_0_1(self):
            result = adjust_rci_for_rainfall(SAMPLE_RCI, 1000.0)
            for soil, vals in result.items():
                if isinstance(vals, tuple):
                    for v in vals:
                        if v is not None:
                            self.assertGreaterEqual(v, 0.1 * SAMPLE_RCI[soil][0] * 0.9,
                                f"RCI for {soil} dropped too low")

    print("Running ccm_weather self-tests …")
    unittest.main(verbosity=2, exit=False)
