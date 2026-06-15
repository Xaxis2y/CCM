"""
ccm_soil_validator.py
=====================
Automated soil feature class validator for the CCM Tool.

Detection runs in 4 levels — from fastest/most precise to slowest/most flexible:

  Level 1 — Exact or known-alias field name match
             Checks 40+ known field names from Canadian (DSS, SLC, CanSIS),
             US (SSURGO), global (SoilGrids, HWSD, FAO), and military (FACC)
             datasets.

  Level 2 — Fuzzy string similarity match
             Uses difflib to find the closest field name even if it is
             slightly misspelled or abbreviated (e.g. "SoilTyp" → "soilType").

  Level 3 — Value scan (content-based detection)
             Samples up to 200 rows of every text/string field and checks
             whether the values look like USCS codes ("CL", "GW", "ML" …)
             or texture descriptions ("lean clay", "fine sandy loam" …).

  Level 4 — Texture percentage detection
             Looks for Sand %, Silt %, Clay % fields separately.
             If all three are present, USCS can be derived mathematically
             using the USDA texture triangle.

Public API
----------
    result = validate_soil_fc(fc_path, sample_rows=200)
    result.level          # int  1-4 = found something, 0 = nothing found
    result.uscs_field     # str | None  — field to use for USCS codes
    result.texture_fields # dict | None — {"sand":..., "silt":..., "clay":...}
    result.confidence     # "high" | "medium" | "low"
    result.warning        # str  — human-readable message for the tool UI
    result.can_proceed    # bool — True if execute() can continue safely
    result.action         # str  — what the tool will do ("use field X", "derive", …)
"""

VERSION = "0.46"  # v0.46 — Version bump aligned with toolbox-wide v0.46 release.

import arcpy
import difflib
import re
from dataclasses import dataclass, field
from typing import Optional, Dict, List


# ─────────────────────────────────────────────────────────────────────────────
# 1. CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

# Valid USCS codes recognised by the CCM RCI lookup table
USCS_CODES: set = {
    "gw", "gp", "gm", "gc",          # Gravel
    "sw", "sp", "sm", "sc",          # Sand
    "ml", "cl", "ol",                 # Low-plasticity fine-grained
    "ch", "mh", "oh",                 # High-plasticity fine-grained
    "pt",                             # Peat / highly organic
    "ml-cl",                          # Borderline
    "ev", "evaporite",                # Evaporite / salt flat
    "rk", "rock",                     # Rock
    "ne", "notevaluated",             # Not evaluated
}

# Text descriptions that map directly to USCS codes
# Keys are lowercased, stripped of spaces
TEXTURE_DESC_TO_USCS: Dict[str, str] = {
    # Gravel family
    "wellgradedgravel": "GW", "wellgradedgravelwithsand": "GW",
    "poorlygradedgravel": "GP", "poorlygradedgravelwithsand": "GP",
    "siltygravel": "GM", "siltygravelsand": "GM",
    "clayeygravel": "GC", "clayeygravelsand": "GC",
    "gravel": "GW",
    # Sand family
    "wellgradedsand": "SW", "wellgradedsandwithgravel": "SW",
    "poorlygradedsand": "SP", "poorlygradedsandwithgravel": "SP",
    "siltysand": "SM", "siltysandwithgravel": "SM",
    "clayeysand": "SC",
    "sand": "SP", "gravellysand": "SW",
    # Fine-grained low plasticity
    "siltandfinessand": "ML", "siltandfinessandwithgravel": "ML",
    "silt": "ML", "finessand": "ML", "siltyfinessand": "ML",
    "leanclay": "CL", "leanclayandgravel": "CL", "sandyleanclay": "CL",
    "siltyleanclay": "CL",
    "organicsiltandclay": "OL", "organicsilt": "OL",
    # Fine-grained high plasticity
    "fatclay": "CH", "fattyclay": "CH", "heavyclay": "CH",
    "elasticsilt": "MH", "micaceous": "MH",
    "organicclay": "OH", "organicsiltandfatclay": "OH",
    # Special
    "peat": "PT", "muck": "PT", "organicsoil": "PT",
    "rock": "RK", "bedrock": "RK", "hardrock": "RK",
    "evaporite": "EV", "salt": "EV",
    "notevaluated": "NE", "notassessed": "NE", "unknown": "NE",
    # USDA texture classes → closest USCS
    "clay": "CH", "siltyclay": "CH",
    "sandyclay": "SC",
    "clayloam": "CL", "siltyclayloam": "CL",
    "sandyclayloam": "SC",
    "loam": "CL", "siltloam": "ML", "siltloamwithgravel": "ML",
    "sandyloam": "SM", "loamysand": "SP",
    "loamyfinesand": "SM",
    # Canadian / French terminology
    "argileux": "CH", "limoneux": "ML", "sableux": "SP",
    "argilesableux": "SC", "limoneuxsableux": "SM",
}

