# ccm_soil_preprocess.py
# CCM Soil Data Preprocessor — v2.06
# Compatible with ArcGIS Pro 3.x (Python 3.x + arcpy)
#
# Handles the three preprocessing steps required before soil data
# can be used by the CCM analysis tool:
#
#   Step 1 — Field Mapping : Joins companion tables so texture / class
#             data reaches the polygon geometry layer.
#   Step 2 — Normalisation : Converts raw values (%, texture codes,
#             classification names) into USCS two-letter codes.
#   Step 3 — Gap Filling   : Replaces any remaining NULL soilType
#             values with a user-specified default USCS code.
#
# Supported source databases
# ──────────────────────────
#   DSS_CANADA   Canada Detailed Soil Survey v3
#                  Shapefile (POLY_ID) + CMP table + layer table + name table
#   SLC_CANADA   Soil Landscapes of Canada v3.2
#                  File GDB with LAT (geometry), CMP, SLT, SNT tables
#   SSURGO_US    USDA SSURGO / STATSGO2
#                  MUPOLYGON (MUKEY) + tabular folder or gSSURGO .gdb
#   HWSD_GLOBAL  Harmonized World Soil Database v2
#                  HWSD2.bil raster + HWSD2.mdb Access database
#   GENERIC      Any polygon FC with sand/silt/clay % fields,
#                  a USDA texture class field, or a soil name field
#
# Output
# ──────
#   A new polygon FC with a 'soilType' field containing USCS codes.
#   This FC can be fed directly into CCMTool without any further
#   preparation — the soil validator will resolve it at Level 1.

import os
import sys
import struct
import arcpy

# ── Version ─────────────────────────────────────────────────────────────────
# Versioning aligns with MCE_CCM_V2.pyt  (v2.01, v2.02, …)
# v2.02 — TDS (NGA) + GGDM (NGA) support; shared Military Topographic UI
# v2.03 — SoilGrids 2.0 (Global) support: raster stack → USCS polygon FC
VERSION = "2.20"

# =============================================================================
# SOURCE TYPE CONSTANTS
# =============================================================================

SOURCE_AUTO      = "Auto-Detect"
SOURCE_DSS       = "DSS (Canada)"
SOURCE_SLC       = "SLC (Canada)"
SOURCE_SSURGO    = "SSURGO / STATSGO2 (US)"
SOURCE_HWSD      = "HWSD v2 (Global)"
SOURCE_MGCP        = "MGCP"
SOURCE_TDS         = "TDS (NGA)"
SOURCE_GGDM        = "GGDM (NGA)"
SOURCE_SOILGRIDS   = "SoilGrids 2.0 (Global)"
SOURCE_GENERIC     = "Generic (Any FC)"

ALL_SOURCES = [
    SOURCE_AUTO,
    SOURCE_DSS,
    SOURCE_SLC,
    SOURCE_SSURGO,
    SOURCE_HWSD,
    SOURCE_SOILGRIDS,
    SOURCE_MGCP,
    SOURCE_TDS,
    SOURCE_GGDM,
    SOURCE_GENERIC,
]

# SoilGrids 2.0 depth layer definitions
# key   : depth string used in file names  (e.g. sand_0-5cm_mean.tif)
# value : thickness in cm  (used for weighted averaging)
SOILGRIDS_DEPTH_LAYERS = {
    "0-5cm":    5,
    "5-15cm":   10,
    "15-30cm":  15,
    "30-60cm":  30,
    "60-100cm": 40,
    "100-200cm":100,
}
# Depths included in the 0-30 cm weighted mean
SOILGRIDS_TOPSOIL_DEPTHS = ["0-5cm", "5-15cm", "15-30cm"]

# Integer codes used when writing a USCS classification raster
# (RasterToPolygon produces gridcode = these integers; joined back to strings)
SOILGRIDS_USCS_INT = {
    1: "GW", 2: "GP", 3: "GM", 4: "GC",
    5: "SW", 6: "SP", 7: "SM", 8: "SC",
    9: "ML", 10: "CL", 11: "OL",
    12: "MH", 13: "CH", 14: "OH",
    15: "Pt",
    0: "NE",
}
SOILGRIDS_INT_FROM_USCS = {v: k for k, v in SOILGRIDS_USCS_INT.items()}

# =============================================================================
# USCS CODE MASTER LIST  (valid output codes for soilType field)
# =============================================================================

VALID_USCS = {
    # Gravels
    "GW", "GP", "GM", "GC",
    # Sands
    "SW", "SP", "SM", "SC",
    # Fine-grained (low plasticity)
    "ML", "CL", "OL",
    # Fine-grained (high plasticity)
    "MH", "CH", "OH",
    # Highly organic
    "Pt",
    # Not evaluated / unknown
    "NE",
}

# =============================================================================
# LOOKUP TABLES
# =============================================================================

# ── USDA texture class → USCS (simplified for CCM)  ─────────────────────────
# Source: USACE EM-1110-1-1905 Table B-3; Ayers et al. (2011) overlay method.
# For CCM the key distinction is trafficability tier, so we collapse fine
# distinctions that share the same RCI tier.
USDA_TEXCL_TO_USCS = {
    # USDA class       USCS   Comments
    "sand":            "SP",  # almost pure sand
    "loamy sand":      "SP",  # sand-dominant, little fines
    "sandy loam":      "SM",  # sand + silty fines
    "loam":            "ML",  # balanced — silt-dominant for CCM
    "silt loam":       "ML",  # silt loam
    "silt":            "ML",  # very silty
    "sandy clay loam": "SC",  # sand + clay fines
    "clay loam":       "CL",  # medium clay
    "silty clay loam": "CL",  # medium clay, silty
    "sandy clay":      "SC",  # high sand + high clay
    "silty clay":      "CH",  # high silt + high clay
    "clay":            "CH",  # high clay
    # Some labs report these variants
    "gravelly sand":         "GP",
    "gravelly loamy sand":   "GM",
    "gravelly sandy loam":   "GM",
    "gravelly loam":         "GM",
    "coarse sand":           "SP",
    "fine sandy loam":       "SM",
    "very fine sandy loam":  "ML",
    "heavy clay":            "CH",
    "organic":               "Pt",
    "peat":                  "Pt",
    "muck":                  "Pt",
    "rock":                  "NE",
    "water":                 "NE",
    "ice":                   "NE",
    "urban":                 "NE",
    "miscellaneous":         "NE",
    "variable":              "NE",
}

# ── Canadian PMTEX first-character → USCS ───────────────────────────────────
# PMTEX in DSS/SLC Name tables stores parent-material texture codes as 2-char
# strings where the first character gives the broad texture class:
#   C = Coarse  (sands, gravels, coarse tills)
#   M = Medium  (loams, sandy loams, silt loams)
#   F = Fine    (clay loams, clays, fine tills)
#   O = Organic (peats, mucks)
#   R = Bedrock
#   W = Water
#   - = Not specified / missing
# The second character is the texture of the underlying layer (or '-' if absent).
PMTEX_FIRST_TO_USCS = {
    "C": "SP",   # Coarse → poorly-graded sand / silty sand
    "M": "ML",   # Medium → silt / sandy silt
    "F": "CL",   # Fine   → clay loam
    "O": "Pt",   # Organic → peat
    "R": "NE",   # Bedrock → not evaluated
    "W": "NE",   # Water → not evaluated
}

# ── Canadian soil ORDER → approximate USCS fallback ─────────────────────────
# Used when neither texture % nor PMTEX are available.
# Keys are 2-char Canadian Soil Classification Order codes from the SNT table.
CANADIAN_ORDER_TO_USCS = {
    "BL": "ML",   # Brunisolic → typically loamy / silty
    "CH": "ML",   # Chernozemic → silty loam to clay loam
    "CR": "NE",   # Cryosolic → permafrost; varies widely
    "GL": "ML",   # Gleysolic → fine-textured, moist
    "LH": "ML",   # Luvisolic → loam / clay loam
    "MN": "ML",   # Brunisolic (older code)
    "OR": "Pt",   # Organic → peat / muck
    "PD": "SP",   # Podzolic → sandy / coarse
    "RE": "NE",   # Regosolic → weakly developed; variable
    "SO": "ML",   # Solonetzic → clay / clay loam
    "UG": "NE",   # Unclassified / disturbed
    "GH": "NE",   # Anthropogenic / disturbed
    "RM": "NE",   # Rocky material
    "WA": "NE",   # Water
    "IC": "NE",   # Ice
}

# ── USDA Soil Taxonomy Orders → approximate USCS fallback ────────────────────
# 12 USDA orders stored in SSURGO component.taxorder field.
# Used as Path F when sand/silt/clay % and texcl are both absent.
# Mapping is broad (order-level) — accuracy ~60-70%.
USDA_TAXORDER_TO_USCS = {
    "alfisols":    "CL",   # Moderately leached; clay-rich B horizon
    "andisols":    "ML",   # Volcanic ash soils; silty, low density
    "aridisols":   "SP",   # Desert soils; dry, sandy to loamy
    "entisols":    "SP",   # Young/undeveloped soils; often sandy
    "gelisols":    "NE",   # Permafrost soils; not trafficable
    "histosols":   "Pt",   # Organic/peat soils
    "inceptisols": "ML",   # Weakly developed; loam to silt loam
    "mollisols":   "ML",   # Grassland; dark, silty loam to clay loam
    "oxisols":     "CL",   # Heavily weathered tropical; clay-rich
    "spodosols":   "SM",   # Sandy, leached; coarse-textured
    "ultisols":    "CL",   # Leached clay soils; acidic
    "vertisols":   "CH",   # Shrink-swell clays; high plasticity
}

# ── MGCP Surface Material Code (SMC) → USCS ──────────────────────────────────
# SMC values follow the MGCP/FACC feature attribute catalogue (v4.x).
# These are integer attribute values on the Surface Cover (SU) feature class.
#
# IMPORTANT: SMC enumeration values vary between MGCP versions and suppliers.
# Verify these values against your specific MGCP Product Specification before
# use.  The dict below reflects MGCP v4.5 / FACC standard values.
# If a value is missing from this table it will fall through to
# soil_name_to_uscs() using the SMC label string as a last resort.
SMC_TO_USCS = {
    # ── Non-traversable surfaces → NE ──────────────────────────────────────
    2:   "NE",   # Bedrock
    6:   "NE",   # Concrete / paved
    12:  "NE",   # Ice / glacier (permanent)
    13:  "NE",   # Lava / volcanic rock
    17:  "NE",   # Paved road surface
    19:  "NE",   # Rock / rocky outcrop
    20:  "NE",   # Salt flat / evaporite
    24:  "NE",   # Snow / permanent snowfield
    28:  "NE",   # Water / open water
    998: "NE",   # Not applicable
    999: "NE",   # Unknown / no data
    # ── Coarse / sandy soils → SP / SM ─────────────────────────────────────
    3:   "GM",   # Boulders / cobbles
    11:  "GM",   # Gravel
    21:  "SP",   # Sand / desert sand
    32:  "SM",   # Pumice / volcanic sand
    # ── Fine-grained soils → ML / CL / CH ──────────────────────────────────
    4:   "CL",   # Clay
    14:  "ML",   # Loess / aeolian silt
    16:  "ML",   # Mud
    22:  "ML",   # Silt
    # ── Mixed / generic soils → ML ─────────────────────────────────────────
    5:   "ML",   # Composition (mixed / generic soil)
    8:   "ML",   # Earth / topsoil (generic)
    15:  "ML",   # Marsh / swamp substrate (soft)
    23:  "ML",   # Soil (unspecified)
    26:  "ML",   # Tundra (vegetation over soft ground)
    # ── Organic soils → Pt ─────────────────────────────────────────────────
    18:  "Pt",   # Peat / bog
    27:  "Pt",   # Organic / decomposed vegetation
}

# Human-readable labels for SMC codes — used as fallback text matching when
# the integer code is absent but a label field (e.g. "SMC_TXT") is present.
SMC_LABEL_TO_USCS = {
    "bedrock": "NE", "rock": "NE", "lava": "NE", "ice": "NE",
    "snow": "NE", "water": "NE", "paved": "NE", "concrete": "NE",
    "salt": "NE", "evaporite": "NE",
    "sand": "SP", "desert sand": "SP",
    "gravel": "GM", "boulders": "GM", "cobbles": "GM",
    "clay": "CL",
    "silt": "ML", "mud": "ML", "loess": "ML", "loam": "ML",
    "soil": "ML", "earth": "ML", "tundra": "ML", "marsh": "ML",
    "peat": "Pt", "bog": "Pt", "organic": "Pt",
}

# ── SSURGO / WoSIS soil-order / taxon name fragments → USCS ─────────────────
# For when sand/silt/clay % and texcl are all absent.
# soil_name_to_uscs() iterates these sorted by length (longest first) so
# compound phrases like "sandy clay loam" always win over bare "clay".
SOIL_NAME_FRAGMENTS_TO_USCS = {
    # ── Compound phrases (longest match wins) ─────────────────────────────────
    "sandy clay loam":  "SC",
    "silty clay loam":  "CL",
    "sandy clay":       "SC",
    "silty clay":       "CH",
    "clay loam":        "CL",
    "silt loam":        "ML",
    "sandy loam":       "SM",
    "loamy sand":       "SP",
    # ── Single keywords ───────────────────────────────────────────────────────
    "gravelly":  "GM",
    "organic":   "Pt",
    "gravel":    "GP",
    "sandy":     "SM",
    "loamy":     "SM",
    "rocky":     "NE",
    "water":     "NE",
    "urban":     "NE",
    "peat":      "Pt",
    "muck":      "Pt",
    "silt":      "ML",
    "loam":      "ML",
    "clay":      "CL",
    "sand":      "SP",
    "rock":      "NE",
    "fill":      "SM",
}

# ── WRB / FAO 90 soil unit codes → approximate USCS ─────────────────────────
# Used for HWSD and FAO-based datasets.
# Coverage: the 32 WRB reference soil groups + major FAO-90 units.
WRB_TO_USCS = {
    # Coarse / sandy soils
    "AR": "SP",   # Arenosols → sand
    "RQ": "SP",   # Regosols on sand
    "LP": "SP",   # Leptosols (sandy) — fallback
    # Medium-textured soils
    "CM": "ML",   # Cambisols → loam / silt loam
    "LV": "ML",   # Luvisols → silt loam to clay loam
    "LX": "ML",   # Lixisols
    "PH": "ML",   # Phaeozems → loam
    "CH": "ML",   # Chernozems → loam / clay loam
    "KS": "ML",   # Kastanozems
    "GY": "ML",   # Gypsisols
    "CL": "CL",   # Calcisols → clay loam
    "DU": "ML",   # Durisols
    "ST": "ML",   # Stagnosols
    "PL": "ML",   # Planosols
    "AB": "CL",   # Albeluvisols
    "AL": "CL",   # Alisols
    "AC": "CL",   # Acrisols
    "NT": "CL",   # Nitisols
    "FR": "CL",   # Ferralsols → clay-rich
    # Fine / clay soils
    "VR": "CH",   # Vertisols → very clayey, shrink-swell
    "SN": "CH",   # Solonetz → clay-rich
    # Organic
    "HS": "Pt",   # Histosols → peat / organic
    "HL": "Pt",   # Histosols (lacustrine)
    # Wet / hydromorphic
    "GL": "ML",   # Gleysols → fine-textured
    "FL": "ML",   # Fluvisols → alluvial, variable
    "AT": "ML",   # Anthrosols → disturbed, variable
    "TC": "ML",   # Technosols
    # Coarse / skeletal
    "RG": "SP",   # Regosols → sandy to loamy
    "SC": "ML",   # Solonchaks → saline, silty
    "PZ": "SM",   # Podzols → sandy with illuvial layer
    "UM": "SM",   # Umbrisols → loamy
    "AN": "ML",   # Andosols → variable; loamy default
    "KL": "NE",   # Kastanozem light (not standard WRB)
    # FAO-90 specific codes
    "Ah": "ML",   # Haplic Acrisol
    "Ao": "CL",   # Orthic Acrisol
    "Bf": "ML",   # Ferric Cambisol
    "Be": "ML",   # Eutric Cambisol
    "Bk": "ML",   # Calcic Cambisol
    "Bh": "ML",   # Humic Cambisol
    "Bd": "ML",   # Dystric Cambisol
    "Hh": "Pt",   # Haplic Histosol
    "Ht": "Pt",   # Thionic Histosol
    "Jc": "ML",   # Calcaric Fluvisol
    "Je": "ML",   # Eutric Fluvisol
    "Lf": "ML",   # Ferric Luvisol
    "Le": "ML",   # Eutric Luvisol
    "Vc": "CH",   # Chromic Vertisol
    "Vp": "CH",   # Pellic Vertisol
    "Zo": "ML",   # Orthic Solonchak
    "Nd": "CH",   # Dystric Nitisol
    "Nh": "CH",   # Humic Nitisol
    "Fr": "CL",   # Rhodic Ferralsol
    "Fo": "CL",   # Orthic Ferralsol
    "Ge": "SP",   # Eutric Arenosol
    "Gc": "SP",   # Cambic Arenosol
    "Pz": "SM",   # Podzols
    "Qc": "SP",   # Calcaric Regosol
    "Qe": "SP",   # Eutric Regosol
}

# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def _msg(messages, text, level="message"):
    """Unified logging: works inside arcpy tool (messages object) or standalone."""
    if messages is not None:
        if level == "warning":
            messages.addWarningMessage(text)
        elif level == "error":
            messages.addErrorMessage(text)
        else:
            messages.addMessage(text)
    else:
        prefix = {"warning": "[WARN]", "error": "[ERROR]"}.get(level, "[INFO]")
        print(f"{prefix} {text}")


def _arcpy_msg(messages, text, level="message"):
    """Same as _msg but uses arcpy.Add* as fallback (for execute() context)."""
    if messages is not None:
        _msg(messages, text, level)


def _ace_driver_available():
    """
    Check whether the 64-bit Microsoft Access Database Engine (ACE) is
    installed on this machine.

    Returns (bool, str)  — (available, detail_message)

    Checks two registry locations:
      1. HKCR\\Microsoft.ACE.OLEDB.16.0   (Office 2016 / ACE 2016, preferred)
      2. HKCR\\Microsoft.ACE.OLEDB.12.0   (ACE 2010 fallback)
      3. HKLM ODBC driver entry            (alternate registration path)
    """
    try:
        import winreg

        # Check OLE DB provider registrations (most reliable)
        for version in ("16.0", "12.0"):
            key_path = f"Microsoft.ACE.OLEDB.{version}"
            try:
                with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, key_path):
                    return True, f"ACE OLE DB {version} found."
            except FileNotFoundError:
                pass

        # Check ODBC driver registration
        odbc_path = r"SOFTWARE\ODBC\ODBCINST.INI\Microsoft Access Driver (*.mdb, *.accdb)"
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, odbc_path):
                return True, "ACE ODBC driver found."
        except FileNotFoundError:
            pass

        return (
            False,
            "Microsoft Access Database Engine (64-bit) is NOT installed.\n"
            "HWSD v2 requires it to read HWSD2.mdb.\n\n"
            "To fix:\n"
            "  1. Go to: https://www.microsoft.com/en-us/download/details.aspx?id=54920\n"
            "  2. Download 'accessdatabaseengine_X64.exe'  (the 64-bit version)\n"
            "  3. Install it, then restart ArcGIS Pro.\n\n"
            "Note: install the X64 version — ArcGIS Pro uses 64-bit Python and\n"
            "will not see the 32-bit (accessdatabaseengine.exe) driver.",
        )

    except ImportError:
        # winreg is Windows-only; on non-Windows just assume OK
        return True, "winreg not available (non-Windows)."
    except Exception as e:
        return True, f"ACE check inconclusive: {e}"
    else:
        if level == "warning":
            arcpy.AddWarning(text)
        elif level == "error":
            arcpy.AddError(text)
        else:
            arcpy.AddMessage(text)


