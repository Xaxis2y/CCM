# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# ccm_project_config.py
# CCM Project Configuration — save / load project JSON so data only needs
# to be entered once and all subsequent steps auto-populate.
#
# Config file: <output_folder>/ccm_project.json
#
# VERSION = "0.57"

import json
import os
import datetime

VERSION = "0.57"  # v0.57 -- version bump only: added QUICK_START.html and CCM_anaconda.bat (Anaconda Prompt environment setup script); no code/logic changes. See CHANGELOG_v0.57.md.
CONFIG_FILENAME   = "ccm_project.json"

# ── Keys stored in the config ─────────────────────────────────────────────────
# (all paths are absolute strings; None if not set)
_DEFAULTS = {
    # Core spatial inputs
    "extent_fc"         : None,   # Analysis Extent polygon FC
    "dem_path"          : None,   # Raw DEM raster
    "slope_fc"          : None,   # Derived/provided slope-regions FC
    "slope_field"       : None,   # Name of the slope-value field on slope_fc
    "slope_units"       : "percent",  # "percent" | "degrees" — units of slope_field
    "contours_fc"       : None,   # Contour lines FC
    # Data Intelligence hand-off (Step 0b)
    "data_root"        : None,
    "data_catalog_json": None,
    # Pre-processed layers (outputs of Steps 0 / 0b)
    "soil_fc"           : None,   # Pre-processed soil FC
    "veg_fc"            : None,   # Pre-processed vegetation FC
    # Hydrology (list of FC paths)
    "hydro_fcs"         : [],
    # Vehicle data
    "vehicle_csv"       : None,
    # Analysis settings
    "moisture_default"  : "moist",
    # Output locations
    "project_folder"    : None,
    "project_gdb"       : None,
    # Supplemental derived layers (v0.46)
    "geomorphon_ras"    : None,   # Geomorphon Landforms raster (Pro 3.5+)
    # Mobility map results (filled after Step 2)
    "mobility_map_fc"   : None,
    "last_vehicles"     : [],
    "last_run_output"   : None,
    # Metadata
    "ccm_version"       : VERSION,
    "created"           : None,
    "last_updated"      : None,
}


# =============================================================================
# SAVE / LOAD
# =============================================================================

def save_config(project_folder, **fields):
    """
    Save (or update) ccm_project.json in project_folder.

    Pass keyword arguments matching keys in _DEFAULTS to set values.
    Existing keys not in fields are preserved.

    Returns the full path to the saved config file.
    """
    config_path = os.path.join(str(project_folder), CONFIG_FILENAME)

    # Load existing config if present (preserve fields not being updated)
    existing = {}
    if os.path.isfile(config_path):
        try:
            with open(config_path, encoding="utf-8") as fh:
                existing = json.load(fh)
        except Exception:
            existing = {}

    # Merge: start from defaults, overlay existing, then apply new fields
    merged = dict(_DEFAULTS)
    merged.update(existing)
    merged.update(fields)

    # Always stamp version and timestamps
    merged["ccm_version"]  = VERSION
    merged["last_updated"] = datetime.datetime.now().isoformat(timespec="seconds")
    if not merged.get("created"):
        merged["created"] = merged["last_updated"]

    # Ensure project_folder is recorded
    merged["project_folder"] = str(project_folder)

    with open(config_path, "w", encoding="utf-8") as fh:
        json.dump(merged, fh, indent=2, ensure_ascii=False)

    return config_path


def load_config(config_path_or_folder):
    """
    Load ccm_project.json from a file path or folder.

    Returns a dict (possibly empty if not found).
    """
    path = str(config_path_or_folder)
    if os.path.isdir(path):
        path = os.path.join(path, CONFIG_FILENAME)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def find_config(start_path):
    """
    Search for ccm_project.json starting from start_path.
    Checks the path itself (if folder) then walks up 2 levels.
    Returns the config dict or {}.
    """
    candidates = [start_path]
    # Walk up parent dirs
    for _ in range(2):
        start_path = os.path.dirname(start_path)
        candidates.append(start_path)

    for p in candidates:
        cfg = load_config(p)
        if cfg:
            return cfg
    return {}


# v0.57 post-review "5.5": find_latest_speed_surface(output_folder, ...) used
# to live here. It had zero callers anywhere in the codebase (grep-verified)
# and mutated arcpy.env.workspace without restoring it. ccm_step3_advanced.py
# already has its own, purpose-built equivalent -- _list_speed_surfaces(project_gdb)
# -- which correctly saves/restores arcpy.env.workspace via try/finally and
# scans the actual project_gdb (from ccm_project.json's "mobility_map_fc" /
# project_gdb) rather than every *.gdb in a folder. Rather than maintain two
# overlapping implementations (one with the workspace bug), the dead one was
# removed; Step 3's auto-fill already covers this need. See CHANGELOG_v0.57.md.


# =============================================================================
# TOOL INVOCATION HELPER
# =============================================================================

def by_name(parameters):
    """
    {parameter_name: parameter} view over an existing .pyt parameter list.

    v0.57 post-review "M-3": run_tool() (below) already solved fragile
    positional access for calling a SEPARATE tool's getParameterInfo() by
    name. This is the companion for the more common case — a tool's own
    execute()/updateParameters()/updateMessages(), which is handed the same
    *parameters* list it declared in getParameterInfo() and today reads it
    positionally (parameters[18], parameters[26], ...). Every one of those
    positions is currently correct, but three separate comments in
    ccm_step1_setup.py's own getParameterInfo() say "appended last to
    preserve existing indices" — i.e. new parameters are placed at the end
    of the dialog, not where they logically belong, purely to avoid
    renumbering existing positional reads. Migrating a method to
    `P = by_name(parameters); P["soil_preproc_fc"].valueAsText` removes that
    constraint for that method, one method at a time (see the callers of
    this function for examples migrated so far).

    Raises ValueError on a duplicate parameter name (a getParameterInfo()
    bug that positional indexing would silently miss and this should not).
    """
    out = {}
    for p in parameters:
        if p.name in out:
            raise ValueError(f"duplicate parameter name in parameter list: {p.name!r}")
        out[p.name] = p
    return out


def run_tool(tool, messages=None, **kwargs):
    """
    Invoke an ArcGIS Python-toolbox tool programmatically by *parameter name*
    instead of by fragile positional index.

    This replaces the old pattern of hand-building a list of fake parameter
    shims in a fixed order (which broke silently whenever a tool's parameter
    list was reordered).  Callers now pass keyword arguments whose keys match
    the ``name`` of each arcpy.Parameter returned by ``tool.getParameterInfo()``.

    Example
    -------
        run_tool(CCMSoilPreprocessTool(), messages,
                 source_type=src, soil_fc=raw, extent_fc=ext, output_fc=out)

    Unknown keyword names raise KeyError so typos surface immediately rather
    than being silently dropped.  Multi-value parameters accept a Python list.
    """
    params = tool.getParameterInfo()
    by_name = {p.name: p for p in params}

    unknown = [k for k in kwargs if k not in by_name]
    if unknown:
        raise KeyError(
            f"{type(tool).__name__}.run_tool: unknown parameter(s) "
            f"{unknown}; valid names: {sorted(by_name)}"
        )

    for name, value in kwargs.items():
        p = by_name[name]
        # Multi-value parameters: accept a list and also populate .values
        if isinstance(value, (list, tuple)) and getattr(p, "multiValue", False):
            p.values = list(value)
            p.value = ";".join(str(v) for v in value)
        else:
            p.value = value

    return tool.execute(params, messages)

# <<< END OF FILE >>>
