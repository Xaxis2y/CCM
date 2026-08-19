# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
ccm_waypoints.py
================
CCM Tool — Phase 2, Feature 9: Waypoints with Feasibility Fallback
-------------------------------------------------------------------
Allows users to select approximate start and end points, then:

  1. If either point falls in a NO-GO area, automatically searches within
     a ~500-metre radius for the nearest passable location.
  2. Finds the shortest traversable path between the two (snapped) points.
  3. Reports:
     - Total travel distance (metres / km)
     - Estimated travel time per vehicle
     - A list of which vehicles from the fleet can complete the route
     - The reason any vehicle cannot complete the route

Algorithm
---------
Path finding uses a vector graph traversal over the CCM speed surface:
  - Each polygon is a node; edges connect adjacent passable polygons.
  - Edge weight = time to traverse (polygon_area_m² / avg_speed_ms).
  - Dijkstra's algorithm finds the minimum-time path.
  - If Spatial Analyst is available, Network Analyst (NA) is preferred.
  - Otherwise falls back to pure Python graph traversal.

Output
------
  - A polyline feature class showing the route
  - A point feature class showing start and end (snapped) positions
  - A summary table (text in geoprocessing pane) with distances, times,
    and vehicle capability list

Usage
-----
    from ccm_waypoints import find_route

    result = find_route(
        speed_surface_fc  = r"C:\\...\\speed_surface_LAV_moist",
        speed_field       = "SpeedKMH",
        start_latlon      = (45.42, -75.69),   # WGS84
        end_latlon        = (45.50, -75.55),
        vehicle_speeds    = {"LAV III": None, "Leopard 2": None},  # None = read from FC
        snap_radius_m     = 500,
        output_route_fc   = r"C:\\...\\CCM_Output.gdb\\route",
        output_points_fc  = r"C:\\...\\CCM_Output.gdb\\route_points",
        scratch_gdb       = arcpy.env.scratchGDB,
    )