# =============================================================================
# TEXTURE / CLASSIFICATION CONVERSION
# =============================================================================

def texture_pct_to_uscs(sand, silt, clay, cofrag=0):
    """
    Convert sand / silt / clay weight-percentages to a USCS code.

    Uses the USDA texture triangle as an intermediate step (USDA NRCS
    boundary definitions), then maps the USDA class to USCS via
    USDA_TEXCL_TO_USCS.

    Parameters
    ----------
    sand, silt, clay : float
        Percentages (0–100).  Need not sum to exactly 100; they are
        normalised internally.
    cofrag : float
        Coarse-fragment content (% by volume).  Values ≥ 30 % trigger
        a gravelly USCS class.

    Returns
    -------
    str  USCS code, or None if inputs are invalid.
    """
    try:
        s = float(sand)
        si = float(silt)
        c  = float(clay)
    except (TypeError, ValueError):
        return None

    # Reject clearly bad values (-9 = DSS missing data sentinel)
    if s < 0 or si < 0 or c < 0:
        return None
    total = s + si + c
    if total < 5:          # effectively no data
        return None

    # Normalise to 100 %
    s  = s  / total * 100
    si = si / total * 100
    c  = c  / total * 100

    # Coarse-fragment override (> 30 % gravel/cobble by volume)
    if cofrag and float(cofrag) >= 30:
        if c < 15:
            return "GP"   # Poorly-graded gravel
        elif c < 35:
            return "GM"   # Silty/clayey gravel
        else:
            return "GC"   # Clayey gravel

    # ── USDA texture triangle (NRCS boundary definitions) ────────────────
    if c >= 40:
        if si >= 40:
            usda = "silty clay"
        elif s >= 45:
            usda = "sandy clay"
        else:
            usda = "clay"
    elif c >= 35:
        # clay 35-40 %: sandy clay if sand-heavy, silty clay loam if silt-heavy,
        # else clay (the small triangular "clay" extension below 40 % on USDA chart)
        if s >= 45:
            usda = "sandy clay"
        elif si >= 40:
            usda = "silty clay loam"
        else:
            usda = "clay"
    elif c >= 27.5:
        if si >= 40:
            usda = "silty clay loam"
        elif s >= 45:
            usda = "sandy clay loam"
        else:
            usda = "clay loam"
    elif c >= 20:
        if s >= 45:
            usda = "sandy clay loam"
        elif si >= 50:
            usda = "silt loam"   # clay 20-27 % + high silt → still silt loam
        else:
            usda = "clay loam"
    elif c >= 7.5:
        if si >= 50:
            usda = "silt loam"
        elif s >= 52.5:
            usda = "sandy loam"
        elif s >= 25:
            usda = "loam"
        else:
            usda = "silt loam"
    else:
        # Clay < 7.5 %
        if si >= 80:
            usda = "silt"
        elif si >= 50:
            usda = "silt loam"
        elif s >= 85:
            usda = "sand"
        elif s >= 70:
            usda = "loamy sand"
        else:
            usda = "sandy loam"

    # ── USCS fines-content override ───────────────────────────────────────
    # USDA "sand" and "loamy sand" map to SP (clean sand).  However, when
    # total fines (silt + clay) exceed 20 % the material will behave more
    # like SM under load — trafficability degrades noticeably.  We apply a
    # 20 % threshold (rather than the strict USCS 12 %) because USDA silt
    # includes some fine-sand-sized particles that USCS would count as sand,
    # so the effective fines content for USCS is usually lower than USDA %.
    # No plasticity index is available, so SC is not used here; SM is the
    # conservative, CCM-safe choice.
    if usda in ("sand", "loamy sand") and (si + c) >= 20:
        usda = "sandy loam"   # → SM via USDA_TEXCL_TO_USCS

    return USDA_TEXCL_TO_USCS.get(usda, "ML")


def usda_texcl_to_uscs(texcl_raw):
    """
    Convert a raw USDA texture class string to a USCS code.

    Handles mixed case, extra spaces, and common abbreviations.
    """
    if not texcl_raw:
        return None
    key = str(texcl_raw).strip().lower()
    # Direct lookup
    if key in USDA_TEXCL_TO_USCS:
        return USDA_TEXCL_TO_USCS[key]
    # Fuzzy match on fragments
    for fragment, uscs in SOIL_NAME_FRAGMENTS_TO_USCS.items():
        if fragment in key:
            return uscs
    return None


def pmtex_to_uscs(pmtex_raw):
    """
    Convert a Canadian DSS/SLC PMTEX code to a USCS code.

    Only the first character (upper-layer texture class) is used:
      C = Coarse → SP
      M = Medium → ML
      F = Fine   → CL
      O = Organic → Pt
      R = Rock → NE
      W = Water → NE
    """
    if not pmtex_raw:
        return None
    first = str(pmtex_raw).strip().upper()[:1]
    return PMTEX_FIRST_TO_USCS.get(first)


def wrb_to_uscs(wrb_raw):
    """
    Convert a WRB or FAO-90 soil unit code to a USCS code.

    Tries exact match first, then 2-char prefix match.
    """
    if not wrb_raw:
        return None
    key = str(wrb_raw).strip()
    if key in WRB_TO_USCS:
        return WRB_TO_USCS[key]
    if len(key) >= 2 and key[:2] in WRB_TO_USCS:
        return WRB_TO_USCS[key[:2]]
    return None


def soil_name_to_uscs(name_raw):
    """
    Derive an approximate USCS code from a free-text soil name.

    Scans SOIL_NAME_FRAGMENTS_TO_USCS for keyword matches in the
    lowercased name string.  Longer fragments are tested before shorter
    ones so that "sandy loam" matches before the bare "sand" fragment.
    """
    if not name_raw:
        return None
    key = str(name_raw).strip().lower()
    for fragment in sorted(SOIL_NAME_FRAGMENTS_TO_USCS, key=len, reverse=True):
        if fragment in key:
            return SOIL_NAME_FRAGMENTS_TO_USCS[fragment]
    return None


# =============================================================================
# DBF / TABLE READER  (pure Python — no arcpy dependency for reading)
# =============================================================================

def read_dbf(dbf_path, key_field=None, value_fields=None, encoding="latin-1"):
    """
    Read a dBASE III+ (.dbf) file and return a list of dicts.

    Parameters
    ----------
    key_field    : str or None
        If given, return a dict keyed on this field instead of a list.
    value_fields : list[str] or None
        Subset of columns to keep.  None = keep all.
    encoding     : str
        Character encoding (default latin-1 covers most legacy DBFs).

    Returns
    -------
    list[dict]  or  dict  (if key_field is given)
    """
    if not os.path.isfile(dbf_path):
        raise FileNotFoundError(f"DBF not found: {dbf_path!r}")

    with open(dbf_path, "rb") as f:
        header      = f.read(32)
        num_records = struct.unpack_from("<I", header, 4)[0]
        header_size = struct.unpack_from("<H", header, 8)[0]
        record_size = struct.unpack_from("<H", header, 10)[0]

        fields = []
        while True:
            fd = f.read(32)
            if fd[0] == 0x0D:
                break
            name = fd[:11].replace(b"\x00", b"").decode("ascii", errors="replace").strip()
            ftype = chr(fd[11])
            flen  = fd[16]
            fields.append((name, ftype, flen))

        # Skip any remaining header bytes to reach the first record
        f.seek(header_size + 1)

        keep = set(value_fields) if value_fields else None

        rows = []
        for _ in range(num_records):
            raw = f.read(record_size)
            if not raw or raw[0] == 0x1A:
                break
            if raw[0] == 0x2A:        # deleted record
                continue
            row    = {}
            offset = 1
            for fname, ftype, flen in fields:
                chunk = raw[offset : offset + flen]
                offset += flen
                if keep and fname not in keep:
                    continue
                val = chunk.decode(encoding, errors="replace").strip()
                row[fname] = val
            rows.append(row)

    if key_field:
        return {r[key_field]: r for r in rows if key_field in r}
    return rows


def read_arcpy_table(table_path, key_field=None, value_fields=None):
    """
    Read any table readable by arcpy (GDB table, shapefile attribute table,
    in-memory table, etc.) into a list of dicts.

    Slower than read_dbf but works for GDB tables and non-dbf formats.
    """
    fields = [f.name for f in arcpy.ListFields(table_path)
              if f.type not in ("Geometry", "Blob", "Raster")]
    if value_fields:
        fields = [f for f in fields if f in (value_fields + ([key_field] if key_field else []))]

    rows = []
    with arcpy.da.SearchCursor(table_path, fields) as cur:
        for row in cur:
            d = dict(zip(fields, row))
            rows.append(d)

    if key_field:
        return {r[key_field]: r for r in rows if key_field in r and r[key_field]}
    return rows


# =============================================================================
# SOURCE AUTO-DETECTION
# =============================================================================

def detect_source_type(fc_path, aux_folder=None):
    """
    Heuristically detect which soil database a feature class came from.

    Detection hierarchy
    ───────────────────
    1. File naming patterns (dss_*, mupolygon, HWSD2, slc_*)
    2. Field names present in the FC attribute table
    3. Presence of companion files in aux_folder

    Returns one of the SOURCE_* constants.
    """
    if not fc_path:
        return SOURCE_GENERIC

    name_lower = os.path.basename(str(fc_path)).lower()

    # ── Name-based heuristics ────────────────────────────────────────────────
    if "dss_" in name_lower or name_lower.startswith("dss"):
        return SOURCE_DSS
    if "mupolygon" in name_lower or "ssurgo" in name_lower or "statsgo" in name_lower:
        return SOURCE_SSURGO
    if "hwsd" in name_lower:
        return SOURCE_HWSD
    if "slc" in name_lower or "soil_landscapes" in name_lower:
        return SOURCE_SLC
    # SoilGrids 2.0: files named  sand_0-5cm_mean.tif / silt_… / clay_…
    if name_lower.startswith(("sand_", "silt_", "clay_")) and name_lower.endswith(".tif"):
        return SOURCE_SOILGRIDS
    if "soilgrids" in name_lower:
        return SOURCE_SOILGRIDS
    # Military topographic name hints
    if "su_sfc" in name_lower or "mgcp" in name_lower:
        return SOURCE_MGCP
    if "surfacecovera" in name_lower or "_tds" in name_lower or "tds_" in name_lower:
        return SOURCE_TDS
    if "surfacemateriala" in name_lower or "ggdm" in name_lower:
        return SOURCE_GGDM

    # ── Folder-level fingerprinting (SoilGrids folder supplied as path) ─────
    if os.path.isdir(str(fc_path)):
        try:
            files_lower = [f.lower() for f in os.listdir(fc_path)]
            if any(f.startswith(("sand_", "silt_", "clay_")) and f.endswith(".tif")
                   for f in files_lower):
                return SOURCE_SOILGRIDS
        except Exception:
            pass

    # ── GDB-level fingerprinting (for MGCP / TDS / GGDM passed as GDB path) ─
    # When the user supplies the GDB root rather than a specific FC, check what
    # feature classes exist inside to identify the schema.
    if str(fc_path).lower().endswith(".gdb") and arcpy.Exists(fc_path):
        try:
            old_ws = arcpy.env.workspace
            arcpy.env.workspace = fc_path
            gdb_fcs = {f.lower() for f in (arcpy.ListFeatureClasses() or [])}
            arcpy.env.workspace = old_ws
            if "surfacemateriala" in gdb_fcs:
                return SOURCE_GGDM
            if "surfacecovera" in gdb_fcs:
                return SOURCE_TDS
            if "su_sfc" in gdb_fcs:
                return SOURCE_MGCP
        except Exception:
            pass

    # ── Field-based heuristics ───────────────────────────────────────────────
    try:
        field_names = {f.name.upper() for f in arcpy.ListFields(fc_path)}
    except Exception:
        return SOURCE_GENERIC

    if "MUKEY" in field_names:
        return SOURCE_SSURGO
    if "MU_GLOBAL" in field_names or "MU_SRC" in field_names:
        return SOURCE_HWSD
    if "POLY_ID" in field_names and "HECTARES" in field_names:
        # Could be DSS or SLC — check folder for clues
        if aux_folder:
            folder_contents = os.listdir(aux_folder) if os.path.isdir(aux_folder) else []
            folder_lower    = " ".join(folder_contents).lower()
            if "cmp" in folder_lower:
                return SOURCE_DSS
            if ".gdb" in folder_lower:
                return SOURCE_SLC
        return SOURCE_DSS   # Default for bare POLY_ID+HECTARES shapefile
    # FACC / military topo: SMC field present
    if "SMC" in field_names or "SMCL" in field_names:
        return SOURCE_MGCP   # Conservative default; user can override

    if "SAND" in field_names or "SILT" in field_names or "CLAY" in field_names:
        return SOURCE_GENERIC
    if "TSAND" in field_names or "TSILT" in field_names:
        return SOURCE_GENERIC   # Already has texture — treat as generic
    if "TEXCL" in field_names:
        return SOURCE_GENERIC

    return SOURCE_GENERIC


# =============================================================================
# RESULT CLASS
# =============================================================================

class PreprocessResult:
    """Lightweight result container returned by each preprocess_* function."""

    def __init__(self):
        self.source_type      = SOURCE_GENERIC
        self.output_fc        = None
        self.total_features   = 0
        self.mapped_count     = 0    # features that got a USCS code from Step 2
        self.gap_filled_count = 0    # features that needed Step 3 gap fill
        self.null_count       = 0    # features still NULL after gap fill
        self.uscs_distribution = {}  # {uscs_code: count}
        self.warnings         = []

    @property
    def success(self):
        return self.output_fc is not None and arcpy.Exists(self.output_fc)

    def summary(self):
        lines = [
            f"Source       : {self.source_type}",
            f"Output FC    : {self.output_fc}",
            f"Total features     : {self.total_features:,}",
            f"Codes resolved     : {self.mapped_count:,}",
            f"Gap filled (Step 3): {self.gap_filled_count:,}",
            f"Still NULL         : {self.null_count:,}",
        ]
        if self.uscs_distribution:
            lines.append("USCS distribution  :")
            for code, count in sorted(self.uscs_distribution.items(),
                                      key=lambda x: -x[1]):
                lines.append(f"    {code:<6}  {count:,}")
        return "\n".join(lines)


# =============================================================================
# STEP 3 — GAP FILLING  (shared across all sources)
# =============================================================================

# Sentinel value that activates the smart three-tier algorithm
GAP_FILL_SMART = "Smart (auto)"


def gap_fill_soil_fc(fc_path, default_uscs="NE", soil_field="soilType", messages=None):
    """
    Fixed-code gap fill: assign default_uscs to every NULL soilType feature.

    Parameters
    ----------
    fc_path      : str   Path to the polygon FC to modify in place.
    default_uscs : str   USCS code to assign (default 'NE').
    soil_field   : str   Name of the field to fill (default 'soilType').
    messages     : arcpy messages object or None.

    Returns
    -------
    int   Number of features that were gap-filled.
    """
    if default_uscs not in VALID_USCS:
        _arcpy_msg(messages, f"Gap-fill code '{default_uscs}' is not a standard USCS code. "
                   f"Using 'NE' instead.", "warning")
        default_uscs = "NE"

    filled = 0
    with arcpy.da.UpdateCursor(fc_path, [soil_field]) as cur:
        for row in cur:
            val = row[0]
            if val is None or str(val).strip() == "":
                row[0] = default_uscs
                cur.updateRow(row)
                filled += 1

    if filled:
        _arcpy_msg(messages, f"[Step 3 — Gap Fill]  {filled:,} feature(s) filled with '{default_uscs}'.")
    else:
        _arcpy_msg(messages, "[Step 3 — Gap Fill]  No NULL values found — "
                   "all features already have a soilType.")

    return filled


def smart_gap_fill_soil_fc(fc_path, soil_field="soilType",
                            matched_poly_ids=None, poly_id_field=None,
                            messages=None):
    """
    Data-only gap fill.  No inference, no interpolation from neighbours.

    Rule: if we have no soil data for a polygon, we do not invent one.
    Unknown soil = NE (Non-Engineerable) — safer for CCM than a wrong guess.

    Two passes:

    Pass 1 — Known non-soil  (DSS / SLC only)
    ──────────────────────────────────────────
    If matched_poly_ids is provided, any polygon whose POLY_ID was *never*
    found in the CMP companion table gets 'NE'.  Those polygons genuinely
    have no soil record — they represent water bodies, rock outcrops, urban
    footprints, ice, etc.  This is a data-driven assignment, not a guess.

    Pass 2 — Remaining NULLs
    ─────────────────────────
    Any polygon still NULL after Pass 1 had a CMP entry but the texture /
    classification data in that entry was missing or unreadable.  It also
    gets 'NE'.  We have no data; we make no assumption.

    Parameters
    ----------
    fc_path          : str   Polygon FC to modify in place.
    soil_field       : str   Field containing USCS codes (default 'soilType').
    matched_poly_ids : set   POLY_IDs that had CMP matches.  None to skip
                             Pass 1 (all NULLs go straight to Pass 2).
    poly_id_field    : str   Name of the POLY_ID field in fc_path.
    messages         : arcpy messages object or None.

    Returns
    -------
    dict  { 'known_non_soil': int, 'no_data': int, 'total': int }
    """
    counts = {"known_non_soil": 0, "no_data": 0, "total": 0}

    def _count_nulls():
        n = 0
        with arcpy.da.SearchCursor(fc_path, [soil_field]) as c:
            for r in c:
                if r[0] is None or str(r[0]).strip() == "":
                    n += 1
        return n

    initial_nulls = _count_nulls()
    if initial_nulls == 0:
        _arcpy_msg(messages, "[Step 3 — Gap Fill]  No NULL values — skipped.")
        return counts

    _arcpy_msg(messages, f"[Step 3 — Gap Fill]  {initial_nulls:,} polygons have no soil data.")

    # ── Pass 1: Known non-soil polygons (POLY_ID absent from CMP table) ───────
    if matched_poly_ids is not None and poly_id_field:
        kns = 0
        with arcpy.da.UpdateCursor(fc_path, [poly_id_field, soil_field]) as cur:
            for row in cur:
                if row[1] is None or str(row[1]).strip() == "":
                    pid = str(row[0] or "").strip()
                    if pid and pid not in matched_poly_ids:
                        row[1] = "NE"
                        cur.updateRow(row)
                        kns += 1
        counts["known_non_soil"] = kns
        if kns:
            _arcpy_msg(messages,
                       f"  Pass 1 (known non-soil)  : {kns:,} polygons → 'NE'  "
                       f"[POLY_ID not in source CMP table — confirmed non-soil feature]")

    # ── Pass 2: Remaining NULLs — no data available, assign NE ───────────────
    nd = 0
    with arcpy.da.UpdateCursor(fc_path, [soil_field]) as cur:
        for row in cur:
            if row[0] is None or str(row[0]).strip() == "":
                row[0] = "NE"
                cur.updateRow(row)
                nd += 1
    counts["no_data"] = nd
    if nd:
        _arcpy_msg(messages,
                   f"  Pass 2 (no data)         : {nd:,} polygons → 'NE'  "
                   f"[soil record existed but texture/classification data was missing]")

    counts["total"] = counts["known_non_soil"] + counts["no_data"]
    _arcpy_msg(messages,
               f"[Step 3 — Gap Fill]  Complete.\n"
               f"    Known non-soil (Pass 1)  : {counts['known_non_soil']:,}\n"
               f"    No data available (Pass 2): {counts['no_data']:,}\n"
               f"    Total filled             : {counts['total']:,}")
    return counts


