# CCM Tool v0.60.10 Integration Guide

This is the combined release copy of the complete Steps 0-4 toolbox and the
Step 0b Data Intelligence/scoring modules, built on the v0.60.0 single-root
project architecture. The original `v0.58.1` and `v0.58.1a` folders are not
modified.

## Toolbox registration

`CCM_Tool_v0.60.10.pyt` imports and registers six tools:

1. Step 0 — Load MGCP Data
2. Step 0b — Data Intelligence Scan
3. Step 1 — Project Setup & Pre-process
4. Step 2 — Generate Mobility Map
5. Step 3 — Advanced Analysis
6. Step 4 — Compare Two Vehicles

The toolbox uses guarded imports so ArcGIS displays an actionable unavailable
tool if a module cannot load. The v0.60.10 Step 0b import is
`ccm_step0b_intelligence.CCMDataIntelligenceTool`; that class calls the
integrated workflow in `ccm_step0b_integration.py`.

## Single-root project parameter

Every tool above shares one `project_root` parameter (labeled "Project Root
Folder" in the dialog) instead of the separate Output Geodatabase / Data Root
Folder / Project Folder / Project Output Folder parameters earlier releases
used. `ccm_project_config.py` is the one canonical reader/writer of
`ccm_project.json`:

- `save_config(project_root, **fields)` merges the given fields into the
  existing config (read-merge-write; it never drops keys a previous step
  wrote), and always keeps `project_root` in sync with the folder actually
  used.
- `load_config(project_root)` reads it back.
- `run_tool(tool, messages=None, **kwargs)` is the test-harness helper that
  sets `arcpy.Parameter` values by matching keyword names against each
  parameter's `.name`, then calls `execute()` — the same by-name convention
  every `arcpy_smoke_test_*.py` script uses.

Step 0 and Step 0b both call `_apply_project_root_layout()`-equivalent logic
at dialog-validation time (inside `updateParameters()`), not only at
`execute()` — so `01_Input_Data/`, `02_Scan_Index/`, and `ccm_project.json`
all exist as soon as a valid Project Root Folder is set, even before the
analyst clicks Run. Step 1 reuses the project geodatabase Step 0 already
created (`03_Project.gdb`) instead of erroring or recreating it, so either
step can run first.

Two standalone, non-toolbox helpers also read/write this same layout:
`ccm_project_init.py` (a Tk GUI that creates the layout ahead of time, no
arcpy required) and the Data Scanner GUI (`CCM_Data_Scanner_GUI.py`), which
scans `<project_root>/01_Input_Data` when populated, falling back to the
root itself otherwise.

## Step 0b flow

The integrated flow is:

1. Build the factual catalog using `ccm_data_catalog.py`.
2. Normalize the factual role records into the scoring-engine contract.
3. Calculate quality, fitness, and confidence outputs.
4. Write the current readiness status (`Not Yet Run` until Step 1).
5. Generate role recommendations.
6. Write factual reports, scoring JSON files, recommendation JSON/HTML, and
   additive project configuration links, all under
   `<project_root>/02_Scan_Index`.

The factual `run_scan()` function remains available for compatibility and can
be selected with the CLI `--factual-only` option. The default CLI and ArcGIS
toolbox entry point use the integrated workflow.

## Project hand-off

Step 0 writes, at minimum: `project_root`, `data_root`, `scan_index_dir`, and
`project_gdb`. Step 0b preserves every existing `ccm_project.json` key and
adds:

```json
{
  "project_root": "D:/GIS/Project",
  "data_root": "D:/GIS/Project/01_Input_Data",
  "scan_index_dir": "D:/GIS/Project/02_Scan_Index",
  "data_catalog_json": "D:/GIS/Project/02_Scan_Index/ccm_data_catalog.json",
  "data_quality_scores": "D:/GIS/Project/02_Scan_Index/ccm_quality_scores.json",
  "data_fitness_scores": "D:/GIS/Project/02_Scan_Index/ccm_fitness_scores.json",
  "data_confidence_scores": "D:/GIS/Project/02_Scan_Index/ccm_confidence_scores.json",
  "data_readiness_scores": "D:/GIS/Project/02_Scan_Index/ccm_readiness_scores.json",
  "data_recommendations": "D:/GIS/Project/02_Scan_Index/ccm_recommendations.json",
  "data_recommendations_report": "D:/GIS/Project/02_Scan_Index/CCM_Recommendations_Report.html",
  "ccm_version": "0.60.10"
}
```

Step 1 displays the recommendation file at startup. It does not automatically
select, replace, or mutate an input. The recommendation layer **must not** be
treated as an automatic substitute for explicit Step 1 parameters. Explicit
Step 1 parameters remain the source of truth, and recommendation overrides
remain reviewable.

Step 2's Vehicle dropdown reads `vehicle_csv` from this same config. If a
Project Root Folder holds only a Step 0b scan (no Step 1 `project_gdb` /
`vehicle_csv` yet), Step 2 now falls back to the bundled vehicle list with a
warning rather than showing an empty dropdown, and an explicit error names
the mismatch ("this folder holds a Step 0b scan, not a Step 1 project")
instead of leaving every config-driven field silently blank.

## Runtime modes

- **ArcGIS Pro toolbox mode:** ArcPy can read richer metadata and enumerate
  file-geodatabase layers.
- **Anaconda CLI mode:** built-in readers and optional GDAL/OGR provide a
  useful offline scan without ArcGIS Pro.

The environment setup is `CCM_anaconda.bat`. Run it from **Anaconda Prompt**
and use the dedicated `ccm_tool` environment; do not install project
dependencies into `base`.

## Verification checklist

From Anaconda Prompt:

```bat
CCM_anaconda.bat
RUN_TESTS.bat
```

Then, with ArcGIS Pro open and signed in:

```bat
RUN_ARCGIS_SMOKE_TEST.bat
```

The portable gate checks syntax, version synchronization, calibration files,
legacy regressions, factual inventory, scoring/recommendation outputs, the
single-root rewrite's pure-Python surface (`test_single_root_pure_python.py`),
and release packaging. The licensed gate additionally checks toolbox
parameter loading, dialog-time behavior (`updateParameters()` /
`updateMessages()` — auto-filled defaults, the Vehicle dropdown, live
validation messages) via `arcpy_smoke_test_v060_single_root.py`, and the
integrated Step 0b path through ArcPy. `MANUAL_TEST_CHECKLIST.md` covers the
same licensed ground as a human walkthrough inside ArcGIS Pro's own dialogs.

## Scope boundary

Recommendations are evidence-based guidance for analyst review. They do not
constitute official certification, do not alter source data, and do not
silently replace Step 1 inputs. ArcPy/GDAL-dependent metadata should be
verified on the user's licensed environment before production modeling.

# <<< END OF FILE >>>
