# -*- coding: utf-8 -*-
# MCE Cross Country Mobility Tool — V2
# Version : v2.36
# Compatible with ArcGIS Pro 3.x  (Python 3.11)
#
# ── UPDATE THIS whenever you make changes ────────────────────────────────────
VERSION = "2.40"
#
# v2.30  — Step 3 isochrone interval fix + RefreshTOC removed
#   • Fixed: time intervals passed as semicolons to ccm_isochrone (was commas)
#   • Fixed: arcpy.RefreshTOC() removed (ArcMap-only, not in ArcGIS Pro)
#
# v2.29  — Multi-format coordinate support (MGRS, DD, DMS, DDM, UTM)
#   • ccm_coords.py v2.0: fixed ConvertCoordinateNotation keyword arg bug
#     (all calls now use positional arguments — 'out_table' kwarg rejected by
#      ArcGIS Pro). Added any_to_latlon(), latlon_to_all_formats(),
#      format_coord_display(), detect_format().
#   • All coordinate input fields now accept any format (MGRS/DD/DMS/DDM/UTM).
#   • Coordinate display fields auto-compute equivalents in all formats.
#   • Step 3 category labels updated with plain-English descriptions.
#   • ccm_step3_advanced.py, ccm_isochrone.py, ccm_waypoints.py updated.
#
# v2.28  — Step 3: Vehicle B dropdown + Obstacle Detection auto-fill
# -----------------------------------------------------------------------
#   • Vehicle B Speed Surface: changed from DEFeatureClass (blank browser)
#     to GPString ValueList — auto-populated from all speed_surface_* FCs
#     found in CCM_Project.gdb when the project folder is selected.
#   • Vehicle A and B Names: auto-derived from the FC names
#     (speed_surface_T62_T72_moist → "T62 / T72 (moist)").
#   • Obstacle Detection: Contour Lines FC and Hydro Line FC now
#     auto-fill from ccm_project.json (contours_fc / hydro_fcs) —
#     no manual selection needed if Step 1 was run.
#   • Helper functions _list_speed_surfaces() and _label_from_speed_fc()
#     added to ccm_step3_advanced.py.
#
# v2.27  — MGRS coordinate input for all point parameters
# -----------------------------------------------------------------------
#   • New ccm_coords.py module: mgrs_to_latlon(), validate_mgrs(),
#     format_latlon_as_mgrs() using arcpy.management.ConvertCoordinateNotation
#   • ccm_step3_advanced.py: iso_start_point, wp_start_point, wp_end_point
#     changed from GPPoint to GPString (MGRS).  Validation in
#     updateMessages; conversion printed to geoprocessing pane.
#   • ccm_waypoints.py: start_point and end_point changed to GPString (MGRS).
#   • ccm_isochrone.py: start_point changed to GPString (MGRS).
#   • ccm_coords registered in V2.pyt module-level imports.
#
# v2.26  — Step 2: copy final mobility map into CCM_Project.gdb
# -----------------------------------------------------------------------
#   • After _CCMAnalysisEngine completes, the speed surface FC is copied
#     from the per-run GDB (CCM_<vehicles>_<moisture>.gdb) into the
#     project GDB (CCM_Project.gdb) so the final product has one stable,
#     predictable location.
#   • The copied path is saved to ccm_project.json as mobility_map_fc.
#   • Existing FC of the same name in project GDB is replaced on re-run.
#   • Per-run GDB is kept intact (contains all intermediate layers).
#
# v2.25  — Step 2: persist derived slope & contour paths to project config
# -----------------------------------------------------------------------
#   • Slope polygon now saved to project GDB (not scratchGDB which ArcGIS
#     Pro clears between sessions).
#   • After first successful derivation of slope regions and contour lines,
#     each path is written back to ccm_project.json via _cfg_mod.save_config.
#   • Subsequent Step 2 runs read the saved paths from config and skip
#     re-derivation entirely — no more repeated "deriving from DEM" on
#     every run.
#
# v2.24  — Bug fix: fill_gaps_in_feature_class isEmpty → .area == 0
# -----------------------------------------------------------------------
#   • gap_geom.isEmpty replaced with gap_geom.area == 0  (arcpy Polygon
#     does not have an isEmpty attribute — caused AttributeError at the
#     end of veg processing in Step 2 every run).
#   • Added # -*- coding: utf-8 -*- declaration (line 1) so Windows
#     systems with non-UTF-8 system locale load the file correctly.
#
# v2.23  — Performance: gap fill + vegetation processing
# -----------------------------------------------------------------------
#   • fill_gaps_in_feature_class(): replaced iterative Python .union() loop
#     (O(n) geometry ops, hours on large datasets) with a single
#     arcpy.management.Dissolve call (C++ accelerated, seconds).
#     Requires only Basic licence.
#   • calculate_vegetation_factor(): removed per-feature arcpy.AddMessage
#     and run_log.log_gap calls that spammed the message pane with thousands
#     of identical lines on non-forest veg layers.
#   • Vegetation loop: replaced per-feature messages with per-FC counters
#     and a single summary line per layer (e.g. "8200 VTI-only features").
#   • RunLog.log_gap(): deduplicated — identical messages logged only once,
#     preventing run_log.data_gaps list from growing to thousands of entries.
#
# v2.22  — Single-file architecture (V1 engine merged into V2.pyt)
# -----------------------------------------------------------------------
#   • MCE_CCM_V1.pyt content merged directly into MCE_CCM_V2.pyt.
#     V2.pyt is now fully self-contained — MCE_CCM_V1.pyt is no longer
#     required at runtime.
#   • _load_pyt() importlib loader removed; _V1CCMTool reference replaced
#     by _CCMAnalysisEngine (V1's CCMTool class, merged inline).
#   • _CCMValidateEngineV1 (V1's CCMValidateTool) also merged for
#     completeness; V2's CCMValidateTool wrapper is unchanged.
#   • All _v1_mod / _v1_find_field / _v1_read_csv / _v1_SOIL_ALIASES
#     indirections replaced with direct module-level references.
#   • _ff() simplified: calls find_field() directly (no None-guard needed).
#   • Runtime V1 fallback block in CCMStep2MobilityTool.execute() removed
#     (no longer needed — engine is always available).
#   • Extra V1 imports (math, datetime) added to V2 import block.
#   • Versioning: increment VERSION constant for each future change.
# ─────────────────────────────────────────────────────────────────────────────
#
# v2.21  — 3-Step Workflow
# -----------------------------------------------------------------------
#   • ccm_step1_setup.py    — "Step 1. Project Setup & Pre-process"
#     Collects all raw inputs once; runs soil + veg pre-processing
#     sequentially; writes ccm_project.json to the project folder
#   • ccm_step2_mobility.py — "Step 2. Generate Mobility Map"
#     Loads ccm_project.json; user picks vehicles and moisture only;
#     delegates to V1 CCMTool via _P shim; updates config with results
#   • ccm_step3_advanced.py — "Step 3. Advanced Analysis"
#     Loads config / speed surface; runs any combination of Reason Map,
#     Isochrone, Vehicle Compare, Obstacle Detection, Waypoint Routing
#   • ccm_project_config.py — project JSON save/load helpers (v2.21)
#   • All 3 new wrapper tools prepended to the toolbox tool list so they
#     appear first (before legacy individual tools)
#
# v2.15  — Vegetation: multi-file Canada Bio selection (LAI + fCOVER etc.)
# -----------------------------------------------------------------------
#   • _classify_canada_bio_files(file_list): new helper — classifies an
#     explicit list of file paths into Canada Bio roles (height/closure/lai)
#     using the same keyword matching as _scan_canada_bio_folder()
#   • preprocess_canada_bio(): new bio_files= parameter — when supplied,
#     skips the folder scan entirely and uses the pre-classified dict directly
#   • preprocess_vegetation(): threads bio_files= through to canada_bio dispatch
#   • execute(): when multiple rasters are selected and the first file is
#     detected as Canada Bio, calls _classify_canada_bio_files() instead of
#     _mosaic_rasters() — prevents incorrect mosaicking of heterogeneous rasters
#     (LAI + fCOVER are different physical quantities, not same-type tiles)
#   • updateMessages(): shows "roles detected: [...]" banner for Canada Bio
#     multi-file selection instead of generic "will be mosaicked" message
#   • p_raster label updated to mention Canada Bio multi-file support
#
# v2.14  — Vegetation: NRCAN date/auxiliary file guard + fCOVER support
# -----------------------------------------------------------------------
#   • Fixed _scan_canada_bio_folder() for NRCAN hyphen naming convention
#     (vegetation-YYYY-VH/CC/LAI.tif); added fCOVER to closure keywords
#   • Added errorfCOVER / errorLAI / Partition / QC to skip list
#   • Added NRCAN filename regex detection in detect_veg_source_type()
#   • Date / Bitmask files now show explicit error with guidance to correct files
#   • Sibling folder inference: selecting any single NRCAN file auto-scans folder
#
# v2.13  — Vegetation: multi-tile mosaic support
# -----------------------------------------------------------------------
#   • p_raster (Land-Cover Raster) now has multiValue=True — user can
#     select 2, 5, 10+ adjacent tiles in one dialog; paths returned as
#     semicolon-separated string
#   • _mosaic_rasters(): new helper — detects pixel type from first tile,
#     calls MosaicToNewRaster into scratchGDB, returns temp path;
#     single-tile input skips mosaic entirely (zero overhead)
#   • execute(): parses semicolon list, strips ArcGIS quote-wrapping on
#     paths with spaces, mosaics if >1 tile, deletes temp after processing
#   • updateMessages(): validates each path in the multivalue list;
#     shows info banner when 2+ tiles are selected
#   • updateParameters(): extracts first path from semicolon list for
#     auto-detect (so source type is shown immediately on first tile pick)
#
# v2.12  — Vegetation: GEDI Canopy Height + Canada Biophysical Parameters
# -----------------------------------------------------------------------
#   • SOURCE_GEDI: continuous float height raster → 6 height bands via
#     arcpy.sa.Reclassify; stemDiameter from Jucker et al. 2017 allometric
#     (D = 0.557 × H^0.809); treeSpacing and VTI from band lookup table
#   • SOURCE_CANADA_BIO: NRCAN biophysical parameter folder
#     - _scan_canada_bio_folder(): finds VH/CC/LAI rasters by filename pattern
#     - Height → height-band lookup (same as GEDI)
#     - Canopy Closure → ZonalStatistics → refines treeSpacing per polygon
#     - LAI → ZonalStatistics → refines VTI per polygon
#   • detect_veg_source_type(): new checks —
#     - Folder path → _scan_canada_bio_folder()
#     - _get_raster_info() pixel-type check → float raster = GEDI/CHM
#     - Filename hints: "gedi", "canopy_height", "chm", "forest_height"
#   • Tool UI: new p7 "Biophysical Rasters Folder" for Canada Bio;
#     detected_source moved from p7 → p8
#
# v2.11  — Vegetation Data Preprocessor
# -----------------------------------------------------------------------
#   • ccm_veg_preprocess.py: new module — converts land-cover raster to
#     CCM vegetation polygon FC with vegetationTrafficImpact, treeSpacing,
#     stemDiameter fields
#   • detect_veg_source_type(): auto-fingerprints dataset from pixel values
#     — supports ESA WorldCover 10 m, NLCD (US 30 m), CGLS-LC100 (100 m),
#     Generic; MODIS/VIIRS and NOAA VH excluded (resolution too coarse
#     for vehicle passability — 1 km cell can span an entire forested mountain)
#   • CCMVegPreprocessTool: new ArcGIS tool "0b. Pre-process Vegetation Data"
#     registered in Toolbox immediately after soil preprocessor
#   • Auto-reproject CRS guard inherited from soil preprocessor pattern
#
# v2.10  — Auto-reproject output to Projected CRS
# -----------------------------------------------------------------------
#   • _ensure_projected_crs(): new helper — checks output FC after every run;
#     if it is in a Geographic CRS (e.g. WGS 1984 from HWSD / SoilGrids),
#     automatically reprojects in-place to match the Analysis Extent's CRS
#   • preprocess_soil_data(): all source branches now assign to `result`
#     instead of returning directly, so the CRS guard runs for every source
#   • If no projected extent is provided, a clear warning with fix instructions
#     is printed instead of silently producing an unusable geographic FC
#
# v2.09  — Bug fixes (5 issues found in code audit)
# -----------------------------------------------------------------------
#   • HWSD v1: write-soilType loop now translates gridcode (MU_GLOBAL)
#     through mu_to_smu → SMU_ID before looking up smu_to_uscs;
#     previously v1 always produced 0 mapped polygons (v2 was unaffected)
#   • SoilGrids: DefineProjection now called AFTER uscs_ras.save() so
#     projection is actually written to the file-on-disk
#   • Diagnostic: ADODB registry check fixed to use HKEY_CLASSES_ROOT
#     instead of HKLM\SOFTWARE\Classes
#   • updateMessages: SoilGrids "no extent" warning no longer overwrites
#     the higher-priority "no folder" warning (changed if/if to if/elif)
#   • Comment fix: gridcode annotation updated for v1 vs v2 difference
#
# v2.08  — Triple-method MDB reader + ACE driver diagnostics
# -----------------------------------------------------------------------
#   • _read_mdb_win32com(): new 2nd method via raw ADODB COM dispatch
#     (different OLE DB initialisation path from arcpy — may succeed when
#     arcpy's OLE DB path is blocked by a 32-bit/64-bit Office conflict)
#   • _log_ace_diagnostic(): prints registered Access ODBC drivers (pyodbc)
#     and ADODB COM class presence on startup, for instant diagnosis
#   • read_mdb_table(): now tries pyodbc → win32com → arcpy in order;
#     first success wins; clear fix instructions printed when all fail
#
# v2.07  — HWSD v1 / v2 auto-schema detection
# -----------------------------------------------------------------------
#   • read_mdb_table() reads all candidate fields for both v1 and v2
#     in a single call; schema sniffed from first returned row
#   • v1:  T_SAND / T_SILT / T_CLAY, MU_GLOBAL lookup chain kept
#   • v2:  SAND / SILT / CLAY, raster pixel IS HWSD2_SMU_ID directly
#   • WRB classification: WRB2006/FAO90 (v1) or WRB4/WRB2 (v2) auto-selected
#   • Detected version logged to geoprocessing messages for diagnostics
#
# v2.03  — SoilGrids 2.0 (Global) support
# -----------------------------------------------------------------------
#   • SOURCE_SOILGRIDS constant + added to ALL_SOURCES dropdown
#   • preprocess_soilgrids(): GeoTIFF raster stack → USCS polygon FC
#     - Supports single depth (0-5cm … 60-100cm) or Weighted 0-30cm mean
#     - g/kg → % conversion, vectorised numpy USCS classification
#     - Auto-clips to extent using Spatial Analyst ExtractByMask
#   • detect_source_type(): recognises sand_*/silt_*/clay_*.tif filenames
#     and SoilGrids folder fingerprinting
#   • Tool UI: new "SoilGrids 2.0 (Global)" category (folder + depth params)
#   • updateMessages(): warns if no extent set (global raster performance)
#
# v2.02  — TDS (NGA) and GGDM (NGA) support added to soil preprocessor
# -----------------------------------------------------------------------
#   • SOURCE_TDS / SOURCE_GGDM constants + ALL_SOURCES list updated
#   • preprocess_tds() / preprocess_ggdm() public wrappers
#   • _NE_PATTERNS dict: per-source non-soil FC name patterns
#   • detect_source_type() GDB fingerprinting (SurfaceCoverA → TDS,
#     SurfaceMaterialA → GGDM)
#   • Shared "Military Topographic (MGCP / TDS / GGDM)" UI category
#   • is_mil_topo flag replaces is_mgcp in updateParameters()
#
# Layout redesign v2.1
# --------------------
#   Page 1 (uncategorised) — all essential inputs visible immediately:
#     Analysis Extent, DEM, Slope Regions, Soil, Vegetation, Hydrology,
#     Vehicle CSV, Select Vehicles, Soil Moisture, Output Folder
#   Category "Optional Data" — Contour Lines
#   Category "Advanced Options" — Symbology, Live Weather, Rainfall Override
#
#   Smart warnings fire as soon as a layer is selected:
#     - missing required fields (with list of what IS available)
#     - wrong geometry type
#     - Geographic CRS (must reproject)
#     - no spatial overlap with extent
#     - unknown soil type codes (sampled from first 100 rows)
#     - DEM provided but no Slope Regions → auto-derive note
#     - missing vehicle CSV columns
#
# NOTE: arcpy.AddMessage / AddWarning are NEVER called at module load time
#       or inside __init__ / getParameterInfo. Only inside execute().

import arcpy
import os
import sys
import math
import pandas as pd
from datetime import datetime

# ── Add this folder to sys.path so companion .py modules import cleanly ───────
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


# ── Load V1 (.pyt) via importlib ──────────────────────────────────────────────
# NOTE: spec_from_file_location() returns None for .pyt files because Python
# does not recognise the extension.  We must supply a SourceFileLoader
# explicitly so importlib treats the file as plain Python source.

# =============================================================================
# V1 ENGINE — merged from MCE_CCM_V1.pyt (v2.22)
# All classes and helpers below were previously loaded at runtime via
# importlib.  They are now part of this file.  Do not edit these sections
# unless you are specifically patching V1 engine behaviour.
# =============================================================================


# ─────────────────────────────────────────────────────────────────────────────
# FIELD ALIASES
# Maps each canonical CCM field name to a list of accepted aliases.
# Comparison is case-insensitive at runtime (all aliases are stored lowercase).
# ─────────────────────────────────────────────────────────────────────────────
FIELD_ALIASES = {
    "surfaceSlope": [
        "surfaceslope", "slope", "slope_pct", "slope_percent",
        "surfslope", "surface_slope", "gradient", "grad_pct",
        "slope_deg", "incline", "percent_slope",
    ],
    "soilType": [
        "soiltype", "soil_type", "soil_class", "soilclass",
        "f_code", "soil", "uscs", "uscs_class",
        "soil_classification", "texture_class", "soil_texture",
    ],
    "highestElevation": [
        "highestelevation", "elevation", "contour", "elev",
        "elev_m", "elev_ft", "z", "height",
        "contourelevation", "cont_elev", "contour_elevation",
        "contour_value", "elevvalue", "contourvalue",
    ],
    "vegetationTrafficImpact": [
        "vegetationtrafficimpact", "veg_traffic_impact", "vti",
        "traffic_impact", "veg_impact", "vegtrafficimpact",
        "veg_ti", "vegetation_impact",
    ],
    "treeSpacing": [
        "treespacing", "tree_spacing", "spacing_m", "spacing",
        "treespace", "tree_space", "avg_spacing", "canopy_spacing",
    ],
    "stemDiameter": [
        "stemdiameter", "stem_diameter", "stem_diam", "stemdia",
        "diameter_m", "diameter", "stem_d", "avg_diameter",
        "trunk_diam",
    ],
}