# ── Field name aliases: Level 1 exact/known match ────────────────────────────

# USCS / soil classification field aliases
SOIL_TYPE_FIELD_ALIASES: List[str] = [
    # CCM standard
    "soiltype", "soil_type", "soil_class", "soilclass",
    # USCS explicit
    "uscs", "uscs_class", "uscs_code", "uscs_group", "uscs_symbol",
    "unifiedsoilclassification", "soil_uscs",
    # Military / FACC / VMAP
    "f_code", "fcode", "facc", "facc_code",
    # Canadian DSS / SLC / CanSIS
    "soil_type_id", "soiltypeid", "soil_map_sym", "soilmapsym",
    "soil_sym", "soil_symbol", "soilsym", "slc_code",
    "soil_code", "soilcode", "soil_name", "soilname",
    "texture_class", "texclass", "tex_class",
    "soilkind", "soil_kind", "kind",
    # SSURGO (US)
    "texcl", "texture", "soil_texture",
    "muname", "compname", "taxclname",
    # SoilGrids / FAO / HWSD
    "wrb_class", "wrb_code", "fao_class", "hwsd_class",
    "soil_classification", "classification",
    # Generic fallbacks
    "type", "code", "class", "category",
    "soil", "surfacetype", "surface_type",
]

# ── Sand / Silt / Clay field aliases: Level 4 texture detection ───────────────

SAND_FIELD_ALIASES: List[str] = [
    "sand", "sand_pct", "sand_percent", "pct_sand",
    "sandtotal", "sandtotal_r", "sand_content",
    "sand_0_5cm", "sand_0_5cm_mean", "sand_5_15cm_mean",
    "pct_sa", "sa", "sand_fraction",
]
SILT_FIELD_ALIASES: List[str] = [
    "silt", "silt_pct", "silt_percent", "pct_silt",
    "silttotal", "silttotal_r", "silt_content",
    "silt_0_5cm", "silt_0_5cm_mean", "silt_5_15cm_mean",
    "pct_si", "si", "silt_fraction",
]
CLAY_FIELD_ALIASES: List[str] = [
    "clay", "clay_pct", "clay_percent", "pct_clay",
    "claytotal", "claytotal_r", "clay_content",
    "clay_0_5cm", "clay_0_5cm_mean", "clay_5_15cm_mean",
    "pct_cl", "cl_pct", "clay_fraction",
]


# ─────────────────────────────────────────────────────────────────────────────
# 2. RESULT DATACLASS
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SoilValidationResult:
    level:          int             = 0       # 0=nothing, 1–4 = detection level
    uscs_field:     Optional[str]   = None    # field to read USCS codes from
    mapped_from:    Optional[str]   = None    # original field name (if renamed)
    texture_fields: Optional[Dict]  = None    # {"sand":f, "silt":f, "clay":f}
    confidence:     str             = "none"  # "high" | "medium" | "low" | "none"
    can_proceed:    bool            = False   # safe to call execute()?
    warning:        str             = ""      # message shown in tool UI
    action:         str             = ""      # what the tool will do
    sample_values:  List[str]       = field(default_factory=list)
    unknown_values: List[str]       = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# 3. INTERNAL HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _field_map(fc: str) -> Dict[str, str]:
    """Return {lowercase_name: actual_name} for all fields in fc."""
    return {f.name.lower(): f.name
            for f in arcpy.ListFields(fc)
            if f.type not in ("OID", "Geometry", "Blob", "Raster")}


