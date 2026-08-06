<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
<!-- Copyright (c) 2026 Eui Soo SON -->

# CCM Tool v0.55.0 — Quick Start

One page to get from "toolbox on disk" to a first Mobility Map. For full
detail (parameter reference, troubleshooting, technical background), see
`CCM_Tool_v0.55.0_User_Manual.docx`.

---

## 1. Before you start, you need

- ArcGIS Pro 3.5 or newer, with the Spatial Analyst extension licensed
- The `CCM_Tool_v0.55.0` folder on disk (this folder)
- An Analysis Extent polygon (your study area) in a **Projected CRS**
  (e.g. UTM) — not Geographic/WGS84; see Manual Section 3.4 for why
- A DEM raster **or** a pre-drawn slope-regions polygon layer
- Soil data and vegetation data (Step 1 pre-processes either raw or
  already-prepared inputs — see Manual Sections 4.2 / 4.3)
- A vehicle definitions CSV (`Vehicle_Data/Vehicles_Can.csv` ships with
  64 platforms already; add your own rows or point at your own file)

## 2. Load the toolbox

1. Open ArcGIS Pro and your project.
2. Catalog pane → right-click **Toolboxes** → **Add Toolbox**.
3. Navigate to this folder and select `CCM_Tool_v0.55.0.pyt`.
4. Expand it — five tools appear: Step 0, Step 1, Step 2, Step 3, and
   Step 4 (Compare Two Vehicles).

If a tool shows as `[UNAVAILABLE — failed to load]`, one of the `ccm_*.py`
modules isn't sitting next to the `.pyt` file — make sure the whole folder
was copied, not just the `.pyt` itself.

## 3. Run it — Step by step

**Step 1 — Project Setup (once per project)**
1. Double-click **Step 1. Project Setup & Pre-process**.
2. Set **Project Output Folder** — a new empty folder (e.g. `C:\CCM\Mission01`).
3. Set **Analysis Extent** — your study area polygon (Projected CRS).
4. Set **DEM** or **Slope Regions** (or both).
5. Set **Default Soil Moisture Condition** (dry / moist / wet).
6. Fill in **Soil Pre-processing** and **Vegetation Pre-processing** for
   your data source.
7. Under **Hydrology & Vehicles**, set any water-body layers and the
   Vehicle Definitions CSV.
8. Click **Run**. This writes `ccm_project.json` in your output folder —
   every later step reads it and auto-fills.

**Step 2 — Generate the Mobility Map (once per vehicle)**
1. Double-click **Step 2**.
2. Select your **Project Folder** from Step 1 — everything else auto-fills.
3. Pick a **vehicle** from the dropdown. Run Step 2 again for each
   additional vehicle you want — each run produces its own speed surface.
4. Set the soil moisture condition; optionally tick **Use Live Weather**
   (or set a **Manual Rainfall Override**, which takes precedence) — see
   Manual Section 7.
5. Click **Run**. Output: a speed-surface polygon feature class
   (`SpeedKMH`, `Mobility`, `F1..F5`/`F_hydro` fields) in your project GDB.

**Step 3 — Advanced Analysis (optional, run any time after Step 2)**
1. Double-click **Step 3. Advanced Analysis**.
2. Select your **Project Folder** (auto-fills the Speed Surface FC).
3. Tick whichever analyses you want: Reason Map, Isochrone (reachability),
   Vehicle Compare, Obstacle Detection, Waypoint Route.
4. Fill in the parameters each ticked analysis needs.
5. Click **Run**.

**Step 4 — Compare Two Vehicles (optional, standalone)**
Skip Steps 1-3 entirely if you already have two Speed Surface feature
classes (e.g. from different project folders) — Step 4 compares them
directly. Both must share the same Projected CRS.

## 4. Reading the output map

All Step 3 outputs auto-load into `CCM_TOOL_MAP`, grouped per run as
"CCM — \<vehicle\> (\<moisture\>)":

- **Speed surface** — the only filled layer. Green = GO, amber =
  RESTRICTED, red = NO GO. Red always means No-Go and nothing else.
- **Reachability rings** (Isochrone) — hollow outlines, light→dark
  blue-purple by time band.
- **Vehicle Comparison** — filled only where the two vehicles differ
  (teal = Vehicle A only, orange = Vehicle B only).
- **Obstacle areas** — red 45° hatching.
- **Route** — magenta line, white halo; gold = start point, red = end point.

If a layer draws with default/random ArcGIS Pro symbology instead of the
above, check the Geoprocessing Messages pane — Step 3 logs a warning
naming exactly which layer's styling failed and why (see Manual Section 9).

## 5. Optional: Step 0 (batch-load MGCP data) and the Data Root shortcut

If your inputs are raw MGCP cells (GeoPackage / File GDB / Shapefile),
run **Step 0** first — it merges them into one geodatabase and writes
`mgcp_manifest.json`, which Step 1's **MGCP Manifest** parameter reads to
auto-fill Raw Soil FC, Hydrology Layers, and Contour Lines.

If you'd rather not browse to each dataset individually, put everything
under one parent folder with descriptive subfolder names (`Soil`, `DEM`,
`Vegetation`, `Hydro`, `Vehicle`, `Extent`, …) and point Step 0 and/or
Step 1's **Data Root Folder** parameter at it — every input left blank is
auto-filled, ranked by expected accuracy when duplicates exist. See Manual
Section 2.6.

## 6. If something goes wrong

Check the Geoprocessing Messages pane first — most CCM warnings/errors are
self-explanatory and name the offending parameter. Manual Section 9
(Troubleshooting) covers the common ones, including:

- `ERROR 000384` (Union licence limit) — fixed as of v0.54.4; make sure
  you're on v0.55.0, not an older unpatched copy.
- "Reachability Map log shows falling back to the vector method" — this
  is expected resilience behaviour (ERROR 160333, an intermittent ArcGIS
  Pro raster issue), not a failure; you still get a usable, slightly less
  precise Isochrone output.
- "Analysis Extent uses a Geographic CRS" — reproject to a Projected CRS
  (UTM) first; see Manual Section 3.4.

## 7. Verifying this copy of the toolbox

From this folder:

    pip install pytest
    pytest tests/test_ccm.py tests/test_v050.py -v   # arcpy-independent checks
    python build.py                                   # integrity check + rebuilds the release zip

Both should complete without errors. The `tests/arcpy_smoke_test*.py`
scripts and `tests/verify_v0544.py` additionally require a licensed
ArcGIS Pro install to run meaningfully — run them from ArcGIS Pro's
Python environment (see the Manual's Section 9.2 / `CLAUDE.md`) before
relying on this copy for production work, especially after moving it to
a new machine.

For a one-command version of all of the above (including the real-ArcGIS
smoke tests, in a dedicated cloned conda environment — never installed
into `base`), run `RUN_LOCAL_VERIFICATION.bat` from ArcGIS Pro's Python
Command Prompt. It writes a full timestamped log file next to itself.

# <<< END OF FILE >>>
