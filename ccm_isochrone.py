"""
ccm_isochrone.py
================
CCM Tool — Phase 2, Feature 6: Time-Distance Maps (Isochrones)
---------------------------------------------------------------
Generates isochrone polygons from a CCM speed-surface feature class.
An isochrone shows all locations reachable from a start point within a
given travel time (e.g. 30 min, 1 hr, 2 hr).

This is essential for mission timing and fuel planning because it
answers "How far can I get in 2 hours?" not just "Can I go there?"

Algorithm Overview
------------------
The isochrone is computed on the CCM speed surface using a
raster-based cost-distance approach:

  1. Convert the vector speed surface (speed_kmh field) to a raster
     COST surface (time_per_cell = cell_size_m / speed_ms).
  2. Run arcpy.sa.DistanceAccumulation() (Pro 3.5+) or CostDistance() (legacy) from the start point.
  3. Reclassify into time-bands (0–30min, 30–60min, 60–120min, etc.).
  4. Convert reclassified raster to polygon isochrone rings.
  5. Optionally smooth the polygons for display.

Requirements
------------
  - ArcGIS Pro Spatial Analyst extension (for DistanceAccumulation / CostDistance / raster ops)
  - OR fallback vector method using network traversal (slower, no extension)

The module detects licence availability and chooses automatically.

Usage
-----
    from ccm_isochrone import generate_isochrones

    generate_isochrones(
        speed_surface_fc = r"C:\\...\\speed_surface_LAV_moist",
        speed_field      = "SpeedKMH",
        start_point      = (45.42, -75.69),   # WGS84 lat, lon
        time_bands_min   = [30, 60, 120, 240],
        cell_size_m      = 50,
        output_fc        = r"C:\\...\\CCM_Output.gdb\\isochrones_LAV",
        scratch_gdb      = arcpy.env.scratchGDB,
    )
"""

VERSION = "0.46"  # v0.46 — Version bump aligned with toolbox-wide v0.46 release.
# v0.46 — Bug fixes:
#          1. print() on ccm_coords import failure → arcpy.AddWarning().
#          2. Removed unused "SHAPE@XY" token from SearchCursor in
#             _snap_point_to_feature_class (only SHAPE@ is used).
#          3. VERSION bumped to align with full toolbox release.

import arcpy
import os
import sys
import math
from typing import List, Optional, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

_coords_mod = None
try:
    import ccm_coords as _coords_mod
except Exception as _e:
    arcpy.AddWarning(f"[CCM Isochrone] ccm_coords: {_e}")


# ---------------------------------------------------------------------------
# SECTION 1 — CONSTANTS & DEFAULTS
# ---------------------------------------------------------------------------

DEFAULT_TIME_BANDS_MIN = [30, 60, 120, 240]   # minutes
DEFAULT_CELL_SIZE_M    = 50                    # raster resolution
MIN_SPEED_KMH          = 0.1                   # avoid divide-by-zero
_NO_GO_LABEL           = "NO GO"               # speed = 0 / missing


# ---------------------------------------------------------------------------
# SECTION 2 — HELPER FUNCTIONS
# ---------------------------------------------------------------------------

def _check_spatial_analyst() -> bool:
    """Return True if the Spatial Analyst extension is available."""
    try:
        if arcpy.CheckExtension("Spatial") == "Available":
            arcpy.CheckOutExtension("Spatial")
            return True
        return False
    except Exception:
        return False


def _snap_point_to_feature_class(
    lat: float,
    lon: float,
    fc: str,
    snap_radius_m: float = 500,
) -> Tuple[float, float]:
    """
    Snap (lat, lon) to the nearest passable feature in fc.
    Returns snapped (x, y) in the FC's projected coordinate system.
    """
    sr_wgs84  = arcpy.SpatialReference(4326)
    pt_wgs84  = arcpy.PointGeometry(arcpy.Point(lon, lat), sr_wgs84)
    desc      = arcpy.Describe(fc)
    sr_proj   = desc.spatialReference
    pt_proj   = pt_wgs84.projectAs(sr_proj)

    closest_x, closest_y = pt_proj.centroid.X, pt_proj.centroid.Y
    closest_dist = math.inf

    with arcpy.da.SearchCursor(fc, ["SHAPE@"]) as cur:
        for row in cur:
            geom = row[0]
            if geom is None:
                continue
            dist = geom.distanceTo(pt_proj)
            if dist < closest_dist:
                closest_dist = dist
                cx, cy = geom.centroid.X, geom.centroid.Y
                closest_x, closest_y = cx, cy

    if closest_dist > snap_radius_m:
        arcpy.AddWarning(
            f"[CCM Isochrone] Nearest passable feature is {closest_dist:.0f}m away "
            f"from the start point — this may affect isochrone accuracy."
        )
    return closest_x, closest_y


