# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
ccm_vehicle_compare.py
======================
CCM Tool — Phase 2, Feature 7: Vehicle Comparison (Side-by-Side)
----------------------------------------------------------------
Runs a side-by-side CCM analysis for two or more vehicles and produces
a comparison layer that classifies each terrain polygon into one of:

  BOTH_GO      — both vehicles can pass
  A_ONLY       — Vehicle A can pass; Vehicle B cannot
  B_ONLY       — Vehicle B can pass; Vehicle A cannot
  NEITHER      — neither vehicle can pass

This helps commanders instantly see which vehicle is better for a
specific terrain and where one vehicle has an advantage over the other.

Usage
-----
    from ccm_vehicle_compare import compare_vehicles

    result_fc = compare_vehicles(
        speed_surface_a = r"C:\\...\\speed_surface_LAV_moist",
        speed_surface_b = r"C:\\...\\speed_surface_TANK_moist",
        vehicle_name_a  = "LAV III",
        vehicle_name_b  = "Leopard 2 Tank",
        speed_field     = "SpeedKMH",
        go_threshold    = 5.0,        # km/h — below this is considered NO GO
        output_fc       = r"C:\\...\\CCM_Output.gdb\\vehicle_compare",
        scratch_gdb     = arcpy.env.scratchGDB,
    )

The output feature class has fields:
    VEHICLE_A     — name of vehicle A
    VEHICLE_B     — name of vehicle B
    SPEED_A       — vehicle A's speed at this polygon (km/h)
    SPEED_B       — vehicle B's speed at this polygon (km/h)
    COMPARE_RESULT— one of: BOTH_GO / A_ONLY / B_ONLY / NEITHER / DATA_GAP
    ADVANTAGE     — speed advantage of A over B (+ve = A faster, -ve = B faster)
    MOBILITY_A    — mobility label for vehicle A
    MOBILITY_B    — mobility label for vehicle B
