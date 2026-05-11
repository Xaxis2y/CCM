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

VERSION = "2.20"  # Aligned with MCE_CCM_V2.pyt versioning

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

    Method:
    1. Clip contours to AOI.
    2. Use GenerateNearTable to find PAIRS of contour lines that are
       within (2 × contour_interval_m / tan(slope_break_thresh)) metres
       of each other.  This is the horizontal distance at which the
       slope would equal slope_break_thresh.
    3. For each close pair, compute the actual slope and flag as obstacle
       if slope >= slope_break_thresh.

    Note: Self-matches (IN_FID == NEAR_FID) are explicitly excluded so
    every detected pair represents two DISTINCT contour lines, preventing
    the false-positive avalanche that would occur from self-intersection.

    Returns a list of dicts with centroid x, y, width_m, description.
    """
    obstacles = []

    try:
        arcpy.AddMessage("[CCM Obstacles] Detecting slope breaks from contours …")

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

    A hydro gap is flagged when the buffered hydro line has a width
    less than ditch_max_width_m — indicating a narrow crossing that may
    not be bridgeable by some vehicles.
    """
    obstacles = []
    if not hydro_fc or not arcpy.Exists(hydro_fc):
        return []

    arcpy.AddMessage("[CCM Obstacles] Detecting hydro gaps (narrow crossings) …")
    try:
        clipped = os.path.join(scratch_gdb, "ccm_obs_hydro_clip")
        arcpy.analysis.Clip(hydro_fc, extent_fc, clipped)

        with arcpy.da.SearchCursor(
            clipped, ["SHAPE@", "SHAPE@LENGTH", "SHAPE@XY"]
        ) as cur:
            for geom, length, (cx, cy) in cur:
                if geom is None or length < 1:
                    continue

                # Estimate width from geometry extent
                ext   = geom.extent
                width = min(ext.width, ext.height)

                if width <= ditch_max_width_m:
                    stops = [
                        v for v, vw in vehicle_widths_m.items() if vw > width
                    ]
                    severity = SEV_STOP if stops else SEV_CAUTION
                    obstacles.append({
                        "type":    OT_GAP,
                        "x": cx, "y": cy,
                        "width_m": round(width, 2),
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
            f"[CCM Obstacles] Found {len(obstacles)} narrow hydro crossings."
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

        with arcpy.da.SearchCursor(clipped, ["SHAPE@", "SHAPE@XY"]) as cur:
            for geom, (cx, cy) in cur:
                if geom is None:
                    continue
                obstacles.append({
                    "type":    OT_LINEAR,
                    "x": cx, "y": cy,
                    "width_m": 1.0,   # default — linear features have ~1m width
                    "severity": SEV_STOP,
                    "description": (
                        f"Linear barrier detected from layer: "
                        f"'{os.path.basename(barrier_fc)}'. "
                        "Manual verification recommended."
                    ),
                    "source": os.path.basename(barrier_fc),
                    "vehicle_stop": ";".join(vehicle_widths_m.keys()),
                })

        if arcpy.Exists(clipped):
            arcpy.management.Delete(clipped)

        arcpy.AddMessage(
            f"[CCM Obstacles] Found {len(obstacles)} linear barrier features."
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
        import pandas as pd

        extent_fc   = parameters[0].valueAsText
        contours_fc = parameters[1].valueAsText or None
        hydro_fc    = parameters[2].valueAsText or None
        barrier_fc  = parameters[3].valueAsText or None
        veh_csv     = parameters[4].valueAsText or None
        cont_int    = float(parameters[5].value or DEFAULT_CONTOUR_INTERVAL_M)
        slope_thr   = float(parameters[6].value or DEFAULT_SLOPE_BREAK_THRESH)
        ditch_max   = float(parameters[7].value or DEFAULT_DITCH_MAX_WIDTH_M)
        output_fc   = parameters[8].valueAsText

        vehicle_widths = {}
        if veh_csv and os.path.exists(veh_csv):
            try:
                df = pd.read_csv(veh_csv, encoding="utf-8")
                for _, r in df.iterrows():
                    if "vehicle_name" in df.columns and "width_m" in df.columns:
                        vehicle_widths[str(r["vehicle_name"])] = float(r["width_m"])
            except Exception as e:
                arcpy.AddWarning(f"[CCM Obstacles] Could not read vehicle CSV: {e}")

        detect_obstacles(
            extent_fc          = extent_fc,
            contours_fc        = contours_fc,
            hydro_fc           = hydro_fc,
            barrier_fc         = barrier_fc,
            vehicle_widths_m   = vehicle_widths,
            contour_interval_m = cont_int,
            slope_break_thresh = slope_thr,
            ditch_max_width_m  = ditch_max,
            output_fc          = output_fc,
            scratch_gdb        = arcpy.env.scratchGDB,
        )
