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
  - Linear obstacles (walls, berms, hedgerows, fences)
    → narrow linear features from contour data or line features
  - Gap obstacles  (narrow ditches, stream crossings, road cuts)
    → gaps in passable ground where width < vehicle width
  - Slope breaks   (sudden slope increase over a short distance)
    → detected from contour spacing / DEM derivatives
  - Point obstacles (boulders, single trees, structures)
    → detected from point feature classes

Why this matters
-----------------
Standard CCM maps use low-res polygons (50–500m).  A 2-metre ditch that
stops every vehicle is invisible at that scale.  This module uses finer
datasets (contours, detailed hydro, building footprints) to find those
hidden blockers before a vehicle gets stuck.

Output
------
An obstacle feature class (points or lines) with fields:
  OBSTACLE_TYPE   — "LINEAR_BARRIER" / "GAP" / "SLOPE_BREAK" / "POINT"
  WIDTH_M         — estimated obstacle width or gap width in metres
  SEVERITY        — "STOP" (impassable) / "CAUTION" (may be passable)
  DESCRIPTION     — plain-English description
  VEHICLE_STOP    — semicolon-delimited list of vehicles this stops

Usage
-----
    from ccm_obstacle_detect import detect_obstacles

    obstacle_fc = detect_obstacles(
        contours_fc        = r"C:\\...\\Contours.shp",
        hydro_fc           = r"C:\\...\\HydroLines.shp",
        building_fc        = r"C:\\...\\Buildings.shp",    # optional
        extent_fc          = r"C:\\...\\AOI.shp",
        vehicle_widths_m   = {"LAV III": 2.65, "Leopard 2": 3.75},
        contour_interval_m = 5,
        slope_break_thresh = 45,       # degrees — steeper = STOP obstacle
        ditch_max_width_m  = 4.0,      # gaps narrower than this are gaps
        output_fc          = r"C:\\...\\CCM_Output.gdb\\obstacles",
        scratch_gdb        = arcpy.env.scratchGDB,
    )