# ─────────────────────────────────────────────────────────────────────────────
# SOIL TYPE ALIASES
# Maps raw soilType values (USCS codes, plain English, camelCase) to the
# canonical keys used in rci_soils_dict.  All keys are stored lowercase.
# ─────────────────────────────────────────────────────────────────────────────
SOIL_TYPE_ALIASES = {
    # ── USCS codes ─────────────────────────────────────────────────────────
    "gw":    "wellGradedGravel",
    "gp":    "poorlyGradedGravel",
    "gm":    "siltyGravelSand",
    "gc":    "clayeyGravel",
    "sw":    "wellGradedSand",
    "sp":    "poorlyGradedSand",
    "sm":    "siltySand",
    "sc":    "clayeySand",
    "ml":    "siltAndFineSand",
    "cl":    "leanClay",
    "ol":    "organicSiltandClay",
    "ch":    "fatClay",
    "mh":    "micaceous",
    "oh":    "organicClay",
    "pt":    "peat",
    "ml-cl": "siltFineSandLeanClay",
    "ev":    "evaporite",
    "rk":    "rock",
    "ne":    "notEvaluated",
    # ── Plain English ──────────────────────────────────────────────────────
    "well graded gravel":        "wellGradedGravel",
    "well-graded gravel":        "wellGradedGravel",
    "poorly graded gravel":      "poorlyGradedGravel",
    "poorly-graded gravel":      "poorlyGradedGravel",
    "silty gravel":              "siltyGravelSand",
    "silty gravel sand":         "siltyGravelSand",
    "clayey gravel":             "clayeyGravel",
    "well graded sand":          "wellGradedSand",
    "well-graded sand":          "wellGradedSand",
    "poorly graded sand":        "poorlyGradedSand",
    "poorly-graded sand":        "poorlyGradedSand",
    "silty sand":                "siltySand",
    "clayey sand":               "clayeySand",
    "silt":                      "siltAndFineSand",
    "silt and fine sand":        "siltAndFineSand",
    "lean clay":                 "leanClay",
    "organic silt":              "organicSiltandClay",
    "organic silt and clay":     "organicSiltandClay",
    "fat clay":                  "fatClay",
    "elastic silt":              "micaceous",
    "micaceous":                 "micaceous",
    "organic clay":              "organicClay",
    "peat":                      "peat",
    "rock":                      "rock",
    "evaporite":                 "evaporite",
    "not evaluated":             "notEvaluated",
    # ── Compact camelCase variants (stripped, lowercased) ──────────────────
    "wellgradedgravel":          "wellGradedGravel",
    "poorlygradedgravel":        "poorlyGradedGravel",
    "siltygravelsand":           "siltyGravelSand",
    "siltygravel":               "siltyGravelSand",
    "clayeygravel":              "clayeyGravel",
    "wellgradedsand":            "wellGradedSand",
    "poorlygradedsand":          "poorlyGradedSand",
    "siltysand":                 "siltySand",
    "clayeysand":                "clayeySand",
    "siltandfinessand":          "siltAndFineSand",
    "leanclay":                  "leanClay",
    "organicsiltandclay":        "organicSiltandClay",
    "fatclay":                   "fatClay",
    "organicclay":               "organicClay",
    "siltfinesandleanclay":      "siltFineSandLeanClay",
}


# ─────────────────────────────────────────────────────────────────────────────
# RUN LOG  —  collects issues during execute() and prints a structured summary
# ─────────────────────────────────────────────────────────────────────────────

class RunLog:
    """
    Accumulates warnings, data-quality issues, and coverage statistics
    during a CCM tool run.  Call print_summary() at the end of execute()
    to display a single consolidated report in the geoprocessing pane.
    """

    def __init__(self):
        self.aliases       = []   # list of (canonical, actual, layer_label)
        self.data_gaps     = []   # free-form warning strings
        self.null_soils    = 0    # count of features with NULL soilType
        self.unknown_soils = []   # list of unrecognised raw soilType values
        self.vehicle_warns = []   # list of (vehicle_name, [null_optional_fields])
        self.coverage      = {}   # Mobility label -> feature count

    def log_alias(self, canonical, actual, layer):
        self.aliases.append((canonical, actual, layer))

    def log_gap(self, msg):
        if msg not in self.data_gaps:   # deduplicate — prevents list explosion
            self.data_gaps.append(msg)

    def log_null_soil(self):
        self.null_soils += 1

    def log_unknown_soil(self, raw_val):
        if raw_val not in self.unknown_soils:
            self.unknown_soils.append(raw_val)

    def log_vehicle_warn(self, vname, fields):
        self.vehicle_warns.append((vname, list(fields)))

    def log_coverage(self, label, count=1):
        self.coverage[label] = self.coverage.get(label, 0) + count

    def print_summary(self, output_gdb, speed_surface_fc, vehicles, soil_moisture):
        ts  = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
        sep = "\u2550" * 62

        def msg(text=""):
            arcpy.AddMessage(text)

        def warn(text):
            arcpy.AddWarning(text)

        msg(sep)
        msg("  CCM RUN SUMMARY")
        msg(sep)
        msg(f"  Completed : {ts}")
        msg(f"  Vehicles  : {', '.join(vehicles)}")
        msg(f"  Moisture  : {soil_moisture}")
        msg(f"  Output    : {speed_surface_fc}")
        msg()

        # ── Field aliases ──────────────────────────────────────────────────
        n = len(self.aliases)
        msg(f"  [FIELD ALIASES]   {n} resolved" if n else "  [FIELD ALIASES]   none")
        for canonical, actual, layer in self.aliases:
            msg(f"    • '{actual}'  ->  '{canonical}'  ({layer})")
        msg()

        # ── Data gaps ──────────────────────────────────────────────────────
        n = len(self.data_gaps)
        msg(f"  [DATA GAPS]   {n} warning(s)" if n else "  [DATA GAPS]   none")
        for gap in self.data_gaps:
            warn(f"    ! {gap}")
        msg()

        # ── Soil type issues ───────────────────────────────────────────────
        soil_issues = self.null_soils + len(self.unknown_soils)
        msg(f"  [SOIL TYPES]   {soil_issues} issue(s)" if soil_issues
            else "  [SOIL TYPES]   all recognised")
        if self.null_soils:
            warn(f"    ! {self.null_soils} feature(s) had NULL soilType — F4/F5 set to NULL")
        for v in self.unknown_soils:
            warn(f"    ! Unrecognised value: '{v}' — F4/F5 set to NULL"
                 "  (add to SOIL_TYPE_ALIASES to fix)")
        msg()

        # ── Vehicle warnings ───────────────────────────────────────────────
        n = len(self.vehicle_warns)
        msg(f"  [VEHICLES]   {n} warning(s)" if n else "  [VEHICLES]   all fields present")
        for vname, fields in self.vehicle_warns:
            warn(f"    ! {vname} — NULL optional fields: {', '.join(fields)}")
        msg()

        # ── Output coverage ────────────────────────────────────────────────
        msg("  [OUTPUT COVERAGE]")
        missing_total = 0
        for label, count in sorted(self.coverage.items(), key=lambda x: -x[1]):
            flag = "  !" if "Missing" in label else ""
            msg(f"    • {label:<42} {count:>7} feature(s){flag}")
            if "Missing" in label:
                missing_total += count
        if missing_total:
            warn(f"    -> {missing_total} feature(s) could not be fully classified"
                 " due to missing input data")
        msg()
        msg(sep)


# ─────────────────────────────────────────────────────────────────────────────
# MODULE-LEVEL HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def find_field(fc, canonical_name):
    """
    Searches the feature class for a field matching canonical_name or any of
    its registered aliases (case-insensitive).

    Returns the actual field name as it appears in the FC, or None if absent.
    """
    actual = {f.name.lower(): f.name for f in arcpy.ListFields(fc)}
    # 1. Try exact match (case-insensitive)
    if canonical_name.lower() in actual:
        return actual[canonical_name.lower()]
    # 2. Try each registered alias
    for alias in FIELD_ALIASES.get(canonical_name, []):
        if alias.lower() in actual:
            return actual[alias.lower()]
    return None


def normalize_soil_type(raw_value):
    """
    Normalises a raw soilType string to the canonical key used in rci_soils_dict.

    Handles:
      - USCS codes ("GW", "CL", "SP" …)
      - Plain English ("Lean Clay", "Well Graded Gravel" …)
      - camelCase variants ("leanClay", "wellGradedGravel" …)

    Returns the original string unchanged if no mapping is found,
    so the caller can raise a meaningful KeyError with the original value.
    """
    if raw_value is None:
        return None
    key = raw_value.strip().lower()
    return SOIL_TYPE_ALIASES.get(key, raw_value)


def check_projection(fc, label):
    """
    Validates that fc uses a Projected (not Geographic) coordinate system.

    Raises ValueError with a clear, actionable message if a Geographic CRS
    (e.g. WGS84 lat/lon) is detected.  Returns the SpatialReference on success.
    """
    sr = arcpy.Describe(fc).spatialReference
    if sr.type == "Geographic":
        raise ValueError(
            f"Input '{label}' uses a Geographic coordinate system "
            f"({sr.name}).  All inputs must use a Projected coordinate "
            "system (e.g. UTM).  Use the Project tool in ArcGIS Pro to "
            "reproject your data before running the CCM Tool."
        )
    return sr


def read_csv_robust(path):
    """
    Reads a CSV file, falling back to latin-1 encoding if UTF-8 fails.
    Raises a clear ValueError for unreadable files.
    """
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            return pd.read_csv(path, encoding=enc)
        except UnicodeDecodeError:
            continue
        except Exception as e:
            raise ValueError(f"Cannot read vehicle CSV '{path}': {e}") from e
    raise ValueError(
        f"Could not read vehicle CSV '{path}' with any supported encoding "
        "(utf-8, latin-1, cp1252).  Please save the file as UTF-8."
    )


# ─────────────────────────────────────────────────────────────────────────────
# TOOLBOX DEFINITION
# ─────────────────────────────────────────────────────────────────────────────


# ── V1 Analysis Engine (was CCMTool in V1) ────────────────────────────────

