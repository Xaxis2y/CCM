# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# ccm_veg_preprocess.py
# CCM Vegetation Data Preprocessor — v0.46
# Compatible with ArcGIS Pro 3.x (Python 3.x + arcpy)
#
# Converts land-cover / vegetation raster datasets (GeoTIFF, IMG, etc.) into
# a polygon Feature Class with the three CCM vegetation fields:
#
#   vegetationTrafficImpact  (VTI)   — float 0.0–1.0
#       Controls Factor F2 (vegetation resistance to movement).
#       0 = no impedance; 1 = impassable.
#
#   treeSpacing              (metres) — float ≥ 0
#       Average gap between stems; controls F3 (manoeuvre room).
#       0 = no trees present in the class.
#
#   stemDiameter             (cm)    — float ≥ 0
#       Average trunk diameter at breast height; controls F3.
#       0 = no trees present in the class.
#
# Supported raster datasets (auto-detected):
# ─────────────────────────────────────────
#   CLASS-CODE RASTERS  (integer class codes → lookup table)
#   ──────────────────
#   ESA WorldCover 10 m   (2020/2021)  — Copernicus / ESA      ★ recommended
#       11 classes, codes: 10 20 30 40 50 60 70 80 90 95 100
#   NLCD (National Land Cover Database, US)  — USGS
#       16 classes, codes: 11 21 22 23 24 31 41 42 43 52 71 81 82 90 95
#   CGLS-LC100 (Copernicus Global Land Service 100 m)  — Copernicus
#       3-digit forest sub-classes (111–126) plus 2-digit codes 20–200
#   Generic raster  — any other integer land-cover raster
#       Falls back to a uniform CCM-safe default.
#
#   CONTINUOUS HEIGHT RASTERS  (float metres → allometric derivation)
#   ─────────────────────────
#   NASA/GEDI Global Canopy Height  (10 m / 30 m)
#       Float raster 0–65 m.  Pixel values are actual tree heights (m).
#       Reclassified into 6 height bands; allometric equations derive
#       stemDiameter (Jucker et al. 2017) and treeSpacing.
#       Download: Google Earth Engine → NASA/GEDI/L2A or
#                 Potapov 2021 Global Forest Canopy Height 30 m GeoTIFF
#
#   BIOPHYSICAL PARAMETER FOLDERS  (multi-raster, computed per pixel)
#   ──────────────────────────────
#   Canada Biophysical Parameters  — NRCAN / NRCan
#       Folder containing rasters for Canopy Height (VH_*), Canopy
#       Closure (CC_*), and optionally LAI (*LAI*).
#       Height → stemDiameter via allometric.
#       Closure → treeSpacing via crown packing model.
#       LAI or Closure → VTI.
#       Download: Open Government Canada — "Vegetation Biophysical Parameters"
#
# NOTE: MODIS (250 m–1 km) and NOAA Vegetation Health (1 km) are NOT supported.
#   At 1 km resolution a single cell can span an entire forested hillside;
#   it is impossible to derive meaningful treeSpacing or stemDiameter values
#   for vehicle passability analysis.  Use ESA WorldCover 10 m instead.
#
# Pipeline
# ────────
#   1. Auto-detect dataset type from unique pixel values (or accept override)
#   2. Clip raster to Analysis Extent (optional)
#   3. RasterToPolygon → dissolve on 'gridcode'
#   4. Add CCM fields; populate via lookup table
#   5. Gap-fill unmapped classes with user-supplied defaults
#   6. Auto-reproject to match extent FC CRS if output is Geographic
#
# Output
# ──────
#   A polygon FC containing:
#     'gridcode'                 — original raster class code
#     'vegClass'                 — human-readable class name  (TEXT 80)
#     'vegetationTrafficImpact'  — VTI float
#     'treeSpacing'              — metres float
#     'stemDiameter'             — cm float
#
# This FC can be fed directly into CCMTool as the Vegetation layer.

import os
import re
import arcpy

# ── Version ──────────────────────────────────────────────────────────────────
VERSION = "0.55.0"  # v0.55.0 -- merge release: reconciles the debranded/relicensed v0.54.1 line with all v0.54.2-v0.54.7 fixes (Union licence-limit crash, speed-surface symbology field, alpha scale, ERROR 160333 isochrone resilience, build.py packaging guards). See CHANGELOG_v0.55.md.

# =============================================================================
# SOURCE TYPE CONSTANTS
# =============================================================================

SOURCE_AUTO          = "Auto-Detect"
SOURCE_ESA           = "ESA WorldCover 10 m"
SOURCE_NLCD          = "NLCD (US)"
SOURCE_CGLS          = "CGLS-LC100 (Global 100 m)"
SOURCE_GEDI          = "NASA/GEDI Canopy Height (continuous)"
SOURCE_CANADA_BIO    = "Canada Biophysical Parameters (NRCAN)"
SOURCE_DMTI          = "DMTI Land Use (Canada)"
SOURCE_GENERIC       = "Generic Land-Cover Raster"

ALL_VEG_SOURCES = [
    SOURCE_AUTO,
    SOURCE_ESA,
    SOURCE_NLCD,
    SOURCE_CGLS,
    SOURCE_GEDI,
    SOURCE_CANADA_BIO,
    SOURCE_DMTI,
    SOURCE_GENERIC,
]

# =============================================================================
# LOOKUP TABLES
# Each entry:  class_code → (VTI, treeSpacing_m, stemDiameter_cm, description)
# =============================================================================

# ── ESA WorldCover 10 m ──────────────────────────────────────────────────────
# Source: ESA WorldCover Product User Manual (2020)
# https://esa-worldcover.org
LOOKUP_ESA = {
    10:  (0.70, 15.0, 25.0, "Tree cover"),
    20:  (0.30,  0.0,  0.0, "Shrubland"),
    30:  (0.10,  0.0,  0.0, "Grassland"),
    40:  (0.10,  0.0,  0.0, "Cropland"),
    50:  (0.00,  0.0,  0.0, "Built-up"),
    60:  (0.00,  0.0,  0.0, "Bare / sparse vegetation"),
    70:  (0.00,  0.0,  0.0, "Snow and ice"),
    80:  (0.50,  0.0,  0.0, "Permanent water bodies"),
    90:  (0.30,  0.0,  0.0, "Herbaceous wetland"),
    95:  (0.80,  8.0, 15.0, "Mangroves"),
   100:  (0.10,  0.0,  0.0, "Moss and lichen"),
}

# ── NLCD (National Land Cover Database) ──────────────────────────────────────
# Source: USGS NLCD 2019 class definitions
LOOKUP_NLCD = {
    11:  (0.50,  0.0,  0.0, "Open Water"),
    21:  (0.10, 20.0, 15.0, "Developed, Open Space"),
    22:  (0.10, 25.0, 15.0, "Developed, Low Intensity"),
    23:  (0.00,  0.0,  0.0, "Developed, Medium Intensity"),
    24:  (0.00,  0.0,  0.0, "Developed, High Intensity"),
    31:  (0.00,  0.0,  0.0, "Barren Land"),
    41:  (0.70, 10.0, 25.0, "Deciduous Forest"),
    42:  (0.80,  8.0, 30.0, "Evergreen Forest"),
    43:  (0.70, 10.0, 25.0, "Mixed Forest"),
    52:  (0.30,  0.0,  0.0, "Shrub/Scrub"),
    71:  (0.10,  0.0,  0.0, "Grassland/Herbaceous"),
    81:  (0.10,  0.0,  0.0, "Pasture/Hay"),
    82:  (0.10,  0.0,  0.0, "Cultivated Crops"),
    90:  (0.60, 12.0, 15.0, "Woody Wetlands"),
    95:  (0.20,  0.0,  0.0, "Emergent Herbaceous Wetlands"),
}

# ── CGLS-LC100 (Copernicus Global Land Service 100 m) ────────────────────────
# Source: Copernicus Global Land Service documentation
# 3-digit codes (111–126) distinguish closed vs. open forest and leaf type.
LOOKUP_CGLS = {
      0:  (0.00,  0.0,  0.0, "No data"),
     20:  (0.30,  0.0,  0.0, "Shrubland"),
     30:  (0.10,  0.0,  0.0, "Herbaceous vegetation"),
     40:  (0.10,  0.0,  0.0, "Cultivated / managed vegetation"),
     50:  (0.00,  0.0,  0.0, "Urban / built-up"),
     60:  (0.00,  0.0,  0.0, "Bare / sparse vegetation"),
     70:  (0.00,  0.0,  0.0, "Snow and ice"),
     80:  (0.50,  0.0,  0.0, "Permanent water bodies"),
     90:  (0.30,  0.0,  0.0, "Wetlands"),
    100:  (0.10,  0.0,  0.0, "Moss and lichen"),
    111:  (0.90,  6.0, 30.0, "Closed forest — evergreen needle leaf"),
    112:  (0.90,  6.0, 35.0, "Closed forest — evergreen broad leaf"),
    113:  (0.80,  8.0, 25.0, "Closed forest — deciduous needle leaf"),
    114:  (0.80,  8.0, 30.0, "Closed forest — deciduous broad leaf"),
    115:  (0.80,  8.0, 28.0, "Closed forest — mixed"),
    116:  (0.80,  8.0, 25.0, "Closed forest — unknown"),
    121:  (0.60, 12.0, 25.0, "Open forest — evergreen needle leaf"),
    122:  (0.60, 12.0, 30.0, "Open forest — evergreen broad leaf"),
    123:  (0.50, 15.0, 20.0, "Open forest — deciduous needle leaf"),
    124:  (0.50, 15.0, 25.0, "Open forest — deciduous broad leaf"),
    125:  (0.50, 15.0, 22.0, "Open forest — mixed"),
    126:  (0.50, 15.0, 20.0, "Open forest — unknown"),
    200:  (0.50,  0.0,  0.0, "Open sea"),
}

