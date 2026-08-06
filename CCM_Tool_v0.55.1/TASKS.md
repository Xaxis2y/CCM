# CCM Tool — Task Tracking
*Last updated: 2026-08-06 (session 10) | Current version: v0.55.1*

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
| 10 | User manual updated to v0.49 | `CCM_Tool_v0.49_User_Manual.docx` — new Sections 7.4–7.7, updated formula, P_GO field, mmp_kpa column, version history (v0.48 + v0.49 rows added) ✅ |

---

## Open (prioritized)

### ~~P1 — RCI table calibration~~ ✅ DONE (2026-06-19 session 2)

Values updated in `soil_rci.csv` and `_BUILTIN_USCS_RCI` per ERDC/GL TR-02-6,
FM 5-430-00-1 App E, NRMM Turnage 1971. See `CHANGELOG_v0.49.md` section 6.
Tests: 103 passed.

---

### ~~P3 — Update user manual for v0.49~~ ✅ DONE (2026-06-19 session 3)

`CCM_Tool_v0.49_User_Manual.docx` created from the v0.46 base. Changes:
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
cd /sessions/friendly-wonderful-mccarthy/mnt/CCM_Tool_v0.48.0/CCM_Tool_v0.48.0

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
| Project root | `C:\Users\son.es\Documents\ES_Project\CCM_Tool_v0.48.0\CCM_Tool_v0.48.0\` |
| Mobility engine | `ccm_step2_mobility.py` |
| Weather / soil moisture | `ccm_weather.py` |
| RCI calibration table | `soil_rci.csv` |
| Vehicle definitions | `Vehicles_Can.csv` |
| Test suite | `tests/test_ccm.py` |
| User manual (v0.49) | `CCM_Tool_v0.49_User_Manual.docx` |
| This file | `TASKS.md` |
| 11 | Release zip built | `CCM_Tool_v0.50.1.zip` — 19/19 files OK, all integrity checks passed ✅ |
| 12 | v0.50.2 truncation-recovery release | Restored truncated `ccm_step0_mgcp.py` / `ccm_step1_setup.py`, reimplemented 3 missing Step 3 helpers, rewrote truncated `README.md`; pyflakes undefined-name check added to `build.py`; manual updated; `CCM_Tool_v0.50.2.zip` — 19/19 files OK ✅ |
| 13 | v0.51.0 map display release | New `ccm_map_display.py`; Step 3 display block rewritten (hollow blue→purple reachability rings, COMPARE_RESULT difference-only renderer, red-hatched obstacles, per-run `CCM — <vehicle> (<moisture>)` group with enforced draw order); 8 new tests (138 total); `CCM_Tool_v0.51.0.zip` ✅ |
| 14 | v0.51.1 Unknown-CRS auto-repair | Step 0: pre-run .prj detection warning, new Assume-WGS84 parameter (DefineProjection on import — assign, never reproject), SR-mismatch warning names offending cells; `CCM_Tool_v0.51.1.zip` ✅ |
| 15 | v0.52.0 one-folder Data Root | New `ccm_data_discovery.py` (keyword + content sniffing, accuracy ranking for duplicate soil/DEM/veg sources); Data Root parameter on Step 0 (auto-fills MGCP inputs) and Step 1 (extent/DEM/contours/veg/hydro/vehicle/soil block); 10 new tests (148 total); `CCM_Tool_v0.52.0.zip` ✅ |
| 16 | v0.53.0 vehicle database | `Vehicles_Can.csv` expanded 13 → 64 platforms (16 CAN / 26 US / 22 RUS) with nation/source/note columns; derived VCI/MMP internally consistent with model constants; truncated Vehicle_Data copy repaired; 4 new tests (152 total); `CCM_Tool_v0.53.0.zip` ✅ |
| 17 | v0.53.2 waypoint-truncation fix | Restored truncated `CCMWaypointTool.execute()` (now calls `find_route()` — Step 3 waypoint routing was silently producing no output); hardened Step 3 to only report success / add the layer when the route FC exists; version bumped 0.53.1 → 0.53.2 across modules, `.pyt` + sidecars, tests, docs, manual; `CCM_Tool_v0.53.2.zip` ✅ |
| 18 | v0.53.3 lint + copyright | Source modules made pyflakes-clean (removed unused imports `math`/`sys`/`os`/`arcpy.sa`/`_veg_mod`, dead locals `pt`/`speeds_sorted`/`p_vehicle`/`desc`/`_COORD_HINT`, fixed the invalid `\.` docstring escape and three placeholder-less f-strings — no behavioural change); copyright headers reduced to `Eui Soo Son` only across all modules, README and the CHANGELOG v0.49 author line (removed rank, unit attribution, and proprietary boilerplate); version bumped 0.53.2 → 0.53.3 across modules, `.pyt` + sidecars, tests, docs, manual; `CCM_Tool_v0.53.3.zip` ✅ |
| 19 | v0.54.0 CRS smart warnings + manual | Extended the Geographic-CRS check (previously only Step 1's Analysis Extent, blocking) with new non-blocking warnings: Step 0 Output Coordinate System (recommends UTM before Step 1), Step 1 supporting layers (DEM/Slope/Contours/Soil/Vegetation/Hydro vs. the Analysis Extent), Step 3 Speed Surface + obstacle-detection layers, Step 4 Vehicle A/B mismatch. New shared `ccm_coords.describe_spatial_reference()` / `geographic_crs_warning()` / `crs_mismatch_warning()` helpers (5 new tests, 160 total, 157 passed / 3 skipped). User Manual: new Section 3.4 (why Projected CRS / UTM, beginner-level, worked UTM-zone example) plus per-step data/projection notes in Sections 2.5, 4.1, 5, 6.3, new Troubleshooting rows, and a Step 4 row added to the Section 1.4 step table; version bumped 0.53.3 → 0.54.0 across modules, `.pyt` + sidecars, tests, docs, manual; `CCM_Tool_v0.54.0.zip` ✅ |
| 20 | v0.54.1 rebrand + relicense | Toolbox renamed and standardized to "CCM Tool" throughout — toolbox, all source/test files, filenames (`CCM_Tool_v0.54.1.pyt` + sidecars, zip, user manual), and every doc including historical CHANGELOGs; project relicensed under SPDX-License-Identifier: GPL-2.0-or-later (previously "All Rights Reserved"; new copyright line: Copyright (c) 2026 Eui Soo SON); version bumped 0.54.0 → 0.54.1 across modules, `.pyt` + sidecars, tests, docs, manual; `CCM_Tool_v0.54.1.zip` ✅ |
| 21 | v0.54.2 pre-release audit fixes | Full pre-release inspection of v0.54.1 found five defects, all fixed here. **(1)** `ccm_map_display.style_speed_surface()` built its renderer on `Condition_Number`, a field NO module has ever produced (the real contract field is `Mobility` = GO/RESTRICTED/NO GO) — the speed surface, the toolbox's primary deliverable, therefore rendered flat or unstyled whenever Step 3 rebuilt the map; it now applies the packaged `Mobility_Symbology*.lyrx` first (identical to what Step 2 attaches, so both paths produce the same map) with a Mobility-field `UniqueValueRenderer` as fallback, and reports loudly instead of `except: pass` when neither works. **(2)** Every colour table used a 0-255 alpha channel, but arcpy's CIM colour dict takes alpha on 0-100 — values of 150-255 were clamped to opaque, so no intended per-class transparency ever rendered; all tables corrected. **(3)** `build.py` walked the folder with no version filter and shipped 17 stale files in the v0.54.1 zip (two obsolete toolboxes from an earlier product naming, two superseded manuals, twelve orphan sidecars, a `~$` Word lock file) — added `should_include()` screening plus a hard stop when a second `.pyt` is present; stale files deleted and the duplicate root `Vehicles_Can.csv` removed in favour of `Vehicle_Data/`. **(4)** `tests/arcpy_smoke_test.py` did a bare top-level `import arcpy`, aborting pytest COLLECTION on any machine without ArcGIS Pro so the 157 real tests never ran — now `pytest.importorskip`. **(5)** `CCM_Tool_v*.pyt.xml` still carried `<toolbox name="…v0.50.1">` internally through four renames — rewritten, with an abstract and credit block added. Presentation: `.lyrx` legends pruned from 7 classes to the 3 Step 2 can emit (SLOW / VERY SLOW / NO GO - Hydro Feature / NO GO - Vegetation were permanently blank rows) and RESTRICTED recoloured amber to match; Step 3 layer/group names derive a clean vehicle label (`CCM — Leopard (moist)`, not `CCM — speed_surface_leopard_moist (moist)`); `kind_of()` returns `None` for unrecognised outputs instead of silently applying speed-surface symbology to them. Tests: the old `test_condition_colours_no_go_is_red` asserted the *buggy* `"1"`..`"5"` keys and was replaced by four regression guards (real field values, colour semantics, 0-100 alpha scale, `kind_of` None). 160 passed / 4 skipped. Version bumped 0.54.1 → 0.54.2 across modules, `.pyt` + sidecars, tests, docs, manual; `CCM_Tool_v0.54.2.zip` ✅ |
| 22 | v0.54.3 verification follow-up | Ran `tests/verify_v0543.py` against ArcGIS Pro 3.7.1 (9/9 checks, 0 fail). **Confirmed** defect 1 fails SILENTLY: assigning the non-existent `Condition_Number` to `renderer.fields` did not raise, arcpy built a 1-class renderer labelled `'400'` — every Step 3 speed surface since v0.51 drew as one flat colour with no warning. v0.54.2's renderer verified correct (field `Mobility`, 3 classes, right colours, clean layer name). **Fixed a regression** the run exposed: `style_speed_surface()` set `lyr.transparency` before `ApplySymbologyFromLayer()`, which resets it — the surface rendered fully opaque (`Transparency : 0.0`) and hid the basemap; transparency is now applied after symbology in every branch via `_set_transparency()`, with the value in one constant `SURFACE_TRANSPARENCY = 55`. **Corrected a claim**: v0.54.2 said arcpy clamps alpha >100 — it does not (240 read back as 240). The 0-100 scale is still right, established instead by Pro's own authored `.lyrx` storing 100 for opaque; the alpha test was rewritten to round-trip through a saved `.lyrx` and compare against that reference. Version bumped 0.54.2 → 0.54.3 across modules, `.pyt` + sidecars, tests, docs, manual; `CCM_Tool_v0.54.3.zip` ✅ |
| 23 | v0.54.4 Union license-limit fix | Ran `tests/arcpy_smoke_test.py` against a real ArcGIS Pro 3.7.1 / Standard-licence install for the first time — it FAILED: `build_speed_surface()` passed soil+veg+slope (3 inputs) to a single `arcpy.analysis.Union` call, which raises `ERROR 000384: Cannot have more than 2 inputs with a Basic or Standard license`. Step 2, the tool's core output, could not run at all below the Advanced tier — worse than any symbology defect since it blocks generation, not just presentation. New `_union_license_safe()` folds inputs pairwise (Esri's own documented fix for error 000384), unconditionally rather than gated on a licence check, so it behaves identically on Basic/Standard/Advanced; single input uses `CopyFeatures`, chain intermediates are cleaned up, original source layers are never touched. 5 new tests in `TestUnionLicenseSafety` assert no `Union` call ever exceeds 2 inputs (1/2/3/5-input cases, including the exact failing shape, plus the 0-input error case) using a recorder in place of arcpy — these run without a licence and would have caught this before it ever reached one. 165 passed / 4 skipped. Version bumped 0.54.3 → 0.54.4 across modules, `.pyt` + sidecars, tests, docs, manual; `CCM_Tool_v0.54.4.zip` ✅ Follow-up in the same release: Steps 0, 1, and 3 had NO real-ArcGIS coverage at all (only mocked-arcpy unit tests) despite Step 2 having just failed on first real contact — added `tests/arcpy_smoke_test_step0.py` (MGCP import + APPEND merge-cells path + manifest hand-off), `tests/arcpy_smoke_test_step1.py` (config write-out, THEN chains the real resulting `ccm_project.json` into `build_speed_surface()` to prove the actual Step 1 → Step 2 hand-off, not just each step in isolation), and `tests/arcpy_smoke_test_step3.py` (all 5 sub-analyses in one run — Reason Map, Isochrone, Vehicle Compare, Obstacle Detection, Waypoint Routing — plus confirms the map auto-load path degrades safely with no live Pro session). All three invoke via `run_tool()` by parameter name, matching CLAUDE.md convention. No version bump for this addition — new coverage, not a behaviour change (same precedent as `verify_v0542.py`/`verify_v0543.py`); `CLAUDE.md` Rule 1 item 4 updated to list all three. |
| 24 | v0.54.5 fixes from the new smoke tests | Running the 3 new smoke tests (row 23) against real ArcGIS Pro 3.7.1 surfaced two more findings — Step 0 passed clean (15/15), but Step 1 and Step 3 each found one real issue. **(1)** `tests/arcpy_smoke_test_step1.py` fed hand-off vehicle name `"TestTank"` into the REAL `Vehicles_Can.csv` (deliberately used for that test) — a name that only exists in the synthetic CSVs used by the Step 2/Step 3 smoke tests — so `build_speed_surface()` correctly raised `RuntimeError: Vehicle 'TestTank' not in CSV`. This proved the tool's error handling works; the test itself was wrong. Fixed by using `"M1"`, a real row in the shipped CSV. **(2)** `tests/arcpy_smoke_test_step3.py`'s Isochrone check hit `ERROR 160333: The table was not found` on `sa.Reclassify()`, immediately after a successful `DistanceAccumulation()` save — all 4 other Step 3 sub-analyses (Reason Map, Vehicle Compare, Obstacle Detection, Waypoint Routing incl. the No-Go snap fallback) passed cleanly in the same run. ERROR 160333 is a real but poorly-documented ArcGIS Pro raster issue — Esri's own KB article (000027676) only covers an unrelated cause (pre-upgrade file geodatabases), and an Esri Community thread on Pro 3.4.2 confirms no single deterministic root cause is published. Fixed in `ccm_isochrone.py` with two defence-in-depth mitigations: `cost_dist.save()` now runs inside the same `EnvManager(parallelProcessingFactor="100%")` block as `DistanceAccumulation()` (arcpy.sa rasters are evaluated lazily, so the previous scoping let the actual raster write happen under a different, inconsistent parallel-processing setting — one known trigger class for this error); and new `_reclassify_with_retry()` rebuilds raster statistics via `CalculateStatistics` and retries once, single-threaded (`parallelProcessingFactor="0"`), specifically for ERROR 160333, re-raising unchanged if the retry also fails or a different error occurs. No new mocked pytest was added for this fix: like the rest of `_generate_isochrones_sa()`, it depends on a local `import arcpy.sa as sa` and real Spatial Analyst raster objects, which the project's existing pattern (see row 23's `arcpy_smoke_test_step3.py`) validates via the real-ArcGIS smoke test rather than a fake-arcpy unit test — consistent with `_generate_isochrones_sa` never having mocked coverage either. Pytest suite unchanged at 165 passed / 4 skipped. Version bumped 0.54.4 → 0.54.5 across modules, `.pyt` + sidecars (incl. the 5 per-tool `.pyt.xml` metadata sidecars), tests, docs, manual. While updating docs, also corrected a mislabelled historical entry found in `PROJECT_STATUS.md` and two source-file comments: the v0.54.1 rebrand/relicense story had been mislabelled "v0.54.4" (a leftover from an earlier blanket version-string replace) — corrected to its true version, v0.54.1. `CCM_Tool_v0.54.5.zip` ✅ |
| 25 | v0.54.6 ERROR 160333 follow-up | The v0.54.5 fix was re-verified against real ArcGIS Pro 3.7.1 by re-running `tests/arcpy_smoke_test_step1.py` (17/17 PASS, `M1` hand-off confirmed working) and `tests/arcpy_smoke_test_step3.py` (Isochrone only failure). The log showed `_reclassify_with_retry()`'s v0.54.5 mitigation fired exactly as designed (`Rebuilding raster statistics and retrying once, single-threaded …`) but hit the IDENTICAL `ERROR 160333` again on retry — ruling out stale statistics / parallel tiling as the (whole) trigger. Two further changes in `ccm_isochrone.py`: **(1)** `_reclassify_with_retry()`'s primary attempt now runs Reclassify on the in-memory `cost_dist` Raster object instead of re-reading it from the scratch geodatabase immediately after `.save()` — re-reading a raster by path right after writing it is a plausible geodatabase catalog/business-table timing trigger for "table was not found"; the v0.54.5 stats-rebuild + single-thread retry is kept as a second-line fallback in case the in-memory attempt also fails. **(2)** `generate_isochrones()` now wraps the Spatial Analyst path in a try/except and falls back to the module's existing, licence-independent vector method (`_generate_isochrones_vector()`, previously only used when Spatial Analyst isn't licensed at all) if the SA path fails for any reason — so a persistent ArcGIS/licence/environment issue no longer means no isochrone output, just a less-precise one (polygon-bounded rather than raster-cell-bounded), with a clear warning logged either way. `tests/arcpy_smoke_test_step3.py` updated to capture the `_FakeMessages` instance and report via `note()` whether the raster or vector path actually produced the output, instead of treating both as an unqualified pass — kept the msgs.warnings inspection non-fatal since either path succeeding is a legitimate outcome. No new mocked pytest (same reasoning as v0.54.5 — depends on real `arcpy.sa` objects); validated by the real re-run. Pytest suite unchanged: 165 passed / 3 skipped. Version bumped 0.54.5 → 0.54.6 across modules, `.pyt` + sidecars, tests, docs, manual. `CCM_Tool_v0.54.6.zip` ✅ |
| 26 | v0.54.7 smoke-test detection fix | Re-ran `tests/arcpy_smoke_test_step3.py` against real ArcGIS Pro 3.7.1 to verify the v0.54.6 fix (log: `smoke_step3_v0546.log`). Structural checks all PASS (output FC exists, `TIME_BAND` field present, ≥1 ring), but the log revealed **both** v0.54.6 mitigations (in-memory Reclassify and the stats+single-thread retry) hit `ERROR 160333` again, identically — the raster path has now failed 3 consecutive real-environment attempts across v0.54.5/v0.54.6. Only the vector fallback produced output, and it did so correctly: the log's own `"Isochrones (vector method) saved to: …"` / `ISOCHRONE COMPLETE` messages confirm it. This is treated as the durable outcome going forward — a 4th speculative raster-level mitigation was not attempted without new diagnostic evidence; the resilience mechanism (guaranteed output via vector fallback, added in v0.54.6) is what actually solves the user-facing problem, independent of whether the underlying ArcGIS bug is ever fixed. Separately, the same log exposed a real bug in the smoke test's own diagnostic: it printed `INFO B. Isochrone: produced via Spatial Analyst path (DistanceAccumulation)` — the wrong answer — because the check inspected `msgs.warnings` for the SA→vector fallback notice, but `ccm_isochrone.py` logs that notice via the global `arcpy.AddWarning()`, a different channel the `messages` object passed into `run_tool()` never receives. Fixed by checking `"gridcode" in iso_fields` instead: `RasterToPolygon` (the SA path's last step) always adds that field, `Dissolve` (the vector path's last step) never does — verified directly against each method's own code, not inferred. No change to `ccm_isochrone.py`'s actual isochrone-generation logic this round — only the test's detection logic was wrong. Pytest suite unchanged: 165 passed / 3 skipped. Version bumped 0.54.6 → 0.54.7 across modules, `.pyt` + sidecars, tests, docs, manual. `CCM_Tool_v0.54.7.zip` ✅ |
| 27 | v0.55.0 consolidation (multi-PC merge) | Two machines had diverged: `CCM_Tool_v0.54.1` (renamed/relicensed today — GPL headers standardized, old changelogs archived to `archives/CHANGELOG_HISTORY/` — but built from a PRE-v0.54.2 snapshot, so none of rows 21-26 below had landed) vs. `CCM_Tool_v0.54.7` (rows 21-26 all present and verified, but still carrying the pre-rename branding). Diffed every file between both folders. 14 of 19 modules differed only in header/version cosmetics. 5 files carried real logic differences — `build.py`, `ccm_isochrone.py`, `ccm_map_display.py`, `ccm_step2_mobility.py`, `ccm_step3_advanced.py` — plus `Symbology/*.lyrx`; in every case the v0.54.7 side was strictly ahead (confirmed `_union_license_safe()`, the Mobility-field renderer + 0-100 alpha scale, the 3-class pruned `.lyrx` legend, the ERROR 160333 in-memory-Reclassify + vector fallback, and `build.py`'s `should_include()`/stale-toolbox guard were ALL present only in the v0.54.7 line — the v0.54.1 line's `build.py` had regressed to the pre-v0.54.2 unfiltered packager, its `Vehicles_Can.csv` had regressed to the pre-v0.54.2 duplicated-at-root state, its `arcpy_smoke_test.py` lacked the `pytest.importorskip` guard so pytest collection would abort on any machine without ArcGIS Pro, and its 3 per-tool smoke tests plus `verify_v0544.py` were simply absent). The User Manual in the v0.54.1 folder was also internally inconsistent — the title/filename used the new naming convention (`CCM_Tool_v0.54.1`) but body text still instructed users to open the old pre-rename toolbox filename, which doesn't exist under that name. Resolution: v0.54.7 taken as the code base, v0.54.1's debrand/relicense treatment re-applied on top (not the reverse), version bumped 0.54.7 → 0.55.0 across modules, `.pyt` + sidecars, tests, docs, manual; `CLAUDE.md` and `CCM_Improvement_Research.md` (present only in the v0.54.1 working folder — the v0.54.7 folder was release-zip contents, which exclude internal dev docs) carried forward; one-time cleanup reports specific to today's v0.54.1 pass (`CLEANUP_STATUS_v0.54.1.md`, `CLEANUP_SUMMARY.md`, `FINAL_CLEANUP_REPORT.txt`, a stale-file deletion list, `ZIP_CONTENTS.md`) retired as superseded. New `QUICK_START.md` added. Syntax-checked (`ast.parse`) and pyflakes-scanned clean on all 19 modules + `.pyt`; pytest suite runs 165 passed / 3 skipped (arcpy-dependent) in an environment without a licensed ArcGIS Pro install, confirming the `importorskip` guard carried over correctly. `CCM_Tool_v0.55.0.zip` ✅ |
| 28 | v0.55.1 version bump | Following a thorough scrub of v0.55.0 (removed all remaining pre-rename organization/product-name references from docs, code, and archived changelogs; fixed a privacy leak in `Vehicle_Data/Vehicles_Can.csv.xml`'s embedded ArcGIS lineage metadata; verified the exact two-line copyright header — `SPDX-License-Identifier: GPL-2.0-or-later` / `Copyright (c) 2026 Eui Soo SON` — across every module, the `.pyt`, the `.pyt.xml` `idCredit`, the manual, and every top-level doc; added missing header comments to `CHANGELOG_v0.54.md` / `CHANGELOG_v0.55.md`; rebuilt and re-verified clean: `build.py` 21/21 OK, pytest 165 passed / 3 skipped, pyflakes clean, zero residual hits on a whole-tree + in-zip + in-docx sweep), two new local-testing convenience files were added: `QUICK_START.html` (a styled HTML rendering of `QUICK_START.md`, now packaged in the release zip — `build.py`'s `INCLUDE_PATTERNS` gained `.html`) and `CCM_anaconda_environment.bat` (creates/verifies the dedicated `ccm_v055_test` conda environment on its own, as a companion prep step to `RUN_LOCAL_VERIFICATION.bat`; not packaged in the zip, same treatment as that file). No toolbox/geoprocessing logic changed. Version bumped 0.55.0 → 0.55.1 across modules, `.pyt` + sidecars, tests, docs, manual; `CCM_Tool_v0.55.1.zip` ✅ |