class _CCMAnalysisEngine:
    def __init__(self):
        self.label = "MCE Cross Country Mobility Tool"
        self.description = (
            "Calculates off-road mobility of personnel and vehicles across "
            "natural terrain and creates a mobility map."
        )
        self.canRunInBackground = False

    # ── Parameters ────────────────────────────────────────────────────────────

    def getParameterInfo(self):
        params = []

        param1 = arcpy.Parameter(
            displayName="Extent Polygon Feature Class",
            name="extent_polygon_fc",
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Input",
        )
        param2 = arcpy.Parameter(
            displayName="Slope_Region_S Feature Class",
            name="surface_configuration_fc",
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Input",
        )
        param3 = arcpy.Parameter(
            displayName="Contours Feature Class",
            name="contours_fc",
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Input",
        )
        param4 = arcpy.Parameter(
            displayName="Soil_Surface_Region_S Feature Class",
            name="soil_fc",
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Input",
        )
        param5 = arcpy.Parameter(
            displayName="Soil Moisture Condition",
            name="soil_moisture_condition",
            datatype="String",
            parameterType="Required",
            direction="Input",
        )
        param5.filter.type = "ValueList"
        param5.filter.list = ["dry", "moist", "wet"]

        param6 = arcpy.Parameter(
            displayName="All Considered Vegetation Feature Classes",
            name="vegetation_fcs",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input",
            multiValue=True,
        )
        param7 = arcpy.Parameter(
            displayName="Hydro Feature Classes",
            name="hydro_fcs",
            datatype="GPFeatureLayer",
            parameterType="Optional",
            direction="Input",
            multiValue=True,
        )
        param8 = arcpy.Parameter(
            displayName="Vehicle Capabilities CSV",
            name="vehicle_csv",
            datatype="DEFile",
            parameterType="Required",
            direction="Input",
        )
        param9 = arcpy.Parameter(
            displayName="Select Vehicle(s)",
            name="select_vehicles",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
            multiValue=True,
        )
        param10 = arcpy.Parameter(
            displayName="Output Folder",
            name="output_folder",
            datatype="DEFolder",
            parameterType="Required",
            direction="Output",
        )
        param11 = arcpy.Parameter(
            displayName="Symbology Layer for Speed Surface Feature Class (.lyrx)",
            name="speed_surface_symbology_lyrx",
            datatype="DEFile",
            parameterType="Optional",
            direction="Input",
        )

        params.extend([param1, param2, param3, param4, param5,
                        param6, param7, param8, param9, param10, param11])
        return params

    def isLicensed(self):
        return True

    # ── Dynamic parameter updates ──────────────────────────────────────────────

    def updateParameters(self, parameters):
        # parameters[7] = vehicle_csv
        if parameters[7].altered:
            vehicle_csv = parameters[7].valueAsText
            if vehicle_csv and os.path.isfile(vehicle_csv):
                try:
                    vehicles_df = read_csv_robust(vehicle_csv)
                    if "name" in vehicles_df.columns:
                        parameters[8].filter.list = [
                            str(v) for v in vehicles_df["name"].tolist()
                        ]
                except Exception:
                    pass
        return

    # ── Pre-run validation messages ────────────────────────────────────────────

    def updateMessages(self, parameters):
        """
        Comprehensive live validation — called every time any parameter changes.
        Sets error / warning messages directly on each parameter so the tool
        dialog gives immediate visual feedback before the user clicks Run.

        Checks performed per parameter:
          [0] Extent     — projection (error), geometry type, feature count
          [1] Slope FC   — projection (error), geometry type, surfaceSlope field,
                           extent bounding-box overlap
          [2] Contours   — geometry type, elevation field (alias), extent overlap
          [3] Soil FC    — projection (error), geometry type, soilType field,
                           quick sample of unique soil values (unknown → warn),
                           extent overlap
          [5] Veg FCs    — geometry type, VTI/treeSpacing/stemDiameter fields,
                           extent overlap; aggregated into one message
          [6] Hydro FCs  — geometry type must be Polygon (Union requirement),
                           extent overlap
          [7] Vehicle CSV— required columns present, file readable
          [8] Vehicles   — selected names exist in CSV
        """

        # ── Internal helpers ───────────────────────────────────────────────
        def safe_desc(path):
            try:    return arcpy.Describe(path)
            except: return None

        def bboxes_overlap(e1, e2):
            return (e1.XMin < e2.XMax and e1.XMax > e2.XMin and
                    e1.YMin < e2.YMax and e1.YMax > e2.YMin)

        def overlap_warn(fc_path, aoi_path, label, param):
            try:
                if not bboxes_overlap(arcpy.Describe(fc_path).extent,
                                      arcpy.Describe(aoi_path).extent):
                    param.setWarningMessage(
                        f"'{label}' bounding box does not overlap the Extent "
                        "Polygon — verify your input data."
                    )
            except Exception:
                pass

        extent_ok   = parameters[0].value and not parameters[0].hasError()
        extent_path = parameters[0].valueAsText if extent_ok else None

        # ── [0] Extent Polygon ─────────────────────────────────────────────
        if parameters[0].value and not parameters[0].hasError():
            try:
                d = safe_desc(parameters[0].valueAsText)
                if d:
                    if d.spatialReference.type == "Geographic":
                        parameters[0].setErrorMessage(
                            f"Extent polygon uses a Geographic CRS "
                            f"({d.spatialReference.name}).  "
                            "All inputs must be Projected (e.g. UTM).  "
                            "Use the Project tool to reproject first."
                        )
                    elif d.shapeType != "Polygon":
                        parameters[0].setErrorMessage(
                            f"Extent must be a Polygon FC (got {d.shapeType})."
                        )
                    else:
                        cnt = int(arcpy.management.GetCount(
                            parameters[0].valueAsText)[0])
                        if cnt == 0:
                            parameters[0].setErrorMessage(
                                "Extent polygon FC is empty (0 features)."
                            )
            except Exception:
                pass

        # ── [1] Slope Region FC ────────────────────────────────────────────
        if parameters[1].value and not parameters[1].hasError():
            slope_path = parameters[1].valueAsText
            try:
                d = safe_desc(slope_path)
                if d:
                    if d.spatialReference.type == "Geographic":
                        parameters[1].setErrorMessage(
                            f"Slope FC uses a Geographic CRS "
                            f"({d.spatialReference.name}).  "
                            "Reproject to a Projected CRS first."
                        )
                    elif d.shapeType != "Polygon":
                        parameters[1].setWarningMessage(
                            f"Slope FC geometry is '{d.shapeType}' — "
                            "Polygon expected."
                        )
                    else:
                        actual = find_field(slope_path, "surfaceSlope")
                        if actual is None:
                            flds = ", ".join(
                                f.name for f in arcpy.ListFields(slope_path)
                                if f.type not in ("OID", "Geometry")
                            )
                            parameters[1].setErrorMessage(
                                "No 'surfaceSlope' field (or alias) found.  "
                                f"Available: {flds}"
                            )
                        elif actual != "surfaceSlope":
                            parameters[1].setWarningMessage(
                                f"'surfaceSlope' absent; using '{actual}' as alias."
                            )
                        if extent_path and not parameters[1].hasError():
                            overlap_warn(slope_path, extent_path,
                                         "Slope Region", parameters[1])
            except Exception:
                pass

        # ── [2] Contours FC ────────────────────────────────────────────────
        if parameters[2].value and not parameters[2].hasError():
            cont_path = parameters[2].valueAsText
            try:
                d = safe_desc(cont_path)
                if d:
                    if d.shapeType not in ("Polyline", "Polygon"):
                        parameters[2].setWarningMessage(
                            f"Contours geometry is '{d.shapeType}' — "
                            "Polyline or Polygon expected."
                        )
                    elev_field = find_field(cont_path, "highestElevation")
                    if elev_field is None:
                        flds = ", ".join(
                            f.name for f in arcpy.ListFields(cont_path)
                            if f.type not in ("OID", "Geometry")
                        )
                        parameters[2].setWarningMessage(
                            "No elevation field ('highestElevation' or alias) "
                            "found — contour normalisation skipped (F2 = 1.0 "
                            f"everywhere).  Available: {flds}"
                        )
                    elif elev_field != "highestElevation":
                        parameters[2].setWarningMessage(
                            f"Using '{elev_field}' as alias for "
                            "'highestElevation'."
                        )
                    if extent_path and not parameters[2].hasError():
                        overlap_warn(cont_path, extent_path,
                                     "Contours", parameters[2])
            except Exception:
                pass

        # ── [3] Soil FC ────────────────────────────────────────────────────
        if parameters[3].value and not parameters[3].hasError():
            soil_path = parameters[3].valueAsText
            try:
                d = safe_desc(soil_path)
                if d:
                    if d.spatialReference.type == "Geographic":
                        parameters[3].setErrorMessage(
                            f"Soil FC uses a Geographic CRS "
                            f"({d.spatialReference.name}).  "
                            "Reproject to a Projected CRS first."
                        )
                    elif d.shapeType != "Polygon":
                        parameters[3].setWarningMessage(
                            f"Soil FC geometry is '{d.shapeType}' — "
                            "Polygon expected."
                        )
                    else:
                        actual = find_field(soil_path, "soilType")
                        if actual is None:
                            flds = ", ".join(
                                f.name for f in arcpy.ListFields(soil_path)
                                if f.type not in ("OID", "Geometry")
                            )
                            parameters[3].setErrorMessage(
                                "No 'soilType' field (or alias) found.  "
                                f"Available: {flds}"
                            )
                        elif actual != "soilType":
                            parameters[3].setWarningMessage(
                                f"'soilType' absent; using '{actual}' as alias."
                            )
                        else:
                            # Quick sample — flag any unknown soil values
                            unique_raw = set()
                            with arcpy.da.SearchCursor(
                                    soil_path, [actual]) as cur:
                                for i, row in enumerate(cur):
                                    if i >= 100: break
                                    if row[0]:
                                        unique_raw.add(str(row[0]))
                            unknown = [
                                v for v in unique_raw
                                if normalize_soil_type(v) not in
                                   SOIL_TYPE_ALIASES.values()
                                and normalize_soil_type(v) == v
                            ]
                            if unknown:
                                parameters[3].setWarningMessage(
                                    "Unrecognised soilType value(s) found "
                                    "(will produce NULL F4/F5): "
                                    f"{', '.join(sorted(unknown))}.  "
                                    "Run 'Validate CCM Inputs' for full "
                                    "details and to add mappings."
                                )
                        if extent_path and not parameters[3].hasError():
                            overlap_warn(soil_path, extent_path,
                                         "Soil", parameters[3])
            except Exception:
                pass

        # ── [5] Vegetation FCs (multivalue) ───────────────────────────────
        if parameters[5].value and not parameters[5].hasError():
            try:
                veg_fcs = parameters[5].values
                if veg_fcs:
                    issues = []
                    for veg_fc in veg_fcs:
                        vp   = str(veg_fc)
                        name = os.path.basename(vp)
                        d    = safe_desc(vp)
                        if not d:
                            issues.append(f"'{name}': cannot read FC")
                            continue
                        if d.shapeType != "Polygon":
                            issues.append(
                                f"'{name}': expected Polygon, "
                                f"got {d.shapeType}"
                            )
                        vti = find_field(vp, "vegetationTrafficImpact")
                        ts  = find_field(vp, "treeSpacing")
                        sd  = find_field(vp, "stemDiameter")
                        if vti is None:
                            issues.append(
                                f"'{name}': no vegetationTrafficImpact "
                                "field — F3 will be NULL"
                            )
                        elif ts is None or sd is None:
                            issues.append(
                                f"'{name}': no treeSpacing/stemDiameter "
                                "— simplified F3 (VTI only)"
                            )
                        if extent_path:
                            try:
                                if not bboxes_overlap(
                                        arcpy.Describe(vp).extent,
                                        arcpy.Describe(extent_path).extent):
                                    issues.append(
                                        f"'{name}': does not overlap "
                                        "extent polygon"
                                    )
                            except Exception:
                                pass
                    if issues:
                        parameters[5].setWarningMessage(
                            "Vegetation layer notes:\n" +
                            "\n".join(f"  \u2022 {i}" for i in issues)
                        )
            except Exception:
                pass

        # ── [6] Hydro FCs (multivalue, optional) ──────────────────────────
        if parameters[6].value and not parameters[6].hasError():
            try:
                hydro_fcs = parameters[6].values
                if hydro_fcs:
                    issues = []
                    for h in hydro_fcs:
                        hp   = str(h)
                        name = os.path.basename(hp)
                        d    = safe_desc(hp)
                        if not d:
                            continue
                        if d.shapeType != "Polygon":
                            issues.append(
                                f"'{name}': geometry is '{d.shapeType}'.  "
                                "Hydro must be Polygon for the Union step — "
                                "buffer line/polyline features first."
                            )
                        if extent_path:
                            try:
                                if not bboxes_overlap(
                                        arcpy.Describe(hp).extent,
                                        arcpy.Describe(extent_path).extent):
                                    issues.append(
                                        f"'{name}': does not overlap "
                                        "extent polygon"
                                    )
                            except Exception:
                                pass
                    if issues:
                        parameters[6].setWarningMessage(
                            "Hydro layer issues:\n" +
                            "\n".join(f"  \u2022 {i}" for i in issues)
                        )
            except Exception:
                pass

        # ── [7] Vehicle CSV ────────────────────────────────────────────────
        if parameters[7].value and not parameters[7].hasError():
            csv_path = parameters[7].valueAsText
            if csv_path and os.path.isfile(csv_path):
                try:
                    df = read_csv_robust(csv_path)
                    required = [
                        "name", "max_off_road_grad", "max_on_road_grad",
                        "max_road_spd_kph", "vci_1", "vci_50",
                        "locomotion_type",
                    ]
                    missing = [h for h in required if h not in df.columns]
                    if missing:
                        parameters[7].setWarningMessage(
                            "Vehicle CSV missing required columns: "
                            f"{', '.join(missing)}"
                        )
                except Exception as e:
                    parameters[7].setWarningMessage(
                        f"Cannot read vehicle CSV: {e}"
                    )

        # ── [8] Selected vehicles vs CSV ───────────────────────────────────
        if (parameters[8].value and not parameters[8].hasError() and
                parameters[7].value and not parameters[7].hasError()):
            csv_path = parameters[7].valueAsText
            if csv_path and os.path.isfile(csv_path):
                try:
                    df = read_csv_robust(csv_path)
                    if "name" in df.columns:
                        selected  = [str(v) for v in
                                     (parameters[8].values or [])]
                        not_found = [
                            v for v in selected
                            if v not in df["name"].astype(str).tolist()
                        ]
                        if not_found:
                            parameters[8].setWarningMessage(
                                "Vehicle(s) not found in CSV: "
                                f"{', '.join(not_found)}"
                            )
                except Exception:
                    pass

        return

    # ── Main execution ─────────────────────────────────────────────────────────

    def execute(self, parameters, messages):
        arcpy.env.overwriteOutput = True                                # [R1]
        run_log = RunLog()                                              # [N2]

        # ── Retrieve parameters ────────────────────────────────────────────
        extent_fc          = parameters[0].valueAsText
        surface_config_fc  = parameters[1].valueAsText
        contours_fc        = parameters[2].valueAsText
        soil_fc            = parameters[3].valueAsText
        soil_moisture      = parameters[4].valueAsText
        vegetation_fcs     = parameters[5].values
        # [B1] FIX: check parameters[6] (hydro) not parameters[7] (vehicle csv)
        hydro_fcs          = parameters[6].values if parameters[6].altered else None
        vehicle_csv        = parameters[7].valueAsText
        selected_vehicles  = [str(v) for v in (parameters[8].values or [])]
        output_folder      = os.path.normpath(parameters[9].valueAsText)
        symbology_layer    = parameters[10].valueAsText

        # ── Projection guard ───────────────────────────────────────────────
        # [C3] All vector inputs must be in a Projected CRS
        arcpy.SetProgressorLabel("Validating input coordinate systems...")
        for fc_path, lbl in [
            (extent_fc,         "Extent Polygon"),
            (surface_config_fc, "Slope Region"),
            (soil_fc,           "Soil Layer"),
        ]:
            check_projection(fc_path, lbl)

        # ── Validate vehicle CSV ───────────────────────────────────────────
        arcpy.SetProgressorLabel("Reading vehicle CSV...")
        vehicle_df = read_csv_robust(vehicle_csv)                       # [R2]

        required_csv_headers = [
            "name", "max_off_road_grad", "max_on_road_grad",
            "max_road_spd_kph", "vci_1", "vci_50", "locomotion_type",
        ]
        missing_headers = [h for h in required_csv_headers
                           if h not in vehicle_df.columns]
        if missing_headers:
            raise ValueError(
                f"Vehicle CSV is missing required columns: "
                f"{', '.join(missing_headers)}"
            )
        arcpy.AddMessage("Vehicle CSV validated — all required columns present.")

        # ── Validate & coerce each selected vehicle record ─────────────────
        def validate_vehicle_record(record):
            """
            Checks for nulls and coerces numeric fields.
            Critical fields (speed, gradients, locomotion) → raise ValueError.
            Optional fields (VCI, width, override, turning radius) → warn only;
              downstream calculations will use NaN/fallback mode gracefully.
            """
            vname = record["name"]

            CRITICAL_FIELDS  = ["max_road_spd_kph", "max_on_road_grad",
                                 "max_off_road_grad", "locomotion_type"]
            OPTIONAL_FIELDS  = ["vci_1", "vci_50", "vehicle_width_m",
                                 "max_override_diameter_m", "min_turning_radius_m"]

            null_critical = [f for f in CRITICAL_FIELDS
                             if f in record.index and pd.isnull(record[f])]
            null_optional = [f for f in OPTIONAL_FIELDS
                             if f in record.index and pd.isnull(record[f])]

            if null_critical:
                raise ValueError(
                    f"Vehicle '{vname}' has NULL values in critical fields: "
                    f"{null_critical}.  These must be populated before running."
                )
            if null_optional:
                arcpy.AddWarning(
                    f"Vehicle '{vname}' has NULL values in optional fields: "
                    f"{null_optional}.  "
                    "Soil (F4/F5) or vegetation tree-spacing calculations will "
                    "fall back to NULL/simplified mode for affected factors."
                )
                run_log.log_vehicle_warn(vname, null_optional)         # [N2]
            expected_types = {
                "max_road_spd_kph":       int,
                "max_on_road_grad":        float,
                "max_off_road_grad":       float,
                "vehicle_width_m":         float,
                "max_override_diameter_m": float,
                "vci_1":                   float,
                "vci_50":                  float,
                "min_turning_radius_m":    float,
                "locomotion_type":         int,
            }
            for field, dtype in expected_types.items():
                if field not in record.index:
                    continue
                val = record[field]
                try:                                                     # [R3]
                    record[field] = dtype(val)
                except (TypeError, ValueError):
                    raise TypeError(
                        f"Field '{field}' in vehicle '{vname}' cannot be "
                        f"converted to {dtype.__name__}.  Got: {val!r}"
                    )
            return record

        def combine_vehicle_records(records):
            combined = records[0].copy()
            for rec in records[1:]:
                combined["max_road_spd_kph"]       = min(combined["max_road_spd_kph"],       rec["max_road_spd_kph"])
                combined["max_on_road_grad"]        = min(combined["max_on_road_grad"],        rec["max_on_road_grad"])
                combined["max_off_road_grad"]       = min(combined["max_off_road_grad"],       rec["max_off_road_grad"])
                combined["vehicle_width_m"]         = max(combined["vehicle_width_m"],         rec["vehicle_width_m"])
                combined["max_override_diameter_m"] = min(combined["max_override_diameter_m"], rec["max_override_diameter_m"])
                combined["vci_1"]                   = min(combined["vci_1"],                   rec["vci_1"])
                combined["vci_50"]                  = min(combined["vci_50"],                  rec["vci_50"])
                combined["min_turning_radius_m"]    = max(combined["min_turning_radius_m"],    rec["min_turning_radius_m"])
                combined["locomotion_type"]         = min(combined["locomotion_type"],         rec["locomotion_type"])
            return combined

        if not selected_vehicles:
            raise ValueError("No vehicles selected.")

        vehicle_records = []
        vehicle_selection = "_".join(selected_vehicles)
        for vname in selected_vehicles:
            match = vehicle_df.loc[vehicle_df["name"].astype(str) == vname]
            if match.empty:
                raise ValueError(
                    f"Vehicle '{vname}' not found in CSV.  "
                    f"Available: {vehicle_df['name'].tolist()}"
                )
            record = validate_vehicle_record(match.iloc[0])
            vehicle_records.append(record)

        final_vehicle = (
            combine_vehicle_records(vehicle_records)
            if len(vehicle_records) > 1
            else vehicle_records[0]
        )
        arcpy.AddMessage(f"Vehicle record finalised:\n{final_vehicle.to_string()}")

        # ── Output GDB setup ───────────────────────────────────────────────
        arcpy.SetProgressorLabel("Setting up output geodatabase...")
        if not os.path.exists(output_folder):
            os.makedirs(output_folder)
        gdb_base = f"CCM_{vehicle_selection}_{soil_moisture}"
        gdb_name = f"{gdb_base}.gdb"
        output_gdb = os.path.normpath(os.path.join(output_folder, gdb_name))

        if arcpy.Exists(output_gdb):
            arcpy.AddMessage(f"Using existing GDB: {output_gdb}")
        else:
            arcpy.management.CreateFileGDB(output_folder, gdb_name)
            arcpy.AddMessage(f"Created GDB: {output_gdb}")

        arcpy.env.workspace = output_gdb                               # set after GDB exists

        # ── Utility functions ──────────────────────────────────────────────
        def delete_fields(fc, keep_fields):
            """Drops all fields NOT in keep_fields."""
            to_drop = [
                f.name for f in arcpy.ListFields(fc)
                if f.name not in keep_fields
            ]
            if to_drop:
                arcpy.management.DeleteField(fc, to_drop)

        def clip_feature_class(in_fc, clip_fc, out_fc):
            """Clips in_fc to clip_fc, validates output, raises on failure."""
            try:
                arcpy.analysis.Clip(in_fc, clip_fc, out_fc)
                if (not arcpy.Exists(out_fc) or
                        int(arcpy.management.GetCount(out_fc)[0]) == 0):
                    arcpy.AddWarning(
                        f"Clip output '{out_fc}' is empty — verify spatial "
                        f"overlap between '{in_fc}' and the extent polygon."
                    )
                    raise ValueError(f"Clipped FC '{out_fc}' is empty.")
                return out_fc
            except arcpy.ExecuteError:
                arcpy.AddError(
                    f"ArcPy failed to clip '{in_fc}'.  "
                    "Check for locked data or projection mismatch."
                )
                raise

        def fill_gaps_in_feature_class(output_fc, extent_fc_path):
            """
            [C4] Fills spatial gaps between output_fc and the extent polygon.
            Uses Dissolve (geoprocessing, C++ accelerated) to reduce the
            output FC to a single geometry before the difference operation.
            This replaces the previous iterative Python .union() loop which
            was O(n) geometry operations and extremely slow on large datasets.
            Appends a single NULL-attribute feature for any uncovered area.
            Requires only Basic licence (Dissolve is available at all levels).
            """
            # Build union of extent polygon(s) — extent is usually 1 feature
            extent_geom = None
            with arcpy.da.SearchCursor(extent_fc_path, ["SHAPE@"]) as cur:
                for row in cur:
                    if row[0]:
                        extent_geom = (
                            row[0] if extent_geom is None
                            else extent_geom.union(row[0])
                        )
            if extent_geom is None:
                arcpy.AddWarning("Gap fill skipped: extent polygon is empty.")
                return

            # Dissolve output_fc into a single geometry (one fast GP call
            # instead of N iterative Python .union() calls).
            fc_name   = os.path.basename(output_fc)
            diss_tmp  = os.path.join(arcpy.env.scratchGDB,
                                     f"_ccm_gap_diss_{fc_name}")
            try:
                if arcpy.Exists(diss_tmp):
                    arcpy.management.Delete(diss_tmp)
                arcpy.management.Dissolve(output_fc, diss_tmp)

                covered_geom = None
                with arcpy.da.SearchCursor(diss_tmp, ["SHAPE@"]) as cur:
                    for row in cur:
                        if row[0]:
                            covered_geom = row[0]
                            break          # Dissolve → always 1 output row
            finally:
                if arcpy.Exists(diss_tmp):
                    arcpy.management.Delete(diss_tmp)

            # Compute gap geometry
            if covered_geom is not None:
                gap_geom = extent_geom.difference(covered_geom)
            else:
                gap_geom = extent_geom  # nothing covered at all

            if gap_geom is None or gap_geom.area == 0:
                return

            # Insert a NULL-attribute row for the gap area
            with arcpy.da.InsertCursor(output_fc, ["SHAPE@"]) as ins:
                ins.insertRow([gap_geom])
            arcpy.AddMessage(
                f"Gap fill: added {gap_geom.area:,.1f} m² of uncovered "
                f"area to '{os.path.basename(output_fc)}'."
            )

        # ── Discover actual field names via aliases ─────────────────────────
        # [C1] All field references now use discovered names, not hardcoded strings.
        arcpy.SetProgressorLabel("Discovering field names...")

        slope_field = find_field(surface_config_fc, "surfaceSlope")
        if slope_field is None:
            raise ValueError(
                "No 'surfaceSlope' field (or recognised alias) found in the "
                "Slope Region feature class.  "
                f"Fields present: {[f.name for f in arcpy.ListFields(surface_config_fc)]}"
            )
        if slope_field != "surfaceSlope":
            arcpy.AddMessage(f"Using '{slope_field}' as alias for 'surfaceSlope'.")
            run_log.log_alias("surfaceSlope", slope_field, "Slope Region")  # [N2]

        soil_type_field = find_field(soil_fc, "soilType")
        if soil_type_field is None:
            raise ValueError(
                "No 'soilType' field (or recognised alias) found in the "
                "Soil feature class.  "
                f"Fields present: {[f.name for f in arcpy.ListFields(soil_fc)]}"
            )
        if soil_type_field != "soilType":
            arcpy.AddMessage(f"Using '{soil_type_field}' as alias for 'soilType'.")
            run_log.log_alias("soilType", soil_type_field, "Soil Layer")    # [N2]

        # Contour elevation field [C1]
        elev_field = find_field(contours_fc, "highestElevation") if contours_fc else None
        if contours_fc and elev_field is None:
            arcpy.AddWarning(
                "No elevation field (highestElevation or alias) found in "
                "Contours FC.  Contour normalisation will be skipped "
                "(normalization_factor defaults to 1)."
            )
        elif contours_fc and elev_field != "highestElevation":
            arcpy.AddMessage(
                f"Using '{elev_field}' as alias for 'highestElevation' in contours."
            )
            run_log.log_alias("highestElevation", elev_field, "Contours") # [N2]

        # ── Validate required fields ───────────────────────────────────────
        arcpy.SetProgressorLabel("Validating input field schema...")

        slope_fc_fields = [f.name for f in arcpy.ListFields(surface_config_fc)]
        if slope_field not in slope_fc_fields:
            raise ValueError(f"Slope field '{slope_field}' missing from slope FC.")

        soil_fc_fields = [f.name for f in arcpy.ListFields(soil_fc)]
        if soil_type_field not in soil_fc_fields:
            raise ValueError(f"Soil type field '{soil_type_field}' missing from soil FC.")

        for veg_fc in vegetation_fcs:
            veg_fc_path = str(veg_fc)
            vti_field = find_field(veg_fc_path, "vegetationTrafficImpact")
            if vti_field is None:
                arcpy.AddWarning(
                    f"Vegetation FC '{veg_fc_path}' has no 'vegetationTrafficImpact' "
                    "field (or alias) — F3 will be NULL for features in this layer."
                )
                run_log.log_gap(                                        # [N2]
                    f"vegetationTrafficImpact not found in "
                    f"'{os.path.basename(veg_fc_path)}' — "
                    "F3 NULL for all features in this layer"
                )

        # ── Clip and prepare slope ─────────────────────────────────────────
        arcpy.SetProgressorLabel("Clipping and preparing slope layer...")
        surface_config_clipped = clip_feature_class(
            surface_config_fc, extent_fc,
            os.path.join(output_gdb, "surface_config_clipped"),
        )

        # Rename slope alias field to 'surfaceSlope' in the clipped copy
        # so all downstream code can use the canonical name.
        if slope_field != "surfaceSlope":
            arcpy.management.AlterField(
                surface_config_clipped, slope_field,
                "surfaceSlope", "surfaceSlope",
            )
            arcpy.AddMessage(
                f"Renamed field '{slope_field}' → 'surfaceSlope' in clipped layer."
            )

        # Add poly_id for contour intercept calculations
        arcpy.management.AddField(surface_config_clipped, "poly_id", "LONG")
        with arcpy.da.UpdateCursor(surface_config_clipped, ["poly_id"]) as cur:
            for pid, row in enumerate(cur, start=1):
                row[0] = pid
                cur.updateRow(row)

        arcpy.management.AddField(surface_config_clipped, "intercept_Average", "DOUBLE")

        # ── Contour intercept calculation ──────────────────────────────────
        arcpy.SetProgressorLabel("Computing contour intercept averages...")
        if contours_fc and elev_field:
            elevs = []
            with arcpy.da.SearchCursor(contours_fc, [elev_field]) as cur:
                for row in cur:
                    if row[0] is not None:
                        elevs.append(row[0])
            unique_elev = sorted(set(elevs))
            if len(unique_elev) > 1:
                diffs = [abs(unique_elev[i + 1] - unique_elev[i])
                         for i in range(len(unique_elev) - 1)]
                avg_diff = sum(diffs) / len(diffs)
            else:
                avg_diff = 20
            normalization_factor = 20 / avg_diff if avg_diff != 0 else 1

            temp_intersect = os.path.join("memory", "temp_intersect")    # [B6]
            arcpy.analysis.Intersect(
                [surface_config_clipped, contours_fc],
                temp_intersect, "ALL", "", "LINE",
            )

            poly_counts = {}
            with arcpy.da.SearchCursor(temp_intersect, ["poly_id"]) as cur:
                for row in cur:
                    pid = row[0]
                    poly_counts[pid] = poly_counts.get(pid, 0) + 1

            def get_slope_category(slope):
                if slope is None:
                    return "0-3%"
                if slope <= 3:   return "0-3%"
                if slope <= 10:  return "3-10%"
                if slope <= 20:  return "10-20%"
                if slope <= 30:  return "20-30%"
                if slope <= 45:  return "30-45%"
                return ">45%"

            category_counts  = {}
            poly_category    = {}
            with arcpy.da.SearchCursor(
                    surface_config_clipped, ["poly_id", "surfaceSlope"]) as cur:
                for row in cur:
                    pid = row[0]
                    cat = get_slope_category(row[1])
                    poly_category[pid] = cat
                    cnt = poly_counts.get(pid, 0)
                    category_counts.setdefault(cat, []).append(cnt)

            category_average = {
                cat: (sum(counts) / len(counts) if counts else 0)
                for cat, counts in category_counts.items()
            }

            with arcpy.da.UpdateCursor(
                    surface_config_clipped,
                    ["poly_id", "intercept_Average", "surfaceSlope"]) as cur:
                for row in cur:
                    cat = poly_category.get(row[0])
                    row[1] = (category_average[cat] * normalization_factor
                              if cat else 0)
                    cur.updateRow(row)

            if arcpy.Exists(temp_intersect):
                arcpy.management.Delete(temp_intersect)
        else:
            # No contour data or no elevation field — set intercept_Average = 0
            with arcpy.da.UpdateCursor(
                    surface_config_clipped, ["intercept_Average"]) as cur:
                for row in cur:
                    row[0] = 0
                    cur.updateRow(row)
            arcpy.AddWarning(
                "Contour intercept calculation skipped — "
                "F2 terrain roughness factor will be set to 1.0 everywhere."
            )

        # ── Clip and prepare soil ──────────────────────────────────────────
        arcpy.SetProgressorLabel("Clipping and preparing soil layer...")
        soil_clipped = clip_feature_class(
            soil_fc, extent_fc,
            os.path.join(output_gdb, "soil_clipped"),
        )

        # Rename soil alias field to 'soilType' in the clipped copy
        if soil_type_field != "soilType":
            arcpy.management.AlterField(
                soil_clipped, soil_type_field, "soilType", "soilType",
            )
            arcpy.AddMessage(
                f"Renamed field '{soil_type_field}' → 'soilType' in clipped layer."
            )

        delete_fields(soil_clipped,
                      ["OBJECTID", "Shape", "Shape_Length", "Shape_Area", "soilType"])
        delete_fields(surface_config_clipped,
                      ["OBJECTID", "Shape", "Shape_Length", "Shape_Area",
                       "surfaceSlope", "poly_id", "intercept_Average"])

        # ── Clip and prepare vegetation layers ─────────────────────────────
        arcpy.SetProgressorLabel("Clipping vegetation layers...")
        clipped_veg_fcs = []
        for veg_fc in vegetation_fcs:
            veg_path = str(veg_fc)
            clipped = clip_feature_class(
                veg_path, extent_fc,
                os.path.join(output_gdb,
                             f"{os.path.basename(veg_path)}_clipped"),
            )
            clipped_veg_fcs.append(clipped)

        # Standardise vegetation field aliases in clipped copies
        for clipped in clipped_veg_fcs:
            for canonical in ("vegetationTrafficImpact", "treeSpacing", "stemDiameter"):
                actual = find_field(clipped, canonical)
                if actual and actual != canonical:
                    arcpy.management.AlterField(
                        clipped, actual, canonical, canonical,
                    )
                    arcpy.AddMessage(
                        f"Renamed '{actual}' → '{canonical}' in "
                        f"'{os.path.basename(clipped)}'."
                    )
                    run_log.log_alias(                                  # [N2]
                        canonical, actual, os.path.basename(clipped)
                    )

        for clipped in clipped_veg_fcs:
            fnames = [f.name for f in arcpy.ListFields(clipped)]
            keep = ["OBJECTID", "Shape", "Shape_Length", "Shape_Area"]
            for fn in ("treeSpacing", "stemDiameter", "vegetationTrafficImpact"):
                if fn in fnames:
                    keep.append(fn)
            delete_fields(clipped, keep)

        # ── Create output feature classes ──────────────────────────────────
        arcpy.SetProgressorLabel("Creating output feature classes...")
        spatial_ref = arcpy.Describe(surface_config_fc).spatialReference

        surface_config_out = os.path.join(output_gdb, "surface_config_fc")
        soil_out           = os.path.join(output_gdb, "soil_fc")
        vegetation_out     = os.path.join(output_gdb, "vegetation_surface_fc")
        speed_surface_fc   = os.path.join(
            output_gdb,
            f"speed_surface_{vehicle_selection}_{soil_moisture}",
        )

        # Surface config output
        arcpy.management.CreateFeatureclass(
            output_gdb, "surface_config_fc", "POLYGON",
            surface_config_clipped, spatial_reference=spatial_ref,
        )
        for fld in [("F1", "DOUBLE"), ("F2", "DOUBLE"), ("F1_2", "DOUBLE"),
                    ("surfaceSlope", "DOUBLE")]:
            arcpy.management.AddField(surface_config_out, fld[0], fld[1])
        for fld, ftype in [("poly_id", "LONG"), ("intercept_Average", "DOUBLE")]:
            if fld not in [f.name for f in arcpy.ListFields(surface_config_out)]:
                arcpy.management.AddField(surface_config_out, fld, ftype)

        # Vegetation output
        arcpy.management.CreateFeatureclass(
            output_gdb, "vegetation_surface_fc", "POLYGON",
            spatial_reference=spatial_ref,
        )
        for fld, ftype in [("F3", "DOUBLE"), ("treeSpacing", "DOUBLE"),
                            ("stemDiameter", "DOUBLE"),
                            ("vegetationTrafficImpact", "DOUBLE")]:
            arcpy.management.AddField(vegetation_out, fld, ftype)

        # Soil output
        arcpy.management.CreateFeatureclass(
            output_gdb, "soil_fc", "POLYGON",
            soil_clipped, spatial_reference=spatial_ref,
        )
        for fld, ftype in [("F4", "DOUBLE"), ("F5", "DOUBLE"), ("rci", "DOUBLE")]:
            arcpy.management.AddField(soil_out, fld, ftype)

        # ── RCI lookup table ───────────────────────────────────────────────
        rci_soils_dict = {
            "wellGradedGravel":     {"soils_category": "GW",    "rci_dry": 163, "rci_moist": 123, "rci_wet": 83,  "F5_tracked": 0.70, "F5_wheeled": 0.90},
            "poorlyGradedGravel":   {"soils_category": "GP",    "rci_dry": 160, "rci_moist": 120, "rci_wet": 81,  "F5_tracked": 0.65, "F5_wheeled": 0.85},
            "siltyGravelSand":      {"soils_category": "GM",    "rci_dry": 120, "rci_moist": 76,  "rci_wet": 32,  "F5_tracked": 0.80, "F5_wheeled": 1.00},
            "clayeyGravel":         {"soils_category": "GC",    "rci_dry": 130, "rci_moist": 91,  "rci_wet": 52,  "F5_tracked": 0.75, "F5_wheeled": 0.95},
            "wellGradedSand":       {"soils_category": "SW",    "rci_dry": 155, "rci_moist": 116, "rci_wet": 78,  "F5_tracked": 0.60, "F5_wheeled": 0.80},
            "poorlyGradedSand":     {"soils_category": "SP",    "rci_dry": 145, "rci_moist": 109, "rci_wet": 73,  "F5_tracked": 0.55, "F5_wheeled": 0.75},
            "siltySand":            {"soils_category": "SM",    "rci_dry": 119, "rci_moist": 72,  "rci_wet": 25,  "F5_tracked": 0.90, "F5_wheeled": 1.00},
            "clayeySand":           {"soils_category": "SC",    "rci_dry": 126, "rci_moist": 86,  "rci_wet": 46,  "F5_tracked": 0.85, "F5_wheeled": 1.00},
            "siltAndFineSand":      {"soils_category": "ML",    "rci_dry": 118, "rci_moist": 69,  "rci_wet": 20,  "F5_tracked": 1.00, "F5_wheeled": 1.00},
            "leanClay":             {"soils_category": "CL",    "rci_dry": 123, "rci_moist": 81,  "rci_wet": 40,  "F5_tracked": 0.95, "F5_wheeled": 1.00},
            "organicSiltandClay":   {"soils_category": "OL",    "rci_dry": 111, "rci_moist": 57,  "rci_wet": 3,   "F5_tracked": 1.00, "F5_wheeled": 1.00},
            "fatClay":              {"soils_category": "CH",    "rci_dry": 136, "rci_moist": 99,  "rci_wet": 62,  "F5_tracked": 0.90, "F5_wheeled": 1.00},
            "micaceous":            {"soils_category": "MH",    "rci_dry": 114, "rci_moist": 61,  "rci_wet": 8,   "F5_tracked": 1.00, "F5_wheeled": 1.00},
            "organicClay":          {"soils_category": "OH",    "rci_dry": 107, "rci_moist": 54,  "rci_wet": 1,   "F5_tracked": 1.00, "F5_wheeled": 1.00},
            "peat":                 {"soils_category": "PT",    "rci_dry": 106, "rci_moist": 52,  "rci_wet": 0,   "F5_tracked": 1.00, "F5_wheeled": 1.00},
            "siltFineSandLeanClay": {"soils_category": "ML-CL", "rci_dry": 116, "rci_moist": 67,  "rci_wet": 18,  "F5_tracked": 1.00, "F5_wheeled": 1.00},
            "evaporite":            {"soils_category": "EV",    "rci_dry": 0,   "rci_moist": 0,   "rci_wet": 0,   "F5_tracked": 0.00, "F5_wheeled": 0.00},
            "rock":                 {"soils_category": "RK",    "rci_dry": 165, "rci_moist": 165, "rci_wet": 165, "F5_tracked": 0.50, "F5_wheeled": 0.70},
            "notEvaluated":         {"soils_category": "NE",    "rci_dry": None,"rci_moist": None,"rci_wet": None,"F5_tracked": None, "F5_wheeled": None},
        }

        # ── Factor calculation functions ───────────────────────────────────

        def calculate_speed_slope_factor(surface_slope, intercept_avg,
                                          max_offroad_grad, max_onroad_grad,
                                          max_speed):
            if surface_slope is None:
                surface_slope = math.nan
            F1 = (max_offroad_grad - surface_slope) / (max_onroad_grad / max_speed)
            F1 = max(0.0, F1)
            F2 = (280 - intercept_avg) / 280
            F2 = max(0.0, F2)                                          # [B4]
            F1_2 = F1 * F2
            return F1, F2, F1_2

        def calculate_vegetation_factor(treeSpacing, stemDiameter,
                                         vegetationTrafficImpact, W, OD, MTR, fc_name):
            # NOTE: per-feature AddMessage/log_gap calls removed (v2.23).
            # Counters are accumulated by the calling loop and reported once
            # per FC, keeping the message pane clean on large datasets.
            if vegetationTrafficImpact is None:
                return None
            if treeSpacing is None or stemDiameter is None or treeSpacing <= 0:
                return vegetationTrafficImpact

            # V1 — manoeuvring between trees
            numerator = treeSpacing - stemDiameter - W
            if W >= treeSpacing or numerator <= 0:
                V1 = 0.0
            else:
                VF  = min(max(numerator / (4 * W),   0.0), 1.0)
                denom_v1a = MTR - W
                if denom_v1a <= 0:                                      # [R4]
                    V1a = 0.0
                else:
                    V1a = min(max(numerator / denom_v1a, 0.0), 1.0)
                V1 = VF * V1a

            # V2 — overriding / crushing trees
            if stemDiameter >= OD or treeSpacing <= 0:
                V2 = 0.0
            else:
                VT = max((W + stemDiameter) / treeSpacing, 1.0)
                V2 = 1.0 - (VT * ((stemDiameter ** 2 - OD ** 2) / treeSpacing))
                V2 = max(min(V2, 1.0), 0.0)

            manoeuvre = max(V1, V2)
            F3 = max(0.0, min(vegetationTrafficImpact * manoeuvre, 1.0))
            return F3

        def calculate_soil_factor(raw_soil_type, VCI1, VCI50, moisture):
            # [C2] Normalise soil type before lookup
            soil_key = normalize_soil_type(raw_soil_type)
            if soil_key not in rci_soils_dict:
                raise KeyError(
                    f"soilType '{raw_soil_type}' (normalised: '{soil_key}') "
                    "not found in RCI table.  "
                    f"Valid keys: {list(rci_soils_dict.keys())}"
                )
            loco = "tracked" if int(final_vehicle["locomotion_type"]) == 1 else "wheeled"
            entry = rci_soils_dict[soil_key]
            F5  = entry[f"F5_{loco}"]
            RCI = entry.get(f"rci_{moisture}")
            if RCI is None:
                raise KeyError(
                    f"No RCI value for soilType '{soil_key}' / "
                    f"moisture '{moisture}'."
                )
            F4 = (RCI - VCI1) / (VCI50 - VCI1) if VCI50 != VCI1 else 0.0
            return min(1.0, max(F4, 0.0)), F5, float(RCI)

        # ── Insert slope data ──────────────────────────────────────────────
        arcpy.SetProgressorLabel("Computing slope factors (F1, F2)...")
        with (
            arcpy.da.SearchCursor(
                surface_config_clipped,
                ["SHAPE@", "surfaceSlope", "intercept_Average", "poly_id"],
            ) as src,
            arcpy.da.InsertCursor(
                surface_config_out,
                ["SHAPE@", "F1", "F2", "F1_2", "surfaceSlope",
                 "poly_id", "intercept_Average"],
            ) as ins,
        ):
            for row in src:
                F1, F2, F1_2 = calculate_speed_slope_factor(
                    row[1], row[2],
                    final_vehicle["max_off_road_grad"],
                    final_vehicle["max_on_road_grad"],
                    final_vehicle["max_road_spd_kph"],
                )
                ins.insertRow([row[0], F1, F2, F1_2, row[1], row[3], row[2]])

        # ── Insert soil data ───────────────────────────────────────────────
        arcpy.SetProgressorLabel("Computing soil factors (F4, F5)...")
        with (
            arcpy.da.SearchCursor(soil_clipped, ["SHAPE@", "soilType"]) as src,
            arcpy.da.InsertCursor(soil_out, ["SHAPE@", "F4", "F5", "rci"]) as ins,
        ):                                                               # [B5]
            for row in src:
                soil_val = row[1]
                if soil_val is None:
                    arcpy.AddWarning("Soil feature has NULL soilType — F4/F5 set to NULL.")
                    run_log.log_null_soil()                             # [N2]
                    ins.insertRow((row[0], math.nan, math.nan, math.nan))
                    continue
                try:
                    F4, F5, rci_val = calculate_soil_factor(
                        soil_val,
                        final_vehicle["vci_1"],
                        final_vehicle["vci_50"],
                        soil_moisture,
                    )
                    ins.insertRow((row[0], F4, F5, rci_val))
                except (KeyError, ValueError) as exc:
                    arcpy.AddWarning(
                        f"soilType '{soil_val}' unrecognised ({exc}) — "
                        "F4/F5 set to NULL for this feature.  "
                        "Check SOIL_TYPE_ALIASES in the script to add a mapping."
                    )
                    run_log.log_unknown_soil(str(soil_val))             # [N2]
                    ins.insertRow((row[0], math.nan, math.nan, math.nan))

        # ── Insert vegetation data ─────────────────────────────────────────
        arcpy.SetProgressorLabel("Computing vegetation factors (F3)...")
        W   = final_vehicle["vehicle_width_m"]
        OD  = final_vehicle["max_override_diameter_m"]
        MTR = final_vehicle["min_turning_radius_m"]

        with arcpy.da.InsertCursor(
            vegetation_out,
            ["SHAPE@", "F3", "treeSpacing", "stemDiameter", "vegetationTrafficImpact"],
        ) as ins:
            for clipped in clipped_veg_fcs:
                fnames = [f.name for f in arcpy.ListFields(clipped)]
                has_ts  = "treeSpacing"             in fnames
                has_sd  = "stemDiameter"             in fnames
                has_vti = "vegetationTrafficImpact"  in fnames
                fc_label = os.path.basename(clipped)

                if has_ts and has_sd and has_vti:
                    # Per-FC counters (replaces per-feature AddMessage spam)
                    n_total = n_vti_only = n_null_vti = 0
                    with arcpy.da.SearchCursor(
                        clipped,
                        ["SHAPE@", "treeSpacing", "stemDiameter",
                         "vegetationTrafficImpact"],
                    ) as src:
                        for row in src:
                            n_total += 1
                            vti, ts, sd = row[3], row[1], row[2]
                            if vti is None:
                                n_null_vti += 1
                            elif ts is None or sd is None or ts <= 0:
                                n_vti_only += 1
                            F3 = calculate_vegetation_factor(
                                ts, sd, vti, W, OD, MTR, clipped
                            )
                            F3 = math.nan if F3 is None else F3
                            ins.insertRow((row[0], F3, ts, sd, vti))
                    # One summary message per FC instead of one per feature
                    arcpy.AddMessage(
                        f"'{fc_label}': {n_total} features processed — "
                        f"{n_total - n_vti_only - n_null_vti} full F3, "
                        f"{n_vti_only} VTI-only (treeSpacing=0/missing), "
                        f"{n_null_vti} NULL VTI."
                    )
                    if n_vti_only:
                        run_log.log_gap(
                            f"'{fc_label}': {n_vti_only}/{n_total} features used "
                            "VTI-only F3 (treeSpacing zero or missing — non-forest areas)"
                        )
                    if n_null_vti:
                        run_log.log_gap(
                            f"'{fc_label}': {n_null_vti}/{n_total} features had "
                            "NULL vegetationTrafficImpact — F3 set to NULL"
                        )

                elif has_vti:
                    arcpy.AddMessage(
                        f"'{fc_label}': using vegetationTrafficImpact only "
                        "(no treeSpacing/stemDiameter fields in this FC)."
                    )
                    with arcpy.da.SearchCursor(
                        clipped, ["SHAPE@", "vegetationTrafficImpact"]
                    ) as src:
                        for row in src:
                            F3 = row[1] if row[1] is not None else math.nan
                            ins.insertRow((row[0], F3, None, None, row[1]))

                else:
                    arcpy.AddWarning(
                        f"'{fc_label}': no vegetation fields found — "
                        "F3 set to NULL for all features."
                    )
                    run_log.log_gap(
                        f"'{fc_label}': no vegetation fields "
                        "(no VTI, treeSpacing, or stemDiameter) — "
                        "F3 NULL for all features"
                    )
                    with arcpy.da.SearchCursor(clipped, ["SHAPE@"]) as src:
                        for row in src:
                            ins.insertRow((row[0], math.nan, None, None, None))

        # ── Clean up temp clipped FCs ──────────────────────────────────────
        for tmp in clipped_veg_fcs + [surface_config_clipped, soil_clipped]:
            if arcpy.Exists(tmp):
                arcpy.management.Delete(tmp)

        # ── Gap filling ────────────────────────────────────────────────────
        # [C4] Fill spatial gaps in all three base layers so the union
        # produces complete AOI coverage (gaps appear as NULL-attribute areas).
        arcpy.SetProgressorLabel("Filling spatial gaps in output layers...")
        fill_gaps_in_feature_class(vegetation_out,     extent_fc)
        fill_gaps_in_feature_class(surface_config_out, extent_fc)
        fill_gaps_in_feature_class(soil_out,           extent_fc)

        # ── Hydro processing ───────────────────────────────────────────────
        hydro_out = None
        if hydro_fcs:
            arcpy.SetProgressorLabel("Processing hydro layers...")
            clipped_hydro_fcs = []
            for hydro_fc in hydro_fcs:
                hydro_path = str(hydro_fc)
                clipped_h = clip_feature_class(
                    hydro_path, extent_fc,
                    os.path.join(output_gdb,
                                 f"{os.path.basename(hydro_path)}_clipped"),
                )
                # [B2] FIX: delete fields from the CLIPPED copy, not the source
                delete_fields(clipped_h,
                              ["OBJECTID", "Shape", "Shape_Length", "Shape_Area"])
                clipped_hydro_fcs.append(clipped_h)

            hydro_out = os.path.join(output_gdb, "hydro_fc")
            arcpy.management.CreateFeatureclass(
                output_gdb, "hydro_fc", "POLYGON",
                clipped_hydro_fcs[0], spatial_reference=spatial_ref,
            )
            arcpy.management.AddField(hydro_out, "is_hydro", "SHORT")
            with arcpy.da.InsertCursor(hydro_out, ["SHAPE@", "is_hydro"]) as ins:
                for clipped_h in clipped_hydro_fcs:
                    with arcpy.da.SearchCursor(clipped_h, ["SHAPE@"]) as src:
                        for row in src:
                            ins.insertRow([row[0], 1])
            for clipped_h in clipped_hydro_fcs:
                if arcpy.Exists(clipped_h):
                    arcpy.management.Delete(clipped_h)

        # ── Union all layers ───────────────────────────────────────────────
        arcpy.SetProgressorLabel("Running Union to create speed surface...")
        union_inputs = [vegetation_out, soil_out, surface_config_out]
        if hydro_out:
            union_inputs.append(hydro_out)
        arcpy.analysis.Union(union_inputs, speed_surface_fc, "ALL")

        arcpy.management.AddField(speed_surface_fc, "speed_kph", "DOUBLE")
        arcpy.management.AddField(speed_surface_fc, "Mobility",  "TEXT")

        # ── Speed and mobility classification ─────────────────────────────
        arcpy.SetProgressorLabel("Calculating speed and mobility classification...")

        speed_code = (
            "def calc_speed(F1_2, F3, F4, F5):\n"
            "    if F1_2 is None or F3 is None or F4 is None or F5 is None:\n"
            "        return None\n"
            "    return F1_2 * F3 * F4 * F5\n"
        )
        mob_code = (
            "def classify_mobility(F1_2, F3, F4, F5, speed):\n"
            "    nulls = []\n"
            "    if F1_2 is None: nulls.append('Slope')\n"
            "    if F3  is None: nulls.append('Vegetation')\n"
            "    if F4  is None: nulls.append('Soils')\n"
            "    if F5  is None: nulls.append('Surface Roughness')\n"
            "    if nulls:\n"
            "        return 'Missing ' + ', '.join(nulls) + ' Coverage'\n"
            "    if speed == 0:\n"
            "        zeros = []\n"
            "        if F1_2 == 0: zeros.append('Slope')\n"
            "        if F3  == 0: zeros.append('Vegetation')\n"
            "        if F4  == 0: zeros.append('Soils')\n"
            "        if zeros:\n"
            "            return 'NO GO - ' + ', '.join(zeros)\n"
            "        return 'NO GO'\n"
            "    if speed >= 30:  return 'GO'\n"
            "    if speed >= 15:  return 'RESTRICTED'\n"
            "    if speed >= 5:   return 'SLOW'\n"
            "    if speed >= 1.5: return 'VERY SLOW'\n"
            "    return 'NO GO'\n"
        )

        arcpy.management.CalculateField(
            speed_surface_fc, "speed_kph",
            "calc_speed(!F1_2!, !F3!, !F4!, !F5!)", "PYTHON3", speed_code,
        )
        arcpy.management.CalculateField(
            speed_surface_fc, "Mobility",
            "classify_mobility(!F1_2!, !F3!, !F4!, !F5!, !speed_kph!)",
            "PYTHON3", mob_code,
        )

        # Override hydro features to NO GO
        if hydro_out:
            with arcpy.da.UpdateCursor(
                    speed_surface_fc, ["is_hydro", "Mobility", "speed_kph"]) as cur:
                for row in cur:
                    if row[0] == 1:
                        row[1] = "NO GO - Hydro Feature"
                        row[2] = 0
                        cur.updateRow(row)

        # ── Tally output coverage for the run summary ──────────────────────
        # [N2] Done AFTER hydro override so labels are final
        arcpy.SetProgressorLabel("Tallying output coverage...")
        with arcpy.da.SearchCursor(speed_surface_fc, ["Mobility"]) as cur:
            for row in cur:
                label = row[0] if row[0] else "Unclassified"
                run_log.log_coverage(label)

        # Clean up intermediate factor FCs (retain only speed surface)
        delete_fields(
            speed_surface_fc,
            ["OBJECTID", "Shape", "Shape_Length", "Shape_Area",
             "speed_kph", "F1", "F2", "F1_2", "F3", "F4", "F5",
             "Mobility"],
        )

        # ── Apply symbology and save layer file ────────────────────────────
        if symbology_layer:                                              # [B3]
            arcpy.SetProgressorLabel("Applying symbology...")
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            layer_name = f"{vehicle_selection}_{soil_moisture}_{ts}"
            lyrx_path  = os.path.join(
                output_folder,
                f"CCM_{vehicle_selection}_{soil_moisture}_{ts}.lyrx",
            )
            if arcpy.Exists(layer_name):
                arcpy.management.Delete(layer_name)
            arcpy.ClearWorkspaceCache_management()
            try:
                aprx = arcpy.mp.ArcGISProject("CURRENT")
                for mv in aprx.listMaps():
                    mv.clearSelection()
            except Exception:
                pass  # Not running inside an active ArcGIS Pro project session
            arcpy.management.MakeFeatureLayer(speed_surface_fc, layer_name)
            arcpy.management.ApplySymbologyFromLayer(layer_name, symbology_layer)
            arcpy.management.SaveToLayerFile(layer_name, lyrx_path)
            arcpy.AddMessage(
                f"Symbology applied and saved: {lyrx_path}"
            )
        else:
            arcpy.AddMessage(
                "No symbology layer provided — skipping layer file creation.  "
                "You can apply symbology manually using the Mobility_Symbology.lyrx "
                "in the Symbology folder."
            )

        run_log.print_summary(                                          # [N2]
            output_gdb, speed_surface_fc, selected_vehicles, soil_moisture
        )
        return

    # ── Post-execution cleanup ─────────────────────────────────────────────

    def postExecute(self, parameters):
        arcpy.ClearWorkspaceCache_management()
        arcpy.env.workspace = None
        return