# ── NASA/GEDI Canopy Height — height-band bins ───────────────────────────────
# Continuous float rasters (0–65 m) are reclassified into 6 bands.
# stemDiameter values derived from pan-temperate allometric model
#   D(cm) = 0.557 × H(m)^0.809  (Jucker et al. 2017, Global Ecology & Biogeography)
# treeSpacing estimated from typical crown packing at each height class.
# VTI scaled proportionally to canopy height (taller = denser = higher F2).
#
# Bin integer code → (VTI, treeSpacing_m, stemDiameter_cm, label, height_range_m)
LOOKUP_GEDI_BINS = {
    1: (0.05,  0.0,  0.0, "Open / no canopy  (0–2 m)",          (0,   2)),
    2: (0.25,  5.0,  3.0, "Low shrub / young regrowth  (2–5 m)", (2,   5)),
    3: (0.50, 10.0, 11.0, "Young / open forest  (5–10 m)",       (5,  10)),
    4: (0.70, 15.0, 22.0, "Mature forest  (10–20 m)",            (10, 20)),
    5: (0.85, 12.0, 37.0, "Tall mature forest  (20–35 m)",       (20, 35)),
    6: (0.90, 10.0, 55.0, "Very tall / old-growth forest  (>35 m)", (35, 999)),
}

# Height band boundary list for arcpy.sa.Reclassify RemapRange
# Each entry: [min_height, max_height, bin_code]
GEDI_RECLASS_RANGES = [
    [v[4][0], v[4][1], k] for k, v in LOOKUP_GEDI_BINS.items()
]

# ── DMTI Spatial — CanMap Land Use (Canada) ──────────────────────────────────
# DMTI land use is a *vector* product: generalised land-use polygons carrying a
# land-use classification field.  Rasterise it on the land-use code field (or
# supply the polygon FC) before running the land-cover step.
#
# IMPORTANT: DMTI land-use class codes vary by product vintage and licence.
# Verify the integer codes below against your DMTI Product Specification.  For
# any class not in this table — or any other unknown source whose classes are
# described in plain language — classify_landcover_label() is used as a
# keyword-based fallback so the data is still processed rather than dropped.
#
# value tuple = (VTI, treeSpacing_m, stemDiameter_cm, label)
LOOKUP_DMTI = {
    1: (0.00,  0.0,  0.0, "Residential"),
    2: (0.00,  0.0,  0.0, "Commercial"),
    3: (0.00,  0.0,  0.0, "Resource & Industrial"),
    4: (0.00,  0.0,  0.0, "Government & Institutional"),
    5: (0.10,  0.0,  0.0, "Parks & Recreational"),
    6: (0.05,  0.0,  0.0, "Open Area / Undeveloped"),
    7: (0.70, 12.0, 22.0, "Forest / Wooded Area"),
    8: (0.10,  0.0,  0.0, "Agricultural / Cropland"),
    9: (0.50,  0.0,  0.0, "Waterbody"),
}


# Keyword-based land-cover classifier.  Maps a free-text land-cover / land-use
# description to mobility vegetation parameters.  Source-agnostic, so it works
# across DMTI, CORINE, national land-use schemes, or any "other" dataset whose
# classes are labelled in plain language.  Rules are ordered most-specific
# first; the first keyword hit wins.
#
# Each rule: (keyword_tuple, (VTI, treeSpacing_m, stemDiameter_cm, label))
_LANDCOVER_KEYWORD_RULES = [
    (("dense forest", "closed forest", "evergreen", "coniferous", "old-growth"),
        (0.85,  8.0, 30.0, "Forest (dense)")),
    (("forest", "wooded", "woodland", "treed", "tree cover", "trees", "timber"),
        (0.70, 12.0, 22.0, "Forest")),
    (("orchard", "vineyard", "plantation"),
        (0.40,  6.0, 15.0, "Orchard / plantation")),
    (("shrub", "scrub", "brush", "bush", "heath"),
        (0.30,  0.0,  0.0, "Shrubland")),
    (("wetland", "marsh", "swamp", "bog", "fen", "mangrove"),
        (0.40,  0.0,  0.0, "Wetland")),
    (("crop", "cultivat", "agricultur", "farm", "pasture", "hay", "arable", "field"),
        (0.10,  0.0,  0.0, "Cropland / agriculture")),
    (("grass", "meadow", "herbaceous", "rangeland", "prairie", "savanna"),
        (0.10,  0.0,  0.0, "Grassland")),
    (("park", "recreation", "golf", "cemetery", "greenspace", "green space"),
        (0.10,  0.0,  0.0, "Park / recreational")),
    (("residential", "commercial", "industrial", "institution", "government",
      "urban", "built", "developed", "transport", "road", "building",
      "settlement", "airport", "infrastructure"),
        (0.00,  0.0,  0.0, "Built-up / developed")),
    (("water", "lake", "river", "ocean", "sea", "pond", "reservoir", "lagoon"),
        (0.50,  0.0,  0.0, "Water")),
    (("snow", "ice", "glacier"),
        (0.00,  0.0,  0.0, "Snow / ice")),
    (("bare", "barren", "rock", "sand", "sparse", "open area", "open land",
      "beach", "gravel", "quarry", "mine"),
        (0.05,  0.0,  0.0, "Bare / sparse")),
    (("moss", "lichen", "tundra"),
        (0.10,  0.0,  0.0, "Moss / lichen / tundra")),
]


def classify_landcover_label(label):
    """Map a free-text land-cover / land-use label to mobility vegetation
    parameters.

    Returns (VTI, treeSpacing_m, stemDiameter_cm, canonical_label) on a match,
    or None if the label is empty or unrecognised.  Pure-Python and arcpy-free
    so it is unit-testable and reusable for generic auto-discovery.
    """
    if not label:
        return None
    text = str(label).strip().lower()
    if not text:
        return None
    for keywords, values in _LANDCOVER_KEYWORD_RULES:
        if any(kw in text for kw in keywords):
            return values
    return None


# Fingerprint sets for auto-detection
_ESA_CODES  = frozenset(LOOKUP_ESA.keys())
_NLCD_CODES = frozenset(LOOKUP_NLCD.keys())
_CGLS_CODES = frozenset(LOOKUP_CGLS.keys())

# =============================================================================
# RESULT NAMEDTUPLE-LIKE CLASS
# =============================================================================

class VegPreprocessResult:
    """Returned by preprocess_vegetation()."""
    __slots__ = ("success", "output_fc", "source_detected", "n_polygons",
                 "n_mapped", "n_gap_filled", "n_unmapped")

    def __init__(self, success=False, output_fc=None, source_detected="",
                 n_polygons=0, n_mapped=0, n_gap_filled=0, n_unmapped=0):
        self.success         = success
        self.output_fc       = output_fc
        self.source_detected = source_detected
        self.n_polygons      = n_polygons
        self.n_mapped        = n_mapped
        self.n_gap_filled    = n_gap_filled
        self.n_unmapped      = n_unmapped

# =============================================================================
# RASTER METADATA HELPER
# =============================================================================

def _get_raster_info(raster_path):
    """
    Return (pixel_type, min_val, max_val, is_float) for a raster.

    pixel_type examples: 'U8', 'S16', 'U16', 'F32', 'F64'
    is_float   — True if pixel type starts with 'F'
    Returns (None, None, None, False) on failure.
    """
    try:
        ras = arcpy.Raster(raster_path)
        pt  = ras.pixelType        # e.g. 'U8', 'F32'
        is_float = pt.startswith("F")
        mn = float(arcpy.management.GetRasterProperties(
            raster_path, "MINIMUM").getOutput(0))
        mx = float(arcpy.management.GetRasterProperties(
            raster_path, "MAXIMUM").getOutput(0))
        return pt, mn, mx, is_float
    except Exception:
        return None, None, None, False


# =============================================================================
# UNIQUE VALUE EXTRACTION
# =============================================================================

def _get_unique_values(raster_path):
    """
    Return a set of integer pixel values present in the raster.

    Tries three strategies in order:
      1. Raster Attribute Table  (fast — pre-built VAT)
      2. arcpy.RasterToNumPyArray (small rasters; samples up to 5 000 × 5 000)
      3. arcpy.GetRasterProperties(UNIQUEVALUECOUNT) fallback  (emergency)

    Returns a set of ints, or an empty set on failure.
    """
    unique = set()

    # ── Strategy 1: Raster Attribute Table ──────────────────────────────────
    try:
        ras = arcpy.Raster(raster_path)
        if ras.hasRAT:
            with arcpy.da.SearchCursor(raster_path, ["Value"]) as cur:
                for row in cur:
                    try:
                        unique.add(int(row[0]))
                    except (TypeError, ValueError):
                        pass
            if unique:
                return unique
    except Exception:
        pass

    # ── Strategy 2: numpy sample ─────────────────────────────────────────────
    try:
        import numpy as np
        ras   = arcpy.Raster(raster_path)
        ncols = min(ras.width,  5000)
        nrows = min(ras.height, 5000)
        arr   = arcpy.RasterToNumPyArray(ras, ncols=ncols, nrows=nrows,
                                         nodata_to_value=-9999)
        vals  = np.unique(arr)
        for v in vals:
            if v != -9999:
                try:
                    unique.add(int(v))
                except (TypeError, ValueError):
                    pass
        if unique:
            return unique
    except Exception:
        pass

    # ── Strategy 3: arcpy.GetRasterProperties ────────────────────────────────
    try:
        min_val = int(float(
            arcpy.management.GetRasterProperties(raster_path, "MINIMUM").getOutput(0)))
        max_val = int(float(
            arcpy.management.GetRasterProperties(raster_path, "MAXIMUM").getOutput(0)))
        # Return the min/max boundary only — enough for coarse fingerprinting
        unique = {min_val, max_val}
    except Exception:
        pass

    return unique

# =============================================================================
# AUTO-DETECTION
# =============================================================================