def _dispatch_gap_fill(fc_path, gap_fill_code, soil_field="soilType",
                        matched_poly_ids=None, poly_id_field=None, messages=None):
    """
    Route to the correct gap-fill strategy based on gap_fill_code.

    If gap_fill_code == GAP_FILL_SMART  → smart_gap_fill_soil_fc()
    Otherwise                           → gap_fill_soil_fc() with fixed code

    Returns int (total features filled) for compatibility with result tracking.
    """
    if gap_fill_code == GAP_FILL_SMART:
        result = smart_gap_fill_soil_fc(
            fc_path,
            soil_field        = soil_field,
            matched_poly_ids  = matched_poly_ids,
            poly_id_field     = poly_id_field,
            messages          = messages,
        )
        return result.get("total", 0)
    else:
        return gap_fill_soil_fc(
            fc_path,
            default_uscs = gap_fill_code,
            soil_field   = soil_field,
            messages     = messages,
        )


# =============================================================================
# CRS GUARD — auto-reproject geographic output to match extent CRS
# =============================================================================

def _ensure_projected_crs(output_fc, reference_fc=None, messages=None):
    """
    If *output_fc* is in a Geographic CRS (degrees), attempt to auto-reproject
    it to match *reference_fc*'s Projected CRS.

    This is called automatically after every preprocess_* run so that sources
    whose native data is in WGS 1984 (HWSD, SoilGrids) produce output that is
    immediately usable in the CCM Mobility Map tool without a manual Project
    step.

    Strategy
    --------
    1. If output is already projected  → do nothing, return immediately.
    2. If a projected reference_fc is available  → reproject in-place
       (Project to temp → Delete original → Rename temp back).
    3. If no projected reference available  → emit a clear warning with the
       manual fix instructions; leave the FC untouched.

    The reproject overwrites the original path so that result.output_fc remains
    valid and downstream code needs no changes.
    """
    # ── 1. Check output CRS ───────────────────────────────────────────────────
    try:
        sr = arcpy.Describe(output_fc).spatialReference
    except Exception:
        return output_fc   # cannot describe — leave as-is

    if sr.type != "Geographic":
        return output_fc   # already projected, nothing to do

    # ── 2. Find a projected target CRS from the reference FC ─────────────────
    target_sr = None
    if reference_fc:
        ref_str = str(reference_fc).strip()
        if ref_str and arcpy.Exists(ref_str):
            try:
                ref_sr = arcpy.Describe(ref_str).spatialReference
                if ref_sr.type == "Projected":
                    target_sr = ref_sr
            except Exception:
                pass

    # ── 3a. No projected reference → warn and exit ───────────────────────────
    if target_sr is None:
        _arcpy_msg(messages,
                   "\n[CRS]  Output is in a Geographic CRS ({name}).\n"
                   "  The CCM tool requires a Projected CRS (metres).\n"
                   "  Quick fix:\n"
                   "    • Re-run with an Analysis Extent polygon in your project CRS\n"
                   "      (the tool will auto-reproject the output to match it), OR\n"
                   "    • Run the 'Project' tool (Data Management ▸ Projections)\n"
                   "      on the output FC and use the reprojected version in CCM."
                   .format(name=sr.name),
                   "warning")
        return output_fc

    # ── 3b. Reproject in-place ────────────────────────────────────────────────
    _arcpy_msg(messages,
               "\n[CRS]  Output is geographic ({src}) — auto-reprojecting to\n"
               "       match extent CRS: {tgt}..."
               .format(src=sr.name, tgt=target_sr.name))

    workspace = os.path.dirname(output_fc)
    fc_name   = os.path.basename(output_fc)
    tmp_name  = fc_name + "_prjtmp"
    tmp_path  = os.path.join(workspace, tmp_name)

    try:
        if arcpy.Exists(tmp_path):
            arcpy.management.Delete(tmp_path)

        # Project to temp (ArcGIS auto-selects datum transformation)
        arcpy.management.Project(output_fc, tmp_path, target_sr)

        # Swap: delete original, rename temp to original name
        arcpy.management.Delete(output_fc)
        arcpy.management.Rename(tmp_path, fc_name)

        _arcpy_msg(messages,
                   "[CRS]  Reprojection complete → {}.".format(target_sr.name))

    except Exception as e:
        _arcpy_msg(messages,
                   "[CRS]  Auto-reproject failed: {}\n"
                   "  Run the 'Project' tool manually before using this FC in CCM."
                   .format(e),
                   "warning")
        # Clean up temp if it was partially created
        try:
            if arcpy.Exists(tmp_path):
                arcpy.management.Delete(tmp_path)
        except Exception:
            pass

    return output_fc


# =============================================================================
# STEP 1+2 — DSS CANADA  (Detailed Soil Survey)
# =============================================================================

def _find_dss_tables(folder):
    """
    Auto-discover DSS companion tables in folder.

    Returns a dict with optional keys: 'cmp', 'layer', 'name'.
    """
    found = {}
    if not folder or not os.path.isdir(folder):
        return found
    for fname in os.listdir(folder):
        fl = fname.lower()
        full = os.path.join(folder, fname)
        if fl.endswith(".dbf"):
            if "cmp" in fl and "cmp" not in found:
                found["cmp"] = full
            elif any(x in fl for x in ("layer", "_slt", "slayer")) and "layer" not in found:
                found["layer"] = full
            elif any(x in fl for x in ("name", "_snt", "sname")) and "name" not in found:
                found["name"] = full
    return found


def preprocess_dss(soil_fc, output_fc,
                   cmp_table=None, layer_table=None, name_table=None,
                   extent_fc=None, gap_fill_code="NE",
                   messages=None):
    """
    Process a Canadian DSS shapefile (POLY_ID, HECTARES) by joining its
    companion tables and deriving a soilType USCS field.

    Data flow
    ─────────
    dss_*.shp (POLY_ID)
        └─ CMP table  (POLY_ID → dominant component → SOIL_ID)
               └─ Layer table (SOIL_ID → TSAND, TSILT, TCLAY)  [Step 2a]
               └─ Name table  (SOIL_ID → PMTEX1)               [Step 2b fallback]
                              (SOIL_ID → ORDER2)                [Step 2c fallback]

    Parameters
    ----------
    soil_fc      : str   Path to the bare DSS polygon shapefile / FC.
    output_fc    : str   Output FC path (new FC created here).
    cmp_table    : str   Path to CMP .dbf (component table).
    layer_table  : str   Path to soil layer .dbf.
    name_table   : str   Path to soil name .dbf (optional, for PMTEX fallback).
    extent_fc    : str   Optional extent polygon for clipping.
    gap_fill_code: str   USCS code for Step 3 gap fill.
    messages     : arcpy messages object or None.

    Returns
    -------
    PreprocessResult
    """
    result = PreprocessResult()
    result.source_type = SOURCE_DSS

    _arcpy_msg(messages, "=" * 60)
    _arcpy_msg(messages, "[CCM Soil Preprocess]  Source: DSS Canada")
    _arcpy_msg(messages, "=" * 60)

    # ── Validate inputs ───────────────────────────────────────────────────────
    if not arcpy.Exists(soil_fc):
        _arcpy_msg(messages, f"Soil FC not found: {soil_fc!r}", "error")
        return result
    if not cmp_table or not os.path.isfile(cmp_table):
        _arcpy_msg(messages, "Component table (.dbf) not provided or not found. "
                   "Cannot derive SOIL_ID from POLY_ID.", "error")
        return result

    # ── Step 1a: Read CMP table — build POLY_ID → dominant SOIL_ID map ────────
    _arcpy_msg(messages, "[Step 1 — Field Mapping]  Reading component table...")
    cmp_rows = read_dbf(cmp_table, value_fields=["POLY_ID", "CMP", "PERCENT", "SOIL_ID"])

    # Select dominant component per POLY_ID:
    #   Primary strategy  : CMP == '1' (first-listed = dominant by extent)
    #   Fallback strategy : highest PERCENT value
    poly_to_soil = {}
    poly_percent  = {}
    for row in cmp_rows:
        pid  = row.get("POLY_ID", "").strip()
        soil = row.get("SOIL_ID", "").strip()
        cmp  = row.get("CMP", "").strip()
        pct_raw = row.get("PERCENT", "0").strip()
        if not pid or not soil:
            continue
        try:
            pct = float(pct_raw) if pct_raw else 0.0
        except ValueError:
            pct = 0.0

        if cmp == "1":
            poly_to_soil[pid] = soil          # CMP=1 wins immediately
        elif pid not in poly_to_soil and pct > poly_percent.get(pid, -1):
            poly_to_soil[pid] = soil           # Highest % among non-CMP-1
            poly_percent[pid] = pct

    _arcpy_msg(messages, f"  Component table: {len(cmp_rows):,} rows → "
               f"{len(poly_to_soil):,} dominant polygon–soil pairs.")

    # ── Step 1b: Read layer table — build SOIL_ID → texture data ─────────────
    soil_to_texture = {}
    if layer_table and os.path.isfile(layer_table):
        _arcpy_msg(messages, "[Step 1 — Field Mapping]  Reading soil layer table...")
        layer_rows = read_dbf(layer_table,
                              value_fields=["SOIL_ID", "LAYER_NO", "UDEPTH",
                                            "TSAND", "TSILT", "TCLAY",
                                            "COFRAG", "ORGCARB", "VONPOST"])
        # Select best layer per SOIL_ID:
        #   1. Prefer LAYER_NO == '1'
        #   2. Else: minimum UDEPTH (shallowest)
        #   3. Any row with valid texture if still unresolved
        layer_priority = {}    # SOIL_ID → (priority_score, row)
        for row in layer_rows:
            sid = row.get("SOIL_ID", "").strip()
            if not sid:
                continue
            ln = row.get("LAYER_NO", "").strip()
            try:
                ud = float(row.get("UDEPTH", "9999").strip() or "9999")
            except ValueError:
                ud = 9999

            # Score: LAYER_NO=1 gets 0, others get UDEPTH (lower = better)
            score = 0 if ln == "1" else ud

            if sid not in layer_priority or score < layer_priority[sid][0]:
                layer_priority[sid] = (score, row)

        for sid, (_, row) in layer_priority.items():
            sand_raw  = row.get("TSAND",  "").strip()
            silt_raw  = row.get("TSILT",  "").strip()
            clay_raw  = row.get("TCLAY",  "").strip()
            cofrag    = row.get("COFRAG", "").strip()
            orgcarb   = row.get("ORGCARB","").strip()
            vonpost   = row.get("VONPOST","").strip()

            def safe_float(v):
                try:
                    f = float(v)
                    return f if f >= 0 else None   # -9 = missing in DSS
                except (ValueError, TypeError):
                    return None

            soil_to_texture[sid] = {
                "sand":   safe_float(sand_raw),
                "silt":   safe_float(silt_raw),
                "clay":   safe_float(clay_raw),
                "cofrag": safe_float(cofrag),
                "orgcarb": safe_float(orgcarb),
                "vonpost": safe_float(vonpost),
            }

        _arcpy_msg(messages, f"  Layer table: {len(layer_rows):,} rows → "
                   f"{len(soil_to_texture):,} unique SOIL_ID texture records.")
    else:
        _arcpy_msg(messages, "  Layer table not provided — texture % path skipped.", "warning")

    # ── Step 1c: Read name table — build SOIL_ID → PMTEX / ORDER ─────────────
    soil_to_meta = {}
    if name_table and os.path.isfile(name_table):
        _arcpy_msg(messages, "[Step 1 — Field Mapping]  Reading soil name table (PMTEX fallback)...")
        name_rows = read_dbf(name_table,
                             value_fields=["SOIL_ID", "PMTEX1", "PMTEX2",
                                           "DRAINAGE", "KIND", "ORDER2"])
        for row in name_rows:
            sid = row.get("SOIL_ID", "").strip()
            if sid:
                soil_to_meta[sid] = row
        _arcpy_msg(messages, f"  Name table: {len(name_rows):,} soil records loaded.")

    # ── Step 2: Normalise — derive USCS for each POLY_ID ─────────────────────
    _arcpy_msg(messages, "[Step 2 — Normalisation]  Deriving USCS codes...")

    poly_to_uscs = {}
    path2a = path2b = path2c = 0

    for pid, sid in poly_to_soil.items():
        uscs = None

        # 2a — Texture %  (most accurate)
        if sid in soil_to_texture:
            t = soil_to_texture[sid]
            s, si, cl = t.get("sand"), t.get("silt"), t.get("clay")
            cof = t.get("cofrag") or 0
            orx = t.get("orgcarb") or 0
            vp  = t.get("vonpost") or 0

            # Organic override (VONPOST > 0 or very high organic carbon)
            if vp and vp > 0:
                uscs = "Pt"
            elif orx and orx > 30:
                uscs = "Pt"
            elif s is not None and si is not None and cl is not None:
                uscs = texture_pct_to_uscs(s, si, cl, cof)

            if uscs:
                path2a += 1

        # 2b — PMTEX fallback (parent material texture code)
        if not uscs and sid in soil_to_meta:
            pmtex = soil_to_meta[sid].get("PMTEX1", "").strip()
            kind  = soil_to_meta[sid].get("KIND", "").strip().upper()
            if kind in ("O", "P"):
                uscs = "Pt"     # Organic / peat
            else:
                uscs = pmtex_to_uscs(pmtex)
            if uscs:
                path2b += 1

        # 2c — Canadian soil Order fallback
        if not uscs and sid in soil_to_meta:
            order = soil_to_meta[sid].get("ORDER2", "").strip().upper()
            uscs  = CANADIAN_ORDER_TO_USCS.get(order)
            if uscs:
                path2c += 1

        if uscs:
            poly_to_uscs[pid] = uscs

    _arcpy_msg(messages,
               f"  Resolved via texture %   : {path2a:,}\n"
               f"  Resolved via PMTEX code  : {path2b:,}\n"
               f"  Resolved via soil Order  : {path2c:,}\n"
               f"  Total resolved           : {len(poly_to_uscs):,} "
               f"of {len(poly_to_soil):,} polygons")

    # ── Create output FC ──────────────────────────────────────────────────────
    _arcpy_msg(messages, "[Step 1 — Output]  Copying geometry to output FC...")

    # Clip to extent if provided
    if extent_fc and arcpy.Exists(extent_fc):
        arcpy.analysis.Clip(soil_fc, extent_fc, output_fc)
        _arcpy_msg(messages, f"  Clipped to extent: {extent_fc}")
    else:
        arcpy.management.CopyFeatures(soil_fc, output_fc)

    # Add soilType field
    arcpy.management.AddField(output_fc, "soilType", "TEXT", field_length=10)

    result.total_features = int(arcpy.management.GetCount(output_fc)[0])
    result.output_fc      = output_fc

    # ── Write soilType values ─────────────────────────────────────────────────
    _arcpy_msg(messages, "[Step 2 — Output]  Writing soilType field...")
    written = 0
    with arcpy.da.UpdateCursor(output_fc, ["POLY_ID", "soilType"]) as cur:
        for row in cur:
            pid = str(row[0]).strip() if row[0] else ""
            uscs = poly_to_uscs.get(pid)
            if uscs:
                row[1] = uscs
                cur.updateRow(row)
                written += 1

    result.mapped_count = written
    _arcpy_msg(messages, f"  soilType written to {written:,} of {result.total_features:,} features.")

    # ── Step 3: Gap fill ──────────────────────────────────────────────────────
    # Pass matched_poly_ids so Smart fill can identify non-soil polygons
    # (those NOT in the CMP table) and assign 'NE' with high confidence.
    result.gap_filled_count = _dispatch_gap_fill(
        output_fc, gap_fill_code,
        matched_poly_ids = set(poly_to_soil.keys()),
        poly_id_field    = "POLY_ID",
        messages         = messages,
    )

    # ── Tally final distribution ──────────────────────────────────────────────
    dist = {}
    null_ct = 0
    with arcpy.da.SearchCursor(output_fc, ["soilType"]) as cur:
        for row in cur:
            v = row[0]
            if v is None or str(v).strip() == "":
                null_ct += 1
            else:
                dist[str(v).strip()] = dist.get(str(v).strip(), 0) + 1
    result.null_count          = null_ct
    result.uscs_distribution   = dist

    _arcpy_msg(messages, "\n" + result.summary())
    return result


# =============================================================================
# STEP 1+2 — SLC CANADA  (Soil Landscapes of Canada v3.2 .gdb)
# =============================================================================

