<!--
SPDX-License-Identifier: GPL-2.0-or-later
Copyright (c) 2026 Eui Soo SON
-->

# MANUAL_TEST_CHECKLIST.md — Single-root architecture verification

## Why this file exists

`test_single_root_pure_python.py` (in this same folder) verifies everything
that does **not** require `arcpy` — see that script's own docstring and its log,
`test_single_root_pure_python_<timestamp>.log`. For v0.60.10, the portable
release suite records **310 passed, 5 skipped** ArcPy-only tests when the
dedicated environment is available.

What it *cannot* verify is anything that only runs inside ArcGIS Pro's Python
(`arcpy`): Step 0's parameter-dialog behavior, Step 1's GDB creation/reuse inside
a real geodatabase, Step 2's Vehicle dropdown logic, and Step 3's speed-surface
hand-off. Those four are exactly the tools most affected by the v0.60.0 single-root
rewrite, so this checklist walks through them by hand.

Two complementary paths are provided for each stage:

* **A. Automated (`RUN_ARCGIS_SMOKE_TEST.bat`)** — runs the six `tests/arcpy_smoke_test_*.py`
  scripts via ArcGIS Pro's own `propy.bat`, all of which were updated for v0.60.0 in
  this pass (renamed `project_folder=` kwargs to `project_root=`, updated the
  `03_Project.gdb` name expectations, added explicit single-root layout assertions
  to the Step 0 test). This is the fast path — run it first.
