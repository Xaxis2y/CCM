# CCM Tool v0.60.10

Integrated Cross-Country Mobility (CCM) toolbox for ArcGIS Pro.

This release combines the complete Steps 0-4 toolbox with the Step 0b Data
Intelligence factual inventory and its Quality, Fitness, Confidence,
Readiness, and reviewable recommendation outputs, on top of a **single-root
project architecture**: every step now points at ONE project folder instead
of a different folder parameter per step.

## Single-root project architecture (v0.60.0)

Every step (Step 0, 0b, 1, 2, 3) takes one **Project Root Folder**
(`project_root`) parameter instead of a separate folder per step. Point a
step at the same project folder and it finds — or creates — everything it
needs there:

```
<Project Root>/
    ccm_project.json     # canonical config, read/written by every step
    01_Input_Data/        # put source GIS data here (Step 0 / Step 0b input)
    02_Scan_Index/         # Step 0b Data Intelligence Scan output
    03_Project.gdb         # the project geodatabase
```

Step 0 and Step 0b both auto-create this layout and write `ccm_project.json`
as soon as a valid root is set — even before you click Run, so a folder
picked in Step 0 or Step 0b is immediately usable by every later step. Step 1
reuses the geodatabase Step 0 already created instead of erroring or
recreating it, so either step can now run first. Step 2 and Step 3 read the
same `project_root` back through `ccm_project_config.py`'s canonical
`load_config()` / `save_config()`, the one config reader/writer every step
now shares. This closes the original bug report: Step 2's Vehicle dropdown
used to come up empty whenever its Project Folder pointed at a Step 0b scan
folder instead of a Step 1 project — it now falls back to the bundled
vehicle list with a clear warning, and a genuine Step-0b-only folder gets an
explicit error naming the mismatch instead of a silently empty list.

Two standalone helpers make the single-root layout easier to set up and
inspect outside a full toolbox run:

- **Project Initializer** (`ccm_project_init.py`, or the frozen `.exe` from
  `build_project_init_exe.py`) — a small Tk GUI that lets you pick one
  folder and creates the whole `01_Input_Data` / `02_Scan_Index` /
  `ccm_project.json` layout in it, with no arcpy or ArcGIS Pro required.
  Run it before Step 0 if you want the folder ready in advance, or skip it —
  Step 0 and Step 0b create the same layout automatically the first time
  either one runs against a folder.
- **Data Scanner GUI** (`CCM_Data_Scanner_GUI.py`, launched via
  `CCM_Data_Scanner.bat`) — the standalone, ArcGIS-Pro-independent front end
  for the Step 0b Data Intelligence scan, now single-root aware: point it at
  a project root and it scans `<root>/01_Input_Data` when that layout
  already has data in it, falling back to scanning the root directly
  otherwise, so it still works as the very first tool run against a folder
  with no CCM structure yet.

## What Data Intelligence (Step 0b) adds

Step 0b scans one complete data-root folder and:

- identifies likely DEM, soil, vegetation, hydrology, contour, MGCP, vehicle,
  moisture, and extent datasets;
- reads available raster, vector, table, CRS, schema, container, duplicate,
  and coverage metadata;
- calculates quality scores across the available evidence;
- evaluates dataset fitness for CCM roles and calculates confidence;
- writes a readiness status that remains `Not Yet Run` until Step 1 outputs are
  available; and
- creates reviewable role recommendations without modifying source data or
  silently replacing a user's Step 1 selection.

Data Intelligence is registered as its own toolbox tool (Step 0b), separate
from Step 1 — it never runs automatically as part of Step 1, and Step 1's
explicit parameters always remain authoritative over any recommendation.

## Workflow

1. **Step 0 — Load MGCP Data** (optional): consolidate MGCP source cells.
2. **Step 0b — Data Intelligence Scan**: scan the complete data root and
   review the factual and recommendation reports.
3. **Step 1 — Project Setup & Pre-process**: review recommendations and select
   the actual inputs explicitly.
4. **Step 2 — Generate Mobility Map**: compute vehicle speed surfaces.
5. **Step 3 — Advanced Analysis**: reason maps, reachability, comparison,
   obstacles, and waypoint routing.
6. **Step 4 — Compare Two Vehicles** (optional): compare existing surfaces.

Every step above is pointed at the same Project Root Folder.

## Quick start in Anaconda Prompt

Run the environment setup from **Anaconda Prompt**, not the base environment:

```bat
CCM_anaconda.bat
RUN_TESTS.bat
```

The setup creates or refreshes the dedicated `ccm_tool` environment and
installs pytest, pyflakes, and PyInstaller there. Do not install these
packages into `base`; dependency conflicts in the base environment can make
the validation result unreliable.

For optional GDAL/OGR support:

```bat
CCM_anaconda.bat ccm_tool_gdal --with-gdal
set CCM_ENV_NAME=ccm_tool_gdal
RUN_TESTS.bat
```

For a real data scan:

```bat
RUN_DATA_SCAN.bat "D:\GIS\Project" "D:\GIS\Project\01_Input_Data\Extent\AOI.shp"
```

(pass the Project Root Folder; if it does not yet contain `01_Input_Data`,
the scan falls back to scanning the root directly.)

ArcPy is supplied by a licensed ArcGIS Pro installation. After opening and
signing in to ArcGIS Pro, run the licensed smoke tests from Anaconda Prompt:

```bat
RUN_ARCGIS_SMOKE_TEST.bat
```

This runs all seven licensed smoke tests — Steps 0-3, the single-root
dialog-behavior test (Vehicle dropdown scenarios, GDB-resolution fallback),
the factual Step 0b test, and the integrated Step 0b test — and reports a
combined PASS/FAIL with per-test logs under `verification_logs\`.

## Toolbox registration

In ArcGIS Pro, add `CCM_Tool_v0.60.10.pyt` from this folder. The toolbox should
show six entries: Step 0, Step 0b, Step 1, Step 2, Step 3, and Step 4.

Step 0b writes these files to `<Project Root>/02_Scan_Index`:

- `ccm_data_catalog.json` — factual inventory plus normalized scoring records;
- `CCM_Data_Intelligence_Report.html` and `.txt` — factual reports;
- `ccm_quality_scores.json` — eight evidence-based quality metrics;
- `ccm_fitness_scores.json` — role-specific dataset evaluations;
- `ccm_confidence_scores.json` — role and model confidence;
- `ccm_readiness_scores.json` — current readiness status;
- `ccm_recommendations.json` — machine-readable reviewable selections; and
- `CCM_Recommendations_Report.html` — human-readable recommendation report.

`ccm_project.json` itself lives directly in the Project Root Folder, not in
`02_Scan_Index`.

Step 1 displays the recommendations at startup. Its explicit parameters remain
authoritative, and any override is still the analyst's decision.

## Release files

| File | Purpose |
|---|---|
| `CCM_Tool_v0.60.10.pyt` | ArcGIS Pro toolbox entry point |
| `ccm_project_config.py` | Canonical `ccm_project.json` read/write (`load_config`/`save_config`) and `run_tool()` test dispatch |
| `ccm_project_init.py` | Standalone Project Initializer GUI (creates the single-root layout, no arcpy needed) |
| `build_project_init_exe.py` | PyInstaller build script for the Project Initializer |
| `CCM_Data_Scanner_GUI.py` | Standalone, single-root-aware Data Intelligence Scanner GUI |
| `ccm_step0b_intelligence.py` | Step 0b toolbox class, factual engine, and CLI |
| `ccm_step0b_integration.py` | Integrated scoring and recommendation workflow |
| `ccm_data_quality.py` | Quality scoring engine |
| `ccm_data_fitness.py` | Role fitness engine |
| `ccm_data_confidence.py` | Confidence engine |
| `ccm_data_readiness.py` | Step 1 readiness engine |
| `ccm_data_selector.py` | Reviewable role recommendation engine |
| `ccm_step1_recommendations_ui.py` | Step 1 recommendation display |
| `RUN_TESTS.bat` | Anaconda verification launcher |
| `RUN_ARCGIS_SMOKE_TEST.bat` | Licensed ArcPy smoke launcher (7 tests) |
| `test_single_root_pure_python.py` | Pure-Python (no arcpy) verifier for the single-root rewrite |
| `MANUAL_TEST_CHECKLIST.md` | Manual ArcGIS Pro dialog-walkthrough checklist |
| `package_ccm.py` | Blocking verifier and ZIP packager |
| `CCM_Tool_v0.60.10_User_Manual.docx` | Full English operator manual |

## Verification

`RUN_TESTS.bat` runs static syntax/version checks, pyflakes, calibration
audits, the legacy regression suite, the factual inventory tests, the
integration tests, fixture generation, and an end-to-end scan that verifies
all factual, scoring, recommendation, and project-config outputs. Generated
logs and fixtures are excluded from the release ZIP.

`test_single_root_pure_python.py` additionally exercises every pure-Python
part of the single-root rewrite (config round-tripping, the Project
Initializer, a full Step 0b integrator scan, and `package_ccm.py`'s own
end-to-end self-check) without needing arcpy at all.

The ArcPy launcher (`RUN_ARCGIS_SMOKE_TEST.bat`) runs the Steps 0-3 smoke
tests, the single-root dialog-behavior smoke test (Vehicle dropdown
scenarios A/B/C plus a Step 0b-only negative control, and the Step 3
GDB-resolution fallback), the factual Step 0b smoke test, and the integrated
Step 0b smoke test. ArcPy and a valid ArcGIS Pro license are required for
that gate. `MANUAL_TEST_CHECKLIST.md` walks through the same ground by hand
inside ArcGIS Pro's own dialogs.

License: GPL-2.0-or-later. Copyright (c) 2026 Eui Soo SON.

# <<< END OF FILE >>>