def preprocess_slc(gdb_path, output_fc,
                   extent_fc=None, gap_fill_code="NE",
                   messages=None):
    """
    Process a Soil Landscapes of Canada v3.2 File Geodatabase.

    The GDB contains (at minimum):
      LAT or SLC_* feature class  — polygon geometry with POLY_ID
      CMP table                   — POLY_ID, CMP, PERCENT, SOIL_ID
      SLT table                   — SOIL_ID, LAYER_NO, TSAND, TSILT, TCLAY
      SNT table                   — SOIL_ID, SOILNAME, PMTEX1, ORDER2
    """
    result = PreprocessResult()
    result.source_type = SOURCE_SLC

    _arcpy_msg(messages, "=" * 60)
    _arcpy_msg(messages, "[CCM Soil Preprocess]  Source: SLC Canada (GDB)")
    _arcpy_msg(messages, "=" * 60)

    if not arcpy.Exists(gdb_path):
        _arcpy_msg(messages, f"GDB not found: {gdb_path!r}", "error")
        return result

    # ── Discover tables and feature class inside the GDB ─────────────────────
    arcpy.env.workspace = gdb_path

    fcs     = arcpy.ListFeatureClasses() or []
    tables  = arcpy.ListTables()         or []

    def find_by_name(items, *keywords):
        kws = [k.lower() for k in keywords]
        for item in items:
            il = item.lower()
            if any(k in il for k in kws):
                return os.path.join(gdb_path, item)
        return None

    soil_fc_gdb = find_by_name(fcs, "lat", "slc", "polygon", "soil")
    cmp_tbl     = find_by_name(tables, "cmp", "component")
    slt_tbl     = find_by_name(tables, "slt", "layer")
    snt_tbl     = find_by_name(tables, "snt", "name", "soil_name")

    arcpy.env.workspace = None

    if not soil_fc_gdb:
        _arcpy_msg(messages, "No polygon feature class found in GDB.", "error")
        return result

    _arcpy_msg(messages, f"  Polygon FC  : {soil_fc_gdb}")
    _arcpy_msg(messages, f"  CMP table   : {cmp_tbl or '(not found)'}")
    _arcpy_msg(messages, f"  Layer table : {slt_tbl or '(not found)'}")
    _arcpy_msg(messages, f"  Name table  : {snt_tbl or '(not found)'}")

    # ── Read tables using arcpy (GDB tables can't be read with read_dbf) ──────
    def arcpy_table_to_dict(tbl_path, key, fields):
        if not tbl_path or not arcpy.Exists(tbl_path):
            return {}
        avail = {f.name.upper() for f in arcpy.ListFields(tbl_path)}
        actual_fields = [f for f in fields if f.upper() in avail]
        d = {}
        with arcpy.da.SearchCursor(tbl_path, actual_fields) as cur:
            for row in cur:
                r = dict(zip(actual_fields, row))
                k = str(r.get(key, "") or "").strip()
                if k and k not in d:
                    d[k] = r
        return d

    # Build same dicts as preprocess_dss then delegate to shared logic
    poly_to_soil   = {}
    poly_percent_m = {}

    if cmp_tbl:
        _arcpy_msg(messages, "[Step 1]  Reading CMP table...")
        cmp_fields = ["POLY_ID", "CMP", "PERCENT", "SOIL_ID"]
        avail = {f.name.upper() for f in arcpy.ListFields(cmp_tbl)}
        cmp_fields = [f for f in cmp_fields if f.upper() in avail]
        with arcpy.da.SearchCursor(cmp_tbl, cmp_fields) as cur:
            for row in cur:
                r   = dict(zip(cmp_fields, row))
                pid = str(r.get("POLY_ID") or "").strip()
                sid = str(r.get("SOIL_ID") or "").strip()
                cmp = str(r.get("CMP")     or "").strip()
                try:
                    pct = float(r.get("PERCENT") or 0)
                except (ValueError, TypeError):
                    pct = 0.0
                if not pid or not sid:
                    continue
                if cmp == "1":
                    poly_to_soil[pid] = sid
                elif pid not in poly_to_soil and pct > poly_percent_m.get(pid, -1):
                    poly_to_soil[pid]   = sid
                    poly_percent_m[pid] = pct

    soil_to_texture = {}
    if slt_tbl:
        _arcpy_msg(messages, "[Step 1]  Reading SLT layer table...")
        slt_fields = ["SOIL_ID", "LAYER_NO", "UDEPTH", "TSAND", "TSILT", "TCLAY", "COFRAG"]
        avail = {f.name.upper() for f in arcpy.ListFields(slt_tbl)}
        slt_fields = [f for f in slt_fields if f.upper() in avail]
        layer_priority = {}
        with arcpy.da.SearchCursor(slt_tbl, slt_fields) as cur:
            for row in cur:
                r   = dict(zip(slt_fields, row))
                sid = str(r.get("SOIL_ID") or "").strip()
                if not sid:
                    continue
                ln  = str(r.get("LAYER_NO") or "").strip()
                try:
                    ud = float(r.get("UDEPTH") or 9999)
                except (ValueError, TypeError):
                    ud = 9999
                score = 0 if ln == "1" else ud
                if sid not in layer_priority or score < layer_priority[sid][0]:
                    layer_priority[sid] = (score, r)
        for sid, (_, r) in layer_priority.items():
            def sf(v):
                try:
                    f = float(v or -1)
                    return f if f >= 0 else None
                except (ValueError, TypeError):
                    return None
            soil_to_texture[sid] = {
                "sand": sf(r.get("TSAND")), "silt": sf(r.get("TSILT")),
                "clay": sf(r.get("TCLAY")), "cofrag": sf(r.get("COFRAG")),
            }

    soil_to_meta = {}
    if snt_tbl:
        _arcpy_msg(messages, "[Step 1]  Reading SNT name table...")
        snt_fields = ["SOIL_ID", "PMTEX1", "PMTEX2", "KIND", "ORDER2", "DRAINAGE"]
        avail = {f.name.upper() for f in arcpy.ListFields(snt_tbl)}
        snt_fields = [f for f in snt_fields if f.upper() in avail]
        with arcpy.da.SearchCursor(snt_tbl, snt_fields) as cur:
            for row in cur:
                r   = dict(zip(snt_fields, row))
                sid = str(r.get("SOIL_ID") or "").strip()
                if sid:
                    soil_to_meta[sid] = r

    # ── Step 2: Derive USCS ───────────────────────────────────────────────────
    _arcpy_msg(messages, "[Step 2 — Normalisation]  Deriving USCS codes...")
    poly_to_uscs = {}
    for pid, sid in poly_to_soil.items():
        uscs = None
        if sid in soil_to_texture:
            t = soil_to_texture[sid]
            if (t.get("sand") is not None and t.get("silt") is not None
                    and t.get("clay") is not None):
                uscs = texture_pct_to_uscs(t["sand"], t["silt"], t["clay"],
                                           t.get("cofrag") or 0)
        if not uscs and sid in soil_to_meta:
            kind = str(soil_to_meta[sid].get("KIND") or "").strip().upper()
            if kind in ("O", "P"):
                uscs = "Pt"
            else:
                uscs = pmtex_to_uscs(str(soil_to_meta[sid].get("PMTEX1") or ""))
        if not uscs and sid in soil_to_meta:
            order = str(soil_to_meta[sid].get("ORDER2") or "").strip().upper()
            uscs  = CANADIAN_ORDER_TO_USCS.get(order)
        if uscs:
            poly_to_uscs[pid] = uscs

    # ── Copy geometry and write field ─────────────────────────────────────────
    if extent_fc and arcpy.Exists(extent_fc):
        arcpy.analysis.Clip(soil_fc_gdb, extent_fc, output_fc)
    else:
        arcpy.management.CopyFeatures(soil_fc_gdb, output_fc)

    arcpy.management.AddField(output_fc, "soilType", "TEXT", field_length=10)
    result.total_features = int(arcpy.management.GetCount(output_fc)[0])
    result.output_fc      = output_fc

    written = 0
    fld_names = [f.name for f in arcpy.ListFields(output_fc)]
    poly_fld  = next((f for f in fld_names if f.upper() == "POLY_ID"), None)
    if poly_fld:
        with arcpy.da.UpdateCursor(output_fc, [poly_fld, "soilType"]) as cur:
            for row in cur:
                pid  = str(row[0] or "").strip()
                uscs = poly_to_uscs.get(pid)
                if uscs:
                    row[1] = uscs
                    cur.updateRow(row)
                    written += 1

    result.mapped_count     = written
    # SLC also has POLY_ID — pass matched_poly_ids for Tier 1 non-soil detection
    result.gap_filled_count = _dispatch_gap_fill(
        output_fc, gap_fill_code,
        matched_poly_ids = set(poly_to_soil.keys()),
        poly_id_field    = poly_fld,
        messages         = messages,
    )

    dist = {}
    null_ct = 0
    with arcpy.da.SearchCursor(output_fc, ["soilType"]) as cur:
        for row in cur:
            v = row[0]
            if v is None or str(v).strip() == "":
                null_ct += 1
            else:
                dist[str(v).strip()] = dist.get(str(v).strip(), 0) + 1
    result.null_count        = null_ct
    result.uscs_distribution = dist

    _arcpy_msg(messages, "\n" + result.summary())
    return result


# =============================================================================
# STEP 1+2 — SSURGO / STATSGO2 (US)
# =============================================================================

def preprocess_ssurgo(mupolygon_fc, tabular_folder_or_gdb, output_fc,
                      extent_fc=None, gap_fill_code="NE",
                      messages=None):
    """
    Process a USDA SSURGO or STATSGO2 dataset.

    Spatial layer: MUPOLYGON shapefile or feature class containing MUKEY.

    Tabular data (two accepted layouts)
    ─────────────────────────────────────
    A) Folder layout (standard SSURGO download):
         tabular/mapunit.txt  — MUKEY
         tabular/comp.txt     — MUKEY, COKEY, comppct_r, compname
         tabular/chorizon.txt — COKEY, CHKEY, hzdept_r, sandtotal_r,
                                silttotal_r, claytotal_r, texcl
    B) gSSURGO .gdb layout:
         MapUnit table
         Component table
         Chorizon table

    Field aliases recognised (case-insensitive):
      MUKEY  : mukey, mu_key, mapunit_key, musym (last resort)
      sand   : sandtotal_r, sand_r, tsand, sand, s
      silt   : silttotal_r, silt_r, tsilt, silt, si
      clay   : claytotal_r, clay_r, tclay, clay, c
      texcl  : texcl, texture_class, tex_class, texture
    """
    result = PreprocessResult()
    result.source_type = SOURCE_SSURGO

    _arcpy_msg(messages, "=" * 60)
    _arcpy_msg(messages, "[CCM Soil Preprocess]  Source: SSURGO / STATSGO2 (US)")
    _arcpy_msg(messages, "=" * 60)

    if not arcpy.Exists(mupolygon_fc):
        _arcpy_msg(messages, f"MUPOLYGON FC not found: {mupolygon_fc!r}", "error")
        return result

    # ── Locate tabular data ───────────────────────────────────────────────────
    is_gdb = str(tabular_folder_or_gdb).lower().endswith(".gdb")
    tabular_folder = None
    tabular_gdb    = None

    if is_gdb:
        tabular_gdb = tabular_folder_or_gdb
    else:
        # Look for 'tabular' subfolder
        if os.path.isdir(os.path.join(tabular_folder_or_gdb, "tabular")):
            tabular_folder = os.path.join(tabular_folder_or_gdb, "tabular")
        elif os.path.isdir(tabular_folder_or_gdb):
            tabular_folder = tabular_folder_or_gdb

    def _find_ssurgo_field(fc_or_table, *candidates):
        """Case-insensitive field finder for SSURGO tables."""
        avail = {f.name.lower(): f.name for f in arcpy.ListFields(fc_or_table)}
        for c in candidates:
            if c.lower() in avail:
                return avail[c.lower()]
        return None

    def _read_table(source, required_fields, optional_fields=()):
        """Read a SSURGO tabular file (txt or GDB table)."""
        if is_gdb:
            tbl = os.path.join(tabular_gdb, source)
            if not arcpy.Exists(tbl):
                return []
        else:
            # Try common SSURGO txt filenames
            candidates = [
                os.path.join(tabular_folder, f"{source}.txt"),
                os.path.join(tabular_folder, f"{source}.dbf"),
                os.path.join(tabular_folder, source),
            ]
            tbl = next((p for p in candidates if os.path.isfile(p)), None)
            if not tbl:
                return []

        avail = {f.name.lower(): f.name for f in arcpy.ListFields(tbl)}
        fields = []
        for f in list(required_fields) + list(optional_fields):
            if f.lower() in avail:
                fields.append(avail[f.lower()])
        if not fields:
            return []
        rows = []
        with arcpy.da.SearchCursor(tbl, fields) as cur:
            for row in cur:
                rows.append(dict(zip(fields, row)))
        return rows

    # ── Read component table → MUKEY → dominant COKEY ────────────────────────
    _arcpy_msg(messages, "[Step 1]  Reading component table...")
    comp_rows = _read_table(
        "component",
        required_fields=["mukey", "cokey"],
        optional_fields=["comppct_r", "compname", "taxclname", "taxorder"],
    )

    if not comp_rows:
        _arcpy_msg(messages, "Component table not found or empty. "
                   "Check tabular folder or gDB path.", "error")
        return result

    mukey_to_cokey   = {}
    mukey_pct        = {}
    cokey_to_taxorder = {}   # Path F fallback
    for r in comp_rows:
        muk = str(r.get("mukey") or r.get("MUKEY") or "").strip()
        cok = str(r.get("cokey") or r.get("COKEY") or "").strip()
        try:
            pct = float(r.get("comppct_r") or r.get("COMPPCT_R") or 0)
        except (ValueError, TypeError):
            pct = 0.0
        if not muk or not cok:
            continue
        if pct > mukey_pct.get(muk, -1):
            mukey_to_cokey[muk] = cok
            mukey_pct[muk]      = pct
        # Store taxorder for every cokey regardless of dominance
        tax = str(r.get("taxorder") or r.get("TAXORDER") or "").strip().lower()
        if tax and cok:
            cokey_to_taxorder[cok] = tax

    _arcpy_msg(messages, f"  {len(mukey_to_cokey):,} map-unit → dominant-component pairs.")

    # ── Read chorizon table → COKEY → surface texture ─────────────────────────
    _arcpy_msg(messages, "[Step 1]  Reading chorizon table...")
    horiz_rows = _read_table(
        "chorizon",
        required_fields=["cokey", "hzdept_r"],
        optional_fields=["sandtotal_r", "silttotal_r", "claytotal_r", "texcl",
                          "hzdepb_r", "fragvol_r"],
    )

    cokey_to_texture = {}
    cokey_depth      = {}
    for r in horiz_rows:
        cok = str(r.get("cokey") or r.get("COKEY") or "").strip()
        try:
            depth = float(r.get("hzdept_r") or r.get("HZDEPT_R") or 9999)
        except (ValueError, TypeError):
            depth = 9999
        if not cok:
            continue
        if depth < cokey_depth.get(cok, 9999):
            cokey_depth[cok] = depth

            def sf(v):
                try:
                    return float(v) if v is not None else None
                except (ValueError, TypeError):
                    return None

            cokey_to_texture[cok] = {
                "sand":   sf(r.get("sandtotal_r") or r.get("SANDTOTAL_R")),
                "silt":   sf(r.get("silttotal_r") or r.get("SILTTOTAL_R")),
                "clay":   sf(r.get("claytotal_r") or r.get("CLAYTOTAL_R")),
                "texcl":  str(r.get("texcl") or r.get("TEXCL") or "").strip(),
                "cofrag": sf(r.get("fragvol_r") or r.get("FRAGVOL_R")),
            }

    # ── Step 2: Derive USCS per MUKEY ────────────────────────────────────────
    _arcpy_msg(messages, "[Step 2 — Normalisation]  Deriving USCS codes...")
    mukey_to_uscs = {}
    for muk, cok in mukey_to_cokey.items():
        uscs = None
        if cok in cokey_to_texture:
            t = cokey_to_texture[cok]
            s, si, cl = t.get("sand"), t.get("silt"), t.get("clay")
            texcl     = t.get("texcl")
            cofrag    = t.get("cofrag") or 0

            # Path A: sand/silt/clay % → USDA triangle
            if s is not None and si is not None and cl is not None:
                uscs = texture_pct_to_uscs(s, si, cl, cofrag)
            # Path B: USDA texture class string
            elif texcl:
                uscs = usda_texcl_to_uscs(texcl)

        # Path F: USDA Taxonomy Order (last resort — ~60-70% accurate)
        if not uscs:
            taxorder = cokey_to_taxorder.get(cok, "")
            if taxorder:
                uscs = USDA_TAXORDER_TO_USCS.get(taxorder)

        if uscs:
            mukey_to_uscs[muk] = uscs

    # ── Create output, write field ─────────────────────────────────────────────
    if extent_fc and arcpy.Exists(extent_fc):
        arcpy.analysis.Clip(mupolygon_fc, extent_fc, output_fc)
    else:
        arcpy.management.CopyFeatures(mupolygon_fc, output_fc)

    arcpy.management.AddField(output_fc, "soilType", "TEXT", field_length=10)
    result.total_features = int(arcpy.management.GetCount(output_fc)[0])
    result.output_fc      = output_fc

    mukey_fld = _find_ssurgo_field(output_fc, "mukey", "MUKEY", "mu_key")
    written = 0
    if mukey_fld:
        with arcpy.da.UpdateCursor(output_fc, [mukey_fld, "soilType"]) as cur:
            for row in cur:
                muk  = str(row[0] or "").strip()
                uscs = mukey_to_uscs.get(muk)
                if uscs:
                    row[1] = uscs
                    cur.updateRow(row)
                    written += 1
    else:
        _arcpy_msg(messages, "MUKEY field not found in output FC.", "warning")

    result.mapped_count     = written
    result.gap_filled_count = _dispatch_gap_fill(output_fc, gap_fill_code, messages=messages)

    dist = {}
    null_ct = 0
    with arcpy.da.SearchCursor(output_fc, ["soilType"]) as cur:
        for row in cur:
            v = row[0]
            if v is None or str(v).strip() == "":
                null_ct += 1
            else:
                dist[str(v).strip()] = dist.get(str(v).strip(), 0) + 1
    result.null_count        = null_ct
    result.uscs_distribution = dist

    _arcpy_msg(messages, "\n" + result.summary())
    return result


# =============================================================================
# STEP 1+2 — HWSD v2 (Global raster + Access DB)
# =============================================================================

