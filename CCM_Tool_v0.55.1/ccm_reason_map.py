# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
ccm_reason_map.py
=================
CCM Tool — Phase 2, Feature 5: Reason Mapping ("Why is it Red?")
-----------------------------------------------------------------
Enriches a CCM speed-surface feature class with a human-readable
NO_GO_REASON field so that when a user clicks a "red" (No-Go) polygon
they see exactly why travel is restricted.

Design
------
The CCM model computes five factors (F1–F5).  This module inspects each
factor value in the output feature class and writes a structured reason
string to a new field called ``NO_GO_REASON``.

Reason categories and their trigger conditions:
  - "Slope too steep"             F1 = 0  (slope > vehicle limit)
  - "Soil too weak (dry)"         F4 or F5 = 0, moisture = dry
  - "Soil too weak (wet)"         F4 or F5 = 0, moisture = wet/moist
  - "Water too deep"              Hydro F-factor = 0
  - "Dense vegetation"            F2 or F3 = 0
  - "Multiple restrictions"       more than one factor = 0
  - "Missing data"                NULL F-factors — input data gap

The module also produces a RESTRICT_CODE integer field for easy
symbology classification:
  0 = GO
  1 = RESTRICTED (slow but passable)
  2 = NO GO — slope
  3 = NO GO — soil
  4 = NO GO — water
  5 = NO GO — vegetation
  6 = NO GO — multiple
  9 = MISSING DATA

Usage
-----
    from ccm_reason_map import add_reason_map

    add_reason_map(
        speed_surface_fc   = r"C:\\...\\CCM_Output.gdb\\speed_surface_LAV_moist",
        mobility_field     = "Mobility",
        f1_field           = "F1_slope",
        f2_field           = "F2_vegetation",
        f3_field           = "F3_veg_spacing",
        f4_field           = "F4_soil_dry",
        f5_field           = "F5_soil_wet",
        hydro_field        = "F_hydro",       # optional
        moisture_condition = "moist",
    )

