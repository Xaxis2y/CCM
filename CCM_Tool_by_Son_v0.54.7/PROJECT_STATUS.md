# CCM Tool by Son — Project Status & Continuation Notes

*Current: **v0.54.7** — July 26, 2026 (see CHANGELOG files).*

> v0.54.7: smoke-test detection fix (no production-code change). Fixed
> `tests/arcpy_smoke_test_step3.py`'s check for which isochrone path ran —
> it inspected `msgs.warnings`, but `ccm_isochrone.py` logs the SA→vector
> fallback notice via the global `arcpy.AddWarning()`, not the `messages`
> object passed into `run_tool()`, so the check always silently reported
> "Spatial Analyst path" regardless of which method actually ran. A real
> re-run's log (`smoke_step3_v0546.log`) showed the vector fallback had
> fired while the test still printed the SA-path message — the
> contradiction that exposed the bug. Replaced with a `"gridcode" in
> iso_fields` check: `RasterToPolygon` (the SA path's last step) always
> adds that field; `Dissolve` (the vector path's last step) never does —
> verified directly against each method's own code. `ccm_isochrone.py`
> itself is unchanged this round: the v0.54.6 in-memory-Reclassify and
> vector-fallback mitigations were confirmed working in the same real
> re-run (see CHANGELOG_v0.54.md). See CHANGELOG_v0.54.md.

> v0.54.6: ERROR 160333 follow-up — the v0.54.5 mitigation didn't hold up.
> Re-running `tests/arcpy_smoke_test_step3.py` against real ArcGIS Pro 3.7.1
> showed `_reclassify_with_retry()`'s stats-rebuild + single-threaded retry
> fired exactly as designed but hit the IDENTICAL `ERROR 160333` again —
> ruling out stale statistics / parallel tiling as the (whole) trigger.
> Two further changes in `ccm_isochrone.py`: (1) the primary Reclassify
> attempt now runs on the in-memory `cost_dist` Raster object instead of
> re-reading it from the scratch geodatabase immediately after `.save()` —
> a plausible catalog-timing trigger for "table was not found"; the
> v0.54.5 stats+single-thread retry is kept as a second-line fallback.
> (2) `generate_isochrones()` now catches a total Spatial Analyst failure
> and falls back to the module's existing, licence-independent vector
> method, so a real ArcGIS/licence issue no longer means no isochrone
> output at all — just a less-precise one, with a clear warning logged.
> `tests/arcpy_smoke_test_step3.py` now reports which path (raster or
> vector) actually produced the output rather than treating both as an
> unqualified pass. See CHANGELOG_v0.54.md.

> v0.54.5: ERROR 160333 Reclassify fix + Step 1 smoke-test fix. Running the
> 3 new end-to-end smoke tests (Steps 0, 1, 3) against a real ArcGIS Pro
> 3.7.1 install surfaced two more findings the mocked-arcpy test suite could
> not: (1) `tests/arcpy_smoke_test_step1.py` fed the hand-off vehicle name
> "TestTank" into the REAL `Vehicles_Can.csv` — a name that only exists in
> the synthetic CSVs used by the other two smoke tests — so `build_speed_
> surface()` correctly raised `RuntimeError`; fixed by using a real vehicle
> ("M1"). (2) `tests/arcpy_smoke_test_step3.py`'s Isochrone check hit
> `ERROR 160333: The table was not found` on Reclassify, immediately after a
> successful DistanceAccumulation. This is a real but poorly-documented
> ArcGIS Pro raster issue (Esri KB 000027676; an Esri Community thread on
> Pro 3.4.2 confirms no single deterministic cause is published). Fixed in
> `ccm_isochrone.py` with two mitigations: `cost_dist.save()` now runs
> inside the same `EnvManager(parallelProcessingFactor="100%")` block as
> `DistanceAccumulation` (arcpy.sa rasters are evaluated lazily, so the
> previous scoping let the actual write happen under a different parallel
> setting); and a new `_reclassify_with_retry()` rebuilds raster statistics
> and retries once, single-threaded, if ERROR 160333 recurs. Steps 0 (15/15)
> and the rest of Step 3 (Reason Map, Vehicle Compare, Obstacle Detection,
> Waypoint Routing incl. the No-Go snap fallback) all passed cleanly on the
> real run. See CHANGELOG_v0.54.md.
>
> v0.54.4: Union license-limit fix. Running `tests/arcpy_smoke_test.py`
> against a real ArcGIS Pro 3.7.1 / Standard-licence install surfaced a
> failure the static review never touched — `build_speed_surface()` unioned
> soil + vegetation + slope (3 inputs) in one `arcpy.analysis.Union` call,
> which raises `ERROR 000384: Cannot have more than 2 inputs with a Basic or
> Standard license`. Step 2, the tool's core output, failed outright for any
> user below the Advanced tier. New `_union_license_safe()` folds any number
> of inputs pairwise (Esri's own documented workaround for this error) —
> unconditionally, not gated on a licence-tier check, so behaviour is
> identical on Basic, Standard, and Advanced. 5 new regression tests assert
> no `Union` call ever carries more than 2 inputs, covering the exact
> 3-input shape that failed. See CHANGELOG_v0.54.md.
>
> v0.54.3: verification follow-up. Running `tests/verify_v0543.py` against
> ArcGIS Pro 3.7.1 confirmed the v0.54.2 speed-surface defect failed SILENTLY
> (arcpy accepted the bogus field and built a 1-class renderer — maps drew
> flat, with no warning), and exposed one regression: transparency was being
> set before `ApplySymbologyFromLayer()`, which resets it, so the surface
> rendered opaque over the basemap. Fixed, with the value in one constant.
> The v0.54.2 claim that arcpy clamps colour alpha above 100 was wrong and is
> corrected in CHANGELOG_v0.54.md.
>
> v0.54.2: pre-release audit fixes. `ccm_map_display.style_speed_surface()`
> rendered on `Condition_Number` — a field no CCM module has ever produced —
> so the speed surface (the toolbox's primary deliverable) rendered flat or
> unstyled whenever Step 3 rebuilt the map; it now applies the packaged
> `.lyrx`, with a Mobility-field renderer as fallback. Every colour table used
> a 0-255 alpha channel where arcpy's CIM dict takes 0-100, so all intended
> transparency was clamped to opaque. `build.py` shipped 17 stale files
> (including two obsolete toolboxes and a Word lock file) in the release zip;
> it now screens them out and refuses to package when a second `.pyt` is
> present. Also: the arcpy smoke test no longer aborts pytest collection, the
> `.lyrx` legends are pruned to the three classes Step 2 can emit, and layer
> names read "Speed Surface — Leopard" rather than the raw FC basename.
>
> v0.54.1: rebrand + relicense release. "MCE CCM Tool" is renamed "CCM
> Tool by Son" throughout — toolbox, all source/test files, filenames
> (`CCM_Tool_by_Son_v0.54.1.pyt` + sidecars, the release zip, the user
> manual), and every doc including historical CHANGELOGs. Project
> relicensed under SPDX-License-Identifier: GPL-2.0-or-later (previously
> "All Rights Reserved"); new copyright line: Copyright (c) 2026 Eui Soo
> SON (Beta). No functional / geoprocessing changes.
> *(Note: this entry was previously mislabelled "v0.54.4" here — a leftover
> from an earlier blanket version-string replace. Corrected in v0.54.5;
> see CHANGELOG_v0.54.1 section for the original, correctly-dated record.)*

> v0.54.0: smart CRS/projection warnings extended from Step 1's Analysis
> Extent (existing, blocking) to Step 0's Output Coordinate System, Step 1's
> supporting layers (DEM, Slope, Contours, Soil, Vegetation, Hydro — vs. the
> Analysis Extent), Step 3's Speed Surface + obstacle-detection layers, and
> Step 4's Vehicle A/B comparison (all non-blocking warnings). New shared
> `ccm_coords.geographic_crs_warning()` / `crs_mismatch_warning()` helpers.
> User Manual gains Section 3.4 (why Projected CRS / UTM is required, with a
> worked example) plus per-step data/projection callouts. 5 new tests (160
> total, 157 passed / 3 skipped).

## Release protocol (mandatory — see CLAUDE.md)

1. **Every modification = version bump**, applied to ALL files: module
   VERSION constants, .pyt filename + toolversion + xml sidecars, build.py,
   tests, README, PROJECT_STATUS, TASKS, CHANGELOG, **and the user manual**
   (title page + version-history table). Then rebuild the release zip.
2. **Every file write must be verified** — this mounted folder silently
   truncates writes. Write locally, copy in, md5-compare source vs
   destination; run `python build.py` (ast + EOF marker + pyflakes
   undefined-name scan) before calling any change done.


> v0.50.0: four verified bug fixes (Step 1 config save TypeError, hydro_fcs
> multi-value parsing, Step 3 layer indexing, Step 0 overwriteOutput), Step 2
> auto-symbology on the derived output, and the MGCP/FACC catalog:
> ccm_mgcp_catalog.py (122 codes), labelled Step 0 pick-list, theme filter,
> theme group layers, mgcp_manifest.json -> Step 1 auto-fill.

> v0.49.0 is the NG-NRMM doctrinal upgrade: Speed Made Good area-weighted CDF,
> min-of-factors speed model, MMP metric, stochastic P(GO) Monte Carlo, and
> spatial per-polygon soil moisture via Open-Meteo VWC grid.  See CHANGELOG_v0.49.md.
>
> v0.48.0 was a correctness pass: three-way soil moisture
> (the "moist" condition now uses the moist RCI column), slope field
> name/units recorded at Step 1 and honoured by Step 2 (degree->percent
> conversion), the antecedent scenario stamped on the Reason Map
> (MOIST_SCEN field), integer isochrone band labels, and several doc fixes.

---

## 1. Where the project stands

v0.49 is the NG-NRMM alignment release.  The toolbox is
end-to-end functional: Step 1 (setup/pre-process) → Step 2 (mobility map)
→ Step 3 (advanced analyses). The test suite passes without arcpy
(130 passed / 3 skipped as of v0.50.0).

### What was fixed (see CHANGELOG files for detail)
- **Rebuilt the missing Step 2 engine** (`ccm_step2_mobility.py`). An earlier build shipped
  without the core mobility-map generator: nothing produced the `SpeedKMH` speed
  surface or wrote `mobility_map_fc` to the config, so every Step 3 tool had no
  valid input. Step 2 was reverse-engineered from the downstream tools' contracts.
- **Repaired truncated/corrupted files**: `CCM_Tool_by_Son_v0.46.pyt` was cut off mid-`main()`,
  `ccm_step1_setup.py` had 238 trailing null bytes, `ccm_project_config.py` had a
  mangled footer. All files now end with `# <<< END OF FILE >>>` and verify clean.
- **Decoupled sub-tool invocation**: new `run_tool(tool, **kwargs)` in
  `ccm_project_config.py` calls tools by parameter *name*; Step 1 no longer builds
  fragile fixed-order positional parameter lists.
- **No more silently vanishing tools**: if a module fails to import, the toolbox
  registers a stub tool that displays the import error instead of dropping the tool.
- **Minor fixes**: obstacle CSV header detection now parses columns properly;
  version constants unified.

## 2. The Step 2 output contract (do not break)

Downstream tools consume these exact field names on the speed-surface FC:

| Field | Type | Consumed by |
|---|---|---|
| `Mobility` | TEXT ("GO"/"RESTRICTED"/"NO GO") | symbology .lyrx, reason map |
| `SpeedKMH` | FLOAT | isochrone, waypoints, vehicle compare |
| `F1_slope` | DOUBLE 0..1 | reason map |
| `F2_vegetation` | DOUBLE 0..1 | reason map |
| `F3_veg_spacing` | DOUBLE 0..1 | reason map |
| `F4_soil_dry` | DOUBLE 0..1 | reason map |
| `F5_soil_wet` | DOUBLE 0..1 | reason map |
| `F_hydro` | DOUBLE 0..1 | reason map |

FC naming: `speed_surface_{vehicle_tag}_{moisture}` inside the project GDB
(`ccm_project_config.find_latest_speed_surface` depends on this pattern).
Step 2 writes `mobility_map_fc`, `last_run_output`, `last_vehicles` back to
`ccm_project.json` so Step 3 auto-fills.

## 3. Open items / next steps

1. ~~Calibrate the soil RCI table~~ — MECHANISM DONE in v0.46: edit
   **`soil_rci.csv`** (per-USCS dry/moist/wet RCI) — loaded automatically,
   built-ins as fallback. Remaining: populate it with doctrinal values
   (FM 5-430-00-1 / FM 5-170 / NRMM cone-index data) and validate GO/NO-GO
   boundaries against a trusted CCM overlay for a known AOI.
   **This validation item remains the highest priority before operational use.**
2. ~~Weather wiring~~ — DONE in v0.46 + v0.49: Step 2 has "Use Live Weather",
   "Manual Rainfall Override", "Antecedent Scenario", and now "Use Spatial Soil
   Moisture" (3×3 Open-Meteo VWC grid, per-polygon moisture conditions).
3. ~~**Slope field detection**~~ — DONE in v0.48.0.
4. **Validate Step 2 in ArcGIS Pro** — SCRIPT READY: run
   `tests/arcpy_smoke_test.py` in the ArcGIS Pro Python window.
   Still needs to be EXECUTED on a licensed machine (unchanged from v0.48).
5. ~~Rename build scripts~~ — DONE in v0.46.
6. ~~Update the user manual~~ — v0.46 manual exists; **needs update for v0.49
   features** (SMG summary, min-model, stochastic P(GO), spatial moisture,
   MMP metric, new Advanced tool parameters).
7. **SMAP L4 integration** — v0.49 uses Open-Meteo ERA5 (~9 km) as the spatial
   moisture source.  NASA SMAP L4 (true 9 km, 3-hourly, with freeze/thaw layer)
   is the NG-NRMM gold standard.  Requires NASA Earthdata credentials.
   Replace `_query_open_meteo_soil()` in `ccm_weather.py` with a SMAP OPeNDAP
   client — the public interface (`bbox, n_grid → {(lat,lon): vwc}`) is stable.
8. **Direction-dependent slope speed** — NG-NRMM outputs max speed for three
   travel directions (up/down/cross-slope) via tractive-effort vs. grade-resistance
   curves.  Current F1 uses a single scalar.  Requires slope aspect layer +
   travel bearing from waypoint/isochrone tools.  Deferred to next release.
9. **MMP column validation** — `Vehicles_Can.csv` now has `mmp_kpa` values derived
   from the VCI_50 formula (Shoop 2000).  Replace with measured values from
   vehicle technical manuals (ERDC/GL-00-1 or OEM specs) when available.
10. **Split `ccm_soil_preprocess.py`** (3,900 lines) — deferred by decision.
11. **Performance backlog** from `CCM_Improvement_Research.md`: Distance
    Accumulation for isochrone/waypoints, NumPy vectorization in obstacle detect,
    multiprocessing for SoilGrids rasters, ML-based USCS classification.

## 4. How to verify the baseline

    pip install pytest
    pytest tests/test_ccm.py -v        # 107+ passed, 3 skipped expected
    python build.py                    # integrity check + builds CCM_Tool_by_Son_v<VERSION>.zip

## 5. File inventory (v0.54.7)

- `CHANGELOG_v0.49.md` — **v0.49.0 changes** (SMG, min-model, MMP, stochastic, spatial moisture)
- `CCM_Tool_by_Son_v0.54.7.pyt` — toolbox entry; registers Steps 0-4 (incl. Vehicle Compare)
- `ccm_mgcp_catalog.py` — MGCP/FACC feature-code catalog + manifest helpers (new in v0.50.0)
- `ccm_step1_setup.py` — Step 1: project setup + soil/veg pre-processing
- `ccm_step2_mobility.py` — **Step 2: mobility map / speed-surface engine (new in v0.46)**
- `ccm_step3_advanced.py` — Step 3: reason map, isochrone, compare, obstacles, route
- `ccm_map_display.py` — shared map display/symbology module (v0.51)
- `ccm_soil_preprocess.py`, `ccm_soil_validator.py` — soil ingestion → USCS
- `ccm_veg_preprocess.py` — vegetation rasters → VTI/spacing/stem diameter
- `ccm_reason_map.py`, `ccm_isochrone.py`, `ccm_waypoints.py`,
  `ccm_obstacle_detect.py`, `ccm_vehicle_compare.py` — Step 3 analysis modules
- `ccm_weather.py` — live rainfall → soil RCI adjustment
- `ccm_coords.py` — coordinate format parsing / conversion
- `ccm_project_config.py` — `ccm_project.json` read/write + `run_tool` dispatcher
- `build.py` — integrity check + zip packager (reads `VERSION`)
- `soil_rci.csv` — per-USCS dry/moist/wet RCI calibration table
- `Vehicles_Can.csv` — vehicle definitions
- `Symbology/Mobility_Symbology_Final.lyrx` — mobility layer symbology