def preprocess_hwsd(raster_path, hwsd_db_path, output_fc,
                    extent_fc=None, gap_fill_code="NE",
                    messages=None):
    """
    Process the Harmonized World Soil Database v2 raster.

    Workflow
    ────────
    1. Convert .bil raster to polygons (or clip to extent first).
    2. Read HWSD2.mdb (Access DB) via arcpy:
         HWSD2_SMU  → MU_GLOBAL, HWSD2_SMU_ID, SHARE (dominant component)
         HWSD2_LAYERS → HWSD2_SMU_ID, LAYER (1=topsoil), T_SAND, T_SILT, T_CLAY,
                        WRB2006 (classification code), FAO90 (alt classification)
    3. Derive USCS from T_SAND/T_SILT/T_CLAY (primary) or WRB2006 code (fallback).
    4. Join USCS to the polygon FC via the raster VALUE field (= MU_GLOBAL).
    5. Gap fill NULLs.

    Note: Reading HWSD2.mdb requires the Microsoft Access Database Engine
    (ACE) driver, which is installed with ArcGIS Pro.  The mdb is accessed
    as an OLE DB data source via arcpy.da.

    Parameters
    ----------
    raster_path  : str  Path to HWSD2.bil raster.
    hwsd_db_path : str  Path to HWSD2.mdb Access database.
    output_fc    : str  Output polygon FC path.
    extent_fc    : str  Optional analysis extent polygon.
    gap_fill_code: str  USCS code for gap fill.
    messages     : arcpy messages object or None.
    """
    result = PreprocessResult()
    result.source_type = SOURCE_HWSD

    _arcpy_msg(messages, "=" * 60)
    _arcpy_msg(messages, "[CCM Soil Preprocess]  Source: HWSD v2 (Global)")
    _arcpy_msg(messages, "=" * 60)

    if not arcpy.Exists(raster_path):
        _arcpy_msg(messages, f"HWSD raster not found: {raster_path!r}", "error")
        return result
    if not os.path.isfile(hwsd_db_path):
        _arcpy_msg(messages, f"HWSD2.mdb not found: {hwsd_db_path!r}", "error")
        return result

    sa_available = arcpy.CheckExtension("Spatial") == "Available"

    # ── Step 1: Raster → polygons ─────────────────────────────────────────────
    _arcpy_msg(messages, "[Step 1]  Converting HWSD raster to polygons...")
    scratch_gdb  = arcpy.env.scratchGDB
    raster_clipped = raster_path

    if extent_fc and arcpy.Exists(extent_fc):
        if sa_available:
            arcpy.CheckOutExtension("Spatial")
            try:
                ext_desc = arcpy.Describe(extent_fc)
                arcpy.env.extent = ext_desc.extent
                clipped_ras = arcpy.sa.ExtractByMask(raster_path, extent_fc)
                raster_clipped = os.path.join(scratch_gdb, "hwsd_clip")
                clipped_ras.save(raster_clipped)
                arcpy.env.extent = None
            except Exception as e:
                _arcpy_msg(messages, f"Raster clip failed ({e}); using full raster.", "warning")
            finally:
                arcpy.CheckInExtension("Spatial")
        else:
            _arcpy_msg(messages, "Spatial Analyst not available — skipping raster clip.", "warning")

    raw_poly = os.path.join(scratch_gdb, "hwsd_poly_raw")
    arcpy.conversion.RasterToPolygon(raster_clipped, raw_poly, "NO_SIMPLIFY", "Value")

    # 'gridcode' in output = pixel value
    #   HWSD v1:  MU_GLOBAL  (needs mu_to_smu lookup to reach SMU_ID)
    #   HWSD v2:  HWSD2_SMU_ID  (direct key into texture/USCS tables)
    if extent_fc and arcpy.Exists(extent_fc) and not sa_available:
        arcpy.analysis.Clip(raw_poly, extent_fc, output_fc)
    else:
        arcpy.management.CopyFeatures(raw_poly, output_fc)

    result.total_features = int(arcpy.management.GetCount(output_fc)[0])
    arcpy.management.AddField(output_fc, "soilType", "TEXT", field_length=10)

    # ── Step 1b: Read HWSD2.mdb tables ───────────────────────────────────────
    # HWSD2 v2.0 schema (2022 release) — field names differ from v1:
    #   Raster pixel value  = HWSD2_SMU_ID  (NOT MU_GLOBAL — that field is gone)
    #   HWSD2_SMU  fields   : HWSD2_SMU_ID, SHARE, WRB4, WRB2, FAO90, ...
    #   HWSD2_LAYERS fields : HWSD2_SMU_ID, LAYER, SAND, SILT, CLAY, ... (no T_ prefix)
    # We read via three independent methods and use the first that succeeds.
    # Method 1: pyodbc  (ACE ODBC driver — separate from arcpy's OLE DB path)
    # Method 2: win32com ADODB (raw COM dispatch — different init than arcpy)
    # Method 3: arcpy workspace (last resort)
    _arcpy_msg(messages, "[Step 1]  Reading HWSD2.mdb...")
    _arcpy_msg(messages, f"  MDB path: {hwsd_db_path}")

    # ── driver diagnostic (printed once, helps diagnose ACE issues) ───────
    def _log_ace_diagnostic():
        lines = []
        try:
            import pyodbc
            acc_drivers = [d for d in pyodbc.drivers()
                           if "access" in d.lower() or "mdb" in d.lower()]
            if acc_drivers:
                lines.append(f"  [diag] pyodbc Access drivers: {acc_drivers}")
            else:
                lines.append("  [diag] pyodbc available but NO Access ODBC driver found.")
                lines.append("         Run:  accessdatabaseengine_X64.exe /quiet")
        except ImportError:
            lines.append("  [diag] pyodbc not installed in this Python environment.")
            lines.append("         Install via ArcGIS Pro > Python Package Manager > pyodbc")
        try:
            import winreg
            # ADODB.Connection is registered under HKEY_CLASSES_ROOT
            # (which merges HKLM\SOFTWARE\Classes and HKCU\SOFTWARE\Classes)
            winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "ADODB.Connection")
            lines.append("  [diag] ADODB.Connection COM class: registered (win32com path OK)")
        except Exception:
            lines.append("  [diag] ADODB.Connection COM class: not found")
        for ln in lines:
            _arcpy_msg(messages, ln)

    _log_ace_diagnostic()

    def _read_mdb_pyodbc(db_path, table_name, fields):
        """Method 1 — pyodbc ODBC driver. Returns (rows|None, error_str|None)."""
        try:
            import pyodbc
        except ImportError:
            return None, "pyodbc not installed"
        conn_str = (
            r"Driver={Microsoft Access Driver (*.mdb, *.accdb)};"
            f"DBQ={db_path};"
        )
        try:
            conn   = pyodbc.connect(conn_str, autocommit=True)
            cursor = conn.cursor()
            col_names = [col.column_name.upper()
                         for col in cursor.columns(table=table_name)]
            if not col_names:
                conn.close()
                return None, f"Table '{table_name}' not found (pyodbc)"
            actual  = [f for f in fields if f.upper() in col_names]
            select_cols = ", ".join(f"[{f}]" for f in actual)
            cursor.execute(f"SELECT {select_cols} FROM [{table_name}]")
            rows = [dict(zip(actual, row)) for row in cursor.fetchall()]
            conn.close()
            return rows, None
        except Exception as e:
            return None, str(e)

    def _read_mdb_win32com(db_path, table_name, fields):
        """Method 2 — win32com ADODB (OLE DB via raw COM, not arcpy's path)."""
        try:
            import win32com.client
        except ImportError:
            return None, "win32com not available"
        try:
            conn = win32com.client.Dispatch("ADODB.Connection")
            conn.Open(
                f"Provider=Microsoft.ACE.OLEDB.12.0;"
                f"Data Source={db_path};"
                f"Persist Security Info=False;"
            )
            rs = win32com.client.Dispatch("ADODB.Recordset")
            rs.Open(f"SELECT * FROM [{table_name}]", conn, 3, 1)
            col_names = [rs.Fields(i).Name.upper()
                         for i in range(rs.Fields.Count)]
            actual = [f for f in fields if f.upper() in col_names]
            idx    = {f.upper(): i for i, f in enumerate(col_names)}
            rows   = []
            while not rs.EOF:
                row_vals = [rs.Fields(idx[f.upper()]).Value for f in actual]
                rows.append(dict(zip(actual, row_vals)))
                rs.MoveNext()
            rs.Close()
            conn.Close()
            return rows, None
        except Exception as e:
            return None, str(e)

    def _read_mdb_arcpy(db_path, table_name, fields):
        """Method 3 — arcpy workspace (OLE DB via arcpy internals)."""
        rows = []
        old_ws = arcpy.env.workspace
        try:
            tbl_path = os.path.join(db_path, table_name)
            if arcpy.Exists(tbl_path):
                avail  = {f.name.upper() for f in arcpy.ListFields(tbl_path)}
                actual = [f for f in fields if f.upper() in avail]
                with arcpy.da.SearchCursor(tbl_path, actual) as cur:
                    for row in cur:
                        rows.append(dict(zip(actual, row)))
                return rows, None
            arcpy.env.workspace = db_path
            all_tables = arcpy.ListTables() or []
            match = next((t for t in all_tables
                          if t.upper() == table_name.upper()), None)
            if match:
                avail  = {f.name.upper() for f in arcpy.ListFields(match)}
                actual = [f for f in fields if f.upper() in avail]
                with arcpy.da.SearchCursor(match, actual) as cur:
                    for row in cur:
                        rows.append(dict(zip(actual, row)))
                return rows, None
            visible = ", ".join(all_tables) if all_tables else "(none)"
            return [], f"Table not found. arcpy sees: [{visible}]"
        except Exception as e:
            return [], str(e)
        finally:
            arcpy.env.workspace = old_ws

    def read_mdb_table(table_name, fields):
        """Try all three methods in order; return first success."""
        # Method 1: pyodbc
        rows, err = _read_mdb_pyodbc(hwsd_db_path, table_name, fields)
        if rows is not None and rows:
            _arcpy_msg(messages, f"  [{table_name}]  {len(rows):,} rows  (method: pyodbc)")
            return rows
        _arcpy_msg(messages, f"  [{table_name}]  pyodbc: {err}")

        # Method 2: win32com ADODB
        rows, err = _read_mdb_win32com(hwsd_db_path, table_name, fields)
        if rows is not None and rows:
            _arcpy_msg(messages, f"  [{table_name}]  {len(rows):,} rows  (method: win32com)")
            return rows
        _arcpy_msg(messages, f"  [{table_name}]  win32com: {err}")

        # Method 3: arcpy workspace
        rows, err = _read_mdb_arcpy(hwsd_db_path, table_name, fields)
        if rows:
            _arcpy_msg(messages, f"  [{table_name}]  {len(rows):,} rows  (method: arcpy)")
            return rows
        _arcpy_msg(messages, f"  [{table_name}]  arcpy: {err}", "warning")

        # All three failed — emit a clear fix message
        _arcpy_msg(messages, (
            f"  [{table_name}]  ALL read methods failed.\n"
            "  Most likely cause: Microsoft Access Database Engine (64-bit) not\n"
            "  properly installed.  Fix:\n"
            "    1. Download AccessDatabaseEngine_X64.exe from microsoft.com\n"
            "    2. Install with:  AccessDatabaseEngine_X64.exe /quiet\n"
            "       (the /quiet flag is required when 32-bit Office is installed)\n"
            "    3. Restart ArcGIS Pro completely and retry."
        ), "warning")
        return []

    # ── Auto-detect HWSD schema version from actual field names ──────────────
    # Rather than hardcoding v1 or v2 field names, we probe the first row of
    # each table to discover which fields are present, then adapt accordingly.
    #
    # HWSD v1 (pre-2022)          │  HWSD v2 (2022 release)
    # ────────────────────────────┼──────────────────────────────────────────
    # Raster value = MU_GLOBAL    │  Raster value = HWSD2_SMU_ID  (direct)
    # SMU table has MU_GLOBAL     │  SMU table has NO MU_GLOBAL
    # Texture: T_SAND/T_SILT/T_CLAY│ Texture: SAND/SILT/CLAY (no T_ prefix)
    # Classification: WRB2006     │  Classification: WRB4, WRB2
    # SMU table: HWSD1_SMU_ID     │  SMU table: HWSD2_SMU_ID

    # Read with all candidate fields for both versions — missing ones are skipped
    smu_rows   = read_mdb_table("HWSD2_SMU", [
        # v1 fields
        "MU_GLOBAL", "HWSD1_SMU_ID", "HWSD2_SMU_ID", "SHARE",
        "WRB2006", "FAO90",
        # v2 fields
        "WRB4", "WRB2",
    ])
    layer_rows = read_mdb_table("HWSD2_LAYERS", [
        "HWSD2_SMU_ID", "HWSD1_SMU_ID", "LAYER",
        # v1 texture fields
        "T_SAND", "T_SILT", "T_CLAY",
        # v2 texture fields
        "SAND", "SILT", "CLAY",
        "WRB2006", "FAO90",
    ])

    # ── Hard stop if both tables empty ────────────────────────────────────────
    if not smu_rows and not layer_rows:
        _arcpy_msg(messages,
                   "[HWSD]  Both tables returned 0 rows — .mdb could not be read.\n"
                   "  Possible causes:\n"
                   "    1. 64-bit ACE driver conflict with 32-bit Microsoft Office.\n"
                   "       Workaround: run the installer from Command Prompt as Admin:\n"
                   "         accessdatabaseengine_X64.exe /quiet\n"
                   "    2. HWSD2.mdb is open or locked by another application.\n"
                   "    3. The file is corrupted — try re-downloading HWSD2 from FAO.",
                   "error")
        return result
    if not layer_rows:
        _arcpy_msg(messages,
                   "[HWSD]  HWSD2_LAYERS returned 0 rows — cannot derive texture.",
                   "error")
        return result

    _arcpy_msg(messages,
               f"  HWSD2_SMU:    {len(smu_rows):,} rows\n"
               f"  HWSD2_LAYERS: {len(layer_rows):,} rows")

    # ── Sniff schema version from first row ───────────────────────────────────
    sample_layer = layer_rows[0] if layer_rows else {}
    sample_smu   = smu_rows[0]   if smu_rows   else {}

    # Texture field names
    if "T_SAND" in sample_layer:
        f_sand, f_silt, f_clay = "T_SAND", "T_SILT", "T_CLAY"
        hwsd_ver = "v1"
    else:
        f_sand, f_silt, f_clay = "SAND", "SILT", "CLAY"
        hwsd_ver = "v2"

    # Classification field names
    f_wrb = "WRB2006" if "WRB2006" in sample_smu else ("WRB4" if "WRB4" in sample_smu else "WRB2")
    f_fao = "FAO90"

    # Raster key strategy
    # v1: raster pixel = MU_GLOBAL → look up dominant HWSD2_SMU_ID via SMU table
    # v2: raster pixel = HWSD2_SMU_ID directly
    has_mu_global = "MU_GLOBAL" in sample_smu

    _arcpy_msg(messages,
               f"  Detected schema: HWSD {hwsd_ver}  "
               f"(texture: {f_sand}/{f_silt}/{f_clay},  "
               f"raster key: {'MU_GLOBAL→SMU_ID' if has_mu_global else 'HWSD2_SMU_ID direct'},  "
               f"classification: {f_wrb})")

    # ── Build WRB classification fallback from SMU table ─────────────────────
    smu_wrb = {}
    for r in smu_rows:
        smu = str(r.get("HWSD2_SMU_ID") or r.get("HWSD1_SMU_ID") or "").strip()
        if smu:
            smu_wrb[smu] = (str(r.get(f_wrb) or "").strip()
                            or str(r.get(f_fao) or "").strip())

    # ── Build raster → SMU_ID lookup (v1 only — via MU_GLOBAL) ───────────────
    # In v2 the raster pixel IS the SMU_ID so this table is not needed.
    mu_to_smu = {}
    if has_mu_global:
        mu_share = {}
        for r in smu_rows:
            mu  = str(r.get("MU_GLOBAL") or "").strip()
            smu = str(r.get("HWSD2_SMU_ID") or r.get("HWSD1_SMU_ID") or "").strip()
            try:
                share = float(r.get("SHARE") or 0)
            except (ValueError, TypeError):
                share = 0.0
            if mu and smu and share > mu_share.get(mu, -1):
                mu_to_smu[mu] = smu
                mu_share[mu]  = share
        _arcpy_msg(messages,
                   f"  MU_GLOBAL → SMU_ID mappings: {len(mu_to_smu):,}")

    # ── Build lookup: SMU_ID → top-layer texture ─────────────────────────────
    smu_to_texture = {}
    smu_depth      = {}

    def _sf(v):
        try:
            f = float(v) if v is not None else None
            return f if f is not None and f >= 0 else None
        except (ValueError, TypeError):
            return None

    for r in layer_rows:
        smu   = str(r.get("HWSD2_SMU_ID") or r.get("HWSD1_SMU_ID") or "").strip()
        layer = r.get("LAYER")
        try:
            lnum = int(layer) if layer is not None else 9
        except (ValueError, TypeError):
            lnum = 9
        if not smu:
            continue
        if lnum < smu_depth.get(smu, 99):
            smu_depth[smu] = lnum
            smu_to_texture[smu] = {
                "sand": _sf(r.get(f_sand)),
                "silt": _sf(r.get(f_silt)),
                "clay": _sf(r.get(f_clay)),
                "wrb":  smu_wrb.get(smu, ""),
            }

    _arcpy_msg(messages,
               f"  SMU texture lookup built: {len(smu_to_texture):,} SMU(s)")

    # ── Step 2: Derive USCS per raster key ────────────────────────────────────
    _arcpy_msg(messages, "[Step 2 — Normalisation]  Deriving USCS from HWSD data...")
    smu_to_uscs = {}
    for smu, t in smu_to_texture.items():
        uscs = None
        s, si, cl = t.get("sand"), t.get("silt"), t.get("clay")
        if s is not None and si is not None and cl is not None:
            uscs = texture_pct_to_uscs(s, si, cl)
        if not uscs and t.get("wrb"):
            uscs = wrb_to_uscs(t["wrb"])
        if uscs:
            smu_to_uscs[smu] = uscs

    # ── Write soilType ────────────────────────────────────────────────────────
    _arcpy_msg(messages,
               f"  USCS codes resolved for {len(smu_to_uscs):,} SMU(s)")
    if smu_to_uscs:
        _arcpy_msg(messages,
                   f"  Sample SMU keys: {list(smu_to_uscs.keys())[:5]}")

    written          = 0
    sample_gridcodes = []
    gc_field         = "gridcode"   # RasterToPolygon always names it this
    with arcpy.da.UpdateCursor(output_fc, [gc_field, "soilType"]) as cur:
        for row in cur:
            gc = row[0]
            if gc is None:
                continue
            try:
                gc_key = str(int(gc))
            except (TypeError, ValueError):
                gc_key = str(gc).strip()
            if len(sample_gridcodes) < 5:
                sample_gridcodes.append(gc_key)

            # v1: gridcode = MU_GLOBAL → translate to SMU_ID first
            # v2: gridcode = HWSD2_SMU_ID directly → no translation needed
            if has_mu_global:
                smu_key = mu_to_smu.get(gc_key, "")
            else:
                smu_key = gc_key

            if not smu_key:
                continue
            uscs = smu_to_uscs.get(smu_key)
            if uscs:
                row[1] = uscs
                cur.updateRow(row)
                written += 1

    if sample_gridcodes:
        _arcpy_msg(messages,
                   f"  Sample gridcodes from polygon FC: {sample_gridcodes}")
    if written == 0 and smu_to_uscs:
        _arcpy_msg(messages,
                   "[HWSD]  Lookup has entries but no gridcodes matched.\n"
                   "  Verify the raster is HWSD2.bil (not HWSD1).", "warning")

    result.mapped_count     = written
    result.output_fc        = output_fc
    result.gap_filled_count = gap_fill_soil_fc(output_fc, gap_fill_code, messages=messages)

    dist = {}
    null_ct = 0
    with arcpy.da.SearchCursor(output_fc, ["soilType"]) as cur:
        for row in cur:
            v = row[0]
            if v is None or str(v).strip() == "":
                null_ct += 1
            else:
                dist[str(v).strip()] = dist.get(str(v).strip(), 0) + 1
    result.null_count        = null_ct
    result.uscs_distribution = dist

    _arcpy_msg(messages, "\n" + result.summary())
    return result


# =============================================================================
# STEP 1+2 — SOILGRIDS 2.0  (Global raster stack, 250 m)
# =============================================================================

def _find_soilgrids_rasters(folder, depth):
    """
    Locate sand / silt / clay GeoTIFFs for the requested depth in *folder*.

    SoilGrids 2.0 naming convention:
        sand_{depth}_mean.tif   e.g. sand_0-5cm_mean.tif
        silt_{depth}_mean.tif
        clay_{depth}_mean.tif

    Also accepts older/alternate suffixes  (_mean_250m, _Q0.5, etc.).

    Returns dict  {"sand": path, "silt": path, "clay": path}
    or raises FileNotFoundError if any layer is missing.
    """
    found = {}
    if not os.path.isdir(folder):
        raise FileNotFoundError(f"SoilGrids folder not found: {folder!r}")

    for var in ("sand", "silt", "clay"):
        candidates = []
        for fname in os.listdir(folder):
            fl = fname.lower()
            if fl.startswith(var + "_") and depth.lower() in fl and fl.endswith(".tif"):
                candidates.append(os.path.join(folder, fname))
        if not candidates:
            raise FileNotFoundError(
                f"No '{var}' raster found for depth '{depth}' in {folder!r}.  "
                f"Expected a file matching {var}_{depth}_mean.tif"
            )
        # Prefer *_mean* over other statistics; otherwise take first match
        mean_files = [p for p in candidates if "_mean" in os.path.basename(p).lower()]
        found[var] = mean_files[0] if mean_files else candidates[0]

    return found