def _scan_canada_bio_folder(folder_path):
    """
    Look for NRCAN biophysical rasters in a folder.

    Returns dict with keys that are found:
        'height'  : path to canopy height raster (VH / CanopyHeight)
        'closure' : path to canopy closure raster (CC / CanopyClosure)
        'lai'     : path to LAI raster
    Returns empty dict if folder doesn't look like Canada Bio.
    """
    found = {}
    if not folder_path or not os.path.isdir(str(folder_path)):
        return found

    # Both underscore (_) and hyphen (-) variants for NRCAN and other datasets.
    # NRCAN naming: vegetation-YYYY-VH.tif / -CC.tif / -LAI.tif / -fCOVER.tif
    # Note: this dataset does NOT include VH (Vegetation Height).
    # fCOVER (Fraction of Vegetation Cover, 0-1) is used as a canopy-closure
    # proxy to drive treeSpacing when no CC or VH file is present.
    height_kw  = ("_vh_", "_vh.", "-vh.", "-vh_",
                  "canopyheight", "canopy_height",
                  "forestheight", "forest_height",
                  "treeheight",   "tree_height",
                  "vegheight",    "veg_height")
    closure_kw = ("_cc_", "_cc.", "-cc.", "-cc_",
                  "canopyclosure", "canopy_closure",
                  "canopycover",   "canopy_cover",
                  # fCOVER = Fraction of Vegetation Cover — NRCAN canopy proxy
                  "-fcover.", "_fcover.", "-fcover_", "_fcover_")
    lai_kw     = ("_lai_", "_lai.", "-lai.", "-lai_",
                  "leafareaindex", "leaf_area_index")

    # Files to skip — error/uncertainty, date, quality, partition, thumbnail
    skip_kw    = ("-date.", "_date.", "-bitmask", "_bitmask",
                  "-fpar.", "_fpar.", "-mask.", "_mask.",
                  # NRCAN uncertainty/auxiliary rasters
                  "errorfcover", "errorlai", "errorfpar",
                  "-partition.", "_partition.",
                  "-qc.", "_qc.", "thumbnail")

    raster_ext = {".tif", ".tiff", ".img", ".vrt", ".nc"}

    try:
        for fname in sorted(os.listdir(folder_path)):  # sorted → deterministic
            flower = fname.lower()
            ext    = os.path.splitext(flower)[1]
            if ext not in raster_ext:
                continue
            # Skip auxiliary rasters (date of acquisition, bitmask, fPAR)
            if any(k in flower for k in skip_kw):
                continue
            fpath = os.path.join(folder_path, fname)
            if "height" not in found and any(k in flower for k in height_kw):
                found["height"] = fpath
            elif "closure" not in found and any(k in flower for k in closure_kw):
                found["closure"] = fpath
            elif "lai" not in found and any(k in flower for k in lai_kw):
                found["lai"] = fpath
    except Exception:
        pass

    return found


def _classify_canada_bio_files(file_list):
    """
    Classify a list of file paths into Canada Bio roles (height/closure/lai).

    Uses the same keyword logic as _scan_canada_bio_folder() but operates on
    an explicit list of paths rather than scanning a directory.  This lets the
    user select LAI + fCOVER (or any combination of VH / CC / LAI / fCOVER)
    directly in the multiValue raster parameter instead of pointing to a folder.

    Returns dict with keys: 'height', 'closure', 'lai'  (only those found).
    """
    height_kw  = ("_vh_", "_vh.", "-vh.", "-vh_",
                  "canopyheight", "canopy_height",
                  "forestheight", "forest_height",
                  "treeheight",   "tree_height",
                  "vegheight",    "veg_height")
    closure_kw = ("_cc_", "_cc.", "-cc.", "-cc_",
                  "canopyclosure", "canopy_closure",
                  "canopycover",   "canopy_cover",
                  # fCOVER = Fraction of Vegetation Cover — NRCAN canopy proxy
                  "-fcover.", "_fcover.", "-fcover_", "_fcover_")
    lai_kw     = ("_lai_", "_lai.", "-lai.", "-lai_",
                  "leafareaindex", "leaf_area_index")
    skip_kw    = ("-date.", "_date.", "-bitmask", "_bitmask",
                  "-fpar.", "_fpar.", "-mask.", "_mask.",
                  "errorfcover", "errorlai", "errorfpar",
                  "-partition.", "_partition.",
                  "-qc.", "_qc.", "thumbnail")

    found = {}
    for fpath in file_list:
        flower = os.path.basename(str(fpath)).lower()
        if any(k in flower for k in skip_kw):
            continue
        if "height" not in found and any(k in flower for k in height_kw):
            found["height"] = fpath
        elif "closure" not in found and any(k in flower for k in closure_kw):
            found["closure"] = fpath
        elif "lai" not in found and any(k in flower for k in lai_kw):
            found["lai"] = fpath
    return found


def detect_veg_source_type(raster_path):
    """
    Identify which vegetation/land-cover dataset a path refers to.

    Detection hierarchy
    ───────────────────
    0. Folder path → check for Canada Biophysical raster patterns
    1. Filename hints  (fast, zero I/O)
    2. Pixel-type check  (float raster → likely GEDI continuous height)
    3. Pixel-value fingerprinting  (reads raster attribute table or numpy)
       a. Any value > 126          → CGLS-LC100
       b. Values ⊆ ESA codes       → ESA WorldCover
       c. NLCD signature codes     → NLCD
       d. Values 0–17              → warn MODIS, use Generic

    Returns (source_constant, detection_note) tuple.
    """
    if not raster_path:
        return SOURCE_GENERIC, "No path supplied"

    path_str   = str(raster_path)
    name_lower = os.path.basename(path_str).lower()

    # ── 0. Folder → Canada Bio? ───────────────────────────────────────────────
    if os.path.isdir(path_str):
        bio = _scan_canada_bio_folder(path_str)
        if "height" in bio or "closure" in bio:
            found_list = sorted(bio.keys())
            return (SOURCE_CANADA_BIO,
                    f"Detected from folder contents — biophysical rasters found: "
                    f"{found_list}")
        return (SOURCE_GENERIC,
                "Folder supplied but no recognised biophysical rasters found. "
                "Expected files containing 'VH', 'CC', or 'LAI' in their names.")

    # ── 1. Filename hints ─────────────────────────────────────────────────────

    # NRCAN Canada Biophysical Parameters: vegetation-YYYY-VH/CC/LAI.tif
    # Must check BEFORE generic keyword checks to avoid misclassification.
    _nrcan_pat = re.search(r'vegetation[-_]\d{4}[-_]', name_lower)
    if _nrcan_pat:
        # Files that are NOT vegetation parameters — reject with clear guidance
        _bad_suffixes = ("-date.", "_date.", "-bitmask", "_bitmask",
                         "-fpar.", "_fpar.", "-mask.", "_mask.")
        if any(s in name_lower for s in _bad_suffixes):
            suffix = name_lower.split(_nrcan_pat.group())[-1].split(".")[0].upper()
            return (SOURCE_GENERIC,
                    f"⚠ NRCAN '{suffix}' file selected — this raster contains "
                    f"{'acquisition dates' if 'date' in name_lower else 'quality/auxiliary data'}, "
                    "NOT vegetation parameters.\n"
                    "  Select one of these instead:\n"
                    "    vegetation-YYYY-VH.tif   (Vegetation Height → stemDiameter)\n"
                    "    vegetation-YYYY-CC.tif   (Canopy Closure → treeSpacing)\n"
                    "    vegetation-YYYY-LAI.tif  (Leaf Area Index → VTI)\n"
                    "  OR: use the 'Biophysical Rasters Folder' parameter and point\n"
                    "  it at the whole folder — VH + CC + LAI will be combined.")
        # VH / CC / LAI files → Canada Bio
        _good_suffixes = ("-vh.", "_vh.", "-cc.", "_cc.", "-lai.", "_lai.")
        if any(s in name_lower for s in _good_suffixes):
            return (SOURCE_CANADA_BIO,
                    "Detected from filename (NRCAN Canada Biophysical pattern). "
                    "Sibling VH / CC / LAI rasters in the same folder will be "
                    "combined automatically.")
        # Other vegetation-YYYY-*.tif files → treat as Canada Bio best-effort
        return (SOURCE_CANADA_BIO,
                "Detected from filename (NRCAN Canada Biophysical pattern — "
                "unrecognised suffix; will attempt to scan folder for VH/CC/LAI).")

    # DMTI / CanMap land-use (Canada) — vector land-use product.
    if ("dmti" in name_lower or "canmap" in name_lower or "_lur" in name_lower
            or name_lower.startswith("lur") or "land_use" in name_lower
            or "landuse" in name_lower):
        return (SOURCE_DMTI,
                "Detected from filename (DMTI / CanMap land-use pattern). "
                "Vector land use is rasterised on its land-use code field; "
                "unrecognised classes fall back to keyword classification.")

    if "worldcover" in name_lower or "esa_wc" in name_lower or "esawc" in name_lower:
        return SOURCE_ESA,  "Detected from filename (ESA WorldCover pattern)"
    if "nlcd" in name_lower:
        return SOURCE_NLCD, "Detected from filename (NLCD pattern)"
    if "cgls" in name_lower or "lc100" in name_lower:
        return SOURCE_CGLS, "Detected from filename (CGLS-LC100 pattern)"
    if ("gedi" in name_lower or "canopy_height" in name_lower
            or "canopyheight" in name_lower or "_chm" in name_lower
            or "forest_height" in name_lower
            or "glad" in name_lower or "_gfh" in name_lower
            or "forestheight" in name_lower or "treeheight" in name_lower):
        return (SOURCE_GEDI,
                "Detected from filename (GEDI / GLAD / canopy height model pattern)")
    if "mcd12" in name_lower or "modis" in name_lower or "viirs" in name_lower:
        return (SOURCE_GENERIC,
                "MODIS/VIIRS detected (≥250 m resolution). "
                "Resolution too coarse for CCM vehicle passability analysis. "
                "Use ESA WorldCover 10 m instead.")

    # ── 2. Float raster → GEDI or continuous height ───────────────────────────
    _, mn, mx, is_float = _get_raster_info(path_str)
    if is_float and mn is not None:
        if 0 <= mn and mx <= 80:
            return (SOURCE_GEDI,
                    f"Detected from pixel type (float, range {mn:.1f}–{mx:.1f} m) "
                    "— consistent with continuous canopy height model (GEDI/CHM)")
        # Float but outside expected height range — still likely continuous
        return (SOURCE_GENERIC,
                f"Float raster (range {mn:.1f}–{mx:.1f}) but outside expected "
                "0–80 m canopy height range; falling back to Generic")

    # ── 3. Integer pixel-value fingerprinting ─────────────────────────────────
    unique = _get_unique_values(path_str)
    if not unique:
        return SOURCE_GENERIC, "Could not read pixel values — falling back to Generic"

    # Remove common nodata / fill values before scoring
    clean = unique - {0, 255, 256, -9999, 65535}
    if not clean:
        clean = unique

    max_val = max(clean) if clean else 0

    # (a) CGLS-LC100: 3-digit forest codes 111–126 are unique to this dataset
    if max_val > 126 or any(111 <= v <= 126 for v in clean):
        return (SOURCE_CGLS,
                f"Detected from pixel values — max={max_val}, "
                "3-digit forest sub-class codes found (CGLS-LC100)")

    # (b) ESA WorldCover: all codes multiples of 10 or 95, range 10–100
    if max_val <= 100:
        esa_overlap = clean & _ESA_CODES
        if len(esa_overlap) >= max(1, len(clean) * 0.4):
            non_esa = {v for v in clean if v % 10 != 0 and v != 95}
            if len(non_esa) <= 1:
                return (SOURCE_ESA,
                        f"Detected from pixel values — codes match ESA WorldCover "
                        f"({sorted(esa_overlap)})")

    # (c) NLCD: distinctive codes
    nlcd_signature = {11, 21, 22, 23, 24, 31, 41, 42, 43, 52, 71, 81, 82, 90}
    if clean & nlcd_signature:
        return (SOURCE_NLCD,
                f"Detected from pixel values — NLCD signature codes found "
                f"({sorted(clean & nlcd_signature)})")

    # (d) Small integer range consistent with MODIS — warn
    if max_val <= 17 and min(clean) >= 0:
        return (SOURCE_GENERIC,
                f"Pixel values 0–{max_val} are consistent with MODIS IGBP, "
                "but MODIS (≥250 m) is too coarse for CCM analysis. "
                "Use ESA WorldCover 10 m for reliable results.")

    # (e) Integer height raster — GLAD Global Forest Canopy Height or similar
    # Signature: many unique integer values (not sparse class codes) in 0–80 m range.
    # GLAD/GFH: U8, values 0–60 m, ~61 unique values.
    # Class-code rasters typically have ≤30 unique values; height rasters have many more.
    min_val_clean = min(clean) if clean else 0
    if (1 <= max_val <= 80
            and min_val_clean >= 0
            and len(clean) > 20):
        return (SOURCE_GEDI,
                f"Detected from pixel values — integer range {min_val_clean}–{max_val} m "
                f"with {len(clean)} unique values; consistent with integer canopy height "
                "raster (e.g. GLAD/GFH 30 m, NLMR CHM). "
                "Will be reclassified into 6 height bands.")

    return (SOURCE_GENERIC,
            f"Could not fingerprint dataset (unique values: {sorted(clean)[:20]}); "
            "using Generic fallback — all polygons will receive gap-fill defaults")

