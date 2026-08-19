# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
ccm_mgcp_catalog.py  —  MGCP / FACC feature-code catalog
=========================================================
Pure-Python (no arcpy) dictionary that maps MGCP feature-class names
(FACC/DIGEST 5-character codes such as ``AP030``, ``BH140``, ``DA010``)
to a human-readable name, a display theme, and a CCM role.

Purpose
-------
MGCP deliveries arrive as dozens of feature classes with opaque code
names.  This module answers, deterministically:

  * "What is AP030?"            -> Road (Transportation)
  * "Which FC is the soil data?"-> DA010 (Ground Surface Element, SMC field)
  * "Which FCs feed CCM?"       -> everything whose ccm_role is not None

Used by:
  * ccm_step0_mgcp.py  — labelled pick-list, theme filter, theme group
                         layers, mgcp_manifest.json
  * ccm_step1_setup.py — manifest-driven auto-fill of soil / hydro /
                         contour inputs

New in v0.50.0.
"""

import os
import re

VERSION = "0.58.2"  # v0.58.2 -- bumped by bump_version.py from v0.57. Review this line's comment.

# ── Themes ─────────────────────────────────────────────────────────────────────
THEME_TRANSPORT   = "Transportation"
THEME_HYDRO       = "Hydrography"
THEME_ELEVATION   = "Elevation"
THEME_SOIL        = "Soil"
THEME_PHYSIO      = "Physiography"
THEME_VEG         = "Vegetation"
THEME_CULTURE     = "Culture"
THEME_BOUNDARY    = "Boundary"
THEME_AERO        = "Aeronautical"
THEME_MILITARY    = "Military"
THEME_OTHER       = "Other"

ALL_THEMES = [
    THEME_SOIL, THEME_VEG, THEME_HYDRO, THEME_TRANSPORT, THEME_ELEVATION,
    THEME_PHYSIO, THEME_CULTURE, THEME_BOUNDARY, THEME_AERO,
    THEME_MILITARY, THEME_OTHER,
]

# Themes that feed the CCM mobility model (Step 1/2 inputs + obstacles)
CCM_RELEVANT_THEMES = [
    THEME_SOIL, THEME_VEG, THEME_HYDRO, THEME_TRANSPORT,
    THEME_ELEVATION, THEME_PHYSIO,
]

# ── CCM roles ──────────────────────────────────────────────────────────────────
ROLE_SOIL     = "soil"       # soil source (SMC attribute)
ROLE_HYDRO    = "hydro"      # water body -> hydro_fcs (F_hydro NO-GO)
ROLE_VEG      = "veg"        # vegetation cover -> veg factors F2/F3
ROLE_CONTOURS = "contours"   # elevation contours -> slope fallback
ROLE_OBSTACLE = "obstacle"   # linear/area movement obstacle
ROLE_ROAD     = "road"       # road network (on-road speed / egress)

# ── Catalog ────────────────────────────────────────────────────────────────────
# code : (human-readable name, theme, ccm_role or None)
# Codes follow FACC / MGCP TRD naming.  Both AL013 and AL015 are listed
# because Building changed codes between TRD versions.
MGCP_CATALOG = {
    # ── Culture / industry (A*) ───────────────────────────────────────────────
    "AA010": ("Extraction Mine",              THEME_CULTURE,   ROLE_OBSTACLE),
    "AA012": ("Quarry",                       THEME_CULTURE,   ROLE_OBSTACLE),
    "AA040": ("Rig / Superstructure",         THEME_CULTURE,   None),
    "AA052": ("Hydrocarbons Field",           THEME_CULTURE,   None),
    "AB000": ("Disposal Site",                THEME_CULTURE,   None),
    "AC000": ("Processing / Treatment Plant", THEME_CULTURE,   None),
    "AC030": ("Settling Pond",                THEME_HYDRO,     ROLE_HYDRO),
    "AD010": ("Electric Power Plant",         THEME_CULTURE,   None),
    "AD030": ("Electrical Substation",        THEME_CULTURE,   None),
    "AF010": ("Chimney / Smokestack",         THEME_CULTURE,   None),
    "AH050": ("Fortification",                THEME_MILITARY,  ROLE_OBSTACLE),
    "AK040": ("Athletic Field",               THEME_CULTURE,   None),
    "AK160": ("Stadium",                      THEME_CULTURE,   None),
    "AL010": ("Facility",                     THEME_CULTURE,   None),
    "AL012": ("Archaeological Site",          THEME_CULTURE,   None),
    "AL013": ("Building",                     THEME_CULTURE,   ROLE_OBSTACLE),
    "AL015": ("Building",                     THEME_CULTURE,   ROLE_OBSTACLE),
    "AL020": ("Built-up Area",                THEME_CULTURE,   ROLE_OBSTACLE),
    "AL025": ("Cairn",                        THEME_CULTURE,   None),
    "AL030": ("Cemetery",                     THEME_CULTURE,   ROLE_OBSTACLE),
    "AL070": ("Fence",                        THEME_CULTURE,   ROLE_OBSTACLE),
    "AL080": ("Gantry",                       THEME_CULTURE,   None),
    "AL105": ("Settlement",                   THEME_CULTURE,   ROLE_OBSTACLE),
    "AL130": ("Memorial Monument",            THEME_CULTURE,   None),
    "AL200": ("Ruins",                        THEME_CULTURE,   None),
    "AL240": ("Tower (Non-communication)",    THEME_CULTURE,   None),
    "AL260": ("Wall",                         THEME_CULTURE,   ROLE_OBSTACLE),
    "AM010": ("Storage Depot",                THEME_CULTURE,   None),
    "AM020": ("Grain Storage Structure",      THEME_CULTURE,   None),
    "AM030": ("Grain Elevator",               THEME_CULTURE,   None),
    "AM040": ("Mineral Pile",                 THEME_CULTURE,   ROLE_OBSTACLE),
    "AM060": ("Surface Bunker",               THEME_MILITARY,  None),
    "AM070": ("Storage Tank",                 THEME_CULTURE,   None),
    "AM080": ("Water Tower",                  THEME_CULTURE,   None),
    # ── Rail / roads / transport structures (AN / AP / AQ / AT) ──────────────
    "AN010": ("Railway",                      THEME_TRANSPORT, ROLE_ROAD),
    "AN050": ("Railway Sidetrack",            THEME_TRANSPORT, None),
    "AN060": ("Railway Yard",                 THEME_TRANSPORT, None),
    "AN075": ("Railway Turntable",            THEME_TRANSPORT, None),
    "AP010": ("Cart Track",                   THEME_TRANSPORT, ROLE_ROAD),
    "AP020": ("Road Interchange",             THEME_TRANSPORT, ROLE_ROAD),
    "AP030": ("Road",                         THEME_TRANSPORT, ROLE_ROAD),
    "AP050": ("Trail",                        THEME_TRANSPORT, ROLE_ROAD),
    "AQ040": ("Bridge",                       THEME_TRANSPORT, ROLE_ROAD),
    "AQ060": ("Control Tower",                THEME_AERO,      None),
    "AQ065": ("Culvert",                      THEME_TRANSPORT, None),
    "AQ113": ("Pipeline",                     THEME_CULTURE,   ROLE_OBSTACLE),
    "AQ116": ("Pumping Station",              THEME_CULTURE,   None),
    "AQ130": ("Tunnel",                       THEME_TRANSPORT, None),
    "AT010": ("Dish Aerial",                  THEME_CULTURE,   None),
    "AT042": ("Pylon",                        THEME_CULTURE,   None),
    "AT045": ("Radar Station",                THEME_MILITARY,  None),
    "AT080": ("Communication Tower",          THEME_CULTURE,   None),
    # ── Hydrography (B*) ──────────────────────────────────────────────────────
    "BA010": ("Land / Water Boundary",        THEME_HYDRO,     None),
    "BA030": ("Island",                       THEME_HYDRO,     None),
    "BA040": ("Tidal Water",                  THEME_HYDRO,     ROLE_HYDRO),
    "BA050": ("Beach",                        THEME_HYDRO,     None),
    "BB005": ("Harbour",                      THEME_HYDRO,     ROLE_HYDRO),
    "BB190": ("Berthing Structure (Pier/Wharf/Quay)", THEME_HYDRO, None),
    "BD120": ("Reef",                         THEME_HYDRO,     None),
    "BH010": ("Aqueduct",                     THEME_HYDRO,     ROLE_OBSTACLE),
    "BH020": ("Canal",                        THEME_HYDRO,     ROLE_HYDRO),
    "BH030": ("Ditch",                        THEME_HYDRO,     ROLE_OBSTACLE),
    "BH070": ("Ford",                         THEME_HYDRO,     None),
    "BH080": ("Lake / Pond",                  THEME_HYDRO,     ROLE_HYDRO),
    "BH090": ("Land Subject to Inundation",   THEME_HYDRO,     ROLE_HYDRO),
    "BH110": ("Penstock",                     THEME_HYDRO,     None),
    "BH120": ("Rapids",                       THEME_HYDRO,     ROLE_HYDRO),
    "BH135": ("Rice Field",                   THEME_HYDRO,     ROLE_HYDRO),
    "BH140": ("River / Stream",               THEME_HYDRO,     ROLE_HYDRO),
    "BH155": ("Salt Evaporator",              THEME_HYDRO,     ROLE_HYDRO),
    "BH160": ("Sabkha",                       THEME_HYDRO,     ROLE_HYDRO),
    "BH165": ("Waterfall",                    THEME_HYDRO,     None),
    "BH170": ("Natural Pool / Spring",        THEME_HYDRO,     None),
    "BI010": ("Cistern",                      THEME_HYDRO,     None),
    "BI020": ("Dam / Weir",                   THEME_HYDRO,     ROLE_OBSTACLE),
    "BI030": ("Lock",                         THEME_HYDRO,     None),
    "BI040": ("Sluice Gate",                  THEME_HYDRO,     None),
    "BJ030": ("Glacier",                      THEME_HYDRO,     ROLE_HYDRO),
    "BJ065": ("Ice Shelf",                    THEME_HYDRO,     ROLE_HYDRO),
    "BJ100": ("Snow / Ice Field",             THEME_HYDRO,     ROLE_HYDRO),
    "BJ110": ("Tundra",                       THEME_VEG,       ROLE_VEG),
    # ── Hypsography (C*) ──────────────────────────────────────────────────────
    "CA010": ("Elevation Contour",            THEME_ELEVATION, ROLE_CONTOURS),
    "CA030": ("Spot Elevation",               THEME_ELEVATION, None),
    # ── Physiography (D*) ─────────────────────────────────────────────────────
    "DA005": ("Asphalt Lake",                 THEME_PHYSIO,    ROLE_OBSTACLE),
    "DA010": ("Ground Surface Element (soil — SMC attribute)",
                                              THEME_SOIL,      ROLE_SOIL),
    "DB010": ("Bluff / Cliff / Escarpment",   THEME_PHYSIO,    ROLE_OBSTACLE),
    "DB070": ("Cut",                          THEME_PHYSIO,    ROLE_OBSTACLE),
    "DB090": ("Embankment",                   THEME_PHYSIO,    ROLE_OBSTACLE),
    "DB110": ("Geologic Fault",               THEME_PHYSIO,    None),
    "DB115": ("Geothermal Feature",           THEME_PHYSIO,    None),
    "DB150": ("Mountain Pass",                THEME_PHYSIO,    None),
    "DB160": ("Rock Formation",               THEME_PHYSIO,    ROLE_OBSTACLE),
    "DB170": ("Sand Dunes",                   THEME_PHYSIO,    ROLE_OBSTACLE),
    "DB180": ("Volcano",                      THEME_PHYSIO,    ROLE_OBSTACLE),
    # ── Vegetation (E*) ───────────────────────────────────────────────────────
    "EA010": ("Crop Land",                    THEME_VEG,       ROLE_VEG),
    "EA020": ("Hedgerow",                     THEME_VEG,       ROLE_OBSTACLE),
    "EA030": ("Plant Nursery",                THEME_VEG,       ROLE_VEG),
    "EA040": ("Orchard / Plantation",         THEME_VEG,       ROLE_VEG),
    "EA050": ("Vineyard",                     THEME_VEG,       ROLE_VEG),
    "EA055": ("Hop Field",                    THEME_VEG,       ROLE_VEG),
    "EB010": ("Grassland",                    THEME_VEG,       ROLE_VEG),
    "EB020": ("Thicket / Scrub / Brush",      THEME_VEG,       ROLE_VEG),
    "EC010": ("Bamboo / Cane",                THEME_VEG,       ROLE_VEG),
    "EC015": ("Forest",                       THEME_VEG,       ROLE_VEG),
    "EC020": ("Oasis",                        THEME_VEG,       ROLE_VEG),
    "EC030": ("Trees / Woodland",             THEME_VEG,       ROLE_VEG),
    "EC040": ("Cleared Way / Firebreak",      THEME_VEG,       None),
    "ED010": ("Marsh / Wetland",              THEME_VEG,       ROLE_VEG),
    "ED020": ("Swamp",                        THEME_VEG,       ROLE_VEG),
    # ── Boundaries (F*) ───────────────────────────────────────────────────────
    "FA000": ("Administrative Boundary",      THEME_BOUNDARY,  None),
    "FA015": ("Firing Range",                 THEME_MILITARY,  None),
    # ── Aeronautical (G*) ─────────────────────────────────────────────────────
    "GB005": ("Land Aerodrome / Airport",     THEME_AERO,      None),
    "GB015": ("Apron / Hardstanding",         THEME_AERO,      None),
    "GB030": ("Helipad",                      THEME_AERO,      None),
    "GB035": ("Heliport",                     THEME_AERO,      None),
    "GB040": ("Launch Pad",                   THEME_AERO,      None),
    "GB045": ("Overrun / Stopway",            THEME_AERO,      None),
    "GB055": ("Runway",                       THEME_AERO,      None),
    "GB075": ("Taxiway",                      THEME_AERO,      None),
    # ── Military / general (S* / Z*) ─────────────────────────────────────────
    "SU001": ("Military Installation",        THEME_MILITARY,  None),
    "ZD040": ("Named Location",               THEME_OTHER,     None),
    "ZD045": ("Annotated Location",           THEME_OTHER,     None),
}

# First-letter fallback when a code is not in the catalog.
_LETTER_THEMES = {
    "A": THEME_CULTURE,
    "B": THEME_HYDRO,
    "C": THEME_ELEVATION,
    "D": THEME_PHYSIO,
    "E": THEME_VEG,
    "F": THEME_BOUNDARY,
    "G": THEME_AERO,
    "S": THEME_MILITARY,
    "Z": THEME_OTHER,
}

# Regex: a FACC code embedded anywhere in an FC name
# (handles prefixes/suffixes such as "main_AP030", "AP030_1", "AP030L").
_CODE_RE = re.compile(r"([A-Z]{2}\d{3})")


# ── Public API ─────────────────────────────────────────────────────────────────

def extract_code(fc_name):
    """
    Extract the 5-character FACC code from a feature-class name.
    Returns the code (e.g. 'AP030') or None if no code pattern is found.
    """
    if not fc_name:
        return None
    base = os.path.splitext(os.path.basename(str(fc_name)))[0]
    m = _CODE_RE.search(base.upper())
    return m.group(1) if m else None


def lookup(fc_name):
    """
    Classify a feature-class name.

    Returns dict: {code, name, theme, ccm_role}.  Falls back to the
    first-letter theme for codes not in the catalog, and to THEME_OTHER
    for names with no recognisable code.
    """
    code = extract_code(fc_name)
    if code and code in MGCP_CATALOG:
        name, theme, role = MGCP_CATALOG[code]
        return {"code": code, "name": name, "theme": theme, "ccm_role": role}
    if code:
        theme = _LETTER_THEMES.get(code[0], THEME_OTHER)
        return {"code": code, "name": f"Unknown feature ({code})",
                "theme": theme, "ccm_role": None}
    return {"code": None, "name": str(fc_name), "theme": THEME_OTHER,
            "ccm_role": None}


def label(fc_name):
    """
    Human-readable pick-list label:  'AP030 — Road (Transportation)'.
    Non-MGCP names pass through with just the theme appended.
    """
    info = lookup(fc_name)
    base = os.path.splitext(os.path.basename(str(fc_name)))[0]
    if info["code"]:
        return f"{base} — {info['name']} ({info['theme']})"
    return f"{base} ({info['theme']})"


def name_from_label(value):
    """
    Recover the raw FC name from a pick-list label produced by label().
    Safe on plain FC names (returns them unchanged).
    """
    s = str(value).strip().strip("'\"")
    # Split on the em-dash separator first, then on ' (' for the
    # theme-only form.
    if " — " in s:
        return s.split(" — ")[0].strip()
    if " (" in s and s.endswith(")"):
        return s[: s.rindex(" (")].strip()
    return s


def theme_of(fc_name):
    """Theme string for an FC name."""
    return lookup(fc_name)["theme"]


def is_ccm_relevant(fc_name):
    """True if the FC's theme feeds the CCM mobility model."""
    return theme_of(fc_name) in CCM_RELEVANT_THEMES


# ── Manifest helpers ───────────────────────────────────────────────────────────

MANIFEST_FILENAME = "mgcp_manifest.json"


def manifest_path_for_gdb(output_gdb):
    """Manifest sits next to the output GDB."""
    return os.path.join(os.path.dirname(str(output_gdb)), MANIFEST_FILENAME)


def load_manifest(path_or_gdb):
    """
    Load a manifest JSON.  Accepts the manifest path, its folder, or the
    output GDB path.  Returns dict or {}.
    """
    import json
    p = str(path_or_gdb)
    if p.lower().endswith(".gdb"):
        p = manifest_path_for_gdb(p)
    elif os.path.isdir(p):
        p = os.path.join(p, MANIFEST_FILENAME)
    if not os.path.isfile(p):
        return {}
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def features_by_role(manifest, role):
    """List of manifest feature entries with the given ccm_role."""
    return [f for f in (manifest.get("features") or [])
            if f.get("ccm_role") == role]

# <<< END OF FILE >>>