def _speed_to_cost(speed_kmh: Optional[float], cell_size_m: float) -> float:
    """
    Convert speed (km/h) to travel cost (seconds per cell).

    Cost = cell_size_m / speed_m_per_s
         = cell_size_m / (speed_kmh * 1000 / 3600)

    No-go areas (speed = 0 or None) are assigned a very high cost
    (not NoData, so the cost surface stays contiguous).
    """
    if speed_kmh is None or speed_kmh <= 0:
        return 1e9   # effectively impassable
    speed_ms = max(speed_kmh, MIN_SPEED_KMH) * 1000.0 / 3600.0
    return cell_size_m / speed_ms


def _make_time_band_labels(time_bands_min: List[int]) -> List[str]:
    """Build human-readable labels for each time band."""
    labels = []
    prev = 0
    for t in sorted(time_bands_min):
        if t < 60:
            labels.append(f"{prev}–{t} min")
        else:
            h = t // 60
            m = t % 60
            if prev < 60:
                p_str = f"{prev} min"
            else:
                ph = prev // 60
                pm = prev % 60
                p_str = f"{ph}h{pm:02d}" if pm else f"{ph}h"
            t_str = f"{h}h{m:02d}" if m else f"{h}h"
            labels.append(f"{p_str}–{t_str}")
        prev = t
    labels.append(f"> {_format_time(sorted(time_bands_min)[-1])}")
    return labels


def _format_time(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} min"
    h = minutes // 60
    m = minutes % 60
    return f"{h}h{m:02d}" if m else f"{h}h"


# ---------------------------------------------------------------------------
# SECTION 3 — SPATIAL ANALYST PATH (best quality)
# ---------------------------------------------------------------------------