# =============================================================================
# CRS GUARD  (self-contained; mirrors _ensure_projected_crs in soil preprocessor)
# =============================================================================

def _ensure_projected_crs(output_fc, reference_fc=None, messages=None):
    """
    If output_fc is in a Geographic CRS, auto-reproject to a Projected CRS.

    Target CRS is taken from reference_fc (the Analysis Extent) when available.
    Falls back to WGS 1984 Web Mercator Auxiliary Sphere if no reference.

    Reprojects in-place:  Project → Delete original → Rename projected copy.
    """
    def _msg(txt, warn=False):
        if messages:
            if warn:
                messages.addWarningMessage(txt)
            else:
                messages.addMessage(txt)
        else:
            print(txt)

    try:
        sr = arcpy.Describe(output_fc).spatialReference
    except Exception as exc:
        _msg(f"[VegPreprocess] CRS check failed: {exc}", warn=True)
        return output_fc

    if sr.type != "Geographic":
        return output_fc   # already projected — nothing to do

    _msg(f"[VegPreprocess] Output is in Geographic CRS ({sr.name}). "
         "Auto-reprojecting to Projected CRS …")

    # Determine target CRS
    target_sr = None
    if reference_fc and arcpy.Exists(str(reference_fc)):
        try:
            ref_sr = arcpy.Describe(reference_fc).spatialReference
            if ref_sr.type == "Projected":
                target_sr = ref_sr
                _msg(f"[VegPreprocess]   Target CRS: {ref_sr.name} "
                     "(from Analysis Extent)")
        except Exception:
            pass

    if target_sr is None:
        # Fallback: Web Mercator
        target_sr = arcpy.SpatialReference(3857)
        _msg("[VegPreprocess]   No projected Analysis Extent found. "
             "Using WGS 1984 Web Mercator Auxiliary Sphere (EPSG:3857).",
             warn=True)

    # Build a temporary path for the projected copy
    out_str  = str(output_fc)
    proj_tmp = out_str + "_proj_tmp"
    if arcpy.Exists(proj_tmp):
        arcpy.management.Delete(proj_tmp)

    try:
        arcpy.management.Project(output_fc, proj_tmp, target_sr)
        arcpy.management.Delete(output_fc)
        arcpy.management.Rename(proj_tmp, output_fc)
        _msg(f"[VegPreprocess]   Reprojection complete → {output_fc}")
    except Exception as exc:
        _msg(f"[VegPreprocess] Reprojection failed: {exc}\n"
             "  Manual fix: Data Management → Projections → Project\n"
             f"  Input: {output_fc}\n"
             f"  Target CRS: {target_sr.name}", warn=True)
        # Clean up failed temp if it exists
        if arcpy.Exists(proj_tmp):
            try:
                arcpy.management.Delete(proj_tmp)
            except Exception:
                pass

    return output_fc

# =============================================================================
# CORE PROCESSING
# =============================================================================

def _msg(messages, text, warn=False, error=False):
    """Safe message helper — works inside and outside arcpy tool context."""
    if messages:
        if error:
            messages.addErrorMessage(text)
        elif warn:
            messages.addWarningMessage(text)
        else:
            messages.addMessage(text)
    else:
        print(text)


# =============================================================================
# GEDI CANOPY HEIGHT PROCESSING
# =============================================================================

def _reclass_height_raster(height_ras_path, extent_fc=None, messages=None):
    """
    Reclassify a continuous canopy-height raster (metres) into GEDI_HEIGHT_BINS.

    Steps
    ─────
    1. Optionally clip to extent_fc (ExtractByMask)
    2. arcpy.sa.Reclassify with RemapRange → integer bin codes 1–6
    3. Save to scratchGDB

    Returns (classified_raster_path, lookup_dict) where lookup_dict maps
    bin_code → (VTI, spacing, diam, label).
    Returns (None, {}) on failure.
    """
    scratch = arcpy.env.scratchGDB or arcpy.env.scratchFolder or ""

    # ── Optional clip ─────────────────────────────────────────────────────────
    work_ras = height_ras_path
    if extent_fc and arcpy.Exists(str(extent_fc)):
        try:
            arcpy.env.mask = extent_fc
            clipped = arcpy.sa.ExtractByMask(height_ras_path, extent_fc)
            clip_path = os.path.join(scratch, "ccm_gedi_clip_tmp")
            if arcpy.Exists(clip_path):
                arcpy.management.Delete(clip_path)
            clipped.save(clip_path)
            work_ras = clip_path
            _msg(messages, "[VegPreprocess/GEDI] Raster clipped to Analysis Extent.")
        except Exception as exc:
            _msg(messages,
                 f"[VegPreprocess/GEDI] Clip failed ({exc}); using full raster.",
                 warn=True)

    # ── Build RemapRange from GEDI bin definitions ────────────────────────────
    reclass_map = arcpy.sa.RemapRange(GEDI_RECLASS_RANGES)

    classified_path = os.path.join(scratch, "ccm_gedi_reclass_tmp")
    try:
        if arcpy.Exists(classified_path):
            arcpy.management.Delete(classified_path)
        _msg(messages, "[VegPreprocess/GEDI] Reclassifying height into 6 bands …")
        classified = arcpy.sa.Reclassify(work_ras, "Value", reclass_map, "NODATA")
        classified.save(classified_path)
        _msg(messages, "[VegPreprocess/GEDI] Reclassification complete.")
    except Exception as exc:
        _msg(messages,
             f"[VegPreprocess/GEDI] Reclassify failed: {exc}", error=True)
        return None, {}

    # Build lookup (bin code → (VTI, spacing, diam, label))
    bin_lookup = {k: v[:4] for k, v in LOOKUP_GEDI_BINS.items()}
    return classified_path, bin_lookup


def preprocess_gedi(raster_path, output_fc, extent_fc=None,
                    gap_vti=0.05, gap_spacing=0.0, gap_diam=0.0,
                    messages=None):
    """
    Convert a GEDI / CHM canopy-height raster to a CCM vegetation FC.

    Pipeline
    ────────
    1. Clip to extent (optional)
    2. Reclassify continuous height → 6 integer bands
    3. RasterToPolygon on classified raster
    4. Apply allometric lookup per band
    5. CRS guard

    The allometric model used (Jucker et al. 2017) is calibrated on pan-
    temperate broadleaf and needleleaf trees.  In boreal or tropical zones
    the stemDiameter estimates will have ±20–30 % error; VTI and treeSpacing
    are robust across biomes since they are based on canopy structure.
    """
    _msg(messages, "[VegPreprocess/GEDI] Starting GEDI Canopy Height processing …")

    classified_path, bin_lookup = _reclass_height_raster(
        raster_path, extent_fc, messages)

    if not classified_path:
        return VegPreprocessResult()

    result = _apply_veg_lookup(
        raster_path  = classified_path,
        lookup       = bin_lookup,
        source_name  = SOURCE_GEDI,
        output_fc    = output_fc,
        extent_fc    = None,          # already clipped inside _reclass
        gap_vti      = gap_vti,
        gap_spacing  = gap_spacing,
        gap_diam     = gap_diam,
        messages     = messages,
    )

    # Clean temp raster
    try:
        arcpy.management.Delete(classified_path)
    except Exception:
        pass

    return result