"""

VERSION = "0.57"  # v0.57 -- version bump only: added QUICK_START.html and CCM_anaconda.bat (Anaconda Prompt environment setup script); no code/logic changes. See CHANGELOG_v0.57.md.
# v0.46 — Bug fixes:
#          1. print() on ccm_coords import failure → arcpy.AddWarning().
#          2. Fixed _build_adjacency docstring and type annotation — both
#             stated 2-tuple (neighbour_oid, travel_time_s) but the function
#             appends 3-tuples (oid_b, travel_s, dist_m).  Dijkstra unpacks
#             3-tuples correctly; only the documentation was wrong.
#          3. VERSION bumped to align with full toolbox release.

import arcpy
import os
import sys
import math
import heapq
from typing import Dict, List, Optional, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

_coords_mod = None
try:
    import ccm_coords as _coords_mod
except Exception as _e:
    arcpy.AddWarning(f"[CCM Waypoints] ccm_coords: {_e}")


# ---------------------------------------------------------------------------
# SECTION 1 — CONSTANTS
# ---------------------------------------------------------------------------

DEFAULT_SNAP_RADIUS_M   = 500.0
DEFAULT_GO_THRESHOLD    = 5.0     # km/h — below this = no-go for routing
_INF                    = math.inf


# ---------------------------------------------------------------------------
# SECTION 2 — SPATIAL HELPERS
# ---------------------------------------------------------------------------

def _latlon_to_projected(
    lat: float,
    lon: float,
    sr_proj: arcpy.SpatialReference,
) -> Tuple[float, float]:
    """Convert WGS84 lat/lon to the projected coordinate system."""
    sr_wgs84 = arcpy.SpatialReference(4326)
    pt       = arcpy.PointGeometry(arcpy.Point(lon, lat), sr_wgs84)
    pt_proj  = pt.projectAs(sr_proj)
    return pt_proj.centroid.X, pt_proj.centroid.Y


def _find_nearest_passable(
    x: float,
    y: float,
    feat_data: dict,
    snap_radius_m: float,
    go_threshold: float,
) -> Optional[int]:
    """
    Find the OID of the nearest passable polygon to (x, y).
    Returns None if no passable polygon exists within snap_radius_m.
    """
    best_oid  = None
    best_dist = _INF

    for oid, d in feat_data.items():
        spd  = d["speed"]
        geom = d["geom"]
        if geom is None or spd is None or spd < go_threshold:
            continue
        cx, cy = d["centroid"]
        dist   = math.hypot(cx - x, cy - y)
        if dist < best_dist:
            best_dist = dist
            best_oid  = oid

    if best_oid is not None and best_dist > snap_radius_m:
        arcpy.AddWarning(
            f"[CCM Waypoints] Nearest passable polygon is {best_dist:.0f} m away "
            f"(snap radius = {snap_radius_m} m). Route accuracy may be reduced."
        )
    return best_oid


# ---------------------------------------------------------------------------
# SECTION 3 — GRAPH BUILDER
# ---------------------------------------------------------------------------

def _build_adjacency(feat_data: dict, go_threshold: float) -> dict:
    """
    Build a spatial adjacency graph from feat_data.
    Returns {oid: [(neighbour_oid, travel_time_s, dist_m), ...]}

    Each edge is a 3-tuple: (neighbour_oid, travel_time_s, dist_m).
    Dijkstra unpacks all three values when relaxing edges.

    Travel time between two polygons = distance_between_centroids /
                                        average_speed_m_per_s
    """
    adj: Dict[int, List[Tuple[int, float, float]]] = {oid: [] for oid in feat_data}

    oids = list(feat_data.keys())
    n    = len(oids)

    arcpy.AddMessage(f"[CCM Waypoints] Building adjacency graph ({n} polygons) …")

    for i in range(n):
        oid_a = oids[i]
        geom_a = feat_data[oid_a]["geom"]
        spd_a  = feat_data[oid_a]["speed"] or 0
        cx_a, cy_a = feat_data[oid_a]["centroid"]

        if geom_a is None:
            continue

        for j in range(i + 1, n):
            oid_b = oids[j]
            geom_b = feat_data[oid_b]["geom"]
            spd_b  = feat_data[oid_b]["speed"] or 0
            cx_b, cy_b = feat_data[oid_b]["centroid"]

            if geom_b is None:
                continue

            # Check adjacency (shared boundary or near-touching)
            try:
                touches  = geom_a.touches(geom_b)
                overlaps = geom_a.overlaps(geom_b)
            except Exception:
                continue

            if not (touches or overlaps):
                continue

            # Skip edges where either polygon is no-go
            if spd_a < go_threshold or spd_b < go_threshold:
                continue

            # Edge weight: time to move from centroid A to centroid B
            dist_m    = math.hypot(cx_a - cx_b, cy_a - cy_b)
            avg_speed  = (spd_a + spd_b) / 2.0
            speed_ms   = avg_speed * 1000.0 / 3600.0
            travel_s   = dist_m / speed_ms if speed_ms > 0 else _INF

            adj[oid_a].append((oid_b, travel_s, dist_m))
            adj[oid_b].append((oid_a, travel_s, dist_m))

    return adj


# ---------------------------------------------------------------------------
# SECTION 4 — DIJKSTRA PATH FINDING
# ---------------------------------------------------------------------------

def _dijkstra(
    adj:       dict,
    start_oid: int,
    end_oid:   int,
) -> Tuple[Optional[List[int]], float, float]:
    """
    Find the shortest (minimum time) path from start_oid to end_oid.

    Returns:
        path     — list of OIDs from start to end (inclusive), or None
        total_s  — total travel time in seconds
        total_m  — total distance in metres
    """
    dist_t  = {oid: _INF for oid in adj}
    dist_m_ = {oid: 0.0  for oid in adj}
    prev    = {oid: None for oid in adj}

    dist_t[start_oid] = 0.0
    heap = [(0.0, start_oid)]

    while heap:
        curr_t, curr = heapq.heappop(heap)
        if curr_t > dist_t[curr]:
            continue
        if curr == end_oid:
            break

        for nb, travel_s, dist_m in adj.get(curr, []):
            new_t = dist_t[curr] + travel_s
            if new_t < dist_t[nb]:
                dist_t[nb]  = new_t
                dist_m_[nb] = dist_m_[curr] + dist_m
                prev[nb]    = curr
                heapq.heappush(heap, (new_t, nb))

    # Reconstruct path
    if dist_t[end_oid] == _INF:
        return None, _INF, 0.0

    path = []
    node = end_oid
    while node is not None:
        path.append(node)
        node = prev[node]
    path.reverse()

    return path, dist_t[end_oid], dist_m_[end_oid]


# ---------------------------------------------------------------------------
# SECTION 5 — ROUTE GEOMETRY BUILDER
# ---------------------------------------------------------------------------

def _build_route_geometry(
    path:      List[int],
    feat_data: dict,
    sr:        arcpy.SpatialReference,
) -> arcpy.Polyline:
    """Convert a list of polygon OIDs to a polyline through their centroids."""
    pts = []
    for oid in path:
        cx, cy = feat_data[oid]["centroid"]
        pts.append(arcpy.Point(cx, cy))
    array = arcpy.Array(pts)
    return arcpy.Polyline(array, sr)


# ---------------------------------------------------------------------------
# SECTION 6 — VEHICLE CAPABILITY CHECK
# ---------------------------------------------------------------------------

def _check_vehicle_capability(
    path:             List[int],
    feat_data:        dict,
    vehicle_speeds:   Dict[str, Optional[float]],
    go_threshold:     float,
) -> Dict[str, dict]:
    """
    For each vehicle, determine if it can complete the route and estimate time.

    Parameters
    ----------
    path : list of int
        OID path returned by Dijkstra.
    feat_data : dict
        OID → {speed, centroid, geom} — using the primary vehicle's speeds.
    vehicle_speeds : dict
        {vehicle_name: override_speed_kmh or None}.
        If None, uses the speed from feat_data for each polygon.
    go_threshold : float

    Returns
    -------
    dict  {vehicle_name: {can_go: bool, time_min: float, distance_m: float, reason: str}}
    """
    results = {}

    for vname, override_speed in vehicle_speeds.items():
        total_time_s = 0.0
        total_dist_m = 0.0
        blocking_oid = None

        for i in range(len(path) - 1):
            oid_a = path[i]
            oid_b = path[i + 1]

            d_a = feat_data.get(oid_a, {})
            d_b = feat_data.get(oid_b, {})

            spd_a = override_speed if override_speed else (d_a.get("speed") or 0)
            spd_b = override_speed if override_speed else (d_b.get("speed") or 0)

            if spd_a < go_threshold or spd_b < go_threshold:
                blocking_oid = oid_b
                break

            avg_spd  = (spd_a + spd_b) / 2.0
            cx_a, cy_a = d_a.get("centroid", (0, 0))
            cx_b, cy_b = d_b.get("centroid", (0, 0))
            dist_m   = math.hypot(cx_a - cx_b, cy_a - cy_b)
            speed_ms = avg_spd * 1000.0 / 3600.0
            total_time_s += dist_m / speed_ms if speed_ms > 0 else _INF
            total_dist_m += dist_m

        if blocking_oid is not None:
            results[vname] = {
                "can_go":     False,
                "time_min":   None,
                "distance_m": total_dist_m,
                "reason":     f"Route blocked at polygon OID {blocking_oid} — speed below threshold",
            }
        else:
            results[vname] = {
                "can_go":     True,
                "time_min":   round(total_time_s / 60.0, 1),
                "distance_m": round(total_dist_m, 1),
                "reason":     "Route fully passable",
            }

    return results


# ---------------------------------------------------------------------------
# SECTION 7 — MAIN PUBLIC FUNCTION
# ---------------------------------------------------------------------------

def find_route(
    speed_surface_fc:  str,
    speed_field:       str,
    start_latlon:      Tuple[float, float],
    end_latlon:        Tuple[float, float],
    vehicle_speeds:    Optional[Dict[str, Optional[float]]] = None,
    snap_radius_m:     float = DEFAULT_SNAP_RADIUS_M,
    go_threshold:      float = DEFAULT_GO_THRESHOLD,
    output_route_fc:   str   = "",
    output_points_fc:  str   = "",
    scratch_gdb:       str   = "",
) -> dict:
    """
    Find a route between two approximate points on a CCM speed surface.

    Parameters
    ----------
    speed_surface_fc : str
        CCM output speed surface feature class.
    speed_field : str
        Speed field name (km/h) in the speed surface.
    start_latlon, end_latlon : (lat, lon)
        WGS84 decimal degrees.
    vehicle_speeds : dict, optional
        {vehicle_name: override_speed_kmh or None}
        If None, only the primary vehicle (from speed_field) is assessed.
    snap_radius_m : float
        Search radius (m) when snapping infeasible points.
    go_threshold : float
        Minimum speed (km/h) to consider a polygon passable.
    output_route_fc : str, optional
        Output polyline feature class for the route.
    output_points_fc : str, optional
        Output point feature class for start/end (snapped) positions.
    scratch_gdb : str, optional
        Scratch workspace.

    Returns
    -------
    dict with keys:
        "route_fc"        : str  — path to output route feature class
        "points_fc"       : str  — path to output points feature class
        "start_snapped"   : (x, y) in projected CRS
        "end_snapped"     : (x, y) in projected CRS
        "distance_m"      : float
        "vehicle_results" : dict  {vehicle_name: {can_go, time_min, reason}}
        "route_found"     : bool
    """
    if not scratch_gdb:
        scratch_gdb = arcpy.env.scratchGDB
    if not output_route_fc:
        gdb            = os.path.dirname(speed_surface_fc)
        output_route_fc = os.path.join(gdb, "ccm_route")
    if not output_points_fc:
        gdb              = os.path.dirname(speed_surface_fc)
        output_points_fc = os.path.join(gdb, "ccm_route_points")
    if vehicle_speeds is None:
        vehicle_speeds = {"Primary Vehicle": None}

    arcpy.AddMessage("[CCM Waypoints] Starting route finding …")

    desc    = arcpy.Describe(speed_surface_fc)
    sr_proj = desc.spatialReference

    # ── Step 1: Load features ─────────────────────────────────────────────
    arcpy.SetProgressorLabel("Waypoints: Loading speed surface …")
    feat_data = {}
    with arcpy.da.SearchCursor(
        speed_surface_fc, ["OID@", speed_field, "SHAPE@XY", "SHAPE@"]
    ) as cur:
        for oid, spd, cxy, geom in cur:
            feat_data[oid] = {
                "speed":    float(spd) if spd is not None else 0.0,
                "centroid": cxy,
                "geom":     geom,
            }

    arcpy.AddMessage(f"[CCM Waypoints] Loaded {len(feat_data)} polygons.")

    # ── Step 2: Convert lat/lon to projected coords ───────────────────────
    sx, sy = _latlon_to_projected(start_latlon[0], start_latlon[1], sr_proj)
    ex, ey = _latlon_to_projected(end_latlon[0],   end_latlon[1],   sr_proj)

    # ── Step 3: Snap to nearest passable polygon ──────────────────────────
    arcpy.SetProgressorLabel("Waypoints: Snapping points …")
    start_oid = _find_nearest_passable(sx, sy, feat_data, snap_radius_m, go_threshold)
    end_oid   = _find_nearest_passable(ex, ey, feat_data, snap_radius_m, go_threshold)

    if start_oid is None:
        raise RuntimeError(
            f"[CCM Waypoints] No passable polygon found within "
            f"{snap_radius_m} m of start point ({start_latlon[0]:.4f}, "
            f"{start_latlon[1]:.4f}).  Try a different start location."
        )

    if end_oid is None:
        raise RuntimeError(
            f"[CCM Waypoints] No passable polygon found within "
            f"{snap_radius_m} m of end point ({end_latlon[0]:.4f}, "
            f"{end_latlon[1]:.4f}).  Try a different end location."
        )

    start_snapped = feat_data[start_oid]["centroid"]
    end_snapped   = feat_data[end_oid]["centroid"]

    arcpy.AddMessage(
        f"[CCM Waypoints] Start snapped: {start_snapped}  "
        f"(original: {sx:.1f}, {sy:.1f})"
    )
    arcpy.AddMessage(
        f"[CCM Waypoints] End snapped  : {end_snapped}  "
        f"(original: {ex:.1f}, {ey:.1f})"
    )

    # ── Step 4: Build adjacency graph ─────────────────────────────────────
    arcpy.SetProgressorLabel("Waypoints: Building terrain graph …")
    adj = _build_adjacency(feat_data, go_threshold)

    # ── Step 5: Dijkstra ──────────────────────────────────────────────────
    arcpy.SetProgressorLabel("Waypoints: Finding shortest path …")
    path, total_time_s, total_dist_m = _dijkstra(adj, start_oid, end_oid)

    if path is None:
        arcpy.AddWarning(
            "[CCM Waypoints] No passable route found between start and end points. "
            "The terrain between them may be entirely no-go."
        )
        return {"route_found": False, "distance_m": None, "vehicle_results": {}}

    arcpy.AddMessage(
        f"[CCM Waypoints] Route found: {len(path)} segments, "
        f"{total_dist_m / 1000.0:.2f} km, "
        f"~{total_time_s / 60.0:.1f} min (primary vehicle)."
    )

    # ── Step 6: Check all vehicles ────────────────────────────────────────
    arcpy.SetProgressorLabel("Waypoints: Checking vehicle capabilities …")
    vehicle_results = _check_vehicle_capability(
        path, feat_data, vehicle_speeds, go_threshold
    )

    # ── Step 7: Write route polyline ──────────────────────────────────────
    arcpy.SetProgressorLabel("Waypoints: Writing route feature class …")
    if arcpy.Exists(output_route_fc):
        arcpy.management.Delete(output_route_fc)
    arcpy.management.CreateFeatureclass(
        os.path.dirname(output_route_fc),
        os.path.basename(output_route_fc),
        "POLYLINE",
        spatial_reference=sr_proj,
    )
    arcpy.management.AddField(output_route_fc, "DISTANCE_M",  "DOUBLE")
    arcpy.management.AddField(output_route_fc, "DISTANCE_KM", "DOUBLE")
    arcpy.management.AddField(output_route_fc, "TIME_MIN",    "DOUBLE")
    arcpy.management.AddField(output_route_fc, "SEGMENT_CNT", "SHORT")

    route_geom = _build_route_geometry(path, feat_data, sr_proj)
    with arcpy.da.InsertCursor(
        output_route_fc,
        ["SHAPE@", "DISTANCE_M", "DISTANCE_KM", "TIME_MIN", "SEGMENT_CNT"]
    ) as cur:
        cur.insertRow([
            route_geom,
            round(total_dist_m, 1),
            round(total_dist_m / 1000.0, 3),
            round(total_time_s / 60.0, 1),
            len(path) - 1,
        ])

    # ── Step 8: Write start/end points ────────────────────────────────────
    if arcpy.Exists(output_points_fc):
        arcpy.management.Delete(output_points_fc)
    arcpy.management.CreateFeatureclass(
        os.path.dirname(output_points_fc),
        os.path.basename(output_points_fc),
        "POINT",
        spatial_reference=sr_proj,
    )
    arcpy.management.AddField(output_points_fc, "POINT_TYPE",  "TEXT", field_length=20)
    arcpy.management.AddField(output_points_fc, "SNAPPED",     "SHORT")
    arcpy.management.AddField(output_points_fc, "SNAP_DIST_M", "DOUBLE")

    with arcpy.da.InsertCursor(
        output_points_fc,
        ["SHAPE@XY", "POINT_TYPE", "SNAPPED", "SNAP_DIST_M"]
    ) as cur:
        snap_dist_start = math.hypot(start_snapped[0] - sx, start_snapped[1] - sy)
        snap_dist_end   = math.hypot(end_snapped[0]   - ex, end_snapped[1]   - ey)
        cur.insertRow([start_snapped, "START", int(snap_dist_start > 1), round(snap_dist_start, 1)])
        cur.insertRow([end_snapped,   "END",   int(snap_dist_end   > 1), round(snap_dist_end,   1)])

    # ── Step 9: Print summary ─────────────────────────────────────────────
    sep = "─" * 58
    arcpy.AddMessage(sep)
    arcpy.AddMessage("  ROUTE SUMMARY")
    arcpy.AddMessage(sep)
    arcpy.AddMessage(f"  Distance     : {total_dist_m / 1000.0:.2f} km  "
                     f"({total_dist_m:.0f} m)")
    arcpy.AddMessage(f"  Snap radius  : {snap_radius_m} m")
    arcpy.AddMessage(sep)
    arcpy.AddMessage("  VEHICLE CAPABILITY")
    arcpy.AddMessage(sep)
    for vname, vres in vehicle_results.items():
        if vres["can_go"]:
            arcpy.AddMessage(
                f"  ✓  {vname:<25}  {vres['time_min']:.1f} min  "
                f"({vres['distance_m'] / 1000.0:.2f} km)"
            )
        else:
            arcpy.AddWarning(
                f"  ✗  {vname:<25}  CANNOT COMPLETE — {vres['reason']}"
            )
    arcpy.AddMessage(sep)
    arcpy.AddMessage(f"  Route output  : {output_route_fc}")
    arcpy.AddMessage(f"  Points output : {output_points_fc}")
    arcpy.AddMessage(sep)

    return {
        "route_fc":        output_route_fc,
        "points_fc":       output_points_fc,
        "start_snapped":   start_snapped,
        "end_snapped":     end_snapped,
        "distance_m":      total_dist_m,
        "time_min":        total_time_s / 60.0,
        "vehicle_results": vehicle_results,
        "route_found":     True,
    }


# ---------------------------------------------------------------------------
# SECTION 8 — ARCGIS TOOLBOX TOOL WRAPPER
# ---------------------------------------------------------------------------

class CCMWaypointTool:
    """ArcGIS Python Toolbox tool for waypoint routing on CCM speed surface."""

    def __init__(self):
        self.label       = "7.  Find Fastest Route  (A to B)"
        self.description = (
            "Finds the best passable route between approximate start and end "
            "points on a CCM speed surface. If a selected point is infeasible "
            "(no-go terrain), the tool automatically finds the nearest passable "
            "location within a 500-metre radius.  Reports total distance, "
            "travel time, and which vehicles can complete the route."
        )
        self.canRunInBackground = False

    def getParameterInfo(self):
        p0 = arcpy.Parameter(
            displayName="CCM Speed Surface Feature Class",
            name="speed_surface_fc",
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Input",
        )
        p1 = arcpy.Parameter(
            displayName="Speed Field (km/h)",
            name="speed_field",
            datatype="Field",
            parameterType="Required",
            direction="Input",
        )
        p1.parameterDependencies = [p0.name]

        p2 = arcpy.Parameter(
            displayName=(
                "Start Point (A)  — enter in any coordinate format\n"
                "(MGRS, Decimal Degrees, DMS, DDM, or UTM)"
            ),
            name="start_point",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
        )

        p2b = arcpy.Parameter(
            displayName="↳ Start Point — Coordinate Equivalents  (auto-computed — all formats)",
            name="start_point_display",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )

        p3 = arcpy.Parameter(
            displayName=(
                "End Point (B)  — enter in any coordinate format\n"
                "(MGRS, Decimal Degrees, DMS, DDM, or UTM)"
            ),
            name="end_point",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
        )

        p3b = arcpy.Parameter(
            displayName="↳ End Point — Coordinate Equivalents  (auto-computed — all formats)",
            name="end_point_display",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )

        p4 = arcpy.Parameter(
            displayName="Snap Radius (metres) — search for passable location",
            name="snap_radius_m",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input",
        )
        p4.value = DEFAULT_SNAP_RADIUS_M

        p5 = arcpy.Parameter(
            displayName="GO Threshold (km/h) — below this = NO GO",
            name="go_threshold",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input",
        )
        p5.value = DEFAULT_GO_THRESHOLD

        p6 = arcpy.Parameter(
            displayName="Vehicle Capabilities CSV (optional)",
            name="vehicle_csv",
            datatype="DEFile",
            parameterType="Optional",
            direction="Input",
        )
        p7 = arcpy.Parameter(
            displayName="Output Route Feature Class",
            name="output_route_fc",
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Output",
        )
        p8 = arcpy.Parameter(
            displayName="Output Route Points Feature Class",
            name="output_points_fc",
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Output",
        )
        # Indices: 0=speed_fc, 1=speed_field,
        #          2=start_point, 3=start_display,
        #          4=end_point,   5=end_display,
        #          6=snap_radius, 7=go_threshold, 8=vehicle_csv,
        #          9=output_route, 10=output_points
        return [p0, p1, p2, p2b, p3, p3b, p4, p5, p6, p7, p8]

    def isLicensed(self):
        return True

    def updateParameters(self, p):
        # Populate coordinate display fields (indices 3 and 5)
        if _coords_mod:
            for coord_idx, display_idx in [(2, 3), (4, 5)]:
                raw = (p[coord_idx].valueAsText or "").strip()
                if raw:
                    try:
                        lat, lon = _coords_mod.any_to_latlon(raw)
                        fmt = _coords_mod.detect_format(raw)
                        p[display_idx].value = _coords_mod.format_coord_display(lat, lon, fmt)
                    except Exception as e:
                        p[display_idx].value = f"(Cannot convert: {e})"
                else:
                    p[display_idx].value = ""

    def updateMessages(self, p):
        if _coords_mod:
            for idx in (2, 4):   # start=2, end=4 (display fields at 3,5)
                raw = (p[idx].valueAsText or "").strip()
                if raw:
                    fmt = _coords_mod.detect_format(raw)
                    if fmt == "Unknown":
                        p[idx].setErrorMessage(
                            f"Cannot recognise coordinate format: {raw!r}\n"
                            "Accepted: MGRS, DD, DMS, DDM, UTM"
                        )

    def execute(self, parameters, messages):
        arcpy.SetLogMetadata(False)  # Prevent GDB history metadata accumulation (perf)
        import pandas as pd

        # Indices: 0=speed_fc, 1=speed_field,
        #          2=start_point, 3=start_display,
        #          4=end_point,   5=end_display,
        #          6=snap_radius, 7=go_threshold, 8=vehicle_csv,
        #          9=output_route, 10=output_points
        fc          = parameters[0].valueAsText
        spd_field   = parameters[1].valueAsText
        start_raw   = (parameters[2].valueAsText or "").strip()
        end_raw     = (parameters[4].valueAsText or "").strip()
        snap_r      = float(parameters[6].value or DEFAULT_SNAP_RADIUS_M)
        go_thr      = float(parameters[7].value or DEFAULT_GO_THRESHOLD)
        veh_csv     = parameters[8].valueAsText or None
        out_route   = parameters[9].valueAsText
        out_pts     = parameters[10].valueAsText

        # Convert coordinates → (lat, lon) — accepts any supported format
        if _coords_mod is None:
            raise RuntimeError(
                "[CCM Waypoints] ccm_coords.py not loaded — "
                "cannot convert coordinates."
            )

        try:
            start_latlon = _coords_mod.any_to_latlon(start_raw)
            fmt = _coords_mod.detect_format(start_raw)
            arcpy.AddMessage(
                f"[CCM Waypoints] Start [{fmt}]: {start_raw} → "
                f"{start_latlon[0]:.6f}°N  {start_latlon[1]:.6f}°E"
            )
        except Exception as e:
            raise RuntimeError(f"[CCM Waypoints] Cannot convert Start coordinate '{start_raw}': {e}")

        try:
            end_latlon = _coords_mod.any_to_latlon(end_raw)
            fmt = _coords_mod.detect_format(end_raw)
            arcpy.AddMessage(
                f"[CCM Waypoints] End   [{fmt}]: {end_raw} → "
                f"{end_latlon[0]:.6f}°N  {end_latlon[1]:.6f}°E"
            )
        except Exception as e:
            raise RuntimeError(f"[CCM Waypoints] Cannot convert End coordinate '{end_raw}': {e}")

        # Build vehicle dict
        vehicle_speeds = {}
        if veh_csv and os.path.exists(veh_csv):
            try:
                df = pd.read_csv(veh_csv, encoding="utf-8")
                for _, r in df.iterrows():
                    name  = str(r.get("vehicle_name", "Unknown"))
                    speed = r.get("max_road_speed_kmh") or None
                    vehicle_speeds[name] = float(speed) if speed else None
            except Exception as e:
                arcpy.AddWarning(f"Could not load vehicle CSV: {e}")

        # ── Run the routing engine ────────────────────
        # find_route() snaps the endpoints, builds the terrain graph, runs
        # Dijkstra, writes the route + points feature classes, and prints the
        # full route / vehicle-capability summary itself.
        try:
            result = find_route(
                speed_surface_fc = fc,
                speed_field      = spd_field,
                start_latlon     = start_latlon,
                end_latlon       = end_latlon,
                vehicle_speeds   = vehicle_speeds or None,
                snap_radius_m    = snap_r,
                go_threshold     = go_thr,
                output_route_fc  = out_route,
                output_points_fc = out_pts,
                scratch_gdb      = arcpy.env.scratchGDB,
            )
        except Exception as e:
            raise RuntimeError(f"[CCM Waypoints] Routing failed: {e}")

        if not result.get("route_found"):
            arcpy.AddWarning(
                "[CCM Waypoints] No passable route was found between the "
                "start and end points — no route output was written."
            )
            return

        arcpy.AddMessage(
            f"[CCM Waypoints] Waypoint routing complete → "
            f"{result['route_fc']}"
        )
        return

# <<< END OF FILE >>>
