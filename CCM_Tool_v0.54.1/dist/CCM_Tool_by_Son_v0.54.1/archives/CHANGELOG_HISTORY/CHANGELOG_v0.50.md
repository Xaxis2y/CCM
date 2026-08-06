<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
<!-- Copyright (c) 2026 Eui Soo SON -->

# CHANGELOG — v0.50.0 (2026-07-01)

## Bug Fixes

| ID | Severity | File | Fix |
|----|----------|------|-----|
| BUG-1 | Critical | `ccm_step1_setup.py` | `save_config(project_folder, config)` passed the config dict positionally to a keyword-only function → `TypeError` at the end of Step 1 and `ccm_project.json` was never written through the primary path. Now called as `save_config(project_folder, **config)`. |
| BUG-2 | Major | `ccm_step1_setup.py` | Multiple hydrology layers were stored in the config as ONE semicolon-joined (quoted) string, so Step 2/3 `arcpy.Exists()` failed for every hydro layer whenever >1 layer or a path with spaces was supplied — water was silently not treated as NO-GO. Now parsed with `_parse_multi()` into a proper list. |
| BUG-3 | Moderate | `ccm_step3_advanced.py` | After `addDataFromPath`, the code grabbed `listLayers()[0]` and assumed it was the just-added layer — wrong with group layers or user-reordered contents; symbology/renames could land on the wrong layer. Now uses the layer object returned by `addDataFromPath` (with `listLayers()[0]` as fallback only). |
| BUG-4 | Minor | `ccm_step0_mgcp.py` | `overwriteOutput` was hard-set to `False` after each `CopyFeatures` instead of leaving it for the run; `execute()` restores the caller's original value at the end. |

## New — Step 2 map display

- The derived Output Speed Surface parameter now carries
  `Symbology\Mobility_Symbology_Final.lyrx`, so ArcGIS Pro applies the CCM
  mobility symbology automatically when the derived output is added to the
  map. Previously the speed surface appeared with random default symbology.

## New — MGCP feature-code catalog (`ccm_mgcp_catalog.py`)

Pure-Python FACC/DIGEST code dictionary (~140 codes) mapping MGCP
feature-class names to human-readable names, display themes, and CCM roles
(soil / veg / hydro / contours / road / obstacle). First-letter theme
fallback guarantees every FC gets at least a theme
(A=Culture, B=Hydrography, C=Elevation, D=Physiography, E=Vegetation, …).

### Step 0 — Load MGCP Data (loader lineage v0.13)

- **Labelled pick-list** — the FC filter now shows
  `AP030 — Road (Transportation)` instead of bare `AP030`. Old bare-name
  selections are still accepted.
- **Theme filter** (new parameter 12) — import only chosen themes; the
  convenience entry *CCM-Relevant Only* expands to
  Soil / Vegetation / Hydrography / Transportation / Elevation / Physiography.
- **Group layers by theme** (new parameter 13, default ON) — map layers are
  nested under `MGCP — <Theme>` group layers and renamed with their
  human-readable catalog label. Overrides Group-by-GDB-Name when enabled.
- **`mgcp_manifest.json`** — written next to the output GDB after import:
  per-FC code, name, theme, ccm_role, geometry, feature count, spatial
  reference, field list, and contributing source cells. The run log also
  prints a classification-by-theme summary and the detected CCM-usable
  layers.
- Existing parameter indices unchanged (new parameters appended at 12/13).

### Step 1 — Project Setup

- New optional parameter 25: **MGCP Manifest**. Pointing it at Step 0's
  `mgcp_manifest.json` auto-fills (only where the user left fields empty):
  - Raw Soil FC ← `DA010` (Ground Surface Element, SMC attribute)
    and Soil Data Source ← `MGCP`
  - Hydrology Layers ← all water-body polygons (BH080, BH140, BA040, …)
  - Contour Lines ← `CA010` (when no DEM is provided)
- Auto-fill runs in the dialog (`updateParameters`) and again at execute
  time so scripted `run_tool` invocations benefit too. Everything remains
  user-overridable.