def _load_raster_as_array(raster_path, extent_fc=None, messages=None):
    """
    Load a raster into a numpy float32 array, optionally clipped to extent_fc.

    Returns  (array, raster_object)  where array values are the raw pixel values
    (g/kg for SoilGrids layers — caller must ÷10 to get %).

    NoData cells are set to numpy.nan.
    Requires Spatial Analyst for clipping; falls back to unclipped if unavailable.
    """
    import numpy as np

    sa_available = arcpy.CheckExtension("Spatial") == "Available"
    ras_path = raster_path

    if extent_fc and arcpy.Exists(extent_fc):
        if sa_available:
            arcpy.CheckOutExtension("Spatial")
            try:
                clipped = arcpy.sa.ExtractByMask(raster_path, extent_fc)
                scratch = os.path.join(arcpy.env.scratchGDB,
                                       "sg_clip_" + os.path.splitext(
                                           os.path.basename(raster_path))[0][-20:])
                clipped.save(scratch)
                ras_path = scratch
            except Exception as e:
                _arcpy_msg(messages,
                           f"  Raster clip failed ({e}); using full raster.", "warning")
            finally:
                arcpy.CheckInExtension("Spatial")
        else:
            _arcpy_msg(messages,
                       "  Spatial Analyst unavailable — extent clip skipped.", "warning")

    ras    = arcpy.Raster(ras_path)
    nodata = ras.noDataValue
    arr    = arcpy.RasterToNumPyArray(ras_path, nodata_to_value=nodata if nodata is not None else -9999)
    arr    = arr.astype(np.float32)

    nd_val = nodata if nodata is not None else -9999
    arr[arr == nd_val] = np.nan
    # Also treat 0 as NoData for SoilGrids (unsampled ocean cells stored as 0)
    arr[arr < 0] = np.nan

    return arr, ras


def _classify_uscs_array_sg(sand_pct, silt_pct, clay_pct):
    """
    Vectorised USCS classification from sand / silt / clay % numpy arrays.

    Mirrors the logic in texture_pct_to_uscs() but operates element-wise on
    full raster arrays using numpy boolean masks.

    Returns an int16 array using SOILGRIDS_INT_FROM_USCS codes.
    0 = NE / NoData.
    """
    import numpy as np

    result = np.zeros(sand_pct.shape, dtype=np.int16)

    valid = (~np.isnan(sand_pct) & ~np.isnan(silt_pct) & ~np.isnan(clay_pct))
    total = np.where(valid, sand_pct + silt_pct + clay_pct, np.nan)
    valid &= (total > 5)

    # Normalise to 100 %
    s  = np.where(valid, sand_pct / total * 100, 0.0)
    si = np.where(valid, silt_pct / total * 100, 0.0)
    c  = np.where(valid, clay_pct / total * 100, 0.0)

    def assign(mask, code):
        result[valid & mask] = SOILGRIDS_INT_FROM_USCS.get(code, 0)

    # Apply in increasing priority (last assignment wins for a given pixel)
    # Low-specificity classes first, high-specificity last
    assign(np.ones(s.shape, bool), "SM")        # default: silty sand
    assign(si >= 80,               "ML")        # very silty → silt
    assign((si >= 50) & (c < 12), "ML")        # silt-dominated, low clay
    assign((si >= 50) & (c >= 12) & (c < 27), "CL")   # silty clay loam
    assign((si >= 40) & (c >= 27) & (c < 40), "MH")   # elastic silt
    assign((s  >= 70) & (c < 5),  "SP")        # clean sand
    assign((s  >= 85) & (c < 5),  "SP")        # very clean sand
    assign((s  >= 70) & (c >= 5)  & (c < 12), "SM")   # silty sand
    assign((s  >= 50) & (c >= 12) & (c < 25), "SC")   # clayey sand
    assign((c  >= 20) & (c < 35),             "CL")   # lean clay / clay loam
    assign((c  >= 35) & (c < 40),             "CH")   # fat clay (lower end)
    assign((c  >= 40),                         "CH")   # fat clay
    assign((c  >= 40) & (s >= 45),            "SC")   # sandy clay → SC in USCS
    assign((c  >= 40) & (si >= 40),           "CH")   # silty clay → CH

    result[~valid] = 0   # NE
    return result


def preprocess_soilgrids(soilgrids_folder, output_fc,
                          sand_raster=None, silt_raster=None, clay_raster=None,
                          depth_mode="0-5cm",
                          extent_fc=None, gap_fill_code="NE",
                          messages=None):
    """
    Process SoilGrids 2.0 rasters into a CCM-ready polygon FC.

    Workflow
    ────────
    1. Locate sand / silt / clay GeoTIFF(s) in *soilgrids_folder* (or use
       explicit raster paths supplied via sand_raster / silt_raster / clay_raster).
    2. Clip each raster to *extent_fc* if provided (requires Spatial Analyst).
    3. If depth_mode == 'Weighted 0-30cm': load all three topsoil layers (0-5,
       5-15, 15-30 cm) and compute a thickness-weighted average
       (5×sl1 + 10×sl2 + 15×sl3) / 30.
    4. Convert raw values from g/kg → % (÷ 10).
    5. Classify each pixel to a USCS code using the texture triangle.
    6. Write an integer USCS raster → RasterToPolygon → assign soilType string.
    7. Gap-fill remaining NULLs.

    Parameters
    ----------
    soilgrids_folder : str   Folder containing SoilGrids GeoTIFFs.
                             May be None if explicit raster paths are provided.
    output_fc        : str   Output polygon FC path.
    sand_raster      : str   Optional explicit sand raster path (overrides folder search).
    silt_raster      : str   Optional explicit silt raster path.
    clay_raster      : str   Optional explicit clay raster path.
    depth_mode       : str   One of: '0-5cm', '5-15cm', '15-30cm', '30-60cm',
                             '60-100cm', 'Weighted 0-30cm'.
                             Default: '0-5cm' (topsoil, fastest).
    extent_fc        : str   Optional analysis extent polygon (strongly recommended
                             for global rasters).
    gap_fill_code    : str   USCS code for gap fill  (default 'NE').
    messages         :       arcpy messages object or None.

    Returns
    -------
    PreprocessResult
    """
    import numpy as np

    result = PreprocessResult()
    result.source_type = SOURCE_SOILGRIDS

    _arcpy_msg(messages, "=" * 60)
    _arcpy_msg(messages, f"[CCM Soil Preprocess]  Source: {SOURCE_SOILGRIDS}")
    _arcpy_msg(messages, f"[CCM Soil Preprocess]  Depth mode: {depth_mode}")
    _arcpy_msg(messages, "=" * 60)

    scratch_gdb = arcpy.env.scratchGDB

    # ── Step 1: Locate / validate rasters ────────────────────────────────────
    _arcpy_msg(messages, "[Step 1]  Locating SoilGrids rasters...")

    if sand_raster and silt_raster and clay_raster:
        # Explicit paths supplied
        raster_sets = [{"sand": sand_raster, "silt": silt_raster, "clay": clay_raster}]
        depths_used = [depth_mode if depth_mode != "Weighted 0-30cm" else "explicit"]
        is_weighted = False
    elif depth_mode == "Weighted 0-30cm":
        is_weighted = True
        try:
            raster_sets = [_find_soilgrids_rasters(soilgrids_folder, d)
                           for d in SOILGRIDS_TOPSOIL_DEPTHS]
        except FileNotFoundError as e:
            _arcpy_msg(messages, str(e), "error")
            return result
        depths_used = SOILGRIDS_TOPSOIL_DEPTHS
    else:
        is_weighted = False
        try:
            raster_sets = [_find_soilgrids_rasters(soilgrids_folder, depth_mode)]
        except FileNotFoundError as e:
            _arcpy_msg(messages, str(e), "error")
            return result
        depths_used = [depth_mode]

    for d, rs in zip(depths_used, raster_sets):
        for var, path in rs.items():
            _arcpy_msg(messages, f"  [{d}] {var}: {path}")

    # ── Step 2: Load arrays (clip if extent provided) ────────────────────────
    _arcpy_msg(messages, "[Step 2]  Loading raster data...")

    def load_set(rset):
        arrs = {}
        ras_objs = {}
        for var in ("sand", "silt", "clay"):
            arr, ras = _load_raster_as_array(rset[var], extent_fc=extent_fc,
                                              messages=messages)
            arrs[var]     = arr
            ras_objs[var] = ras
        return arrs, ras_objs

    if is_weighted:
        # Load all three depth layers and compute weighted mean
        weights = [SOILGRIDS_DEPTH_LAYERS[d] for d in SOILGRIDS_TOPSOIL_DEPTHS]
        total_w = sum(weights)

        weighted_sand = None
        weighted_silt = None
        weighted_clay = None
        ref_ras = None

        for d, rset, w in zip(SOILGRIDS_TOPSOIL_DEPTHS, raster_sets, weights):
            _arcpy_msg(messages, f"  Loading depth {d} (weight = {w} cm)...")
            arrs, ras_objs = load_set(rset)
            if ref_ras is None:
                ref_ras = ras_objs["sand"]

            # Accumulate weighted sums (skip NaN cells)
            for var, accum in [("sand", "wsand"), ("silt", "wsilt"), ("clay", "wclay")]:
                layer = np.where(np.isnan(arrs[var]), 0.0, arrs[var]) * w
                if var == "sand":
                    weighted_sand = layer if weighted_sand is None else weighted_sand + layer
                elif var == "silt":
                    weighted_silt = layer if weighted_silt is None else weighted_silt + layer
                else:
                    weighted_clay = layer if weighted_clay is None else weighted_clay + layer

        sand_arr = weighted_sand / total_w
        silt_arr = weighted_silt / total_w
        clay_arr = weighted_clay / total_w

    else:
        arrs, ras_objs = load_set(raster_sets[0])
        sand_arr = arrs["sand"]
        silt_arr = arrs["silt"]
        clay_arr = arrs["clay"]
        ref_ras  = ras_objs["sand"]

    # ── Step 3: Convert g/kg → % ─────────────────────────────────────────────
    _arcpy_msg(messages, "[Step 3]  Converting g/kg → % and classifying to USCS...")
    sand_pct = sand_arr / 10.0
    silt_pct = silt_arr / 10.0
    clay_pct = clay_arr / 10.0

    # ── Step 4: Vectorised USCS classification ────────────────────────────────
    uscs_int_arr = _classify_uscs_array_sg(sand_pct, silt_pct, clay_pct)

    valid_pixels = int(np.sum(uscs_int_arr > 0))
    total_pixels = int(uscs_int_arr.size)
    _arcpy_msg(messages,
               f"  Classified {valid_pixels:,} / {total_pixels:,} pixels "
               f"({100*valid_pixels/max(total_pixels,1):.1f}% coverage)")

    # ── Step 5: Write USCS integer raster ────────────────────────────────────
    _arcpy_msg(messages, "[Step 5]  Writing USCS raster...")

    # Reconstruct a NumPy raster using the reference raster's spatial reference
    desc     = arcpy.Describe(ref_ras.catalogPath)
    cell_x   = ref_ras.meanCellWidth
    cell_y   = ref_ras.meanCellHeight
    ext      = ref_ras.extent
    sr       = ref_ras.spatialReference
    ll_point = arcpy.Point(ext.XMin, ext.YMin)

    uscs_ras_path = os.path.join(scratch_gdb, "sg_uscs_int")
    if arcpy.Exists(uscs_ras_path):
        arcpy.management.Delete(uscs_ras_path)

    uscs_ras = arcpy.NumPyArrayToRaster(
        uscs_int_arr, ll_point, cell_x, cell_y,
        value_to_nodata=0,
    )
    # Save to disk FIRST — DefineProjection requires a file path, not an
    # in-memory raster object.
    uscs_ras.save(uscs_ras_path)
    arcpy.management.DefineProjection(uscs_ras_path, sr)

    # ── Step 6: Raster → polygon ──────────────────────────────────────────────
    _arcpy_msg(messages, "[Step 6]  Converting to polygon FC...")
    raw_poly = os.path.join(scratch_gdb, "sg_poly_raw")
    if arcpy.Exists(raw_poly):
        arcpy.management.Delete(raw_poly)
    arcpy.conversion.RasterToPolygon(uscs_ras_path, raw_poly, "NO_SIMPLIFY", "Value")

    # Clip to extent if we couldn't do it at the raster stage
    if extent_fc and arcpy.Exists(extent_fc):
        arcpy.analysis.Clip(raw_poly, extent_fc, output_fc)
    else:
        arcpy.management.CopyFeatures(raw_poly, output_fc)

    result.total_features = int(arcpy.management.GetCount(output_fc)[0])
    _arcpy_msg(messages, f"  {result.total_features:,} polygons created.")

    # ── Step 7: Map gridcode → soilType string ────────────────────────────────
    _arcpy_msg(messages, "[Step 7]  Assigning soilType field...")
    arcpy.management.AddField(output_fc, "soilType", "TEXT", field_length=10)

    written = 0
    with arcpy.da.UpdateCursor(output_fc, ["gridcode", "soilType"]) as cur:
        for row in cur:
            code = int(row[0]) if row[0] is not None else 0
            uscs = SOILGRIDS_USCS_INT.get(code)
            if uscs and uscs != "NE":
                row[1] = uscs
                cur.updateRow(row)
                written += 1

    result.mapped_count = written
    _arcpy_msg(messages, f"  {written:,} polygons assigned a USCS code.")

    # ── Step 8: Gap fill ──────────────────────────────────────────────────────
    result.output_fc        = output_fc
    result.gap_filled_count = gap_fill_soil_fc(output_fc, gap_fill_code,
                                               messages=messages)

    # Collect final distribution
    dist    = {}
    null_ct = 0
    with arcpy.da.SearchCursor(output_fc, ["soilType"]) as cur:
        for row in cur:
            v = row[0]
            if v is None or str(v).strip() == "":
                null_ct += 1
            else:
                dist[str(v).strip()] = dist.get(str(v).strip(), 0) + 1

    result.null_count        = null_ct
    result.uscs_distribution = dist

    _arcpy_msg(messages, "\n" + result.summary())
    return result


# =============================================================================
# MILITARY TOPOGRAPHIC  — NE PRE-PASS PATTERNS
# Feature class name candidates for confirmed non-traversable / non-soil areas.
# All three schemas share FACC heritage but use different FC naming conventions.
# Lists are ordered most-common-first for fast discovery.
# =============================================================================

_NE_PATTERNS = {
    SOURCE_MGCP: [
        # Water bodies
        "WB_WATERBODY", "HY_WATERBODY", "WatercourseA", "LakeResA",
        "LakRes", "WatrcrsA", "HY_LAKE_RES", "HY_WATCRSA",
        # Built-up / urban
        "AL_BUILTUPA", "BuiltUpA", "BUA", "AL_BLDGP", "AL_RUNWAY",
        "AerFacA", "RailroadA",
        # Rock / bedrock
        "GA_ROCKAREA", "RockA", "GA_ROCK",
        # Ice / snow (permanent)
        "GA_ICEFIELD", "IcefldA", "GA_ICE",
    ],
    SOURCE_TDS: [
        # Water bodies  (TDS 6.0 / 7.0)
        "WaterbodyA", "LakeResA", "LakeA", "RiverA", "SeaA",
        "InlandWaterA", "InundatedA", "SwampA",
        # Built-up / urban
        "BuiltUpAreaA", "BuildingA", "RunwayA",
        "MilitaryInstallationA", "StorageTankA",
        # Rock / bedrock
        "RockyGroundA", "LavaA",
        # Ice / snow (permanent)
        "GlacierA", "SnowfieldA", "IceShelfA",
    ],
    SOURCE_GGDM: [
        # Water bodies  (GGDM 3.0)
        "WaterBodyA", "WatercourseA", "LakeA", "InlandWaterA",
        "CanalA", "SwampA",
        # Built-up / urban
        "BuiltUpAreaA", "FacilityA", "RunwayA", "AerodromeA",
        # Rock / bedrock
        "RockyGroundA", "LavaFlowA",
        # Ice / snow (permanent)
        "GlacierA", "SnowfieldA",
    ],
}


# =============================================================================
# STEP 1+2 — MILITARY TOPOGRAPHIC  (MGCP / TDS / GGDM)
# =============================================================================

def mgcp_ne_prepass(mgcp_gdb_or_folder, output_soil_fc,
                    non_soil_fcs=None, source_type=None, messages=None):
    """
    Pre-pass: stamp NE on soil polygons that spatially overlap confirmed
    non-traversable features (water, urban, rock, ice) from a military
    topographic database (MGCP, TDS, or GGDM).

    This runs as a parallel pass alongside — not instead of — the soil
    source classification.  It is data-driven: the source schema explicitly
    codes these features as non-traversable surface types.

    Parameters
    ----------
    mgcp_gdb_or_folder : str
        Path to the military topo File GDB or folder containing feature classes.
    output_soil_fc : str
        The already-created output soil FC to update in place.
    non_soil_fcs : list of str, optional
        Explicit list of feature class names to use as NE sources.
        If None, auto-discovers using patterns from _NE_PATTERNS[source_type].
    source_type : str, optional
        One of SOURCE_MGCP, SOURCE_TDS, SOURCE_GGDM.  Determines which
        pattern list is used when non_soil_fcs is None.  Defaults to MGCP.
    messages : arcpy messages object or None.

    Returns
    -------
    int  Number of polygons stamped NE.
    """
    src = source_type or SOURCE_MGCP
    label = f"[{src} NE pre-pass]"

    if not arcpy.Exists(output_soil_fc):
        _arcpy_msg(messages, f"{label}  Output FC not found — skipped.", "warning")
        return 0

    # ── Discover non-soil feature classes ────────────────────────────────────
    if non_soil_fcs is None:
        patterns = _NE_PATTERNS.get(src, _NE_PATTERNS[SOURCE_MGCP])
        discovered = []
        if arcpy.Exists(mgcp_gdb_or_folder):
            old_ws = arcpy.env.workspace
            arcpy.env.workspace = mgcp_gdb_or_folder
            all_fcs = arcpy.ListFeatureClasses() or []
            arcpy.env.workspace = old_ws
            fc_upper = {f.upper(): f for f in all_fcs}
            for pat in patterns:
                if pat.upper() in fc_upper:
                    full = os.path.join(mgcp_gdb_or_folder, fc_upper[pat.upper()])
                    discovered.append(full)
        non_soil_fcs = discovered

    if not non_soil_fcs:
        _arcpy_msg(messages,
                   f"{label}  No non-soil feature classes found — skipped.")
        return 0

    _arcpy_msg(messages,
               f"{label}  Using {len(non_soil_fcs)} non-soil FC(s).")

    scratch = arcpy.env.scratchGDB
    total_ne = 0

    for ne_fc in non_soil_fcs:
        if not arcpy.Exists(ne_fc):
            continue
        try:
            join_path = os.path.join(scratch, "ccm_miltopo_ne_join")
            if arcpy.Exists(join_path):
                arcpy.management.Delete(join_path)

            arcpy.analysis.SpatialJoin(
                output_soil_fc, ne_fc, join_path,
                join_operation = "JOIN_ONE_TO_ONE",
                join_type      = "KEEP_COMMON",
                match_option   = "INTERSECT",
            )

            # Collect OIDs of soil polygons that intersected a non-soil feature
            oid_fld = arcpy.Describe(output_soil_fc).OIDFieldName
            ne_oids = set()
            with arcpy.da.SearchCursor(join_path, [oid_fld]) as cur:
                for row in cur:
                    ne_oids.add(row[0])

            arcpy.management.Delete(join_path)

            if ne_oids:
                with arcpy.da.UpdateCursor(
                        output_soil_fc, [oid_fld, "soilType"]) as cur:
                    for row in cur:
                        if row[0] in ne_oids:
                            row[1] = "NE"
                            cur.updateRow(row)
                            total_ne += 1

                _arcpy_msg(messages,
                           f"  {os.path.basename(ne_fc)}: {len(ne_oids):,} "
                           f"polygons → 'NE'")
        except Exception as e:
            _arcpy_msg(messages,
                       f"  {os.path.basename(ne_fc)}: error — {e}", "warning")

    _arcpy_msg(messages,
               f"{label}  Complete — {total_ne:,} total polygons set to NE.")
    return total_ne