# =============================================================================
# CANADA BIOPHYSICAL PARAMETERS PROCESSING
# =============================================================================

def preprocess_canada_bio(bio_folder, output_fc, extent_fc=None,
                          gap_vti=0.05, gap_spacing=0.0, gap_diam=0.0,
                          bio_files=None, messages=None):
    """
    Convert NRCAN Canada Biophysical Parameter rasters to a CCM vegetation FC.

    Detection priority
    ──────────────────
    1. Canopy Height (VH_* / CanopyHeight_*)   — primary geometry source
       → Reclassify into 6 height bands → apply GEDI lookup
    2. Canopy Closure (CC_* / CanopyClosure_*) — used to refine treeSpacing
       → spacing = max(2.0, base_spacing × (1 − CC/100))
    3. LAI (*LAI*)                             — used to refine VTI
       → VTI = min(1.0, LAI / 6.0)  [LAI 6 = dense closed canopy]

    If no Height raster is found, falls back to Closure or LAI as the
    primary source with simplified VTI-only mapping.

    Parameters
    ──────────
    bio_folder : str  — folder containing NRCAN rasters (scanned when bio_files is None)
    bio_files  : dict — pre-classified {role: path} dict (overrides folder scan when supplied).
                        Roles: 'height', 'closure', 'lai'.  Pass this when the user selected
                        individual files (LAI + fCOVER etc.) via the multiValue raster param.
    """
    _msg(messages,
         "[VegPreprocess/CanadaBio] Starting Canada Biophysical "
         "Parameters processing …")

    # Use pre-classified file dict when supplied (user selected files directly),
    # otherwise scan the folder for recognised raster names.
    if bio_files:
        bio = bio_files
        _msg(messages,
             f"[VegPreprocess/CanadaBio] Using pre-classified files: "
             f"{sorted(bio.keys())}")
    else:
        _msg(messages, f"[VegPreprocess/CanadaBio] Folder: {bio_folder}")
        bio = _scan_canada_bio_folder(bio_folder)
    if not bio:
        _msg(messages,
             "[VegPreprocess/CanadaBio] No recognised biophysical rasters found. "
             "Expected files containing 'VH', 'CC', or 'LAI' in names.",
             error=True)
        return VegPreprocessResult()

    _msg(messages,
         f"[VegPreprocess/CanadaBio] Found rasters: {sorted(bio.keys())}")

    # ── Primary processing: canopy height ─────────────────────────────────────
    if "height" in bio:
        _msg(messages, f"[VegPreprocess/CanadaBio] Height raster: {bio['height']}")
        classified_path, bin_lookup = _reclass_height_raster(
            bio["height"], extent_fc, messages)
        if not classified_path:
            return VegPreprocessResult()

        result = _apply_veg_lookup(
            raster_path  = classified_path,
            lookup       = bin_lookup,
            source_name  = SOURCE_CANADA_BIO,
            output_fc    = output_fc,
            extent_fc    = None,
            gap_vti      = gap_vti,
            gap_spacing  = gap_spacing,
            gap_diam     = gap_diam,
            messages     = messages,
        )
        try:
            arcpy.management.Delete(classified_path)
        except Exception:
            pass

        if not result.success:
            return result

        # ── Refine treeSpacing using Canopy Closure ───────────────────────────
        if "closure" in bio and arcpy.Exists(output_fc):
            _msg(messages,
                 f"[VegPreprocess/CanadaBio] Refining treeSpacing from "
                 f"Canopy Closure: {bio['closure']}")
            try:
                scratch = arcpy.env.scratchGDB or arcpy.env.scratchFolder or ""
                cc_ras  = arcpy.Raster(bio["closure"])
                # If extent_fc supplied, clip closure raster before sampling
                if extent_fc and arcpy.Exists(str(extent_fc)):
                    arcpy.env.mask = extent_fc
                    cc_ras = arcpy.sa.ExtractByMask(cc_ras, extent_fc)

                # Sample CC raster value at centroid of each polygon
                # and adjust spacing: spacing_adj = spacing × (1 − CC/100)
                cc_sample_path = os.path.join(
                    scratch or os.path.dirname(output_fc),
                    "ccm_bio_cc_sample_tmp"
                )
                if arcpy.Exists(cc_sample_path):
                    arcpy.management.Delete(cc_sample_path)
                arcpy.sa.ZonalStatisticsAsTable(
                    output_fc, "OBJECTID", cc_ras, cc_sample_path,
                    "DATA", "MEAN")

                # Join mean CC back onto output FC and update spacing
                arcpy.management.JoinField(
                    output_fc, "OBJECTID", cc_sample_path, "OBJECTID_1", ["MEAN"])

                with arcpy.da.UpdateCursor(
                        output_fc, ["treeSpacing", "MEAN"]) as cur:
                    for row in cur:
                        base_spacing = row[0] or 0.0
                        cc_mean      = row[1]
                        if cc_mean is not None and base_spacing > 0:
                            cc_frac  = max(0.0, min(100.0, float(cc_mean))) / 100.0
                            # denser closure → smaller spacing, floor at 2 m
                            row[0] = max(2.0, base_spacing * (1.0 - cc_frac * 0.6))
                        cur.updateRow(row)

                # Drop the temporary join field
                arcpy.management.DeleteField(output_fc, "MEAN")
                arcpy.management.Delete(cc_sample_path)
                _msg(messages,
                     "[VegPreprocess/CanadaBio] treeSpacing refined from "
                     "Canopy Closure.")
            except Exception as exc:
                _msg(messages,
                     f"[VegPreprocess/CanadaBio] Closure refinement failed "
                     f"({exc}); spacing values kept from height bins.", warn=True)

        # ── Refine VTI using LAI ──────────────────────────────────────────────
        if "lai" in bio and arcpy.Exists(output_fc):
            _msg(messages,
                 f"[VegPreprocess/CanadaBio] Refining VTI from LAI: "
                 f"{bio['lai']}")
            try:
                scratch = arcpy.env.scratchGDB or arcpy.env.scratchFolder or ""
                lai_ras = arcpy.Raster(bio["lai"])
                if extent_fc and arcpy.Exists(str(extent_fc)):
                    arcpy.env.mask = extent_fc
                    lai_ras = arcpy.sa.ExtractByMask(lai_ras, extent_fc)

                lai_sample = os.path.join(
                    scratch or os.path.dirname(output_fc),
                    "ccm_bio_lai_sample_tmp"
                )
                if arcpy.Exists(lai_sample):
                    arcpy.management.Delete(lai_sample)
                arcpy.sa.ZonalStatisticsAsTable(
                    output_fc, "OBJECTID", lai_ras, lai_sample, "DATA", "MEAN")
                arcpy.management.JoinField(
                    output_fc, "OBJECTID", lai_sample, "OBJECTID_1", ["MEAN"])

                with arcpy.da.UpdateCursor(
                        output_fc,
                        ["vegetationTrafficImpact", "MEAN"]) as cur:
                    for row in cur:
                        lai_mean = row[1]
                        if lai_mean is not None:
                            row[0] = min(1.0, float(lai_mean) / 6.0)
                        cur.updateRow(row)

                arcpy.management.DeleteField(output_fc, "MEAN")
                arcpy.management.Delete(lai_sample)
                _msg(messages,
                     "[VegPreprocess/CanadaBio] VTI refined from LAI.")
            except Exception as exc:
                _msg(messages,
                     f"[VegPreprocess/CanadaBio] LAI refinement failed "
                     f"({exc}); VTI kept from height bins.", warn=True)

        result.source_detected = SOURCE_CANADA_BIO
        return result

    # ── Fallback: no height raster — use closure or LAI for VTI only ─────────
    primary_ras = bio.get("closure") or bio.get("lai")
    if not primary_ras:
        _msg(messages,
             "[VegPreprocess/CanadaBio] No usable raster found.", error=True)
        return VegPreprocessResult()

    _msg(messages,
         f"[VegPreprocess/CanadaBio] No height raster; using "
         f"{'Canopy Closure' if 'closure' in bio else 'LAI'} as primary.",
         warn=True)

    # Use Generic lookup (empty) — polygons get gap-fill defaults
    return _apply_veg_lookup(
        raster_path  = primary_ras,
        lookup       = {},
        source_name  = SOURCE_CANADA_BIO,
        output_fc    = output_fc,
        extent_fc    = extent_fc,
        gap_vti      = gap_vti,
        gap_spacing  = gap_spacing,
        gap_diam     = gap_diam,
        messages     = messages,
    )


