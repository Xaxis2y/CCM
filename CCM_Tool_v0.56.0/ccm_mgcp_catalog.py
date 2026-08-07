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
  * ccm_step0_mgcp.py  — labelled pick-list, theme filter, theme/geometry
                         group layers, mgcp_manifest.json
  * ccm_step1_setup.py — manifest-driven auto-fill of soil / hydro /
                         contour inputs

New in v0.50.0.

v0.56.0 — "Unknown feature" elimination + geometry grouping support
-------------------------------------------------------------------
Before v0.56.0 any FACC code missing from ``MGCP_CATALOG`` produced the
label ``"Unknown feature (XXnnn)"``, and any feature-class name with no
embedded FACC code at all (MGCP TRD 4.x thematic deliveries use names
such as ``TransportationGroundCrv`` or ``HydrographySrf``) collapsed into
theme ``Other``.  Real deliveries therefore filled the Contents pane with
"Unknown ..." layers and an oversized "Other" group.

``lookup()`` now resolves a name through FOUR ordered tiers and reports
which one fired via the new ``match`` key:

  1. ``MATCH_USER``     — user override from ``mgcp_catalog_user.csv``
                          (see ``load_user_catalog``); always wins.
  2. ``MATCH_EXACT``    — the FACC code is in ``MGCP_CATALOG``.
  3. ``MATCH_CATEGORY`` — the code is not catalogued, but its 2-letter
                          FACC category IS (``_FACC_CATEGORIES``).  The
                          FACC category structure is stable across TRD
                          revisions, so ``AP999`` is reliably a
                          "Road / track feature (Transportation)" even
                          though its exact meaning is unknown here.  This
                          is a genuine classification, not a guess at the
                          feature name — hence no ``ccm_role`` is
                          inferred (never feed an unverified layer into
                          the mobility model).
  4. ``MATCH_KEYWORD``  — no FACC code at all; the NAME is matched against
                          ``_NAME_RULES`` so TRD 4.x thematic names land
                          in the right theme.  Roles are inferred only for
                          the two unambiguous cases (soil, contours).
  5. ``MATCH_NONE``     — nothing matched; theme ``Other``.

Deliberately NOT done: inventing human-readable names for FACC codes that
could not be verified against an authoritative MGCP TRD feature
catalogue.  A wrong name is worse than an honest category.  Use
``mgcp_catalog_user.csv`` (template auto-written by Step 0) to name the
codes present in YOUR delivery, from YOUR TRD document.