# ─────────────────────────────────────────────────────────────────────────────
# VALIDATION TOOL  (the "Test before Run" companion to CCMTool)
# ─────────────────────────────────────────────────────────────────────────────


# ── V1 Validator Engine (was CCMValidateTool in V1) ──────────────────────

class _CCMValidateEngineV1:
    """
    Pre-run validation tool for the MCE CCM workflow.

    Runs the same comprehensive checks as the live updateMessages() dialog
    validation, but also performs deeper inspections that are too slow for
    real-time use — full soil-value enumeration, coordinate-system consistency
    across all layers, spatial-overlap verification for every layer, and a
    vehicle-record completeness audit.

    Output is a structured PASS / WARN / FAIL report printed to the
    ArcGIS Pro geoprocessing messages pane.  No output data is written;
    the tool is read-only and safe to re-run as many times as needed.
    """

    def __init__(self):
        self.label       = "Validate CCM Inputs"
        self.description = (
            "Performs comprehensive pre-run validation of all CCM inputs and "
            "prints a PASS / WARN / FAIL report to the messages pane.  "
            "No output data is created — use this tool before running the "
            "main CCM tool to confirm your data is ready."
        )
        self.canRunInBackground = False

    # ── Parameters  (mirrors CCMTool params 0-8, omits output folder & symbology) ──

    def getParameterInfo(self):
        params = []

        # [0] Extent polygon
        p = arcpy.Parameter(
            displayName="Extent Polygon Feature Class",
            name="extent_fc",
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Input",
        )
        params.append(p)

        # [1] Slope
        p = arcpy.Parameter(
            displayName="Slope Feature Class",
            name="slope_fc",
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Input",
        )
        params.append(p)

        # [2] Contours
        p = arcpy.Parameter(
            displayName="Contour Feature Class",
            name="contour_fc",
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Input",
        )
        params.append(p)

        # [3] Soil
        p = arcpy.Parameter(
            displayName="Soil Feature Class",
            name="soil_fc",
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Input",
        )
        params.append(p)

        # [4] Soil moisture condition
        p = arcpy.Parameter(
            displayName="Soil Moisture Condition",
            name="soil_moisture",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
        )
        p.filter.type = "ValueList"
        p.filter.list = ["Dry", "Wet"]
        params.append(p)

        # [5] Vegetation (multivalue)
        p = arcpy.Parameter(
            displayName="Vegetation Feature Class(es)",
            name="vegetation_fcs",
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Input",
            multiValue=True,
        )
        params.append(p)

        # [6] Hydro (multivalue, optional)
        p = arcpy.Parameter(
            displayName="Hydro Feature Class(es)  [Optional]",
            name="hydro_fcs",
            datatype="DEFeatureClass",
            parameterType="Optional",
            direction="Input",
            multiValue=True,
        )
        params.append(p)

        # [7] Vehicle CSV
        p = arcpy.Parameter(
            displayName="Vehicle Capabilities CSV",
            name="vehicle_csv",
            datatype="DEFile",
            parameterType="Required",
            direction="Input",
        )
        p.filter.list = ["csv"]
        params.append(p)

        # [8] Vehicle selection (multivalue, populated from CSV)
        p = arcpy.Parameter(
            displayName="Select Vehicle(s)",
            name="vehicle_selection",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
            multiValue=True,
        )
        params.append(p)

        return params

    # ── Populate vehicle list from CSV (same as CCMTool) ──────────────────────

    def updateParameters(self, parameters):
        if parameters[7].altered and not parameters[7].hasBeenValidated:
            csv_path = parameters[7].valueAsText
            if csv_path and os.path.isfile(csv_path):
                try:
                    df = read_csv_robust(csv_path)
                    if "vehicle_type" in df.columns:
                        names = sorted(df["vehicle_type"].dropna().unique().tolist())
                        parameters[8].filter.type = "ValueList"
                        parameters[8].filter.list = names
                except Exception:
                    pass
        return

    def updateMessages(self, parameters):
        return

    # ── execute  ──────────────────────────────────────────────────────────────

    def execute(self, parameters, messages):  # noqa: C901
        """
        Runs all validation checks and prints a structured report.
        Nothing is written to disk.
        """

        # ── Helper: emit a pass/warn/fail line ────────────────────────────────
        PASS  = "  [PASS]"
        WARN  = "  [WARN]"
        FAIL  = "  [FAIL]"
        INFO  = "  [INFO]"
        SEP   = "─" * 62

        results = {"pass": 0, "warn": 0, "fail": 0}

        def ok(msg):
            results["pass"] += 1
            arcpy.AddMessage(f"{PASS}  {msg}")

        def warn(msg):
            results["warn"] += 1
            arcpy.AddWarning(f"{WARN}  {msg}")

        def fail(msg):
            results["fail"] += 1
            arcpy.AddError(f"{FAIL}  {msg}")

        def info(msg):
            arcpy.AddMessage(f"{INFO}  {msg}")

        def section(title):
            arcpy.AddMessage("")
            arcpy.AddMessage(SEP)
            arcpy.AddMessage(f"  {title}")
            arcpy.AddMessage(SEP)

        # ── Collect inputs ────────────────────────────────────────────────────
        extent_fc    = parameters[0].valueAsText
        slope_fc     = parameters[1].valueAsText
        contour_fc   = parameters[2].valueAsText
        soil_fc      = parameters[3].valueAsText
        soil_moisture= parameters[4].valueAsText
        veg_raw      = parameters[5].valueAsText or ""
        hydro_raw    = parameters[6].valueAsText or ""
        vehicle_csv  = parameters[7].valueAsText
        veh_raw      = parameters[8].valueAsText or ""

        def split_multi(raw):
            """Split a multivalue parameter string into a clean list."""
            if not raw:
                return []
            parts = [p.strip().strip("'\"") for p in raw.split(";")]
            return [p for p in parts if p]

        veg_fcs   = split_multi(veg_raw)
        hydro_fcs = split_multi(hydro_raw)
        veh_names = split_multi(veh_raw)

        arcpy.AddMessage("")
        arcpy.AddMessage("=" * 62)
        arcpy.AddMessage("  MCE CCM — PRE-RUN VALIDATION REPORT")
        arcpy.AddMessage(f"  {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}")
        arcpy.AddMessage("=" * 62)

        # ─────────────────────────────────────────────────────────────────────
        # 1. COORDINATE SYSTEMS
        # ─────────────────────────────────────────────────────────────────────
        section("1 / 6   COORDINATE SYSTEMS")

        named_layers = [
            ("Extent",  extent_fc),
            ("Slope",   slope_fc),
            ("Contours",contour_fc),
            ("Soil",    soil_fc),
        ]
        for i, vfc in enumerate(veg_fcs, 1):
            named_layers.append((f"Vegetation[{i}]", vfc))
        for i, hfc in enumerate(hydro_fcs, 1):
            named_layers.append((f"Hydro[{i}]", hfc))

        wkids   = {}   # label → wkid string
        wkt_map = {}   # label → wkt (for human display)

        for label, fc in named_layers:
            if not fc or not arcpy.Exists(fc):
                fail(f"{label}: path does not exist or is not accessible")
                continue
            try:
                sr = arcpy.Describe(fc).spatialReference
                is_geo = (sr.type == "Geographic")
                wkids[label]   = str(sr.factoryCode)
                wkt_map[label] = sr.name
                if is_geo:
                    fail(f"{label}: GEOGRAPHIC CRS ({sr.name})  — reproject to a projected CRS before running CCM")
                else:
                    ok(f"{label}: projected CRS  →  {sr.name}  [WKID {sr.factoryCode}]")
            except Exception as e:
                fail(f"{label}: could not read spatial reference  — {e}")

        # Consistency check — are all layers in the same CRS?
        unique_wkids = set(v for v in wkids.values() if v != "0")
        if len(unique_wkids) > 1:
            warn("Layers are in DIFFERENT projected coordinate systems:")
            for lbl, wkid in wkids.items():
                arcpy.AddMessage(f"       {lbl:20s}  WKID {wkid}  ({wkt_map.get(lbl,'')})")
            arcpy.AddMessage("       → ArcGIS Pro can reproject on-the-fly, but for best")
            arcpy.AddMessage("         accuracy reproject all layers to the same CRS first.")
        elif len(unique_wkids) == 1:
            ok(f"All layers share the same projected CRS  [WKID {list(unique_wkids)[0]}]")

        # ─────────────────────────────────────────────────────────────────────
        # 2. GEOMETRY TYPES & FEATURE COUNTS
        # ─────────────────────────────────────────────────────────────────────
        section("2 / 6   GEOMETRY TYPES & FEATURE COUNTS")

        required_geom = {
            "Extent":   "Polygon",
            "Slope":    "Polygon",
            "Contours": None,          # Polyline or Polygon accepted
            "Soil":     "Polygon",
        }

        def check_geom_and_count(label, fc, expected_geom=None, hydro_mode=False):
            if not fc or not arcpy.Exists(fc):
                return
            try:
                desc  = arcpy.Describe(fc)
                gtype = desc.shapeType
                count = int(arcpy.management.GetCount(fc).getOutput(0))

                if count == 0:
                    fail(f"{label}: feature class is EMPTY (0 features)")
                else:
                    info(f"{label}: {count:,} feature(s)  —  geometry = {gtype}")

                if expected_geom and gtype != expected_geom:
                    warn(f"{label}: expected {expected_geom} but found {gtype}")
                if hydro_mode and gtype != "Polygon":
                    fail(f"{label}: Hydro MUST be Polygon for the Union step  (found {gtype})")
                    ok_geom = False
                else:
                    ok_geom = True

                if count > 0 and (not expected_geom or gtype == expected_geom) and ok_geom:
                    ok(f"{label}: geometry type OK ({gtype})")
            except Exception as e:
                fail(f"{label}: could not inspect geometry — {e}")

        check_geom_and_count("Extent",   extent_fc,   "Polygon")
        check_geom_and_count("Slope",    slope_fc,    "Polygon")
        check_geom_and_count("Contours", contour_fc,  None)
        check_geom_and_count("Soil",     soil_fc,     "Polygon")
        for i, vfc in enumerate(veg_fcs, 1):
            check_geom_and_count(f"Vegetation[{i}]", vfc, "Polygon")
        for i, hfc in enumerate(hydro_fcs, 1):
            check_geom_and_count(f"Hydro[{i}]", hfc, None, hydro_mode=True)

        # ─────────────────────────────────────────────────────────────────────
        # 3. REQUIRED FIELDS
        # ─────────────────────────────────────────────────────────────────────
        section("3 / 6   REQUIRED FIELDS")

        def check_field(label, fc, canonical):
            if not fc or not arcpy.Exists(fc):
                return None
            found = find_field(fc, canonical)
            if found is None:
                aliases = FIELD_ALIASES.get(canonical, [])
                fail(
                    f"{label}: field '{canonical}' NOT FOUND.  "
                    f"Checked aliases: {', '.join(aliases[:6])}"
                    + ("…" if len(aliases) > 6 else "")
                )
                return None
            if found == canonical:
                ok(f"{label}: '{canonical}' found  ✓")
            else:
                warn(
                    f"{label}: '{canonical}' NOT found by exact name — "
                    f"using alias '{found}'.  "
                    f"(Field will be renamed in the clipped copy — original data is NOT modified.)"
                )
            return found

        # Slope
        check_field("Slope",    slope_fc,   "surfaceSlope")
        # Contours
        check_field("Contours", contour_fc, "highestElevation")
        # Soil
        check_field("Soil",     soil_fc,    "soilType")
        # Vegetation — all three fields required
        for i, vfc in enumerate(veg_fcs, 1):
            lbl = f"Vegetation[{i}]"
            check_field(lbl, vfc, "vegetationTrafficImpact")
            vts_found = find_field(vfc, "treeSpacing")  if arcpy.Exists(vfc) else None
            vsd_found = find_field(vfc, "stemDiameter") if arcpy.Exists(vfc) else None
            if vts_found and vsd_found:
                info(f"{lbl}: treeSpacing ('{vts_found}') and stemDiameter ('{vsd_found}') present — advanced vegetation model enabled")
            elif not vts_found and not vsd_found:
                info(f"{lbl}: treeSpacing and stemDiameter absent — simplified vegetation model will be used")
            elif not vts_found:
                warn(f"{lbl}: treeSpacing absent but stemDiameter present — simplified model forced")
            else:
                warn(f"{lbl}: stemDiameter absent but treeSpacing present — simplified model forced")

        # ─────────────────────────────────────────────────────────────────────
        # 4. SOIL TYPE VALUES
        # ─────────────────────────────────────────────────────────────────────
        section("4 / 6   SOIL TYPE VALUES")

        if soil_fc and arcpy.Exists(soil_fc):
            soil_field = find_field(soil_fc, "soilType")
            if soil_field:
                try:
                    raw_vals = set()
                    with arcpy.da.SearchCursor(soil_fc, [soil_field]) as cur:
                        for row in cur:
                            v = row[0]
                            if v is not None:
                                raw_vals.add(str(v).strip())

                    info(f"Unique soilType values found ({len(raw_vals)}):")
                    known_canonical = {
                        "wellGradedGravel","poorlyGradedGravel","siltyGravelSand",
                        "clayeyGravel","wellGradedSand","poorlyGradedSand",
                        "siltySand","clayeySand","siltAndFineSand","leanClay",
                        "organicSiltandClay","fatClay","micaceous","organicClay",
                        "peat","siltFineSandLeanClay","evaporite","rock","notEvaluated",
                    }
                    unknowns = []
                    for v in sorted(raw_vals):
                        canonical = normalize_soil_type(v)
                        if canonical in known_canonical:
                            arcpy.AddMessage(f"       '{v}'  →  '{canonical}'  ✓")
                        else:
                            unknowns.append(v)
                            arcpy.AddMessage(f"       '{v}'  →  UNKNOWN  ✗")
                    if unknowns:
                        warn(
                            f"{len(unknowns)} unrecognised soilType value(s): "
                            + ", ".join(f"'{u}'" for u in unknowns)
                            + ".  These will produce NULL RCI scores.  "
                            "Add them to SOIL_TYPE_ALIASES in the script to fix."
                        )
                    else:
                        ok(f"All {len(raw_vals)} soilType value(s) map to recognised canonical keys")
                except Exception as e:
                    warn(f"Could not enumerate soilType values: {e}")
            else:
                fail("Soil: soilType field not found — skipping value check")
        else:
            fail("Soil: feature class not accessible — skipping value check")

        # ─────────────────────────────────────────────────────────────────────
        # 5. SPATIAL OVERLAP  (extent vs all layers)
        # ─────────────────────────────────────────────────────────────────────
        section("5 / 6   SPATIAL OVERLAP WITH EXTENT")

        if extent_fc and arcpy.Exists(extent_fc):
            try:
                ext_env = arcpy.Describe(extent_fc).extent
                overlap_layers = [
                    ("Slope",    slope_fc),
                    ("Contours", contour_fc),
                    ("Soil",     soil_fc),
                ]
                for i, vfc in enumerate(veg_fcs, 1):
                    overlap_layers.append((f"Vegetation[{i}]", vfc))
                for i, hfc in enumerate(hydro_fcs, 1):
                    overlap_layers.append((f"Hydro[{i}]", hfc))

                for label, fc in overlap_layers:
                    if not fc or not arcpy.Exists(fc):
                        continue
                    try:
                        lyr_ext = arcpy.Describe(fc).extent
                        # Bounding-box overlap test
                        overlap = not (
                            lyr_ext.XMax < ext_env.XMin or
                            lyr_ext.XMin > ext_env.XMax or
                            lyr_ext.YMax < ext_env.YMin or
                            lyr_ext.YMin > ext_env.YMax
                        )
                        if overlap:
                            ok(f"{label}: bounding box overlaps extent  ✓")
                        else:
                            fail(
                                f"{label}: bounding box does NOT overlap the extent polygon.  "
                                f"Extent  [{ext_env.XMin:.1f},{ext_env.YMin:.1f} → "
                                f"{ext_env.XMax:.1f},{ext_env.YMax:.1f}]  |  "
                                f"Layer   [{lyr_ext.XMin:.1f},{lyr_ext.YMin:.1f} → "
                                f"{lyr_ext.XMax:.1f},{lyr_ext.YMax:.1f}]"
                            )
                    except Exception as e:
                        warn(f"{label}: could not check spatial overlap — {e}")
            except Exception as e:
                warn(f"Could not read extent bounding box — {e}")
        else:
            fail("Extent feature class not accessible — skipping overlap checks")

        # ─────────────────────────────────────────────────────────────────────
        # 6. VEHICLE RECORDS
        # ─────────────────────────────────────────────────────────────────────
        section("6 / 6   VEHICLE RECORDS")

        CRITICAL_VEH_FIELDS = [
            "vehicle_type", "max_road_spd_kph", "max_on_road_grad",
            "max_off_road_grad", "locomotion_type",
        ]
        OPTIONAL_VEH_FIELDS = [
            "vci_1", "vci_50", "vehicle_width_m",
            "max_override_diameter_m", "min_turning_radius_m",
        ]
        ALL_VEH_FIELDS = CRITICAL_VEH_FIELDS + OPTIONAL_VEH_FIELDS

        if vehicle_csv and os.path.isfile(vehicle_csv):
            try:
                df = read_csv_robust(vehicle_csv)
                csv_cols_lower = [c.lower() for c in df.columns]

                # Column presence check
                missing_critical = [f for f in CRITICAL_VEH_FIELDS if f not in csv_cols_lower]
                missing_optional = [f for f in OPTIONAL_VEH_FIELDS if f not in csv_cols_lower]

                if missing_critical:
                    fail(f"Vehicle CSV missing CRITICAL columns: {', '.join(missing_critical)}")
                else:
                    ok(f"Vehicle CSV: all critical columns present")

                if missing_optional:
                    warn(f"Vehicle CSV missing optional columns: {', '.join(missing_optional)}")
                else:
                    ok(f"Vehicle CSV: all optional columns present")

                # Normalise column names for lookup
                df.columns = [c.lower() for c in df.columns]

                # Per-vehicle record checks
                if veh_names:
                    info(f"Checking {len(veh_names)} selected vehicle(s)...")
                    for vname in veh_names:
                        row_df = df[df["vehicle_type"] == vname] if "vehicle_type" in df.columns else pd.DataFrame()
                        if row_df.empty:
                            fail(f"  Vehicle '{vname}': NOT FOUND in CSV")
                            continue
                        row = row_df.iloc[0]

                        # Critical fields
                        crit_nulls = [f for f in CRITICAL_VEH_FIELDS if f in row.index and (pd.isna(row[f]) or str(row[f]).strip() == "")]
                        # Optional fields
                        opt_nulls  = [f for f in OPTIONAL_VEH_FIELDS  if f in row.index and (pd.isna(row[f]) or str(row[f]).strip() == "")]

                        if crit_nulls:
                            fail(f"  Vehicle '{vname}': NULL critical field(s): {', '.join(crit_nulls)}")
                        else:
                            ok(f"  Vehicle '{vname}': all critical fields populated")

                        if opt_nulls:
                            warn(
                                f"  Vehicle '{vname}': NULL optional field(s): {', '.join(opt_nulls)}.  "
                                f"Affected F-factors (F4/F5 or tree-spacing model) will use fallback/NULL mode."
                            )
                        else:
                            ok(f"  Vehicle '{vname}': all optional fields populated")

                        # locomotion_type value check
                        if "locomotion_type" in row.index:
                            loco = str(row["locomotion_type"]).strip().lower()
                            valid_loco = {"tracked", "wheeled", "foot"}
                            if loco not in valid_loco:
                                warn(f"  Vehicle '{vname}': locomotion_type='{row['locomotion_type']}' — expected one of: {', '.join(sorted(valid_loco))}")
                            else:
                                ok(f"  Vehicle '{vname}': locomotion_type='{row['locomotion_type']}'  ✓")

                        # V1a denominator guard preview
                        if "min_turning_radius_m" in row.index and "vehicle_width_m" in row.index:
                            try:
                                mtr = float(row["min_turning_radius_m"])
                                vw  = float(row["vehicle_width_m"])
                                if mtr <= vw:
                                    warn(
                                        f"  Vehicle '{vname}': min_turning_radius_m ({mtr}) ≤ vehicle_width_m ({vw}) — "
                                        f"V1a will be set to 0 (ZeroDivision guard active)"
                                    )
                            except (ValueError, TypeError):
                                pass  # nulls already flagged above
                else:
                    warn("No vehicles selected — skipping per-vehicle record checks")

            except Exception as e:
                fail(f"Could not read vehicle CSV: {e}")
        else:
            fail(f"Vehicle CSV not found or not accessible: {vehicle_csv}")

        # ─────────────────────────────────────────────────────────────────────
        # SUMMARY
        # ─────────────────────────────────────────────────────────────────────
        arcpy.AddMessage("")
        arcpy.AddMessage("=" * 62)
        arcpy.AddMessage("  VALIDATION SUMMARY")
        arcpy.AddMessage("=" * 62)
        arcpy.AddMessage(f"  PASS : {results['pass']}")
        arcpy.AddMessage(f"  WARN : {results['warn']}")
        arcpy.AddMessage(f"  FAIL : {results['fail']}")
        arcpy.AddMessage("=" * 62)

        if results["fail"] > 0:
            arcpy.AddMessage("")
            arcpy.AddError(
                f"  ✗  {results['fail']} FAIL(s) detected — the CCM tool will likely "
                f"crash or produce incorrect results.  Fix the issues above before running."
            )
        elif results["warn"] > 0:
            arcpy.AddMessage("")
            arcpy.AddWarning(
                f"  ⚠  {results['warn']} WARNING(s) detected — the CCM tool will run "
                f"but some inputs may produce degraded or unexpected output.  "
                f"Review the warnings above."
            )
        else:
            arcpy.AddMessage("")
            arcpy.AddMessage(
                "  ✓  All checks passed — your inputs look ready for the CCM tool."
            )
        arcpy.AddMessage("=" * 62)
        return

    def postExecute(self, parameters):
        return