def _apply_veg_lookup(raster_path, lookup, source_name, output_fc,
                      extent_fc=None, gap_vti=0.2, gap_spacing=0.0,
                      gap_diam=0.0, messages=None):
    """
    Convert a land-cover raster to a CCM vegetation polygon FC.

    Steps
    ─────
    1. Clip raster to extent_fc (if supplied)
    2. RasterToPolygon  (gridcode = original class code)
    3. Add CCM fields   (vegClass, vegetationTrafficImpact, treeSpacing, stemDiameter)
    4. Populate via lookup table; gap-fill unmapped classes
    5. Return VegPreprocessResult

    Parameters
    ──────────
    raster_path  : str   — path to input land-cover raster
    lookup       : dict  — {class_code: (VTI, spacing_m, diam_cm, description)}
    source_name  : str   — human-readable dataset name for logging
    output_fc    : str   — destination polygon FC path
    extent_fc    : str   — Analysis Extent polygon (for clipping, optional)
    gap_vti      : float — VTI for unmapped/gap classes
    gap_spacing  : float — treeSpacing for unmapped classes
    gap_diam     : float — stemDiameter for unmapped classes
    messages     : GP messages object (or None)

    Returns VegPreprocessResult.
    """
    result = VegPreprocessResult()

    _msg(messages, f"[VegPreprocess] Dataset   : {source_name}")
    _msg(messages, f"[VegPreprocess] Input     : {raster_path}")
    _msg(messages, f"[VegPreprocess] Output    : {output_fc}")

    # ── Step 1: Clip to extent ────────────────────────────────────────────────
    work_ras = raster_path
    clip_tmp  = None
    if extent_fc and arcpy.Exists(str(extent_fc)):
        try:
            arcpy.env.mask = extent_fc
            clipped = arcpy.sa.ExtractByMask(raster_path, extent_fc)
            clip_tmp = os.path.join(
                arcpy.env.scratchGDB or arcpy.env.scratchFolder or
                os.path.dirname(output_fc),
                "ccm_veg_clip_tmp"
            )
            if arcpy.Exists(clip_tmp):
                arcpy.management.Delete(clip_tmp)
            clipped.save(clip_tmp)
            work_ras = clip_tmp
            _msg(messages, "[VegPreprocess] Raster clipped to Analysis Extent.")
        except Exception as exc:
            _msg(messages,
                 f"[VegPreprocess] Clip to extent failed ({exc}); "
                 "processing full raster.", warn=True)

    # ── Step 2: RasterToPolygon ───────────────────────────────────────────────
    poly_tmp = os.path.join(
        arcpy.env.scratchGDB or os.path.dirname(output_fc),
        "ccm_veg_poly_tmp"
    )
    try:
        if arcpy.Exists(poly_tmp):
            arcpy.management.Delete(poly_tmp)
        _msg(messages, "[VegPreprocess] Running RasterToPolygon …")
        arcpy.conversion.RasterToPolygon(
            in_raster             = work_ras,
            out_polygon_features  = poly_tmp,
            simplify              = "NO_SIMPLIFY",
            raster_field          = "Value",
            create_multipart_features = "SINGLE_OUTER_PART",
        )
        # Rename gridcode field (ArcGIS sometimes names it 'gridcode' or 'Value')
        # Ensure 'gridcode' exists — RasterToPolygon always creates it.
        n_poly = int(arcpy.management.GetCount(poly_tmp).getOutput(0))
        _msg(messages, f"[VegPreprocess] {n_poly:,} polygons created.")
    except Exception as exc:
        _msg(messages, f"[VegPreprocess] RasterToPolygon failed: {exc}", error=True)
        return result

    # ── Step 3: Copy to output and add CCM fields ─────────────────────────────
    try:
        if arcpy.Exists(output_fc):
            arcpy.management.Delete(output_fc)
        arcpy.management.CopyFeatures(poly_tmp, output_fc)

        # vegClass
        arcpy.management.AddField(output_fc, "vegClass",
                                  "TEXT", field_length=80)
        # vegetationTrafficImpact
        arcpy.management.AddField(output_fc, "vegetationTrafficImpact", "FLOAT")
        # treeSpacing
        arcpy.management.AddField(output_fc, "treeSpacing", "FLOAT")
        # stemDiameter
        arcpy.management.AddField(output_fc, "stemDiameter", "FLOAT")

        _msg(messages, "[VegPreprocess] CCM fields added.")
    except Exception as exc:
        _msg(messages, f"[VegPreprocess] Field setup failed: {exc}", error=True)
        return result

    # ── Step 4: Populate via lookup ───────────────────────────────────────────
    n_mapped     = 0
    n_gap_filled = 0
    n_unmapped   = 0
    unknown_codes = set()

    fields = ["gridcode", "vegClass",
              "vegetationTrafficImpact", "treeSpacing", "stemDiameter"]

    try:
        with arcpy.da.UpdateCursor(output_fc, fields) as cur:
            for row in cur:
                gc = row[0]
                try:
                    code = int(gc) if gc is not None else None
                except (TypeError, ValueError):
                    code = None

                if code is None:
                    row[1] = "No data"
                    row[2] = gap_vti
                    row[3] = gap_spacing
                    row[4] = gap_diam
                    n_gap_filled += 1
                elif code in lookup:
                    vti, spacing, diam, desc = lookup[code]
                    row[1] = desc
                    row[2] = vti
                    row[3] = spacing
                    row[4] = diam
                    n_mapped += 1
                else:
                    row[1] = f"Unknown class {code}"
                    row[2] = gap_vti
                    row[3] = gap_spacing
                    row[4] = gap_diam
                    n_gap_filled += 1
                    unknown_codes.add(code)
                    n_unmapped += 1

                cur.updateRow(row)
    except Exception as exc:
        _msg(messages, f"[VegPreprocess] Lookup population failed: {exc}", error=True)
        return result

    # ── Summary ───────────────────────────────────────────────────────────────
    _msg(messages, "")
    _msg(messages, "─" * 50)
    _msg(messages, f"[VegPreprocess] COMPLETE  — {source_name}")
    _msg(messages, f"  Polygons total   : {n_poly:>8,}")
    _msg(messages, f"  Mapped (lookup)  : {n_mapped:>8,}  "
         f"({100*n_mapped/max(n_poly,1):.1f}%)")
    _msg(messages, f"  Gap-filled       : {n_gap_filled:>8,}  "
         f"({100*n_gap_filled/max(n_poly,1):.1f}%)")
    if unknown_codes:
        _msg(messages,
             f"  Unknown codes    : {sorted(unknown_codes)}", warn=True)
        _msg(messages,
             "    → These classes received the gap-fill defaults "
             f"(VTI={gap_vti}, spacing={gap_spacing} m, diam={gap_diam} cm).",
             warn=True)
    _msg(messages, "─" * 50)

    # ── Cleanup temp rasters / FC ─────────────────────────────────────────────
    for tmp in [clip_tmp, poly_tmp]:
        if tmp and arcpy.Exists(tmp):
            try:
                arcpy.management.Delete(tmp)
            except Exception:
                pass

    result.success         = True
    result.output_fc       = output_fc
    result.source_detected = source_name
    result.n_polygons      = n_poly
    result.n_mapped        = n_mapped
    result.n_gap_filled    = n_gap_filled
    result.n_unmapped      = n_unmapped
    return result


# =============================================================================
# PUBLIC ENTRY POINT
# =============================================================================

def preprocess_vegetation(raster_path, output_fc, extent_fc=None,
                          source_type=SOURCE_AUTO,
                          bio_folder=None,
                          bio_files=None,
                          gap_vti=0.2, gap_spacing=0.0, gap_diam=0.0,
                          messages=None):
    """
    Main dispatcher for the vegetation preprocessor.

    Parameters
    ──────────
    raster_path  : str   — path to input raster (class-code, height, or folder)
    output_fc    : str   — destination polygon FC (will be created/overwritten)
    extent_fc    : str   — Analysis Extent polygon FC (optional; clips + sets CRS)
    source_type  : str   — one of ALL_VEG_SOURCES; SOURCE_AUTO triggers detection
    bio_folder   : str   — Canada Biophysical folder (overrides raster_path for
                           SOURCE_CANADA_BIO; used when folder ≠ raster)
    bio_files    : dict  — pre-classified {role: path} for Canada Bio when the user
                           selected individual files (skips folder scan entirely)
    gap_vti      : float — VTI (0–1) for unmapped/gap polygons  (default 0.2)
    gap_spacing  : float — treeSpacing (m) for gap polygons      (default 0)
    gap_diam     : float — stemDiameter (cm) for gap polygons    (default 0)
    messages     : arcpy GP messages object (or None for console)

    Returns VegPreprocessResult.
    """
    # ── Resolve primary input path ────────────────────────────────────────────
    # Canada Bio: bio_folder takes priority; fall back to raster_path if folder
    primary_path = raster_path or ""
    if bio_folder and os.path.isdir(str(bio_folder)):
        primary_path = bio_folder
    elif raster_path and os.path.isdir(str(raster_path)):
        primary_path = raster_path   # user browsed to folder directly

    if not primary_path or not arcpy.Exists(str(primary_path)):
        _msg(messages,
             f"[VegPreprocess] Input not found: {primary_path}", error=True)
        return VegPreprocessResult()

    # ── Auto-detect source ────────────────────────────────────────────────────
    if not source_type or source_type == SOURCE_AUTO:
        source_type, detect_note = detect_veg_source_type(primary_path)
        _msg(messages, f"[VegPreprocess] Auto-detected: {source_type}")
        _msg(messages, f"[VegPreprocess]   {detect_note}")
    else:
        _msg(messages, f"[VegPreprocess] Source (user-specified): {source_type}")

    # ── Dispatch to appropriate processor ────────────────────────────────────
    if source_type == SOURCE_GEDI:
        result = preprocess_gedi(
            raster_path = primary_path,
            output_fc   = output_fc,
            extent_fc   = extent_fc,
            gap_vti     = gap_vti,
            gap_spacing = gap_spacing,
            gap_diam    = gap_diam,
            messages    = messages,
        )

    elif source_type == SOURCE_CANADA_BIO:
        # Resolve folder: bio_folder > primary_path if it's a dir > parent of raster
        # This allows the user to select just the VH file; sibling CC/LAI are found.
        if bio_folder and os.path.isdir(str(bio_folder)):
            folder = bio_folder
        elif os.path.isdir(str(primary_path)):
            folder = primary_path
        else:
            folder = os.path.dirname(str(primary_path))
            _msg(messages,
                 f"[VegPreprocess] Canada Bio: scanning folder for VH/CC/LAI "
                 f"siblings: {folder}")
        result = preprocess_canada_bio(
            bio_folder  = folder,
            output_fc   = output_fc,
            extent_fc   = extent_fc,
            gap_vti     = gap_vti,
            gap_spacing = gap_spacing,
            gap_diam    = gap_diam,
            bio_files   = bio_files,   # pre-classified dict overrides folder scan
            messages    = messages,
        )

    else:
        # Class-code rasters: ESA, NLCD, CGLS, Generic
        if source_type == SOURCE_ESA:
            lookup = LOOKUP_ESA
        elif source_type == SOURCE_NLCD:
            lookup = LOOKUP_NLCD
        elif source_type == SOURCE_CGLS:
            lookup = LOOKUP_CGLS
        elif source_type == SOURCE_DMTI:
            lookup = LOOKUP_DMTI
        else:
            lookup = {}
            _msg(messages,
                 "[VegPreprocess] Generic source: all polygons will receive "
                 "gap-fill defaults.  Consider specifying the source type manually.",
                 warn=True)

        result = _apply_veg_lookup(
            raster_path  = primary_path,
            lookup       = lookup,
            source_name  = source_type,
            output_fc    = output_fc,
            extent_fc    = extent_fc,
            gap_vti      = gap_vti,
            gap_spacing  = gap_spacing,
            gap_diam     = gap_diam,
            messages     = messages,
        )

    # ── CRS guard ─────────────────────────────────────────────────────────────
    if result.success and result.output_fc and arcpy.Exists(str(result.output_fc)):
        _ensure_projected_crs(result.output_fc, extent_fc, messages)

    return result