Also new in v0.56.0: ``geometry_group()`` / ``GEOMETRY_GROUPS``, which
Step 0 uses to build the Point / Line / Polygon map groups.
"""

import os
import re

VERSION = "0.56.0"  # v0.56.0 -- MGCP loader: Point/Line/Polygon map groups; FACC category + name-keyword fallback classification (no more "Unknown feature"); user-editable mgcp_catalog_user.csv override; hardened Unknown-CRS repair. See CHANGELOG_v0.56.md.

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

# ── Match tiers (v0.56.0) ──────────────────────────────────────────────────────
MATCH_USER     = "user"       # from mgcp_catalog_user.csv
MATCH_EXACT    = "exact"      # FACC code found in MGCP_CATALOG
MATCH_CATEGORY = "category"   # 2-letter FACC category fallback
MATCH_KEYWORD  = "keyword"    # name-keyword fallback (no FACC code)
MATCH_NONE     = "none"       # nothing matched

# Tiers that mean "this FC is NOT individually catalogued here".  Step 0
# reports these so the user can extend mgcp_catalog_user.csv.
UNCLASSIFIED_MATCHES = (MATCH_CATEGORY, MATCH_KEYWORD, MATCH_NONE)

# ── Geometry groups (v0.56.0) ──────────────────────────────────────────────────
GEOM_POINT   = "Point"
GEOM_LINE    = "Line"
GEOM_POLYGON = "Polygon"
GEOM_OTHER   = "Other"

# Cartographic draw order, TOP of the Contents pane first: points must draw
# above lines, lines above polygons, or the polygons hide everything.
GEOMETRY_GROUPS = [GEOM_POINT, GEOM_LINE, GEOM_POLYGON, GEOM_OTHER]

# arcpy Describe().shapeType (and OGR/GeoPackage spellings) -> group
_SHAPETYPE_TO_GROUP = {
    "point"           : GEOM_POINT,
    "multipoint"      : GEOM_POINT,
    "polyline"        : GEOM_LINE,
    "line"            : GEOM_LINE,
    "linestring"      : GEOM_LINE,
    "multilinestring" : GEOM_LINE,
    "curve"           : GEOM_LINE,
    "polygon"         : GEOM_POLYGON,
    "multipolygon"    : GEOM_POLYGON,
    "area"            : GEOM_POLYGON,
    "surface"         : GEOM_POLYGON,
}

# MGCP / DIGEST feature-class NAME suffix conventions, used only when the
# real shapeType is unavailable:
#   TRD 4.x thematic  : ...Pnt / ...Crv / ...Srf
#   DIGEST / VMap     : ...P   / ...L   / ...A  (also _P / _L / _A / _S)
#   common shapefile  : _pt / _ln / _ar / _poly / _point / _line
_NAME_GEOM_RULES = [
    (re.compile(r"(?:pnt|point|_pt|_p)$", re.I),                 GEOM_POINT),
    (re.compile(r"(?:crv|curve|line|_ln|_l)$", re.I),            GEOM_LINE),
    (re.compile(r"(?:srf|surf|surface|poly|polygon|area|_ar|_a|_s)$",
                re.I),                                          GEOM_POLYGON),
    # Bare single-letter suffix directly after a 5-char FACC code: AP030L
    (re.compile(r"^[A-Z]{2}\d{3}P$", re.I),                      GEOM_POINT),
    (re.compile(r"^[A-Z]{2}\d{3}L$", re.I),                      GEOM_LINE),
    (re.compile(r"^[A-Z]{2}\d{3}[AS]$", re.I),                   GEOM_POLYGON),
]

# ── Catalog ────────────────────────────────────────────────────────────────────
# code : (human-readable name, theme, ccm_role or None)
# Codes follow FACC / MGCP TRD naming.  Both AL013 and AL015 are listed
# because Building changed codes between TRD versions.
MGCP_CATALOG = {
    # ── Culture / industry (A*) ───────────────────────────────────────────────
    "AA010": ("Extraction Mine",              THEME_CULTURE,   ROLE_OBSTACLE),
    "AA012": ("Quarry",                       THEME_CULTURE,   ROLE_OBSTACLE),
    "AA040": ("Rig / Superstructure",         THEME_CULTURE,   None),
    "AA050": ("Well",                         THEME_CULTURE,   None),
    "AA052": ("Hydrocarbons Field",           THEME_CULTURE,   None),
    "AB000": ("Disposal Site",                THEME_CULTURE,   None),
    "AC000": ("Processing / Treatment Plant", THEME_CULTURE,   None),
    "AC030": ("Settling Pond",                THEME_HYDRO,     ROLE_HYDRO),
    "AD010": ("Electric Power Plant",         THEME_CULTURE,   None),
    "AD030": ("Electrical Substation",        THEME_CULTURE,   None),
    "AF010": ("Chimney / Smokestack",         THEME_CULTURE,   None),
    "AF030": ("Cooling Tower",                THEME_CULTURE,   None),
    "AF040": ("Crane",                        THEME_CULTURE,   None),
    "AH050": ("Fortification",                THEME_MILITARY,  ROLE_OBSTACLE),
    "AJ050": ("Windmill",                     THEME_CULTURE,   None),
    "AJ051": ("Wind Turbine",                 THEME_CULTURE,   None),
    "AJ110": ("Greenhouse",                   THEME_CULTURE,   ROLE_OBSTACLE),
    "AK030": ("Amusement Park",               THEME_CULTURE,   None),
    "AK040": ("Athletic Field",               THEME_CULTURE,   None),
    "AK120": ("Park",                         THEME_CULTURE,   None),
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
    "AL208": ("Shanty Town",                  THEME_CULTURE,   ROLE_OBSTACLE),
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
    "AP040": ("Gate",                         THEME_TRANSPORT, ROLE_OBSTACLE),
    "AP041": ("Vehicle Barrier",              THEME_TRANSPORT, ROLE_OBSTACLE),
    "AP050": ("Trail",                        THEME_TRANSPORT, ROLE_ROAD),
    "AQ040": ("Bridge",                       THEME_TRANSPORT, ROLE_ROAD),
    "AQ060": ("Control Tower",                THEME_AERO,      None),
    "AQ065": ("Culvert",                      THEME_TRANSPORT, None),
    "AQ070": ("Ferry Crossing",               THEME_TRANSPORT, ROLE_ROAD),
    "AQ113": ("Pipeline",                     THEME_CULTURE,   ROLE_OBSTACLE),
    "AQ116": ("Pumping Station",              THEME_CULTURE,   None),
    "AQ125": ("Transportation Station",       THEME_TRANSPORT, None),
    "AQ130": ("Tunnel",                       THEME_TRANSPORT, None),
    "AQ150": ("Stair",                        THEME_TRANSPORT, None),
    "AQ170": ("Motor Vehicle Station",        THEME_TRANSPORT, None),
    "AT005": ("Cable / Transmission Line",    THEME_CULTURE,   None),
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
    "ZD020": ("Void Collection Area",         THEME_OTHER,     None),
    "ZD040": ("Named Location",               THEME_OTHER,     None),
    "ZD045": ("Annotated Location",           THEME_OTHER,     None),
}

# ── FACC 2-letter category fallback (v0.56.0) ─────────────────────────────────
# The FACC/DIGEST category structure (first two letters) is stable across TRD
# revisions and is what makes an uncatalogued code still classifiable.  Value:
# (category description, theme).  No ccm_role is ever inferred at this tier —
# an unverified feature must not silently feed the mobility model.
_FACC_CATEGORIES = {
    "AA": ("Extraction / mining feature",        THEME_CULTURE),
    "AB": ("Waste-disposal feature",             THEME_CULTURE),
    "AC": ("Processing / treatment facility",    THEME_CULTURE),
    "AD": ("Power-generation facility",          THEME_CULTURE),
    "AF": ("Industrial structure",               THEME_CULTURE),
    "AG": ("Commercial / retail facility",       THEME_CULTURE),
    "AH": ("Fortification",                      THEME_MILITARY),
    "AI": ("Accommodation facility",             THEME_CULTURE),
    "AJ": ("Agricultural structure",             THEME_CULTURE),
    "AK": ("Recreational facility",              THEME_CULTURE),
    "AL": ("Settlement / building feature",      THEME_CULTURE),
    "AM": ("Storage facility",                   THEME_CULTURE),
    "AN": ("Railway feature",                    THEME_TRANSPORT),
    "AP": ("Road / track feature",               THEME_TRANSPORT),
    "AQ": ("Transportation structure",           THEME_TRANSPORT),
    "AT": ("Communication / utility feature",    THEME_CULTURE),
    "BA": ("Shoreline / coastal feature",        THEME_HYDRO),
    "BB": ("Port / harbour feature",             THEME_HYDRO),
    "BC": ("Navigation aid",                     THEME_HYDRO),
    "BD": ("Underwater danger / obstruction",    THEME_HYDRO),
    "BE": ("Bathymetric feature",                THEME_HYDRO),
    "BF": ("Sea-floor / bottom feature",         THEME_HYDRO),
    "BG": ("Tide / current feature",             THEME_HYDRO),
    "BH": ("Inland water feature",               THEME_HYDRO),
    "BI": ("Hydrographic structure",             THEME_HYDRO),
    "BJ": ("Snow / ice feature",                 THEME_HYDRO),
    "CA": ("Relief / elevation feature",         THEME_ELEVATION),
    "CB": ("Relief-related feature",             THEME_ELEVATION),
    "CC": ("Relief-related feature",             THEME_ELEVATION),
    "DA": ("Surface-material feature",           THEME_SOIL),
    "DB": ("Landform feature",                   THEME_PHYSIO),
    "DC": ("Landform feature",                   THEME_PHYSIO),
    "DD": ("Landform feature",                   THEME_PHYSIO),
    "EA": ("Cultivated vegetation",              THEME_VEG),
    "EB": ("Herbaceous vegetation",              THEME_VEG),
    "EC": ("Trees / shrub vegetation",           THEME_VEG),
    "ED": ("Wetland vegetation",                 THEME_VEG),
    "EE": ("Special vegetation feature",         THEME_VEG),
    "FA": ("Administrative boundary feature",    THEME_BOUNDARY),
    "FC": ("Maritime limit",                     THEME_BOUNDARY),
    "GA": ("Airspace feature",                   THEME_AERO),
    "GB": ("Aerodrome feature",                  THEME_AERO),
    "SU": ("Military installation feature",      THEME_MILITARY),
    "ZB": ("Geodetic control feature",           THEME_OTHER),
    "ZC": ("Cartographic feature",               THEME_OTHER),
    "ZD": ("Named / annotated location",         THEME_OTHER),
    "ZI": ("Metadata feature",                   THEME_OTHER),
}

# First-letter fallback when even the 2-letter category is unknown.
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

_LETTER_DESCRIPTIONS = {
    "A": "Culture feature",
    "B": "Hydrography feature",
    "C": "Hypsography feature",
    "D": "Physiography feature",
    "E": "Vegetation feature",
    "F": "Boundary feature",
    "G": "Aeronautical feature",
    "S": "Military feature",
    "Z": "General / metadata feature",
}

# ── Name-keyword rules (v0.56.0) ──────────────────────────────────────────────
# For feature-class names with NO embedded FACC code — MGCP TRD 4.x thematic
# deliveries ("TransportationGroundCrv", "HydrographySrf", "VegetationSrf"),
# and hand-named layers.  Evaluated IN ORDER; first hit wins, so the more
# specific themes are listed before the broad "culture" catch-all.
# Tuple: (compiled pattern, display name, theme, ccm_role)
_NAME_RULES = [
    (re.compile(r"soil|smc|surfacemat|groundsurf|ground_surf", re.I),
     "Soil / ground surface",          THEME_SOIL,      ROLE_SOIL),
    # Only a genuine CONTOUR layer earns ROLE_CONTOURS — Step 1 auto-fills
    # its slope-fallback input from that role, and a spot-height layer there
    # would silently produce a wrong slope surface.
    (re.compile(r"contour", re.I),
     "Elevation Contour",              THEME_ELEVATION, ROLE_CONTOURS),
    (re.compile(r"hypso|spot_?elev|elevation|relief", re.I),
     "Elevation",                      THEME_ELEVATION, None),
    (re.compile(r"veget|forest|woodland|tree|crop|agricultur|farm|grass|"
                r"scrub|brush|thicket|orchard|vineyard|marsh|swamp|wetland",
                re.I),
     "Vegetation",                     THEME_VEG,       None),
    (re.compile(r"hydro|water|river|stream|lake|pond|canal|ditch|reservoir|"
                r"coast|shorel|inundat|marine|tidal|aquatic", re.I),
     "Hydrography",                    THEME_HYDRO,     None),
    (re.compile(r"transport|road|street|highway|track|trail|rail|bridge|"
                r"tunnel|ferry|runway_?link|traffic", re.I),
     "Transportation",                 THEME_TRANSPORT, None),
    (re.compile(r"physio|landform|terrain|slope|cliff|bluff|escarp|dune|"
                r"rock|volcan", re.I),
     "Physiography",                   THEME_PHYSIO,    None),
    (re.compile(r"aero|airport|airfield|aerodrome|runway|taxiway|apron|"
                r"heli", re.I),
     "Aeronautical",                   THEME_AERO,      None),
    (re.compile(r"militar|firing|fortif|cantonment|garrison|barrack", re.I),
     "Military",                       THEME_MILITARY,  None),
    (re.compile(r"boundar|administrat|admin_|political|limit", re.I),
     "Boundary",                       THEME_BOUNDARY,  None),
    (re.compile(r"settlement|building|structure|culture|urban|built_?up|"
                r"facility|industr|storage|utility|recreat|commerc|"
                r"residential", re.I),
     "Culture / built-up",             THEME_CULTURE,   None),
    (re.compile(r"metadata|^meta|_meta", re.I),
     "Metadata",                       THEME_OTHER,     None),
]

# Regex: a FACC code embedded anywhere in an FC name
# (handles prefixes/suffixes such as "main_AP030", "AP030_1", "AP030L").
_CODE_RE = re.compile(r"([A-Z]{2}\d{3})")

# ── User override catalog (v0.56.0) ───────────────────────────────────────────
USER_CATALOG_FILENAME = "mgcp_catalog_user.csv"
USER_CATALOG_ENV      = "CCM_MGCP_CATALOG_USER"

# code -> (name, theme, ccm_role or None).  Populated by load_user_catalog().
_USER_CATALOG = {}
_USER_CATALOG_SOURCES = []

_USER_CATALOG_HEADER = "code,name,theme,ccm_role"

_USER_CATALOG_PREAMBLE = [
    "# mgcp_catalog_user.csv — local MGCP feature-code overrides for the CCM Tool",
    "#",
    "# The built-in catalog (ccm_mgcp_catalog.MGCP_CATALOG) covers the FACC codes",
    "# that could be verified against an authoritative source.  Anything else is",
    "# classified by its 2-letter FACC category, which gives a correct THEME but",
    "# only a generic NAME.  Fill in the rows below from your own MGCP TRD",
    "# Feature and Attribute Catalogue to get exact names — and, where the layer",
    "# really is a CCM input, a ccm_role.",
    "#",
    "# Columns",
    "#   code      5-character FACC code, e.g. AP030",
    "#   name      human-readable name shown in the map Contents pane",
    "#   theme     one of: " + " | ".join(ALL_THEMES),
    "#   ccm_role  blank, or one of: soil | hydro | veg | contours | obstacle | road",
    "#             LEAVE BLANK unless you are certain — a wrong role feeds the",
    "#             wrong data into the Step 2 mobility model.",
    "#",
    "# Lines starting with '#' are ignored.  Rows already filled in are kept",
    "# when Step 0 refreshes this template.",
    "#",
]


def user_catalog_search_paths(extra_folder=None):
    """
    Ordered list of candidate ``mgcp_catalog_user.csv`` locations.

    1. ``$CCM_MGCP_CATALOG_USER``  (full file path, or a folder)
    2. *extra_folder*              (Step 0 passes the output-GDB folder)
    3. this module's own folder    (ships with the toolbox)
    """
    paths = []
    env = os.environ.get(USER_CATALOG_ENV) or ""
    if env:
        paths.append(env if env.lower().endswith(".csv")
                     else os.path.join(env, USER_CATALOG_FILENAME))
    if extra_folder:
        paths.append(os.path.join(str(extra_folder), USER_CATALOG_FILENAME))
    paths.append(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              USER_CATALOG_FILENAME))
    # De-duplicate, preserve order
    seen, out = set(), []
    for p in paths:
        key = os.path.normcase(os.path.abspath(p))
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def _parse_user_catalog_file(path):
    """Parse one override CSV.  Returns {code: (name, theme, role)}."""
    import csv
    entries = {}
    try:
        with open(path, encoding="utf-8-sig", newline="") as fh:
            rows = [r for r in csv.reader(fh)
                    if r and not str(r[0]).lstrip().startswith("#")]
    except Exception:
        return entries
    for row in rows:
        cells = [(c or "").strip() for c in row]
        if not cells or not cells[0]:
            continue
        if cells[0].lower() == "code":     # header line
            continue
        code = cells[0].upper()
        if not re.fullmatch(r"[A-Z]{2}\d{3}", code):
            continue
        name  = cells[1] if len(cells) > 1 else ""
        theme = cells[2] if len(cells) > 2 else ""
        role  = cells[3] if len(cells) > 3 else ""
        if not name:
            continue                        # blank template row — skip
        if theme not in ALL_THEMES:
            theme = ""                      # invalid -> fall back below
        entries[code] = (name, theme or None, role.lower() or None)
    return entries


def load_user_catalog(extra_folder=None, reset=True):
    """
    Load ``mgcp_catalog_user.csv`` overrides.

    Later files in :func:`user_catalog_search_paths` do NOT overwrite codes
    already supplied by an earlier (higher-priority) file.

    Returns ``(n_codes, [paths_loaded])``.
    """
    global _USER_CATALOG, _USER_CATALOG_SOURCES
    if reset:
        _USER_CATALOG = {}
        _USER_CATALOG_SOURCES = []
    for path in user_catalog_search_paths(extra_folder):
        if not os.path.isfile(path):
            continue
        entries = _parse_user_catalog_file(path)
        if not entries:
            continue
        added = False
        for code, val in entries.items():
            if code not in _USER_CATALOG:
                _USER_CATALOG[code] = val
                added = True
        if added and path not in _USER_CATALOG_SOURCES:
            _USER_CATALOG_SOURCES.append(path)
    return len(_USER_CATALOG), list(_USER_CATALOG_SOURCES)


def user_catalog_sources():
    """Paths that contributed to the loaded user catalog."""
    return list(_USER_CATALOG_SOURCES)


def write_user_catalog_template(folder, codes, existing_ok=True):
    """
    Write / refresh ``mgcp_catalog_user.csv`` in *folder*, pre-seeded with
    *codes* (an iterable of FACC codes that fell back to a category match).

    Rows the user has already filled in are preserved verbatim; only new,
    still-unnamed codes are appended as blank template rows.  Returns the
    file path, or None on failure.
    """
    try:
        path = os.path.join(str(folder), USER_CATALOG_FILENAME)
        already = _parse_user_catalog_file(path) if os.path.isfile(path) else {}
        if already and not existing_ok:
            return path
        new_codes = sorted({str(c).upper() for c in (codes or [])
                            if c and str(c).upper() not in already})
        if not new_codes and os.path.isfile(path):
            return path                       # nothing to add
        lines = list(_USER_CATALOG_PREAMBLE)
        lines.append(_USER_CATALOG_HEADER)
        for code in sorted(already):
            name, theme, role = already[code]
            lines.append("%s,%s,%s,%s" % (code, name, theme or "", role or ""))
        for code in new_codes:
            info  = _category_info(code)
            theme = info[1] if info else THEME_OTHER
            lines.append("%s,,%s," % (code, theme))
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write("\n".join(lines) + "\n")
        return path
    except Exception:
        return None


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


def _category_info(code):
    """(description, theme) for a FACC code's 2-letter category, or None."""
    if not code or len(code) < 2:
        return None
    cat = code[:2].upper()
    if cat in _FACC_CATEGORIES:
        return _FACC_CATEGORIES[cat]
    letter = cat[0]
    if letter in _LETTER_THEMES:
        return (_LETTER_DESCRIPTIONS.get(letter, "Uncatalogued feature"),
                _LETTER_THEMES[letter])
    return None