def _generate_isochrones_sa(
    speed_surface_fc: str,
    speed_field:      str,
    start_xy:         Tuple[float, float],
    time_bands_min:   List[int],
    cell_size_m:      float,
    output_fc:        str,
    scratch_gdb:      str,
) -> str:
    """
    Generate isochrones using arcpy Spatial Analyst.

    Uses DistanceAccumulation (Pro 3.5+) when available — up to 50× faster
    than the legacy CostDistance tool on large rasters. Falls back to
    CostDistance on older Pro versions automatically.
    """
    import arcpy.sa as sa

    # DistanceAccumulation was introduced in Pro 3.5 and is dramatically faster.
    # Detect availability: if the function exists in arcpy.sa, use it.
    _use_dist_accum = hasattr(sa, "DistanceAccumulation")
    if _use_dist_accum:
        arcpy.AddMessage(
            "[CCM Isochrone] Using Spatial Analyst (DistanceAccumulation — Pro 3.5+)."
        )
    else:
        arcpy.AddMessage(
            "[CCM Isochrone] Using Spatial Analyst (CostDistance — legacy fallback)."
        )

    # ── Step 1: Convert speed surface to COST raster ─────────────────────
    arcpy.AddMessage("[CCM Isochrone] Converting speed surface to cost raster …")

    cost_fc = os.path.join(scratch_gdb, "ccm_iso_cost_fc")
    if arcpy.Exists(cost_fc):
        arcpy.management.Delete(cost_fc)
    arcpy.management.CopyFeatures(speed_surface_fc, cost_fc)

    # Add a COST field
    arcpy.management.AddField(cost_fc, "ISO_COST", "DOUBLE")
    with arcpy.da.UpdateCursor(cost_fc, [speed_field, "ISO_COST"]) as cur:
        for row in cur:
            row[1] = _speed_to_cost(row[0], cell_size_m)
            cur.updateRow(row)

    cost_raster_path = os.path.join(scratch_gdb, "ccm_iso_cost_ras")
    arcpy.conversion.FeatureToRaster(
        cost_fc, "ISO_COST", cost_raster_path, cell_size_m
    )
    cost_raster = sa.Raster(cost_raster_path)

    # ── Step 2: Create source point raster ───────────────────────────────
    desc    = arcpy.Describe(speed_surface_fc)
    sr_proj = desc.spatialReference

    src_pt_fc = os.path.join(scratch_gdb, "ccm_iso_src")
    if arcpy.Exists(src_pt_fc):
        arcpy.management.Delete(src_pt_fc)
    arcpy.management.CreateFeatureclass(
        scratch_gdb, "ccm_iso_src", "POINT", spatial_reference=sr_proj
    )
    with arcpy.da.InsertCursor(src_pt_fc, ["SHAPE@XY"]) as cur:
        cur.insertRow([start_xy])

    src_raster_path = os.path.join(scratch_gdb, "ccm_iso_src_ras")
    arcpy.conversion.FeatureToRaster(src_pt_fc, "OBJECTID", src_raster_path, cell_size_m)
    src_raster = sa.Raster(src_raster_path)

    # ── Step 3: Distance accumulation (Pro 3.5+) or legacy CostDistance ──────
    cost_dist_path = os.path.join(scratch_gdb, "ccm_iso_costdist")
    if _use_dist_accum:
        arcpy.AddMessage("[CCM Isochrone] Running DistanceAccumulation …")
        # DistanceAccumulation replaces CostDistance in Pro 3.5+.
        # Source raster → cost raster → accumulated travel-time surface.
        cost_dist = sa.DistanceAccumulation(
            in_source_data          = src_raster,
            in_cost_raster          = cost_raster,
        )
    else:
        arcpy.AddMessage("[CCM Isochrone] Running CostDistance (legacy) …")
        cost_dist = sa.CostDistance(src_raster, cost_raster)
    cost_dist.save(cost_dist_path)

    # ── Step 4: Reclassify into time bands (seconds) ──────────────────────
    arcpy.AddMessage("[CCM Isochrone] Reclassifying into time bands …")
    sorted_bands = sorted(time_bands_min)
    # Build reclassify remap: 0 → band1_sec, band1_sec → band2_sec, etc.
    remap_ranges = []
    prev_sec = 0
    for i, t_min in enumerate(sorted_bands, start=1):
        t_sec = t_min * 60
        remap_ranges.append([prev_sec, t_sec, i])
        prev_sec = t_sec
    remap_ranges.append([prev_sec, 1e9, len(sorted_bands) + 1])

    remap  = arcpy.sa.RemapRange(remap_ranges)
    reclass = sa.Reclassify(cost_dist_path, "Value", remap, "NODATA")
    reclass_path = os.path.join(scratch_gdb, "ccm_iso_reclass")
    reclass.save(reclass_path)

    # ── Step 5: Convert to polygon ────────────────────────────────────────
    arcpy.AddMessage("[CCM Isochrone] Converting to polygon isochrones …")
    if arcpy.Exists(output_fc):
        arcpy.management.Delete(output_fc)

    arcpy.conversion.RasterToPolygon(
        reclass_path, output_fc, "NO_SIMPLIFY", "Value"
    )

    # ── Step 6: Add time-band label field ─────────────────────────────────
    arcpy.management.AddField(output_fc, "TIME_BAND",  "TEXT", field_length=40)
    arcpy.management.AddField(output_fc, "MAX_MIN",    "SHORT")
    arcpy.management.AddField(output_fc, "BAND_ORDER", "SHORT")

    labels = _make_time_band_labels(sorted_bands)
    band_map = {i + 1: (sorted_bands[i], labels[i]) for i in range(len(sorted_bands))}
    band_map[len(sorted_bands) + 1] = (9999, labels[-1])

    with arcpy.da.UpdateCursor(output_fc, ["gridcode", "TIME_BAND", "MAX_MIN", "BAND_ORDER"]) as cur:
        for row in cur:
            code = row[0]
            if code in band_map:
                t_min, label = band_map[code]
                row[1] = label
                row[2] = t_min
                row[3] = code
            else:
                row[1] = "Unknown"
                row[2] = -1
                row[3] = -1
            cur.updateRow(row)

    # Clean up scratch
    for tmp in [cost_fc, cost_raster_path, src_pt_fc, src_raster_path,
                cost_dist_path, reclass_path]:
        if arcpy.Exists(tmp):
            try:
                arcpy.management.Delete(tmp)
            except Exception:
                pass

    arcpy.AddMessage(f"[CCM Isochrone] Isochrones saved to: {output_fc}")
    return output_fc