# ── End of merged V1 engine ──────────────────────────────────────────────


# ── Load Phase 2 modules ──────────────────────────────────────────────────────
_CCMReasonMapTool      = None
_CCMIsochroneTool      = None
_CCMVehicleCompareTool = None
_CCMObstacleDetectTool = None
_CCMWaypointTool       = None
_weather_mod           = None
_coords_mod            = None

try:
    import ccm_coords as _coords_mod
except Exception as e:
    print(f"[CCM V2] ccm_coords: {e}")

try:
    from ccm_reason_map    import CCMReasonMapTool      as _CCMReasonMapTool
except Exception as e:
    print(f"[CCM V2] ccm_reason_map: {e}")
try:
    from ccm_isochrone     import CCMIsochroneTool      as _CCMIsochroneTool
except Exception as e:
    print(f"[CCM V2] ccm_isochrone: {e}")
try:
    from ccm_vehicle_compare import CCMVehicleCompareTool as _CCMVehicleCompareTool
except Exception as e:
    print(f"[CCM V2] ccm_vehicle_compare: {e}")
try:
    from ccm_obstacle_detect import CCMObstacleDetectTool as _CCMObstacleDetectTool
except Exception as e:
    print(f"[CCM V2] ccm_obstacle_detect: {e}")
try:
    from ccm_waypoints     import CCMWaypointTool       as _CCMWaypointTool