def _text_fields(fc: str) -> Dict[str, str]:
    """Return {lowercase_name: actual_name} for String/Text fields only."""
    return {f.name.lower(): f.name
            for f in arcpy.ListFields(fc)
            if f.type in ("String", "Integer", "SmallInteger")}


def _sample_values(fc: str, field_name: str, n: int = 200) -> List[str]:
    """Return up to n non-null unique values from field_name as strings."""
    seen = set()
    vals = []
    try:
        with arcpy.da.SearchCursor(fc, [field_name]) as cur:
            for i, row in enumerate(cur):
                if i >= n * 3:          # scan up to 3× to find n unique
                    break
                v = row[0]
                if v is None:
                    continue
                s = str(v).strip()
                if s and s not in seen:
                    seen.add(s)
                    vals.append(s)
                    if len(vals) >= n:
                        break
    except Exception:
        pass
    return vals


def _looks_like_uscs(value: str) -> bool:
    """Return True if value looks like a USCS code."""
    return value.strip().lower().replace("-", "").replace(" ", "") in {
        c.replace("-", "") for c in USCS_CODES
    }


def _looks_like_texture_desc(value: str) -> bool:
    """Return True if value looks like a soil texture description."""
    key = re.sub(r"[^a-z]", "", value.lower())
    return key in TEXTURE_DESC_TO_USCS


def _fuzzy_best_match(candidate: str, aliases: List[str],
                      cutoff: float = 0.72) -> Optional[str]:
    """Return the best fuzzy match from aliases for candidate, or None."""
    matches = difflib.get_close_matches(
        candidate.lower(), aliases, n=1, cutoff=cutoff
    )
    return matches[0] if matches else None


def _derive_uscs_from_texture(sand: float, silt: float, clay: float) -> str:
    """
    Approximate USCS code from USDA texture triangle percentages.
    Returns canonical USCS code string.
    """
    if clay >= 50:
        return "CH"
    if clay >= 35:
        return "CL" if silt < 40 else "CL"
    if clay >= 25:
        return "SC" if sand >= 45 else "CL"
    if clay >= 18:
        if sand >= 45:
            return "SC"
        return "CL" if silt < 56 else "ML"
    if clay >= 12:
        if silt >= 50:
            return "ML"
        if sand >= 52:
            return "SM"
        return "ML"
    if silt >= 80:
        return "ML"
    if sand >= 70:
        return "SP" if clay < 5 else "SM"
    if sand >= 52:
        return "SM"
    return "ML"


# ─────────────────────────────────────────────────────────────────────────────
# 4. MAIN DETECTION LOGIC
# ─────────────────────────────────────────────────────────────────────────────