def _keyword_info(fc_name):
    """(display name, theme, role) from the NAME, or None if nothing matches."""
    base = os.path.splitext(os.path.basename(str(fc_name)))[0]
    for pattern, name, theme, role in _NAME_RULES:
        if pattern.search(base):
            return (name, theme, role)
    return None


def lookup(fc_name):
    """
    Classify a feature-class name.

    Returns dict with keys:
        code      FACC code or None
        name      human-readable feature name
        theme     one of ALL_THEMES
        ccm_role  ROLE_* or None
        match     MATCH_USER / MATCH_EXACT / MATCH_CATEGORY /
                  MATCH_KEYWORD / MATCH_NONE   (v0.56.0)

    Resolution order — user override, exact FACC code, 2-letter FACC
    category, name keyword, nothing.  See the module docstring.
    """
    code = extract_code(fc_name)

    # 1 — user override (always wins)
    if code and code in _USER_CATALOG:
        name, theme, role = _USER_CATALOG[code]
        if not theme:
            info  = _category_info(code)
            theme = info[1] if info else THEME_OTHER
        return {"code": code, "name": name, "theme": theme,
                "ccm_role": role, "match": MATCH_USER}

    # 2 — exact catalog hit
    if code and code in MGCP_CATALOG:
        name, theme, role = MGCP_CATALOG[code]
        return {"code": code, "name": name, "theme": theme,
                "ccm_role": role, "match": MATCH_EXACT}

    # 3 — FACC 2-letter category fallback
    if code:
        info = _category_info(code)
        if info:
            desc, theme = info
            return {"code": code, "name": desc, "theme": theme,
                    "ccm_role": None, "match": MATCH_CATEGORY}
        return {"code": code, "name": "Uncatalogued feature",
                "theme": THEME_OTHER, "ccm_role": None,
                "match": MATCH_CATEGORY}

    # 4 — no FACC code: classify by name keywords
    kw = _keyword_info(fc_name)
    if kw:
        name, theme, role = kw
        return {"code": None, "name": name, "theme": theme,
                "ccm_role": role, "match": MATCH_KEYWORD}

    # 5 — nothing matched
    return {"code": None, "name": str(fc_name), "theme": THEME_OTHER,
            "ccm_role": None, "match": MATCH_NONE}