# =============================================================================
# MULTI-TILE MOSAIC HELPER
# =============================================================================

def _mosaic_rasters(raster_list, messages=None):
    """
    Mosaic a list of raster paths into a single temporary raster.

    Strategy
    ────────
    • 1 raster  → return it directly (no processing)
    • 2+ rasters → arcpy.management.MosaicToNewRaster → scratchGDB temp

    The pixel type is auto-detected from the first raster so that
    integer class-code rasters (ESA = U8) and float height rasters
    (GEDI = F32) are both handled correctly.

    Returns path to mosaicked raster, or None on failure.
    The caller is responsible for deleting the temp raster when done.
    """
    # Strip surrounding quotes ArcGIS sometimes adds around paths with spaces
    clean = [r.strip("'\"") for r in raster_list if r.strip("'\"")]
    if not clean:
        _msg(messages, "[VegPreprocess/Mosaic] No valid raster paths supplied.",
             error=True)
        return None
    if len(clean) == 1:
        return clean[0]   # single tile — nothing to mosaic

    _msg(messages,
         f"[VegPreprocess/Mosaic] Mosaicking {len(clean)} tiles …")
    for i, p in enumerate(clean, 1):
        _msg(messages, f"  Tile {i}: {os.path.basename(p)}")

    # Detect pixel type from first raster
    pt_raw, _, _, is_float = _get_raster_info(clean[0])
    pt_map = {
        "U1":  "1_BIT",
        "U2":  "2_BIT",
        "U4":  "4_BIT",
        "U8":  "8_BIT_UNSIGNED",
        "S8":  "8_BIT_SIGNED",
        "U16": "16_BIT_UNSIGNED",
        "S16": "16_BIT_SIGNED",
        "U32": "32_BIT_UNSIGNED",
        "S32": "32_BIT_SIGNED",
        "F32": "32_BIT_FLOAT",
        "F64": "64_BIT",
    }
    pixel_type = pt_map.get(pt_raw or "U8", "8_BIT_UNSIGNED")
    _msg(messages, f"[VegPreprocess/Mosaic] Pixel type: {pixel_type}")

    # Output destination
    scratch = (arcpy.env.scratchGDB
               or arcpy.env.scratchFolder
               or os.path.dirname(clean[0]))
    mosaic_name = "ccm_veg_mosaic_tmp"
    mosaic_path = os.path.join(scratch, mosaic_name)

    try:
        if arcpy.Exists(mosaic_path):
            arcpy.management.Delete(mosaic_path)

        arcpy.management.MosaicToNewRaster(
            input_rasters                    = clean,
            output_location                  = scratch,
            raster_dataset_name_with_extension = mosaic_name,
            coordinate_system_for_the_raster = "",
            pixel_type                       = pixel_type,
            cellsize                         = "",
            number_of_bands                  = 1,
            mosaic_method                    = "LAST",
            mosaic_colormap_mode             = "FIRST",
        )
        _msg(messages,
             f"[VegPreprocess/Mosaic] Mosaic complete "
             f"({len(clean)} tiles → {mosaic_path})")
        return mosaic_path

    except Exception as exc:
        _msg(messages,
             f"[VegPreprocess/Mosaic] MosaicToNewRaster failed: {exc}",
             error=True)
        return None


# =============================================================================
# ARCGIS TOOL CLASS
# =============================================================================