def validate_soil_fc(fc_path: str, sample_rows: int = 200) -> SoilValidationResult:
    """
    Run 4-level soil field detection on fc_path.
    Returns a SoilValidationResult with all findings and a ready-to-display
    warning string for use in updateMessages().
    """
    result = SoilValidationResult()

    try:
        all_fields  = _field_map(fc_path)
        text_fields = _text_fields(fc_path)
        avail_names = sorted(all_fields.values())
        avail_str   = ", ".join(avail_names) or "(none)"
    except Exception as exc:
        result.warning = f"Cannot read fields from soil FC: {exc}"
        return result

    # ── LEVEL 1: Exact / known-alias field name match ─────────────────────────
    for alias in SOIL_TYPE_FIELD_ALIASES:
        if alias in all_fields:
            actual = all_fields[alias]
            # Quick value check to confirm field has USCS-like content
            vals  = _sample_values(fc_path, actual, sample_rows)
            uscs  = [v for v in vals if _looks_like_uscs(v)]
            tdesc = [v for v in vals if _looks_like_texture_desc(v)]
            unknown = [v for v in vals if not _looks_like_uscs(v)
                       and not _looks_like_texture_desc(v)]

            result.level        = 1
            result.uscs_field   = actual
            result.mapped_from  = alias
            result.confidence   = "high"
            result.can_proceed  = True
            result.sample_values = vals[:10]
            result.unknown_values = unknown[:10]

            if uscs:
                result.action  = f"Using field '{actual}' — {len(uscs)} of {len(vals)} sampled values are valid USCS codes."
                result.warning = ""   # no warning needed
            elif tdesc:
                result.action  = (
                    f"Field '{actual}' contains texture descriptions (e.g. '{tdesc[0]}').  "
                    "The tool will normalise these to USCS codes automatically."
                )
                result.warning = (
                    f"⚠  Soil field '{actual}' uses texture descriptions, not USCS codes.  "
                    "The tool will attempt automatic conversion — verify the output F4/F5 values."
                )
            else:
                result.action  = f"Field '{actual}' found but values could not be confirmed as USCS or texture codes."
                result.warning = (
                    f"⚠  Field '{actual}' was found but its values do not match known USCS codes "
                    f"or texture descriptions.  Sample values: {', '.join(vals[:5]) or '(empty)'}.  "
                    "F4 / F5 may be NULL for some features."
                )
            if unknown:
                result.warning += (
                    f"\n  Unrecognised values in sample ({len(unknown)} found): "
                    + ", ".join(f"'{v}'" for v in unknown[:8])
                    + ".  These will be treated as 'Not Evaluated' (NE)."
                )
            return result

    # ── LEVEL 2: Fuzzy string similarity match ────────────────────────────────
    best_match_field = None
    best_score       = 0.0
    best_alias_hit   = None

    for field_lower, field_actual in all_fields.items():
        match = _fuzzy_best_match(field_lower, SOIL_TYPE_FIELD_ALIASES, cutoff=0.72)
        if match:
            score = difflib.SequenceMatcher(None, field_lower, match).ratio()
            if score > best_score:
                best_score       = score
                best_match_field = field_actual
                best_alias_hit   = match

    if best_match_field:
        vals    = _sample_values(fc_path, best_match_field, sample_rows)
        uscs    = [v for v in vals if _looks_like_uscs(v)]
        tdesc   = [v for v in vals if _looks_like_texture_desc(v)]
        unknown = [v for v in vals if not _looks_like_uscs(v)
                   and not _looks_like_texture_desc(v)]

        result.level        = 2
        result.uscs_field   = best_match_field
        result.mapped_from  = best_alias_hit
        result.confidence   = "medium"
        result.can_proceed  = bool(uscs or tdesc)
        result.sample_values = vals[:10]
        result.unknown_values = unknown[:10]

        if uscs or tdesc:
            result.action  = (
                f"Fuzzy match: using field '{best_match_field}' "
                f"(similarity {best_score:.0%} to expected name '{best_alias_hit}').  "
                f"{len(uscs or tdesc)} of {len(vals)} sampled values are usable."
            )
            result.warning = (
                f"⚠  No standard soil field found — closest match is '{best_match_field}' "
                f"({best_score:.0%} similar to '{best_alias_hit}').  "
                "The tool will use this field.  "
                f"Rename it to 'soilType' to suppress this warning."
            )
        else:
            result.action  = f"Fuzzy match found '{best_match_field}' but values are unrecognisable."
            result.warning = (
                f"⚠  Possible soil field '{best_match_field}' found by fuzzy match, "
                "but its values do not match USCS codes or known texture descriptions.  "
                f"Sample values: {', '.join(vals[:5]) or '(empty)'}.  "
                "F4 / F5 soil factors will be NULL."
            )
        return result

    # ── LEVEL 3: Value scan — look inside every string field for USCS content ─
    best_field_by_content = None
    best_uscs_count       = 0
    best_tdesc_count      = 0

    for field_lower, field_actual in text_fields.items():
        vals  = _sample_values(fc_path, field_actual, sample_rows)
        uscs  = sum(1 for v in vals if _looks_like_uscs(v))
        tdesc = sum(1 for v in vals if _looks_like_texture_desc(v))
        score = uscs * 2 + tdesc          # weight USCS hits more
        if score > (best_uscs_count * 2 + best_tdesc_count):
            best_field_by_content = field_actual
            best_uscs_count       = uscs
            best_tdesc_count      = tdesc
            _vals_snapshot        = vals

    if best_field_by_content and (best_uscs_count + best_tdesc_count) > 0:
        pct = (best_uscs_count + best_tdesc_count) / max(len(_vals_snapshot), 1)
        result.level        = 3
        result.uscs_field   = best_field_by_content
        result.confidence   = "medium" if pct > 0.6 else "low"
        result.can_proceed  = pct > 0.4
        result.sample_values = _vals_snapshot[:10]

        result.action  = (
            f"Value scan: field '{best_field_by_content}' has "
            f"{best_uscs_count} USCS codes + {best_tdesc_count} texture descriptions "
            f"in {len(_vals_snapshot)} sampled rows ({pct:.0%} hit rate)."
        )
        result.warning = (
            f"⚠  No recognised soil field name found.  "
            f"Value scan identified '{best_field_by_content}' as the most likely soil "
            f"classification field ({pct:.0%} of sampled values match USCS/texture patterns).  "
            "Please confirm this is the correct field and rename it to 'soilType' "
            "for full compatibility."
        )
        if not result.can_proceed:
            result.warning += (
                "\n  Hit rate is below 40% — F4/F5 may be NULL for many features."
            )
        return result

    # ── LEVEL 4: Texture percentage fields (Sand / Silt / Clay %) ────────────
    found_sand = next((all_fields[a] for a in SAND_FIELD_ALIASES if a in all_fields), None)
    found_silt = next((all_fields[a] for a in SILT_FIELD_ALIASES if a in all_fields), None)
    found_clay = next((all_fields[a] for a in CLAY_FIELD_ALIASES if a in all_fields), None)

    # Also try fuzzy on texture field names
    if not found_sand:
        for fl, fa in all_fields.items():
            if _fuzzy_best_match(fl, SAND_FIELD_ALIASES, 0.78):
                found_sand = fa; break
    if not found_silt:
        for fl, fa in all_fields.items():
            if _fuzzy_best_match(fl, SILT_FIELD_ALIASES, 0.78):
                found_silt = fa; break
    if not found_clay:
        for fl, fa in all_fields.items():
            if _fuzzy_best_match(fl, CLAY_FIELD_ALIASES, 0.78):
                found_clay = fa; break

    if found_sand and found_silt and found_clay:
        result.level           = 4
        result.texture_fields  = {"sand": found_sand, "silt": found_silt,
                                   "clay": found_clay}
        result.confidence      = "medium"
        result.can_proceed     = True
        result.action          = (
            f"Texture fields detected: Sand='{found_sand}', Silt='{found_silt}', "
            f"Clay='{found_clay}'.  USCS will be derived using the USDA texture triangle."
        )
        result.warning = (
            f"⚠  No USCS field found.  However, Sand/Silt/Clay percentage fields were "
            f"detected ({found_sand}, {found_silt}, {found_clay}).  "
            "The tool will derive USCS codes automatically using the USDA texture triangle.  "
            "Derived codes are approximate — use a proper USCS classification for critical analysis."
        )
        return result

    elif found_clay:    # at least Clay gives partial info
        result.level          = 4
        result.texture_fields = {"clay": found_clay}
        result.confidence     = "low"
        result.can_proceed    = False
        result.warning = (
            f"⚠  Only Clay % field found ('{found_clay}').  "
            "Sand and Silt fields are also needed to derive USCS codes.  "
            "F4/F5 soil factors cannot be computed.  "
            "Provide a layer with USCS codes or add Sand % and Silt % fields."
        )
        return result

    # ── LEVEL 0: Nothing found ────────────────────────────────────────────────
    result.level       = 0
    result.confidence  = "none"
    result.can_proceed = False
    result.warning = (
        "❌  No usable soil classification field found in this feature class.\n\n"
        "The CCM tool needs ONE of the following to compute F4 (dry RCI) and F5 (wet RCI):\n"
        "  Option A — A field with USCS codes  (GW, CL, ML, CH, SP …)\n"
        "             Rename your field to 'soilType' and populate with USCS codes.\n"
        "  Option B — A field with texture descriptions\n"
        "             (e.g. 'Lean Clay', 'Silty Sand', 'Well Graded Gravel')\n"
        "             Rename the field to 'soilType'.\n"
        "  Option C — Three separate fields for Sand %, Silt %, Clay %\n"
        "             The tool will derive USCS automatically.\n\n"
        f"Fields currently in this FC: {avail_str}\n\n"
        "Where to get Canadian soil data:\n"
        "  • Soil Landscapes of Canada (SLC v3.2) — open.canada.ca\n"
        "  • National Soil DataBase (NSDB) — sis.agr.gc.ca\n"
        "  • CanSIS Provincial Soil Survey data — sis.agr.gc.ca/cansis"
    )
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 5. TEXTURE DERIVATION (used by execute() when Level 4 is detected)
# ─────────────────────────────────────────────────────────────────────────────