except Exception as e:
    print(f"[CCM V2] ccm_waypoints: {e}")
try:
    import ccm_weather as _weather_mod
except Exception as e:
    print(f"[CCM V2] ccm_weather: {e}")
    _weather_mod = None

_soil_validator_mod = None
try:
    import ccm_soil_validator as _soil_validator_mod
except Exception as e:
    print(f"[CCM V2] ccm_soil_validator: {e}")

_CCMSoilPreprocessTool = None
try:
    from ccm_soil_preprocess import CCMSoilPreprocessTool as _CCMSoilPreprocessTool
except Exception as e:
    print(f"[CCM V2] ccm_soil_preprocess: {e}")

_CCMVegPreprocessTool = None
try:
    from ccm_veg_preprocess import CCMVegPreprocessTool as _CCMVegPreprocessTool
except Exception as e:
    print(f"[CCM V2] ccm_veg_preprocess: {e}")

# ── Load project config helper (used by inline CCMStep2MobilityTool) ─────────
_cfg_mod = None
try:
    import ccm_project_config as _cfg_mod
except Exception as e:
    print(f"[CCM V2] ccm_project_config: {e}")

# ── Load 3-Step Workflow tools ────────────────────────────────────────────────
# CCMStep2MobilityTool is defined inline (no external file) so it can access
# _V1CCMTool, _v1_read_csv, _cfg_mod, etc. as V2.pyt module globals.
_CCMStep1SetupTool    = None
_CCMStep3AdvancedTool = None

try:
    from ccm_step1_setup    import CCMStep1SetupTool    as _CCMStep1SetupTool
except Exception as e:
    print(f"[CCM V2] ccm_step1_setup: {e}")
try:
    from ccm_step3_advanced import CCMStep3AdvancedTool as _CCMStep3AdvancedTool
except Exception as e:
    print(f"[CCM V2] ccm_step3_advanced: {e}")


# ── Minimal parameter shim so V2 params can be forwarded to V1's execute() ───

class _P:
    """
    Mimics the arcpy.Parameter interface used by V1's execute().
    Supports:  .value  .valueAsText  .values (multiValue)  .altered
    """
    def __init__(self, value, value_as_text=None, values=None, altered=True):
        self.value       = value
        self.valueAsText = value_as_text if value_as_text is not None \
                           else (str(value) if value else None)
        self.values      = values
        self.altered     = altered


# ── Small helpers used in smart-warning checks ────────────────────────────────

def _ff(fc, canonical):
    """Thin wrapper — calls the merged V1 find_field() directly."""
    return find_field(fc, canonical)


def _bboxes_overlap(ext_a, ext_b):
    return not (ext_a.XMax < ext_b.XMin or ext_a.XMin > ext_b.XMax or
                ext_a.YMax < ext_b.YMin or ext_a.YMin > ext_b.YMax)


def _safe_desc(path):
    try:
        return arcpy.Describe(path)
    except Exception:
        return None


def _overlap_warn(fc_path, extent_path, label, param):
    try:
        if not _bboxes_overlap(arcpy.Describe(fc_path).extent,
                               arcpy.Describe(extent_path).extent):
            param.setWarningMessage(
                f"{label} does not spatially overlap the Analysis Extent.  "
                "Features outside the extent are ignored — check your data."
            )
    except Exception:
        pass


# =============================================================================
# CCMTool V2  —  redesigned layout + smart warnings + V1 delegation
# =============================================================================