def _preprocess_facc_source(source_type, surface_fc, output_fc,
                             smc_field=None,
                             gdb_for_ne_prepass=None,
                             extent_fc=None, gap_fill_code="NE",
                             messages=None):
    """
    Shared processor for all FACC-based military topographic sources
    (MGCP, TDS, GGDM).  Called via thin public wrappers below.

    Workflow
    ────────
    1. Copy / clip the surface cover FC to output_fc.
    2. Auto-detect or accept the SMC field name.
    3. Map each SMC integer code → USCS via SMC_TO_USCS lookup table.
       Fallback: text label field → SMC_LABEL_TO_USCS → soil_name_to_uscs().
    4. Optional NE pre-pass from companion non-soil FCs in gdb_for_ne_prepass.
    5. Gap fill remaining NULLs.

    Parameters
    ----------
    source_type           : str   SOURCE_MGCP | SOURCE_TDS | SOURCE_GGDM
    surface_fc            : str   Surface Cover polygon FC (e.g. SU_SFC, SurfaceCoverA).
    output_fc             : str   Output FC path.
    smc_field             : str   SMC attribute field name.  None = auto-detect.
    gdb_for_ne_prepass    : str   Optional GDB path for NE pre-pass.
    extent_fc             : str   Optional clip extent.
    gap_fill_code         : str   Gap fill strategy.
    messages              : arcpy messages object or None.

    IMPORTANT — SMC value verification
    ────────────────────────────────────
    SMC enumeration values vary between MGCP / TDS / GGDM versions and
    national suppliers.  The SMC_TO_USCS table reflects FACC / MGCP v4.5
    standard values.  Always verify against your specific Product
    Specification.  Values not found in the table fall through to text-label
    matching and are logged as warnings.
    """
    result = PreprocessResult()
    result.source_type = source_type

    _arcpy_msg(messages, "=" * 60)
    _arcpy_msg(messages, f"[CCM Soil Preprocess]  Source: {source_type}")
    _arcpy_msg(messages, "=" * 60)

    if not arcpy.Exists(surface_fc):
        _arcpy_msg(messages, f"{source_type} surface FC not found: {surface_fc!r}", "error")
        return result

    # ── Copy / clip ───────────────────────────────────────────────────────────
    if extent_fc and arcpy.Exists(extent_fc):
        arcpy.analysis.Clip(surface_fc, extent_fc, output_fc)
    else:
        arcpy.management.CopyFeatures(surface_fc, output_fc)

    arcpy.management.AddField(output_fc, "soilType", "TEXT", field_length=10)
    result.total_features = int(arcpy.management.GetCount(output_fc)[0])
    result.output_fc      = output_fc

    # ── Auto-detect SMC field ─────────────────────────────────────────────────
    fld_map = {f.name.lower(): f.name for f in arcpy.ListFields(output_fc)}
    if smc_field and smc_field.lower() in fld_map:
        smc_fld = fld_map[smc_field.lower()]
    else:
        # Standard FACC SMC field names (shared across MGCP, TDS, GGDM)
        for cand in ("smc", "smcl", "surface_material_code", "surfmat",
                     "mat_code", "material"):
            if cand in fld_map:
                smc_fld = fld_map[cand]
                break
        else:
            smc_fld = None

    # Also look for a label/text companion field
    smc_label_fld = None
    for cand in ("smc_txt", "smc_label", "smc_name", "mat_desc",
                 "surface_material", "material_name"):
        if cand in fld_map:
            smc_label_fld = fld_map[cand]
            break

    if not smc_fld and not smc_label_fld:
        _arcpy_msg(messages,
                   "No SMC field found.  Expected 'SMC', 'SMCL', or similar.  "
                   "Use the 'SMC Field' parameter to specify the field name.",
                   "error")
        return result

    _arcpy_msg(messages,
               f"[Step 1 — Field Mapping]  SMC field: {smc_fld or '(none)'}  "
               f"Label field: {smc_label_fld or '(none)'}")

    # ── Step 2: Map SMC → USCS ────────────────────────────────────────────────
    _arcpy_msg(messages, "[Step 2 — Normalisation]  Mapping SMC codes → USCS...")

    read_fields = ["soilType"]
    if smc_fld:
        read_fields.insert(0, smc_fld)
    if smc_label_fld:
        read_fields.append(smc_label_fld)

    unknown_codes = set()
    written = 0

    with arcpy.da.UpdateCursor(output_fc, read_fields) as cur:
        for row in cur:
            idx = 0
            smc_val   = row[idx] if smc_fld else None
            idx += 1 if smc_fld else 0
            soil_idx  = idx
            idx += 1
            label_val = row[idx] if smc_label_fld else None

            uscs = None

            # Path 1: integer SMC code lookup
            if smc_val is not None:
                try:
                    uscs = SMC_TO_USCS.get(int(smc_val))
                except (ValueError, TypeError):
                    pass
                if uscs is None and smc_val is not None:
                    try:
                        unknown_codes.add(int(smc_val))
                    except (ValueError, TypeError):
                        pass

            # Path 2: label / text field fallback
            if not uscs and label_val:
                label_key = str(label_val).strip().lower()
                uscs = SMC_LABEL_TO_USCS.get(label_key)
                if not uscs:
                    # Try substring matching via SOIL_NAME_FRAGMENTS
                    uscs = soil_name_to_uscs(label_key)

            if uscs:
                row[soil_idx] = uscs
                cur.updateRow(row)
                written += 1

    result.mapped_count = written

    if unknown_codes:
        _arcpy_msg(messages,
                   f"  WARNING: {len(unknown_codes)} unrecognised SMC code(s) — "
                   f"not in SMC_TO_USCS table: {sorted(unknown_codes)}\n"
                   f"  Verify against your {source_type} Product Specification and update "
                   f"SMC_TO_USCS in ccm_soil_preprocess.py if needed.",
                   "warning")

    _arcpy_msg(messages, f"  Mapped {written:,} of {result.total_features:,} polygons.")

    # ── Optional NE pre-pass from companion non-soil feature classes ──────────
    if gdb_for_ne_prepass:
        result.gap_filled_count += mgcp_ne_prepass(
            gdb_for_ne_prepass, output_fc,
            source_type=source_type, messages=messages)

    # ── Gap fill ──────────────────────────────────────────────────────────────
    result.gap_filled_count += _dispatch_gap_fill(
        output_fc, gap_fill_code, messages=messages)

    # ── Distribution summary ──────────────────────────────────────────────────
    dist = {}
    null_ct = 0
    with arcpy.da.SearchCursor(output_fc, ["soilType"]) as cur:
        for row in cur:
            v = row[0]
            if v is None or str(v).strip() == "":
                null_ct += 1
            else:
                dist[str(v).strip()] = dist.get(str(v).strip(), 0) + 1
    result.null_count        = null_ct
    result.uscs_distribution = dist

    _arcpy_msg(messages, "\n" + result.summary())
    return result


# ── Public thin wrappers ──────────────────────────────────────────────────────

def preprocess_mgcp(mgcp_surface_fc, output_fc,
                    smc_field=None, mgcp_gdb_for_ne_prepass=None,
                    extent_fc=None, gap_fill_code="NE", messages=None):
    """Process an MGCP Surface Cover FC (e.g. SU_SFC).  See _preprocess_facc_source()."""
    return _preprocess_facc_source(
        SOURCE_MGCP, mgcp_surface_fc, output_fc,
        smc_field=smc_field, gdb_for_ne_prepass=mgcp_gdb_for_ne_prepass,
        extent_fc=extent_fc, gap_fill_code=gap_fill_code, messages=messages,
    )


def preprocess_tds(tds_surface_fc, output_fc,
                   smc_field=None, tds_gdb_for_ne_prepass=None,
                   extent_fc=None, gap_fill_code="NE", messages=None):
    """
    Process a TDS (Topographic Data Store) Surface Cover FC.

    Common TDS 6.0 / 7.0 surface cover FC names: SurfaceCoverA
    Common SMC field name: SMC (same as MGCP / FACC standard)
    """
    return _preprocess_facc_source(
        SOURCE_TDS, tds_surface_fc, output_fc,
        smc_field=smc_field, gdb_for_ne_prepass=tds_gdb_for_ne_prepass,
        extent_fc=extent_fc, gap_fill_code=gap_fill_code, messages=messages,
    )


def preprocess_ggdm(ggdm_surface_fc, output_fc,
                    smc_field=None, ggdm_gdb_for_ne_prepass=None,
                    extent_fc=None, gap_fill_code="NE", messages=None):
    """
    Process a GGDM (Geospatial-Intelligence Geospatial Data Model) surface FC.

    Common GGDM 3.0 surface cover FC names: SurfaceMaterialA
    Common SMC field names: SMC, material_code
    """
    return _preprocess_facc_source(
        SOURCE_GGDM, ggdm_surface_fc, output_fc,
        smc_field=smc_field, gdb_for_ne_prepass=ggdm_gdb_for_ne_prepass,
        extent_fc=extent_fc, gap_fill_code=gap_fill_code, messages=messages,
    )


# =============================================================================
# STEP 1+2 — GENERIC FC  (any polygon FC with direct texture / class fields)
# =============================================================================

def preprocess_generic(fc_path, output_fc,
                       sand_field=None, silt_field=None, clay_field=None,
                       texcl_field=None, soil_name_field=None,
                       wrb_field=None,
                       extent_fc=None, gap_fill_code="NE",
                       messages=None):
    """
    Process any polygon FC that contains one or more of:
      • Sand / silt / clay % fields
      • A USDA texture class text field (texcl)
      • A soil name / description text field
      • A WRB / FAO-90 soil unit code field

    The tool auto-discovers suitable fields when not explicitly specified.

    Parameters
    ----------
    fc_path       : str  Input polygon FC.
    output_fc     : str  Output FC path.
    sand_field,
    silt_field,
    clay_field    : str  Explicit field names (or None = auto-discover).
    texcl_field   : str  USDA texture class field (e.g. 'texcl', 'TEXTURE').
    soil_name_field: str  Free-text soil name field.
    wrb_field     : str  WRB / FAO-90 code field (e.g. 'WRB2006').
    extent_fc     : str  Optional clipping extent.
    gap_fill_code : str  USCS code for gap fill.
    messages      : arcpy messages object or None.
    """
    result = PreprocessResult()
    result.source_type = SOURCE_GENERIC

    _arcpy_msg(messages, "=" * 60)
    _arcpy_msg(messages, "[CCM Soil Preprocess]  Source: Generic FC")
    _arcpy_msg(messages, "=" * 60)

    if not arcpy.Exists(fc_path):
        _arcpy_msg(messages, f"Input FC not found: {fc_path!r}", "error")
        return result

    # ── Auto-discover fields ──────────────────────────────────────────────────
    field_map = {f.name.lower(): f.name for f in arcpy.ListFields(fc_path)}

    def _find(*candidates):
        for c in candidates:
            if c.lower() in field_map:
                return field_map[c.lower()]
        return None

    s_fld   = sand_field      or _find("tsand", "sand", "sandtotal_r", "sand_pct", "pct_sand", "s_pct")
    si_fld  = silt_field      or _find("tsilt", "silt", "silttotal_r", "silt_pct", "pct_silt", "si_pct")
    cl_fld  = clay_field      or _find("tclay", "clay", "claytotal_r", "clay_pct", "pct_clay", "c_pct")
    tx_fld  = texcl_field     or _find("texcl", "texture_class", "tex_class", "texture", "tex")
    nm_fld  = soil_name_field or _find("soilname", "soil_name", "compname", "name",
                                        "taxclname", "mapunit_name", "musym")
    wb_fld  = wrb_field       or _find("wrb2006", "wrb", "fao90", "fao_90",
                                        "soil_unit", "soil_code", "wu_sym")

    _arcpy_msg(messages, "  Auto-discovered fields:")
    _arcpy_msg(messages, f"    Sand      : {s_fld or '(none)'}")
    _arcpy_msg(messages, f"    Silt      : {si_fld or '(none)'}")
    _arcpy_msg(messages, f"    Clay      : {cl_fld or '(none)'}")
    _arcpy_msg(messages, f"    Texcl     : {tx_fld or '(none)'}")
    _arcpy_msg(messages, f"    Soil name : {nm_fld or '(none)'}")
    _arcpy_msg(messages, f"    WRB code  : {wb_fld or '(none)'}")

    read_fields = ["OID@"] + [f for f in [s_fld, si_fld, cl_fld, tx_fld, nm_fld, wb_fld]
                              if f is not None]

    # ── Copy geometry ─────────────────────────────────────────────────────────
    if extent_fc and arcpy.Exists(extent_fc):
        arcpy.analysis.Clip(fc_path, extent_fc, output_fc)
    else:
        arcpy.management.CopyFeatures(fc_path, output_fc)

    arcpy.management.AddField(output_fc, "soilType", "TEXT", field_length=10)
    result.total_features = int(arcpy.management.GetCount(output_fc)[0])
    result.output_fc      = output_fc

    # ── Step 2: Derive USCS for each feature ──────────────────────────────────
    _arcpy_msg(messages, "[Step 2 — Normalisation]  Deriving USCS codes...")
    update_fields = read_fields + ["soilType"]
    written = 0

    with arcpy.da.UpdateCursor(output_fc, update_fields) as cur:
        fld_idx = {name: i for i, name in enumerate(update_fields)}
        for row in cur:
            uscs = None

            # 2a — Texture %
            if s_fld and si_fld and cl_fld:
                try:
                    sv  = row[fld_idx[s_fld]]
                    siv = row[fld_idx[si_fld]]
                    clv = row[fld_idx[cl_fld]]
                    uscs = texture_pct_to_uscs(sv, siv, clv)
                except Exception:
                    pass

            # 2b — USDA texture class
            if not uscs and tx_fld:
                uscs = usda_texcl_to_uscs(row[fld_idx[tx_fld]])

            # 2c — WRB / FAO code
            if not uscs and wb_fld:
                uscs = wrb_to_uscs(row[fld_idx[wb_fld]])

            # 2d — Soil name
            if not uscs and nm_fld:
                uscs = soil_name_to_uscs(row[fld_idx[nm_fld]])

            if uscs:
                row[fld_idx["soilType"]] = uscs
                cur.updateRow(row)
                written += 1

    result.mapped_count     = written
    result.gap_filled_count = _dispatch_gap_fill(output_fc, gap_fill_code, messages=messages)

    dist = {}
    null_ct = 0
    with arcpy.da.SearchCursor(output_fc, ["soilType"]) as cur:
        for row in cur:
            v = row[0]
            if v is None or str(v).strip() == "":
                null_ct += 1
            else:
                dist[str(v).strip()] = dist.get(str(v).strip(), 0) + 1
    result.null_count        = null_ct
    result.uscs_distribution = dist

    _arcpy_msg(messages, "\n" + result.summary())
    return result


# =============================================================================
# MAIN ENTRY POINT  (auto-detects source and dispatches)
# =============================================================================

def preprocess_soil_data(source_type, soil_fc, output_fc,
                         # DSS / SLC
                         cmp_table=None, layer_table=None, name_table=None,
                         slc_gdb=None,
                         # SSURGO
                         tabular_folder=None,
                         # HWSD
                         hwsd_raster=None, hwsd_mdb=None,
                         # SoilGrids 2.0
                         soilgrids_folder=None, soilgrids_depth="0-5cm",
                         soilgrids_sand=None, soilgrids_silt=None, soilgrids_clay=None,
                         # Military topographic  (MGCP / TDS / GGDM — shared params)
                         mgcp_smc_field=None, mgcp_gdb=None,
                         # Generic
                         sand_field=None, silt_field=None, clay_field=None,
                         texcl_field=None, soil_name_field=None, wrb_field=None,
                         # Shared
                         extent_fc=None, gap_fill_code="NE",
                         messages=None):
    """
    Unified entry point.  Dispatches to the appropriate source handler
    based on source_type.

    Returns a PreprocessResult object.
    """
    if source_type == SOURCE_AUTO:
        aux = os.path.dirname(soil_fc) if soil_fc else None
        source_type = detect_source_type(soil_fc, aux_folder=aux)
        _arcpy_msg(messages, f"[Auto-Detect]  Identified source as: {source_type}")

    if source_type == SOURCE_DSS:
        result = preprocess_dss(
            soil_fc, output_fc,
            cmp_table=cmp_table, layer_table=layer_table, name_table=name_table,
            extent_fc=extent_fc, gap_fill_code=gap_fill_code, messages=messages,
        )
    elif source_type == SOURCE_SLC:
        gdb = slc_gdb or (os.path.dirname(soil_fc)
                          if soil_fc and soil_fc.lower().endswith(".gdb") else soil_fc)
        result = preprocess_slc(
            gdb, output_fc,
            extent_fc=extent_fc, gap_fill_code=gap_fill_code, messages=messages,
        )
    elif source_type == SOURCE_SSURGO:
        result = preprocess_ssurgo(
            soil_fc, tabular_folder or os.path.dirname(soil_fc), output_fc,
            extent_fc=extent_fc, gap_fill_code=gap_fill_code, messages=messages,
        )
    elif source_type == SOURCE_HWSD:
        result = preprocess_hwsd(
            hwsd_raster or soil_fc, hwsd_mdb or os.path.join(os.path.dirname(soil_fc), "HWSD2.mdb"),
            output_fc,
            extent_fc=extent_fc, gap_fill_code=gap_fill_code, messages=messages,
        )
    elif source_type == SOURCE_SOILGRIDS:
        folder = soilgrids_folder or (soil_fc if os.path.isdir(str(soil_fc or "")) else None)
        result = preprocess_soilgrids(
            folder, output_fc,
            sand_raster=soilgrids_sand,
            silt_raster=soilgrids_silt,
            clay_raster=soilgrids_clay,
            depth_mode=soilgrids_depth or "0-5cm",
            extent_fc=extent_fc, gap_fill_code=gap_fill_code, messages=messages,
        )
    elif source_type == SOURCE_MGCP:
        result = preprocess_mgcp(
            soil_fc, output_fc,
            smc_field=mgcp_smc_field,
            mgcp_gdb_for_ne_prepass=mgcp_gdb,
            extent_fc=extent_fc, gap_fill_code=gap_fill_code, messages=messages,
        )
    elif source_type == SOURCE_TDS:
        result = preprocess_tds(
            soil_fc, output_fc,
            smc_field=mgcp_smc_field,
            tds_gdb_for_ne_prepass=mgcp_gdb,
            extent_fc=extent_fc, gap_fill_code=gap_fill_code, messages=messages,
        )
    elif source_type == SOURCE_GGDM:
        result = preprocess_ggdm(
            soil_fc, output_fc,
            smc_field=mgcp_smc_field,
            ggdm_gdb_for_ne_prepass=mgcp_gdb,
            extent_fc=extent_fc, gap_fill_code=gap_fill_code, messages=messages,
        )
    else:
        result = preprocess_generic(
            soil_fc, output_fc,
            sand_field=sand_field, silt_field=silt_field, clay_field=clay_field,
            texcl_field=texcl_field, soil_name_field=soil_name_field, wrb_field=wrb_field,
            extent_fc=extent_fc, gap_fill_code=gap_fill_code, messages=messages,
        )

    # ── CRS guard: auto-reproject if output is in a Geographic CRS ───────────
    # Runs for EVERY source.  Sources whose rasters are natively in WGS 1984
    # (HWSD, SoilGrids) will trigger this; vector sources usually won't.
    # Uses the extent_fc CRS as the reprojection target when available.
    if result.output_fc and arcpy.Exists(str(result.output_fc)):
        _ensure_projected_crs(result.output_fc, extent_fc, messages)

    return result


