# CHANGELOG — v0.52.0 (2026-07-03)

## One-folder Data Root — auto-detect and auto-fill (new)

Put every raw dataset under ONE parent folder and let the tool find it:

    MyProject_Data\
        MGCP\...          Soil\...        DEM\...       Contours\...
        Vegetation\...    Hydro\...       Vehicle\...   Extent\...

### New module — `ccm_data_discovery.py`

Two-pass classification: subfolder-name keywords (MGCP / Soil / DEM /
Elevation / Contours / Veg / Hydro / Vehicle / Extent-AOI…) first, then
content sniffing for unnamed folders — FACC-coded shapefile trees classify
as MGCP, a CSV with `vci_1`/`vci_50` headers as the vehicle file, SLC
`cmp*.dbf` tables / SSURGO tabular text / HWSD `.mdb` / SoilGrids property
rasters as their soil source types. Pure-python scan (unit-testable
without arcpy).

### Accuracy ranking when duplicates exist

When several datasets cover the same role, the best is chosen and the
alternatives are reported so the analyst can override:

- **Soil**: SSURGO (US ~1:24k) > SLC/DSS (Canada) > SoilGrids (250 m)
  > HWSD (1 km) > generic FC
- **DEM**: LiDAR/HRDEM name hints > CDEM/SRTM/ASTER hints > largest file
- **Vegetation**: Canada Bio (LAI/fCOVER) > GEDI canopy > WorldCover/NLCD
  > generic; ALL tiles of the winning product family load together
- **Hydrology**: all detected layers load (multi-value, de-duplicated)

### Tool wiring

- **Step 0** — new parameter 15 *Data Root Folder*: auto-fills empty
  GeoPackage / GDB / Shapefile-folder inputs (dialog and scripted runs).
- **Step 1** — new parameter 26 *Data Root Folder*: auto-fills empty
  Extent, DEM, Contours, Vegetation rasters, Hydrology, Vehicle CSV, and
  the full soil source block (type + per-source paths). Runs in the dialog
  and again at execute time; the geoprocessing log prints one line per
  detected role incl. chosen source and alternatives.
- Fill-only-if-empty everywhere — explicit user choices are never
  overwritten. Steps 2/3 need no change (they read `ccm_project.json`).

## Tests

10 new unit tests on a synthetic data tree (keyword + content
classification, accuracy rankings, alternatives report). Suite:
**148 passed / 3 skipped**, arcpy-free.

## Version

- All module `VERSION` constants → `0.52.0`; toolbox renamed
  `CCM_Tool_by_Son_v0.51.1.pyt` → `CCM_Tool_by_Son_v0.52.0.pyt` (sidecars, `build.py`
  incl. `ccm_data_discovery.py` in PY_FILES, README, PROJECT_STATUS,
  TASKS, tests, user manual updated).

# <<< END OF FILE >>>
