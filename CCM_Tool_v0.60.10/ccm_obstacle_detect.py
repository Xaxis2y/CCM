# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
ccm_obstacle_detect.py
======================
CCM Tool — Phase 2, Feature 8: Gap & Obstacle Detection
--------------------------------------------------------
Uses high-resolution input data to detect micro-obstacles that are too
small to be captured in standard CCM vector layers but large enough to
stop or damage a vehicle.

Types of obstacles detected:
  - Slope breaks   (sudden slope increase over a short distance)
    → detected from the horizontal spacing between ADJACENT contour levels
  - Water gaps     (streams, ditches, rivers — line hydro)
    → channel width from a width attribute, or estimated from mean
      discharge (W ≈ 7.2·Q^0.5, Andreadis et al. 2013) when no width exists
  - Water bodies   (lakes, reservoirs, ponds — polygon hydro)
    → equivalent width 4·Area/Perimeter; area obstacles, not crossings
  - Linear barriers (walls, berms, hedgerows, fences — any line layer)

Why this matters
-----------------
Standard CCM maps use low-res polygons (50–500m).  A 2-metre ditch that
stops every vehicle is invisible at that scale.  This module uses finer
datasets (contours, detailed hydro, barrier lines) to find those hidden
blockers before a vehicle gets stuck.

Output
------
An obstacle point feature class with fields:
  OBSTACLE_TYPE   — "SLOPE_BREAK" / "GAP" / "WATER_BODY" / "LINEAR_BARRIER"
  WIDTH_M         — contour spacing, channel width or water-body width (m)
  SLOPE_DEG       — slope angle for SLOPE_BREAK points (else null)
  SEVERITY        — "STOP" (impassable) / "CAUTION" (may be passable)
  DESCRIPTION     — plain-English description
  VEHICLE_STOP    — semicolon-delimited list of vehicles this stops
  SOURCE_LAYER    — input layer the obstacle came from

Units
-----
Every input is clipped to the AOI and then projected to the UTM zone of the
AOI centre before any distance, length or area is measured, so all widths
and search radii are true ground metres regardless of the inputs' CRS
(Geographic WGS84, Web Mercator, …).  The output is written in the CRS of
*output_sr* (Step 3 passes the Speed Surface CRS) or, if none is given, the
AOI CRS.

Usage
-----
    from ccm_obstacle_detect import detect_obstacles

    obstacle_fc = detect_obstacles(
        extent_fc          = r"C:\\...\\AOI.shp",
        contours_fc        = r"C:\\...\\Contours.shp",
        hydro_fcs          = [r"C:\\...\\HydroRIVERS.shp", r"C:\\...\\Lakes.shp"],
        vehicles           = load_vehicle_table(r"C:\\...\\Vehicles_Can.csv"),
        vehicle_name       = "M1",
        contour_interval_m = None,     # None → auto-detect from elevation field
        slope_break_thresh = None,     # None → from vehicle max off-road grade
        ditch_max_width_m  = 4.0,
        output_fc          = r"C:\\...\\03_Project.gdb\\m1_moist_obstacles",
    )