class CCMTool:

    def __init__(self):
        self.label              = "2.  Generate Mobility Map"
        self.description        = (
            "Cross Country Mobility analysis.  Computes a speed surface for "
            "one or more vehicles based on terrain, soil, vegetation, and "
            "hydrology inputs."
        )
        self.canRunInBackground = False

    # =========================================================================
    # getParameterInfo — clean 3-section layout
    # =========================================================================

    def getParameterInfo(self):

        # ── SECTION 1  Essential Inputs (no category — shows first) ──────────

        p_extent = arcpy.Parameter(
            displayName   = "Analysis Extent  (study area polygon)",
            name          = "extent_fc",
            datatype      = "DEFeatureClass",
            parameterType = "Required",
            direction     = "Input",
        )

        p_dem = arcpy.Parameter(
            displayName   = "DEM  (Digital Elevation Model raster)  [optional if Slope Regions provided]",
            name          = "dem_raster",
            datatype      = "DERasterDataset",
            parameterType = "Optional",
            direction     = "Input",
        )

        p_slope = arcpy.Parameter(
            displayName   = "Slope Regions  (polygon FC with slope values)  [optional if DEM provided]",
            name          = "slope_regions_fc",
            datatype      = "DEFeatureClass",
            parameterType = "Optional",
            direction     = "Input",
        )

        p_soil = arcpy.Parameter(
            displayName   = "Soil Data  (polygon FC with soil type field)",
            name          = "soil_fc",
            datatype      = "DEFeatureClass",
            parameterType = "Required",
            direction     = "Input",
        )

        p_veg = arcpy.Parameter(
            displayName   = "Vegetation Layers  (one or more polygon FCs)",
            name          = "vegetation_fcs",
            datatype      = "GPFeatureLayer",
            parameterType = "Required",
            direction     = "Input",
            multiValue    = True,
        )

        p_hydro = arcpy.Parameter(
            displayName   = "Hydrology Layers  (optional — polygon FCs for water bodies)",
            name          = "hydro_fcs",
            datatype      = "GPFeatureLayer",
            parameterType = "Optional",
            direction     = "Input",
            multiValue    = True,
        )

        p_moisture = arcpy.Parameter(
            displayName   = "Soil Moisture Condition",
            name          = "soil_moisture",
            datatype      = "GPString",
            parameterType = "Required",
            direction     = "Input",
        )
        p_moisture.filter.type = "ValueList"
        p_moisture.filter.list = ["dry", "moist", "wet"]
        p_moisture.value       = "dry"

        p_csv = arcpy.Parameter(
            displayName   = "Vehicle Definitions CSV",
            name          = "vehicle_csv",
            datatype      = "DEFile",
            parameterType = "Required",
            direction     = "Input",
        )

        p_vehicles = arcpy.Parameter(
            displayName   = "Select Vehicle(s)",
            name          = "select_vehicles",
            datatype      = "GPString",
            parameterType = "Required",
            direction     = "Input",
            multiValue    = True,
        )
        p_vehicles.filter.type = "ValueList"
        p_vehicles.filter.list = []

        p_output = arcpy.Parameter(
            displayName   = "Output Folder",
            name          = "output_folder",
            datatype      = "DEFolder",
            parameterType = "Required",
            direction     = "Output",
        )

        # ── SECTION 2  Optional Data ──────────────────────────────────────────

        p_contours = arcpy.Parameter(
            displayName   = "Contour Lines  (helps normalise vegetation height)",
            name          = "contours_fc",
            datatype      = "DEFeatureClass",
            parameterType = "Optional",
            direction     = "Input",
            category      = "Optional Data",
        )

        # ── SECTION 3  Advanced Options ───────────────────────────────────────

        p_symbology = arcpy.Parameter(
            displayName   = "Symbology Layer  (.lyrx)",
            name          = "symbology_lyrx",
            datatype      = "DEFile",
            parameterType = "Optional",
            direction     = "Input",
            category      = "Advanced Options",
        )

        p_weather = arcpy.Parameter(
            displayName   = "Enable Live Weather Adjustment  (requires internet)",
            name          = "enable_live_weather",
            datatype      = "GPBoolean",
            parameterType = "Optional",
            direction     = "Input",
            category      = "Advanced Options",
        )
        p_weather.value = False

        p_rain = arcpy.Parameter(
            displayName   = "Manual Rainfall Override  (mm / 24 h — blank = use live data)",
            name          = "manual_rainfall_mm",
            datatype      = "GPDouble",
            parameterType = "Optional",
            direction     = "Input",
            category      = "Advanced Options",
        )
        p_rain.value   = None
        p_rain.enabled = False

        # indices:  0        1      2        3       4      5
        return [p_extent, p_dem, p_slope, p_soil, p_veg, p_hydro,
        #         6           7      8           9         10
                p_moisture, p_csv, p_vehicles, p_output, p_contours,
        #         11           12         13
                p_symbology, p_weather, p_rain]

    def isLicensed(self):
        return True

    # =========================================================================
    # updateParameters — dynamic behaviour (vehicle list from CSV)
    # =========================================================================

    def updateParameters(self, parameters):
        p_csv      = parameters[7]
        p_vehicles = parameters[8]
        p_weather  = parameters[12]
        p_rain     = parameters[13]

        # Populate vehicle picker from CSV whenever a CSV path is present.
        # Do NOT gate on p_csv.altered — that flag resets when other parameters
        # are touched, which would clear the vehicle list unexpectedly.
        if p_csv.value:
            csv_path = p_csv.valueAsText
            if csv_path and os.path.isfile(csv_path):
                names = []
                # Strategy 1: use pandas read_csv_robust (always available)
                try:
                    df = read_csv_robust(csv_path)
                    if "name" in df.columns:
                        names = df["name"].astype(str).tolist()
                except Exception:
                    pass
                # Strategy 2: built-in csv module — no pandas dependency
                if not names:
                    try:
                        import csv as _csv
                        for enc in ("utf-8", "latin-1", "cp1252"):
                            try:
                                with open(csv_path, newline="",
                                          encoding=enc) as fh:
                                    reader = _csv.DictReader(fh)
                                    if reader.fieldnames and "name" in reader.fieldnames:
                                        names = [r["name"] for r in reader
                                                 if r.get("name", "").strip()]
                                break
                            except UnicodeDecodeError:
                                continue
                    except Exception:
                        pass
                if names and p_vehicles.filter.list != names:
                    p_vehicles.filter.list = names

        # Enable manual rainfall only when weather toggle is on
        p_rain.enabled = bool(p_weather.value)

    # =========================================================================
    # updateMessages — smart warnings
    # =========================================================================

    def updateMessages(self, parameters):

        p_extent   = parameters[0]
        p_dem      = parameters[1]
        p_slope    = parameters[2]
        p_soil     = parameters[3]
        p_veg      = parameters[4]
        p_hydro    = parameters[5]
        p_csv      = parameters[7]
        p_vehicles = parameters[8]
        p_contours = parameters[10]

        extent_path = p_extent.valueAsText if p_extent.value else None

        # ── Extent ────────────────────────────────────────────────────────────
        if p_extent.value and not p_extent.hasError():
            d = _safe_desc(p_extent.valueAsText)
            if d:
                if d.shapeType != "Polygon":
                    p_extent.setErrorMessage(
                        f"Analysis Extent must be a Polygon FC (got '{d.shapeType}')."
                    )
                elif d.spatialReference.type == "Geographic":
                    p_extent.setErrorMessage(
                        f"Analysis Extent uses a Geographic CRS ({d.spatialReference.name}).  "
                        "All inputs must use a Projected CRS (e.g. UTM).  "
                        "Use the Project tool to reproject first."
                    )

        # ── DEM + Slope ───────────────────────────────────────────────────────
        if not p_dem.value and not p_slope.value:
            msg = (
                "Provide either a DEM raster or a Slope Regions feature class.  "
                "At least one terrain input is required to compute the slope "
                "factor (F1)."
            )
            p_dem.setWarningMessage(msg)
            p_slope.setWarningMessage(msg)

        elif p_dem.value and not p_slope.value:
            p_dem.setWarningMessage(
                "DEM detected — Slope Regions will be derived automatically "
                "using the Slope tool (requires Spatial Analyst licence).  "
                "If SA is unavailable, F1 will default to 1.0 (no slope penalty)."
            )

        if p_slope.value and not p_slope.hasError():
            slope_path = p_slope.valueAsText
            d = _safe_desc(slope_path)
            if d:
                if d.spatialReference.type == "Geographic":
                    p_slope.setErrorMessage(
                        f"Slope Regions use a Geographic CRS ({d.spatialReference.name}).  "
                        "Reproject to a Projected CRS first."
                    )
                elif d.shapeType != "Polygon":
                    p_slope.setWarningMessage(
                        f"Slope Regions geometry is '{d.shapeType}' — Polygon expected."
                    )
                else:
                    sf = _ff(slope_path, "surfaceSlope")
                    if sf is None:
                        avail = ", ".join(
                            f.name for f in arcpy.ListFields(slope_path)
                            if f.type not in ("OID", "Geometry")
                        )
                        p_slope.setErrorMessage(
                            "No slope field found.  Expected: 'surfaceSlope' (or common aliases: "
                            "'slope', 'slope_pct', 'gradient').  "
                            f"Fields available in this FC: {avail or '(none)'}"
                        )
                    elif sf != "surfaceSlope":
                        p_slope.setWarningMessage(
                            f"'surfaceSlope' not found — using '{sf}' as alias.  "
                            "Rename to 'surfaceSlope' to suppress this warning."
                        )
                    if extent_path and not p_slope.hasError():
                        _overlap_warn(slope_path, extent_path, "Slope Regions", p_slope)

        # ── Soil ──────────────────────────────────────────────────────────────
        if p_soil.value and not p_soil.hasError():
            soil_path = p_soil.valueAsText
            d = _safe_desc(soil_path)
            if d:
                if d.spatialReference.type == "Geographic":
                    p_soil.setErrorMessage(
                        f"Soil layer uses a Geographic CRS ({d.spatialReference.name}).  "
                        "Reproject to a Projected CRS first."
                    )
                elif d.shapeType != "Polygon":
                    p_soil.setWarningMessage(
                        f"Soil layer geometry is '{d.shapeType}' — Polygon expected."
                    )
                else:
                    # ── 4-level automated soil field validator ─────────────────
                    if _soil_validator_mod:
                        try:
                            is_error, msg = _soil_validator_mod.get_soil_warning_for_ui(
                                soil_path
                            )
                            if is_error:
                                p_soil.setErrorMessage(msg)
                            elif msg:
                                p_soil.setWarningMessage(msg)
                        except Exception as exc:
                            p_soil.setWarningMessage(
                                f"Soil field check encountered an error: {exc}"
                            )
                    else:
                        # Fallback: basic single-field check (validator not loaded)
                        sf = _ff(soil_path, "soilType")
                        if sf is None:
                            avail = ", ".join(
                                f.name for f in arcpy.ListFields(soil_path)
                                if f.type not in ("OID", "Geometry")
                            )
                            p_soil.setErrorMessage(
                                "No soil type field found.  Expected: 'soilType' (or aliases: "
                                "'soil_type', 'soil_class', 'uscs').  Without this field the "
                                "soil bearing capacity factors (F4 dry RCI, F5 wet RCI) cannot "
                                f"be computed.  Fields available: {avail or '(none)'}"
                            )
                        elif sf != "soilType":
                            p_soil.setWarningMessage(
                                f"'soilType' not found — using '{sf}' as alias.  "
                                "Rename to 'soilType' to suppress this warning."
                            )
                if extent_path and not p_soil.hasError():
                    _overlap_warn(soil_path, extent_path, "Soil layer", p_soil)

        # ── Vegetation ────────────────────────────────────────────────────────
        if p_veg.value and not p_veg.hasError():
            try:
                veg_list = p_veg.values or []
                issues   = []
                for v in veg_list:
                    vp   = str(v)
                    name = os.path.basename(vp)
                    d    = _safe_desc(vp)
                    if not d:
                        continue
                    if d.shapeType != "Polygon":
                        issues.append(
                            f"'{name}': geometry is '{d.shapeType}' — Polygon required."
                        )
                        continue
                    vti = _ff(vp, "vegetationTrafficImpact")
                    ts  = _ff(vp, "treeSpacing")
                    sd  = _ff(vp, "stemDiameter")
                    missing_flds = []
                    if vti is None:
                        missing_flds.append("vegetationTrafficImpact  (VTI — controls F2)")
                    if ts is None:
                        missing_flds.append("treeSpacing  (controls F3 — tree spacing factor)")
                    if sd is None:
                        missing_flds.append("stemDiameter  (used with treeSpacing for F3)")
                    if missing_flds:
                        issues.append(
                            f"'{name}': missing field(s):\n"
                            + "\n".join(f"      • {f}" for f in missing_flds)
                        )
                    if extent_path:
                        try:
                            if not _bboxes_overlap(arcpy.Describe(vp).extent,
                                                   arcpy.Describe(extent_path).extent):
                                issues.append(f"'{name}': does not overlap the Analysis Extent.")
                        except Exception:
                            pass
                if issues:
                    p_veg.setWarningMessage(
                        "Vegetation layer notes:\n" +
                        "\n".join(f"  • {i}" for i in issues)
                    )
            except Exception:
                pass

        # ── Hydrology ─────────────────────────────────────────────────────────
        if p_hydro.value and not p_hydro.hasError():
            try:
                hydro_list = p_hydro.values or []
                issues     = []
                for h in hydro_list:
                    hp   = str(h)
                    name = os.path.basename(hp)
                    d    = _safe_desc(hp)
                    if not d:
                        continue
                    if d.shapeType != "Polygon":
                        issues.append(
                            f"'{name}': geometry is '{d.shapeType}'.  "
                            "Hydrology must be Polygon — buffer line/polyline features first."
                        )
                    if extent_path:
                        try:
                            if not _bboxes_overlap(arcpy.Describe(hp).extent,
                                                   arcpy.Describe(extent_path).extent):
                                issues.append(f"'{name}': does not overlap the Analysis Extent.")
                        except Exception:
                            pass
                if issues:
                    p_hydro.setWarningMessage(
                        "Hydrology layer notes:\n" +
                        "\n".join(f"  • {i}" for i in issues)
                    )
            except Exception:
                pass

        # ── Vehicle CSV ───────────────────────────────────────────────────────
        if p_csv.value and not p_csv.hasError():
            csv_path = p_csv.valueAsText
            if csv_path and os.path.isfile(csv_path):
                try:
                    df = read_csv_robust(csv_path)
                    required_cols = [
                        "name", "max_off_road_grad", "max_on_road_grad",
                        "max_road_spd_kph", "vci_1", "vci_50", "locomotion_type",
                    ]
                    missing_cols = [c for c in required_cols if c not in df.columns]
                    if missing_cols:
                        p_csv.setWarningMessage(
                            f"Vehicle CSV is missing required column(s): "
                            f"{', '.join(missing_cols)}.  "
                            "The tool will fail at runtime without these columns."
                        )
                except Exception as exc:
                    p_csv.setWarningMessage(f"Cannot read vehicle CSV: {exc}")

        # ── Vehicle selection vs CSV ──────────────────────────────────────────
        if (p_vehicles.value and not p_vehicles.hasError() and
                p_csv.value and not p_csv.hasError()):
            csv_path = p_csv.valueAsText
            if csv_path and os.path.isfile(csv_path):
                try:
                    df = read_csv_robust(csv_path)
                    if "name" in df.columns:
                        selected  = [str(v) for v in (p_vehicles.values or [])]
                        not_found = [
                            v for v in selected
                            if v not in df["name"].astype(str).tolist()
                        ]
                        if not_found:
                            p_vehicles.setWarningMessage(
                                f"Vehicle(s) not found in CSV: {', '.join(not_found)}"
                            )
                except Exception:
                    pass

        # ── Contour Lines ─────────────────────────────────────────────────────
        if p_contours.value and not p_contours.hasError():
            cont_path = p_contours.valueAsText
            d = _safe_desc(cont_path)
            if d:
                if d.shapeType not in ("Polyline", "Polygon"):
                    p_contours.setWarningMessage(
                        f"Contours geometry is '{d.shapeType}' — Polyline or Polygon expected."
                    )
                else:
                    ef = _ff(cont_path, "highestElevation")
                    if ef is None:
                        avail = ", ".join(
                            f.name for f in arcpy.ListFields(cont_path)
                            if f.type not in ("OID", "Geometry")
                        )
                        p_contours.setWarningMessage(
                            "No elevation field found.  Expected: 'highestElevation' "
                            "(or aliases: 'elevation', 'contour', 'elev_m').  "
                            "Contour normalisation for vegetation height will be skipped (F2 = 1.0).  "
                            f"Fields available: {avail or '(none)'}"
                        )
                    elif ef != "highestElevation":
                        p_contours.setWarningMessage(
                            f"Using '{ef}' as alias for 'highestElevation'."
                        )
                if extent_path and not p_contours.hasError():
                    _overlap_warn(cont_path, extent_path, "Contour Lines", p_contours)

    # =========================================================================
    # execute — DEM slope derivation + V1 delegation
    # =========================================================================

    def execute(self, parameters, messages):

        p          = parameters
        extent_fc  = p[0].valueAsText
        dem_path   = p[1].valueAsText
        slope_fc   = p[2].valueAsText
        soil_fc    = p[3].valueAsText
        # p[4] = vegetation (multiValue)
        # p[5] = hydrology  (multiValue)
        moisture   = p[6].valueAsText
        vehicle_csv = p[7].valueAsText
        # p[8] = vehicles   (multiValue)
        output_folder = p[9].valueAsText
        contours_fc   = p[10].valueAsText
        symbology     = p[11].valueAsText
        enable_weather = bool(p[12].value) if p[12].value else False
        manual_rain    = None
        if p[13].value is not None:
            try:
                manual_rain = float(p[13].valueAsText)
            except (ValueError, TypeError):
                pass

        # ── Derive slope from DEM if needed ───────────────────────────────────
        slope_fc_final = slope_fc

        if not slope_fc and dem_path:
            arcpy.AddMessage("[CCM V2] No Slope Regions provided — deriving from DEM...")
            sa_available = arcpy.CheckExtension("Spatial") == "Available"
            if sa_available:
                arcpy.CheckOutExtension("Spatial")
                try:
                    scratch_gdb   = arcpy.env.scratchGDB
                    slope_raster  = arcpy.sa.Slope(dem_path, "PERCENT_RISE")
                    slope_ras_path = os.path.join(scratch_gdb, "ccm_slope_pct")
                    slope_raster.save(slope_ras_path)

                    # Reclassify into slope-range polygons then join slope %
                    reclass_map = arcpy.sa.RemapRange([
                        [0, 5,   1],
                        [5, 10,  2],
                        [10, 15, 3],
                        [15, 20, 4],
                        [20, 30, 5],
                        [30, 45, 6],
                        [45, 90, 7],
                    ])
                    reclass_ras  = arcpy.sa.Reclassify(slope_ras_path, "Value", reclass_map)
                    reclass_path = os.path.join(scratch_gdb, "ccm_slope_reclass")
                    reclass_ras.save(reclass_path)

                    poly_path = os.path.join(scratch_gdb, "ccm_slope_poly")
                    arcpy.conversion.RasterToPolygon(
                        reclass_path, poly_path, "NO_SIMPLIFY", "Value"
                    )

                    # Add surfaceSlope field (midpoint of each class)
                    class_mid = {1: 2.5, 2: 7.5, 3: 12.5, 4: 17.5, 5: 25.0,
                                 6: 37.5, 7: 60.0}
                    arcpy.management.AddField(poly_path, "surfaceSlope", "DOUBLE")
                    with arcpy.da.UpdateCursor(poly_path, ["gridcode", "surfaceSlope"]) as cur:
                        for row in cur:
                            row[1] = class_mid.get(row[0], 0.0)
                            cur.updateRow(row)

                    slope_fc_final = poly_path
                    arcpy.AddMessage(
                        f"[CCM V2] Slope Regions derived from DEM → {poly_path}"
                    )
                except Exception as exc:
                    arcpy.AddWarning(
                        f"[CCM V2] Could not derive Slope Regions from DEM ({exc}).  "
                        "F1 (slope factor) will default to 1.0 — no slope penalty applied."
                    )
                finally:
                    arcpy.CheckInExtension("Spatial")
            else:
                arcpy.AddWarning(
                    "[CCM V2] Spatial Analyst licence not available — cannot derive "
                    "Slope Regions from DEM.  F1 (slope factor) will default to 1.0."
                )

        # ── Resolve soil field — run 4-level validator; derive if Level 4 ────
        if _soil_validator_mod and soil_fc:
            try:
                _sv = _soil_validator_mod.validate_soil_fc(soil_fc)
                if _sv.level == 4 and _sv.can_proceed and _sv.texture_fields:
                    tf = _sv.texture_fields
                    if "sand" in tf and "silt" in tf and "clay" in tf:
                        arcpy.AddMessage(
                            "[CCM V2] Soil: no USCS field found — deriving from "
                            f"Sand/Silt/Clay fields "
                            f"({tf['sand']} / {tf['silt']} / {tf['clay']}) …"
                        )
                        # Write derived codes into a 'soilType' field so V1
                        # find_field() picks it up without any changes to V1.
                        _soil_validator_mod.derive_uscs_field_from_texture(
                            soil_fc,
                            tf["sand"], tf["silt"], tf["clay"],
                            output_field="soilType",
                        )
                elif _sv.level in (1, 2, 3) and _sv.uscs_field:
                    arcpy.AddMessage(
                        f"[CCM V2] Soil field resolved: '{_sv.uscs_field}' "
                        f"(Level {_sv.level} match, confidence: {_sv.confidence})."
                    )
                elif _sv.level == 0:
                    arcpy.AddWarning(
                        "[CCM V2] No usable soil classification field found — "
                        "F4/F5 soil factors will be NULL for all features."
                    )
            except Exception as exc:
                arcpy.AddWarning(f"[CCM V2] Soil field resolution error: {exc}")

        # ── Live weather ──────────────────────────────────────────────────────
        if enable_weather and _weather_mod:
            try:
                _weather_mod.apply_live_weather_to_rci(
                    extent_fc          = extent_fc,
                    rci_soils_dict     = {},
                    manual_rainfall_mm = manual_rain,
                )
                label = (f"manual {manual_rain} mm" if manual_rain is not None
                         else "live data")
                arcpy.AddMessage(f"[CCM V2] Weather RCI adjustment applied ({label}).")
            except Exception as exc:
                arcpy.AddWarning(
                    f"[CCM V2] Weather adjustment failed ({exc}); "
                    "using default RCI values."
                )

        # ── Build V1-compatible parameter list and delegate ───────────────────
        # V1 expects parameters[6].values for hydro and .altered to decide
        # whether hydro was provided
        hydro_altered = bool(p[5].value)
        hydro_values  = p[5].values if hydro_altered else None

        v1_params = [
            _P(extent_fc,          extent_fc),                              # [0]
            _P(slope_fc_final,     slope_fc_final),                         # [1] surface_config
            _P(contours_fc,        contours_fc),                            # [2]
            _P(soil_fc,            soil_fc),                                # [3]
            _P(moisture,           moisture),                               # [4]
            _P(p[4].value,         p[4].valueAsText, values=p[4].values),  # [5] veg (multi)
            _P(p[5].value,         p[5].valueAsText,                        # [6] hydro (multi)
               values=hydro_values, altered=hydro_altered),
            _P(vehicle_csv,        vehicle_csv),                            # [7]
            _P(p[8].value,         p[8].valueAsText, values=p[8].values),  # [8] vehicles
            _P(output_folder,      output_folder),                          # [9]
            _P(symbology,          symbology),                              # [10]
        ]

        _CCMAnalysisEngine().execute(v1_params, messages)


# =============================================================================
# CCMValidateTool V2  —  maps new parameter layout to V1 validate tool
# =============================================================================

class CCMValidateTool:

    def __init__(self):
        self.label              = "1.  Check My Data Before Running"
        self.description        = (
            "Checks all required layers, fields, and projections before "
            "running the main CCM Analysis."
        )
        self.canRunInBackground = False

    def getParameterInfo(self):
        # Reuse CCMTool's parameter definition so layouts stay in sync
        return CCMTool().getParameterInfo()

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        CCMTool().updateParameters(parameters)

    def updateMessages(self, parameters):
        CCMTool().updateMessages(parameters)

    def execute(self, parameters, messages):
        arcpy.AddMessage("=" * 60)
        arcpy.AddMessage("  CCM Input Validation Report")
        arcpy.AddMessage("=" * 60)

        checks = [
            ("Analysis Extent",  parameters[0]),
            ("DEM",              parameters[1]),
            ("Slope Regions",    parameters[2]),
            ("Soil Data",        parameters[3]),
            ("Vegetation",       parameters[4]),
            ("Hydrology",        parameters[5]),
            ("Soil Moisture",    parameters[6]),
            ("Vehicle CSV",      parameters[7]),
            ("Select Vehicles",  parameters[8]),
            ("Output Folder",    parameters[9]),
            ("Contour Lines",    parameters[10]),
        ]

        all_ok = True
        for label, param in checks:
            if not param.value:
                status = "⚪ not provided"
            elif param.hasError():
                status = f"❌ ERROR — {param.message}"
                all_ok = False
            elif param.hasWarning():
                status = f"⚠  WARNING — {param.message}"
            else:
                status = "✅ OK"
            arcpy.AddMessage(f"  {label:<25} {status}")

        arcpy.AddMessage("=" * 60)
        if all_ok:
            arcpy.AddMessage("  All checks passed.  Ready to run CCM Analysis.")
        else:
            arcpy.AddError(
                "  One or more required inputs have errors.  "
                "Fix the issues above before running CCM Analysis."
            )


# =============================================================================
# CCMStep2MobilityTool  —  defined inline so it uses V2.pyt's already-loaded
# _V1CCMTool / _v1_mod / _cfg_mod references directly (no separate import)
# =============================================================================

