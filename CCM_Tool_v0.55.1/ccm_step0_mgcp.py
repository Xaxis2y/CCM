# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
ccm_step0_mgcp.py  —  Step 0: Load MGCP Data
=============================================
Batch-loads MGCP data (GeoPackage, File GDB, Shapefiles) into a target
File Geodatabase and adds layers to the active ArcGIS Pro map.
Matching FC names across multiple cells are appended into single layers.

Merged from LoadMGCPData_v0.12 (standalone MGCP Data Loader toolbox).

Change log (MGCP loader lineage):
  v0.10  2026-06-24  Initial release
  v0.11  2026-06-24  Logic review fixes (OVERWRITE-then-append, group-layer
                     nesting, FC-name validation, gpkg prefix consistency,
                     optional output CRS, scan caching).
  v0.12  2026-06-24  Recursive shapefile scanning; per-cell source labels.
  v0.12+ 2026-06-28  Integrated into CCM Tool as Step 0.
  v0.13  2026-07-01  (CCM v0.50.0) MGCP/FACC catalog integration:
                     human-readable pick-list labels, theme filter,
                     group-by-theme map layers, mgcp_manifest.json output
                     consumed by Step 1 auto-fill.  BUG-4 fix
                     (overwriteOutput no longer clobbered mid-run).