* **B. Manual (inside ArcGIS Pro's own toolbox dialog)** — walks through the actual
  Geoprocessing pane UI, because the automated tests call `execute()` directly and
  therefore never exercise `updateParameters()`/`updateMessages()` dialog-only
  behavior (default-filling, dropdown population, warning/error messages). This is
  the only way to see Scenario A/B/C of the Vehicle dropdown fix (see Section 3)
  and the auto-created-on-open Project Root layout (Section 1) the way an analyst
  actually will.

Do both. B is short (about 15–20 minutes total) and is the part that most directly
answers "does the Vehicle dropdown actually populate now."

---

## 0. Setup

1. Open **Anaconda Prompt** (per project convention — do not install anything into
   the `base` conda environment). If you have not already built the dedicated CCM
   environment, run once:
   ```
   CCM_anaconda.bat ccm_tool
   ```
   This creates a `ccm_tool` conda env with `pytest`, `pyflakes`, and `pyinstaller`
   — used for Section 6 (EXE builds) below, not for the arcpy-dependent steps
   (ArcGIS Pro's own Python via `propy.bat` is required for those; conda environments
   cannot import `arcpy`).

2. Confirm you are testing the correct copy:
   ```
   cd /d C:\Users\Son\Documents\CCM_Tool\CCM_Tool_v0.60.0
   type ccm_version.py | findstr VERSION
   ```
   Expect `VERSION = "0.60.0"`. **v0.59.72 is untouched** — do not test against it by
   mistake.

3. Re-run the pure-Python check to confirm the working copy is healthy before
   spending time on the arcpy-dependent steps below:
   ```
   python test_single_root_pure_python.py
   ```
   Expect `Total checks: 45   Passed: 45   Failed: 0` at the end. If this fails,
   stop and report the log file rather than continuing to Section A/B below —
   something more fundamental broke.

---

## A. Automated ArcPy smoke tests (run first)

From Anaconda Prompt (or a plain `cmd.exe` — this script locates `propy.bat`
itself and does not need conda):

```
cd /d C:\Users\Son\Documents\CCM_Tool\CCM_Tool_v0.60.0
RUN_ARCGIS_SMOKE_TEST.bat
```

Expect at the end:
```
ALL ARCPY SMOKE TESTS PASSED: step0 step1 step2 step3 v060_single_root step0b step0b_integrated
```

If anything fails, the script prints the log path under `verification_logs\`.
**Send that log file back** — do not just say "step1 failed."

What each one now additionally proves for v0.60.0 (on top of what it already
checked pre-v0.60.0):

| Test | New v0.60.0 assertions |
|---|---|
| `step0` | `project_root=` is passed through `run_tool()`; `01_Input_Data/` and `02_Scan_Index/` are auto-created under the chosen root; `ccm_project.json` is written directly at the root with `project_root`/`data_root`/`scan_index_dir`/`project_gdb` all correctly populated — *before* `execute()` even runs (i.e. at dialog-validation time). |
| `step1` | `project_root=` (renamed from `project_folder=`) is accepted; the project GDB is resolved from `ccm_project.json`'s `project_gdb` key rather than a hardcoded name, and is expected to be `03_Project.gdb` (not the old `CCM_Project.gdb`). |
| `step2` | Unaffected by the rename (calls `build_speed_surface()` directly, which already reads `project_gdb` from config) — still confirms the Step 1 → Step 2 hand-off end-to-end. |
| `step3` | `project_root=` (renamed from `project_folder=`) is accepted by `run_tool()`; exercises all five Step 3 sub-analyses against a real Step-1-shaped project. |
| `step0b` / `step0b_integrated` | Confirms report artifacts land under `02_Scan_Index/` while `ccm_project.json` stays at the project root. |
| `v060_single_root` (new) | Drives `updateParameters()`/`updateMessages()` directly -- the dialog-time callbacks the other six tests never touch, since they all call `execute()` straight through `run_tool()`. This is the one that actually automates Sections 1, 4, and 5 below (Step 0's create-on-choose layout, all three Vehicle-dropdown scenarios plus the Step-0b-file negative control, and Step 3's GDB-resolution fallback) -- the sections below are still worth a real-eyes pass in the actual Pro dialog, but nothing here is untested if this one script passes. |

---

## 1. Step 0 (Load MGCP Data) — single-root layout auto-creation

**Goal:** confirm that simply *choosing* a Project Root Folder — without running
the tool yet — creates the `01_Input_Data` / `02_Scan_Index` folders and writes
`ccm_project.json`, so a user who stops after Step 0 already has a coherent
folder they can hand to Step 0b/1.

1. In ArcGIS Pro, open the CCM Toolbox → **Step 0 — Load MGCP Data**.
2. Pick (or create) a **new, empty** folder as **Project Root Folder** — e.g.
   `C:\CCM_Test\Project_A`.
3. **Without filling in anything else**, click into another field (to trigger
   `updateParameters()`), then check on disk:
   - [ ] `Project_A\01_Input_Data\` exists
   - [ ] `Project_A\02_Scan_Index\` exists
   - [ ] `Project_A\ccm_project.json` exists
   - [ ] Opening that JSON shows `"project_root"` and `"data_root"` both pointing
         at `Project_A` and `Project_A\01_Input_Data` respectively
4. Confirm **Output Geodatabase** auto-filled to `Project_A\03_Project.gdb`
   (not the old ArcGIS Pro home-folder default).
5. Add at least one MGCP `.gdb` as Input MGCP Geodatabase, run the tool.
   - [ ] Tool completes without error
   - [ ] `03_Project.gdb` now contains the imported layers
   - [ ] `ccm_project.json`'s `project_gdb` key matches the GDB actually used

---

## 2. Step 0b (Data Intelligence Scan) — now a separate standalone concept

**Goal:** confirm the scan can be pointed at the *same* Project Root Folder from
Step 1, and that its reports land in `02_Scan_Index/` without disturbing
`ccm_project.json` at the root.

1. Open **Step 0b — Data Intelligence Scan** (or run `CCM_Data_Scanner.bat` /
   `CCM_Data_Scanner_GUI.py` — see Section 4 below for the standalone GUI path).
2. Set **Project Root Folder** to the *same* `Project_A` folder used in Section 1.
3. Run it.
   - [ ] `Project_A\02_Scan_Index\` now contains `ccm_data_catalog.json`,
         `CCM_Data_Intelligence_Report.html/.txt`, `ccm_quality_scores.json`,
         `ccm_fitness_scores.json`, `ccm_confidence_scores.json`,
         `ccm_readiness_scores.json`, `ccm_recommendations.json`,
         `CCM_Recommendations_Report.html`
   - [ ] `Project_A\ccm_project.json` (still directly at the root, **not** inside
         `02_Scan_Index`) now has `data_catalog_json`, `data_quality_scores`, etc.
         keys pointing at the files above
   - [ ] Re-opening the HTML report shows non-empty catalog/scoring sections

---

## 3. Step 1 (Project Setup) — the GDB-reuse + data_root default check

1. Open **Step 1 — Project Setup & Pre-process**.
2. Set **Project Root Folder** to the *same* `Project_A` folder.
   - [ ] **Data Root Folder** auto-fills to `Project_A\01_Input_Data` (one-shot
         default — confirm it does *not* overwrite a value you've already typed
         if you clear it and retype something else, then reopen the tool)
3. Fill in Extent/Soil/Vegetation/Slope/Vehicle CSV as usual, run the tool.
   - [ ] Tool completes without error
   - [ ] **`03_Project.gdb` is reused** (check the tool's message log for
         `"Reusing existing project geodatabase"` rather than a fresh-create
         message) — this is the v0.60.0 reuse-aware fix; a second Step 1 run
         must not fail or silently recreate the GDB
   - [ ] `ccm_project.json` now has `vehicle_csv` populated

---

## 4. Step 2 (Generate Mobility Map) — the Vehicle dropdown fix (the original bug report)

This is the scenario the user originally reported: **"Nothing shows up in the Vehicle dropdown"**
(no drop-down options at all). Test all three scenarios below — B and C are the
ones that were silently broken before this fix.

1. Open **Step 2 — Generate Mobility Map**.
2. **Scenario A (normal case)** — point **Project Root Folder** at `Project_A`
   (the one that went through Step 1 above, which has a valid `vehicle_csv`).
   - [ ] Vehicle dropdown populates with real vehicle names from the CSV
3. **Scenario B (vehicle_csv path is stale/deleted)** — in a **copy** of
   `Project_A`'s `ccm_project.json`, edit the `vehicle_csv` value to a path that
   does not exist, then point Step 2 at that folder.
   - [ ] Vehicle dropdown still populates — now from the bundled fallback CSV
         (`Vehicle_Data\Vehicles_Can.csv`)
   - [ ] A warning message appears explaining the fallback is in use
4. **Scenario C (this is the exact bug from the report — a valid Step 1 config with
   `vehicle_csv` entirely missing from the JSON)** — in another copy, **remove**
   the `"vehicle_csv"` key from `ccm_project.json` entirely (leave `project_gdb`
   and everything else intact), then point Step 2 at that folder.
   - [ ] Vehicle dropdown still populates from the bundled fallback CSV (this is
         the specific case that previously showed **zero options and zero
         warning** — confirm a warning message now appears here too)
5. **Negative control** — point Step 2 at a folder that only has a Step 0b scan
   (from Section 2, before ever running Step 1) — i.e. `project_gdb` is also
   absent.
   - [ ] The error message correctly says this folder holds a Data Intelligence
         scan, not a Step 1 project, and tells the user to point at the Step 1
         Project Root Folder or run Step 1 (message should NOT mention the old
         `CCM_Project.gdb` name)

---

## 5. Step 3 (Advanced Analysis)

1. Open **Step 3 — Advanced Analysis**, point **Project Root Folder** at the
   same `Project_A` used through Steps 0/1/2.
   - [ ] Speed Surface FC auto-loads from the project config
2. Enable at least Reason Map + Isochrone, run.
   - [ ] Completes without error
   - [ ] Output feature classes land inside `03_Project.gdb` (not
         `arcpy.env.scratchGDB`) — this confirms the `_derive_output_path()`
         GDB-resolution fallback fixed in this pass works correctly for a
         brand-new v0.60.0 project

---

## 6. Standalone tools (new in v0.60.0)

### 6a. Project Init GUI/EXE (root-folder picker)

```
python ccm_project_init.py
```
   - [ ] A window opens with a "Browse…" button (Tkinter `askdirectory`)
   - [ ] Choosing a new empty folder creates `01_Input_Data/`, `02_Scan_Index/`,
         and `ccm_project.json` (and `03_Project.gdb` too, if run from inside
         ArcGIS Pro's Python where `arcpy` is importable — otherwise a warning
         explains the GDB step was skipped, and the tool does not crash)
   - [ ] Log pane shows each step; a completion message box appears

To build the standalone EXE (from **Anaconda Prompt**, inside the `ccm_tool`
environment created in Section 0):
```
conda activate ccm_tool
python build_project_init_exe.py
```
   - [ ] `dist\CCM_Project_Init.exe` is produced
   - [ ] Running it directly (double-click, no Python needed) opens the same GUI

### 6b. Data Scanner GUI — now calls the full Step 0b pipeline

```
python CCM_Data_Scanner_GUI.py
```
   or the prebuilt EXE from `build_exe.py`.
   - [ ] Selecting a Data Root Folder and Output Folder and running the scan
         now produces the SAME set of report files as running Step 0b from the
         ArcGIS toolbox (catalog + quality/fitness/confidence/readiness scores +
         recommendations, not just the old factual-only catalog+HTML)
   - [ ] The "Open Report" button still opens the HTML report correctly

To rebuild the full toolbox EXE with the newly-added hidden imports:
```
conda activate ccm_tool
python build_exe.py
```

---

## 7. Report back

For each unchecked box above, include:
- the exact ArcGIS Pro version and licensing level in use,
- the full text of any error/warning message shown in the tool's message pane,
- the relevant log file (from `verification_logs\` for Section A, or a copied
  `ccm_project.json` for Sections 1–5),
- whether v0.59.72 (the untouched original, in the sibling folder) shows the
  same problem — this tells us whether it's a v0.60.0 regression or a
  pre-existing issue.

If everything above passes, v0.60.0 is ready to replace v0.59.72 as the
production copy.

## v0.60.8 — Step 3 Obstacle Detection (licensed ArcGIS Pro)

Project: Lebanon template, Speed Surface `speed_surface_m1_moist`, Obstacle
Detection ON, everything else OFF.

- [ ] Hydro field shows HydroRIVERS (lines) first, then HydroLAKES.
- [ ] Log: `Loaded N vehicle(s)` with N > 0 and `Vehicle: M1 … 54.0 %`.
- [ ] Log: `Slope thresholds: CAUTION ≥ 22.7°, STOP ≥ 28.4°`.
- [ ] Log: `Contour interval auto-detected: … m` (or a warning if no elevation field).
- [ ] Basic licence: no ERROR 001102; log says GenerateNearTable directly.
- [ ] Log: `Measuring in WGS_1984_UTM_Zone_36N (EPSG 32636)` (Lebanon AOI centre ≈ 35.9°E).
- [ ] Log: water-gap count with a width basis of `DIS_AV_CMS`.
- [ ] Obstacles layer shows red (STOP) / amber (CAUTION) points.
- [ ] Group layer named `CCM — M1 (moist)` (no doubled moisture).
- [ ] No `start_point` FC created when Reachability/Routing are off.
- [ ] Start Point display: UTM `37S 231026 3764948`.
- [ ] Routing ON with End Point `37SBU 76416 20778`: dialog warns it is outside the AOI.
