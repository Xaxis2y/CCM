# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# ccm_step1_setup.py
# CCM Step 1 — Project Setup & Pre-process
#
# Collects ALL raw inputs once, runs Soil + Vegetation pre-processing,
# and saves ccm_project.json so Steps 2 & 3 never ask for data again.
#
# VERSION = "0.55.0"
VERSION = "0.58.2"  # v0.58.2 -- bumped by bump_version.py from v0.57. Review this line's comment.
# v0.47 — Added Geomorphon Landforms (Pro 3.5+) optional analysis.
# v0.46 — Bug fixes:
#          1. print() on import failures → arcpy.AddWarning() so messages
#             appear in ArcGIS Pro Geoprocessing Messages pane.
#          2. VERSION constant added (was missing in all prior versions).

import arcpy
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# ── Companion modules ─────────────────────────────────────────────────────────
_soil_mod = None
try:
    from ccm_soil_preprocess import CCMSoilPreprocessTool as _CCMSoilPreprocessTool
    import ccm_soil_preprocess as _soil_mod
except Exception as e:
    _CCMSoilPreprocessTool = None
    arcpy.AddWarning(f"[Step 1] ccm_soil_preprocess: {e}")

try:
    from ccm_veg_preprocess import CCMVegPreprocessTool as _CCMVegPreprocessTool
except Exception as e:
    _CCMVegPreprocessTool = None
    arcpy.AddWarning(f"[Step 1] ccm_veg_preprocess: {e}")

_cfg_mod = None
try:
    import ccm_project_config as _cfg_mod
except Exception as e:
    arcpy.AddWarning(f"[Step 1] ccm_project_config: {e}")

# v0.52.0 — one-folder data root discovery
_discovery = None
try:
    import ccm_data_discovery as _discovery
except Exception as e:
    arcpy.AddWarning(f"[Step 1] ccm_data_discovery: {e}")

# v0.50.0 — MGCP catalog/manifest support (auto-fill from Step 0 output)
_catalog = None
try:
    import ccm_mgcp_catalog as _catalog
except Exception as e:
    arcpy.AddWarning(f"[Step 1] ccm_mgcp_catalog: {e}")

# v0.54.0 — shared CRS/projection smart-warning helpers
_coords_mod = None
try:
    import ccm_coords as _coords_mod
except Exception as e:
    arcpy.AddWarning(f"[Step 1] ccm_coords: {e}")

# v0.57 post-review "M-2" — validates a user-supplied "Pre-processed Soil FC"
# has a usable USCS field before Step 2 silently treats every polygon as
# unpenalised soil (see ccm_soil_validator.py's own docstring for the
# 4-level detection it performs). This module shipped in every v0.57
# release but nothing imported it until now.
_soil_validator_mod = None
try:
    import ccm_soil_validator as _soil_validator_mod
except Exception as e:
    arcpy.AddWarning(f"[Step 1] ccm_soil_validator: {e}")

# v0.57 post-review "P-2" — reuse Step 0b's ccm_data_catalog.json for the
# same data root instead of Step 1 silently re-scanning with the older
# ccm_data_discovery heuristic and never surfacing the catalog's CRS /
# resolution / coverage / missing-role findings. See CHANGELOG_v0.57.md
# "P-2" and CCM_Tool_v0.57_Review.md.
_catalog_mod = None
try:
    import ccm_data_catalog as _catalog_mod
except Exception as e:
    arcpy.AddWarning(f"[Step 1] ccm_data_catalog: {e}")


def _parse_multi(value_str):
    """
    Split a semicolon- or comma-separated multi-value string into a list of
    stripped path strings.  Returns a list (possibly empty).

    ArcGIS Pro multi-value parameters use semicolons as the delimiter when
    valueAsText is read, but users may also pass comma-separated lists.  Both
    separators are accepted; empty tokens are dropped.
    """
    if not value_str:
        return []
    # Try semicolons first (ArcGIS native), fall back to commas
    sep = ";" if ";" in str(value_str) else ","
    return [p.strip().strip("'\"") for p in str(value_str).split(sep) if p.strip()]


# ── Minimal parameter shim for calling sub-tools programmatically ─────────────
class _P:
    """Mimics arcpy.Parameter interface used by execute()."""
    def __init__(self, value, value_as_text=None, values=None, altered=True):
        self.value       = value
        self.valueAsText = (value_as_text if value_as_text is not None
                            else (str(value) if value is not None else None))
        self.values      = values
        self.altered     = altered

    def hasError(self):   return False
    def hasWarning(self): return False


