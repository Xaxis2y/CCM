# ccm_step1_setup.py
# CCM Step 1 — Project Setup & Pre-process
#
# Collects ALL raw inputs once, runs Soil + Vegetation pre-processing,
# and saves ccm_project.json so Steps 2 & 3 never ask for data again.
#
# VERSION = "0.46"
VERSION = "0.46"  # v0.46 — Added Geomorphon Landforms (Pro 3.5+) optional analysis.
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

_veg_mod = None
try:
    from ccm_veg_preprocess import CCMVegPreprocessTool as _CCMVegPreprocessTool
    import ccm_veg_preprocess as _veg_mod
except Exception as e:
    _CCMVegPreprocessTool = None
    arcpy.AddWarning(f"[Step 1] ccm_veg_preprocess: {e}")

_cfg_mod = None
try:
    import ccm_project_config as _cfg_mod
except Exception as e:
    arcpy.AddWarning(f"[Step 1] ccm_project_config: {e}")


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
        ]

    def isLicensed(self):
        return True

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

    # =========================================================================
    def updateMessages(self, parameters):
        p_folder       = parameters[0]
        p_extent       = parameters[1]
        p_soil_raw     = parameters[8]
        p_soil_preproc = parameters[18]
        p_veg_rasters  = parameters[19]
        p_veg_preproc  = parameters[20]

        # Extent CRS check
        if p_extent.value and not p_extent.hasError():
            try:
                d = arcpy.Describe(p_extent.valueAsText)
                if d.spatialReference.type == "Geographic":
                    p_extent.setErrorMessage(
                        f"Analysis Extent uses a Geographic CRS "
                        f"({d.spatialReference.name}).  "
                        "Reproject to a Projected CRS (e.g. UTM) first."
                    )
                elif d.shapeType != "Polygon":
                    p_extent.setErrorMessage(
                        f"Analysis Extent must be a Polygon FC (got '{d.shapeType}')."
                    )
            except Exception:
                pass

        # Soil: one of raw or preproc must be provided
        if not p_soil_raw.value and not p_soil_preproc.value:
            p_soil_raw.setWarningMessage(
                "Provide either raw soil data to pre-process, "
                "or an existing pre-processed Soil FC."
            )

        # Veg: one of rasters or preproc must be provided
        if not p_veg_rasters.value and not p_veg_preproc.value:
            p_veg_rasters.setWarningMessage(
                "Provide either vegetation rasters to pre-process, "
                "or an existing pre-processed Vegetation FC."
            )

        # Check for ccm_project.json collision
        if p_folder.value:
            cfg_path = os.path.join(
                str(p_folder.valueAsText), "ccm_project.json"
            )
            if os.path.isfile(cfg_path):
                p_folder.setWarningMessage(
                    "ccm_project.json already exists in this folder — "
                    "running Step 1 will update it."
                )

    # =========================================================================
    def execute(self, parameters, messages):
        arcpy.SetLogMetadata(False)  # Prevent GDB history metadata accumulation (perf)

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
        else:
            arcpy.AddWarning(
                "[Step 1] No soil data provided — soil_fc will not be set in config."
            )

        # ── Pre-process Vegetation ────────────────────────────────────────────
        final_veg_fc = veg_preproc  # use override if supplied

        if not final_veg_fc and veg_rasters_raw:
            if _CCMVegPreprocessTool is None:
                arcpy.AddError(
                    "[Step 1] ccm_veg_preprocess.py not loaded — cannot pre-process vegetation."
                )
                return

            arcpy.AddMessage("[Step 1] ── Running Vegetation Pre-processing ─────────")
            veg_output_fc = os.path.join(project_gdb, "veg_ccm")

            # Invoke the vegetation tool by parameter NAME (no fragile index list).
            try:
                if _cfg_mod and hasattr(_cfg_mod, "run_tool"):
                    _cfg_mod.run_tool(
                        _CCMVegPreprocessTool(), messages,
                        raster_path       = _parse_multi(veg_rasters_raw),
                        extent_fc         = extent_fc,
                        output_fc         = veg_output_fc,
                        gap_vti           = 0.2,
                        gap_tree_spacing  = 0.0,
                        gap_stem_diameter = 0.0,
                    )
                else:
                    _CCMVegPreprocessTool().execute([
                        _P(None),
                        _P(veg_rasters_raw, veg_rasters_raw,
                           values=_parse_multi(veg_rasters_raw)),
                        _P(extent_fc), _P(veg_output_fc),
                        _P(0.2, "0.2"), _P(0.0, "0.0"), _P(0.0, "0.0"),
                        _P(None), _P(None),
                    ], messages)
                final_veg_fc = veg_output_fc
                arcpy.AddMessage(f"[Step 1] Veg pre-processing complete → {final_veg_fc}")
            except Exception as exc:
                arcpy.AddError(f"[Step 1] Vegetation pre-processing failed: {exc}")
                return

        elif final_veg_fc:
            arcpy.AddMessage(
                f"[Step 1] Using existing pre-processed Vegetation FC: {final_veg_fc}"
            )
        else:
            arcpy.AddWarning(
                "[Step 1] No vegetation data provided — veg_fc will not be set in config."
            )

        # ── Build hydro list ──────────────────────────────────────────────────
        hydro_list = []
        if hydro_param.value and hydro_param.values:
            hydro_list = [str(v) for v in hydro_param.values if v]

        # ── Geomorphon Landforms (Pro 3.5+, optional) ─────────────────────────
        # Classifies terrain pixels into landform types (ridges, valleys, slopes,
        # etc.) at high speed from the DEM.  Stored in the project GDB as a
        # supplemental layer; Step 2 can optionally use it to refine slope regions.
        geomorphon_ras_path = None
        if dem_path and arcpy.Exists(dem_path):
            try:
                _inst = arcpy.GetInstallInfo()
                _ver_str = _inst.get("Version", "0.0")
                _ver_parts = tuple(int(x) for x in _ver_str.split(".")[:2])
                if _ver_parts >= (3, 5):
                    arcpy.AddMessage(
                        "[Step 1] Running Geomorphon Landforms (Pro 3.5+) …"
                    )
                    import arcpy.sa as _sa
                    geomorphon_result = _sa.GeomorphonLandforms(dem_path)
                    geomorphon_ras_path = os.path.join(project_gdb, "geomorphon_landforms")
                    if arcpy.Exists(geomorphon_ras_path):
                        arcpy.management.Delete(geomorphon_ras_path)
                    geomorphon_result.save(geomorphon_ras_path)
                    arcpy.AddMessage(
                        f"[Step 1] Geomorphon Landforms saved → {geomorphon_ras_path}"
                    )
                else:
                    arcpy.AddMessage(
                        f"[Step 1] Geomorphon Landforms skipped — "
                        f"requires Pro 3.5+ (detected {_ver_str})."
                    )
            except Exception as _geo_e:
                arcpy.AddWarning(
                    f"[Step 1] Geomorphon Landforms failed (non-fatal): {_geo_e}"
                )

        # ── Save ccm_project.json ─────────────────────────────────────────────
        if _cfg_mod is None:
            arcpy.AddWarning(
                "[Step 1] ccm_project_config.py not loaded — cannot save config."
            )
        else:
            cfg_path = _cfg_mod.save_config(
                project_folder,
                extent_fc           = extent_fc,
                dem_path            = dem_path,
                slope_fc            = slope_fc,
                contours_fc         = contours_fc,
                soil_fc             = final_soil_fc,
                veg_fc              = final_veg_fc,
                hydro_fcs           = hydro_list,
                vehicle_csv         = vehicle_csv,
                moisture_default    = moisture,
                project_gdb         = project_gdb,
                geomorphon_ras      = geomorphon_ras_path,
            )
            arcpy.AddMessage(f"[Step 1] Project config saved → {cfg_path}")

        arcpy.AddMessage("=" * 60)
        arcpy.AddMessage("  Step 1 complete.  Open Step 2 to generate mobility maps.")
        arcpy.AddMessage("=" * 60)


# ── Helper ────────────────────────────────────────────────────────────────────

def _parse_multi(semicolon_string):
    """Split ArcGIS multiValue semicolon string into a list of path strings."""
    if not semicolon_string:
        return []
    import re
    # Strip outer quotes that ArcGIS adds to paths with spaces
    parts = semicolon_string.split(";")
    result = []
    for p in parts:
        p = p.strip().strip(chr(34)).strip(chr(39))
        if p:
            result.append(p)
    return result

# <<< END OF FILE >>>