"""

import arcpy
import os
import sys
import json
import datetime
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:
    import ccm_mgcp_catalog as _catalog
except Exception as _cat_e:
    _catalog = None
    try:
        arcpy.AddWarning(f"[Step 0] ccm_mgcp_catalog not loaded: {_cat_e}")
    except Exception:
        pass

try:
    import ccm_data_discovery as _discovery
except Exception as _dd_e:
    _discovery = None
    try:
        arcpy.AddWarning(f"[Step 0] ccm_data_discovery not loaded: {_dd_e}")
    except Exception:
        pass

try:
    import ccm_coords as _coords_mod
except Exception as _cd_e:
    _coords_mod = None
    try:
        arcpy.AddWarning(f"[Step 0] ccm_coords not loaded: {_cd_e}")
    except Exception:
        pass

VERSION = "0.55.1"  # v0.55.1 -- version bump only: added QUICK_START.html and CCM_anaconda_environment.bat (Anaconda Prompt environment setup script); no code/logic changes. See CHANGELOG_v0.55.md.
_MGCP_VERSION = "v0.13"

# Pick-list convenience entry that expands to all CCM-relevant themes
_CCM_ONLY = "CCM-Relevant Only (Soil / Vegetation / Hydrography / Transportation / Elevation / Physiography)"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _iter_shapefiles(folder, recurse):
    """Yield absolute paths to .shp files in *folder*.

    recurse=True  -> walk all subfolders (finds <cell>\\FC\\*.shp).
    recurse=False -> only the top level of *folder*.
    """
    if recurse:
        for root, _dirs, files in os.walk(folder):
            for fn in sorted(files):
                if fn.lower().endswith(".shp"):
                    yield os.path.join(root, fn)
    else:
        try:
            entries = sorted(os.listdir(folder))
        except Exception:
            entries = []
        for fn in entries:
            full = os.path.join(folder, fn)
            if fn.lower().endswith(".shp") and os.path.isfile(full):
                yield full


def _sr_unknown(path):
    """True when *path* has no usable spatial reference (e.g. missing .prj)."""
    try:
        sr = getattr(arcpy.Describe(path), "spatialReference", None)
        name = getattr(sr, "name", "") or ""
        return (sr is None) or (name == "") or (name.lower() == "unknown")
    except Exception:
        return False


def _try_create_group_layer(active_map, group_name):
    """Create an empty group layer via a temp .lyrx. Returns Layer or None."""
    try:
        doc = {
            "type": "CIMLayerDocument",
            "version": "3.0.0",
            "build": "36057",
            "layers": ["layers/0.json"],
            "layerDefinitions": [{
                "type": "CIMGroupLayer",
                "name": group_name,
                "uRI": "layers/0",
                "visible": True,
                "showLegends": True,
                "transparency": 0,
                "groupExpanded": True,
                "layers": []
            }],
            "binaryReferences": [],
            "layerElevationSurfaces": []
        }
        tmp = os.path.join(tempfile.gettempdir(), f"{group_name}_grp.lyrx")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f)
        lf = arcpy.mp.LayerFile(tmp)
        active_map.addLayer(lf)
        hits = [l for l in active_map.listLayers(group_name) if l.isGroupLayer]
        return hits[0] if hits else None
    except Exception:
        return None


# ── Tool class ─────────────────────────────────────────────────────────────────

class CCMStep0MGCPTool:
    """
    ArcGIS Python Toolbox tool — Step 0: Load MGCP Data.

    Imports MGCP feature classes from GeoPackages, File GDBs, or Shapefile
    folders into a target File GDB.  Matching FC names across multiple cells
    are appended into single consolidated layers.  Layers are optionally added
    to the active ArcGIS Pro map.

    Run this tool BEFORE Step 1 (Project Setup & Pre-process) to ensure all
    terrain data is in a single GDB that Step 1 can reference.
    """

    def __init__(self):
        self.label = "Step 0.  Load MGCP Data"
        self.description = (
            "Batch-imports MGCP data (GeoPackage, File GDB, or Shapefile folders) "
            "into a target File Geodatabase, merging matching feature-class names "
            "across multiple cells. Run this BEFORE Step 1 to consolidate all "
            "terrain source data into a single GDB."
        )
        self.canRunInBackground = False

    # ── Parameters ─────────────────────────────────────────────────────────────

    def getParameterInfo(self):
        params = []

        # 0 — Input GeoPackages
        p0 = arcpy.Parameter(
            displayName="Input MGCP GeoPackages (.gpkg)",
            name="input_gpkg",
            datatype="DEFile",
            parameterType="Optional",
            direction="Input",
            multiValue=True,
        )
        p0.filter.list = ["gpkg"]
        p0.category = "1. Input Data"
        params.append(p0)

        # 1 — Input File GDBs
        p1 = arcpy.Parameter(
            displayName="Input MGCP File Geodatabases (.gdb)",
            name="input_gdb",
            datatype="DEWorkspace",
            parameterType="Optional",
            direction="Input",
            multiValue=True,
        )
        p1.filter.list = ["Local Database"]
        p1.category = "1. Input Data"
        params.append(p1)

        # 2 — Input Shapefile folders
        p2 = arcpy.Parameter(
            displayName="Input Shapefile Folders",
            name="input_shp_folders",
            datatype="DEFolder",
            parameterType="Optional",
            direction="Input",
            multiValue=True,
        )
        p2.category = "1. Input Data"
        params.append(p2)

        # 3 — Recurse subfolders for shapefiles
        p3 = arcpy.Parameter(
            displayName="Search Subfolders for Shapefiles (recursive)",
            name="recurse_shp",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input",
        )
        p3.value = True
        p3.category = "1. Input Data"
        params.append(p3)

        # 4 — Output GDB
        p4 = arcpy.Parameter(
            displayName="Output Geodatabase",
            name="output_gdb",
            datatype="DEWorkspace",
            parameterType="Required",
            direction="Input",
        )
        p4.filter.list = ["Local Database"]
        p4.category = "2. Output"
        params.append(p4)

        # 5 — Auto-create GDB
        p5 = arcpy.Parameter(
            displayName="Create Output GDB If It Does Not Exist",
            name="create_gdb",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input",
        )
        p5.value = True
        p5.category = "2. Output"
        params.append(p5)

        # 6 — Feature class filter (populated dynamically)
        p6 = arcpy.Parameter(
            displayName="Feature Classes to Import  (leave blank = ALL)",
            name="fc_filter",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
            multiValue=True,
        )
        p6.category = "3. Options"
        params.append(p6)

        # 7 — Action when FC already exists
        p7 = arcpy.Parameter(
            displayName="If Feature Class Already Exists in Output GDB",
            name="existing_action",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        p7.filter.type = "ValueList"
        p7.filter.list = [
            "APPEND - add features to existing layer (merge cells)",
            "OVERWRITE - replace existing layer, then merge new cells",
            "SKIP - keep existing, skip import",
        ]
        p7.value = "APPEND - add features to existing layer (merge cells)"
        p7.category = "3. Options"
        params.append(p7)

        # 8 — Add to map
        p8 = arcpy.Parameter(
            displayName="Add Imported Layers to Active Map",
            name="add_to_map",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input",
        )
        p8.value = True
        p8.category = "3. Options"
        params.append(p8)

        # 9 — Group layers
        p9 = arcpy.Parameter(
            displayName="Group Layers by GDB Name in Map",
            name="group_layers",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input",
        )
        p9.value = False
        p9.category = "3. Options"
        params.append(p9)

        # 10 — Output coordinate system (optional)
        p10 = arcpy.Parameter(
            displayName="Output Coordinate System (optional)",
            name="output_sr",
            datatype="GPCoordinateSystem",
            parameterType="Optional",
            direction="Input",
        )
        p10.category = "3. Options"
        params.append(p10)

        # 11 — Derived output
        p11 = arcpy.Parameter(
            displayName="Output Feature Classes",
            name="output_fc",
            datatype="DEFeatureClass",
            parameterType="Derived",
            direction="Output",
            multiValue=True,
        )
        params.append(p11)

        # 12 — Theme filter (v0.50.0) — appended last to preserve indices
        p12 = arcpy.Parameter(
            displayName="Themes to Import  (leave blank = ALL)",
            name="theme_filter",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
            multiValue=True,
        )
        p12.filter.type = "ValueList"
        if _catalog:
            p12.filter.list = [_CCM_ONLY] + list(_catalog.ALL_THEMES)
        else:
            p12.filter.list = [_CCM_ONLY]
        p12.category = "3. Options"
        params.append(p12)

        # 13 — Group map layers by theme (v0.50.0)
        p13 = arcpy.Parameter(
            displayName="Group Layers by Theme in Map  (overrides Group by GDB Name)",
            name="group_by_theme",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input",
        )
        p13.value = True
        p13.category = "3. Options"
        params.append(p13)

        # 14 — Assume WGS84 for Unknown-CRS sources (v0.51.1)
        # MGCP shapefiles are WGS84 by specification; a missing .prj sidecar
        # makes ArcGIS report "Unknown".  The coordinates are unaffected —
        # only the label is missing — so DefineProjection (assign, never
        # reproject) is the correct repair.
        p14 = arcpy.Parameter(
            displayName="Assume WGS84 (EPSG:4326) for Sources With Unknown "
                        "CRS  (MGCP data is WGS84 — repairs missing .prj)",
            name="assume_wgs84",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input",
        )
        p14.value = True
        p14.category = "3. Options"
        params.append(p14)

        # 15 — Data Root folder (v0.52.0) — one-folder auto-fill
        p15 = arcpy.Parameter(
            displayName="Data Root Folder  (optional — scans subfolders and "
                        "auto-fills the empty inputs above)",
            name="data_root",
            datatype="DEFolder",
            parameterType="Optional",
            direction="Input",
        )
        p15.category = "1. Input Data"
        params.append(p15)

        return params

    def isLicensed(self):
        return True

    # ── Dynamic parameter update ───────────────────────────────────────────────

    def _apply_data_root(self, parameters):
        """v0.52.0 — fill empty MGCP inputs from the Data Root folder."""
        if _discovery is None or len(parameters) <= 15:
            return
        root = parameters[15].valueAsText
        if not root:
            return
        if getattr(self, "_root_scanned", None) == root:
            return
        self._root_scanned = root
        res = _discovery.scan(root)
        if res["mgcp_gpkg"] and not parameters[0].values:
            parameters[0].values = res["mgcp_gpkg"]
        if res["mgcp_gdb"] and not parameters[1].values:
            parameters[1].values = res["mgcp_gdb"]
        if res["mgcp_shp_folders"] and not parameters[2].values:
            parameters[2].values = res["mgcp_shp_folders"]

    def updateParameters(self, parameters):
        """Scan inputs and populate the FC filter pick-list."""
        self._apply_data_root(parameters)   # v0.52.0
        gpkg_list = parameters[0].values or []
        gdb_list  = parameters[1].values or []
        shp_list  = parameters[2].values or []
        recurse   = parameters[3].value
        recurse   = True if recurse is None else recurse

        if not (gpkg_list or gdb_list or shp_list):
            return

        # Skip re-scanning when inputs (and recurse flag) are unchanged.
        current_inputs = (recurse,) + tuple(sorted(
            str(x) for x in list(gpkg_list) + list(gdb_list) + list(shp_list)
        ))
        cache = getattr(self, "_scanned_inputs", None)
        if cache == current_inputs:
            return
        self._scanned_inputs = current_inputs

        saved_ws = arcpy.env.workspace
        fc_names = set()

        def _clean(f):
            return f.split(".")[-1] if "." in f else f

        def _scan(ws_path, is_shp=False):
            try:
                if is_shp:
                    for sp in _iter_shapefiles(ws_path, recurse):
                        fc_names.add(os.path.splitext(os.path.basename(sp))[0])
                    return
                arcpy.env.workspace = ws_path
                fc_names.update(_clean(f) for f in (arcpy.ListFeatureClasses() or []))
                for ds in (arcpy.ListDatasets(feature_type="feature") or []):
                    arcpy.env.workspace = os.path.join(ws_path, ds)
                    fc_names.update(_clean(f) for f in (arcpy.ListFeatureClasses() or []))
                arcpy.env.workspace = ws_path
            except Exception:
                pass

        for p in [str(x) for x in gpkg_list]:
            if os.path.exists(p):
                _scan(p)
        for p in [str(x) for x in gdb_list]:
            if os.path.exists(p):
                _scan(p)
        for p in [str(x) for x in shp_list]:
            if os.path.exists(p):
                _scan(p, is_shp=True)

        arcpy.env.workspace = saved_ws

        if fc_names:
            # v0.50.0: show human-readable catalog labels in the pick-list
            # ("AP030 — Road (Transportation)") instead of bare FACC codes.
            if _catalog:
                new_list = sorted(_catalog.label(n) for n in fc_names)
            else:
                new_list = sorted(fc_names)
            if new_list != (parameters[6].filter.list or []):
                prev_sel = parameters[6].values or []
                parameters[6].filter.list = new_list
                # Preserve selections across re-scans; accept either the
                # labelled form or a bare FC name from an older session.
                if _catalog:
                    by_name = {_catalog.name_from_label(v): v for v in new_list}
                    keep = []
                    for s in (str(x) for x in prev_sel):
                        if s in new_list:
                            keep.append(s)
                        elif _catalog.name_from_label(s) in by_name:
                            keep.append(by_name[_catalog.name_from_label(s)])
                else:
                    keep = [v for v in (str(s) for s in prev_sel) if v in new_list]
                if keep:
                    parameters[6].values = keep

    # ── Validation messages ────────────────────────────────────────────────────

    def updateMessages(self, parameters):
        """Validation messages for the tool dialog."""
        gpkg_list = parameters[0].values
        gdb_list  = parameters[1].values
        shp_list  = parameters[2].values

        if not (gpkg_list or gdb_list or shp_list):
            parameters[0].setErrorMessage(
                "At least one input source is required.\n\n"
                "Supported formats:\n"
                "  • GeoPackage (.gpkg)  — single file, add to 'Input MGCP GeoPackages'\n"
                "  • File Geodatabase (.gdb)  — folder ending in .gdb, add to 'Input MGCP File "
                "Geodatabases'\n"
                "  • Shapefile folder  — browse to the folder that contains .shp files, add to "
                "'Input Shapefile Folders' (enable 'Search Subfolders' if shapefiles are nested "
                "inside cell sub-folders)\n\n"
                "You may provide any combination of the three types."
            )

        # v0.51.1 — pre-run detection: shapefiles without a .prj sidecar show
        # up as "Unknown" CRS and trigger SR-mismatch warnings at import time.
        if shp_list:
            recurse = parameters[3].value
            recurse = True if recurse is None else recurse
            _no_prj = []
            try:
                for _fold in (str(x) for x in shp_list):
                    if not os.path.isdir(_fold):
                        continue
                    for _sp in _iter_shapefiles(_fold, recurse):
                        if not os.path.isfile(os.path.splitext(_sp)[0] + ".prj"):
                            _no_prj.append(os.path.basename(_sp))
                        if len(_no_prj) > 25:
                            break
                    if len(_no_prj) > 25:
                        break
            except Exception:
                _no_prj = []
            if _no_prj:
                _shown = ", ".join(_no_prj[:8])
                _more  = "" if len(_no_prj) <= 8 else f" (+{len(_no_prj) - 8} more)"
                _fix   = ("They will be assigned WGS84 automatically after import."
                          if (parameters[14].value if len(parameters) > 14 else True)
                          else "Enable 'Assume WGS84' or add .prj files to repair them.")
                parameters[2].setWarningMessage(
                    f"{len(_no_prj)}{'+' if len(_no_prj) > 25 else ''} shapefile(s) "
                    f"have no .prj file (CRS will read as 'Unknown'): {_shown}{_more}\n"
                    f"MGCP data is WGS84 by specification — only the label is missing. {_fix}"
                )

        out_gdb    = parameters[4].valueAsText
        create_gdb = parameters[5].value
        if out_gdb and not arcpy.Exists(out_gdb):
            if create_gdb:
                parent = os.path.dirname(out_gdb) if out_gdb else ""
                parent_ok = os.path.isdir(parent) if parent else False
                if not parent_ok:
                    parameters[4].setErrorMessage(
                        f"Cannot auto-create GDB — parent folder does not exist: {parent}\n"
                        "Create the parent folder first, then re-enter the GDB path."
                    )
                else:
                    parameters[4].setWarningMessage(
                        f"GDB does not exist yet and will be created automatically:\n"
                        f"  {out_gdb}\n"
                        "The parent folder exists — creation will proceed on Run."
                    )
            else:
                parameters[4].setErrorMessage(
                    f"Geodatabase not found: {out_gdb}\n\n"
                    "Options:\n"
                    "  • Enable 'Create Output GDB If It Does Not Exist' to auto-create it, or\n"
                    "  • Browse to an existing .gdb folder using the folder picker."
                )

        # v0.54.0 — smart CRS warning: recommend UTM now to avoid a separate
        # reprojection pass before Step 1 (Step 1's Analysis Extent blocks on
        # a Geographic CRS — see ccm_step1_setup.py / User Manual Section 3.4).
        if _coords_mod and len(parameters) > 10:
            p_out_sr = parameters[10]
            sr_obj   = p_out_sr.value
            sr_type  = getattr(sr_obj, "type", None) if sr_obj else None
            sr_name  = getattr(sr_obj, "name", None) if sr_obj else None
            if sr_type == "Geographic":
                p_out_sr.setWarningMessage(
                    _coords_mod.geographic_crs_warning(
                        "Output Coordinate System", sr_name)
                )
            elif sr_obj is None:
                p_out_sr.setWarningMessage(
                    "No Output Coordinate System selected — imported data "
                    "will keep its source CRS (Geographic, e.g. WGS84, for "
                    "MGCP data).\n\n"
                    "Step 1 requires the Analysis Extent (and its supporting "
                    "layers) to be in a Projected CRS such as UTM.  Setting "
                    "this parameter now to the UTM zone covering your study "
                    "area avoids a separate Export Features/reprojection "
                    "step before Step 1.  See User Manual Section 3.4."
                )

    # ── Execute ────────────────────────────────────────────────────────────────

    def execute(self, parameters, messages):
        self._apply_data_root(parameters)   # v0.52.0 — scripted invocations
        gpkg_list       = [str(x) for x in (parameters[0].values or [])]
        gdb_list        = [str(x) for x in (parameters[1].values or [])]
        shp_list        = [str(x) for x in (parameters[2].values or [])]
        recurse_shp     = parameters[3].value
        recurse_shp     = True if recurse_shp is None else recurse_shp
        output_gdb      = parameters[4].valueAsText
        create_gdb      = parameters[5].value
        fc_filter       = parameters[6].values
        existing_action = (parameters[7].valueAsText or "").split("-")[0].strip().upper()
        add_to_map      = parameters[8].value
        group_layers    = parameters[9].value
        output_sr       = parameters[10].value  # SpatialReference or None
        theme_filter    = (parameters[12].values
                           if len(parameters) > 12 else None)   # v0.50.0
        group_by_theme  = (bool(parameters[13].value)
                           if len(parameters) > 13 else False)  # v0.50.0
        assume_wgs84    = (bool(parameters[14].value)
                           if len(parameters) > 14 else True)   # v0.51.1

        if fc_filter is not None:
            # Pick-list values may be catalog labels — map back to FC names.
            if _catalog:
                fc_filter = {_catalog.name_from_label(v) for v in fc_filter}
            else:
                fc_filter = {str(v) for v in fc_filter}

        # Expand theme filter into a set of theme strings (None = all themes)
        themes = None
        if theme_filter:
            themes = set()
            for t in (str(v).strip().strip("'\"") for v in theme_filter):
                if t == _CCM_ONLY and _catalog:
                    themes.update(_catalog.CCM_RELEVANT_THEMES)
                elif t:
                    themes.add(t)
            if not themes:
                themes = None
        if themes and not _catalog:
            messages.addWarningMessage(
                "Theme filter ignored — ccm_mgcp_catalog.py not available."
            )
            themes = None

        messages.addMessage(
            f"\n{'='*60}\n"
            f"  Step 0 — Load MGCP Data  ({_MGCP_VERSION})\n"
            f"{'='*60}"
        )

        # Save and restore global env settings
        saved_overwrite = arcpy.env.overwriteOutput
        saved_ws        = arcpy.env.workspace
        saved_out_sr    = arcpy.env.outputCoordinateSystem

        try:
            self._run(
                messages, gpkg_list, gdb_list, shp_list, recurse_shp,
                output_gdb, create_gdb, fc_filter,
                existing_action, add_to_map, group_layers, output_sr,
                parameters, themes=themes, group_by_theme=group_by_theme,
                assume_wgs84=assume_wgs84,
            )
        finally:
            arcpy.env.overwriteOutput        = saved_overwrite
            arcpy.env.workspace              = saved_ws
            arcpy.env.outputCoordinateSystem = saved_out_sr

    # ── Internal run logic ─────────────────────────────────────────────────────

    def _run(self, messages, gpkg_list, gdb_list, shp_list, recurse_shp,
             output_gdb, create_gdb, fc_filter,
             existing_action, add_to_map, group_layers, output_sr, parameters,
             themes=None, group_by_theme=False, assume_wgs84=True):

        # Create output GDB if needed
        if not arcpy.Exists(output_gdb):
            if create_gdb:
                parent = os.path.dirname(output_gdb)
                if not os.path.isdir(parent):
                    messages.addErrorMessage(
                        f"Cannot create GDB — parent folder does not exist: {parent}"
                    )
                    return
                messages.addMessage(f"Creating GDB: {output_gdb}")
                arcpy.management.CreateFileGDB(
                    parent, os.path.basename(output_gdb)
                )
            else:
                messages.addErrorMessage(f"Output GDB not found: {output_gdb}")
                return

        # Apply optional output coordinate system
        if output_sr:
            arcpy.env.outputCoordinateSystem = output_sr
            messages.addMessage(f"Output coordinate system set to: {output_sr.name}")

        # Collect sources
        sources  = []   # (workspace, fc_filename, out_name, source_label)
        seen_sr  = {}   # out_name -> set of source SR names (mismatch detection)

        def _match(name):
            if fc_filter is not None and name not in fc_filter:
                return False
            # v0.50.0: theme filter (catalog-driven)
            if themes is not None and _catalog:
                if _catalog.theme_of(name) not in themes:
                    return False
            return True

        def _out_name(raw):
            base = raw.split(".")[-1] if "." in raw else raw
            try:
                return arcpy.ValidateTableName(base, output_gdb)
            except Exception:
                return base

        def _note_sr(out_name, src_path, label=""):
            if output_sr:
                return
            try:
                d  = arcpy.Describe(src_path)
                sr = getattr(getattr(d, "spatialReference", None), "name", None)
                sr = sr or "Unknown"
                # v0.51.1 — remember which source cells use which SR so the
                # warning can name the offenders instead of just the SR list.
                seen_sr.setdefault(out_name, {}).setdefault(sr, set()).add(
                    label or os.path.basename(str(src_path)))
            except Exception:
                pass

        def collect(ws, label, is_shp=False):
            try:
                if is_shp:
                    for sp in _iter_shapefiles(ws, recurse_shp):
                        d, fn = os.path.split(sp)
                        base  = os.path.splitext(fn)[0]
                        if not _match(base):
                            continue
                        out = _out_name(base)
                        if recurse_shp:
                            rel   = os.path.relpath(sp, ws)
                            parts = rel.split(os.sep)
                            lbl   = parts[0] if len(parts) > 1 else label
                        else:
                            lbl = label
                        sources.append((d, fn, out, lbl))
                        _note_sr(out, sp, lbl)
                    return

                arcpy.env.workspace = ws
                for fc in (arcpy.ListFeatureClasses() or []):
                    name = fc.split(".")[-1] if "." in fc else fc
                    if _match(name):
                        out = _out_name(fc)
                        sources.append((ws, fc, out, label))
                        _note_sr(out, os.path.join(ws, fc), label)
                for ds in (arcpy.ListDatasets(feature_type="feature") or []):
                    ds_path = os.path.join(ws, ds)
                    arcpy.env.workspace = ds_path
                    for fc in (arcpy.ListFeatureClasses() or []):
                        name = fc.split(".")[-1] if "." in fc else fc
                        if _match(name):
                            out = _out_name(fc)
                            sources.append((ds_path, fc, out, label))
                            _note_sr(out, os.path.join(ds_path, fc), label)
                    arcpy.env.workspace = ws
            except Exception as e:
                messages.addWarningMessage(f"Could not scan {label}: {e}")

        for p in gpkg_list:
            messages.addMessage(f"Scanning GeoPackage : {p}")
            collect(p, os.path.basename(p))
        for p in gdb_list:
            messages.addMessage(f"Scanning GDB        : {p}")
            collect(p, os.path.basename(p))
        for p in shp_list:
            mode = "recursive" if recurse_shp else "top-level"
            messages.addMessage(f"Scanning SHP folder ({mode}) : {p}")
            collect(p, os.path.basename(p), is_shp=True)

        if not sources:
            messages.addWarningMessage(
                "No feature classes found. Check inputs and the FC filter. "
                "If shapefiles are in subfolders, enable "
                "'Search Subfolders for Shapefiles'."
            )
            return

        # Warn about coordinate-system mismatches across cells (v0.51.1:
        # name the offending cells; "Unknown" = missing .prj, auto-repairable)
        for out_name, srs in seen_sr.items():
            known = {s for s in srs if s != "Unknown"}
            if len(srs) > 1:
                detail = "; ".join(
                    f"{s}: {', '.join(sorted(cells))}"
                    for s, cells in sorted(srs.items())
                )
                messages.addWarningMessage(
                    f"  [SR MISMATCH] {out_name}: cells use different coordinate "
                    f"systems — {detail}."
                )
                if "Unknown" in srs and assume_wgs84 and len(known) <= 1:
                    messages.addMessage(
                        f"  [SR REPAIR]   {out_name}: 'Unknown' sources have no "
                        ".prj file — MGCP is WGS84 by spec, so the output will "
                        "be assigned WGS84 (label only; coordinates untouched)."
                    )
                elif len(known) > 1:
                    messages.addWarningMessage(
                        f"  [SR MISMATCH] {out_name}: multiple DEFINED systems — "
                        "features will NOT be reprojected unless you set an "
                        "Output Coordinate System."
                    )
            elif srs.keys() == {"Unknown"}:
                messages.addWarningMessage(
                    f"  [NO CRS]      {out_name}: no source has a .prj file. "
                    + ("It will be assigned WGS84 (EPSG:4326) after import."
                       if assume_wgs84 else
                       "Enable 'Assume WGS84' or add .prj files manually.")
                )

        total = len(sources)
        n_src = len(gpkg_list) + len(gdb_list) + len(shp_list)
        messages.addMessage(
            f"\n{'-'*60}\n"
            f"Found {total} FC instance(s) across {n_src} input source(s).\n"
            f"{'-'*60}"
        )

        arcpy.SetProgressor(
            "step",
            f"Importing MGCP data into {os.path.basename(output_gdb)} ...",
            0, total, 1
        )

        imported_names   = []
        seen_names       = set()
        written_this_run = set()   # FCs (re)created during THIS run
        manifest_sources = {}      # out_name -> [source cell labels]  (v0.50.0)

        for i, (ws, fc, out_name, label) in enumerate(sources, start=1):
            arcpy.SetProgressorLabel(f"[{i}/{total}] {out_name}  from  {label}")
            arcpy.SetProgressorPosition(i)

            src_path = os.path.join(ws, fc)
            out_path = os.path.join(output_gdb, out_name)

            try:
                exists = arcpy.Exists(out_path)

                if existing_action == "SKIP" and exists \
                        and out_name not in written_this_run:
                    messages.addMessage(f"  [SKIP]      {out_name}  (already exists)")
                    continue

                # First time we touch this FC in this run.
                if out_name not in written_this_run:
                    if exists and existing_action == "APPEND":
                        messages.addMessage(f"  [APPEND]    {out_name}  <- {label}")
                        arcpy.management.Append(
                            inputs=src_path, target=out_path, schema_type="NO_TEST",
                        )
                    else:
                        # New FC, or OVERWRITE replacing a pre-existing one.
                        tag = ("OVERWRITE" if (exists and existing_action == "OVERWRITE")
                               else "IMPORT")
                        messages.addMessage(f"  [{tag}]    {out_name}  <- {label}")
                        # v0.13 (BUG-4 fix): overwriteOutput stays enabled for the
                        # whole run and is restored once in execute()'s finally
                        # block — no longer force-reset to False mid-run.
                        arcpy.env.overwriteOutput = True
                        arcpy.management.CopyFeatures(src_path, out_path)
                        # v0.51.1 — repair missing .prj: ASSIGN (never
                        # reproject) WGS84, the MGCP specification CRS.
                        if assume_wgs84 and _sr_unknown(src_path):
                            try:
                                arcpy.management.DefineProjection(
                                    out_path, arcpy.SpatialReference(4326)
                                )
                                messages.addMessage(
                                    f"  [SR REPAIR] {out_name}: source had no "
                                    "CRS — assigned WGS84 (EPSG:4326)."
                                )
                            except Exception as _dp_e:
                                messages.addWarningMessage(
                                    f"  [SR REPAIR] {out_name}: could not "
                                    f"assign WGS84: {_dp_e}"
                                )
                    written_this_run.add(out_name)
                else:
                    # Already handled once this run -> merge remaining cells.
                    messages.addMessage(f"  [APPEND]    {out_name}  <- {label}")
                    arcpy.management.Append(
                        inputs=src_path, target=out_path, schema_type="NO_TEST",
                    )
            except Exception as e:
                messages.addWarningMessage(f"  [FAILED]    {out_name}: {e}")
                continue

            if out_name not in seen_names:
                imported_names.append(out_name)
                seen_names.add(out_name)
            manifest_sources.setdefault(out_name, []).append(label)

        arcpy.ResetProgressor()
        messages.addMessage(
            f"\n{'='*60}\n"
            f"Done — {len(imported_names)} unique FC(s) in:\n"
            f"  {output_gdb}\n"
            f"{'='*60}"
        )

        # ── v0.13: classification summary by theme ────────────────────────────
        if _catalog and imported_names:
            by_theme = {}
            for name in imported_names:
                by_theme.setdefault(_catalog.theme_of(name), []).append(name)
            messages.addMessage("Classification by theme:")
            for theme in sorted(by_theme):
                messages.addMessage(
                    f"  {theme:<16} {len(by_theme[theme]):>3} FC(s)")
            ccm_usable = [n for n in imported_names
                          if _catalog.lookup(n).get("ccm_role")]
            if ccm_usable:
                messages.addMessage(
                    "CCM-usable layers detected (feed Step 1 auto-fill): "
                    + ", ".join(sorted(ccm_usable))
                )

        # ── v0.13: write mgcp_manifest.json next to the output GDB ───────────
        # Step 1 reads this manifest to auto-fill Soil / Hydrology / Contours.
        if _catalog and imported_names:
            try:
                features = []
                for name in imported_names:
                    fc_path = os.path.join(output_gdb, name)
                    geometry = None
                    try:
                        geometry = arcpy.Describe(fc_path).shapeType
                    except Exception:
                        pass
                    info = _catalog.lookup(name)
                    feat_count = None
                    sr_name    = None
                    fld_names  = []
                    try:
                        feat_count = int(
                            arcpy.management.GetCount(fc_path)[0])
                    except Exception:
                        pass
                    try:
                        d = arcpy.Describe(fc_path)
                        sr_name = getattr(
                            getattr(d, "spatialReference", None), "name", None)
                    except Exception:
                        pass
                    try:
                        fld_names = [f.name for f in arcpy.ListFields(fc_path)]
                    except Exception:
                        pass
                    features.append({
                        "name"         : name,
                        "path"         : fc_path,
                        "code"         : info.get("code"),
                        "label"        : info.get("name"),
                        "theme"        : info.get("theme"),
                        "ccm_role"     : info.get("ccm_role"),
                        "geometry"     : geometry,
                        "feature_count": feat_count,
                        "spatial_reference": sr_name,
                        "fields"       : fld_names,
                        "sources"      : manifest_sources.get(name, []),
                    })
                manifest = {
                    "ccm_version" : VERSION,
                    "mgcp_loader" : _MGCP_VERSION,
                    "created"     : datetime.datetime.now().isoformat(
                        timespec="seconds"),
                    "output_gdb"  : output_gdb,
                    "features"    : features,
                }
                m_path = _catalog.manifest_path_for_gdb(output_gdb)
                with open(m_path, "w", encoding="utf-8") as fh:
                    json.dump(manifest, fh, indent=2, ensure_ascii=False)
                messages.addMessage(
                    f"Manifest written: {m_path}\n"
                    "  (Step 1 uses this file to auto-fill Soil / Hydrology / "
                    "Contours)"
                )
            except Exception as e:
                messages.addWarningMessage(
                    f"Could not write mgcp_manifest.json: {e}"
                )
        elif imported_names and not _catalog:
            messages.addWarningMessage(
                "mgcp_manifest.json not written — ccm_mgcp_catalog.py not "
                "available."
            )

        # ── Add to active map ─────────────────────────────────────────────────
        if add_to_map and imported_names:
            try:
                aprx       = arcpy.mp.ArcGISProject("CURRENT")
                active_map = aprx.activeMap
                if active_map is None:
                    maps       = aprx.listMaps()
                    active_map = maps[0] if maps else None

                if active_map is None:
                    messages.addWarningMessage(
                        "No open map found — layers not added.")
                else:
                    # v0.13: group by MGCP theme (overrides group-by-GDB-name)
                    theme_groups = {}
                    group_lyr    = None
                    if group_by_theme and _catalog:
                        pass   # theme groups created lazily below
                    elif group_layers:
                        group_name = os.path.splitext(
                            os.path.basename(output_gdb))[0]
                        group_lyr = _try_create_group_layer(
                            active_map, group_name)
                        if group_lyr is None:
                            messages.addWarningMessage(
                                "Group layer could not be created on this "
                                "ArcGIS Pro version. Layers added flat — "
                                "group manually in the Contents pane."
                            )

                    added = 0
                    for fc_name in imported_names:
                        fc_path = os.path.join(output_gdb, fc_name)
                        if not arcpy.Exists(fc_path):
                            continue
                        new_lyr = active_map.addDataFromPath(fc_path)
                        added += 1
                        target_group = group_lyr
                        if group_by_theme and _catalog:
                            try:
                                new_lyr.name = _catalog.label(fc_name)
                            except Exception:
                                pass
                            theme = _catalog.theme_of(fc_name) or "Other"
                            if theme not in theme_groups:
                                theme_groups[theme] = _try_create_group_layer(
                                    active_map, theme)
                            target_group = theme_groups[theme]
                        if target_group is not None and new_lyr is not None:
                            try:
                                # Nest into the group, then drop the flat copy.
                                active_map.addLayerToGroup(target_group, new_lyr)
                                active_map.removeLayer(new_lyr)
                            except Exception:
                                pass   # leave it flat if reparenting unsupported

                    messages.addMessage(
                        f"Added {added} layer(s) to map: '{active_map.name}'"
                    )
            except Exception as e:
                messages.addWarningMessage(f"Could not add layers to map: {e}")

        # ── Derived output ────────────────────────────────────────────────────
        parameters[11].values = [
            os.path.join(output_gdb, n) for n in imported_names
        ]

    def postExecute(self, parameters):
        return

# <<< END OF FILE >>>