def derive_uscs_field_from_texture(fc_path: str, sand_field: str,
                                   silt_field: str, clay_field: str,
                                   output_field: str = "soilType_derived") -> str:
    """
    Adds a new text field to fc_path populated with derived USCS codes
    from Sand/Silt/Clay percentage fields.

    Returns the name of the new field.
    """
    arcpy.AddMessage(
        f"[SoilValidator] Deriving USCS codes from texture fields "
        f"({sand_field}, {silt_field}, {clay_field}) → '{output_field}' …"
    )

    # Add field if not present
    existing = {f.name.lower() for f in arcpy.ListFields(fc_path)}
    if output_field.lower() not in existing:
        arcpy.management.AddField(fc_path, output_field, "TEXT", field_length=10)

    null_count    = 0
    derived_count = 0

    with arcpy.da.UpdateCursor(
            fc_path,
            [sand_field, silt_field, clay_field, output_field]) as cur:
        for row in cur:
            sand_v, silt_v, clay_v = row[0], row[1], row[2]
            if None in (sand_v, silt_v, clay_v):
                row[3] = "NE"
                null_count += 1
            else:
                try:
                    uscs = _derive_uscs_from_texture(
                        float(sand_v), float(silt_v), float(clay_v)
                    )
                    row[3] = uscs
                    derived_count += 1
                except (ValueError, TypeError):
                    row[3] = "NE"
                    null_count += 1
            cur.updateRow(row)

    arcpy.AddMessage(
        f"[SoilValidator] Done — {derived_count} USCS codes derived, "
        f"{null_count} set to NE (missing texture data)."
    )
    return output_field


# ─────────────────────────────────────────────────────────────────────────────
# 6. CONVENIENCE WRAPPER for updateMessages()
# ─────────────────────────────────────────────────────────────────────────────

def get_soil_warning_for_ui(fc_path: str) -> tuple:
    """
    Quick wrapper for use in arcpy tool updateMessages().

    Returns:
        (is_error: bool, message: str)
        is_error=True  → call param.setErrorMessage(message)
        is_error=False → call param.setWarningMessage(message)  (or nothing if message="")
    """
    try:
        result = validate_soil_fc(fc_path)
    except Exception as exc:
        return True, f"Soil validator error: {exc}"

    if result.level == 0:
        return True, result.warning          # Error — cannot proceed

    if result.level == 1 and not result.warning:
        return False, ""                     # Perfect — no message needed

    return False, result.warning             # Warning —
# <<< END OF FILE >>>