class CCMVegPreprocessTool:
    """
    ArcGIS Pro Tool: Pre-process Vegetation / Land-Cover Raster for CCM

    Appears in the CCM Tool Toolbox v0.46 as tool "0b. Pre-process Vegetation Data".
    Converts a land-cover GeoTIFF (ESA WorldCover, NLCD, CGLS-LC100, MODIS, or
    any integer raster) into a polygon FC with CCM vegetation fields.
    """

    def __init__(self):
        self.label              = "0b.  Pre-process Vegetation Data"
        self.description        = (
            "Converts a vegetation/land-cover raster (GeoTIFF, IMG, …) into a "
            "polygon Feature Class with the three CCM vegetation fields:\n"
            "  • vegetationTrafficImpact — resistance factor F2 (0=none → 1=impassable)\n"
            "  • treeSpacing — average gap between stems in metres (controls F3)\n"
            "  • stemDiameter — trunk diameter at breast height in cm (controls F3)\n\n"
            "Supported datasets (auto-detected):\n"
            "  CLASS-CODE RASTERS:\n"
            "    ESA WorldCover 10 m (recommended) · NLCD (US, 30 m) · "
            "CGLS-LC100 (100 m) · Generic\n"
            "  CONTINUOUS HEIGHT RASTERS (float metres):\n"
            "    NASA/GEDI Canopy Height  — reclassified into 6 height bands;\n"
            "    stemDiameter derived from allometric model (Jucker et al. 2017)\n"
            "  BIOPHYSICAL PARAMETER FOLDERS:\n"
            "    Canada Biophysical Parameters (NRCAN) — height + closure + LAI\n\n"
            "Note: MODIS/VIIRS (≥250 m) and NOAA VH (1 km) are not supported — "
            "resolution is too coarse to derive vehicle passability between trees."
        )
        self.canRunInBackground = False

    # =========================================================================
    def getParameterInfo(self):

        # ── p0: Source type override (auto-detect by default) ─────────────────
        p_source = arcpy.Parameter(
            displayName   = "Vegetation Data Source  (leave as Auto-Detect to "
                            "identify from pixel values)",
            name          = "source_type",
            datatype      = "GPString",
            parameterType = "Optional",
            direction     = "Input",
        )
        p_source.filter.type = "ValueList"
        p_source.filter.list = ALL_VEG_SOURCES
        p_source.value       = SOURCE_AUTO

        # ── p1: Input raster(s) — multiValue supports tiles AND Canada Bio files ──
        # NOTE: datatype must be a single type (not a list) for multiValue to work
        # correctly in the ArcGIS Pro UI.  DEFile accepts .tif/.img/etc. just fine.
        p_raster = arcpy.Parameter(
            displayName   = "Land-Cover / Biophysical Raster File(s)  — "
                            "select one file, multiple adjacent tiles (mosaicked), "
                            "or multiple Canada Bio files (LAI + fCOVER etc.)",
            name          = "raster_path",
            datatype      = "DEFile",
            parameterType = "Required",
            direction     = "Input",
            multiValue    = True,
        )

        # ── p2: Analysis Extent (optional clip polygon) ───────────────────────
        p_extent = arcpy.Parameter(
            displayName   = "Analysis Extent  (polygon FC — clips raster and "
                            "sets output CRS)",
            name          = "extent_fc",
            datatype      = "DEFeatureClass",
            parameterType = "Optional",
            direction     = "Input",
        )

        # ── p3: Output polygon FC ─────────────────────────────────────────────
        p_output = arcpy.Parameter(
            displayName   = "Output Vegetation Feature Class",
            name          = "output_fc",
            datatype      = "DEFeatureClass",
            parameterType = "Required",
            direction     = "Output",
        )

        # ── p4: Gap-fill VTI ─────────────────────────────────────────────────
        p_gap_vti = arcpy.Parameter(
            displayName   = "Gap-Fill VTI  (vegetationTrafficImpact for "
                            "unmapped classes, 0.0–1.0)",
            name          = "gap_vti",
            datatype      = "GPDouble",
            parameterType = "Optional",
            direction     = "Input",
            category      = "Gap-Fill Defaults",
        )
        p_gap_vti.value = 0.2

        # ── p5: Gap-fill tree spacing ─────────────────────────────────────────
        p_gap_spacing = arcpy.Parameter(
            displayName   = "Gap-Fill Tree Spacing  (metres; 0 = no trees)",
            name          = "gap_tree_spacing",
            datatype      = "GPDouble",
            parameterType = "Optional",
            direction     = "Input",
            category      = "Gap-Fill Defaults",
        )
        p_gap_spacing.value = 0.0

        # ── p6: Gap-fill stem diameter ────────────────────────────────────────
        p_gap_diam = arcpy.Parameter(
            displayName   = "Gap-Fill Stem Diameter  (cm; 0 = no trees)",
            name          = "gap_stem_diameter",
            datatype      = "GPDouble",
            parameterType = "Optional",
            direction     = "Input",
            category      = "Gap-Fill Defaults",
        )
        p_gap_diam.value = 0.0

        # ── p7: Canada Biophysical Parameters folder ──────────────────────────
        p_bio_folder = arcpy.Parameter(
            displayName   = "Biophysical Rasters Folder  [Canada Bio only — "
                            "folder containing VH, CC, LAI rasters from NRCAN]",
            name          = "bio_folder",
            datatype      = "DEFolder",
            parameterType = "Optional",
            direction     = "Input",
            category      = "Canada Biophysical Parameters (NRCAN)",
        )

        # ── p8: Detected source (derived display) ─────────────────────────────
        p_detected = arcpy.Parameter(
            displayName   = "Detected Source Type",
            name          = "detected_source",
            datatype      = "GPString",
            parameterType = "Derived",
            direction     = "Output",
        )

        return [p_source, p_raster, p_extent, p_output,
                p_gap_vti, p_gap_spacing, p_gap_diam, p_bio_folder, p_detected]

    # =========================================================================
    def updateParameters(self, parameters):
        """Live-update the Detected Source Type label as the user picks a raster."""
        p_source     = parameters[0]
        p_raster     = parameters[1]
        p_bio_folder = parameters[7]
        p_detected   = parameters[8]

        # Auto-detect when raster or bio_folder changes and source is still Auto
        primary_path = None
        if p_bio_folder.value and os.path.isdir(str(p_bio_folder.valueAsText or "")):
            primary_path = p_bio_folder.valueAsText
        elif p_raster.value:
            # multiValue: take first path in the semicolon list
            raw = p_raster.valueAsText or ""
            first = raw.split(";")[0].strip().strip("'\"")
            primary_path = first if first else None

        if primary_path and not p_source.altered:
            try:
                if arcpy.Exists(primary_path) or os.path.isdir(primary_path):
                    src, note = detect_veg_source_type(primary_path)
                    p_detected.value = f"{src} — {note}"
            except Exception:
                pass

    # =========================================================================
    def updateMessages(self, parameters):
        """Validate inputs and set informational / warning messages."""
        p_source     = parameters[0]
        p_raster     = parameters[1]
        p_extent     = parameters[2]
        p_gap_vti    = parameters[4]
        p_bio_folder = parameters[7]

        src_val = p_source.valueAsText or SOURCE_AUTO

        # Raster: validate each path in multivalue list
        if p_raster.value:
            raw_paths = p_raster.valueAsText or ""
            paths = [r.strip().strip("'\"") for r in raw_paths.split(";")
                     if r.strip().strip("'\"")]
            bad = [p for p in paths if not arcpy.Exists(p)]
            if bad:
                p_raster.setErrorMessage(
                    "Raster(s) not found:\n" + "\n".join(bad))
            elif len(paths) > 1:
                # Classify all files — if 2+ roles found, it's Canada Bio multi-file
                bio_candidate = _classify_canada_bio_files(paths)
                is_canada_bio_multi = (
                    src_val == SOURCE_CANADA_BIO
                    or len(bio_candidate) >= 2
                )
                if is_canada_bio_multi:
                    roles = sorted(bio_candidate.keys())
                    p_raster.setIDMessage("WARNING", 975,
                        f"{len(paths)} biophysical files selected — roles detected: "
                        f"{roles}. Files will be combined by role (not mosaicked).")
                else:
                    p_raster.setIDMessage("WARNING", 975,
                        f"{len(paths)} tiles selected — will be mosaicked "
                        "automatically before processing.")

        if (not p_raster.value and not p_bio_folder.value
                and src_val != SOURCE_CANADA_BIO):
            p_raster.setWarningMessage(
                "Provide one or more land-cover/height rasters, or select "
                "'Canada Biophysical Parameters' and supply the folder.")

        # Canada Bio source — guide user to supply folder
        if src_val == SOURCE_CANADA_BIO and not p_bio_folder.value:
            p_bio_folder.setWarningMessage(
                "Canada Biophysical Parameters selected. "
                "Please provide the NRCAN biophysical rasters folder "
                "(containing VH_*, CC_*, LAI_* rasters).")

        # GEDI hint
        if src_val == SOURCE_GEDI and p_raster.value:
            p_raster.setIDMessage("WARNING", 975,
                "[VegPreprocess/GEDI] Raster will be reclassified into 6 height "
                "bands. stemDiameter derived via Jucker et al. 2017 allometric model.")

        # Extent CRS warning
        if p_extent.value and arcpy.Exists(p_extent.valueAsText):
            try:
                ext_sr = arcpy.Describe(p_extent.valueAsText).spatialReference
                if ext_sr.type == "Geographic":
                    p_extent.setWarningMessage(
                        "Analysis Extent is in a Geographic CRS. "
                        "Output will be reprojected to Web Mercator (EPSG:3857). "
                        "For best results, use a Projected CRS for the extent.")
            except Exception:
                pass

        # VTI range
        if p_gap_vti.value is not None:
            try:
                vti = float(p_gap_vti.valueAsText)
                if not 0.0 <= vti <= 1.0:
                    p_gap_vti.setErrorMessage(
                        "Gap-Fill VTI must be between 0.0 and 1.0.")
            except ValueError:
                p_gap_vti.setErrorMessage("Gap-Fill VTI must be a number.")

    # =========================================================================
    def execute(self, parameters, messages):
        arcpy.SetLogMetadata(False)  # Prevent GDB history metadata accumulation (perf)
        source_type   = parameters[0].valueAsText or SOURCE_AUTO
        raster_raw    = parameters[1].valueAsText or ""
        extent_fc     = parameters[2].valueAsText
        output_fc     = parameters[3].valueAsText
        gap_vti_s     = parameters[4].valueAsText
        gap_spacing_s = parameters[5].valueAsText
        gap_diam_s    = parameters[6].valueAsText
        bio_folder    = parameters[7].valueAsText

        # Parse numerics with safe defaults
        try:
            gap_vti     = float(gap_vti_s)     if gap_vti_s     else 0.2
        except ValueError:
            gap_vti     = 0.2
        try:
            gap_spacing = float(gap_spacing_s) if gap_spacing_s else 0.0
        except ValueError:
            gap_spacing = 0.0
        try:
            gap_diam    = float(gap_diam_s)    if gap_diam_s    else 0.0
        except ValueError:
            gap_diam    = 0.0
        # ── Parse multivalue raster list ──────────────────────────────────────
        # ArcGIS multiValue params return paths separated by semicolons.
        # Paths with spaces may be wrapped in single quotes — strip them.
        raster_paths = [r.strip().strip("'\"")
                        for r in raster_raw.split(";")
                        if r.strip().strip("'\"")]

        # ── Route multiple files: Canada Bio classify OR same-type tile mosaic ───
        mosaic_tmp       = None   # temp mosaic raster (cleaned up after use)
        canada_bio_files = None   # pre-classified {role: path} for Canada Bio

        if len(raster_paths) > 1:
            # Decide whether these are Canada Bio role files or same-type tiles.
            # Canada Bio: different rasters (LAI, fCOVER, VH, GLAD height) must NOT
            # be mosaicked — they represent different physical quantities.
            # Tiles: same dataset type covering adjacent areas → mosaic is correct.
            #
            # Detection: classify ALL files by biophysical role first.
            # If 2+ distinct roles found (e.g. height+closure, height+lai, closure+lai)
            # → Canada Bio multi-file mode regardless of source_type setting.
            # This allows mixing GLAD height + NRCAN fCOVER + NRCAN LAI in one run.
            candidate_bio = _classify_canada_bio_files(raster_paths)
            is_canada_bio = (
                source_type == SOURCE_CANADA_BIO    # user forced it, OR
                or len(candidate_bio) >= 2          # 2+ different biophysical roles found
            )

            if is_canada_bio:
                # Use pre-classified dict (already computed above)
                canada_bio_files = candidate_bio
                roles = sorted(canada_bio_files.keys())
                arcpy.AddMessage(
                    f"[CCM Veg Preprocess] {len(raster_paths)} Canada Bio files "
                    f"selected — classified roles: {roles}")
                for role, path in sorted(canada_bio_files.items()):
                    arcpy.AddMessage(f"  {role:8s}: {os.path.basename(path)}")
                # Use the first classified file as raster_path placeholder
                # (real routing happens inside preprocess_canada_bio via bio_files)
                raster_path = raster_paths[0]
                source_type = SOURCE_CANADA_BIO   # ensure correct dispatch
            else:
                arcpy.AddMessage(
                    f"[CCM Veg Preprocess] {len(raster_paths)} tiles selected — "
                    "mosaicking before processing …")
                mosaic_tmp = _mosaic_rasters(raster_paths, messages)
                if not mosaic_tmp:
                    arcpy.AddError(
                        "[CCM Veg Preprocess] Mosaic failed — "
                        "check messages above.")
                    return None
                raster_path = mosaic_tmp
        else:
            raster_path = raster_paths[0] if raster_paths else ""

        # Delete existing output
        if arcpy.Exists(output_fc):
            arcpy.management.Delete(output_fc)

        result = preprocess_vegetation(
            raster_path  = raster_path,
            output_fc    = output_fc,
            extent_fc    = extent_fc,
            source_type  = source_type,
            bio_folder   = bio_folder,
            bio_files    = canada_bio_files,
            gap_vti      = gap_vti,
            gap_spacing  = gap_spacing,
            gap_diam     = gap_diam,
            messages     = messages,
        )

        # Clean up temp mosaic raster (Canada Bio path uses no temp mosaic)
        if mosaic_tmp and arcpy.Exists(mosaic_tmp):
            try:
                arcpy.management.Delete(mosaic_tmp)
                arcpy.AddMessage(
                    "[CCM Veg Preprocess] Temporary mosaic raster deleted.")
            except Exception:
                pass

        # Write derived output param
        parameters[8].value = result.source_detected

        if result.success:
            arcpy.AddMessage(
                f"\n[CCM Veg Preprocess]  Done.\n"
                f"  Output FC : {result.output_fc}\n"
                f"  Dataset   : {result.source_detected}\n"
                f"  Polygons  : {result.n_polygons:,}  "
                f"(mapped {result.n_mapped:,} | "
                f"gap-filled {result.n_gap_filled:,})\n\n"
                "  This FC can now be used as the 'Vegetation Data' input "
                "in the CCM Mobility Map tool."
            )
        else:
            arcpy.AddError(
                f"[CCM Veg Preprocess] Processing failed — {result.error}")

# <<< END OF FILE >>>