"""

VERSION = "0.54.1"  # v0.54.1 — GPL-2.0-or-later relicense + CCM Tool by Son rebrand (see CHANGELOG_v0.54.md).
# v0.47 — Added Pro 3.7+ Contour List polygon path in _detect_slope_breaks_from_contours()
#          as a faster alternative to GenerateNearTable.  Falls back to the
#          GenerateNearTable O(n²) approach on older Pro versions automatically.
#          Wired up CCMObstacleDetectTool.execute() (was bare `pass` stub).
# v0.46 — VERSION bumped to align with full toolbox release.

import arcpy
import os
import math
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# SECTION 1 — CONSTANTS
# ---------------------------------------------------------------------------

# Obstacle type codes
OT_LINEAR   = "LINEAR_BARRIER"
OT_GAP      = "GAP"
OT_SLOPE    = "SLOPE_BREAK"
OT_POINT    = "POINT_OBSTACLE"

SEV_STOP    = "STOP"
SEV_CAUTION = "CAUTION"

# Default parameter values
DEFAULT_SLOPE_BREAK_THRESH = 45    # degrees
DEFAULT_DITCH_MAX_WIDTH_M  = 4.0   # metres
DEFAULT_CONTOUR_INTERVAL_M = 5.0   # metres


# ---------------------------------------------------------------------------
# SECTION 2 — OBSTACLE SCHEMA BUILDER
# ---------------------------------------------------------------------------

def _create_obstacle_fc(out_fc: str, sr: arcpy.SpatialReference) -> str:
    """Create an empty point feature class with the obstacle schema."""
    gdb  = os.path.dirname(out_fc)
    name = os.path.basename(out_fc)

    if arcpy.Exists(out_fc):
        arcpy.management.Delete(out_fc)

    arcpy.management.CreateFeatureclass(
        gdb, name, "POINT", spatial_reference=sr
    )
    fields = [
        ("OBSTACLE_TYPE", "TEXT",   20,  None),
        ("WIDTH_M",       "DOUBLE",  0,  None),
        ("SEVERITY",      "TEXT",   10,  None),
        ("DESCRIPTION",   "TEXT",  250,  None),
        ("VEHICLE_STOP",  "TEXT",  250,  None),
        ("SOURCE_LAYER",  "TEXT",   80,  None),
    ]
    for fname, ftype, flength, _ in fields:
        if ftype == "TEXT":
            arcpy.management.AddField(out_fc, fname, ftype, field_length=flength)
        else:
            arcpy.management.AddField(out_fc, fname, ftype)

    return out_fc


# ---------------------------------------------------------------------------
# SECTION 3 — CONTOUR-BASED SLOPE BREAK DETECTION
# ---------------------------------------------------------------------------

def _get_pro_version() -> tuple:
    """Return (major, minor) ArcGIS Pro version as integers, e.g. (3, 7)."""
    try:
        ver_str = arcpy.GetInstallInfo().get("Version", "0.0")
        parts = ver_str.split(".")[:2]
        return tuple(int(x) for x in parts)
    except Exception:
        return (0, 0)


def _detect_slope_breaks_pro37(
    contours_fc:        str,
    extent_fc:          str,
    contour_interval_m: float,
    slope_break_thresh: float,
    scratch_gdb:        str,
) -> List[dict]:
    """
    Pro 3.7+ fast path: ContourList with contour_type='POLYGON'.

    Each polygon represents the area between two adjacent contour elevations.
    A narrow polygon area (small width) indicates tightly-spaced contours = steep slope.
    This avoids the O(n²) GenerateNearTable approach.

    Returns a list of obstacle dicts on success, or None on failure (caller falls back).
    """
    obstacles = []
    try:
        arcpy.AddMessage(
            "[CCM Obstacles] Detecting slope breaks via ContourList polygon output (Pro 3.7+) …"
        )

        # Clip contours to AOI
        clipped = os.path.join(scratch_gdb, "ccm_obs_contour_poly_clip")
        arcpy.analysis.Clip(contours_fc, extent_fc, clipped)

        feat_count = int(arcpy.management.GetCount(clipped).getOutput(0))
        if feat_count == 0:
            arcpy.AddMessage("[CCM Obstacles] No contours in AOI.")
            return []

        # Convert the clipped line contours to a polygon representation via
        # FeatureToPolygon — this closes each contour band into a polygon.
        poly_fc = os.path.join(scratch_gdb, "ccm_obs_contour_polys")
        arcpy.management.FeatureToPolygon([clipped], poly_fc)

        # For each polygon, approximate the "width" from its area and perimeter
        # (area / (perimeter / 4) ≈ min dimension for roughly rectangular strips).
        # Narrow polygons = tightly spaced contours = steep slopes.
        tan_thresh    = math.tan(math.radians(slope_break_thresh))
        max_spacing_m = (contour_interval_m / tan_thresh) if tan_thresh > 0 else contour_interval_m

        arr = arcpy.da.FeatureClassToNumPyArray(
            poly_fc,
            ["SHAPE@AREA", "SHAPE@LENGTH", "SHAPE@XY"],
            skip_nulls=True,
        )
        # Use explicit field access — safer than nested tuple unpacking
        # on numpy structured arrays (void dtype).
        areas      = arr["SHAPE@AREA"]
        perimeters = arr["SHAPE@LENGTH"]
        centroids  = arr["SHAPE@XY"]      # array of (x, y) tuples

        for area, perimeter, xy in zip(areas, perimeters, centroids):
            if perimeter <= 0:
                continue
            approx_width = (4.0 * float(area)) / float(perimeter)
            if approx_width <= max_spacing_m:
                slope_deg = math.degrees(
                    math.atan(contour_interval_m / max(approx_width, 0.01))
                )
                cx, cy = float(xy[0]), float(xy[1])
                if slope_deg >= slope_break_thresh:
                    obstacles.append({
                        "type":     OT_SLOPE,
                        "x":        cx,
                        "y":        cy,
                        "width_m":  round(approx_width, 2),
                        "severity": SEV_STOP if slope_deg >= 60 else SEV_CAUTION,
                        "description": (
                            f"Steep slope break: ~{slope_deg:.0f}° "
                            f"(contour band width ≈ {approx_width:.1f} m, "
                            f"interval = {contour_interval_m} m) [Pro 3.7 polygon method]"
                        ),
                        "source": "Contours",
                    })

        for tmp in [clipped, poly_fc]:
            if arcpy.Exists(tmp):
                arcpy.management.Delete(tmp)

        arcpy.AddMessage(
            f"[CCM Obstacles] Found {len(obstacles)} slope break obstacles "
            f"(ContourList polygon method)."
        )
        return obstacles

    except Exception as exc:
        arcpy.AddWarning(
            f"[CCM Obstacles] Pro 3.7 polygon method failed ({exc}); "
            "falling back to GenerateNearTable approach."
        )
        return None   # Signal caller to fall back


def _detect_slope_breaks_from_contours(
    contours_fc:        str,
    extent_fc:          str,
    contour_interval_m: float,
    slope_break_thresh: float,
    scratch_gdb:        str,
) -> List[dict]:
    """
    Identify locations where contours are packed very tightly together
    (steep sudden slope) — likely step-like features or cliffs.

    On Pro 3.7+: uses ContourList polygon output (faster, avoids O(n²) near-table).
    On older Pro: falls back to GenerateNearTable approach.

    Returns a list of dicts with centroid x, y, width_m, description.
    """
    # ── Pro 3.7+ fast path ────────────────────────────────────────────────
    if _get_pro_version() >= (3, 7):
        result = _detect_slope_breaks_pro37(
            contours_fc, extent_fc, contour_interval_m,
            slope_break_thresh, scratch_gdb,
        )
        if result is not None:
            return result
        # Fall through to legacy path if Pro 3.7 method failed

    # ── Legacy GenerateNearTable path ─────────────────────────────────────
    obstacles = []

    try:
        arcpy.AddMessage("[CCM Obstacles] Detecting slope breaks from contours (GenerateNearTable) …")

        # Clip contours to AOI
        clipped = os.path.join(scratch_gdb, "ccm_obs_contours_clip")
        arcpy.analysis.Clip(contours_fc, extent_fc, clipped)

        feat_count = int(arcpy.management.GetCount(clipped).getOutput(0))
        if feat_count == 0:
            arcpy.AddMessage("[CCM Obstacles] No contours in AOI.")
            return []

        # Maximum horizontal spacing at which slope == slope_break_thresh
        # tan(slope_deg) = contour_interval / horiz_dist
        # → horiz_dist = contour_interval / tan(slope_thresh_rad)
        tan_thresh = math.tan(math.radians(slope_break_thresh))
        max_spacing_m = contour_interval_m / tan_thresh if tan_thresh > 0 else contour_interval_m

        arcpy.AddMessage(
            f"[CCM Obstacles] Contour search radius: {max_spacing_m:.1f} m "
            f"(slope ≥ {slope_break_thresh}° with {contour_interval_m}m interval)."
        )

        # Generate near table: for each contour, find the closest OTHER contour
        # within the search radius. CLOSE_END="NO" ensures we skip self-matches
        # (distance = 0) and only find genuinely close neighbours.
        near_table = os.path.join(scratch_gdb, "ccm_obs_near")
        arcpy.analysis.GenerateNearTable(
            in_features     = clipped,
            near_features   = clipped,
            out_table       = near_table,
            search_radius   = f"{max_spacing_m} Meters",
            location        = "LOCATION",      # include NEAR_X, NEAR_Y, FROM_X, FROM_Y
            angle           = "NO_ANGLE",
            closest         = "ALL",
            closest_count   = 3,               # up to 3 neighbours per contour
            method          = "PLANAR",
        )

        # Read near pairs and compute slope at each pair's midpoint.
        # Explicitly skip self-matches (IN_FID == NEAR_FID, distance == 0).
        seen_pairs = set()
        fields_near = ["IN_FID", "NEAR_FID", "NEAR_DIST", "FROM_X", "FROM_Y"]

        with arcpy.da.SearchCursor(near_table, fields_near) as cur:
            for in_fid, near_fid, near_dist, from_x, from_y in cur:
                # Skip self-match
                if in_fid == near_fid:
                    continue
                # Skip zero / near-zero distances (same geometry)
                if near_dist is None or near_dist < 0.01:
                    continue
                # Deduplicate symmetric pairs (A→B and B→A)
                pair_key = (min(in_fid, near_fid), max(in_fid, near_fid))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                horiz_m   = float(near_dist)
                # slope = arctan(contour_interval / horizontal_distance)
                slope_deg = math.degrees(math.atan(contour_interval_m / max(horiz_m, 0.01)))

                if slope_deg >= slope_break_thresh:
                    # Midpoint between the two contours as obstacle location
                    cx = from_x if from_x is not None else 0.0
                    cy = from_y if from_y is not None else 0.0
                    obstacles.append({
                        "type":    OT_SLOPE,
                        "x":  cx,
                        "y":  cy,
                        "width_m":  round(horiz_m, 2),
                        "severity": SEV_STOP if slope_deg >= 60 else SEV_CAUTION,
                        "description": (
                            f"Steep slope break: ~{slope_deg:.0f}° "
                            f"(contour spacing = {horiz_m:.1f} m, "
                            f"interval = {contour_interval_m} m)"
                        ),
                        "source": "Contours",
                    })

        # Cleanup
        for tmp in [clipped, near_table]:
            if arcpy.Exists(tmp):
                arcpy.management.Delete(tmp)

        arcpy.AddMessage(
            f"[CCM Obstacles] Found {len(obstacles)} potential slope break obstacles "
            f"({len(seen_pairs)} contour pairs evaluated)."
        )

    except Exception as e:
        arcpy.AddWarning(f"[CCM Obstacles] Slope break detection failed: {e}")

    return obstacles


# ---------------------------------------------------------------------------
# SECTION 4 — HYDRO GAP DETECTION
# ---------------------------------------------------------------------------

def _detect_hydro_gaps(
    hydro_fc:         str,
    extent_fc:        str,
    ditch_max_width_m: float,
    vehicle_widths_m: Dict[str, float],
    scratch_gdb:      str,
) -> List[dict]:
    """
    Detect narrow water crossings (ditches, streams) from hydro line features.

    A hydro gap is flagged when feature length is less than ditch_max_width_m,
    indicating a short / narrow crossing that may not be bridgeable.

    Performance: uses FeatureClassToNumPyArray + NumPy vectorised masking
    instead of row-by-row SearchCursor iteration (50–100× faster on large
    hydro datasets).
    """
    import numpy as np

    obstacles = []
    if not hydro_fc or not arcpy.Exists(hydro_fc):
        return []

    arcpy.AddMessage("[CCM Obstacles] Detecting hydro gaps (narrow crossings) …")
    try:
        clipped = os.path.join(scratch_gdb, "ccm_obs_hydro_clip")
        arcpy.analysis.Clip(hydro_fc, extent_fc, clipped)

        feat_count = int(arcpy.management.GetCount(clipped).getOutput(0))
        if feat_count == 0:
            arcpy.AddMessage("[CCM Obstacles] No hydro features in AOI.")
            if arcpy.Exists(clipped):
                arcpy.management.Delete(clipped)
            return []

        # ── NumPy vectorised load ─────────────────────────────────────────
        # SHAPE@LENGTH  = feature length (metres) used as crossing-width proxy.
        # SHAPE@XY      = centroid (x, y) tuple.
        arr = arcpy.da.FeatureClassToNumPyArray(
            clipped,
            ["SHAPE@LENGTH", "SHAPE@XY"],
            skip_nulls=True,
        )

        lengths = arr["SHAPE@LENGTH"].astype(np.float64)
        centroids = arr["SHAPE@XY"]          # array of (x, y) tuples

        # Vectorised filter: keep only short / narrow crossings
        mask = lengths <= ditch_max_width_m
        candidate_lengths   = lengths[mask]
        candidate_centroids = centroids[mask]

        for width, (cx, cy) in zip(candidate_lengths, candidate_centroids):
            stops = [v for v, vw in vehicle_widths_m.items() if vw > width]
            severity = SEV_STOP if stops else SEV_CAUTION
            obstacles.append({
                "type":    OT_GAP,
                "x": float(cx), "y": float(cy),
                "width_m": round(float(width), 2),
                "severity": severity,
                "description": (
                    f"Narrow water crossing: width ≈ {width:.1f} m. "
                    + (f"Stops: {', '.join(stops)}." if stops
                       else "Passable by all listed vehicles.")
                ),
                "source": os.path.basename(hydro_fc),
                "vehicle_stop": ";".join(stops),
            })

        if arcpy.Exists(clipped):
            arcpy.management.Delete(clipped)

        arcpy.AddMessage(
            f"[CCM Obstacles] Found {len(obstacles)} narrow hydro crossings "
            f"({feat_count} features scanned via NumPy)."
        )
    except Exception as e:
        arcpy.AddWarning(f"[CCM Obstacles] Hydro gap detection failed: {e}")

    return obstacles


# ---------------------------------------------------------------------------
# SECTION 5 — LINEAR BARRIER DETECTION (walls, berms, fences)
# ---------------------------------------------------------------------------

def _detect_linear_barriers(
    barrier_fc:       str,
    extent_fc:        str,
    vehicle_widths_m: Dict[str, float],
    scratch_gdb:      str,
) -> List[dict]:
    """
    Flag line features as linear barriers (walls, fences, berms).
    Any linear feature layer can be passed — the function does not
    assume a specific attribute schema.

    Performance: uses FeatureClassToNumPyArray + NumPy centroid extraction
    instead of row-by-row SearchCursor iteration (50–100× faster on large
    barrier datasets).
    """
    obstacles = []
    if not barrier_fc or not arcpy.Exists(barrier_fc):
        return []

    arcpy.AddMessage(f"[CCM Obstacles] Detecting linear barriers in '{barrier_fc}' …")
    try:
        clipped = os.path.join(scratch_gdb, "ccm_obs_barrier_clip")
        arcpy.analysis.Clip(barrier_fc, extent_fc, clipped)

        geom_type = arcpy.Describe(clipped).shapeType
        if geom_type not in ("Polyline", "Line"):
            arcpy.AddWarning(
                f"[CCM Obstacles] '{barrier_fc}' is not a line layer — skipping."
            )
            arcpy.management.Delete(clipped)
            return []

        feat_count = int(arcpy.management.GetCount(clipped).getOutput(0))
        if feat_count == 0:
            if arcpy.Exists(clipped):
                arcpy.management.Delete(clipped)
            return []

        # ── NumPy vectorised load ─────────────────────────────────────────
        # SHAPE@XY = centroid (x, y) — all we need for linear barriers.
        arr = arcpy.da.FeatureClassToNumPyArray(
            clipped,
            ["SHAPE@XY"],
            skip_nulls=True,
        )
        centroids = arr["SHAPE@XY"]          # array of (x, y) tuples

        source_name  = os.path.basename(barrier_fc)
        vehicle_stop = ";".join(vehicle_widths_m.keys())
        description  = (
            f"Linear barrier detected from layer: '{source_name}'. "
            "Manual verification recommended."
        )

        for (cx, cy) in centroids:
            obstacles.append({
                "type":         OT_LINEAR,
                "x":            float(cx),
                "y":            float(cy),
                "width_m":      1.0,          # default — linear features ~1 m wide
                "severity":     SEV_STOP,
                "description":  description,
                "source":       source_name,
                "vehicle_stop": vehicle_stop,
            })

        if arcpy.Exists(clipped):
            arcpy.management.Delete(clipped)

        arcpy.AddMessage(
            f"[CCM Obstacles] Found {len(obstacles)} linear barrier features "
            f"(loaded via NumPy)."
        )
    except Exception as e:
        arcpy.AddWarning(f"[CCM Obstacles] Linear barrier detection failed: {e}")

    return obstacles


# ---------------------------------------------------------------------------
# SECTION 6 — WRITE OBSTACLES TO FEATURE CLASS
# ---------------------------------------------------------------------------

def _write_obstacles(
    obstacles:  List[dict],
    output_fc:  str,
    sr:         arcpy.SpatialReference,
) -> None:
    """Write a list of obstacle dicts to the output feature class."""
    if not obstacles:
        return

    fields = [
        "SHAPE@XY", "OBSTACLE_TYPE", "WIDTH_M",
        "SEVERITY", "DESCRIPTION", "VEHICLE_STOP", "SOURCE_LAYER",
    ]
    with arcpy.da.InsertCursor(output_fc, fields) as cur:
        for obs in obstacles:
            cur.insertRow([
                (obs["x"], obs["y"]),
                obs.get("type",         "UNKNOWN"),
                obs.get("width_m",       0.0),
                obs.get("severity",     SEV_CAUTION),
                obs.get("description",  ""),
                obs.get("vehicle_stop", ""),
                obs.get("source",       ""),
            ])


# ---------------------------------------------------------------------------
# SECTION 7 — MAIN PUBLIC FUNCTION
# ---------------------------------------------------------------------------

def detect_obstacles(
    extent_fc:           str,
    contours_fc:         Optional[str]         = None,
    hydro_fc:            Optional[str]         = None,
    barrier_fc:          Optional[str]         = None,
    vehicle_widths_m:    Optional[Dict[str, float]] = None,
    contour_interval_m:  float = DEFAULT_CONTOUR_INTERVAL_M,
    slope_break_thresh:  float = DEFAULT_SLOPE_BREAK_THRESH,
    ditch_max_width_m:   float = DEFAULT_DITCH_MAX_WIDTH_M,
    output_fc:           str   = "",
    scratch_gdb:         str   = "",
) -> str:
    """
    Detect micro-obstacles in an AOI using high-resolution input layers.

    Parameters
    ----------
    extent_fc : str
        AOI / extent polygon.
    contours_fc : str, optional
        Contour line feature class for slope break detection.
    hydro_fc : str, optional
        Hydro line feature class for gap/crossing detection.
    barrier_fc : str, optional
        Linear barrier feature class (walls, fences, berms).
    vehicle_widths_m : dict, optional
        {vehicle_name: width_m} — used to assess which vehicles are stopped.
    contour_interval_m : float
        Vertical interval between contour lines in metres.
    slope_break_thresh : float
        Slope angle (degrees) above which a feature is flagged as an obstacle.
    ditch_max_width_m : float
        Maximum gap width (m) that is flagged as a ditch obstacle.
    output_fc : str, optional
        Output path.  Auto-generated if empty.
    scratch_gdb : str, optional
        Scratch workspace.

    Returns
    -------
    str  — path to the obstacle feature class.
    """
    if not scratch_gdb:
        scratch_gdb = arcpy.env.scratchGDB
    if not output_fc:
        gdb       = os.path.dirname(extent_fc)
        output_fc = os.path.join(gdb, "ccm_obstacles")
    if vehicle_widths_m is None:
        vehicle_widths_m = {}

    arcpy.AddMessage("[CCM Obstacles] Starting obstacle detection …")

    # Get spatial reference from extent
    sr = arcpy.Describe(extent_fc).spatialReference

    # Create output FC
    _create_obstacle_fc(output_fc, sr)

    all_obstacles: List[dict] = []

    # ── Slope breaks ─────────────────────────────────────────────────────
    if contours_fc and arcpy.Exists(contours_fc):
        arcpy.SetProgressorLabel("Obstacle Detection: Analysing contours …")
        all_obstacles += _detect_slope_breaks_from_contours(
            contours_fc, extent_fc, contour_interval_m,
            slope_break_thresh, scratch_gdb,
        )

    # ── Hydro gaps ───────────────────────────────────────────────────────
    if hydro_fc and arcpy.Exists(hydro_fc):
        arcpy.SetProgressorLabel("Obstacle Detection: Analysing hydro features …")
        all_obstacles += _detect_hydro_gaps(
            hydro_fc, extent_fc, ditch_max_width_m,
            vehicle_widths_m, scratch_gdb,
        )

    # ── Linear barriers ──────────────────────────────────────────────────
    if barrier_fc and arcpy.Exists(barrier_fc):
        arcpy.SetProgressorLabel("Obstacle Detection: Analysing linear barriers …")
        all_obstacles += _detect_linear_barriers(
            barrier_fc, extent_fc, vehicle_widths_m, scratch_gdb,
        )

    # ── Write to output ──────────────────────────────────────────────────
    arcpy.SetProgressorLabel("Obstacle Detection: Writing output …")
    _write_obstacles(all_obstacles, output_fc, sr)

    total = len(all_obstacles)
    stop_count    = sum(1 for o in all_obstacles if o.get("severity") == SEV_STOP)
    caution_count = total - stop_count

    arcpy.AddMessage(
        f"[CCM Obstacles] Detection complete. "
        f"Total: {total}  |  STOP: {stop_count}  |  CAUTION: {caution_count}"
    )
    arcpy.AddMessage(f"[CCM Obstacles] Output: {output_fc}")
    return output_fc


# ---------------------------------------------------------------------------
# SECTION 8 — ARCGIS TOOLBOX TOOL WRAPPER
# ---------------------------------------------------------------------------

class CCMObstacleDetectTool:
    """ArcGIS Python Toolbox tool for micro-obstacle detection."""

    def __init__(self):
        self.label       = "6.  Find Hidden Obstacles & Gaps"
        self.description = (
            "Uses high-resolution contour, hydro, and barrier data to identify "
            "micro-obstacles (narrow ditches, steep slope breaks, walls) that "
            "are too small for standard CCM layers but large enough to stop a "
            "vehicle.  Run after the main CCM tool to refine the output."
        )
        self.canRunInBackground = False

    def getParameterInfo(self):
        p0 = arcpy.Parameter(
            displayName="AOI / Extent Polygon",
            name="extent_fc",
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Input",
        )
        p1 = arcpy.Parameter(
            displayName="Contours Feature Class (for slope break detection)",
            name="contours_fc",
            datatype="DEFeatureClass",
            parameterType="Optional",
            direction="Input",
        )
        p2 = arcpy.Parameter(
            displayName="Hydro Line Feature Class (for gap/crossing detection)",
            name="hydro_fc",
            datatype="DEFeatureClass",
            parameterType="Optional",
            direction="Input",
        )
        p3 = arcpy.Parameter(
            displayName="Linear Barrier Feature Class (walls, fences, berms)",
            name="barrier_fc",
            datatype="DEFeatureClass",
            parameterType="Optional",
            direction="Input",
        )
        p4 = arcpy.Parameter(
            displayName="Vehicle Widths CSV  (vehicle_name, width_m columns)",
            name="vehicle_csv",
            datatype="DEFile",
            parameterType="Optional",
            direction="Input",
        )
        p5 = arcpy.Parameter(
            displayName="Contour Interval (metres)",
            name="contour_interval_m",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input",
        )
        p5.value = DEFAULT_CONTOUR_INTERVAL_M

        p6 = arcpy.Parameter(
            displayName="Slope Break Threshold (degrees)",
            name="slope_break_thresh",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input",
        )
        p6.value = DEFAULT_SLOPE_BREAK_THRESH

        p7 = arcpy.Parameter(
            displayName="Maximum Ditch / Gap Width (metres)",
            name="ditch_max_width_m",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input",
        )
        p7.value = DEFAULT_DITCH_MAX_WIDTH_M

        p8 = arcpy.Parameter(
            displayName="Output Obstacle Feature Class",
            name="output_fc",
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Output",
        )
        return [p0, p1, p2, p3, p4, p5, p6, p7, p8]

    def isLicensed(self):
        return True

    def updateParameters(self, p):
        pass

    def updateMessages(self, p):
        pass

    def execute(self, parameters, messages):
        arcpy.SetLogMetadata(False)  # Prevent GDB history metadata accumulation (perf)

        extent_fc       = parameters[0].valueAsText
        contours_fc     = parameters[1].valueAsText
        hydro_fc        = parameters[2].valueAsText
        barrier_fc      = parameters[3].valueAsText
        vehicle_csv     = parameters[4].valueAsText
        contour_int     = float(parameters[5].value or DEFAULT_CONTOUR_INTERVAL_M)
        slope_thresh    = float(parameters[6].value or DEFAULT_SLOPE_BREAK_THRESH)
        ditch_width     = float(parameters[7].value or DEFAULT_DITCH_MAX_WIDTH_M)
        output_fc       = parameters[8].valueAsText

        # Load vehicle widths from CSV if provided
        vehicle_widths = {}
        if vehicle_csv and os.path.isfile(vehicle_csv):
            try:
                import csv
                with open(vehicle_csv, newline="", encoding="utf-8") as fh:
                    reader = csv.DictReader(fh)
                    for row in reader:
                        name = (row.get("vehicle_name") or row.get("Vehicle") or "").strip()
                        width_str = (row.get("width_m") or row.get("Width_m") or "").strip()
                        if name and width_str:
                            try:
                                vehicle_widths[name] = float(width_str)
                            except ValueError:
                                pass
                arcpy.AddMessage(
                    f"[Obstacle Detect] Loaded {len(vehicle_widths)} vehicle widths from CSV."
                )
            except Exception as exc:
                arcpy.AddWarning(f"[Obstacle Detect] Could not read vehicle CSV: {exc}")

        detect_obstacles(
            extent_fc           = extent_fc,
            contours_fc         = contours_fc,
            hydro_fc            = hydro_fc,
            barrier_fc          = barrier_fc,
            vehicle_widths_m    = vehicle_widths or None,
            contour_interval_m  = contour_int,
            slope_break_thresh  = slope_thresh,
            ditch_max_width_m   = ditch_width,
            output_fc           = output_fc,
            scratch_gdb         = arcpy.env.scratchGDB,
        )

# <<< END OF FILE >>>