# =============================================================================
class CCMStep1SetupTool:
    """Step 1 — Project Setup & Pre-process.

    Enter all raw data sources ONCE.  The tool pre-processes soil and
    vegetation into CCM-ready polygon layers and writes ccm_project.json
    so that Steps 2 and 3 auto-populate without re-entering data.
    """

    def __init__(self):
        self.label              = "Step 1.  Project Setup & Pre-process"
        self.description        = (
            "Enter all raw inputs once.  "
            "Pre-processes soil and vegetation data into CCM-ready polygon "
            "layers, then saves ccm_project.json so Steps 2 and 3 "
            "auto-fill without re-entering data."
        )
        self.canRunInBackground = False

    # =========================================================================
    def getParameterInfo(self):

        # ── SECTION 1  Project ────────────────────────────────────────────────
        p_folder = arcpy.Parameter(
            displayName   = "Project Output Folder",
            name          = "project_folder",
            datatype      = "DEFolder",
            parameterType = "Required",
            direction     = "Output",
        )

        p_extent = arcpy.Parameter(
            displayName   = "Analysis Extent  (study area polygon — must be Projected CRS)",
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
            displayName   = "Slope Regions  (polygon FC)  [optional if DEM provided]",
            name          = "slope_regions_fc",
            datatype      = "DEFeatureClass",
            parameterType = "Optional",
            direction     = "Input",
        )

        p_slope_field = arcpy.Parameter(
            displayName   = "Slope Value Field  (on the Slope Regions FC) "
                            "[optional — auto-detected if blank]",
            name          = "slope_field",
            datatype      = "Field",
            parameterType = "Optional",
            direction     = "Input",
        )
        p_slope_field.parameterDependencies = [p_slope.name]

        p_slope_units = arcpy.Parameter(
            displayName   = "Slope Field Units",
            name          = "slope_units",
            datatype      = "GPString",
            parameterType = "Optional",
            direction     = "Input",
        )
        p_slope_units.filter.type = "ValueList"
        p_slope_units.filter.list = ["percent", "degrees"]
        p_slope_units.value       = "percent"

        p_contours = arcpy.Parameter(
            displayName   = "Contour Lines  (optional — improves vegetation height normalisation)",
            name          = "contours_fc",
            datatype      = "DEFeatureClass",
            parameterType = "Optional",
            direction     = "Input",
        )

        p_moisture = arcpy.Parameter(
            displayName   = "Default Soil Moisture Condition  (can be changed in Step 2)",
            name          = "soil_moisture",
            datatype      = "GPString",
            parameterType = "Required",
            direction     = "Input",
        )
        p_moisture.filter.type = "ValueList"
        p_moisture.filter.list = ["dry", "moist", "wet"]
        p_moisture.value       = "moist"

        # ── SECTION 2  Soil ───────────────────────────────────────────────────
        p_soil_src_header = arcpy.Parameter(
            displayName   = "─── Soil Data ───────────────────────────────────────",
            name          = "soil_header",
            datatype      = "GPString",
            parameterType = "Optional",
            direction     = "Input",
            category      = "Soil Pre-processing",
        )
        p_soil_src_header.value = ""

        p_soil_source = arcpy.Parameter(
            displayName   = "Soil Data Source  (leave Auto-Detect to identify automatically)",
            name          = "soil_source_type",
            datatype      = "GPString",
            parameterType = "Optional",
            direction     = "Input",
            category      = "Soil Pre-processing",
        )
        p_soil_source.filter.type = "ValueList"
        if _soil_mod and hasattr(_soil_mod, "ALL_SOURCES"):
            p_soil_source.filter.list = _soil_mod.ALL_SOURCES
            p_soil_source.value       = getattr(_soil_mod, "SOURCE_AUTO", "Auto-Detect")
        else:
            p_soil_source.filter.list = ["Auto-Detect"]
            p_soil_source.value       = "Auto-Detect"

        p_soil_raw = arcpy.Parameter(
            displayName   = "Raw Soil FC or HWSD Raster  (source data to pre-process)",
            name          = "soil_raw",
            datatype      = ["DEFeatureClass", "DERasterDataset"],
            parameterType = "Optional",
            direction     = "Input",
            category      = "Soil Pre-processing",
        )

        p_soil_cmp = arcpy.Parameter(
            displayName   = "Component Table (.dbf)  [DSS/SLC Canada]",
            name          = "soil_cmp_table",
            datatype      = "DEFile",
            parameterType = "Optional",
            direction     = "Input",
            category      = "Soil Pre-processing",
        )

        p_soil_layer_tbl = arcpy.Parameter(
            displayName   = "Soil Layer Table (.dbf)  [DSS/SLC Canada]",
            name          = "soil_layer_table",
            datatype      = "DEFile",
            parameterType = "Optional",
            direction     = "Input",
            category      = "Soil Pre-processing",
        )

        p_soil_name_tbl = arcpy.Parameter(
            displayName   = "Soil Name Table (.dbf)  [DSS/SLC PMTEX fallback]",
            name          = "soil_name_table",
            datatype      = "DEFile",
            parameterType = "Optional",
            direction     = "Input",
            category      = "Soil Pre-processing",
        )

        p_soil_slc_gdb = arcpy.Parameter(
            displayName   = "SLC File Geodatabase (.gdb)  [SLC Canada]",
            name          = "soil_slc_gdb",
            datatype      = "DEWorkspace",
            parameterType = "Optional",
            direction     = "Input",
            category      = "Soil Pre-processing",
        )

        p_soil_ssurgo = arcpy.Parameter(
            displayName   = "SSURGO Tabular Folder or gSSURGO .gdb  [SSURGO/STATSGO2 US]",
            name          = "soil_ssurgo",
            datatype      = ["DEFolder", "DEWorkspace"],
            parameterType = "Optional",
            direction     = "Input",
            category      = "Soil Pre-processing",
        )

        p_soil_hwsd = arcpy.Parameter(
            displayName   = "HWSD2.mdb Access Database  [HWSD Global]",
            name          = "soil_hwsd_mdb",
            datatype      = "DEFile",
            parameterType = "Optional",
            direction     = "Input",
            category      = "Soil Pre-processing",
        )

        p_soil_sg_folder = arcpy.Parameter(
            displayName   = "SoilGrids 2.0 Raster Folder  [SoilGrids Global]",
            name          = "soil_sg_folder",
            datatype      = "DEFolder",
            parameterType = "Optional",
            direction     = "Input",
            category      = "Soil Pre-processing",
        )

        p_soil_sg_depth = arcpy.Parameter(
            displayName   = "SoilGrids Depth Layer  [SoilGrids Global]",
            name          = "soil_sg_depth",
            datatype      = "GPString",
            parameterType = "Optional",
            direction     = "Input",
            category      = "Soil Pre-processing",
        )
        p_soil_sg_depth.filter.type = "ValueList"
        p_soil_sg_depth.filter.list = [
            "0-5cm", "5-15cm", "15-30cm", "30-60cm", "60-100cm", "Weighted 0-30cm"
        ]
        p_soil_sg_depth.value = "0-5cm"

        p_soil_gapfill = arcpy.Parameter(
            displayName   = "Soil Gap-Fill Strategy",
            name          = "soil_gap_fill",
            datatype      = "GPString",
            parameterType = "Required",
            direction     = "Input",
            category      = "Soil Pre-processing",
        )
        p_soil_gapfill.filter.type = "ValueList"
        if _soil_mod and hasattr(_soil_mod, "GAP_FILL_SMART"):
            p_soil_gapfill.filter.list = [
                _soil_mod.GAP_FILL_SMART, "NE", "SP", "SM", "ML", "CL", "CH", "Pt"
            ]
            p_soil_gapfill.value = _soil_mod.GAP_FILL_SMART
        else:
            p_soil_gapfill.filter.list = ["Smart (auto)", "NE", "SP", "SM", "ML", "CL", "CH", "Pt"]
            p_soil_gapfill.value = "Smart (auto)"

        p_soil_preproc_fc = arcpy.Parameter(
            displayName   = "Pre-processed Soil FC  [SKIP pre-processing — use existing]",
            name          = "soil_preproc_fc",
            datatype      = "DEFeatureClass",
            parameterType = "Optional",
            direction     = "Input",
            category      = "Soil Pre-processing",
        )

        # ── SECTION 3  Vegetation ─────────────────────────────────────────────
        p_veg_rasters = arcpy.Parameter(
            displayName   = "Vegetation / Biophysical Raster File(s)  "
                            "(tiles or Canada Bio LAI + fCOVER + GLAD height)",
            name          = "veg_raster_files",
            datatype      = "DEFile",
            parameterType = "Optional",
            direction     = "Input",
            multiValue    = True,
            category      = "Vegetation Pre-processing",
        )

        p_veg_preproc_fc = arcpy.Parameter(
            displayName   = "Pre-processed Vegetation FC  [SKIP pre-processing — use existing]",
            name          = "veg_preproc_fc",
            datatype      = "DEFeatureClass",
            parameterType = "Optional",
            direction     = "Input",
            category      = "Vegetation Pre-processing",
        )

        # ── SECTION 4  Hydrology & Vehicles ──────────────────────────────────
        p_hydro = arcpy.Parameter(
            displayName   = "Hydrology Layers  (polygon FCs — water bodies / rivers)",
            name          = "hydro_fcs",
            datatype      = "GPFeatureLayer",
            parameterType = "Optional",
            direction     = "Input",
            multiValue    = True,
            category      = "Hydrology & Vehicles",
        )

        p_vehicle_csv = arcpy.Parameter(
            displayName   = "Vehicle Definitions CSV",
            name          = "vehicle_csv",
            datatype      = "DEFile",
            parameterType = "Required",
            direction     = "Input",
            category      = "Hydrology & Vehicles",
        )

        # ── SECTION 5  MGCP Manifest (v0.50.0) ───────────────────────────────
        p_manifest = arcpy.Parameter(
            displayName   = "MGCP Manifest  (mgcp_manifest.json written by Step 0 — "
                            "auto-fills Soil / Hydrology / Contours below)",
            name          = "mgcp_manifest",
            datatype      = "DEFile",
            parameterType = "Optional",
            direction     = "Input",
        )
        p_manifest.filter.list = ["json"]

        # ── Data Root folder (v0.52.0) ───────────────────────────────────────
        p_data_root = arcpy.Parameter(
            displayName   = "Data Root Folder  (optional — scans subfolders "
                            "named MGCP / Soil / DEM / Contours / Vegetation / "
                            "Hydro / Vehicle / Extent and auto-fills the empty "
                            "inputs; ranked by accuracy when duplicates exist)",
            name          = "data_root",
            datatype      = "DEFolder",
            parameterType = "Optional",
            direction     = "Input",
        )

        # ── indices ───────────────────────────────────────────────────────────
        return [
            p_folder,          # 0
            p_extent,          # 1
            p_dem,             # 2
            p_slope,           # 3
            p_contours,        # 4
            p_moisture,        # 5
            # Soil
            p_soil_src_header, # 6  (decorative label — GPString filler)
            p_soil_source,     # 7
            p_soil_raw,        # 8
            p_soil_cmp,        # 9
            p_soil_layer_tbl,  # 10
            p_soil_name_tbl,   # 11
            p_soil_slc_gdb,    # 12
            p_soil_ssurgo,     # 13
            p_soil_hwsd,       # 14
            p_soil_sg_folder,  # 15
            p_soil_sg_depth,   # 16
            p_soil_gapfill,    # 17
            p_soil_preproc_fc, # 18
            # Veg
            p_veg_rasters,     # 19
            p_veg_preproc_fc,  # 20
            # Hydro & CSV
            p_hydro,           # 21
            p_vehicle_csv,     # 22
            # Slope field metadata (appended last to preserve existing indices)
            p_slope_field,     # 23
            p_slope_units,     # 24
            # MGCP manifest (v0.50.0 — appended last to preserve indices)
            p_manifest,        # 25
            # Data Root folder (v0.52.0 — appended last to preserve indices)
            p_data_root,       # 26
        ]

    def isLicensed(self):
        return True

    # =========================================================================
    def _apply_data_root(self, parameters, messages=None):
        """
        v0.52.0 — Auto-fill inputs from a one-folder Data Root scan.

        Only fills parameters the user left EMPTY; never overwrites explicit
        choices.  When several datasets exist for one role the scanner ranks
        them by expected accuracy (see ccm_data_discovery docstring) and the
        report lines name the chosen source and the alternatives.
        Returns a list of 'field <- value' strings.
        """
        filled = []
        if _discovery is None or len(parameters) <= 26:
            return filled
        root = parameters[26].valueAsText
        if not root:
            return filled
        res = _discovery.scan(root)

        def _fill(idx, value, label, multi=False):
            p = parameters[idx]
            if value and not p.value:
                if multi:
                    p.values = value
                else:
                    p.value = value
                filled.append(f"{label} <- " + (
                    f"{len(value)} item(s)" if multi
                    else os.path.basename(str(value))))

        _fill(1,  res["extent_fc"],   "Extent")
        _fill(2,  res["dem"],         "DEM")
        _fill(4,  res["contours"],    "Contours")
        _fill(19, res["veg_rasters"], "Vegetation rasters", multi=True)
        _fill(21, res["hydro"],       "Hydrology",          multi=True)
        _fill(22, res["vehicle_csv"], "Vehicle CSV")

        # Soil — best-ranked candidate, mapped onto the source-specific params
        soil = res["soil"]
        if soil and not parameters[8].value and not parameters[18].value:
            label_by_type = {
                "SLC":       getattr(_soil_mod, "SOURCE_SLC",       "SLC (Canada)"),
                "SSURGO":    getattr(_soil_mod, "SOURCE_SSURGO",    "SSURGO / STATSGO2 (US)"),
                "HWSD":      getattr(_soil_mod, "SOURCE_HWSD",      "HWSD v2 (Global)"),
                "SoilGrids": getattr(_soil_mod, "SOURCE_SOILGRIDS", "SoilGrids 2.0 (Global)"),
                "Generic":   getattr(_soil_mod, "SOURCE_AUTO",      "Auto-Detect"),
            } if _soil_mod else {}
            param_by_key = {
                "soil_raw": 8, "cmp_table": 9, "layer_table": 10,
                "name_table": 11, "slc_gdb": 12, "ssurgo": 13,
                "hwsd_mdb": 14, "sg_folder": 15,
            }
            src_label = label_by_type.get(soil["source_type"])
            if src_label and (not parameters[7].value or
                              str(parameters[7].value) ==
                              getattr(_soil_mod, "SOURCE_AUTO", "Auto-Detect")):
                parameters[7].value = src_label
                filled.append(f"Soil Source <- {src_label}")
            for key, path in (soil.get("paths") or {}).items():
                idx = param_by_key.get(key)
                if idx is not None and path and not parameters[idx].value:
                    parameters[idx].value = path
                    filled.append(
                        f"Soil {key} <- {os.path.basename(str(path))}")

        if messages is not None:
            for role, what, why in res["report"]:
                messages.addMessage(f"[Step 1] Data root — {role}: {what}  ({why})")
        return filled

    # v0.57 post-review "P-2": Plan v2 §3.5 specified that Step 1 reuse Step
    # 0b's ccm_data_catalog.json for the same data root — that hand-off was
    # never built (data_catalog_json was written by Step 0b and read by no
    # production code). This does NOT replace _apply_data_root()'s own
    # fill logic above (unchanged, zero risk to the existing auto-fill
    # behaviour) — it only SURFACES the catalog's CRS/resolution/coverage
    # facts and missing-role model impacts as messages, at EXECUTE time
    # only (never in updateParameters — the dialog must stay instant, same
    # rule _apply_data_root already follows). See CHANGELOG_v0.57.md "P-2".
    _MISSING_ROLE_IMPACT = {
        # Phrasing mirrors this file's own updateMessages() warnings above
        # (DEM/Slope, Soil, Vegetation) so the same fact is stated the same
        # way whether the analyst sees it in the dialog or in this log.
        "dem":       "no DEM/slope source found — F1_slope = 1.0 everywhere "
                     "(flat-terrain assumption) unless Slope Regions are supplied.",
        "soil":      "no soil dataset found — F4/F5 will default to GO "
                     "(bearing-capacity not computed) unless soil is supplied.",
        "veg":       "no vegetation dataset found — F2/F3 default to 1.0 "
                     "(vegetation ignored) unless vegetation is supplied.",
        "hydro":     "no hydrology layer found — open-water crossings will "
                     "not be flagged as NO GO unless hydrology is supplied.",
        "contours":  "no contours found — vegetation-height normalisation is "
                     "reduced; usually non-blocking when a valid DEM is present.",
        "vehicle":   "no vehicle CSV found — the default Vehicles_Can.csv "
                     "will be used unless one is supplied.",
        "extent":    "no analysis extent found — Step 1 requires an Analysis "
                     "Extent polygon to proceed.",
        "moisture":  "no soil-moisture dataset found — Step 2's spatial "
                     "moisture option needs live weather instead.",
    }

    def _load_catalog_for_root(self, root, project_folder):
        """
        Load ccm_data_catalog.json from *project_folder* iff it was produced
        for THIS same *root* (Step 0b was run against this data root).
        Returns the catalog dict, or None if unavailable / for a different
        root / on any read error (never raises — this is purely additive).
        """
        if _catalog_mod is None or not project_folder or not root:
            return None
        try:
            cat = _catalog_mod.load_catalog_json(str(project_folder))
        except Exception:
            return None
        if not cat:
            return None
        cat_root = cat.get("data_root")
        if not cat_root or os.path.normcase(os.path.normpath(str(cat_root))) \
                != os.path.normcase(os.path.normpath(str(root))):
            return None  # catalog on disk is for a different data root — ignore it
        return cat

    def _log_catalog_facts(self, parameters, messages):
        """Execute-time only: surface Step 0b's catalog facts, if present."""
        if len(parameters) <= 26:
            return
        root = parameters[26].valueAsText
        project_folder = parameters[0].valueAsText
        cat = self._load_catalog_for_root(root, project_folder)
        if not cat:
            return

        arcpy.AddMessage(
            "[Step 1] Reusing Step 0b Data Intelligence catalog for this data "
            f"root ({_catalog_mod.CATALOG_FILENAME}, scanned "
            f"{cat.get('created', 'unknown time')}):"
        )
        for role, bucket in sorted((cat.get("roles") or {}).items()):
            records = bucket.get("records") or []
            if not records:
                continue
            rec = records[0]
            crs = (rec.get("crs") or {}).get("name") or "CRS unknown"
            res_d = rec.get("resolution") or {}
            res_txt = (
                f"{res_d['cell_size_m']} m" if res_d.get("cell_size_m") is not None
                else (f"{res_d['feature_count']:,} feature(s)"
                      if res_d.get("feature_count") is not None else "n/a")
            )
            cov = rec.get("coverage_aoi_pct")
            cov_txt = f"{cov:.0f}% of AOI" if isinstance(cov, (int, float)) else "coverage unknown"
            extra = "" if len(records) == 1 else f"  (+{len(records) - 1} alternate(s))"
            arcpy.AddMessage(
                f"    {role:<10} {os.path.basename(str(rec.get('path', '')))}"
                f"  ·  {crs}  ·  {res_txt}  ·  {cov_txt}{extra}"
            )
        for role in sorted(cat.get("missing_roles") or []):
            impact = self._MISSING_ROLE_IMPACT.get(
                role, "model impact not documented for this role.")
            arcpy.AddWarning(f"[Step 1] Catalog: no {role} data catalogued — {impact}")

    def _apply_manifest(self, parameters, messages=None):
        """
        v0.50.0 — Auto-fill inputs from an MGCP manifest (Step 0 output).

        Only fills parameters the user has left EMPTY; never overwrites
        explicit choices.  Returns a list of 'field <- value' strings
        describing what was filled (empty list if nothing applied).
        """
        filled = []
        if _catalog is None or len(parameters) <= 25:
            return filled
        m_path = parameters[25].valueAsText
        if not m_path:
            return filled
        manifest = _catalog.load_manifest(m_path)
        if not manifest:
            return filled

        def _first_path(role):
            entries = _catalog.features_by_role(manifest, role)
            return entries[0]["path"] if entries else None

        def _all_paths(role, geometry=None):
            out = []
            for e in _catalog.features_by_role(manifest, role):
                if geometry and e.get("geometry") not in (None, geometry):
                    continue
                out.append(e["path"])
            return out

        # Soil — DA010 (SMC) → soil_raw + source type MGCP
        soil_path = _first_path(_catalog.ROLE_SOIL)
        if soil_path and not parameters[8].value and not parameters[18].value:
            parameters[8].value = soil_path
            filled.append(f"Soil FC <- {os.path.basename(soil_path)}")
            src_mgcp = getattr(_soil_mod, "SOURCE_MGCP", "MGCP") if _soil_mod else "MGCP"
            if not parameters[7].value or \
                    str(parameters[7].value) == getattr(_soil_mod, "SOURCE_AUTO",
                                                        "Auto-Detect"):
                parameters[7].value = src_mgcp
                filled.append(f"Soil Source <- {src_mgcp}")

        # Hydrology — all water-body polygons
        hydro_paths = _all_paths(_catalog.ROLE_HYDRO, geometry="Polygon")
        if hydro_paths and not parameters[21].value:
            parameters[21].values = hydro_paths
            filled.append(
                "Hydrology <- " + ", ".join(os.path.basename(h)
                                            for h in hydro_paths)
            )

        # Contours — CA010, only useful when no DEM was given
        contours_path = _first_path(_catalog.ROLE_CONTOURS)
        if contours_path and not parameters[4].value:
            parameters[4].value = contours_path
            filled.append(f"Contours <- {os.path.basename(contours_path)}")

        return filled

    # =========================================================================
    def updateParameters(self, parameters):
        p_soil_preproc = parameters[18]
        p_soil_raw     = parameters[8]
        p_veg_preproc  = parameters[20]
        p_veg_rasters  = parameters[19]

        # If a pre-processed FC is provided, disable the raw data fields
        if p_soil_preproc.value:
            p_soil_raw.enabled = False
        else:
            p_soil_raw.enabled = True

        if p_veg_preproc.value:
            p_veg_rasters.enabled = False
        else:
            p_veg_rasters.enabled = True

        # v0.52.0 — Data Root auto-fill (runs once per root path)
        if len(parameters) > 26 and parameters[26].value:
            r_key = str(parameters[26].valueAsText)
            if getattr(self, "_data_root_applied", None) != r_key:
                self._data_root_applied = r_key
                self._apply_data_root(parameters)

        # v0.50.0 — MGCP manifest auto-fill (runs once per manifest path)
        if len(parameters) > 25 and parameters[25].value:
            m_key = str(parameters[25].valueAsText)
            if getattr(self, "_manifest_applied", None) != m_key:
                self._manifest_applied = m_key
                self._apply_manifest(parameters)

    # =========================================================================
    def updateMessages(self, parameters):
        p_folder       = parameters[0]
        p_extent       = parameters[1]
        p_dem          = parameters[2]
        p_slope        = parameters[3]
        p_soil_raw     = parameters[8]
        p_soil_preproc = parameters[18]
        p_veg_rasters  = parameters[19]
        p_veg_preproc  = parameters[20]
        p_vehicle_csv  = parameters[22]

        # Extent CRS check
        if p_extent.value and not p_extent.hasError():
            try:
                d = arcpy.Describe(p_extent.valueAsText)
                if d.spatialReference.type == "Geographic":
                    p_extent.setErrorMessage(
                        f"Analysis Extent uses a Geographic CRS "
                        f"({d.spatialReference.name}).\n\n"
                        "CCM requires a Projected CRS (e.g. UTM) so that distances "
                        "and areas are computed in metres.\n"
                        "How to fix: right-click the layer in ArcGIS Pro → Data → "
                        "Export Features → change the output CRS to the appropriate "
                        "UTM zone, then use the reprojected FC here."
                    )
                elif d.shapeType != "Polygon":
                    p_extent.setErrorMessage(
                        f"Analysis Extent must be a Polygon feature class "
                        f"(got geometry type '{d.shapeType}').\n"
                        "Draw or import a polygon that covers your study area."
                    )
            except Exception:
                pass

        # v0.54.0 — smart CRS warnings on supporting layers.  The Extent
        # check above is the blocking gate; these are advisory (warning, not
        # error) so a mismatch never silently blocks a run on its own — but
        # a geographic or mismatched layer here can still misalign results
        # or be silently wrong.  See User Manual Section 3.4.
        if _coords_mod:
            _ext_sr_type = _ext_sr_name = _ext_sr_code = None
            if p_extent.value and not p_extent.hasError():
                _ext_sr_type, _ext_sr_name, _ext_sr_code = \
                    _coords_mod.describe_spatial_reference(p_extent.valueAsText)

            if _ext_sr_type == "Projected":
                p_contours_ref = parameters[4]
                p_hydro_ref    = parameters[21]

                def _check_layer_crs(_p, _label, _path):
                    if not _path or _p.hasError():
                        return
                    _typ, _name, _code = _coords_mod.describe_spatial_reference(_path)
                    if _typ is None:
                        return
                    if _typ == "Geographic":
                        _p.setWarningMessage(
                            _coords_mod.geographic_crs_warning(_label, _name))
                    elif _code and _ext_sr_code and _code != _ext_sr_code:
                        _p.setWarningMessage(
                            _coords_mod.crs_mismatch_warning(
                                _label, _name, "Analysis Extent", _ext_sr_name))

                _check_layer_crs(p_dem,          "DEM",                    p_dem.valueAsText)
                _check_layer_crs(p_slope,        "Slope Regions",          p_slope.valueAsText)
                _check_layer_crs(p_contours_ref, "Contour Lines",          p_contours_ref.valueAsText)
                _check_layer_crs(p_soil_raw,     "Raw Soil FC/Raster",     p_soil_raw.valueAsText)
                _check_layer_crs(p_soil_preproc, "Pre-processed Soil FC",  p_soil_preproc.valueAsText)
                _check_layer_crs(p_veg_preproc,  "Pre-processed Vegetation FC", p_veg_preproc.valueAsText)

                # Hydro is multiValue — aggregate into one message per
                # parameter so later paths don't overwrite earlier warnings.
                if p_hydro_ref.value:
                    try:
                        _hydro_paths = [str(v) for v in (p_hydro_ref.values or [])]
                    except Exception:
                        _hydro_paths = []
                    _hydro_msgs = []
                    for _hp in _hydro_paths:
                        _typ, _name, _code = _coords_mod.describe_spatial_reference(_hp)
                        if _typ is None:
                            continue
                        _base = os.path.basename(_hp)
                        if _typ == "Geographic":
                            _hydro_msgs.append(f"  • {_base}: Geographic CRS ({_name})")
                        elif _code and _ext_sr_code and _code != _ext_sr_code:
                            _hydro_msgs.append(f"  • {_base}: {_name} (differs from Analysis Extent)")
                    if _hydro_msgs:
                        p_hydro_ref.setWarningMessage(
                            "One or more Hydrology layers do not match the "
                            "Analysis Extent's Projected CRS:\n"
                            + "\n".join(_hydro_msgs)
                            + "\n\nReproject mismatched layers to match the "
                            "Analysis Extent (ArcGIS Pro -> Data -> Export "
                            "Features).  See User Manual Section 3.4."
                        )

        # DEM / Slope: at least one must be provided for slope analysis
        if not p_dem.value and not p_slope.value:
            p_dem.setWarningMessage(
                "No DEM or Slope Regions provided.\n\n"
                "Without slope data the mobility model will assume flat terrain "
                "(F1_slope = 1.0 everywhere), which overestimates GO area.\n\n"
                "Provide one of:\n"
                "  • DEM raster (.tif / .img / GDB raster) — slope is derived automatically\n"
                "  • Slope Regions polygon FC with a percent- or degree-slope attribute field"
            )

        # Soil: one of raw or preproc must be provided
        if not p_soil_raw.value and not p_soil_preproc.value:
            p_soil_raw.setWarningMessage(
                "No soil data provided.\n\n"
                "Without soil data the model cannot compute bearing-capacity factors "
                "(F4/F5) and will default to GO for all terrain — this underestimates "
                "NO GO area on wet/fine-grained soils.\n\n"
                "Provide one of:\n"
                "  • Raw Soil FC or HWSD raster to auto pre-process (select Source Type)\n"
                "  • An existing pre-processed Soil FC (field 'soilType' with USCS codes) "
                "in the 'Pre-processed Soil FC' field to skip pre-processing\n\n"
                "Supported soil sources: DSS/SLC Canada (.dbf tables + polygon FC), "
                "SSURGO/STATSGO2 US (tabular folder or gSSURGO .gdb), "
                "HWSD Global (.mdb + raster), SoilGrids 2.0 (raster folder), "
                "MGCP SMC polygon FC (Auto-Detect)"
            )

        # Veg: one of rasters or preproc must be provided
        if not p_veg_rasters.value and not p_veg_preproc.value:
            p_veg_rasters.setWarningMessage(
                "No vegetation data provided.\n\n"
                "Without vegetation data F2 (density) and F3 (spacing) default to 1.0, "
                "which ignores forest/canopy cover and may overestimate vehicle speed "
                "through wooded areas.\n\n"
                "Provide one of:\n"
                "  • Vegetation / Biophysical raster(s) — supports:\n"
                "      - Canada Biophysical LAI + fCOVER + GLAD Canopy Height "
                "(.tif tiles, select all in one pick)\n"
                "      - GEDI L4B canopy height raster (.tif)\n"
                "      - Generic land-cover rasters with class codes\n"
                "  • An existing pre-processed Vegetation FC (fields: vegetationTrafficImpact, "
                "treeSpacing, stemDiameter) in the 'Pre-processed Vegetation FC' field"
            )

        # Vehicle CSV check
        if p_vehicle_csv.value and not p_vehicle_csv.hasError():
            csv_path = str(p_vehicle_csv.valueAsText)
            if not os.path.isfile(csv_path):
                p_vehicle_csv.setErrorMessage(
                    f"Vehicle CSV not found: {csv_path}\n"
                    "The default Vehicles_Can.csv is in the Vehicle_Data\\ sub-folder "
                    "next to this toolbox."
                )
            else:
                try:
                    import csv as _csv
                    with open(csv_path, encoding="utf-8-sig") as fh:
                        headers = [h.strip().lower() for h in
                                   next(_csv.reader(fh))]
                    required = {"name", "vci_1", "vci_50", "max_road_spd_kph"}
                    missing = required - set(headers)
                    if missing:
                        p_vehicle_csv.setWarningMessage(
                            f"Vehicle CSV may be missing required columns: "
                            f"{', '.join(sorted(missing))}\n"
                            "Required: name, vci_1, vci_50, max_road_spd_kph\n"
                            "Optional: max_off_road_grad, vehicle_width_m, "
                            "max_override_diameter_m, locomotion_type, mmp_kpa"
                        )
                except Exception:
                    pass

        # Check for ccm_project.json collision
        if p_folder.value:
            cfg_path = os.path.join(
                str(p_folder.valueAsText), "ccm_project.json"
            )
            if os.path.isfile(cfg_path):
                p_folder.setWarningMessage(
                    "A ccm_project.json already exists in this folder — "
                    "running Step 1 will update it with the new settings.\n"
                    "Existing paths not re-supplied here will be preserved.\n"
                    "To start fresh, choose a different output folder or "
                    "delete ccm_project.json manually."
                )

    # =========================================================================
    def execute(self, parameters, messages):
        arcpy.SetLogMetadata(False)  # Prevent GDB history metadata accumulation (perf)

        # v0.52.0 — apply Data Root auto-fill also at execute time
        try:
            _r_filled = self._apply_data_root(parameters, messages)
            for _f in _r_filled:
                arcpy.AddMessage(f"[Step 1] Data-root auto-fill: {_f}")
        except Exception as _r_exc:
            arcpy.AddWarning(f"[Step 1] Data-root auto-fill skipped: {_r_exc}")

        # v0.57 post-review "P-2" — surface Step 0b's catalog facts, if a
        # matching ccm_data_catalog.json exists for this data root. Additive
        # only: never changes what _apply_data_root() above just filled.
        try:
            self._log_catalog_facts(parameters, messages)
        except Exception as _cat_exc:
            arcpy.AddWarning(f"[Step 1] Data Intelligence catalog check skipped: {_cat_exc}")

        # v0.50.0 — apply MGCP manifest auto-fill also at execute time so that
        # scripted invocations (run_tool) benefit, not just the dialog.
        try:
            _filled = self._apply_manifest(parameters, messages)
            for _f in _filled:
                arcpy.AddMessage(f"[Step 1] Manifest auto-fill: {_f}")
        except Exception as _m_exc:
            arcpy.AddWarning(f"[Step 1] Manifest auto-fill skipped: {_m_exc}")

        project_folder  = parameters[0].valueAsText
        extent_fc       = parameters[1].valueAsText
        dem_path        = parameters[2].valueAsText
        slope_fc        = parameters[3].valueAsText
        contours_fc     = parameters[4].valueAsText
        moisture        = parameters[5].valueAsText

        soil_source     = parameters[7].valueAsText
        soil_raw        = parameters[8].valueAsText
        soil_cmp        = parameters[9].valueAsText
        soil_layer_tbl  = parameters[10].valueAsText
        soil_name_tbl   = parameters[11].valueAsText
        soil_slc_gdb    = parameters[12].valueAsText
        soil_ssurgo     = parameters[13].valueAsText
        soil_hwsd       = parameters[14].valueAsText
        soil_sg_folder  = parameters[15].valueAsText
        soil_sg_depth   = parameters[16].valueAsText
        soil_gapfill    = parameters[17].valueAsText
        soil_preproc    = parameters[18].valueAsText

        veg_rasters_raw = parameters[19].valueAsText   # semicolon list or None
        veg_preproc     = parameters[20].valueAsText

        hydro_param     = parameters[21]
        vehicle_csv     = parameters[22].valueAsText
        slope_field     = parameters[23].valueAsText   # explicit slope-value field (optional)
        slope_units     = (parameters[24].valueAsText or "percent")

        # v0.58.2: surface Step 0b recommendations for review. This is
        # intentionally display-only; the user's explicit Step 1 parameters
        # remain authoritative and no source is replaced automatically.
        try:
            from ccm_step1_recommendations_ui import display_recommendations
            display_recommendations(project_folder, arcpy_module=arcpy, verbose=False)
        except Exception as _rec_exc:
            arcpy.AddWarning(
                f"[Step 1] Recommendation display skipped: {_rec_exc}"
            )

        # ── Ensure project folder exists ──────────────────────────────────────
        os.makedirs(project_folder, exist_ok=True)

        # ── Build output GDB path ─────────────────────────────────────────────
        gdb_name     = "CCM_Project.gdb"
        project_gdb  = os.path.join(project_folder, gdb_name)
        if not arcpy.Exists(project_gdb):
            arcpy.management.CreateFileGDB(project_folder, gdb_name)
            arcpy.AddMessage(f"[Step 1] Created project GDB: {project_gdb}")

        # ── Pre-process Soil ──────────────────────────────────────────────────
        final_soil_fc = soil_preproc  # use override if supplied

        if not final_soil_fc and soil_raw:
            if _CCMSoilPreprocessTool is None:
                arcpy.AddError(
                    "[Step 1] ccm_soil_preprocess.py not loaded — cannot pre-process soil."
                )
                return

            arcpy.AddMessage("[Step 1] ── Running Soil Pre-processing ──────────────")
            soil_output_fc = os.path.join(project_gdb, "soil_ccm")

            # Invoke the soil tool by parameter NAME (no fragile index list).
            # Parameter names come from CCMSoilPreprocessTool.getParameterInfo().
            try:
                if _cfg_mod and hasattr(_cfg_mod, "run_tool"):
                    _cfg_mod.run_tool(
                        _CCMSoilPreprocessTool(), messages,
                        source_type   = soil_source,
                        soil_fc       = soil_raw,
                        cmp_table     = soil_cmp,
                        layer_table   = soil_layer_tbl,
                        name_table    = soil_name_tbl,
                        slc_gdb       = soil_slc_gdb,
                        ssurgo_tabular= soil_ssurgo,
                        hwsd_mdb      = soil_hwsd,
                        soilgrids_folder = soil_sg_folder,
                        soilgrids_depth  = soil_sg_depth,
                        mgcp_smc_field   = "SMC",
                        extent_fc     = extent_fc,
                        gap_fill_code = soil_gapfill,
                        output_fc     = soil_output_fc,
                    )
                else:
                    # Fallback: positional shim (legacy path)
                    _CCMSoilPreprocessTool().execute([
                        _P(soil_source), _P(soil_raw), _P(soil_cmp),
                        _P(soil_layer_tbl), _P(soil_name_tbl), _P(soil_slc_gdb),
                        _P(soil_ssurgo), _P(soil_hwsd), _P(soil_sg_folder),
                        _P(soil_sg_depth), _P("SMC"), _P(None), _P(None),
                        _P(None), _P(None), _P(None), _P(None), _P(None),
                        _P(extent_fc), _P(soil_gapfill), _P(soil_output_fc),
                    ], messages)
                final_soil_fc = soil_output_fc
                arcpy.AddMessage(f"[Step 1] Soil pre-processing complete → {final_soil_fc}")
            except Exception as exc:
                arcpy.AddError(f"[Step 1] Soil pre-processing failed: {exc}")
                return

        elif final_soil_fc:
            arcpy.AddMessage(
                f"[Step 1] Using existing pre-processed Soil FC: {final_soil_fc}"
            )
            # v0.57 post-review "M-2": this is a user-supplied override — unlike
            # the auto-pre-processed path above (which always writes canonical
            # USCS codes via ccm_soil_preprocess.py), nothing previously checked
            # that this FC even HAS a usable soilType/USCS field before Step 2
            # ran on it. A mismatch here used to fail silently (see H-3):
            # soil_factor() would find no RCI match and treat every polygon as
            # unpenalised full-speed soil, with no warning anywhere.
            if _soil_validator_mod is not None:
                try:
                    _sv_result = _soil_validator_mod.validate_soil_fc(final_soil_fc)
                    arcpy.AddMessage(
                        f"[Step 1] Soil field detection: level {_sv_result.level}, "
                        f"confidence {_sv_result.confidence}"
                        + (f", field '{_sv_result.uscs_field}'" if _sv_result.uscs_field else "")
                        + (f" — {_sv_result.action}" if _sv_result.action else "")
                    )
                    if _sv_result.warning:
                        arcpy.AddWarning(f"[Step 1] Soil FC check: {_sv_result.warning}")
                    if not _sv_result.can_proceed:
                        arcpy.AddError(
                            "[Step 1] The supplied Pre-processed Soil FC has no "
                            "field ccm_soil_validator recognises as a USCS code "
                            "or derivable texture percentages. Step 2 would run "
                            "with soil silently unpenalised on every polygon. "
                            "Fix the field name/values, or clear this override "
                            "and supply Raw Soil Data instead so Step 1's own "
                            "pre-processor can produce a canonical soilType field."
                        )
                        return
                except Exception as _sv_exc:
                    arcpy.AddWarning(
                        f"[Step 1] Soil validator could not check '{final_soil_fc}' "
                        f"({_sv_exc}); it will be used unchecked."
                    )
            else:
                arcpy.AddWarning(
                    "[Step 1] ccm_soil_validator not loaded — the supplied "
                    "Pre-processed Soil FC's field/values were not checked."
                )
        else:
            arcpy.AddWarning(
                "[Step 1] No soil data provided — soil_fc will not be set in config."
            )

        # ── Pre-process Vegetation ────────────────────────────────────────────
        final_veg_fc = veg_preproc  # use override if supplied

        if not final_veg_fc and veg_rasters_raw:
            if _CCMVegPreprocessTool is None:
                arcpy.AddError(
                    "[Step 1] ccm_veg_preprocess.py not loaded — cannot "
                    "pre-process vegetation."
                )
                return

            arcpy.AddMessage("[Step 1] ── Running Vegetation Pre-processing ─────")
            veg_output_fc = os.path.join(project_gdb, "veg_ccm")

            # Invoke the veg tool by parameter NAME (no fragile index list).
            try:
                if _cfg_mod and hasattr(_cfg_mod, "run_tool"):
                    _cfg_mod.run_tool(
                        _CCMVegPreprocessTool(), messages,
                        raster_path = veg_rasters_raw,
                        extent_fc   = extent_fc,
                        output_fc   = veg_output_fc,
                    )
                else:
                    # Fallback: positional shim (legacy path).  Order matches
                    # CCMVegPreprocessTool.getParameterInfo():
                    #   [source_type, raster_path, extent_fc, output_fc,
                    #    gap_vti, gap_tree_spacing, gap_stem_diameter,
                    #    bio_folder, detected_source]
                    _CCMVegPreprocessTool().execute([
                        _P(None), _P(veg_rasters_raw), _P(extent_fc),
                        _P(veg_output_fc), _P(None), _P(None), _P(None),
                        _P(None), _P(None),
                    ], messages)
                final_veg_fc = veg_output_fc
                arcpy.AddMessage(
                    f"[Step 1] Vegetation pre-processing complete → {final_veg_fc}"
                )
            except Exception as exc:
                arcpy.AddError(f"[Step 1] Vegetation pre-processing failed: {exc}")
                return

        elif final_veg_fc:
            arcpy.AddMessage(
                f"[Step 1] Using existing pre-processed Vegetation FC: "
                f"{final_veg_fc}"
            )
        else:
            arcpy.AddWarning(
                "[Step 1] No vegetation data provided — veg_fc will not be "
                "set in config."
            )

        # ── Slope Regions (provided FC, or derived from DEM) ─────────────────
        final_slope_fc  = slope_fc
        final_slope_fld = slope_field
        final_slope_uni = slope_units

        if not final_slope_fc and dem_path:
            arcpy.AddMessage("[Step 1] ── Deriving Slope Regions from DEM ───────")
            try:
                if arcpy.CheckExtension("Spatial") != "Available":
                    raise RuntimeError("Spatial Analyst extension not available")
                arcpy.CheckOutExtension("Spatial")
                try:
                    from arcpy.sa import (Slope, Reclassify, RemapRange,
                                          ExtractByMask)

                    dem_ras = dem_path
                    if extent_fc and arcpy.Exists(extent_fc):
                        dem_ras = ExtractByMask(dem_path, extent_fc)

                    slope_ras = Slope(dem_ras, "PERCENT_RISE")

                    # CCM slope classes (percent) — cell value = class midpoint:
                    #   0-3, 3-6, 6-10, 10-20, 20-30, 30-45, 45-60, 60+
                    remap = RemapRange([
                        [0,   3,    2], [3,   6,    5], [6,  10,    8],
                        [10, 20,   15], [20, 30,   25], [30, 45,   38],
                        [45, 60,   53], [60, 9999, 70],
                    ])
                    slope_cls = Reclassify(slope_ras, "VALUE", remap, "NODATA")

                    slope_out = os.path.join(project_gdb, "slope_regions")
                    if arcpy.Exists(slope_out):
                        arcpy.management.Delete(slope_out)
                    arcpy.conversion.RasterToPolygon(
                        slope_cls, slope_out, "SIMPLIFY", "Value"
                    )
                    # gridcode carries the class-midpoint percent slope
                    arcpy.management.AddField(slope_out, "slope_pct", "DOUBLE")
                    arcpy.management.CalculateField(
                        slope_out, "slope_pct", "!gridcode!", "PYTHON3"
                    )
                    final_slope_fc  = slope_out
                    final_slope_fld = "slope_pct"
                    final_slope_uni = "percent"
                    arcpy.AddMessage(
                        f"[Step 1] Slope regions derived → {slope_out}"
                    )
                finally:
                    try:
                        arcpy.CheckInExtension("Spatial")
                    except Exception:
                        pass
            except Exception as exc:
                arcpy.AddWarning(
                    f"[Step 1] Slope derivation failed ({exc}) — the mobility "
                    "model will assume flat terrain (F1_slope = 1.0)."
                )
                final_slope_fc = None

        elif final_slope_fc:
            arcpy.AddMessage(
                f"[Step 1] Using provided Slope Regions FC: {final_slope_fc}"
            )
        else:
            arcpy.AddWarning(
                "[Step 1] No DEM or Slope Regions provided — the mobility "
                "model will assume flat terrain (F1_slope = 1.0)."
            )

        # ── Hydrology layer list ──────────────────────────────────────────────
        hydro_fcs = []
        if hydro_param.values:
            hydro_fcs = [str(v) for v in hydro_param.values]
        elif hydro_param.valueAsText:
            hydro_fcs = [s.strip().strip("'\"")
                         for s in hydro_param.valueAsText.split(";")
                         if s.strip()]
        if hydro_fcs:
            arcpy.AddMessage(f"[Step 1] Hydrology layers: {len(hydro_fcs)}")

        # ── Save project config ───────────────────────────────────────────────
        if _cfg_mod is None:
            arcpy.AddError(
                "[Step 1] ccm_project_config.py not loaded — "
                "ccm_project.json not saved."
            )
            return

        cfg_path = _cfg_mod.save_config(
            project_folder,
            extent_fc        = extent_fc,
            dem_path         = dem_path,
            slope_fc         = final_slope_fc,
            slope_field      = final_slope_fld,
            slope_units      = final_slope_uni,
            contours_fc      = contours_fc,
            soil_fc          = final_soil_fc,
            veg_fc           = final_veg_fc,
            hydro_fcs        = hydro_fcs,
            vehicle_csv      = vehicle_csv,
            moisture_default = (moisture or "moist"),
            project_gdb      = project_gdb,
        )

        arcpy.AddMessage(
            f"\n{'='*60}\n"
            f"  STEP 1 COMPLETE — Project configured\n"
            f"{'='*60}\n"
            f"  Config   : {cfg_path}\n"
            f"  GDB      : {project_gdb}\n"
            f"  Soil     : {final_soil_fc or '—'}\n"
            f"  Veg      : {final_veg_fc or '—'}\n"
            f"  Slope    : {final_slope_fc or '—  (flat-terrain assumption)'}\n"
            f"  Hydro    : {len(hydro_fcs)} layer(s)\n"
            f"  Next     : run Step 2 (Generate Mobility Map)\n"
            f"{'='*60}"
        )

# <<< END OF FILE >>>