# ---------------------------------------------------------------------------
# SECTION 4 — VECTOR FALLBACK PATH (no Spatial Analyst)
# ---------------------------------------------------------------------------

def _generate_isochrones_vector(
    speed_surface_fc: str,
    speed_field:      str,
    start_xy:         Tuple[float, float],
    time_bands_min:   List[int],
    output_fc:        str,
    scratch_gdb:      str,
) -> str:
    """
    Fallback isochrone method using vector polygon traversal.
    Works at all ArcGIS Pro licence levels (no Spatial Analyst needed).

    This method grows rings outward from the start point by iteratively
    selecting and dissolving adjacent polygons whose cumulative travel
    time falls within each band.

    Note: Less accurate than the raster method — polygon edges are used
    as travel boundaries.  Recommended cell_size fallback for raster is
    always preferred if SA is available.
    """
    arcpy.AddMessage(
        "[CCM Isochrone] Spatial Analyst not available. "
        "Using vector polygon traversal (fallback method)."
    )

    desc    = arcpy.Describe(speed_surface_fc)
    sr_proj = desc.spatialReference
    sorted_bands = sorted(time_bands_min)

    # ── Tag each polygon with travel time from start ──────────────────────
    # Strategy: BFS-style traversal.  Start from the polygon containing
    # the start point; measure time to adjacent polygons using their
    # centroid distances and average speeds.

    tagged_fc = os.path.join(scratch_gdb, "ccm_iso_tagged")
    if arcpy.Exists(tagged_fc):
        arcpy.management.Delete(tagged_fc)
    arcpy.management.CopyFeatures(speed_surface_fc, tagged_fc)
    arcpy.management.AddField(tagged_fc, "TRAVEL_MIN",  "DOUBLE")
    arcpy.management.AddField(tagged_fc, "ISO_VISITED", "SHORT")

    # Build dict: OID → (speed_kmh, centroid_xy, geometry)
    feat_data = {}
    with arcpy.da.SearchCursor(tagged_fc, ["OID@", speed_field, "SHAPE@XY", "SHAPE@"]) as cur:
        for oid, spd, cxy, geom in cur:
            feat_data[oid] = {
                "speed":    spd if (spd and spd > 0) else 0,
                "centroid": cxy,
                "geom":     geom,
            }

    # Find start OID
    start_pt = arcpy.PointGeometry(arcpy.Point(*start_xy), sr_proj)
    start_oid = None
    min_dist  = math.inf
    for oid, d in feat_data.items():
        g = d["geom"]
        if g is None:
            continue
        dist = g.distanceTo(start_pt)
        if dist < min_dist:
            min_dist  = dist
            start_oid = oid

    if start_oid is None:
        raise RuntimeError("[CCM Isochrone] Could not locate start point within speed surface.")
        return output_fc

    # BFS
    import heapq
    visited    = {}   # oid → min_travel_min
    heap       = [(0.0, start_oid)]
    visited[start_oid] = 0.0

    while heap:
        curr_time, curr_oid = heapq.heappop(heap)
        if curr_time > visited.get(curr_oid, math.inf):
            continue
        curr_data = feat_data[curr_oid]
        curr_geom = curr_data["geom"]
        if curr_geom is None:
            continue

        # Find touching neighbours
        for nb_oid, nb_data in feat_data.items():
            if nb_oid == curr_oid:
                continue
            nb_geom = nb_data["geom"]
            if nb_geom is None:
                continue
            if not curr_geom.touches(nb_geom) and not curr_geom.overlaps(nb_geom):
                continue

            nb_speed = nb_data["speed"]
            if nb_speed <= 0:
                continue

            # Time to traverse this neighbour polygon (centroid–centroid distance)
            dx = curr_data["centroid"][0] - nb_data["centroid"][0]
            dy = curr_data["centroid"][1] - nb_data["centroid"][1]
            dist_m    = math.hypot(dx, dy)
            speed_ms  = nb_speed * 1000.0 / 3600.0
            travel_s  = dist_m / speed_ms
            travel_min = curr_time + travel_s / 60.0

            if travel_min < visited.get(nb_oid, math.inf):
                visited[nb_oid] = travel_min
                heapq.heappush(heap, (travel_min, nb_oid))

    # Write travel times back
    with arcpy.da.UpdateCursor(tagged_fc, ["OID@", "TRAVEL_MIN"]) as cur:
        for row in cur:
            row[1] = visited.get(row[0], -1)
            cur.updateRow(row)

    # ── Dissolve into time bands ──────────────────────────────────────────
    if arcpy.Exists(output_fc):
        arcpy.management.Delete(output_fc)

    arcpy.management.AddField(tagged_fc, "TIME_BAND",  "TEXT", field_length=40)
    arcpy.management.AddField(tagged_fc, "BAND_ORDER", "SHORT")

    labels = _make_time_band_labels(sorted_bands)
    with arcpy.da.UpdateCursor(tagged_fc, ["TRAVEL_MIN", "TIME_BAND", "BAND_ORDER"]) as cur:
        for row in cur:
            t = row[0]
            if t < 0:
                row[1] = "Unreachable"
                row[2] = 99
            else:
                assigned = False
                for i, band_min in enumerate(sorted_bands):
                    if t <= band_min:
                        row[1] = labels[i]
                        row[2] = i + 1
                        assigned = True
                        break
                if not assigned:
                    row[1] = labels[-1]
                    row[2] = len(sorted_bands) + 1
            cur.updateRow(row)

    arcpy.management.Dissolve(
        tagged_fc, output_fc,
        dissolve_field=["TIME_BAND", "BAND_ORDER"],
        statistics_fields=[],
    )

    arcpy.management.AddField(output_fc, "MAX_MIN", "SHORT")
    with arcpy.da.UpdateCursor(output_fc, ["BAND_ORDER", "MAX_MIN"]) as cur:
        for row in cur:
            idx = row[0] - 1
            if 0 <= idx < len(sorted_bands):
                row[1] = sorted_bands[idx]
            else:
                row[1] = 9999
            cur.updateRow(row)

    if arcpy.Exists(tagged_fc):
        arcpy.management.Delete(tagged_fc)

    arcpy.AddMessage(f"[CCM Isochrone] Isochrones (vector method) saved to: {output_fc}")
    return output_fc