"""

VERSION = "0.58.2"  # v0.58.2 -- bumped by bump_version.py from v0.57. Review this line's comment.
# v0.54.1 — GPL-2.0-or-later relicense + CCM Tool rebrand (see CHANGELOG_v0.54.md).
# v0.48 — Version bump for the toolbox-wide v0.48.0 release.
# v0.46 — Bug fixes:
#          1. Removed dead _spatial_join_speeds() helper that was defined but
#             never called (compare_vehicles does its own inline spatial join).
#          2. VERSION bumped to 0.46 to align with full toolbox release.

import arcpy
import os
from typing import Optional, List

try:
    import ccm_coords as _coords_mod
except Exception as _cd_e:
    _coords_mod = None
    try:
        arcpy.AddWarning(f"[Step 4] ccm_coords not loaded: {_cd_e}")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# SECTION 1 — CONSTANTS
# ---------------------------------------------------------------------------

# Speed below which a polygon is considered impassable for a vehicle
DEFAULT_GO_THRESHOLD_KMH = 5.0

# Compare result codes (also written as text)
CR_BOTH_GO   = "BOTH_GO"
CR_A_ONLY    = "A_ONLY"
CR_B_ONLY    = "B_ONLY"
CR_NEITHER   = "NEITHER"
CR_DATA_GAP  = "DATA_GAP"


# ---------------------------------------------------------------------------
# SECTION 2 — HELPER FUNCTIONS
# ---------------------------------------------------------------------------

def _load_feature_speeds(fc: str, speed_field: str) -> dict:
    """
    Load speeds from a CCM speed surface into a dict keyed by polygon shape
    token (SHAPE@WKT) for spatial joining.

    Returns dict: { shape_wkt: (speed_kmh, mobility_label) }
    """
    data = {}
    fields = ["SHAPE@WKT", speed_field]
    mob_field = None
    for f in arcpy.ListFields(fc):
        if f.name.lower() in ("mobility", "mobility_class", "speed_class"):
            mob_field = f.name
            break
    if mob_field:
        fields.append(mob_field)

    with arcpy.da.SearchCursor(fc, fields) as cur:
        for row in cur:
            wkt   = row[0]
            speed = row[1]
            mob   = row[2] if mob_field and len(row) > 2 else None
            data[wkt] = (speed, mob)
    return data


def _is_passable(speed: Optional[float], threshold: float) -> bool:
    """Return True if the speed is above the go threshold."""
    if speed is None:
        return False
    return float(speed) >= threshold


def _compare_label(
    speed_a: Optional[float],
    speed_b: Optional[float],
    threshold: float,
) -> str:
    """Return a COMPARE_RESULT string for a single polygon."""
    if speed_a is None and speed_b is None:
        return CR_DATA_GAP
    go_a = _is_passable(speed_a, threshold)
    go_b = _is_passable(speed_b, threshold)
    if go_a and go_b:
        return CR_BOTH_GO
    elif go_a:
        return CR_A_ONLY
    elif go_b:
        return CR_B_ONLY
    else:
        return CR_NEITHER


def _speed_advantage(
    speed_a: Optional[float],
    speed_b: Optional[float],
) -> Optional[float]:
    """Return speed_a - speed_b, or None if either is missing."""
    if speed_a is None or speed_b is None:
        return None
    return round(speed_a - speed_b, 2)


def _safe_name(name: str) -> str:
    """Convert a vehicle name to a safe field/FC name fragment."""
    import re
    return re.sub(r"[^A-Za-z0-9]", "_", name)[:20]


# ---------------------------------------------------------------------------
# SECTION 3 — MAIN PUBLIC FUNCTION
# ---------------------------------------------------------------------------

def compare_vehicles(
    speed_surface_a: str,
    speed_surface_b: str,
    vehicle_name_a:  str  = "Vehicle A",
    vehicle_name_b:  str  = "Vehicle B",
    speed_field:     str  = "SpeedKMH",
    go_threshold:    float = DEFAULT_GO_THRESHOLD_KMH,
    output_fc:       str   = "",
    scratch_gdb:     str   = "",
) -> str:
    """
    Compare two CCM speed surfaces and produce a combined comparison layer.

    Parameters
    ----------
    speed_surface_a, speed_surface_b : str
        Paths to the CCM output speed surface feature classes.
    vehicle_name_a, vehicle_name_b : str
        Display names for the two vehicles.
    speed_field : str
        Name of the speed field (km/h) in both speed surfaces.
    go_threshold : float
        Speed (km/h) below which a polygon is classified as NO GO.
    output_fc : str, optional
        Output feature class path.  Auto-generated if empty.
    scratch_gdb : str, optional
        Scratch workspace.  Uses arcpy.env.scratchGDB if empty.

    Returns
    -------
    str  — path to the output comparison feature class.
    """
    if not scratch_gdb:
        scratch_gdb = arcpy.env.scratchGDB
    if not output_fc:
        gdb   = os.path.dirname(speed_surface_a)
        output_fc = os.path.join(
            gdb,
            f"compare_{_safe_name(vehicle_name_a)}_vs_{_safe_name(vehicle_name_b)}"
        )

    arcpy.AddMessage(
        f"[CCM Compare] Comparing '{vehicle_name_a}' vs '{vehicle_name_b}' …"
    )

    # ── Step 1: Spatial join B's speeds onto A's geometry ─────────────────
    arcpy.SetProgressorLabel("Vehicle Compare: Joining speed surfaces …")

    speed_field_a = speed_field + "_A"
    speed_field_b = speed_field + "_B"

    # Copy A
    base_fc = os.path.join(scratch_gdb, "ccm_cmp_base")
    if arcpy.Exists(base_fc):
        arcpy.management.Delete(base_fc)
    arcpy.management.CopyFeatures(speed_surface_a, base_fc)
    arcpy.management.AlterField(base_fc, speed_field, speed_field_a, speed_field_a)

    # Spatial join B onto A
    joined = os.path.join(scratch_gdb, "ccm_cmp_joined")
    if arcpy.Exists(joined):
        arcpy.management.Delete(joined)
    arcpy.analysis.SpatialJoin(
        target_features   = base_fc,
        join_features     = speed_surface_b,
        out_feature_class = joined,
        join_operation    = "JOIN_ONE_TO_ONE",
        join_type         = "KEEP_ALL",
        match_option      = "LARGEST_OVERLAP",
        field_mapping     = None,
    )
    # Rename B's speed field
    for f in arcpy.ListFields(joined):
        if f.name == speed_field:
            arcpy.management.AlterField(joined, speed_field, speed_field_b, speed_field_b)
            break

    # ── Step 2: Add comparison fields ─────────────────────────────────────
    arcpy.SetProgressorLabel("Vehicle Compare: Adding comparison fields …")

    if arcpy.Exists(output_fc):
        arcpy.management.Delete(output_fc)
    arcpy.management.CopyFeatures(joined, output_fc)

    for fname, ftype, flength in [
        ("VEHICLE_A",      "TEXT",   80),
        ("VEHICLE_B",      "TEXT",   80),
        ("COMPARE_RESULT", "TEXT",   20),
        ("ADVANTAGE_KMH",  "DOUBLE", 0),
        ("MOBILITY_A",     "TEXT",   40),
        ("MOBILITY_B",     "TEXT",   40),
    ]:
        if ftype == "TEXT":
            arcpy.management.AddField(output_fc, fname, ftype, field_length=flength)
        else:
            arcpy.management.AddField(output_fc, fname, ftype)

    # ── Step 3: Populate comparison fields ────────────────────────────────
    arcpy.SetProgressorLabel("Vehicle Compare: Computing results …")

    # Find mobility fields (may not exist in both)
    mob_a_field = None
    mob_b_field = None
    for f in arcpy.ListFields(output_fc):
        ln = f.name.lower()
        if "mobility" in ln and "_a" in ln:
            mob_a_field = f.name
        if "mobility" in ln and "_b" in ln:
            mob_b_field = f.name
        if "mobility" in ln and not mob_a_field and not mob_b_field:
            mob_a_field = f.name   # best effort

    cursor_fields = [
        speed_field_a, speed_field_b,
        "VEHICLE_A", "VEHICLE_B",
        "COMPARE_RESULT", "ADVANTAGE_KMH",
        "MOBILITY_A", "MOBILITY_B",
    ]
    # Track exact indices for the optional mobility-label source fields so
    # the read position is correct even when only one of the two is present.
    mob_a_idx = len(cursor_fields) if mob_a_field else None
    if mob_a_field:
        cursor_fields.append(mob_a_field)
    mob_b_idx = len(cursor_fields) if mob_b_field else None
    if mob_b_field:
        cursor_fields.append(mob_b_field)

    with arcpy.da.UpdateCursor(output_fc, cursor_fields) as cur:
        for row in cur:
            spd_a   = row[0]
            spd_b   = row[1]
            row[2]  = vehicle_name_a
            row[3]  = vehicle_name_b
            row[4]  = _compare_label(spd_a, spd_b, go_threshold)
            adv     = _speed_advantage(spd_a, spd_b)
            row[5]  = adv if adv is not None else 0.0
            row[6]  = row[mob_a_idx] if mob_a_idx is not None else None
            row[7]  = row[mob_b_idx] if mob_b_idx is not None else None
            cur.updateRow(row)

    # ── Step 4: Summary statistics ────────────────────────────────────────
    arcpy.SetProgressorLabel("Vehicle Compare: Building summary …")
    counts = {CR_BOTH_GO: 0, CR_A_ONLY: 0, CR_B_ONLY: 0, CR_NEITHER: 0, CR_DATA_GAP: 0}
    with arcpy.da.SearchCursor(output_fc, ["COMPARE_RESULT"]) as cur:
        for row in cur:
            key = row[0] if row[0] in counts else CR_DATA_GAP
            counts[key] += 1

    total = sum(counts.values())
    _BAR  = 24

    def _bar(n):
        filled = round(_BAR * n / total) if total > 0 else 0
        return "#" * filled + "." * (_BAR - filled)

    sep = "=" * 62
    arcpy.AddMessage(sep)
    arcpy.AddMessage("  VEHICLE COMPARISON COMPLETE")
    arcpy.AddMessage(sep)
    arcpy.AddMessage(f"  Vehicle A : {vehicle_name_a}")
    arcpy.AddMessage(f"  Vehicle B : {vehicle_name_b}")
    arcpy.AddMessage(f"  GO threshold : {go_threshold} km/h   Total polygons: {total:,}")
    arcpy.AddMessage("  " + "─" * 58)
    _LABELS = {
        CR_BOTH_GO  : "BOTH_GO   (both pass)",
        CR_A_ONLY   : f"A_ONLY    ({vehicle_name_a} only)",
        CR_B_ONLY   : f"B_ONLY    ({vehicle_name_b} only)",
        CR_NEITHER  : "NEITHER   (neither passes)",
        CR_DATA_GAP : "DATA_GAP  (missing data)",
    }
    for key in [CR_BOTH_GO, CR_A_ONLY, CR_B_ONLY, CR_NEITHER, CR_DATA_GAP]:
        n   = counts[key]
        pct = 100.0 * n / total if total > 0 else 0
        arcpy.AddMessage(f"  [{_bar(n)}] {pct:5.1f}%  {n:>7,}  {_LABELS[key]}")
    arcpy.AddMessage("  " + "─" * 58)
    arcpy.AddMessage(f"  Output FC: {output_fc}")
    arcpy.AddMessage(sep)

    # Cleanup
    for tmp in [base_fc, joined]:
        if arcpy.Exists(tmp):
            try:
                arcpy.management.Delete(tmp)
            except Exception:
                pass

    return output_fc


# ---------------------------------------------------------------------------
# SECTION 4 — MULTI-VEHICLE COMPARISON (3+ vehicles)
# ---------------------------------------------------------------------------

def compare_multiple_vehicles(
    speed_surfaces: List[str],
    vehicle_names:  List[str],
    speed_field:    str   = "SpeedKMH",
    go_threshold:   float = DEFAULT_GO_THRESHOLD_KMH,
    output_fc:      str   = "",
    scratch_gdb:    str   = "",
) -> str:
    """
    Compare three or more vehicles in a single output layer.

    For each polygon, writes:
      - SPEED_<VehicleName> for each vehicle
      - BEST_VEHICLE — name of the fastest vehicle in this polygon
      - BEST_SPEED   — speed of the fastest vehicle
      - GO_COUNT     — number of vehicles that can pass this polygon
    """
    if len(speed_surfaces) < 2:
        raise ValueError("At least two speed surfaces required for comparison.")
    if len(speed_surfaces) != len(vehicle_names):
        raise ValueError("speed_surfaces and vehicle_names must be the same length.")

    if not scratch_gdb:
        scratch_gdb = arcpy.env.scratchGDB
    if not output_fc:
        gdb       = os.path.dirname(speed_surfaces[0])
        output_fc = os.path.join(gdb, "vehicle_comparison_multi")

    arcpy.AddMessage(
        f"[CCM Compare] Multi-vehicle comparison: {', '.join(vehicle_names)}"
    )

    # Start with a copy of the first surface
    base = os.path.join(scratch_gdb, "ccm_multi_base")
    if arcpy.Exists(base):
        arcpy.management.Delete(base)
    arcpy.management.CopyFeatures(speed_surfaces[0], base)

    safe_names  = [_safe_name(n) for n in vehicle_names]
    spd_field_0 = f"SPD_{safe_names[0]}"
    arcpy.management.AlterField(base, speed_field, spd_field_0, spd_field_0)

    # Join each additional surface
    for i in range(1, len(speed_surfaces)):
        joined = os.path.join(scratch_gdb, f"ccm_multi_j{i}")
        if arcpy.Exists(joined):
            arcpy.management.Delete(joined)
        arcpy.analysis.SpatialJoin(
            base, speed_surfaces[i], joined,
            "JOIN_ONE_TO_ONE", "KEEP_ALL", match_option="LARGEST_OVERLAP"
        )
        spd_fi = f"SPD_{safe_names[i]}"
        for f in arcpy.ListFields(joined):
            if f.name == speed_field:
                arcpy.management.AlterField(joined, speed_field, spd_fi, spd_fi)
                break
        # Replace base with joined
        if arcpy.Exists(base):
            arcpy.management.Delete(base)
        arcpy.management.CopyFeatures(joined, base)
        arcpy.management.Delete(joined)

    # Copy to output
    if arcpy.Exists(output_fc):
        arcpy.management.Delete(output_fc)
    arcpy.management.CopyFeatures(base, output_fc)
    arcpy.management.Delete(base)

    # Add summary fields
    arcpy.management.AddField(output_fc, "BEST_VEHICLE", "TEXT", field_length=80)
    arcpy.management.AddField(output_fc, "BEST_SPEED",   "DOUBLE")
    arcpy.management.AddField(output_fc, "GO_COUNT",     "SHORT")

    spd_fields = [f"SPD_{n}" for n in safe_names]
    cursor_fields = spd_fields + ["BEST_VEHICLE", "BEST_SPEED", "GO_COUNT"]

    with arcpy.da.UpdateCursor(output_fc, cursor_fields) as cur:
        n_spd = len(spd_fields)
        for row in cur:
            speeds   = [row[i] for i in range(n_spd)]
            go_count = sum(1 for s in speeds if _is_passable(s, go_threshold))
            best_idx = max(
                range(n_spd),
                key=lambda i: speeds[i] if speeds[i] is not None else -1
            )
            row[n_spd]     = vehicle_names[best_idx] if speeds[best_idx] else "NONE"
            row[n_spd + 1] = speeds[best_idx] or 0.0
            row[n_spd + 2] = go_count
            cur.updateRow(row)

    arcpy.AddMessage(f"[CCM Compare] Multi-vehicle output: {output_fc}")
    return output_fc


# ---------------------------------------------------------------------------
# SECTION 5 — ARCGIS TOOLBOX TOOL WRAPPER
# ---------------------------------------------------------------------------

class CCMVehicleCompareTool:
    """ArcGIS Python Toolbox tool for side-by-side vehicle comparison."""

    def __init__(self):
        self.label       = "Step 4.  Compare Two Vehicles"
        self.description = (
            "Overlays two CCM speed-surface layers to show where each vehicle "
            "can go, where one has an advantage, and where neither can pass. "
            "Run the main CCM tool once per vehicle before using this tool."
        )
        self.canRunInBackground = False

    def getParameterInfo(self):
        p0 = arcpy.Parameter(
            displayName="Vehicle A — Speed Surface Feature Class",
            name="fc_a",
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Input",
        )
        p1 = arcpy.Parameter(
            displayName="Vehicle A — Name",
            name="name_a",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
        )
        p2 = arcpy.Parameter(
            displayName="Vehicle B — Speed Surface Feature Class",
            name="fc_b",
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Input",
        )
        p3 = arcpy.Parameter(
            displayName="Vehicle B — Name",
            name="name_b",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
        )
        p4 = arcpy.Parameter(
            displayName="Speed Field Name (km/h)",
            name="speed_field",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
        )
        p4.value = "SpeedKMH"

        p5 = arcpy.Parameter(
            displayName="GO Threshold (km/h) — below this = NO GO",
            name="go_threshold",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input",
        )
        p5.value = DEFAULT_GO_THRESHOLD_KMH

        p6 = arcpy.Parameter(
            displayName="Output Comparison Feature Class",
            name="output_fc",
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Output",
        )
        return [p0, p1, p2, p3, p4, p5, p6]

    def isLicensed(self):
        return True

    def updateParameters(self, p):
        pass

    def updateMessages(self, p):
        # v0.54.0 — smart CRS warnings: both speed surfaces must be in a
        # Projected CRS, and ideally the SAME one, or the comparison overlay
        # will silently misalign / produce meaningless results.  See User
        # Manual Section 3.4.
        if not _coords_mod:
            return
        fc_a, fc_b = p[0], p[2]
        _sr_a = _sr_b = None  # (type, name, code) tuples
        for _p, _label in ((fc_a, "Vehicle A Speed Surface"),
                            (fc_b, "Vehicle B Speed Surface")):
            if not _p.value or _p.hasError():
                continue
            _typ, _name, _code = _coords_mod.describe_spatial_reference(
                str(_p.valueAsText))
            if _typ is None:
                continue
            if _p is fc_a:
                _sr_a = (_typ, _name, _code)
            else:
                _sr_b = (_typ, _name, _code)
            if _typ == "Geographic":
                _p.setWarningMessage(
                    _coords_mod.geographic_crs_warning(_label, _name))

        if (_sr_a and _sr_b
                and _sr_a[0] == "Projected" and _sr_b[0] == "Projected"
                and _sr_a[2] and _sr_b[2] and _sr_a[2] != _sr_b[2]):
            fc_b.setWarningMessage(
                _coords_mod.crs_mismatch_warning(
                    "Vehicle B Speed Surface", _sr_b[1],
                    "Vehicle A Speed Surface", _sr_a[1])
            )

    def execute(self, parameters, messages):
        arcpy.SetLogMetadata(False)  # Prevent GDB history metadata accumulation (perf)
        fc_a        = parameters[0].valueAsText
        name_a      = parameters[1].valueAsText
        fc_b        = parameters[2].valueAsText
        name_b      = parameters[3].valueAsText
        spd_field   = parameters[4].valueAsText
        threshold   = float(parameters[5].value or DEFAULT_GO_THRESHOLD_KMH)
        output_fc   = parameters[6].valueAsText

        compare_vehicles(
            speed_surface_a = fc_a,
            speed_surface_b = fc_b,
            vehicle_name_a  = name_a,
            vehicle_name_b  = name_b,
                 speed_field     = spd_field,
            go_threshold    = threshold,
            output_fc       = output_fc,
        )

# <<< END OF FILE >>>
