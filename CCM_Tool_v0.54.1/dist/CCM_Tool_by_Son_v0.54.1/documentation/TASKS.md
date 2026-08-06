<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
<!-- Copyright (c) 2026 Eui Soo SON -->

# CCM Tool by Son — Task Tracking
*Last updated: 2026-07-21 (session 7) | Current version: v0.54.1*

---

## Completed (v0.49.0 — 2026-06-19)

| # | Task | Notes |
|---|---|---|
| 1 | Speed Made Good + %NOGO area-weighted summary | `compute_speed_made_good()` in `ccm_step2_mobility.py` |
| 2 | Fix `combine_speed`: product → min-of-limiting-factors | `speed_model="min"` default; backward-compat `"product"` |
| 3 | Add MMP metric (`compute_mmp_estimate()`) | `mmp_kpa` column added to `Vehicles_Can.csv` |
| 4 | Stochastic GO/NOGO via Monte Carlo (`compute_stochastic_go()`) | Opt-in `enable_stochastic=True`; `P_GO` field |
| 5 | Spatial soil moisture (`get_spatial_soil_moisture()`) | Open-Meteo 3×3 grid; `moisture_vwc_to_condition()` in `ccm_weather.py` |
| 6 | Unit tests for all new functions | `tests/test_ccm.py` — **103 passed, 3 skipped** with `python -B -m pytest` |
| 7 | Changelogs, PROJECT_STATUS, VERSION bump to 0.49.0 | `CHANGELOG_v0.49.md`, `PROJECT_STATUS.md` |
| 8 | Run test suite and verify | **103 passed, 3 skipped, 0 failed** ✅ |
| 9 | RCI table calibration | `soil_rci.csv` + `_BUILTIN_USCS_RCI` — ERDC/GL TR-02-6 + FM 5-430-00-1 + NRMM Turnage 1971. Tests still 103 passed ✅ |
| 10 | User manual updated to v0.49 | `CCM_Tool_by_Son_v0.49_User_Manual.docx` — new Sections 7.4–7.7, updated formula, P_GO field, mmp_kpa column, version history (v0.48 + v0.49 rows added) ✅ |

---

## Open (prioritized)

### ~~P1 — RCI table calibration~~ ✅ DONE (2026-06-19 session 2)

Values updated in `soil_rci.csv` and `_BUILTIN_USCS_RCI` per ERDC/GL TR-02-6,
FM 5-430-00-1 App E, NRMM Turnage 1971. See `CHANGELOG_v0.49.md` section 6.
Tests: 103 passed.

---

### ~~P3 — Update user manual for v0.49~~ ✅ DONE (2026-06-19 session 3)

`CCM_Tool_by_Son_v0.49_User_Manual.docx` created from the v0.46 base. Changes:
- Title page: v0.46 → v0.49
- Section 1.3: formula updated (product → min); min-model explanation added
- Section 5 (Step 2): intro updated with new opt-in parameters; P_GO row added to output fields table; mmp_kpa row added to vehicle CSV column table
- Sections 7.4–7.7 added: Speed Made Good, Spatial Soil Moisture, Stochastic P(GO), MMP
- Section 7.3: note that RCI values now calibrated to ERDC/GL TR-02-6
- Section 10.1: ccm_step2_mobility.py and ccm_weather.py descriptions updated
- Section 10.4 version history: v0.48 and v0.49 rows added
- Validated: 1105 → 1137 paragraphs (+32), XML clean

---

### P2 — Validate Step 2 in ArcGIS Pro

**File:** `tests/arcpy_smoke_test.py`

**What:** Run the smoke test in the ArcGIS Pro Python window on a licensed machine.
The script is ready; it just needs to be executed.

**Blocker:** Requires ArcGIS Pro license (cannot run in this shell environment).

**How to run:**
1. Open ArcGIS Pro
2. Open Python window (Analysis → Python)
3. `exec(open(r"<path>\tests\arcpy_smoke_test.py").read())`

---

### P4 — SMAP L4 integration

**File:** `ccm_weather.py` — replace `_query_open_meteo_soil()` stub