def label(fc_name):
    """
    Human-readable pick-list label:  'AP030 — Road (Transportation)'.
    Non-MGCP names pass through with just the theme appended.
    """
    info = lookup(fc_name)
    base = os.path.splitext(os.path.basename(str(fc_name)))[0]
    if info["code"]:
        return f"{base} — {info['name']} ({info['theme']})"
    if info["match"] == MATCH_KEYWORD:
        return f"{base} — {info['name']} ({info['theme']})"
    return f"{base} ({info['theme']})"


def alias(fc_name):
    """
    Geodatabase ALIAS for a feature class:  'Building (AL015)'.

    Deliberately name-first (the opposite of :func:`label`, which is
    code-first so pick-lists sort by FACC code).  The alias is what ArcGIS
    Pro shows in Catalog view and in field/feature-class properties, where
    reading order matters more than sort order.  The underlying feature
    class keeps its original MGCP code name — the alias never touches the
    schema.  v0.56.0.
    """
    info = lookup(fc_name)
    base = os.path.splitext(os.path.basename(str(fc_name)))[0]
    name = info["name"]
    if not name or name == base:
        return base
    return f"{name} ({base})"


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


def is_classified(fc_name):
    """
    True when the FC resolved to a NAMED feature (user override or exact
    FACC catalog hit) rather than a category/keyword fallback.  v0.56.0.
    """
    return lookup(fc_name)["match"] in (MATCH_USER, MATCH_EXACT)