## Version

- All module `VERSION` constants → `0.50.0`.
- Toolbox renamed `CCM_Tool_by_Son_v0.49.3.pyt` → `CCM_Tool_by_Son_v0.50.0.pyt`
  (sidecar XMLs and `build.py` updated).

---

# v0.50.1 (2026-07-01) — consistency & repair patch

- Full-repo version sweep: every module `VERSION`, the toolbox filename
  (`CCM_Tool_by_Son_v0.50.1.pyt`), all `.pyt.xml` sidecars (the stale v0.49.2
  Step 1 / Vehicle Compare sidecars renamed and re-pointed), `build.py`,
  README, PROJECT_STATUS, TASKS, and test assertions now agree on one
  version string.
- Repaired `TASKS.md` — a 530-byte NULL block (file corruption from an
  earlier session) removed; final release-log row restored.
- Restored missing `# <<< END OF FILE >>>` integrity markers on the four
  step modules; `build.py` check now passes 19/19 (was silently
  unverifiable before).
- `build.py` PY_FILES extended with `ccm_mgcp_catalog.py` and
  `tests/test_v050.py`.

---

# v0.50.2 (2026-07-03) — truncation-recovery patch (CRITICAL)

A full-file audit found that two modules had been **silently truncated by a
failed write in an earlier session**, and the `# <<< END OF FILE >>>` markers
"restored" in v0.50.1 had been appended to the already-truncated files —
masking the damage. Both files still parsed as valid Python (the cut happened
to land on syntactically complete lines), so syntax checks and the arcpy-free
test suite passed.

## Restored code

| File | What was lost / restored |
|------|--------------------------|
| `ccm_step0_mgcp.py` | Everything after the first line of the import loop (cut at `arcpy.SetProgresso…`): the SKIP/APPEND/OVERWRITE import loop, `mgcp_manifest.json` writer (code / label / theme / ccm_role / geometry / feature count / spatial reference / field list / source cells per FC), classification-by-theme summary, add-to-map with theme group layers + catalog layer renaming, and the derived-output assignment. Step 0 imported **nothing** in this state. |
| `ccm_step1_setup.py` | Everything after the soil pre-processing block (cut mid-comment `# ── Pr`): vegetation pre-processing (`veg_ccm` via `run_tool`), slope-region derivation from DEM (Spatial Analyst, percent-rise classes 0-3-6-10-20-30-45-60+ → `slope_regions` FC with `slope_pct`), hydrology list parsing, the `save_config()` call, and the completion banner. Step 1 wrote **no config** in this state. |
| `ccm_step3_advanced.py` | Three helpers that were called but no longer defined — `_list_speed_surfaces()`, `_label_from_speed_fc()`, `_derive_output_path()` — causing every Step 3 sub-tool (Isochrone, Vehicle Compare, Obstacle Detection, Waypoint Routing) to fail with `NameError` at runtime, and the Vehicle-B dropdown / auto-labels to never populate. Reimplemented. |

Also repaired during this audit: `README.md` (truncated mid-table; rewritten
with Step 0 workflow entry and a complete component table).

## Safeguards

- `build.py` integrity check extended: in addition to `ast.parse` and the EOF
  marker, it now runs a pyflakes **undefined-name** scan on every file (when
  pyflakes is installed) — code that calls helpers lost to truncation fails
  the build instead of shipping.
- Test suite: 130 passed / 3 skipped (arcpy-free), pyflakes clean of
  undefined names.

## Version

- All module `VERSION` constants → `0.50.2`; toolbox renamed
  `CCM_Tool_by_Son_v0.50.1.pyt` → `CCM_Tool_by_Son_v0.50.2.pyt` (sidecar XMLs, `build.py`,
  README, PROJECT_STATUS, test assertions updated).
- User manual updated: `CCM_Tool_by_Son_v0.50.2_User_Manual.docx` (title page,
  new §2.5 Step 0 — Load MGCP Data, architecture table Step 0 row, version
  history through v0.50.2).