# ---------------------------------------------------------------------------
# SECTION 5 — MAIN PUBLIC FUNCTION
# ---------------------------------------------------------------------------

def generate_isochrones(
    speed_surface_fc: str,
    speed_field:      str,
    start_point:      Tuple[float, float],
    time_bands_min:   Optional[List[int]] = None,
    cell_size_m:      float = DEFAULT_CELL_SIZE_M,
    output_fc:        str   = "",
    scratch_gdb:      str   = "",
) -> str:
    """
    Generate isochrone time-band polygons from a CCM speed surface.

    Parameters
    ----------
    speed_surface_fc : str
        Path to the CCM output speed surface feature class.
    speed_field : str
        Name of the field containing vehicle speed (km/h).
    start_point : (lat, lon)
        WGS84 decimal degrees of the origin point.
    time_bands_min : list of int, optional
        Travel time cut-offs in minutes.  Default: [30, 60, 120, 240].
    cell_size_m : float, optional
        Raster cell size in metres (Spatial Analyst path only).  Default: 50.
    output_fc : str, optional
        Path for the output isochrone feature class.  Auto-generated if empty.
    scratch_gdb : str, optional
        Scratch workspace.  Uses arcpy.env.scratchGDB if empty.

    Returns
    -------
    str  — path to the output isochrone feature class.
    """
    if time_bands_min is None:
        time_bands_min = DEFAULT_TIME_BANDS_MIN

    if not scratch_gdb:
        scratch_gdb = arcpy.env.scratchGDB

    if not output_fc:
        gdb  = os.path.dirname(speed_surface_fc)
        base = os.path.basename(speed_surface_fc)
        output_fc = os.path.join(gdb, f"iso_{base}")

    arcpy.AddMessage(
        f"[CCM Isochrone] Generating isochrones from '{speed_surface_fc}'. "
        f"Time bands: {time_bands_min} min."
    )

    # ── Snap start point to nearest passable feature ──────────────────────
    arcpy.SetProgressorLabel("Isochrone: Locating start point …")
    start_xy = _snap_point_to_feature_class(
        start_point[0], start_point[1], speed_surface_fc
    )
    arcpy.AddMessage(
        f"[CCM Isochrone] Start point snapped to "
        f"({start_xy[0]:.1f}, {start_xy[1]:.1f}) in projected CRS."
    )

    # ── Choose method ─────────────────────────────────────────────────────
    arcpy.SetProgressorLabel("Isochrone: Computing travel cost …")
    if _check_spatial_analyst():
        return _generate_isochrones_sa(
            speed_surface_fc, speed_field, start_xy,
            time_bands_min, cell_size_m, output_fc, scratch_gdb,
        )
    else:
        return _generate_isochrones_vector(
            speed_surface_fc, speed_field, start_xy,
            time_bands_min, output_fc, scratch_gdb,
        )


