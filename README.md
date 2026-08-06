# CCM Tool — v0.54.1

Cross-Country Mobility (CCM) assessment toolbox for ArcGIS Pro. Estimates where a
given vehicle can travel across terrain by combining slope, soil strength,
vegetation, hydrology and weather into a per-area mobility/speed surface.

---

## Copyright

SPDX-License-Identifier: GPL-2.0-or-later

Copyright (c) 2026 Eui Soo SON

---

## Workflow (run in order in ArcGIS Pro)

0. **Step 0 — Load MGCP Data** (`ccm_step0_mgcp.py`) *(optional)*  
   Batch-imports MGCP data (GeoPackage / File GDB / Shapefile cells) into one
   geodatabase, merging matching feature classes across cells, and writes
   `mgcp_manifest.json` so Step 1 can auto-fill its Soil / Hydrology / Contours inputs.
1. **Step 1 — Project Setup & Pre-process** (`ccm_step1_setup.py`)  
   Enter all raw inputs once. Pre-processes soil and vegetation into CCM-ready
   polygon layers and writes `ccm_project.json` so later steps auto-populate.
2. **Step 2 — Generate Mobility Map** (`ccm_step2_mobility.py`)  
   Runs the multi-criteria mobility model for a chosen vehicle and produces the
   speed-surface feature class (`SpeedKMH`, `Mobility`, and the `F1..F5`/`F_hydro`
   factor fields). This output is the input for every Step 3 analysis.
3. **Step 3 — Advanced Analysis** (`ccm_step3_advanced.py`)  
   Reason map, reachability (isochrone), vehicle comparison, obstacle detection,
   and fastest-route (waypoint) tools, all driven by the Step 2 speed surface.
4. **Step 4 — Compare Two Vehicles** (`ccm_vehicle_compare.py`) *(optional)*  
   Standalone A/B comparison of any two Speed Surface feature classes — the
   same engine as Step 3's Vehicle Comparison, without needing a project
   folder. Both inputs must share the same Projected CRS.

All spatial inputs across every step must use one consistent Projected CRS
(e.g. UTM) — see `CCM_Tool_by_Son_v0.54.7_User_Manual.docx` Section 3.4 for why,
and Section 9.1 for the CRS-related warnings/errors each step can show.

---

## Main Components

| File | Role |
|---|---|
| `CCM_Tool_by_Son_v0.54.7.pyt` | ArcGIS Python Toolbox entry point — registers Steps 0-4 (Step 4 = the standalone Vehicle Compare tool); shows a stub error tool if a module fails to import. |
| `ccm_step0_mgcp.py` | Step 0 — MGCP batch loader + `mgcp_manifest.json` writer. |
| `ccm_mgcp_catalog.py` | FACC/DIGEST feature-code catalog (names, themes, CCM roles). |
| `ccm_step1_setup.py` | Step 1 — project setup, soil/veg pre-processing, DEM→slope regions, `ccm_project.json`. |
| `ccm_step2_mobility.py` | Core mobility (speed-surface) engine. |
| `ccm_soil_preprocess.py` / `ccm_soil_validator.py` | Soil source ingestion (DSS, SLC, SSURGO, HWSD, SoilGrids, MGCP, TDS, GGDM, generic) into USCS codes. |
| `ccm_veg_preprocess.py` | Vegetation rasters into VTI / tree spacing / stem diameter. |
| `ccm_reason_map.py` | Step 3 — factor breakdown reason map. |
| `ccm_isochrone.py` | Step 3 — travel-time reachability rings. |
| `ccm_vehicle_compare.py` | Step 3 — two-vehicle A/B speed-surface comparison. |
| `ccm_obstacle_detect.py` | Step 3 — slope-break / water / gap micro-obstacle scan. |
| `ccm_waypoints.py` | Step 3 — time-optimal route between two points. |
| `ccm_data_discovery.py` | One-folder Data Root scanner — keyword + content detection, accuracy-ranked auto-fill (v0.52). |
| `ccm_map_display.py` | Shared map display module — one visual language for all CCM outputs (v0.51). |
| `ccm_weather.py` | METAR / Open-Meteo rainfall → RCI adjustment. |
| `ccm_coords.py` | MGRS / DD / DMS / DDM / UTM coordinate conversion + shared CRS/projection smart-warning helpers (v0.54). |
| `ccm_project_config.py` | `ccm_project.json` read/write + `run_tool` named-parameter invocation. |
| `build.py` | Integrity check (syntax, EOF marker, undefined names) + release zip packager. |
| `tests/` | Arcpy-free pytest suite (160 tests) + licensed-install smoke test. |
| `Vehicle_Data/Vehicles_Can.csv` | Vehicle definitions — 64 platforms (Canada / US / Russia) with VCI, gradients, width, MMP + nation/source/note columns (v0.53). |
| `Symbology/` | Mobility layer symbology (.lyrx). |

See `CCM_Tool_by_Son_v0.54.7_User_Manual.docx` for the full manual —
including Section 3.4, a beginner-focused explainer of why every
CCM input must use a Projected CRS (e.g. UTM) — and `CHANGELOG_v0.54.md`
for release notes (v0.54.7 fixes a smoke-test-only bug — `tests/arcpy_smoke_test_step3.py` reported which isochrone code path ran by inspecting `msgs.warnings`, but `ccm_isochrone.py` logs via the global `arcpy.AddWarning()`, so the check always silently reported the wrong path; replaced with a reliable `"gridcode"` field check; no production-code behaviour changed; v0.54.6 is a follow-up to v0.54.5's ERROR 160333 fix — a real ArcGIS Pro re-run showed that mitigation fires but doesn't resolve the error, so Reclassify now runs on the in-memory raster first, and the Reachability Map/Isochrone tool falls back to its vector method if the raster path fails outright, so an isochrone is always produced; v0.54.5 fixes ERROR 160333 — Reclassify could fail immediately after DistanceAccumulation in the Reachability Map/Isochrone tool — plus a vehicle-name bug in the Step 1 smoke test; v0.54.4 fixes ERROR 000384 — Step 2's Union call failed outright below an Advanced licence; v0.54.3 verified the v0.54.2 symbology fixes against real ArcGIS Pro and fixed a transparency regression; v0.54.1 is a rebrand + relicense release — "MCE CCM
Tool" is renamed "CCM Tool by Son" throughout, and the project is
relicensed under SPDX-License-Identifier: GPL-2.0-or-later; v0.54.0 adds
smart CRS/projection warnings to Steps 0, 1, 3 and 4, and expands the
manual with per-step data/projection guidance; v0.53.0 expands the vehicle
database to 64 Canadian / US / Russian platforms; v0.53.1 is a
repository-cleanup release — removed the superseded standalone MGCP Data
Loader toolbox, whose logic is integrated into Step 0, plus orphaned
sidecars and old manuals; v0.53.2 restores the truncated
`CCMWaypointTool.execute()` so Step 3 waypoint routing actually runs; v0.53.3
is a lint-cleanup and copyright-update release).