After running this, users can click any polygon in ArcGIS Pro and read
``NO_GO_REASON`` in the pop-up / Identify Results panel.
"""

VERSION = "0.55.1"  # v0.55.1 -- version bump only: added QUICK_START.html and CCM_anaconda_environment.bat (Anaconda Prompt environment setup script); no code/logic changes. See CHANGELOG_v0.55.md.

import arcpy
import os
from typing import Optional


# ---------------------------------------------------------------------------
# SECTION 1 — RESTRICT CODE CONSTANTS
# ---------------------------------------------------------------------------

RC_GO           = 0
RC_RESTRICTED   = 1
RC_NOGO_SLOPE   = 2
RC_NOGO_SOIL    = 3
RC_NOGO_WATER   = 4
RC_NOGO_VEG     = 5
RC_NOGO_MULTI   = 6
RC_MISSING      = 9

# Human-readable reason strings
REASONS = {
    RC_GO:           "GO — passable",
    RC_RESTRICTED:   "RESTRICTED — reduced speed",
    RC_NOGO_SLOPE:   "NO GO — Slope too steep for this vehicle",
    RC_NOGO_SOIL:    "NO GO — Soil too weak / insufficient bearing capacity",
    RC_NOGO_WATER:   "NO GO — Water crossing depth exceeds vehicle fording limit",
    RC_NOGO_VEG:     "NO GO — Vegetation too dense or trees too large",
    RC_NOGO_MULTI:   "NO GO — Multiple restrictions (see individual F-factors)",
    RC_MISSING:      "INCOMPLETE — Missing input data; could not classify",
}


# ---------------------------------------------------------------------------
# SECTION 2 — FIELD MANAGEMENT HELPERS
# ---------------------------------------------------------------------------

def _add_field_if_missing(fc: str, field_name: str, field_type: str, length: int = 200):
    """Add a field to fc only if it does not already exist."""
    existing = {f.name.lower() for f in arcpy.ListFields(fc)}
    if field_name.lower() not in existing:
        if field_type == "TEXT":
            arcpy.management.AddField(fc, field_name, field_type, field_length=length)
        else:
            arcpy.management.AddField(fc, field_name, field_type)
        arcpy.AddMessage(f"[CCM ReasonMap] Added field '{field_name}' to '{fc}'.")


def _get_field(fc: str, name: str) -> Optional[str]:
    """Return the field name (original case) if it exists, else None."""
    for f in arcpy.ListFields(fc):
        if f.name.lower() == name.lower():
            return f.name
    return None


# ---------------------------------------------------------------------------
# SECTION 3 — REASON CLASSIFICATION LOGIC
# ---------------------------------------------------------------------------

def _classify(
    mobility_val: Optional[str],
    f1: Optional[float],
    f2: Optional[float],
    f3: Optional[float],
    f4: Optional[float],
    f5: Optional[float],
    hydro: Optional[float],
    moisture: str,
) -> tuple:
    """
    Classify a single feature and return (restrict_code, reason_string).

    Parameters
    ----------
    mobility_val : str or None
        The existing Mobility label from the speed surface (e.g. "GO",
        "RESTRICTED", "NO GO - Slope").
    f1..f5, hydro : float or None
        Individual factor values.  0 = blocking; None = missing data.
    moisture : str
        "dry", "moist", or "wet".

    Returns
    -------
    (int, str)  — restrict_code, human-readable reason
    """
    # ── Missing data ─────────────────────────────────────────────────────
    # Include hydro in the "all-missing" check — a hydro factor alone (e.g.
    # hydro=0 with no other F-factors present) is still sufficient to classify
    # a water-depth obstacle.  Only return MISSING when every factor is None.
    f_vals = [f1, f2, f3, f4, f5, hydro]
    if all(v is None for v in f_vals):
        return RC_MISSING, REASONS[RC_MISSING]

    # ── GO or RESTRICTED: positive F-factors, mobility label says passable
    if mobility_val and mobility_val.upper().startswith("GO"):
        return RC_GO, REASONS[RC_GO]
    if mobility_val and mobility_val.upper().startswith("RESTRICTED"):
        # Gather which factors are reduced (> 0 but < 1)
        reduced = []
        if f1 is not None and 0 < f1 < 1:
            reduced.append(f"Slope ({f1:.2f})")
        if f2 is not None and 0 < f2 < 1:
            reduced.append(f"Vegetation ({f2:.2f})")
        if f4 is not None and 0 < f4 < 1:
            reduced.append(f"Soil strength ({f4:.2f})")
        if hydro is not None and 0 < hydro < 1:
            reduced.append(f"Shallow water ({hydro:.2f})")
        detail = "; ".join(reduced) if reduced else "see F-factors"
        return RC_RESTRICTED, f"RESTRICTED — reduced speed ({detail})"

    # ── No-Go: identify blocking factor(s) ───────────────────────────────
    blocking = []

    # Slope
    if f1 is not None and f1 == 0:
        blocking.append("slope")

    # Soil bearing capacity
    soil_block = False
    if f4 is not None and f4 == 0:
        soil_block = True
    if f5 is not None and f5 == 0:
        soil_block = True
    if soil_block:
        blocking.append("soil")

    # Water depth
    if hydro is not None and hydro == 0:
        blocking.append("water")

    # Vegetation / tree spacing
    veg_block = False
    if f2 is not None and f2 == 0:
        veg_block = True
    if f3 is not None and f3 == 0:
        veg_block = True
    if veg_block:
        blocking.append("vegetation")

    # ── Compose reason ───────────────────────────────────────────────────
    if len(blocking) == 0:
        # Mobility label says No-Go but we couldn't find the reason
        return RC_MISSING, "NO GO — Reason undetermined (check F-factors manually)"

    if len(blocking) > 1:
        detail_parts = []
        if "slope"      in blocking: detail_parts.append("Slope (F1=0)")
        if "soil"       in blocking:
            mc = moisture.capitalize()
            detail_parts.append(f"Soil too weak for {mc} conditions")
        if "water"      in blocking: detail_parts.append("Water crossing depth exceeded")
        if "vegetation" in blocking: detail_parts.append("Dense vegetation / large trees")
        detail = "; ".join(detail_parts)
        return RC_NOGO_MULTI, f"NO GO — Multiple restrictions: {detail}"

    reason_key = blocking[0]
    if reason_key == "slope":
        return RC_NOGO_SLOPE, REASONS[RC_NOGO_SLOPE]
    if reason_key == "soil":
        cond = "wet/moist" if moisture in ("wet", "moist") else "dry"
        return RC_NOGO_SOIL, f"NO GO — Soil too weak under {cond} conditions (RCI below vehicle threshold)"
    if reason_key == "water":
        return RC_NOGO_WATER, REASONS[RC_NOGO_WATER]
    if reason_key == "vegetation":
        if f2 == 0 and f3 is not None and f3 > 0:
            return RC_NOGO_VEG, "NO GO — Vegetation density too high (F2=0)"
        if f3 == 0:
            return RC_NOGO_VEG, "NO GO — Tree spacing too narrow for vehicle width (F3=0)"
        return RC_NOGO_VEG, REASONS[RC_NOGO_VEG]

    return RC_MISSING, REASONS[RC_MISSING]


# ---------------------------------------------------------------------------
# SECTION 4 — MAIN PUBLIC FUNCTION
# ---------------------------------------------------------------------------

def add_reason_map(
    speed_surface_fc: str,
    mobility_field:   str  = "Mobility",
    f1_field:         Optional[str] = None,
    f2_field:         Optional[str] = None,
    f3_field:         Optional[str] = None,
    f4_field:         Optional[str] = None,
    f5_field:         Optional[str] = None,
    hydro_field:      Optional[str] = None,
    moisture_condition: str = "moist",
    moisture_scenario:  Optional[str] = None,
) -> None:
    """
    Enrich a CCM speed-surface feature class with NO_GO_REASON and
    RESTRICT_CODE fields.

    Parameters
    ----------
    speed_surface_fc : str
        Path to the output feature class from the CCM main tool.
    mobility_field : str
        Name of the existing Mobility classification field.
    f1_field .. hydro_field : str, optional
        Names of individual F-factor fields.  Pass None if not present.
    moisture_condition : str
        "dry", "moist", or "wet" — used to tailor soil reason messages.
    moisture_scenario : str, optional
        Antecedent moisture scenario from Step 2.  When set to a strategic
        preset (anything other than None / "" / "Live Weather"), a MOIST_SCEN
        text field is added and stamped on every feature.

    Side Effects
    ------------
    Adds / updates fields NO_GO_REASON (TEXT, 400) and RESTRICT_CODE (SHORT)
    in-place on speed_surface_fc.
    """
    arcpy.AddMessage("[CCM ReasonMap] Starting reason mapping …")

    # Annotate the antecedent scenario only when a strategic preset was used.
    write_scen = bool(moisture_scenario
                      and str(moisture_scenario).strip()
                      and str(moisture_scenario).strip() != "Live Weather")

    # ── Add output fields ─────────────────────────────────────────────────
    _add_field_if_missing(speed_surface_fc, "NO_GO_REASON",  "TEXT",  400)
    _add_field_if_missing(speed_surface_fc, "RESTRICT_CODE", "SHORT")
    if write_scen:
        _add_field_if_missing(speed_surface_fc, "MOIST_SCEN", "TEXT", 60)

    # ── Build cursor field list ───────────────────────────────────────────
    cursor_fields = ["NO_GO_REASON", "RESTRICT_CODE"]

    mob_f  = _get_field(speed_surface_fc, mobility_field) or mobility_field
    cursor_fields.append(mob_f)

    factor_fields = {
        "f1": f1_field, "f2": f2_field, "f3": f3_field,
        "f4": f4_field, "f5": f5_field, "hydro": hydro_field,
    }
    present_factors = {}
    for key, fname in factor_fields.items():
        if fname:
            actual = _get_field(speed_surface_fc, fname)
            if actual:
                present_factors[key] = actual
                cursor_fields.append(actual)

    # MOIST_SCEN goes last so the idx=2 mobility/factor bookkeeping is untouched.
    scen_idx = None
    if write_scen:
        scen_idx = len(cursor_fields)
        cursor_fields.append("MOIST_SCEN")

    # ── Update cursor ─────────────────────────────────────────────────────
    updated = 0
    with arcpy.da.UpdateCursor(speed_surface_fc, cursor_fields) as cursor:
        for row in cursor:
            idx = 2  # index into row after the two output fields
            mob_val = row[idx];  idx += 1

            f_vals = {"f1": None, "f2": None, "f3": None,
                      "f4": None, "f5": None, "hydro": None}
            for key in present_factors:
                f_vals[key] = row[idx]
                idx += 1

            code, reason = _classify(
                mobility_val = mob_val,
                f1    = f_vals["f1"],
                f2    = f_vals["f2"],
                f3    = f_vals["f3"],
                f4    = f_vals["f4"],
                f5    = f_vals["f5"],
                hydro = f_vals["hydro"],
                moisture = moisture_condition,
            )
            row[0] = reason
            row[1] = code
            if scen_idx is not None:
                row[scen_idx] = str(moisture_scenario).strip()
            cursor.updateRow(row)
            updated += 1

    arcpy.AddMessage(
        f"[CCM ReasonMap] Reason mapping complete. "
        f"{updated} features updated with NO_GO_REASON and RESTRICT_CODE."
    )
    if write_scen:
        arcpy.AddMessage(
            f"[CCM ReasonMap] Antecedent scenario '{str(moisture_scenario).strip()}' "
            f"stamped on the MOIST_SCEN field."
        )


# ---------------------------------------------------------------------------
# SECTION 5 — ARCGIS TOOLBOX TOOL WRAPPER
# ---------------------------------------------------------------------------

class CCMReasonMapTool:
    """
    ArcGIS Python Toolbox tool that adds reason mapping to an existing
    CCM speed-surface feature class.

    This is a POST-PROCESSING tool — run it after the main CCM tool.
    """

    def __init__(self):
        self.label       = "3.  Explain Why Areas Are Blocked"
        self.description = (
            "Enriches a CCM speed-surface feature class with a NO_GO_REASON "
            "field so users can click any polygon and see exactly why it is "
            "impassable (slope too steep, soil too weak, water too deep, etc.)."
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
            displayName="Mobility Field Name",
            name="mobility_field",
            datatype="Field",
            parameterType="Required",
            direction="Input",
        )
        p1.parameterDependencies = [p0.name]
        p1.value = "Mobility"

        p2 = arcpy.Parameter(
            displayName="Soil Moisture Condition",
            name="moisture",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
        )
        p2.filter.type = "ValueList"
        p2.filter.list = ["dry", "moist", "wet"]
        p2.value = "moist"

        # Optional F-factor field parameters
        def _fp(label, name):
            p = arcpy.Parameter(
                displayName=label,
                name=name,
                datatype="Field",
                parameterType="Optional",
                direction="Input",
            )
            p.parameterDependencies = [p0.name]
            return p

        p3  = _fp("F1 Slope Field",          "f1_field")
        p4  = _fp("F2 Vegetation Field",      "f2_field")
        p5  = _fp("F3 Tree Spacing Field",    "f3_field")
        p6  = _fp("F4 Soil Dry Field",        "f4_field")
        p7  = _fp("F5 Soil Wet Field",        "f5_field")
        p8  = _fp("Hydro F-factor Field",     "hydro_field")

        return [p0, p1, p2, p3, p4, p5, p6, p7, p8]

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        pass

    def updateMessages(self, parameters):
        fc_param = parameters[0]
        if fc_param.value and not arcpy.Exists(str(fc_param.value)):
            fc_param.setErrorMessage("Feature class not found.")

    def execute(self, parameters, messages):
        arcpy.SetLogMetadata(False)  # Prevent GDB history metadata accumulation (perf)
        fc        = parameters[0].valueAsText
        mob_field = parameters[1].valueAsText
        moisture  = parameters[2].valueAsText
        f1        = parameters[3].valueAsText or None
        f2        = parameters[4].valueAsText or None
        f3        = parameters[5].valueAsText or None
        f4        = parameters[6].valueAsText or None
        f5        = parameters[7].valueAsText or None
        hydro     = parameters[8].valueAsText or None

        # Pull the antecedent moisture scenario recorded by Step 2 from the
        # project config (walks up from the speed-surface GDB).  Harmless if it
        # can't be located — the annotation is simply skipped.
        scenario = None
        try:
            import ccm_project_config as _cfg_mod
            cfg = _cfg_mod.find_config(os.path.dirname(str(fc)))
            scenario = cfg.get("moisture_scenario")
        except Exception:
            scenario = None

        add_reason_map(
            speed_surface_fc   = fc,
            mobility_field     = mob_field,
            f1_field           = f1,
            f2_field           = f2,
            f3_field           = f3,
            f4_field           = f4,
            f5_field           = f5,
            hydro_field        = hydro,
            moisture_condition = moisture,
            moisture_scenario  = scenario,
        )

# <<< END OF FILE >>>