# ---------------------------------------------------------------------------
# SECTION 6 — ARCGIS TOOLBOX TOOL WRAPPER
# ---------------------------------------------------------------------------

class CCMIsochroneTool:
    """ArcGIS Python Toolbox tool for CCM isochrone generation."""

    def __init__(self):
        self.label       = "4.  Show Travel Time Zones"
        self.description = (
            "Creates isochrone polygons showing how far a vehicle can travel "
            "from a start point within given time bands (e.g. 30 min, 1 hr, "
            "2 hr).  Run this after the main CCM tool."
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
                "Start Point  — enter in any coordinate format\n"
                "(MGRS, Decimal Degrees, DMS, DDM, or UTM)"
            ),
            name="start_point",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
        )

        p2b = arcpy.Parameter(
            displayName="↳ Coordinate Equivalents  (auto-computed — all formats)",
            name="start_point_display",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )

        p3 = arcpy.Parameter(
            displayName="Time Bands (minutes, semicolon-separated)",
            name="time_bands",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
        )
        p3.value = "30;60;120;240"

        p4 = arcpy.Parameter(
            displayName="Raster Cell Size (m)",
            name="cell_size_m",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input",
        )
        p4.value = 50

        p5 = arcpy.Parameter(
            displayName="Output Isochrone Feature Class",
            name="output_fc",
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Output",
        )
        # p0=speed_fc, p1=speed_field, p2=start_point, p2b=start_display,
        # p3=time_bands, p4=cell_size, p5=output_fc
        return [p0, p1, p2, p2b, p3, p4, p5]

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        # Populate coordinate display field
        if _coords_mod:
            raw = (parameters[2].valueAsText or "").strip()
            if raw:
                try:
                    lat, lon = _coords_mod.any_to_latlon(raw)
                    fmt = _coords_mod.detect_format(raw)
                    parameters[3].value = _coords_mod.format_coord_display(lat, lon, fmt)
                except Exception as e:
                    parameters[3].value = f"(Cannot convert: {e})"
            else:
                parameters[3].value = ""

    def updateMessages(self, parameters):
        # Validate coordinate input (any format)
        if _coords_mod:
            raw = (parameters[2].valueAsText or "").strip()
            if raw:
                fmt = _coords_mod.detect_format(raw)
                if fmt == "Unknown":
                    parameters[2].setErrorMessage(
                        f"Cannot recognise coordinate format: {raw!r}\n"
                        "Accepted: MGRS, DD, DMS, DDM, UTM"
                    )

        # Validate time bands (index shifted by 1 due to display field — now p4)
        tb_param = parameters[4]
        if tb_param.altered:
            raw = tb_param.valueAsText or ""
            try:
                bands = [int(x.strip()) for x in raw.split(";") if x.strip()]
                if not bands:
                    raise ValueError
            except ValueError:
                tb_param.setErrorMessage(
                    "Enter time bands as integers separated by semicolons, "
                    "e.g. 30;60;120;240"
                )

    def execute(self, parameters, messages):
        arcpy.SetLogMetadata(False)  # Prevent GDB history metadata accumulation (perf)
        # Indices: 0=speed_fc, 1=speed_field, 2=start_point, 3=start_display,
        #          4=time_bands, 5=cell_size, 6=output_fc
        fc           = parameters[0].valueAsText
        spd_field    = parameters[1].valueAsText
        start_raw    = (parameters[2].valueAsText or "").strip()
        bands_raw    = parameters[4].valueAsText
        cell_size    = float(parameters[5].value or 50)
        output_fc    = parameters[6].valueAsText

        time_bands = [int(x.strip()) for x in bands_raw.split(";") if x.strip()]
# <<< END OF FILE >>>