**What:** Replace the Open-Meteo ERA5 (~9 km) soil moisture source with
NASA SMAP L4 (true 9 km, 3-hourly, with freeze/thaw layer — NG-NRMM gold standard).

**Interface is stable** — replacing only the inner fetch function:
```python
def _query_open_meteo_soil(lat, lon) -> Optional[float]:
    # Replace body with SMAP OPeNDAP client
    # Returns VWC float (m³/m³) or None
```

**SMAP L4 access:**
- Endpoint: `https://opendap.earthdata.nasa.gov/providers/NSIDC_ECS/...`
- Auth: NASA Earthdata credentials (username/password or .netrc)
- Product: `SPL4SMGP` (SMAP L4 Global 3-hourly, 9 km EASEv2)
- Variable: `Geophysical_Data/sm_surface` (0–5 cm volumetric water content)

**Blocker:** NASA Earthdata credentials required.

---

### P5 — Direction-dependent slope speed (deferred)

**File:** `ccm_step2_mobility.py` — `slope_factor()`

**What:** NG-NRMM outputs max speed for three directions (up/down/cross-slope)
via tractive-effort vs. grade-resistance curves. Current F1 uses a single scalar.

**Requires:** Slope aspect layer + travel bearing from isochrone/waypoint tools.
**Status:** Deferred to next release.

---

### P6 — MMP column validation

**File:** `Vehicles_Can.csv` — `mmp_kpa` column

**What:** Current `mmp_kpa` values are formula-derived from VCI_50 (Shoop 2000).
Replace with measured values from vehicle technical manuals (ERDC/GL-00-1 or OEM specs).

---

### Backlog

- Split `ccm_soil_preprocess.py` (3,900 lines) — deferred by decision
- Distance Accumulation for isochrone/waypoints (performance)
- NumPy vectorization in obstacle detect (performance)
- ML-based USCS classification (future)

---

## How to resume

```bash
# 1. Navigate to project
cd /sessions/friendly-wonderful-mccarthy/mnt/CCM_Tool_by_Son_v0.48.0/CCM_Tool_by_Son_v0.48.0

# 2. Verify tests still green
python -B -m pytest tests/test_ccm.py -v 2>&1 | tail -5
# Expected: 103 passed, 3 skipped, 0 failed

# 3. Next task: P2 — Validate in ArcGIS Pro (requires licensed machine)
#    OR P4 — SMAP L4 integration (requires NASA Earthdata credentials)
#    OR P5 — direction-dependent slope (requires aspect layer design)
```

## Key file paths