class CCMStep2MobilityTool:
    """Step 2 — Generate Mobility Map.

    Reads ccm_project.json from the project folder created in Step 1
    and auto-fills all layer inputs.  The user only needs to select
    vehicles (and optionally change moisture or output settings).
    """

    def __init__(self):
        self.label              = "Step 2.  Generate Mobility Map"
        self.description        = (
            "Generates a CCM speed-surface mobility map.  "
            "Select the project folder created in Step 1 — all inputs "
            "are loaded automatically from ccm_project.json.  "
            "Choose vehicles and run."
        )
        self.canRunInBackground = False

    # =========================================================================
    def getParameterInfo(self):

        p_folder = arcpy.Parameter(
            displayName   = "Project Folder  (folder created in Step 1)",
            name          = "project_folder",
            datatype      = "DEFolder",
            parameterType = "Required",
            direction     = "Input",
        )

        p_moisture = arcpy.Parameter(
            displayName   = "Soil Moisture Condition",
            name          = "soil_moisture",
            datatype      = "GPString",
            parameterType = "Required",
            direction     = "Input",
        )
        p_moisture.filter.type = "ValueList"
        p_moisture.filter.list = ["dry", "moist", "wet"]
        p_moisture.value       = "moist"

        p_vehicles = arcpy.Parameter(
            displayName   = "Select Vehicle(s)",
            name          = "select_vehicles",
            datatype      = "GPString",
            parameterType = "Required",
            direction     = "Input",
            multiValue    = True,
        )
        p_vehicles.filter.type = "ValueList"
        p_vehicles.filter.list = []

        p_status = arcpy.Parameter(
            displayName   = "Loaded Config  (auto-filled from ccm_project.json)",
            name          = "config_status",
            datatype      = "GPString",
            parameterType = "Optional",
            direction     = "Input",
        )
        p_status.enabled = False   # read-only display

        p_symbology = arcpy.Parameter(
            displayName   = "Symbology Layer  (.lyrx)  [optional]",
            name          = "symbology_lyrx",
            datatype      = "DEFile",
            parameterType = "Optional",
            direction     = "Input",
            category      = "Advanced Options",
        )

        p_weather = arcpy.Parameter(
            displayName   = "Enable Live Weather Adjustment  (requires internet)",
            name          = "enable_live_weather",
            datatype      = "GPBoolean",
            parameterType = "Optional",
            direction     = "Input",
            category      = "Advanced Options",
        )
        p_weather.value = False

        p_rain = arcpy.Parameter(
            displayName   = "Manual Rainfall Override  (mm / 24 h)",
            name          = "manual_rainfall_mm",
            datatype      = "GPDouble",
            parameterType = "Optional",
            direction     = "Input",
            category      = "Advanced Options",
        )
        p_rain.enabled = False

        p_contour_interval = arcpy.Parameter(
            displayName   = "Contour Interval  (metres)  — auto-derived from DEM if Step 1 had no contours",
            name          = "contour_interval_m",
            datatype      = "GPDouble",
            parameterType = "Optional",
            direction     = "Input",
            category      = "Advanced Options",
        )
        p_contour_interval.value = 20

        # 0=folder, 1=moisture, 2=vehicles, 3=status,
        # 4=symbology, 5=weather, 6=rain, 7=contour_interval
        return [p_folder, p_moisture, p_vehicles, p_status,
                p_symbology, p_weather, p_rain, p_contour_interval]

    def isLicensed(self):
        return True

    # =========================================================================
    def updateParameters(self, parameters):
        p_folder   = parameters[0]
        p_moisture = parameters[1]
        p_vehicles = parameters[2]
        p_status   = parameters[3]
        p_weather  = parameters[5]
        p_rain     = parameters[6]

        if p_folder.value:
            folder_path = p_folder.valueAsText
            cfg = _cfg_mod.load_config(folder_path) if _cfg_mod else {}

            # Populate vehicle picker from stored CSV
            csv_path = (cfg or {}).get("vehicle_csv")
            if csv_path and os.path.isfile(csv_path):
                names = []
                try:
                    df = read_csv_robust(csv_path)
                    if "name" in df.columns:
                        names = df["name"].astype(str).tolist()
                except Exception:
                    pass
                if not names:
                    try:
                        import csv as _csv
                        for enc in ("utf-8", "latin-1", "cp1252"):
                            try:
                                with open(csv_path, newline="",
                                          encoding=enc) as fh:
                                    reader = _csv.DictReader(fh)
                                    if (reader.fieldnames
                                            and "name" in reader.fieldnames):
                                        names = [r["name"] for r in reader
                                                 if r.get("name", "").strip()]
                                break
                            except UnicodeDecodeError:
                                continue
                    except Exception:
                        pass
                if names and p_vehicles.filter.list != names:
                    p_vehicles.filter.list = names
                    last = (cfg or {}).get("last_vehicles", [])
                    if last and not p_vehicles.value:
                        p_vehicles.values = last

            # Default moisture from config
            if not p_moisture.altered or not p_moisture.value:
                p_moisture.value = (cfg or {}).get("moisture_default", "moist")

            # Config summary display
            if cfg:
                soil   = os.path.basename(cfg.get("soil_fc",  "") or "") or "—"
                veg    = os.path.basename(cfg.get("veg_fc",   "") or "") or "—"
                hydros = cfg.get("hydro_fcs", [])
                h_str  = f"{len(hydros)} layer(s)" if hydros else "—"
                extent = os.path.basename(cfg.get("extent_fc","") or "") or "—"
                p_status.value = (
                    f"Extent: {extent}  |  Soil: {soil}  |  "
                    f"Veg: {veg}  |  Hydrology: {h_str}"
                )
            else:
                p_status.value = "No ccm_project.json found in this folder."

        p_rain.enabled = bool(p_weather.value)

    # =========================================================================
    def updateMessages(self, parameters):
        p_folder   = parameters[0]
        p_vehicles = parameters[2]

        if p_folder.value:
            cfg = _cfg_mod.load_config(p_folder.valueAsText) if _cfg_mod else {}
            if not cfg:
                p_folder.setWarningMessage(
                    "No ccm_project.json found.  Run Step 1 first."
                )
                return
            missing = []
            for key in ("extent_fc", "soil_fc", "veg_fc"):
                path = cfg.get(key)
                if not path:
                    missing.append(key)
                elif not arcpy.Exists(path):
                    missing.append(f"{key} (not found: {path})")
            if missing:
                p_folder.setWarningMessage(
                    "Some layers from Step 1 are missing or unreachable: "
                    + ", ".join(missing)
                    + ".  Re-run Step 1 or fix ccm_project.json."
                )

        if not p_vehicles.value:
            p_vehicles.setWarningMessage(
                "Select at least one vehicle to generate a mobility map."
            )

    # =========================================================================
    def execute(self, parameters, messages):

        folder_path      = parameters[0].valueAsText
        moisture         = parameters[1].valueAsText
        symbology        = parameters[4].valueAsText
        enable_wx        = bool(parameters[5].value) if parameters[5].value else False
        manual_rain      = None
        contour_interval = 20.0
        if parameters[6].value is not None:
            try:
                manual_rain = float(parameters[6].valueAsText)
            except (ValueError, TypeError):
                pass
        if len(parameters) > 7 and parameters[7].value is not None:
            try:
                contour_interval = float(parameters[7].valueAsText)
                if contour_interval <= 0:
                    contour_interval = 20.0
            except (ValueError, TypeError):
                pass

        # ── Load project config ───────────────────────────────────────────────
        cfg = _cfg_mod.load_config(folder_path) if _cfg_mod else {}
        if not cfg:
            arcpy.AddError(
                "[Step 2] No ccm_project.json found in the project folder.  "
                "Run Step 1 first."
            )
            return

        extent_fc   = cfg.get("extent_fc")
        dem_path    = cfg.get("dem_path")
        slope_fc    = cfg.get("slope_fc")
        contours_fc = cfg.get("contours_fc")
        soil_fc     = cfg.get("soil_fc")
        veg_fc      = cfg.get("veg_fc") or ""
        hydro_fcs   = cfg.get("hydro_fcs", [])
        vehicle_csv = cfg.get("vehicle_csv")

        hydro_text    = ";".join(hydro_fcs) if hydro_fcs else None
        hydro_altered = bool(hydro_fcs)
        vehicle_vals  = parameters[2].values if parameters[2].value else []
        vehicle_text  = parameters[2].valueAsText

        # ── Analysis engine is merged inline — always available ──────────────

        # ── Derive slope from DEM if needed ──────────────────────────────────
        slope_fc_final = slope_fc

        if not slope_fc and dem_path:
            arcpy.AddMessage(
                "[Step 2] No Slope Regions in project config — deriving from DEM..."
            )
            sa_available = arcpy.CheckExtension("Spatial") == "Available"
            if sa_available:
                arcpy.CheckOutExtension("Spatial")
                try:
                    scratch_gdb    = arcpy.env.scratchGDB
                    # Save the final polygon to the project GDB so it persists
                    # across runs (scratchGDB is cleared by ArcGIS Pro).
                    _proj_gdb_sl   = cfg.get("project_gdb") or scratch_gdb
                    slope_raster   = arcpy.sa.Slope(dem_path, "PERCENT_RISE")
                    slope_ras_path = os.path.join(scratch_gdb, "ccm_slope_pct")
                    slope_raster.save(slope_ras_path)

                    reclass_map = arcpy.sa.RemapRange([
                        [0,  5,  1],
                        [5,  10, 2],
                        [10, 15, 3],
                        [15, 20, 4],
                        [20, 30, 5],
                        [30, 45, 6],
                        [45, 90, 7],
                    ])
                    reclass_ras  = arcpy.sa.Reclassify(
                        slope_ras_path, "Value", reclass_map
                    )
                    reclass_path = os.path.join(scratch_gdb, "ccm_slope_reclass")
                    reclass_ras.save(reclass_path)

                    poly_path = os.path.join(_proj_gdb_sl, "ccm_slope_poly")
                    if arcpy.Exists(poly_path):
                        arcpy.management.Delete(poly_path)
                    arcpy.conversion.RasterToPolygon(
                        reclass_path, poly_path, "NO_SIMPLIFY", "Value"
                    )

                    class_mid = {1: 2.5, 2: 7.5, 3: 12.5, 4: 17.5,
                                 5: 25.0, 6: 37.5, 7: 60.0}
                    arcpy.management.AddField(poly_path, "surfaceSlope", "DOUBLE")
                    with arcpy.da.UpdateCursor(
                        poly_path, ["gridcode", "surfaceSlope"]
                    ) as _cur:
                        for _row in _cur:
                            _row[1] = class_mid.get(_row[0], 0.0)
                            _cur.updateRow(_row)

                    slope_fc_final = poly_path
                    arcpy.AddMessage(
                        f"[Step 2] Slope Regions derived from DEM → {poly_path}"
                    )
                    # ── Persist so future runs skip re-derivation ─────────────
                    if _cfg_mod:
                        _cfg_mod.save_config(folder_path, slope_fc=slope_fc_final)
                        arcpy.AddMessage(
                            "[Step 2] Slope FC path saved to project config."
                        )
                except Exception as _sl_exc:
                    arcpy.AddWarning(
                        f"[Step 2] Could not derive Slope Regions from DEM "
                        f"({_sl_exc}).  F1 (slope factor) will default to 1.0."
                    )
                finally:
                    arcpy.CheckInExtension("Spatial")
            else:
                arcpy.AddWarning(
                    "[Step 2] Spatial Analyst licence not available — cannot "
                    "derive Slope Regions from DEM.  F1 will default to 1.0."
                )

        # ── Derive contours from DEM if needed ───────────────────────────────
        contours_fc_final = contours_fc

        if not contours_fc and dem_path:
            arcpy.AddMessage(
                f"[Step 2] No Contour Lines in project config — deriving from "
                f"DEM (interval: {contour_interval} m)..."
            )
            _sa_avail  = arcpy.CheckExtension("Spatial") == "Available"
            _ddd_avail = arcpy.CheckExtension("3D")      == "Available"

            if _sa_avail or _ddd_avail:
                _ct_ext = "Spatial" if _sa_avail else "3D"
                arcpy.CheckOutExtension(_ct_ext)
                try:
                    _project_gdb = cfg.get("project_gdb") or arcpy.env.scratchGDB
                    _ct_name     = f"contours_{int(contour_interval)}m"
                    _ct_path     = os.path.join(_project_gdb, _ct_name)

                    # Remove any stale output from a previous run
                    if arcpy.Exists(_ct_path):
                        arcpy.management.Delete(_ct_path)

                    if _sa_avail:
                        arcpy.sa.Contour(dem_path, _ct_path, contour_interval)
                    else:
                        arcpy.ddd.Contour(dem_path, _ct_path, contour_interval)

                    contours_fc_final = _ct_path
                    arcpy.AddMessage(
                        f"[Step 2] Contours ({contour_interval} m interval) "
                        f"derived from DEM → {_ct_path}"
                    )
                    # ── Persist so future runs skip re-derivation ─────────────
                    if _cfg_mod:
                        _cfg_mod.save_config(
                            folder_path, contours_fc=contours_fc_final
                        )
                        arcpy.AddMessage(
                            "[Step 2] Contour FC path saved to project config."
                        )
                except Exception as _ct_exc:
                    arcpy.AddWarning(
                        f"[Step 2] Could not derive contours from DEM "
                        f"({_ct_exc}).  "
                        "Contour-based terrain factor will be skipped."
                    )
                finally:
                    arcpy.CheckInExtension(_ct_ext)
            else:
                arcpy.AddWarning(
                    "[Step 2] Neither Spatial Analyst nor 3D Analyst licence "
                    "available — cannot derive contours from DEM.  "
                    "Contour-based terrain factor will be skipped."
                )

        # ── Resolve soil field ────────────────────────────────────────────────
        if _soil_validator_mod and soil_fc:
            try:
                _sv = _soil_validator_mod.validate_soil_fc(soil_fc)
                if _sv.level == 4 and _sv.can_proceed and _sv.texture_fields:
                    _tf = _sv.texture_fields
                    if "sand" in _tf and "silt" in _tf and "clay" in _tf:
                        arcpy.AddMessage(
                            "[Step 2] Soil: deriving USCS from Sand/Silt/Clay "
                            f"fields ({_tf['sand']} / {_tf['silt']} / "
                            f"{_tf['clay']}) …"
                        )
                        _soil_validator_mod.derive_uscs_field_from_texture(
                            soil_fc,
                            _tf["sand"], _tf["silt"], _tf["clay"],
                            output_field="soilType",
                        )
                elif _sv.level in (1, 2, 3) and _sv.uscs_field:
                    arcpy.AddMessage(
                        f"[Step 2] Soil field resolved: '{_sv.uscs_field}' "
                        f"(Level {_sv.level}, confidence: {_sv.confidence})."
                    )
                elif _sv.level == 0:
                    arcpy.AddWarning(
                        "[Step 2] No usable soil classification field found — "
                        "F4/F5 factors will be NULL for all features."
                    )
            except Exception as _sv_exc:
                arcpy.AddWarning(
                    f"[Step 2] Soil field resolution error: {_sv_exc}"
                )

        # ── Live weather ──────────────────────────────────────────────────────
        if enable_wx and _weather_mod:
            try:
                _weather_mod.apply_live_weather_to_rci(
                    extent_fc          = extent_fc,
                    rci_soils_dict     = {},
                    manual_rainfall_mm = manual_rain,
                )
                _wx_label = (f"manual {manual_rain} mm"
                             if manual_rain is not None else "live data")
                arcpy.AddMessage(
                    f"[Step 2] Weather RCI adjustment applied ({_wx_label})."
                )
            except Exception as _wx_exc:
                arcpy.AddWarning(
                    f"[Step 2] Weather adjustment failed ({_wx_exc}); "
                    "using default RCI values."
                )

        # ── Build V1-compatible 11-param list and delegate directly ───────────
        # V1 parameter order:
        #  [0] extent_fc   [1] slope/surface_config   [2] contours
        #  [3] soil_fc     [4] moisture                [5] veg (multi)
        #  [6] hydro (multi) [7] vehicle_csv           [8] vehicles (multi)
        #  [9] output_folder  [10] symbology
        arcpy.AddMessage("[Step 2] ── Running CCM Analysis ─────────────────────")

        veg_vals = [veg_fc] if veg_fc else []

        v1_params = [
            _P(extent_fc,         extent_fc),                           # [0]
            _P(slope_fc_final,    slope_fc_final),                      # [1]
            _P(contours_fc_final, contours_fc_final),                   # [2]
            _P(soil_fc,        soil_fc),                                # [3]
            _P(moisture,       moisture),                               # [4]
            _P(veg_fc,         veg_fc,       values=veg_vals),         # [5] veg (multi)
            _P(hydro_text,     hydro_text,                              # [6] hydro (multi)
               values=hydro_fcs if hydro_fcs else None,
               altered=hydro_altered),
            _P(vehicle_csv,    vehicle_csv),                            # [7]
            _P(parameters[2].value, vehicle_text, values=vehicle_vals),# [8] vehicles
            _P(folder_path,    folder_path),                            # [9] output
            _P(symbology,      symbology),                              # [10]
        ]

        _CCMAnalysisEngine().execute(v1_params, messages)

        # ── Copy final speed surface into CCM_Project.gdb ─────────────────────
        # The V1 engine writes everything (intermediates + final map) into a
        # per-run GDB (CCM_<vehicles>_<moisture>.gdb).  We copy only the final
        # speed surface FC into the project GDB so the user has one canonical
        # location for all mobility map products.
        project_gdb   = cfg.get("project_gdb")
        mobility_map_fc = None

        if project_gdb and arcpy.Exists(project_gdb):
            # Reconstruct the speed surface path (same naming as V1 engine)
            vehicle_selection = "_".join([str(v) for v in vehicle_vals])
            run_gdb_name  = f"CCM_{vehicle_selection}_{moisture}.gdb"
            run_gdb_path  = os.path.join(folder_path, run_gdb_name)
            src_fc_name   = f"speed_surface_{vehicle_selection}_{moisture}"
            src_fc_path   = os.path.join(run_gdb_path, src_fc_name)

            if arcpy.Exists(src_fc_path):
                dst_fc_path = os.path.join(project_gdb, src_fc_name)
                # Overwrite if this vehicle/moisture combo was run before
                if arcpy.Exists(dst_fc_path):
                    arcpy.management.Delete(dst_fc_path)
                arcpy.management.CopyFeatures(src_fc_path, dst_fc_path)
                mobility_map_fc = dst_fc_path
                arcpy.AddMessage(
                    f"[Step 2] Final mobility map copied to project GDB:\n"
                    f"         {dst_fc_path}"
                )
            else:
                arcpy.AddWarning(
                    f"[Step 2] Could not find speed surface at expected path:\n"
                    f"         {src_fc_path}\n"
                    f"         Mobility map remains in the per-run GDB."
                )
        else:
            arcpy.AddWarning(
                "[Step 2] project_gdb not set in config — "
                "mobility map stays in the per-run GDB.  Re-run Step 1 to "
                "register the project database."
            )

        # ── Update config with run results ────────────────────────────────────
        if _cfg_mod:
            _cfg_mod.save_config(
                folder_path,
                last_vehicles    = [str(v) for v in vehicle_vals],
                moisture_default = moisture,
                last_run_output  = folder_path,
                mobility_map_fc  = mobility_map_fc,
            )
            arcpy.AddMessage("[Step 2] Config updated.")

        arcpy.AddMessage("=" * 60)
        arcpy.AddMessage("  Step 2 complete.  Open Step 3 for advanced analysis.")
        arcpy.AddMessage("=" * 60)


# =============================================================================
# Toolbox  —  safe registration; print() only, never arcpy.Add* at load time
# =============================================================================

class Toolbox:
    def __init__(self):
        self.label       = "MCE CCM Toolbox V2"
        self.alias       = "MCE_CCM_V2"
        self.description = (
            "Next-Generation CCM Analysis Toolbox — "
            "3-Step Workflow: Step 1 (Setup & Pre-process), "
            "Step 2 (Generate Mobility Map), Step 3 (Advanced Analysis). "
            "Supports soil preprocessing (DSS, SLC, SSURGO, HWSD, SoilGrids, Generic), "
            "vegetation preprocessing (ESA WorldCover, NLCD, CGLS-LC100, GEDI, Canada Bio), "
            "DEM-to-slope derivation, live weather integration, "
            "reason mapping, isochrones, vehicle comparison, "
            "obstacle detection, and waypoint routing."
        )

        tools = [CCMTool, CCMValidateTool]

        # Register soil preprocessor as tool #0 (prepend so it sorts first)
        if _CCMSoilPreprocessTool is not None:
            tools.insert(0, _CCMSoilPreprocessTool)
        else:
            print("[CCM V2] Skipping tool — ccm_soil_preprocess.py not loaded.")

        # Register vegetation preprocessor as tool #1 (after soil, before main)
        if _CCMVegPreprocessTool is not None:
            insert_idx = 1 if _CCMSoilPreprocessTool is not None else 0
            tools.insert(insert_idx, _CCMVegPreprocessTool)
        else:
            print("[CCM V2] Skipping tool — ccm_veg_preprocess.py not loaded.")

        # ── Register 3-Step Workflow tools at the very top of the list ────────
        # They appear first in the toolbox so users see the recommended workflow
        # immediately.  Individual legacy tools remain available below.
        # Step 2 is defined inline (CCMStep2MobilityTool) — always available.
        # Step 1 and Step 3 are loaded from external modules.
        step_tools = []
        for cls, tag in [
            (_CCMStep3AdvancedTool, "ccm_step3_advanced.py"),
            (CCMStep2MobilityTool,  "inline"),               # always present
            (_CCMStep1SetupTool,    "ccm_step1_setup.py"),
        ]:
            if cls is not None:
                step_tools.append(cls)
            else:
                print(f"[CCM V2] Skipping step tool — {tag} not loaded.")
        # Prepend in reverse order so Step 1 ends up first, Step 3 third
        for cls in step_tools:
            tools.insert(0, cls)

        for cls, tag in [
            (_CCMReasonMapTool,      "ccm_reason_map.py"),
            (_CCMIsochroneTool,      "ccm_isochrone.py"),
            (_CCMVehicleCompareTool, "ccm_vehicle_compare.py"),
            (_CCMObstacleDetectTool, "ccm_obstacle_detect.py"),
            (_CCMWaypointTool,       "ccm_waypoints.py"),
        ]:
            if cls is not None:
                tools.append(cls)
            else:
                print(f"[CCM V2] Skipping tool — {tag} not loaded.")

        self.tools = tools