def unclassified_codes(fc_names):
    """
    FACC codes among *fc_names* that only resolved to a category fallback.

    Returns a sorted list of codes — exactly the rows worth adding to
    ``mgcp_catalog_user.csv``.  v0.56.0.
    """
    codes = set()
    for n in (fc_names or []):
        info = lookup(n)
        if info["match"] == MATCH_CATEGORY and info["code"]:
            codes.add(info["code"])
    return sorted(codes)


# ── Geometry helpers (v0.56.0) ────────────────────────────────────────────────

def geometry_group(shape_type=None, fc_name=None):
    """
    Map a geometry to one of GEOMETRY_GROUPS ('Point' / 'Line' / 'Polygon' /
    'Other').

    *shape_type* is an arcpy ``Describe().shapeType`` (or any OGR spelling)
    and is authoritative.  When it is missing or unrecognised, the MGCP /
    DIGEST name suffix conventions are used instead (``...Pnt`` / ``...Crv``
    / ``...Srf``, ``_P`` / ``_L`` / ``_A``, ``AP030L``).
    """
    if shape_type:
        grp = _SHAPETYPE_TO_GROUP.get(str(shape_type).strip().lower())
        if grp:
            return grp
    if fc_name:
        base = os.path.splitext(os.path.basename(str(fc_name)))[0]
        for pattern, grp in _NAME_GEOM_RULES:
            if pattern.search(base):
                return grp
    return GEOM_OTHER


def sort_geometry_groups(groups):
    """
    Order *groups* by GEOMETRY_GROUPS (Point, Line, Polygon, Other) — the
    order they should appear TOP-DOWN in the ArcGIS Pro Contents pane so
    points draw above lines and lines above polygons.
    """
    order = {g: i for i, g in enumerate(GEOMETRY_GROUPS)}
    return sorted(set(groups or []),
                  key=lambda g: (order.get(g, len(order)), str(g)))


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