| What | Path |
|---|---|
| Project root | `C:\Users\son.es\Documents\ES_Project\CCM_Tool_by_Son_v0.48.0\CCM_Tool_by_Son_v0.48.0\` |
| Mobility engine | `ccm_step2_mobility.py` |
| Weather / soil moisture | `ccm_weather.py` |
| RCI calibration table | `soil_rci.csv` |
| Vehicle definitions | `Vehicles_Can.csv` |
| Test suite | `tests/test_ccm.py` |
| User manual (v0.49) | `CCM_Tool_by_Son_v0.49_User_Manual.docx` |
| This file | `TASKS.md` |
| 11 | Release zip built | `CCM_Tool_by_Son_v0.50.1.zip` — 19/19 files OK, all integrity checks passed ✅ |
| 12 | v0.50.2 truncation-recovery release | Restored truncated `ccm_step0_mgcp.py` / `ccm_step1_setup.py`, reimplemented 3 missing Step 3 helpers, rewrote truncated `README.md`; pyflakes undefined-name check added to `build.py`; manual updated; `CCM_Tool_by_Son_v0.50.2.zip` — 19/19 files OK ✅ |
| 13 | v0.51.0 map display release | New `ccm_map_display.py`; Step 3 display block rewritten (hollow blue→purple reachability rings, COMPARE_RESULT difference-only renderer, red-hatched obstacles, per-run `CCM — <vehicle> (<moisture>)` group with enforced draw order); 8 new tests (138 total); `CCM_Tool_by_Son_v0.51.0.zip` ✅ |
| 14 | v0.51.1 Unknown-CRS auto-repair | Step 0: pre-run .prj detection warning, new Assume-WGS84 parameter (DefineProjection on import — assign, never reproject), SR-mismatch warning names offending cells; `CCM_Tool_by_Son_v0.51.1.zip` ✅ |
| 15 | v0.52.0 one-folder Data Root | New `ccm_data_discovery.py` (keyword + content sniffing, accuracy ranking for duplicate soil/DEM/veg sources); Data Root parameter on Step 0 (auto-fills MGCP inputs) and Step 1 (extent/DEM/contours/veg/hydro/vehicle/soil block); 10 new tests (148 total); `CCM_Tool_by_Son_v0.52.0.zip` ✅ |
| 16 | v0.53.0 vehicle database | `Vehicles_Can.csv` expanded 13 → 64 platforms (16 CAN / 26 US / 22 RUS) with nation/source/note columns; derived VCI/MMP internally consistent with model constants; truncated Vehicle_Data copy repaired; 4 new tests (152 total); `CCM_Tool_by_Son_v0.53.0.zip` ✅ |
| 17 | v0.53.2 waypoint-truncation fix | Restored truncated `CCMWaypointTool.execute()` (now calls `find_route()` — Step 3 waypoint routing was silently producing no output); hardened Step 3 to only report success / add the layer when the route FC exists; version bumped 0.53.1 → 0.53.2 across modules, `.pyt` + sidecars, tests, docs, manual; `CCM_Tool_by_Son_v0.53.2.zip` ✅ |
| 18 | v0.53.3 lint + copyright | Source modules made pyflakes-clean (removed unused imports `math`/`sys`/`os`/`arcpy.sa`/`_veg_mod`, dead locals `pt`/`speeds_sorted`/`p_vehicle`/`desc`/`_COORD_HINT`, fixed the invalid `\.` docstring escape and three placeholder-less f-strings — no behavioural change); copyright headers reduced to `Eui Soo Son` only across all modules, README and the CHANGELOG v0.49 author line (removed rank/GETESS/MCE/CAF/proprietary boilerplate); version bumped 0.53.2 → 0.53.3 across modules, `.pyt` + sidecars, tests, docs, manual; `CCM_Tool_by_Son_v0.53.3.zip` ✅ |
| 19 | v0.54.0 CRS smart warnings + manual | Extended the Geographic-CRS check (previously only Step 1's Analysis Extent, blocking) with new non-blocking warnings: Step 0 Output Coordinate System (recommends UTM before Step 1), Step 1 supporting layers (DEM/Slope/Contours/Soil/Vegetation/Hydro vs. the Analysis Extent), Step 3 Speed Surface + obstacle-detection layers, Step 4 Vehicle A/B mismatch. New shared `ccm_coords.describe_spatial_reference()` / `geographic_crs_warning()` / `crs_mismatch_warning()` helpers (5 new tests, 160 total, 157 passed / 3 skipped). User Manual: new Section 3.4 (why Projected CRS / UTM, beginner-level, worked UTM-zone example) plus per-step data/projection notes in Sections 2.5, 4.1, 5, 6.3, new Troubleshooting rows, and a Step 4 row added to the Section 1.4 step table; version bumped 0.53.3 → 0.54.0 across modules, `.pyt` + sidecars, tests, docs, manual; `CCM_Tool_by_Son_v0.54.0.zip` ✅ |
| 20 | v0.54.1 rebrand + relicense | "MCE CCM Tool" renamed "CCM Tool by Son" throughout — toolbox, all source/test files, filenames (`CCM_Tool_by_Son_v0.54.1.pyt` + sidecars, zip, user manual), and every doc including historical CHANGELOGs; project relicensed under SPDX-License-Identifier: GPL-2.0-or-later (previously "All Rights Reserved"; new copyright line: Copyright (c) 2026 Eui Soo SON (Beta)); version bumped 0.54.0 → 0.54.1 across modules, `.pyt` + sidecars, tests, docs, manual; `CCM_Tool_by_Son_v0.54.1.zip` ✅ |