"""

VERSION = "0.60.10"  # v0.59.2 -- bumped by bump_version.py from v0.57. Review this line's comment.
# v0.60.8 — Obstacle Detection rebuilt after a real Step 3 run (Lebanon AOI,
#           M1, Basic licence) returned 0 slope breaks and 35 bogus CAUTION
#           "narrow hydro crossings":
#   1. All inputs are now clipped AND projected to the AOI's UTM zone before
#      measuring.  Previously the HydroLAKES polygons stayed in WGS84, so
#      SHAPE@LENGTH was in DEGREES and every lake (< 4 "units") was flagged.
#   2. Vehicle CSV reader accepts the project's real columns (name,
#      vehicle_width_m, max_off_road_grad).  v0.60.7 only looked for
#      vehicle_name/width_m and silently loaded 0 vehicles.
#   3. Slope-break threshold now defaults to the vehicle's max off-road grade
#      (M1: 54 % → 28.4°) instead of a fixed 45°.  STOP = at/above the
#      vehicle limit, CAUTION = 80–100 % of it.
#   4. Contour interval is auto-detected from the contour elevation field
#      instead of assumed to be 5 m; near pairs on the SAME contour level are
#      skipped and slope uses the real elevation difference.
#   5. The FeatureToPolygon path is only attempted with a Standard/Advanced
#      licence (arcpy.ProductInfo()); Basic goes straight to GenerateNearTable
#      instead of failing with ERROR 001102 first.
#   6. Hydro: line features are treated as water gaps (width from attribute or
#      discharge), polygon features as water bodies.  Multiple hydro layers
#      accepted.  The old "feature length ≤ 4 m" test is gone — a line's
#      length is not its crossing width.
#   7. Obstacle location for slope breaks is the midpoint of the contour pair
#      (was the FROM point only).
# v0.47 — Added Pro 3.7+ Contour List polygon path in _detect_slope_breaks_from_contours()
#          as a faster alternative to GenerateNearTable.  Falls back to the
#          GenerateNearTable O(n²) approach on older Pro versions automatically.
#          Wired up CCMObstacleDetectTool.execute() (was bare `pass` stub).
# v0.46 — VERSION bumped to align with full toolbox release.

import arcpy
import csv
import math
import os
import re
import time
from collections import Counter
from typing import List, Optional, Sequence


# ---------------------------------------------------------------------------
# SECTION 1 — CONSTANTS
# ---------------------------------------------------------------------------

# Obstacle type codes
OT_LINEAR   = "LINEAR_BARRIER"
OT_GAP      = "GAP"
OT_SLOPE    = "SLOPE_BREAK"
OT_POINT    = "POINT_OBSTACLE"
OT_WATER    = "WATER_BODY"

SEV_STOP    = "STOP"
SEV_CAUTION = "CAUTION"

# Default parameter values
DEFAULT_SLOPE_BREAK_THRESH = 45.0  # degrees — used only when no vehicle grade is known
DEFAULT_DITCH_MAX_WIDTH_M  = 4.0   # metres
DEFAULT_CONTOUR_INTERVAL_M = 5.0   # metres — used only when auto-detect fails
GENERIC_STOP_DEG           = 60.0  # generic (no-vehicle) STOP threshold
CAUTION_FRACTION           = 0.80  # CAUTION band starts at 80 % of the STOP slope
NEAR_RADIUS_MARGIN         = 1.02  # search radius margin over the exact spacing
NEAR_CLOSEST_COUNT         = 5     # neighbours per contour in GenerateNearTable

# Andreadis, Schumann & Pavelsky (2013), "A simple global river bankfull
# width and depth database", Water Resources Research 49: W = 7.2 · Q^0.50
# (W in m, Q in m³/s).  Used only when a hydro line has no width attribute.
HYD_GEOM_A = 7.2
HYD_GEOM_B = 0.50

# Candidate attribute names (case-insensitive)
CONTOUR_ELEV_FIELDS = ("contour", "elevation", "elev", "z", "zv2", "height",
                       "hgt", "alt", "altitude", "contour_m", "elev_m")
HYDRO_WIDTH_FIELDS  = ("width_m", "width", "wid", "wth", "riv_width",
                       "channel_w", "chan_width", "wd")
HYDRO_Q_FIELDS      = ("dis_av_cms", "discharge", "q_mean", "qmean",
                       "mean_q", "dis_m3_pyr")

VEH_NAME_COLS  = ("name", "vehicle_name", "vehicle", "veh_name")
VEH_WIDTH_COLS = ("vehicle_width_m", "width_m", "width", "veh_width_m")
VEH_GRADE_COLS = ("max_off_road_grad", "max_off_road_grade",
                  "max_offroad_grad", "max_grade_pct")


# ---------------------------------------------------------------------------
# SECTION 2 — PURE-PYTHON HELPERS (unit-tested without arcpy)
# ---------------------------------------------------------------------------

def norm_name(text) -> str:
    """Normalise a vehicle / field name: lower-case, alphanumerics only."""
    return re.sub(r"[^0-9a-z]", "", str(text or "").lower())


def _pick_col(fieldnames: Sequence[str], candidates: Sequence[str]) -> Optional[str]:
    lookup = {norm_name(f): f for f in (fieldnames or [])}
    for cand in candidates:
        hit = lookup.get(norm_name(cand))
        if hit:
            return hit
    return None


def _to_float(value) -> Optional[float]:
    try:
        v = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if math.isnan(v) or math.isinf(v):
        return None
    return v


def load_vehicle_table(csv_path: str) -> List[dict]:
    """
    Read a vehicle CSV and return a list of
        {"name": str, "width_m": float|None, "max_grade_pct": float|None}

    Accepts the CCM Vehicle_Data column names (name, vehicle_width_m,
    max_off_road_grad) as well as the older vehicle_name / width_m spelling.
    Raises FileNotFoundError / ValueError with a clear message on problems.
    """
    if not csv_path or not os.path.isfile(csv_path):
        raise FileNotFoundError(f"Vehicle CSV not found: {csv_path!r}")
    rows: List[dict] = []
    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        cols = reader.fieldnames or []
        c_name  = _pick_col(cols, VEH_NAME_COLS)
        c_width = _pick_col(cols, VEH_WIDTH_COLS)
        c_grade = _pick_col(cols, VEH_GRADE_COLS)
        if not c_name:
            raise ValueError(
                f"Vehicle CSV has no name column (looked for {VEH_NAME_COLS}); "
                f"columns found: {cols}"
            )
        for row in reader:
            name = (row.get(c_name) or "").strip()
            if not name:
                continue
            rows.append({
                "name":          name,
                "width_m":       _to_float(row.get(c_width)) if c_width else None,
                "max_grade_pct": _to_float(row.get(c_grade)) if c_grade else None,
            })
    return rows


def select_vehicle(vehicles: Sequence[dict], hint) -> Optional[dict]:
    """Return the vehicle row whose normalised name equals *hint* (or None)."""
    key = norm_name(hint)
    if not key:
        return None
    for v in vehicles or []:
        if norm_name(v.get("name")) == key:
            return v
    return None


def grade_pct_to_deg(grade_pct) -> Optional[float]:
    """Percent grade (rise/run·100) → slope angle in degrees."""
    g = _to_float(grade_pct)
    if g is None or g <= 0:
        return None
    return math.degrees(math.atan(g / 100.0))


def slope_thresholds(vehicle: Optional[dict], user_thresh_deg=None):
    """
    Decide (caution_deg, stop_deg, source_text) for slope-break detection.

    * user_thresh_deg given  → STOP at that angle, CAUTION at 80 % of it.
    * vehicle grade known    → STOP at the vehicle's max off-road grade.
    * neither                → legacy generic: CAUTION 45°, STOP 60°.
    """
    ut = _to_float(user_thresh_deg)
    if ut is not None and 0 < ut < 90:
        return ut * CAUTION_FRACTION, ut, f"user threshold {ut:.1f}°"
    vdeg = grade_pct_to_deg((vehicle or {}).get("max_grade_pct"))
    if vdeg is not None:
        return (vdeg * CAUTION_FRACTION, vdeg,
                f"{vehicle['name']} max off-road grade "
                f"{vehicle['max_grade_pct']:g}% = {vdeg:.1f}°")
    return (DEFAULT_SLOPE_BREAK_THRESH, GENERIC_STOP_DEG,
            f"generic default (no vehicle grade): CAUTION ≥ "
            f"{DEFAULT_SLOPE_BREAK_THRESH:.0f}°, STOP ≥ {GENERIC_STOP_DEG:.0f}°")


def spacing_for_slope_m(dz_m: float, slope_deg: float) -> float:
    """Horizontal distance at which a rise of dz_m equals slope_deg."""
    t = math.tan(math.radians(slope_deg))
    return dz_m / t if t > 0 else dz_m


def slope_deg_from(dz_m: float, horiz_m: float) -> float:
    return math.degrees(math.atan(abs(dz_m) / max(float(horiz_m), 0.01)))


def detect_contour_interval(values: Sequence) -> Optional[float]:
    """
    Most common positive gap between successive distinct contour elevations.
    Returns None when fewer than two distinct numeric levels exist.
    """
    levels = sorted({round(v, 3) for v in (_to_float(x) for x in values or [])
                     if v is not None})
    if len(levels) < 2:
        return None
    diffs = [round(b - a, 3) for a, b in zip(levels, levels[1:]) if b - a > 1e-6]
    if not diffs:
        return None
    counts = Counter(diffs)
    best = max(counts.values())
    return float(min(d for d, c in counts.items() if c == best))


def utm_epsg_for_lonlat(lon: float, lat: float) -> int:
    """WGS84 UTM EPSG code (326xx north / 327xx south) incl. Norway/Svalbard."""
    lon = ((float(lon) + 180.0) % 360.0) - 180.0
    zone = int((lon + 180.0) // 6.0) + 1
    if 56.0 <= lat < 64.0 and 3.0 <= lon < 12.0:
        zone = 32
    elif 72.0 <= lat < 84.0:
        if 0.0 <= lon < 9.0:
            zone = 31
        elif 9.0 <= lon < 21.0:
            zone = 33
        elif 21.0 <= lon < 33.0:
            zone = 35
        elif 33.0 <= lon < 42.0:
            zone = 37
    zone = max(1, min(60, zone))
    return (32600 if lat >= 0 else 32700) + zone


def estimate_channel_width_m(width_attr=None, discharge_cms=None) -> Optional[float]:
    """Channel width from an attribute, else hydraulic geometry from discharge."""
    w = _to_float(width_attr)
    if w is not None and w > 0:
        return w
    q = _to_float(discharge_cms)
    if q is not None and q > 0:
        return HYD_GEOM_A * (q ** HYD_GEOM_B)
    return None


def polygon_equivalent_width_m(area_m2, perimeter_m) -> Optional[float]:
    """4·A/P — a circle's diameter, ~2× a long strip's width."""
    a, p = _to_float(area_m2), _to_float(perimeter_m)
    if not a or not p or a <= 0 or p <= 0:
        return None
    return 4.0 * a / p


def classify_water_gap(width_m, ditch_max_width_m) -> str:
    """STOP when wider than the ditch limit; CAUTION when narrow or unknown."""
    if width_m is None:
        return SEV_CAUTION
    return SEV_STOP if float(width_m) > float(ditch_max_width_m) else SEV_CAUTION


def vehicles_stopped_by_slope(slope_deg: float, vehicles: Sequence[dict]) -> List[str]:
    out = []
    for v in vehicles or []:
        vdeg = grade_pct_to_deg(v.get("max_grade_pct"))
        if vdeg is not None and slope_deg >= vdeg:
            out.append(v["name"])
    return out


# ---------------------------------------------------------------------------
# SECTION 3 — ARCPY HELPERS
# ---------------------------------------------------------------------------

def _get_pro_version() -> tuple:
    """Return (major, minor) ArcGIS Pro version as integers, e.g. (3, 7)."""
    try:
        ver_str = arcpy.GetInstallInfo().get("Version", "0.0")
        parts = ver_str.split(".")[:2]
        return tuple(int(x) for x in parts)
    except Exception:
        return (0, 0)


def _license_level() -> str:
    """'Basic' / 'Standard' / 'Advanced' / 'Unknown'."""
    try:
        prod = str(arcpy.ProductInfo())
    except Exception:
        return "Unknown"
    return {"ArcView": "Basic", "ArcEditor": "Standard",
            "ArcInfo": "Advanced"}.get(prod, "Unknown")


def _has_standard_license() -> bool:
    return _license_level() in ("Standard", "Advanced")


def _analysis_sr(extent_fc: str):
    """UTM spatial reference for the centre of the AOI."""
    desc = arcpy.Describe(extent_fc)
    ext = desc.extent
    sr = desc.spatialReference
    cx = (ext.XMin + ext.XMax) / 2.0
    cy = (ext.YMin + ext.YMax) / 2.0
    pt = arcpy.PointGeometry(arcpy.Point(cx, cy), sr)
    if sr.type != "Geographic" or sr.factoryCode != 4326:
        pt = pt.projectAs(arcpy.SpatialReference(4326))
    lon, lat = pt.firstPoint.X, pt.firstPoint.Y
    return arcpy.SpatialReference(utm_epsg_for_lonlat(lon, lat))


def _same_sr(sr_a, sr_b) -> bool:
    try:
        if sr_a.factoryCode and sr_b.factoryCode:
            return int(sr_a.factoryCode) == int(sr_b.factoryCode)
        return sr_a.name == sr_b.name
    except Exception:
        return False


def _delete(*paths):
    for p in paths:
        try:
            if p and arcpy.Exists(p):
                arcpy.management.Delete(p)
        except Exception:
            pass


def _prep_layer(in_fc: str, extent_fc: str, analysis_sr, scratch_gdb: str,
                tag: str) -> Optional[str]:
    """
    Clip *in_fc* to the AOI and project the result to *analysis_sr*.
    Returns the path of the metric copy, or None when nothing is in the AOI.
    """
    clipped = os.path.join(scratch_gdb, f"ccm_obs_{tag}_clip")
    projected = os.path.join(scratch_gdb, f"ccm_obs_{tag}_utm")
    _delete(clipped, projected)
    arcpy.analysis.Clip(in_fc, extent_fc, clipped)
    n = int(arcpy.management.GetCount(clipped).getOutput(0))
    if n == 0:
        _delete(clipped)
        return None
    in_sr = arcpy.Describe(clipped).spatialReference
    if _same_sr(in_sr, analysis_sr):
        return clipped
    arcpy.management.Project(clipped, projected, analysis_sr)
    _delete(clipped)
    arcpy.AddMessage(
        f"[CCM Obstacles]   {os.path.basename(in_fc)}: {n} feature(s) in AOI, "
        f"projected {in_sr.name} → {analysis_sr.name} for metric measurement."
    )
    return projected


def _find_field(fc: str, candidates: Sequence[str]) -> Optional[str]:
    try:
        names = [f.name for f in arcpy.ListFields(fc)
                 if f.type in ("Double", "Single", "Integer", "SmallInteger",
                               "BigInteger", "String")]
    except Exception:
        return None
    return _pick_col(names, candidates)


def _create_obstacle_fc(out_fc: str, sr) -> str:
    """Create an empty point feature class with the obstacle schema."""
    gdb  = os.path.dirname(out_fc)
    name = os.path.basename(out_fc)

    if arcpy.Exists(out_fc):
        arcpy.management.Delete(out_fc)

    arcpy.management.CreateFeatureclass(gdb, name, "POINT", spatial_reference=sr)
    fields = [
        ("OBSTACLE_TYPE", "TEXT",   20),
        ("WIDTH_M",       "DOUBLE",  0),
        ("SLOPE_DEG",     "DOUBLE",  0),
        ("SEVERITY",      "TEXT",   10),
        ("DESCRIPTION",   "TEXT",  250),
        ("VEHICLE_STOP",  "TEXT",  250),
        ("SOURCE_LAYER",  "TEXT",   80),
    ]
    for fname, ftype, flength in fields:
        if ftype == "TEXT":
            arcpy.management.AddField(out_fc, fname, ftype, field_length=flength)
        else:
            arcpy.management.AddField(out_fc, fname, ftype)
    return out_fc


# ---------------------------------------------------------------------------
# SECTION 4 — CONTOUR-BASED SLOPE BREAK DETECTION
# ---------------------------------------------------------------------------

def _contour_levels(contours_utm: str):
    """Return (elev_field, {oid: elev}) or (None, {})."""
    fld = _find_field(contours_utm, CONTOUR_ELEV_FIELDS)
    if not fld:
        return None, {}
    elev = {}
    with arcpy.da.SearchCursor(contours_utm, ["OID@", fld]) as cur:
        for oid, z in cur:
            zf = _to_float(z)
            if zf is not None:
                elev[oid] = zf
    return fld, elev


def _slope_obstacle(x, y, horiz_m, dz_m, slope_deg, caution_deg, stop_deg,
                    vehicles, method, source):
    stops = vehicles_stopped_by_slope(slope_deg, vehicles)
    severity = SEV_STOP if slope_deg >= stop_deg else SEV_CAUTION
    return {
        "type":      OT_SLOPE,
        "x":         x,
        "y":         y,
        "width_m":   round(horiz_m, 2),
        "slope_deg": round(slope_deg, 1),
        "severity":  severity,
        "description": (
            f"Steep slope break ~{slope_deg:.0f}° (rise {dz_m:g} m over "
            f"{horiz_m:.1f} m; CAUTION ≥ {caution_deg:.1f}°, STOP ≥ "
            f"{stop_deg:.1f}°) [{method}]"
        )[:250],
        "vehicle_stop": ";".join(stops),
        "source":    source,
    }


def _detect_slope_breaks_polygon(contours_utm, interval_m, caution_deg,
                                 stop_deg, vehicles, scratch_gdb, source):
    """
    Standard/Advanced licence path: FeatureToPolygon closes contour bands;
    a narrow band (4·A/P small) = tightly spaced contours = steep slope.
    Returns a list, or None to make the caller fall back.
    """
    poly_fc = os.path.join(scratch_gdb, "ccm_obs_contour_polys")
    try:
        arcpy.AddMessage(
            "[CCM Obstacles] Slope breaks: contour-band polygon method "
            f"({_license_level()} licence) …"
        )
        _delete(poly_fc)
        arcpy.management.FeatureToPolygon([contours_utm], poly_fc)
        max_band = spacing_for_slope_m(interval_m, caution_deg)
        obstacles = []
        with arcpy.da.SearchCursor(poly_fc, ["SHAPE@AREA", "SHAPE@LENGTH",
                                             "SHAPE@"]) as cur:
            for area, perim, shp in cur:
                width = polygon_equivalent_width_m(area, perim)
                if width is None or width > max_band:
                    continue
                s = slope_deg_from(interval_m, width)
                if s < caution_deg:
                    continue
                lp = shp.labelPoint
                obstacles.append(_slope_obstacle(
                    lp.X, lp.Y, width, interval_m, s, caution_deg, stop_deg,
                    vehicles, "contour-band polygon", source))
        _delete(poly_fc)
        arcpy.AddMessage(
            f"[CCM Obstacles] Found {len(obstacles)} slope break obstacle(s) "
            "(contour-band polygon method)."
        )
        return obstacles
    except Exception as exc:
        _delete(poly_fc)
        arcpy.AddWarning(
            f"[CCM Obstacles] Polygon method failed ({exc}); "
            "falling back to GenerateNearTable."
        )
        return None


def _detect_slope_breaks_near(contours_utm, interval_m, caution_deg, stop_deg,
                              elev, vehicles, scratch_gdb, source):
    """
    Basic-licence path: GenerateNearTable between contour lines.
    Pairs on the same contour level are skipped; the slope uses the real
    elevation difference of the pair.
    """
    radius = spacing_for_slope_m(interval_m, caution_deg) * NEAR_RADIUS_MARGIN
    arcpy.AddMessage(
        f"[CCM Obstacles] Slope breaks: GenerateNearTable, search radius "
        f"{radius:.2f} m (rise {interval_m:g} m at ≥ {caution_deg:.1f}°) …"
    )
    near_table = os.path.join(scratch_gdb, "ccm_obs_near")
    _delete(near_table)
    obstacles = []
    seen = set()
    same_level = 0
    try:
        arcpy.analysis.GenerateNearTable(
            in_features   = contours_utm,
            near_features = contours_utm,
            out_table     = near_table,
            search_radius = f"{radius} Meters",
            location      = "LOCATION",
            angle         = "NO_ANGLE",
            closest       = "ALL",
            closest_count = NEAR_CLOSEST_COUNT,
            method        = "PLANAR",
        )
        flds = ["IN_FID", "NEAR_FID", "NEAR_DIST",
                "FROM_X", "FROM_Y", "NEAR_X", "NEAR_Y"]
        with arcpy.da.SearchCursor(near_table, flds) as cur:
            for in_fid, near_fid, dist, fx, fy, nx, ny in cur:
                if in_fid == near_fid or dist is None or dist < 0.01:
                    continue
                key = (min(in_fid, near_fid), max(in_fid, near_fid))
                if key in seen:
                    continue
                seen.add(key)
                if elev:
                    z1, z2 = elev.get(in_fid), elev.get(near_fid)
                    if z1 is None or z2 is None:
                        continue
                    dz = abs(z1 - z2)
                    if dz < 0.5 * interval_m:
                        same_level += 1
                        continue
                else:
                    dz = interval_m
                s = slope_deg_from(dz, dist)
                if s < caution_deg:
                    continue
                if None not in (fx, fy, nx, ny):
                    x, y = (fx + nx) / 2.0, (fy + ny) / 2.0
                else:
                    x, y = fx or 0.0, fy or 0.0
                obstacles.append(_slope_obstacle(
                    x, y, float(dist), round(dz, 2), s, caution_deg, stop_deg,
                    vehicles, "GenerateNearTable", source))
    except Exception as exc:
        arcpy.AddWarning(f"[CCM Obstacles] Slope break detection failed: {exc}")
    finally:
        _delete(near_table)
    arcpy.AddMessage(
        f"[CCM Obstacles] Found {len(obstacles)} slope break obstacle(s) — "
        f"{len(seen)} contour pair(s) within radius, {same_level} same-level "
        "pair(s) skipped."
    )
    if not seen:
        arcpy.AddWarning(
            "[CCM Obstacles] No contour pairs were found within the search "
            "radius.  Either the AOI has no slopes this steep at this contour "
            "resolution, or the contours are too coarse (e.g. derived from a "
            "30 m DEM, which smooths out short steep breaks)."
        )
    return obstacles


def _detect_slope_breaks_from_contours(contours_fc, extent_fc, analysis_sr,
                                       contour_interval_m, caution_deg,
                                       stop_deg, vehicles, scratch_gdb):
    t0 = time.time()
    contours_utm = None
    try:
        contours_utm = _prep_layer(contours_fc, extent_fc, analysis_sr,
                                   scratch_gdb, "contours")
        if contours_utm is None:
            arcpy.AddWarning("[CCM Obstacles] No contours inside the AOI.")
            return []
        elev_field, elev = _contour_levels(contours_utm)
        interval = _to_float(contour_interval_m)
        if interval is None or interval <= 0:
            interval = detect_contour_interval(elev.values()) if elev else None
            if interval:
                arcpy.AddMessage(
                    f"[CCM Obstacles] Contour interval auto-detected: "
                    f"{interval:g} m (field '{elev_field}')."
                )
            else:
                interval = DEFAULT_CONTOUR_INTERVAL_M
                arcpy.AddWarning(
                    "[CCM Obstacles] Could not detect the contour interval "
                    f"(no elevation field among {CONTOUR_ELEV_FIELDS}); "
                    f"assuming {interval:g} m."
                )
        if not elev:
            arcpy.AddWarning(
                "[CCM Obstacles] Contours have no elevation field — same-level "
                "pairs cannot be excluded; results may include false positives."
            )
        source = os.path.basename(contours_fc)
        result = None
        if _has_standard_license():
            result = _detect_slope_breaks_polygon(
                contours_utm, interval, caution_deg, stop_deg, vehicles,
                scratch_gdb, source)
        else:
            arcpy.AddMessage(
                f"[CCM Obstacles] {_license_level()} licence — FeatureToPolygon "
                "needs Standard/Advanced; using GenerateNearTable directly."
            )
        if result is None:
            result = _detect_slope_breaks_near(
                contours_utm, interval, caution_deg, stop_deg, elev, vehicles,
                scratch_gdb, source)
        return result
    except Exception as exc:
        arcpy.AddWarning(f"[CCM Obstacles] Slope break detection failed: {exc}")
        return []
    finally:
        _delete(contours_utm)
        arcpy.AddMessage(
            f"[CCM Obstacles] Slope-break step took {time.time() - t0:.0f} s."
        )


# ---------------------------------------------------------------------------
# SECTION 5 — HYDRO DETECTION (water gaps + water bodies)
# ---------------------------------------------------------------------------

def _detect_hydro(hydro_fc, extent_fc, analysis_sr, ditch_max_width_m,
                  vehicles, scratch_gdb, tag):
    obstacles = []
    source = os.path.basename(hydro_fc)
    all_names = ";".join(v["name"] for v in vehicles or [])
    hydro_utm = None
    try:
        shape = arcpy.Describe(hydro_fc).shapeType
        if shape not in ("Polyline", "Polygon"):
            arcpy.AddWarning(
                f"[CCM Obstacles] Hydro layer '{source}' is {shape} — only line "
                "(streams) and polygon (water bodies) layers are used; skipped."
            )
            return []
        arcpy.AddMessage(f"[CCM Obstacles] Hydro: '{source}' ({shape}) …")
        hydro_utm = _prep_layer(hydro_fc, extent_fc, analysis_sr,
                                scratch_gdb, tag)
        if hydro_utm is None:
            arcpy.AddMessage(f"[CCM Obstacles]   '{source}': no features in AOI.")
            return []

        if shape == "Polyline":
            wf = _find_field(hydro_utm, HYDRO_WIDTH_FIELDS)
            qf = _find_field(hydro_utm, HYDRO_Q_FIELDS)
            basis = (f"attribute '{wf}'" if wf else
                     f"discharge '{qf}' (W = {HYD_GEOM_A}·Q^{HYD_GEOM_B})" if qf
                     else "none — width unknown")
            arcpy.AddMessage(f"[CCM Obstacles]   Channel-width basis: {basis}.")
            flds = ["SHAPE@"] + ([wf] if wf else []) + ([qf] if qf else [])
            n_stop = n_caution = n_unknown = 0
            with arcpy.da.SearchCursor(hydro_utm, flds) as cur:
                for row in cur:
                    shp = row[0]
                    if shp is None:
                        continue
                    wv = row[1] if wf else None
                    qv = row[-1] if qf else None
                    width = estimate_channel_width_m(wv, qv)
                    sev = classify_water_gap(width, ditch_max_width_m)
                    mid = shp.positionAlongLine(0.5, True).firstPoint
                    if width is None:
                        n_unknown += 1
                        desc = ("Water crossing, width unknown — verify bank "
                                "height, depth and bottom before crossing.")
                    elif sev == SEV_STOP:
                        n_stop += 1
                        desc = (f"Water gap ≈ {width:.1f} m wide (> "
                                f"{ditch_max_width_m:g} m) — needs a bridge or "
                                "recce'd ford site.")
                    else:
                        n_caution += 1
                        desc = (f"Narrow stream/ditch ≈ {width:.1f} m wide — "
                                "likely crossable; check banks.")
                    if width is not None and not wf:
                        desc += " (width estimated from discharge)"
                    obstacles.append({
                        "type": OT_GAP, "x": mid.X, "y": mid.Y,
                        "width_m": round(width, 2) if width is not None else None,
                        "severity": sev, "description": desc[:250],
                        "vehicle_stop": all_names if sev == SEV_STOP else "",
                        "source": source,
                    })
            arcpy.AddMessage(
                f"[CCM Obstacles]   {len(obstacles)} water gap(s): STOP {n_stop}, "
                f"CAUTION {n_caution}, width unknown {n_unknown}."
            )
        else:
            with arcpy.da.SearchCursor(hydro_utm, ["SHAPE@", "SHAPE@AREA",
                                                   "SHAPE@LENGTH"]) as cur:
                for shp, area, perim in cur:
                    if shp is None:
                        continue
                    width = polygon_equivalent_width_m(area, perim)
                    if width is None:
                        continue
                    sev = classify_water_gap(width, ditch_max_width_m)
                    lp = shp.labelPoint
                    desc = (f"Water body ≈ {width:.0f} m across, "
                            f"{float(area) / 1e4:.1f} ha — "
                            + ("impassable, route around." if sev == SEV_STOP
                               else "small pond/pool — check depth."))
                    obstacles.append({
                        "type": OT_WATER, "x": lp.X, "y": lp.Y,
                        "width_m": round(width, 2), "severity": sev,
                        "description": desc[:250],
                        "vehicle_stop": all_names if sev == SEV_STOP else "",
                        "source": source,
                    })
            arcpy.AddMessage(
                f"[CCM Obstacles]   {len(obstacles)} water body/bodies "
                f"(STOP {sum(o['severity'] == SEV_STOP for o in obstacles)})."
            )
    except Exception as exc:
        arcpy.AddWarning(f"[CCM Obstacles] Hydro detection failed for '{source}': {exc}")
    finally:
        _delete(hydro_utm)
    return obstacles


# ---------------------------------------------------------------------------
# SECTION 6 — LINEAR BARRIER DETECTION (walls, berms, fences)
# ---------------------------------------------------------------------------

def _detect_linear_barriers(barrier_fc, extent_fc, analysis_sr, vehicles,
                            scratch_gdb):
    """Flag every line in *barrier_fc* as a linear barrier (midpoint)."""
    obstacles = []
    source = os.path.basename(barrier_fc)
    barrier_utm = None
    try:
        if arcpy.Describe(barrier_fc).shapeType != "Polyline":
            arcpy.AddWarning(f"[CCM Obstacles] '{source}' is not a line layer — skipped.")
            return []
        barrier_utm = _prep_layer(barrier_fc, extent_fc, analysis_sr,
                                  scratch_gdb, "barrier")
        if barrier_utm is None:
            return []
        names = ";".join(v["name"] for v in vehicles or [])
        with arcpy.da.SearchCursor(barrier_utm, ["SHAPE@"]) as cur:
            for (shp,) in cur:
                if shp is None:
                    continue
                mid = shp.positionAlongLine(0.5, True).firstPoint
                obstacles.append({
                    "type": OT_LINEAR, "x": mid.X, "y": mid.Y,
                    "width_m": 1.0, "severity": SEV_STOP,
                    "description": (f"Linear barrier from '{source}'. "
                                    "Manual verification recommended.")[:250],
                    "vehicle_stop": names, "source": source,
                })
        arcpy.AddMessage(f"[CCM Obstacles] Found {len(obstacles)} linear barrier(s).")
    except Exception as exc:
        arcpy.AddWarning(f"[CCM Obstacles] Linear barrier detection failed: {exc}")
    finally:
        _delete(barrier_utm)
    return obstacles


# ---------------------------------------------------------------------------
# SECTION 7 — WRITE OBSTACLES TO FEATURE CLASS
# ---------------------------------------------------------------------------

def _write_obstacles(obstacles, output_fc, analysis_sr, out_sr) -> None:
    """Write obstacle dicts (analysis-SR coordinates) into output_fc (out_sr)."""
    if not obstacles:
        return
    reproject = not _same_sr(analysis_sr, out_sr)
    fields = ["SHAPE@", "OBSTACLE_TYPE", "WIDTH_M", "SLOPE_DEG",
              "SEVERITY", "DESCRIPTION", "VEHICLE_STOP", "SOURCE_LAYER"]
    with arcpy.da.InsertCursor(output_fc, fields) as cur:
        for obs in obstacles:
            geom = arcpy.PointGeometry(arcpy.Point(obs["x"], obs["y"]), analysis_sr)
            if reproject:
                geom = geom.projectAs(out_sr)
            cur.insertRow([
                geom,
                obs.get("type", "UNKNOWN"),
                obs.get("width_m"),
                obs.get("slope_deg"),
                obs.get("severity", SEV_CAUTION),
                obs.get("description", ""),
                (obs.get("vehicle_stop") or "")[:250],
                (obs.get("source") or "")[:80],
            ])


# ---------------------------------------------------------------------------
# SECTION 8 — MAIN PUBLIC FUNCTION
# ---------------------------------------------------------------------------

def detect_obstacles(
    extent_fc:           str,
    contours_fc:         Optional[str]            = None,
    hydro_fcs                                     = None,
    barrier_fc:          Optional[str]            = None,
    vehicles:            Optional[List[dict]]     = None,
    vehicle_name:        Optional[str]            = None,
    contour_interval_m:  Optional[float]          = None,
    slope_break_thresh:  Optional[float]          = None,
    ditch_max_width_m:   float                    = DEFAULT_DITCH_MAX_WIDTH_M,
    output_fc:           str                      = "",
    scratch_gdb:         str                      = "",
    output_sr                                     = None,
    hydro_fc:            Optional[str]            = None,
) -> str:
    """
    Detect micro-obstacles in an AOI using high-resolution input layers.

    Parameters
    ----------
    extent_fc : AOI polygon.
    contours_fc : contour lines (slope breaks).
    hydro_fcs : one path or a list — line (streams) and/or polygon (lakes).
    barrier_fc : linear barriers (walls, fences, berms).
    vehicles : rows from load_vehicle_table().
    vehicle_name : the vehicle this run is for (drives the slope threshold).
    contour_interval_m : None/0 → auto-detect from the elevation field.
    slope_break_thresh : None → the vehicle's max off-road grade.
    ditch_max_width_m : water narrower than this is CAUTION, wider is STOP.
    output_fc : output point FC.
    output_sr : output CRS (defaults to the AOI CRS).
    hydro_fc : backward-compatible single-layer alias for hydro_fcs.
    """
    t_start = time.time()
    if not scratch_gdb:
        scratch_gdb = arcpy.env.scratchGDB
    if not output_fc:
        output_fc = os.path.join(os.path.dirname(extent_fc), "ccm_obstacles")
    vehicles = list(vehicles or [])

    hydro_list = []
    for h in ([hydro_fcs] if isinstance(hydro_fcs, str) else list(hydro_fcs or [])) \
            + ([hydro_fc] if hydro_fc else []):
        for part in str(h).split(";"):
            part = part.strip().strip("'\"")
            if part and part not in hydro_list:
                hydro_list.append(part)

    arcpy.AddMessage("[CCM Obstacles] Starting obstacle detection …")
    arcpy.AddMessage(f"[CCM Obstacles] Licence level: {_license_level()}.")

    analysis_sr = _analysis_sr(extent_fc)
    out_sr = output_sr or arcpy.Describe(extent_fc).spatialReference
    arcpy.AddMessage(
        f"[CCM Obstacles] Measuring in {analysis_sr.name} (EPSG "
        f"{analysis_sr.factoryCode}); output CRS: {out_sr.name}."
    )

    vehicle = select_vehicle(vehicles, vehicle_name)
    if vehicle_name and vehicle is None and vehicles:
        arcpy.AddWarning(
            f"[CCM Obstacles] Vehicle '{vehicle_name}' not found in the vehicle "
            f"CSV ({len(vehicles)} rows) — using generic slope thresholds."
        )
    elif vehicle:
        arcpy.AddMessage(
            f"[CCM Obstacles] Vehicle: {vehicle['name']}  width "
            f"{vehicle.get('width_m')} m  max off-road grade "
            f"{vehicle.get('max_grade_pct')} %."
        )
    caution_deg, stop_deg, basis = slope_thresholds(vehicle, slope_break_thresh)
    arcpy.AddMessage(
        f"[CCM Obstacles] Slope thresholds: CAUTION ≥ {caution_deg:.1f}°, "
        f"STOP ≥ {stop_deg:.1f}°  ({basis})."
    )
    stop_vehicles = [vehicle] if vehicle else vehicles

    _create_obstacle_fc(output_fc, out_sr)
    all_obstacles: List[dict] = []

    if contours_fc and arcpy.Exists(contours_fc):
        arcpy.SetProgressorLabel("Obstacle Detection: analysing contours …")
        all_obstacles += _detect_slope_breaks_from_contours(
            contours_fc, extent_fc, analysis_sr, contour_interval_m,
            caution_deg, stop_deg, stop_vehicles, scratch_gdb)
    elif contours_fc:
        arcpy.AddWarning(f"[CCM Obstacles] Contour FC not found: {contours_fc}")

    for i, hfc in enumerate(hydro_list):
        if not arcpy.Exists(hfc):
            arcpy.AddWarning(f"[CCM Obstacles] Hydro FC not found: {hfc}")
            continue
        arcpy.SetProgressorLabel("Obstacle Detection: analysing hydro …")
        all_obstacles += _detect_hydro(
            hfc, extent_fc, analysis_sr, ditch_max_width_m, stop_vehicles,
            scratch_gdb, f"hydro{i}")

    if barrier_fc and arcpy.Exists(barrier_fc):
        arcpy.SetProgressorLabel("Obstacle Detection: analysing linear barriers …")
        all_obstacles += _detect_linear_barriers(
            barrier_fc, extent_fc, analysis_sr, stop_vehicles, scratch_gdb)

    arcpy.SetProgressorLabel("Obstacle Detection: writing output …")
    _write_obstacles(all_obstacles, output_fc, analysis_sr, out_sr)

    by_type = Counter(o.get("type") for o in all_obstacles)
    stop_count = sum(1 for o in all_obstacles if o.get("severity") == SEV_STOP)
    arcpy.AddMessage(
        f"[CCM Obstacles] Detection complete. Total: {len(all_obstacles)}  |  "
        f"STOP: {stop_count}  |  CAUTION: {len(all_obstacles) - stop_count}  |  "
        + ", ".join(f"{k}: {v}" for k, v in sorted(by_type.items()))
    )
    arcpy.AddMessage(
        f"[CCM Obstacles] Output: {output_fc}  ({time.time() - t_start:.0f} s)"
    )
    return output_fc


# ---------------------------------------------------------------------------
# SECTION 9 — ARCGIS TOOLBOX TOOL WRAPPER
# ---------------------------------------------------------------------------

class CCMObstacleDetectTool:
    """ArcGIS Python Toolbox tool for micro-obstacle detection."""

    def __init__(self):
        self.label       = "6.  Find Hidden Obstacles & Gaps"
        self.description = (
            "Uses high-resolution contour, hydro, and barrier data to identify "
            "micro-obstacles (steep slope breaks, water gaps, water bodies, "
            "walls) that are too small for standard CCM layers but large "
            "enough to stop a vehicle.  Run after the main CCM tool."
        )
        self.canRunInBackground = False

    def getParameterInfo(self):
        p0 = arcpy.Parameter(
            displayName="AOI / Extent Polygon", name="extent_fc",
            datatype="DEFeatureClass", parameterType="Required", direction="Input")
        p1 = arcpy.Parameter(
            displayName="Contours Feature Class (for slope break detection)",
            name="contours_fc", datatype="DEFeatureClass",
            parameterType="Optional", direction="Input")
        p2 = arcpy.Parameter(
            displayName="Hydro Feature Classes (stream lines and/or lake polygons)",
            name="hydro_fc", datatype="DEFeatureClass",
            parameterType="Optional", direction="Input", multiValue=True)
        p3 = arcpy.Parameter(
            displayName="Linear Barrier Feature Class (walls, fences, berms)",
            name="barrier_fc", datatype="DEFeatureClass",
            parameterType="Optional", direction="Input")
        p4 = arcpy.Parameter(
            displayName="Vehicle CSV  (name, vehicle_width_m, max_off_road_grad)",
            name="vehicle_csv", datatype="DEFile",
            parameterType="Optional", direction="Input")
        p5 = arcpy.Parameter(
            displayName="Contour Interval (metres) — blank = auto-detect",
            name="contour_interval_m", datatype="GPDouble",
            parameterType="Optional", direction="Input")
        p6 = arcpy.Parameter(
            displayName="Slope Break STOP Threshold (degrees) — blank = vehicle max grade",
            name="slope_break_thresh", datatype="GPDouble",
            parameterType="Optional", direction="Input")
        p7 = arcpy.Parameter(
            displayName="Maximum Ditch / Gap Width (metres)",
            name="ditch_max_width_m", datatype="GPDouble",
            parameterType="Optional", direction="Input")
        p7.value = DEFAULT_DITCH_MAX_WIDTH_M
        p8 = arcpy.Parameter(
            displayName="Output Obstacle Feature Class", name="output_fc",
            datatype="DEFeatureClass", parameterType="Required", direction="Output")
        p9 = arcpy.Parameter(
            displayName="Vehicle Name (row in the Vehicle CSV)",
            name="vehicle_name", datatype="GPString",
            parameterType="Optional", direction="Input")
        p10 = arcpy.Parameter(
            displayName="Output CRS Reference Layer (e.g. Speed Surface)",
            name="reference_fc", datatype="DEFeatureClass",
            parameterType="Optional", direction="Input")
        return [p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10]

    def isLicensed(self):
        return True

    def updateParameters(self, p):
        pass

    def updateMessages(self, p):
        pass

    def execute(self, parameters, messages):
        arcpy.SetLogMetadata(False)  # Prevent GDB history metadata accumulation (perf)
        by = {p.name: p for p in parameters}

        def _txt(name):
            prm = by.get(name)
            return prm.valueAsText if prm is not None else None

        def _num(name):
            prm = by.get(name)
            return _to_float(prm.value) if prm is not None and prm.value not in (None, "") else None

        vehicle_csv = _txt("vehicle_csv")
        vehicles: List[dict] = []
        if vehicle_csv:
            try:
                vehicles = load_vehicle_table(vehicle_csv)
                arcpy.AddMessage(
                    f"[Obstacle Detect] Loaded {len(vehicles)} vehicle(s) from "
                    f"{vehicle_csv}."
                )
                if not vehicles:
                    arcpy.AddWarning("[Obstacle Detect] Vehicle CSV has no data rows.")
            except Exception as exc:
                arcpy.AddWarning(f"[Obstacle Detect] Could not read vehicle CSV: {exc}")
        else:
            arcpy.AddWarning(
                "[Obstacle Detect] No vehicle CSV — slope thresholds fall back to "
                "generic values and VEHICLE_STOP will be empty."
            )

        out_sr = None
        ref = _txt("reference_fc")
        if ref and arcpy.Exists(ref):
            try:
                out_sr = arcpy.Describe(ref).spatialReference
            except Exception:
                out_sr = None

        detect_obstacles(
            extent_fc          = _txt("extent_fc"),
            contours_fc        = _txt("contours_fc"),
            hydro_fcs          = _txt("hydro_fc"),
            barrier_fc         = _txt("barrier_fc"),
            vehicles           = vehicles,
            vehicle_name       = _txt("vehicle_name"),
            contour_interval_m = _num("contour_interval_m"),
            slope_break_thresh = _num("slope_break_thresh"),
            ditch_max_width_m  = _num("ditch_max_width_m") or DEFAULT_DITCH_MAX_WIDTH_M,
            output_fc          = _txt("output_fc"),
            scratch_gdb        = arcpy.env.scratchGDB,
            output_sr          = out_sr,
        )

# <<< END OF FILE >>>