# =============================================================================
# ARCGIS TOOL CLASS
# =============================================================================

class CCMSoilPreprocessTool:
    """
    ArcGIS Pro Tool: Pre-process Soil Data for CCM Analysis

    Appears in the MCE CCM Toolbox V2 as tool #8.
    Takes raw soil data from any supported source (DSS, SLC, SSURGO, HWSD, or
    a generic FC) and produces a clean feature class with a 'soilType' field
    containing USCS codes, ready for direct use by the CCM Mobility Map tool.
    """

    def __init__(self):
        self.label              = "0.  Pre-process Soil Data  (Step 1–3)"
        self.description        = (
            "Prepares raw soil data for CCM analysis in three steps:\n"
            "  1. Field Mapping  — joins companion tables (CMP, Layer, Name) so "
            "texture data reaches the polygon geometry.\n"
            "  2. Normalisation  — converts raw values (%, texture codes, names) "
            "into standard USCS two-letter codes.\n"
            "  3. Gap Filling    — replaces remaining NULL soilType polygons with "
            "a configurable default USCS code.\n\n"
            "Supported sources: DSS Canada, SLC Canada, SSURGO/STATSGO2 (US), "
            "HWSD v2 (Global), Generic polygon FC."
        )
        self.canRunInBackground = False

    # =========================================================================
    def getParameterInfo(self):

        # ── p0: Source type ────────────────────────────────────────────────────
        p_source = arcpy.Parameter(
            displayName   = "Soil Data Source",
            name          = "source_type",
            datatype      = "GPString",
            parameterType = "Required",
            direction     = "Input",
        )
        p_source.filter.type = "ValueList"
        p_source.filter.list = ALL_SOURCES
        p_source.value       = SOURCE_AUTO

        # ── p1: Main soil FC ──────────────────────────────────────────────────
        p_soil = arcpy.Parameter(
            displayName   = "Soil Polygon Feature Class  (or HWSD raster)",
            name          = "soil_fc",
            datatype      = ["DEFeatureClass", "DERasterDataset"],
            parameterType = "Required",
            direction     = "Input",
        )

        # ── p2: CMP table (DSS/SLC) ──────────────────────────────────────────
        p_cmp = arcpy.Parameter(
            displayName   = "Component Table (.dbf)  [DSS/SLC]",
            name          = "cmp_table",
            datatype      = "DEFile",
            parameterType = "Optional",
            direction     = "Input",
            category      = "DSS / SLC Canada",
        )

        # ── p3: Layer table (DSS/SLC) ────────────────────────────────────────
        p_layer = arcpy.Parameter(
            displayName   = "Soil Layer Table (.dbf)  [DSS/SLC]",
            name          = "layer_table",
            datatype      = "DEFile",
            parameterType = "Optional",
            direction     = "Input",
            category      = "DSS / SLC Canada",
        )

        # ── p4: Name table (DSS/SLC) ─────────────────────────────────────────
        p_name = arcpy.Parameter(
            displayName   = "Soil Name Table (.dbf)  [DSS/SLC — used for PMTEX fallback]",
            name          = "name_table",
            datatype      = "DEFile",
            parameterType = "Optional",
            direction     = "Input",
            category      = "DSS / SLC Canada",
        )

        # ── p5: SLC GDB ──────────────────────────────────────────────────────
        p_slc_gdb = arcpy.Parameter(
            displayName   = "SLC File Geodatabase (.gdb)  [SLC only — contains all tables]",
            name          = "slc_gdb",
            datatype      = "DEWorkspace",
            parameterType = "Optional",
            direction     = "Input",
            category      = "DSS / SLC Canada",
        )

        # ── p6: SSURGO tabular folder / gDB ──────────────────────────────────
        p_ssurgo = arcpy.Parameter(
            displayName   = "SSURGO Tabular Folder or gSSURGO .gdb  [SSURGO only]",
            name          = "ssurgo_tabular",
            datatype      = ["DEFolder", "DEWorkspace"],
            parameterType = "Optional",
            direction     = "Input",
            category      = "SSURGO / STATSGO2 (US)",
        )

        # ── p7: HWSD database ─────────────────────────────────────────────────
        p_hwsd_mdb = arcpy.Parameter(
            displayName   = "HWSD2.mdb Access Database  [HWSD only]",
            name          = "hwsd_mdb",
            datatype      = "DEFile",
            parameterType = "Optional",
            direction     = "Input",
            category      = "HWSD v2 (Global)",
        )

        # ── p8: SoilGrids — folder ────────────────────────────────────────────
        p_sg_folder = arcpy.Parameter(
            displayName   = "SoilGrids 2.0 Raster Folder  [SoilGrids only]",
            name          = "soilgrids_folder",
            datatype      = "DEFolder",
            parameterType = "Optional",
            direction     = "Input",
            category      = "SoilGrids 2.0 (Global)",
        )

        # ── p9: SoilGrids — depth mode ───────────────────────────────────────
        p_sg_depth = arcpy.Parameter(
            displayName   = "Depth Layer  [SoilGrids only]",
            name          = "soilgrids_depth",
            datatype      = "GPString",
            parameterType = "Optional",
            direction     = "Input",
            category      = "SoilGrids 2.0 (Global)",
        )
        p_sg_depth.filter.type = "ValueList"
        p_sg_depth.filter.list = [
            "0-5cm",
            "5-15cm",
            "15-30cm",
            "30-60cm",
            "60-100cm",
            "Weighted 0-30cm",
        ]
        p_sg_depth.value = "0-5cm"

        # ── p10: Military Topo — SMC field name  (shared: MGCP / TDS / GGDM) ─
        p_mgcp_smc = arcpy.Parameter(
            displayName   = "SMC Field Name  [MGCP / TDS / GGDM]",
            name          = "mgcp_smc_field",
            datatype      = "GPString",
            parameterType = "Optional",
            direction     = "Input",
            category      = "Military Topographic  (MGCP / TDS / GGDM)",
        )
        p_mgcp_smc.value = "SMC"

        # ── p11: Military Topo — GDB for NE pre-pass  (shared: MGCP / TDS / GGDM)
        p_mgcp_gdb = arcpy.Parameter(
            displayName   = (
                "Military Topo GDB  "
                "(NE pre-pass — water / urban / rock / ice → NE)  [MGCP / TDS / GGDM]"
            ),
            name          = "mgcp_gdb",
            datatype      = "DEWorkspace",
            parameterType = "Optional",
            direction     = "Input",
            category      = "Military Topographic  (MGCP / TDS / GGDM)",
        )

        # ── p12: Generic — sand field ─────────────────────────────────────────
        p_sand = arcpy.Parameter(
            displayName   = "Sand % Field  [Generic]",
            name          = "sand_field",
            datatype      = "Field",
            parameterType = "Optional",
            direction     = "Input",
            category      = "Generic FC Options",
        )
        p_sand.parameterDependencies = ["soil_fc"]

        # ── p13: Generic — silt field ────────────────────────────────────────
        p_silt = arcpy.Parameter(
            displayName   = "Silt % Field  [Generic]",
            name          = "silt_field",
            datatype      = "Field",
            parameterType = "Optional",
            direction     = "Input",
            category      = "Generic FC Options",
        )
        p_silt.parameterDependencies = ["soil_fc"]

        # ── p14: Generic — clay field ────────────────────────────────────────
        p_clay = arcpy.Parameter(
            displayName   = "Clay % Field  [Generic]",
            name          = "clay_field",
            datatype      = "Field",
            parameterType = "Optional",
            direction     = "Input",
            category      = "Generic FC Options",
        )
        p_clay.parameterDependencies = ["soil_fc"]

        # ── p15: Generic — texture class field ──────────────────────────────
        p_texcl = arcpy.Parameter(
            displayName   = "Texture Class Field (USDA)  [Generic]",
            name          = "texcl_field",
            datatype      = "Field",
            parameterType = "Optional",
            direction     = "Input",
            category      = "Generic FC Options",
        )
        p_texcl.parameterDependencies = ["soil_fc"]

        # ── p16: Generic — soil name field ──────────────────────────────────
        p_soilname = arcpy.Parameter(
            displayName   = "Soil Name / Description Field  [Generic]",
            name          = "soil_name_field",
            datatype      = "Field",
            parameterType = "Optional",
            direction     = "Input",
            category      = "Generic FC Options",
        )
        p_soilname.parameterDependencies = ["soil_fc"]

        # ── p17: Generic — WRB / FAO code field ─────────────────────────────
        p_wrb = arcpy.Parameter(
            displayName   = "WRB / FAO-90 Code Field  [Generic / HWSD]",
            name          = "wrb_field",
            datatype      = "Field",
            parameterType = "Optional",
            direction     = "Input",
            category      = "Generic FC Options",
        )
        p_wrb.parameterDependencies = ["soil_fc"]

        # ── p18: Analysis extent ─────────────────────────────────────────────
        p_extent = arcpy.Parameter(
            displayName   = "Analysis Extent  (optional — clips output to study area)",
            name          = "extent_fc",
            datatype      = "DEFeatureClass",
            parameterType = "Optional",
            direction     = "Input",
        )

        # ── p19: Gap-fill code ───────────────────────────────────────────────
        p_gapfill = arcpy.Parameter(
            displayName   = (
                "Gap-fill Strategy  (Step 3)  —  how to handle polygons with no soil data\n"
                "  Smart (auto) : NE — data-driven only.  Known non-soil features (absent\n"
                "                 from source CMP table) get NE.  All remaining unknowns\n"
                "                 also get NE.  No inference from neighbours.  [recommended]\n"
                "  NE           : Assign NE to every NULL polygon (same result, explicit)\n"
                "  SP / SM / ML / CL / CH / Pt : Force a single fixed USCS code on all NULLs"
            ),
            name          = "gap_fill_code",
            datatype      = "GPString",
            parameterType = "Required",
            direction     = "Input",
        )
        p_gapfill.filter.type = "ValueList"
        p_gapfill.filter.list = [
            GAP_FILL_SMART,  # Data-driven NE assignment — no inference from neighbours
            "NE",            # Not Evaluated (honest unknown)
            "SP",            # Poorly-graded sand
            "SM",            # Silty sand
            "ML",            # Silt / sandy silt
            "CL",            # Clay loam
            "CH",            # Heavy clay
            "Pt",            # Peat / organic
        ]
        p_gapfill.value = GAP_FILL_SMART

        # ── p20: Output FC ───────────────────────────────────────────────────
        p_output = arcpy.Parameter(
            displayName   = "Output Feature Class  (CCM-ready soil layer)",
            name          = "output_fc",
            datatype      = "DEFeatureClass",
            parameterType = "Required",
            direction     = "Output",
        )

        return [
            p_source,    # 0
            p_soil,      # 1
            p_cmp,       # 2
            p_layer,     # 3
            p_name,      # 4
            p_slc_gdb,   # 5
            p_ssurgo,    # 6
            p_hwsd_mdb,  # 7
            p_sg_folder, # 8  ← SoilGrids folder
            p_sg_depth,  # 9  ← SoilGrids depth
            p_mgcp_smc,  # 10
            p_mgcp_gdb,  # 11
            p_sand,      # 12
            p_silt,      # 13
            p_clay,      # 14
            p_texcl,     # 15
            p_soilname,  # 16
            p_wrb,       # 17
            p_extent,    # 18
            p_gapfill,   # 19
            p_output,    # 20
        ]

    def isLicensed(self):
        return True

    # =========================================================================
    def updateParameters(self, parameters):
        p_source    = parameters[0]
        p_soil      = parameters[1]
        p_cmp       = parameters[2]
        p_layer     = parameters[3]
        p_name      = parameters[4]
        p_slc       = parameters[5]
        p_ssurgo    = parameters[6]
        p_hwsd      = parameters[7]
        p_sg_folder = parameters[8]
        p_sg_depth  = parameters[9]
        p_mgcp_smc  = parameters[10]
        p_mgcp_gdb  = parameters[11]

        src = p_source.valueAsText or SOURCE_AUTO

        # Auto-detect when soil FC / folder is set and source is still Auto
        if p_soil.altered and p_soil.value and src == SOURCE_AUTO:
            detected = detect_source_type(p_soil.valueAsText)
            if detected != SOURCE_GENERIC:
                p_source.value = detected

        # Enable/disable categories based on source
        is_dss        = src in (SOURCE_DSS, SOURCE_SLC, SOURCE_AUTO)
        is_ssurgo     = src == SOURCE_SSURGO
        is_hwsd       = src == SOURCE_HWSD
        is_soilgrids  = src == SOURCE_SOILGRIDS
        is_mil_topo   = src in (SOURCE_MGCP, SOURCE_TDS, SOURCE_GGDM)

        p_cmp.enabled       = is_dss
        p_layer.enabled     = is_dss
        p_name.enabled      = is_dss
        p_slc.enabled       = src in (SOURCE_SLC, SOURCE_AUTO)
        p_ssurgo.enabled    = is_ssurgo
        p_hwsd.enabled      = is_hwsd
        p_sg_folder.enabled = is_soilgrids
        p_sg_depth.enabled  = is_soilgrids
        p_mgcp_smc.enabled  = is_mil_topo
        p_mgcp_gdb.enabled  = is_mil_topo

        # Auto-populate DSS companion table paths from soil FC folder
        if p_soil.altered and p_soil.value and src in (SOURCE_DSS, SOURCE_AUTO):
            folder = os.path.dirname(p_soil.valueAsText)
            tables = _find_dss_tables(folder)
            if tables.get("cmp") and not p_cmp.value:
                p_cmp.value = tables["cmp"]
            if tables.get("layer") and not p_layer.value:
                p_layer.value = tables["layer"]
            if tables.get("name") and not p_name.value:
                p_name.value = tables["name"]

        # Auto-populate SoilGrids folder when user points at a raster file
        if p_soil.altered and p_soil.value and is_soilgrids:
            path_str = p_soil.valueAsText
            if os.path.isfile(path_str) and not p_sg_folder.value:
                p_sg_folder.value = os.path.dirname(path_str)

    # =========================================================================
    def updateMessages(self, parameters):
        p_source    = parameters[0]
        p_soil      = parameters[1]
        p_cmp       = parameters[2]
        p_sg_folder = parameters[8]
        p_output    = parameters[20]

        src = p_source.valueAsText or SOURCE_AUTO

        # Warn if DSS/SLC source is selected but CMP table is missing
        if src in (SOURCE_DSS, SOURCE_SLC) and not p_cmp.value:
            p_cmp.setWarningMessage(
                "Component table is required for DSS/SLC sources.  "
                "Without it, SOIL_ID cannot be resolved from POLY_ID and "
                "no texture data can be derived."
            )

        # Warn if HWSD selected but ACE driver is not installed
        if src == SOURCE_HWSD:
            ace_ok, ace_msg = _ace_driver_available()
            if not ace_ok:
                parameters[7].setErrorMessage(
                    "Required driver not installed.\n\n"
                    + ace_msg
                )

        # Warn if HWSD selected but soil input looks like a vector FC
        if src == SOURCE_HWSD and p_soil.value:
            ext = os.path.splitext(str(p_soil.valueAsText))[-1].lower()
            if ext in (".shp", ".gdb"):
                p_soil.setWarningMessage(
                    "HWSD source selected but input appears to be a vector FC.  "
                    "HWSD expects a raster (.bil or .tif).  "
                    "Switch source to 'Generic' if your FC already has MU_GLOBAL values."
                )

        # Warn if SoilGrids selected but no folder or raster provided
        # (higher priority — checked first so it is not overwritten)
        if src == SOURCE_SOILGRIDS and not p_sg_folder.value and not p_soil.value:
            p_sg_folder.setWarningMessage(
                "SoilGrids source requires either a raster folder in 'SoilGrids Raster Folder' "
                "or a specific GeoTIFF in 'Soil Polygon Feature Class'.  "
                "Folder should contain files named: sand_0-5cm_mean.tif, silt_0-5cm_mean.tif, "
                "clay_0-5cm_mean.tif  (and other depths as needed)."
            )
        elif src == SOURCE_SOILGRIDS and not parameters[18].value:
            # Only show the performance warning when the folder IS set (no-folder
            # warning takes priority above and would otherwise be overwritten here)
            p_sg_folder.setWarningMessage(
                "No Analysis Extent set.  SoilGrids rasters are global (250 m resolution) — "
                "processing without a clipping extent may be very slow and memory-intensive.  "
                "It is strongly recommended to set an Analysis Extent polygon."
            )

        # Check output doesn't already exist
        if p_output.value and arcpy.Exists(p_output.valueAsText):
            p_output.setWarningMessage(
                "Output FC already exists and will be overwritten."
            )

    # =========================================================================
    def execute(self, parameters, messages):
        src           = parameters[0].valueAsText
        soil_fc       = parameters[1].valueAsText
        cmp_table     = parameters[2].valueAsText
        layer_table   = parameters[3].valueAsText
        name_table    = parameters[4].valueAsText
        slc_gdb       = parameters[5].valueAsText
        ssurgo_tab    = parameters[6].valueAsText
        hwsd_mdb      = parameters[7].valueAsText
        sg_folder     = parameters[8].valueAsText
        sg_depth      = parameters[9].valueAsText
        mgcp_smc_fld  = parameters[10].valueAsText
        mgcp_gdb      = parameters[11].valueAsText
        sand_field    = parameters[12].valueAsText
        silt_field    = parameters[13].valueAsText
        clay_field    = parameters[14].valueAsText
        texcl_field   = parameters[15].valueAsText
        soilname_fld  = parameters[16].valueAsText
        wrb_field     = parameters[17].valueAsText
        extent_fc     = parameters[18].valueAsText
        gap_fill_code = parameters[19].valueAsText
        output_fc     = parameters[20].valueAsText

        # Delete existing output so CopyFeatures doesn't conflict
        if arcpy.Exists(output_fc):
            arcpy.management.Delete(output_fc)

        result = preprocess_soil_data(
            source_type       = src,
            soil_fc           = soil_fc,
            output_fc         = output_fc,
            cmp_table         = cmp_table,
            layer_table       = layer_table,
            name_table        = name_table,
            slc_gdb           = slc_gdb,
            tabular_folder    = ssurgo_tab,
            hwsd_mdb          = hwsd_mdb,
            soilgrids_folder  = sg_folder,
            soilgrids_depth   = sg_depth or "0-5cm",
            mgcp_smc_field    = mgcp_smc_fld,
            mgcp_gdb          = mgcp_gdb,
            sand_field        = sand_field,
            silt_field        = silt_field,
            clay_field        = clay_field,
            texcl_field       = texcl_field,
            soil_name_field   = soilname_fld,
            wrb_field         = wrb_field,
            extent_fc         = extent_fc,
            gap_fill_code     = gap_fill_code,
            messages          = messages,
        )

        if result.success:
            arcpy.AddMessage(f"\n[CCM Soil Preprocess]  Done.  "
                             f"Output: {result.output_fc}")
            arcpy.AddMessage("  This FC can now be used directly as the "
                             "'Soil Data' input in the CCM Mobility Map tool.")
        else:
            arcpy.AddError("[CCM Soil Preprocess]  Processing failed — "
                           "check messages above for details.")

        return result.output_fc
