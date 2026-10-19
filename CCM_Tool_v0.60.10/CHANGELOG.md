# CCM Tool v0.60.10 - Changelog

## v0.60.10 - Step 3 analysis workspace repair

The v0.60.9 direct ArcGIS Pro smoke run showed that the same headless
`scratchGDB` filesystem-folder condition affected Isochrone and Vehicle
Comparison after the Step 2 hand-off was repaired. Both helpers now use the
verified speed-surface geodatabase for their intermediate feature classes.

**Verification.** The portable suite recorded 310 passed and 5 skipped
ArcPy-only tests. The direct ArcGIS Pro smoke suite passed all 7 tests after
the repair.

## v0.60.9 - Basic-licence Step 2/3 scratch-workspace repair

The v0.60.8 licensed ArcGIS Pro smoke run exposed a release-blocking
workspace defect in the Step 2 speed-surface hand-off. In a headless
`propy.bat` run, ArcGIS Pro reported `scratchGDB` as a filesystem folder;
the first pairwise Union output was therefore redirected to a shapefile-like
path and the second Union could not find the expected feature class.

`ccm_step2_mobility.py` now uses the verified project geodatabase for the
short-lived Union and clip intermediates. This keeps the Basic-licence,
Standard-licence, and Advanced-licence paths consistent and repairs the
Step 1 -> Step 2 -> Step 3 hand-off without changing the user-facing output
contract.

**Verification.** The portable suite recorded 310 passed and 5 skipped
ArcPy-only tests. The direct ArcGIS Pro smoke suite recorded all 7 tests
passed after the repair.

## v0.60.8 - Step 3 Obstacle Detection rebuilt (real Lebanon / M1 run)

Found from a real Step 3 run (Lebanon AOI, M1 moist, ArcGIS Pro Basic
licence): Obstacle Detection "succeeded" with 0 slope breaks (0 contour
pairs evaluated) and 35 CAUTION "narrow hydro crossings", all taken from the
HydroLAKES *lake polygons*.  Both results were artefacts, not terrain.

**Root causes and fixes** (`ccm_obstacle_detect.py`, rebuilt):
1. **Units.** Inputs were clipped but never projected.  HydroLAKES is WGS84,
   so `SHAPE@LENGTH` was in *degrees* and every lake (< 4 "units") passed the
   "≤ 4 m" test.  Every input is now clipped and projected to the UTM zone of
   the AOI centre before any distance/length/area is measured; output is
   written in the Speed Surface CRS.
2. **Vehicle CSV read 0 rows.** The reader looked for `vehicle_name`/`width_m`;
   `Vehicle_Data/Vehicles_Can.csv` uses `name`/`vehicle_width_m`.  Both
   spellings accepted now, plus `max_off_road_grad`.
3. **Slope threshold.** Fixed 45° replaced by the vehicle's own max off-road
   grade (M1: 54 % → 28.4°).  STOP ≥ vehicle limit, CAUTION ≥ 80 % of it.
   `VEHICLE_STOP` lists which vehicles each slope stops.  Generic 45°/60°
   only when no vehicle grade is known; a user threshold still overrides.
4. **Contour interval** auto-detected from the elevation field (was assumed
   5 m).  Near pairs on the same contour level are skipped; slope uses the
   pair's real elevation difference; obstacle point is the pair midpoint.
5. **Licence gate.** FeatureToPolygon (Standard+) is only attempted when
   `arcpy.ProductInfo()` is ArcEditor/ArcInfo; Basic goes straight to
   GenerateNearTable instead of failing with ERROR 001102 first.
6. **Hydro logic.** Lines = water gaps (width from a width attribute, else
   W = 7.2·Q^0.5 from mean discharge, Andreadis et al. 2013 — HydroRIVERS
   `DIS_AV_CMS`); wider than the ditch limit = STOP, else CAUTION, unknown
   width = CAUTION.  Polygons = water bodies (`WATER_BODY`, 4·A/P width).
   Several hydro layers accepted.  The old "feature length ≤ 4 m" test is
   gone — a line's length is not its crossing width.
7. New `SLOPE_DEG` output field; per-step timing and a type breakdown in the
   messages.  Tool wrapper gained optional `vehicle_name` and `reference_fc`
   parameters (appended — existing positions unchanged).

`ccm_step3_advanced.py`:
- Passes the vehicle (derived from the Speed Surface name, e.g. `m1`) and the
  Speed Surface as output-CRS reference to Obstacle Detection; falls back to
  the release's own `Vehicle_Data` CSV when the config path is stale.
- "Hydro / Water Feature FCs" is multi-value and auto-fills every hydro layer
  from `ccm_project.json`, stream lines first (v0.60.7 took only the first
  entry — HydroLAKES).
- Group layer no longer reads "CCM — M1 (moist) (moist)".
- `start_point` FC is only created when Reachability or Waypoint Routing ran.
- End-point marker's `COORD_INPUT` now stores the End Point text (was the
  Start Point display field, `p[19]` instead of `p[20]`).
- Tool dialog warns when a Start/End coordinate is outside the project AOI.

`ccm_map_display.py`:
- `ensure_group()` uses `Map.createGroupLayer()` (Pro 3.2+) first; the
  temp-.lyrx fallback had mismatched `layers`/`uRI` entries and is fixed.
- `style_obstacles()` styles the POINT output by SEVERITY (STOP red, CAUTION
  amber); it used to push a polygon hatch symbol onto a point layer.

`ccm_coords.py`:
- UTM display is rounded from a real WGS84→UTM projection.  Esri's
  ConvertCoordinateNotation truncates, so MGRS `37SBT3102664948` displayed as
  northing 3764947 instead of 3764948.

**Verification.** Pure-Python suite: 310 passed, 5 skipped (arcpy-only),
including 14 new tests for the helpers above.  `package_ccm.py` gate run.
**Not yet run in licensed ArcGIS Pro** — re-run Step 3 Obstacle Detection
on the Lebanon project and check the message log against
MANUAL_TEST_CHECKLIST.md "v0.60.8".

## v0.60.7 - Waypoint Route map display made briefing-legible

Requested by the user ahead of using Step 3's Waypoint Routing (Point A to
Point B fastest-route) for a military operation briefing, before having
run it even once: is the current map output easy to read for that use?
Traced the actual symbology in `ccm_map_display.py` and found it was
designed for on-screen review, not a handout.

**What it looked like before.** The route was a magenta core over a white
halo ("glow" line), named "Optimal Route", with per-feature labels off by
default. The route feature class already carries `DISTANCE_KM` and
`TIME_MIN` (computed by `ccm_waypoints.py`), but nothing displayed them on
the map -- only the attribute table. Nothing indicated direction (A vs B)
except which point was which color. The End Point used a soft red
(`[255, 80, 80, 100]`) -- easy to misread as the No-Go red this same map
reserves for impassable terrain on the speed surface underneath it.

**Fix**, all in `ccm_map_display.py`:
1. `style_route()`: core line changed from magenta to dark navy -- reads
   as a dark line under grayscale/black-and-white printing, where the
   earlier bright magenta-on-white glow tended to wash out. Added a
   directional arrowhead (CIM `CIMVectorMarker` + `CIMMarkerPlacementAtExtremities`,
   `extremityPlacement: "JustEnd"`) at the destination end, so the route's
   direction is visible from the line itself. Turned labels on with an
   Arcade expression built from `DISTANCE_KM`/`TIME_MIN` (guarded by a
   field-existence check, falling back to a plain "Optimal Route" label if
   those fields are ever absent) -- e.g. "12.4 km | 38 min" now appears
   along the route.
2. `style_point()`: End Point moved from soft red to a distinct blue,
   Start Point unchanged (gold). Both points now show an on-map "Start"/
   "End" label (from the `LABEL` field `ccm_step3_advanced.py`'s
   `_make_point_marker()` already writes) instead of relying on the
   viewer already knowing gold-vs-blue means start-vs-end.
3. `ccm_step3_advanced.py`: one call-site change, `style_route(_new_lyr)`
   -> `style_route(_new_lyr, _fc)`, so the field-existence check above has
   the route FC to look at.

Label text appearance (font size, bold) is set via the same best-effort,
wrapped-in-its-own-try/except pattern already used elsewhere in this file
-- if that arcpy.mp API surface doesn't match on the user's Pro version,
only the font tuning silently no-ops; the label expression itself (the
part that matters) is unaffected.

**Verification.** Full `pytest` -- 297 passed, 5 skipped (arcpy-only), no
regressions (this change touches only arcpy-dependent map-display code
the pure-Python suite cannot exercise). Full `package_ccm.py` gate
passed. Correctness of the CIM arrow-marker JSON and the Arcade label
expressions was checked by hand against Esri's documented CIM schema and
Arcade syntax (both are well-established patterns), not by running
ArcGIS Pro -- **not yet confirmed visually in licensed ArcGIS Pro**; the
user has not yet run Waypoint Routing even once. Worth a real run before
relying on it for an actual briefing.

## v0.60.6 - Step 1 falsely reported "complete" after Vegetation/Soil pre-processing silently failed

Found while investigating a real Step 1 failure log: running Step 1
against a project root whose `01_Input_Data` folder turned out to be
missing entirely produced a vegetation mosaic error
(`MosaicToNewRaster failed: ... does not exist or is not supported`),
immediately followed -- in the same run -- by
`[Step 1] Vegetation pre-processing complete -> ...\03_Project.gdb\veg_ccm`,
and a `veg_fc` path written into `ccm_project.json` pointing at a
feature class that was never actually created.

**Root cause.** `CCMVegPreprocessTool.execute()` (in
`ccm_veg_preprocess.py`) and `CCMSoilPreprocessTool.execute()` (in
`ccm_soil_preprocess.py`) both logged failure via `arcpy.AddError(...)`
but then returned normally instead of raising -- on a mosaic failure,
on `preprocess_vegetation()`/`preprocess_soil_data()` reporting
`result.success = False`. `ccm_step1_setup.py`'s Step 1 invokes both
sub-tools (via `ccm_project_config.run_tool()` or a positional
fallback) and neither call site ever inspected a return value; both
only distinguish success from failure by whether an exception
propagated. Since neither sub-tool ever raised, Step 1 always fell
through to its success branch -- printed "... pre-processing
complete", and wrote the *intended* output feature-class path into
`ccm_project.json` regardless of whether that feature class actually
exists. Step 1's own `except Exception as exc:` handlers around both
calls (`"[Step 1] Vegetation/Soil pre-processing failed: {exc}"`,
followed by an abort) already existed and were already correct --
they were simply unreachable dead code until this fix, because nothing
ever raised into them.

This is the same "confidently wrong" bug class as v0.60.5's Step 2
misdiagnosis: a downstream step (here, Step 2, or a later Step 1 re-run
reading the stale config) would have failed later with a confusing
"table/raster not found" error against `veg_ccm` or `soil_ccm`,
disconnected from the real cause.

**Fix.** Both `CCMVegPreprocessTool.execute()` failure sites (mosaic
failure; `preprocess_vegetation()` reporting failure) and
`CCMSoilPreprocessTool.execute()`'s one failure site
(`preprocess_soil_data()` reporting failure) now `raise
RuntimeError(...)` with the same message already logged via
`arcpy.AddError()`, instead of returning normally. No change was
needed in `ccm_step1_setup.py` -- its existing try/except handlers
around both calls now correctly catch these exceptions and abort Step
1 with an honest failure message instead of a false "complete".
Audited both files for any other site following the same
log-then-return-without-raising pattern inside a Pro tool `execute()`;
none found beyond the three fixed here. (Step 1's own DEM/Slope-Regions
derivation already had this right: it explicitly catches its own
exceptions and falls back to a documented "flat terrain" assumption
with an `arcpy.AddWarning()`, rather than claiming a slope surface was
produced when it wasn't -- left unchanged.)

Also cleaned up an incidental `DeprecationWarning: invalid escape
sequence '\V'` from a plain (non-raw) docstring in
`ccm_step2_mobility.py` (introduced in v0.60.5) -- a literal Windows
path in prose text, switched to forward slashes since it was
documentation, not an actual path being interpreted.

**Verification.** Full `pytest` suite -- 297 passed, 5 skipped
(arcpy-only), no regressions, and the stray `DeprecationWarning` is
gone. Full `package_ccm.py` gate (`static_checks()`,
`data_calibration_audit()`, `validate_end_to_end()`) passed. The raise
paths themselves are arcpy-dependent (`CCMVegPreprocessTool.execute()`
and `CCMSoilPreprocessTool.execute()` both call `arcpy.AddMessage` /
`arcpy.Exists` throughout) and so cannot be exercised by the
pure-Python test suite; confirmed correct by tracing every call site
and control-flow path by hand instead. **Not yet confirmed in licensed
ArcGIS Pro** -- the user's own most recent Step 1 run (against a
project root missing its `01_Input_Data` folder) is a live vegetation
mosaic failure and would be a natural real-world confirmation if
re-run against v0.60.6: it should now produce a clean
`[Step 1] Vegetation pre-processing failed: ...` and abort, rather than
the false "complete" seen under v0.60.5.

## v0.60.5 - Step 2's "Vehicle CSV not found: None" misdiagnosed a project that had simply never run Step 1

Reported by the user running Step 2 (Generate Mobility Map) against a
real project: `[Step 2] Mobility map generation failed: Vehicle CSV not
found: None`, even though `01_Input_Data\Vehicle\Vehicles_Can.csv`
genuinely existed on disk. The v0.60.2 guard that was supposed to catch
this class of problem (`if not project_gdb: raise "...Step 1 has not
been run..."`) never fired, because -- it turns out -- `project_gdb` is
no longer proof Step 1 ran: `ccm_step0_mgcp.py`'s
`_apply_project_root_layout()` writes `project_gdb` into
`ccm_project.json` as soon as a Project Root Folder is set in the
**Step 0** dialog, at `updateParameters()` (validation) time -- before
Step 0 even executes, let alone Step 1. Inspecting the user's actual
`ccm_project.json` confirmed it: `project_gdb` was set (Step 0 and Step
0b had both run), but `extent_fc`, `soil_fc`, `veg_fc`, `hydro_fcs`, and
`vehicle_csv` were all still empty -- Step 1 (Project Setup &
Pre-process) had simply never been run against that project root, and
the error message never said so.

`build_speed_surface()`'s prerequisite checks are now driven by
`extent_fc` instead: it is Required with no auto-populated default
(unlike `vehicle_csv`, which Step 1's own dialog pre-fills from this
tool's bundled fleet CSV), so it is only ever non-empty once Step 1 has
actually executed successfully. The checks are also pulled out into a
standalone, arcpy-free `diagnose_step2_prerequisites()` function so this
logic is unit-testable on its own rather than only reachable through a
licensed ArcGIS Pro run -- verified directly against three scenarios
(Step 1 never run; Step 1 ran but the CSV is genuinely missing; everything
present) before this release's pytest/package gate ran at all.

### Verification

Direct unit exercise of `diagnose_step2_prerequisites()` against all
three scenarios above (arcpy-free). `python -m pytest tests/test_ccm.py
tests/test_v050.py tests/test_v057_data_intelligence.py
tests/test_ccm_step0b_integration.py test_single_root_pure_python.py` --
297 passed, 5 skipped (arcpy-only). Full `package_ccm.py` gate --
`static_checks()`, `data_calibration_audit()`, `validate_end_to_end()` --
all pass. Licensed ArcPy smoke tests (`RUN_ARCGIS_SMOKE_TEST.bat`) not
yet re-run against this specific release; v0.60.4 (identical apart from
this one function) passed all 7 in the user's environment.

## v0.60.4 - Coverage-confidence fabrication and stale self-identification strings

A short, targeted patch prompted by an independent review of the
Step 0c reprojection-tool design: it flagged two defect classes still
present in v0.60.3 despite the v0.60.3 pass, one of which turned out to
have a second, unreviewed instance. Nothing here changes scan behaviour
for a dataset whose AOI coverage was actually measured -- only the
handling of "never measured" changes.

### 1. Unmeasured AOI coverage was still fabricated as 50.0 in two more places

v0.60.3 fixed the coverage fabrication in the factual-record normalization
path (`ccm_step0b_integration.py`), but two more call sites independently
did the exact same thing and were missed at the time:

`ccm_step0b_integration.py`'s confidence-building loop (feeding
`ConfidenceScorer.score_role_confidence()`) substituted `coverage = 50.0`
whenever a role's best candidate had no measured `coverage_aoi_pct`,
which put every unmeasured candidate at exactly the "Low" confidence
threshold -- a specific, printed confidence level resting on a coverage
fact nothing had evaluated. `ccm_data_selector.py`'s composite
recommendation scorer did the same for the same reason, folding the
fabricated 50% into the weighted score AND printing an invented
"50% coverage" in the recommendation reason text and HTML report.

`coverage_pct` is now passed through as `None` (a fact: "not measured")
instead of being guessed at. `ConfidenceScorer.score_role_confidence()`
treats a `None` coverage as a hard cap at "Low" -- known-good
quality/fitness is not thrown away, but "High"/"Moderate" specifically
certify a *measured* >=95%/>=80% AOI overlap, so unmeasured coverage
cannot earn either. `ccm_data_selector.py`'s composite score drops the
coverage term entirely when unmeasured and redistributes its weight
proportionally across quality/fitness/confidence, instead of scoring a
guessed number; its recommendation text and HTML report now say
"coverage not measured" rather than a fabricated percentage. Verified
against a real end-to-end scan of the pure-Python fixture data: the
non-spatial Vehicle role (no AOI overlap to measure) now shows
`coverage_pct: null` and is capped at "Low" confidence, where it
previously showed a fabricated `50.0`.

### 2. Stale "v0.59.6" (and older) version strings in emitted/user-visible text

`bump_version.py` only ever rewrote `VERSION = "X.Y.Z"` assignments and
renamed files. A version number quoted inside a module docstring header
("CCM Tool v0.59.6 -- ..."), a printed status line
("[OK] Step 0b v0.59.6 complete"), an argparse `--help` description, the
recommendations HTML report's own `<title>`/`<h1>`/footer, or a `.bat`
launcher's banner line is none of those, so several of these had quietly
kept an old release number for multiple releases (some since v0.59.6,
one launcher banner since v0.60.1) even though the same file's real
`VERSION` constant, filename, and actual emitted JSON `"version"` field
were all correctly bumped every time. Fixed in
`ccm_data_confidence.py`, `ccm_data_fitness.py`, `ccm_data_quality.py`,
`ccm_data_readiness.py`, `ccm_data_selector.py`, `ccm_step0b_integration.py`,
`ccm_step0b_intelligence.py`, `ccm_step1_recommendations_ui.py`,
`ccm_project_init.py`, and the `CCM_Data_Scanner.bat` /
`CCM_anaconda.bat` / `RUN_ARCGIS_SMOKE_TEST.bat` / `RUN_DATA_SCAN.bat` /
`RUN_TESTS.bat` / `TEST_CRS_FIX.bat` launchers. Genuine historical
comments ("# v0.54.4 -- fixed the ... defect") describing when a past
behaviour changed were deliberately left alone.

To keep this from recurring, `bump_version.py` now also rewrites these
same known self-identification shapes (in both `.py` and `.bat` files)
on every future bump, and `package_ccm.py`'s `static_checks()` gained a
new `check_no_stale_self_versioning()` release-gate check that fails the
build if any of them still names an old version. Both are intentionally
narrow -- specific known shapes, not "any old version number anywhere"
-- because the codebase has many legitimate historical comments and test
fixtures that must never be rewritten; an early broader pattern was
tried and reverted after it flagged test fixture data and historical
narrative comments as false positives. Verified by bumping a scratch
copy from v0.60.4 to v0.60.5 and confirming every known site updated
automatically with the new check passing cleanly afterward, then
reverting the scratch copy.

### Verification

`python -m pytest tests/test_ccm.py tests/test_v050.py
tests/test_v057_data_intelligence.py tests/test_ccm_step0b_integration.py
test_single_root_pure_python.py` -- 297 passed, 5 skipped (arcpy-only).
`package_ccm.py`'s `static_checks()`, `data_calibration_audit()`, and
`validate_end_to_end()` (real fixture generation + full integrated scan)
all pass. Licensed ArcPy smoke tests still need to run in ArcGIS Pro
before this is called release-final.

## v0.60.3 - Data Intelligence Scan: false "no data" / false "Error" findings

Triggered by a user report: running the standalone Data Intelligence Scan
(``CCM_Data_Scanner_GUI.py``) against a fully-populated, correctly-prepared
Lebanon project (real DEM tiles, real HWSD2 soil, real ESA WorldCover
tiles, real HydroLAKES/HydroRIVERS, a real Vehicles_Can.csv and a real
AOI) still produced a dashboard full of red "Error" badges and a
"Model confidence: At-Risk" verdict that the data did not deserve. None of
these were scanner crashes -- the scan always completed and returned
"status: success" -- they were wrong or misleadingly-labelled findings
inside a report that looked correct at a glance.

### 1. Every subfolder's README.txt was catalogued as analyst data

`.txt` is in `TABLE_EXTS`, so every `README.txt` that
`Project_Root_Folder_Template` ships in each of its `01_Input_Data`
subfolders (DEM/, Soil/, Vegetation/, Hydro/, Contours/, Extent/, MGCP/,
Vehicle/) was picked up as a "table" dataset under that folder's role.
This inflated every role's dataset count by exactly one (11 real DEM
tiles reported as "DEM / Elevation (12)"), ran the Vehicle role's
CSV-schema check against Vehicle/README.txt instead of only
Vehicles_Can.csv (producing a spurious "Missing expected field(s): name,
vci_1, ..." limitation on a plain-English readme), and gave every role a
"no CRS / no accuracy" record that dragged its quality average down for
no reason. `ccm_data_catalog.py` now recognises README/LICENSE/CHANGELOG/
etc. by filename stem, regardless of the folder they sit in, and excludes
them from the catalogue the same way the scanner's own report outputs
already were (v0.59.7).

### 2. HWSD2.hdr / HWSD2.stx reported as "2 unclassified files"

`read_geotiff_header()` only understands classic GeoTIFF IFD tags, so it
returns nothing for `.bil` (ESRI BIL/BSQ/BIP), which stores cell size and
raster dimensions as plain "KEY value" text pairs in a separate `.hdr`
sidecar -- an entirely different format. `HWSD2.bil` therefore got a CRS
(the `.prj` sidecar was already read) but never a resolution, and its
`.hdr`/`.stx` sidecars fell through to "other" -> unclassified, appearing
in every report as unexplained stray files next to a perfectly good
raster. Added `read_esri_bil_hdr()` and wired it into `probe_raster()`;
`.hdr`/`.stx` are now recognised as BIL sidecars and no longer catalogued
as their own datasets.

### 3. CRS quality score: WGS84 UTM (the correct CRS) scored as Geographic

`_score_crs_compatibility()` in `ccm_data_quality.py` had four confirmed
defects, all caught by running it against this project's own real CRS
strings: (a) a dead branch, `"EPSG:3" in crs.split(":")[0]`, that can
never be True since `split(":")[0]` is always the literal text "EPSG";
(b) the "WGS" keyword check ran *before* the "UTM" check, so
`WGS_1984_UTM_Zone_36N` -- the correct CRS for this AOI -- matched "WGS"
first and scored 5.0 (Geographic) instead of 10.0 (Projected); (c)
`EPSG:3857` (Web Mercator, which *is* projected) matched neither the
EPSG:32xxx nor EPSG:4xxx patterns and fell through to 0.0 ("unknown");
(d) a bare EPSG integer with no "EPSG:" prefix also fell through to 0.0.
Rewritten to check the EPSG numeric code first (wherever it appears in
the string) and to check projection keywords before the generic
geographic keywords.

### 4. Fabricated 50% AOI coverage, then a downstream crash once removed

`ccm_step0b_integration.py` set `coverage_pct = 50.0` whenever coverage
had not actually been measured (most commonly: no AOI was supplied to the
scan yet, a normal and explicitly supported state for Step 0b). That
silently scored as "aoi_coverage: 4.0 (<50%, action required)" while the
same report, one section down, correctly said "AOI coverage: not measured
[N/A]" for the identical record -- a direct self-contradiction, and the
`ccm_data_quality` docstring's own promised "Unknown = 5 (neutral)" path
was unreachable because `coverage_pct` was never really `None` by the
time it got there. Removed the fabrication; `coverage_pct` now stays
`None` when genuinely unmeasured. This surfaced a real, separate bug in
`ccm_data_selector.py`: `candidate.get("coverage_pct", 50.0)` only
supplies its default when the *key* is absent, not when the value is an
explicit `None` -- since the key is always present now, this line always
returned `None`, and `coverage / 100.0` two lines later crashed the
entire recommendations phase with `TypeError: unsupported operand
type(s) for /: 'NoneType' and 'float'` for any scan run without an AOI.
Fixed to treat `None` as "supply the default", same as the key being
missing. (`ccm_data_fitness.py` has two similar `.get(..., N)` call
sites; both already wrap the result in `float(...)` inside a
`try/except (ValueError, TypeError)`, so `None` degrades to `0.0` there
without crashing -- left as-is.)

### 5. Composite quality score: 10/10 was structurally unreachable

`duplication_penalty` (0, or negative per duplicate copy) and
`metadata_presence` (a +0..+10 bonus) were averaged into the same list as
the six real 0-10 quality metrics, as if they were quality measurements
in their own right. A dataset that was perfect on every real metric, had
no duplicate copies and full metadata still capped out at 8.62/10 --
the zero penalty and the non-maximal-looking bonus both dragged the mean
down. `score_dataset()` now takes the mean of the six base metrics only,
then applies the penalty and bonus on top of that mean (matching what
their own docstrings already say they are), before clamping the total to
[1, 10]. `crs_compatibility` and `horizontal_accuracy` now also return
`None` (not 0.0/0.0) for a non-spatial dataset (a plain table has neither
a CRS nor a horizontal accuracy to speak of), excluding them from the
base mean for that record instead of penalising it for a property it was
never expected to have -- `_build_reasoning()` updated to guard the now-
possible `None` instead of comparing it with `>=`/`<=`, which would have
raised `TypeError` for every table record (`Vehicles_Can.csv`, every soil
attribute `.dbf`, etc.).

### 6. The "Error" column/badge renamed to "Compatibility"

This was the direct cause of the report reading as "full of errors" when
nothing had failed. The dashboard's compact per-role line printed a raw
`error=YELLOW` field, and the HTML/TXT per-record detail carried an
"Error" badge, for what the column actually measures: source-format
compatibility (native / needs conversion / duplicate copies /
limitations noted) -- not a scan failure. A routine "needs conversion"
yellow badge is not an error, and labelling it one made every scan of
perfectly good, unprojected source data look broken. Renamed in every
place an analyst sees it (TXT dashboard field, HTML dashboard chip, HTML
per-record badge, and the module docstring's own legend); the internal
`row["error"]` dict key is unchanged; no `ccm_*.json` schema changed.

### 7. Reasoning string printed the unrounded composite score

Cosmetic: `_build_reasoning()`'s returned string showed the raw float
(e.g. "9.166666666666668/10") next to a `"quality_score": 9.17` in the
same JSON record. Now formatted to 2 decimal places, matching.

### Verification

Re-ran the standalone scan (arcpy disabled, matching how
`CCM_Data_Scanner_GUI.py` actually runs) against the reporter's real,
fully-populated Lebanon project. Before this release: `datasets_catalogued:
26` (8 of them README.txt copies), `unclassified: 2` (HWSD2.hdr/.stx),
quality average masked by the bugs above, "Model confidence: At-Risk",
recommendations phase reaching only 0-4/7. After: `datasets_catalogued:
19` (exactly the real data files), `unclassified: 0`, quality average
9.19/10 (ceiling of 10.0 now reachable and reached), "Model confidence:
Acceptable", recommendations 4/7 auto-selected, dashboard reads
`compat=` instead of `error=`. The full existing suite (`test_ccm.py`,
`test_v050.py`, `test_v057_data_intelligence.py`,
`test_ccm_step0b_integration.py`, `test_single_root_pure_python.py`) --
297 passed, 5 skipped, 0 failed -- was re-run after every code change in
this release with no regressions.

Standing, unresolved from this same investigation (not a code defect --
an analyst action item, left for the analyst to act on): every dataset in
this project is in a Geographic CRS (EPSG:4326 / GCS_WGS_1984); CCM
requires a Projected CRS before Step 1. The report already flags this
correctly, per-record, as "Geographic CRS -- CCM requires a Projected
CRS". For a Lebanon AOI the recommended target is EPSG:32636 (WGS 84 /
UTM zone 36N).

## v0.60.2 - Cross-step state leaks, config contract, and release tooling

A review pass over the whole Step 0 -> 0b -> 1 -> 2 -> 3 workflow. Seven
defects, none of which raised an error where they were introduced: four
of them produced either silently wrong output or a message that named
nothing useful, and one (the seventh) was in the fix for another entry
on this same list, caught only by running the new arcpy smoke test for
real in ArcGIS Pro rather than by any static check.

### 1. arcpy.env.mask leaked out of Step 1 into the rest of the session

ccm_veg_preprocess.py set `arcpy.env.mask = extent_fc` at four sites and
never cleared it. Those four assignments were the only occurrences of
`env.mask` in the entire project -- there was no reset anywhere and no
try/finally. ArcGIS Pro shares one Python process across every open tool
(the toolbox entry point already compensates for this when reloading
modules), so once Step 1 ran vegetation preprocessing, every later
Spatial Analyst call in that session -- Step 2's speed surface, Step 3's
isochrones and reason maps -- stayed silently clipped to that AOI. An
analyst who then switched AOI, or opened a second project without
restarting Pro, got output masked to the PREVIOUS project's extent with
no warning of any kind. All four sites now save the prior mask and
restore it in `finally`. The assignments are kept rather than deleted
because `ZonalStatisticsAsTable` at two of the sites genuinely reads the
environment mask, so removing them would have changed results.

ccm_soil_preprocess.py had the same bug in milder form: its
`arcpy.env.extent = None` reset sat inside the `try`, so any
ExtractByMask or save failure -- the exact case its own `except` branch
handles and continues past -- left `env.extent` pinned for the rest of
the session. The reset moved into `finally`.

### 2. "Project GDB not found: None"

The reported Step 2 failure. Step 0b records `data_root` and its
catalog/score paths but never `project_gdb`, and `save_config()` merges
`_DEFAULTS`, which materialises the absent key as `None`. Any project
where Step 0b ran before Step 1 therefore held a ccm_project.json that
failed Step 2 with a message naming only the word "None".

`build_speed_surface()` now separates the two real cases and names the
cause and the fix for each: no GDB recorded at all (Step 1 never ran
against this root), versus a GDB recorded but absent from disk (the
folder was moved or copied, so Step 1's absolute paths no longer
resolve). This matters beyond the dialog, because
`build_speed_surface()` is also reached from `run_tool()` and the test
suites, where no dialog validation runs.

The Step 2 dialog guard that detects this case was additionally
requiring `cfg["data_root"]` to be set -- an incidental property of how
Step 0b happens to write, not a test of the condition. A config with
neither `project_gdb` nor `data_root` fired neither that branch nor the
`elif` below it, so the dialog said nothing at all. It now tests absent
`project_gdb` directly, which is what the condition actually is.

### 3. project_root and project_folder could silently diverge

`save_config()` documented that it keeps `project_root` in lock-step
with `project_folder`, but filled `project_root` only when it was empty.
Copy or move a project folder, then let any writer that does not pass
`project_root` explicitly touch it (Step 0b does not), and
`project_folder` pointed at the new location while `project_root` -- and
the `project_gdb` derived from it -- still pointed at the old one. Step 2
would then read and write the PREVIOUS project's geodatabase without
warning. An explicit `project_root=` argument still wins; otherwise it
now tracks the folder the config is actually being written to.

### 4. bump_version.py orphaned every per-tool metadata sidecar

ArcGIS Pro keeps each tool's own description and parameter help in
`<toolbox stem>.<ToolClassName>.pyt.xml`. `rename_toolbox_files()`
renamed the toolbox and its toolbox-level sidecar but not these four, so
after every release they kept the previous version in their names, no
longer matched the renamed .pyt, and Pro showed those tools with no
description or help at all. They are now renamed alongside the toolbox.

### 5. A release test that could not detect what it tested

`package_ccm.release_files()` excluded pytest runtime folders by the
prefix `_pytest_`, but `run_verification()` creates its basetemp as
`pytest_tmp_<timestamp>` -- no leading underscore -- so that guard never
matched. It was masked only because those folders live under
`verification_artifacts/`, which is excluded by name.
`test_release_package_excludes_pytest_runtime_folders` asserted on the
same wrong prefix, so it passed trivially and would have kept passing
even if those folders were packaged. Both spellings are now handled, the
test asserts on the real names, and a second test pins the basetemp
naming so the two cannot drift apart again.

The same function also called `path.is_file()` on every entry of
`ROOT.rglob("*")` BEFORE the exclusion test ran, so excluded trees were
still fully descended into and a single unreadable entry anywhere under
the project root aborted the release with a bare OSError naming no step
-- observed in practice on a stale verification_artifacts tree. It now
walks with directory pruning and guards the stat. `.log` was added to
the excluded suffixes: the pure-python suite writes its run log into the
project root, and it was being swept into the release zip.

### 6. Documentation and language

The toolbox header still read "CCM_Tool_v0.59.6.pyt" / "v0.57" several
releases after the fact, because no bump touched it. The release number
is no longer repeated there; it lives in ccm_version.py, which
bump_version.py does rewrite.

All remaining Korean text was translated to English: the
Project_Root_Folder_Template README set (10 files), one quoted bug
report in MANUAL_TEST_CHECKLIST.md, and a redundant parenthetical gloss
in ccm_weather.py's Spring Thaw scenario. Docs and code in this project
are English-only from this release onward.

### 7. The Step 2 dialog's own error/warning messages could overwrite each other

Found after the fixes above were written, when the user ran the new
tests/arcpy_smoke_test_v0602_fixes.py for real in ArcGIS Pro: Section 3
(a project missing project_gdb entirely -- the same "Step 1 never
completed" case fix #2 above names) came back with a WARNING instead of
the expected ERROR.

An arcpy.Parameter has a single .message slot; calling
setWarningMessage() after an earlier setErrorMessage() on the SAME
parameter silently replaces it -- last call wins. CCMStep2MobilityTool's
updateMessages() ran four checks against p_folder as a mix of if/elif
plus two more UNCONDITIONAL checks below them (a vehicle_csv-moved
check, then a missing-layers check). The fix in #2 above correctly set
the "Step 1 never completed" ERROR, but the unconditional missing-layers
check below it still ran, found soil_fc/veg_fc/slope_fc all absent (true
of any config missing project_gdb), and its WARNING silently overwrote
the ERROR -- so the dialog told the analyst "some layers are missing,
re-run Step 1" instead of naming the real problem (this folder was never
run through Step 1 at all).

This was a pre-existing hazard, not one introduced by this release's
other fixes: tests/arcpy_smoke_test_v060_single_root.py already worked
around it by engineering its fixtures to keep missing_layers empty
(explicit placeholder soil_fc/veg_fc/slope_fc in Scenarios B, C, and the
negative-control Project D) rather than fixing the ordering. It only
surfaced now because arcpy_smoke_test_v0602_fixes.py's Section 3 builds
the minimal config fix #2 is actually about, with nothing set at all.

The four checks are now one if/elif/elif/else chain, so exactly one
message can ever win, in priority order: Step 1 never completed (error),
then vehicle_csv never recorded (warning), then vehicle_csv path stale
(error or warning depending on whether this install's bundled CSV covers
it), and only when none of those three applies, the missing-layers
warning. A genuinely healthy project -- valid project_gdb, resolvable
vehicle_csv -- is the only config that can still reach the last branch,
so that warning can no longer mask a worse problem underneath it.

### Verification

  pyflakes, all 55 files          0 undefined names
  ast parse, all 55 files         0 syntax errors
  test_single_root_pure_python    45/45 pass
  pytest (4 suites)               297 passed, 5 skipped, 0 failed
  arcpy_smoke_test_v0602_fixes.py 25/25 pass in ArcGIS Pro (real run,
                                  after this fix -- including the
                                  "Fix 2 (dialog)" check that failed
                                  before it, now passing)

Every check in that suite, including fix #7 above, is now confirmed by
a real ArcGIS Pro run, not just static analysis. The remaining
arcpy-dependent paths not covered by that suite (Steps 0/1/3 end to
end) still rely on MANUAL_TEST_CHECKLIST.md.

## v0.60.0 - Single-root project architecture

Steps 0, 0b, 1, 2 and 3 each asked for their own folder, independently
typed, with nothing carrying context from one step to the next:
Output Geodatabase (Step 0), Data Root Folder (Step 0 and, separately,
Step 0b and Step 1), Project Folder (Step 0b, optional), Project Output
Folder (Step 1), and Project Folder again (Step 2, Step 3). The only thing
meant to tie them together, ccm_project.json, was reachable only by
re-typing a path at every step -- nothing auto-navigated from one step's
output to the next step's input, and Step 0b's optional Project Folder
silently defaulted to Data Root Folder's PARENT when left blank, a
location nobody chose. Two different tools wrote two different, disjoint
key sets to a file with the same name (ccm_project_config.save_config()
in Step 1; a private json.load/json.dump pair in Step0bIntegrator.run()
that never set project_gdb or vehicle_csv), so whichever ccm_project.json
Step 2/3 happened to be pointed at decided whether the pipeline had
anything to work with. This is the same failure mode already patched in
v0.59.7 for one specific case (a Step 2 Project Folder pointed at a Step
0b config instead of a Step 1 config, e.g. the AOI_Lebanon path mismatch)
-- v0.60.0 removes the pattern itself instead of patching individual
symptoms of it.

- Every step now takes ONE Project Root Folder parameter (`project_root`)
  instead of a separate folder per step. Step 0 auto-creates the shared
  layout -- `01_Input_Data`, `02_Scan_Index`, `03_Project.gdb` -- and writes
  `project_root` / `data_root` / `scan_index_dir` / `project_gdb` into
  ccm_project.json as soon as a valid root is set (at dialog-validation
  time, not only at execute()), so the file and the folders exist even if
  the analyst only runs Step 0 and stops. Step 1 reuses the GDB Step 0
  already created instead of erroring or recreating it -- either step can
  now run first. (ccm_step0_mgcp.py, ccm_step1_setup.py,
  ccm_project_config.py)
- Step 0b takes the same Project Root Folder parameter. It scans
  `<root>/01_Input_Data` when that layout already has data in it, and
  falls back to scanning the root directly otherwise, so it still works
  standalone as the very first tool someone runs against a folder with no
  CCM structure yet. Its Project Folder field is now an advanced override
  that defaults to the project root -- the "defaults to Data Root's parent"
  behavior is gone. (ccm_step0b_intelligence.py)
- Step0bIntegrator.run() writes ccm_project.json through the canonical
  ccm_project_config.save_config() (a real read-merge-write) instead of a
  private json.load/json.dump pair, so its keys and Step 1's keys land in
  the same file regardless of which step ran first, instead of two
  incompatible files in two different folders. Scan artifacts (catalog,
  quality/fitness/confidence/readiness scores, recommendations, HTML
  reports) now write into `<root>/02_Scan_Index/` rather than directly
  into the project root, so they no longer sit next to -- and could not
  previously be confused with -- ccm_project.json itself.
  (ccm_step0b_integration.py)
- Step 2's Vehicle dropdown no longer goes silently empty. Before this
  fix there were three failure modes: (A) a Step 0b config with no
  vehicle_csv at all -- already diagnosed with an error in v0.59.7; (B) a
  vehicle_csv path recorded by a previous install that no longer resolves
  -- v0.59.7 added a warning claiming a fallback to the bundled fleet CSV,
  but never actually implemented the fallback, so the dropdown stayed
  empty regardless; (C) a genuine, otherwise-valid Step 1 config where
  vehicle_csv was simply never recorded or was cleared -- project_gdb IS
  present, so case (A)'s check doesn't fire, and vehicle_csv is falsy, so
  case (B)'s check doesn't fire either -- this one had NO error, NO
  warning, nothing, and is the most likely cause of a dropdown that shows
  up completely empty with no explanation. All three cases now populate
  the dropdown from this install's bundled fleet CSV as a fallback, and
  case (C) now raises the warning it was always missing.
  (ccm_step2_mobility.py)
- New standalone Project Initializer: ccm_project_init.py opens a
  Tkinter folder picker, creates the single-root layout, and writes the
  initial ccm_project.json -- the "run a script, a GUI opens, pick your
  root folder" tool. Works without arcpy (creates 03_Project.gdb only if
  arcpy happens to be available; otherwise Step 0 or Step 1 creates it
  inside ArcGIS Pro). build_project_init_exe.py freezes it into
  dist\CCM_Project_Init.exe via PyInstaller, mirroring build_exe.py's
  existing CCM_Data_Scanner build. (ccm_project_init.py,
  build_project_init_exe.py)
- CCM_Data_Scanner_GUI.py (the standalone Data Intelligence Scan
  tool/exe) now runs the same Step0bIntegrator pipeline the in-Pro Step 0b
  tool runs -- quality/fitness/confidence/readiness scoring and
  recommendations, not just the bare factual catalog it built on its own
  before. Its Reports-folder default no longer falls back to the data
  root's parent; pointed at a project's 01_Input_Data folder it now
  defaults to that project's 02_Scan_Index, matching where Step 0b and
  ccm_project_init.py already put scan output. build_exe.py's hidden-
  imports list grew to match (ccm_step0b_integration, ccm_data_quality,
  ccm_data_fitness, ccm_data_confidence, ccm_data_readiness,
  ccm_data_selector), so CCM_Data_Scanner.exe freezes the same pipeline
  rather than the older, thinner one. (CCM_Data_Scanner_GUI.py,
  build_exe.py)
- The ArcGIS Pro toolbox label no longer drifts from the real release
  version. `toolversion` in the .pyt file was a separate hardcoded literal
  that bump_version.py's project-wide `VERSION = "..."` rewrite never
  touched (different variable name), and had silently fallen a full patch
  release behind -- the toolbox showed "v0.59.6" while the code underneath
  was already v0.59.7. It now imports VERSION from ccm_version.py, the
  project's single source of truth, and cannot drift again.
  (CCM_Tool_v0.60.0.pyt)

## v0.60.1 -- Verification, launcher fix, and first packaged release

- Verification: test_single_root_pure_python.py (new, no arcpy required)
  exercises every pure-Python part of this rewrite end to end -- config
  round-tripping, the standalone Project Initializer, a full
  Step0bIntegrator scan against real synthetic fixture data, and
  package_ccm.py's own validate_end_to_end() self-check -- and reports
  45/45 checks passing. MANUAL_TEST_CHECKLIST.md walks through
  the arcpy-dependent parts (Steps 0/1/2/3 inside ArcGIS Pro) that only
  a licensed session can exercise, including all three Vehicle-dropdown
  scenarios above.
- This verification pass also caught and fixed three regressions the
  parameter rename itself introduced, none of which were reported by
  the user -- found by re-running the project's own arcpy smoke tests
  against the renamed parameters: (1) tests/arcpy_smoke_test_step1.py
  and tests/arcpy_smoke_test_step3.py called run_tool() with the old
  `project_folder=` keyword, which now raises KeyError against Step 1
  and Step 3's renamed `project_root` parameter -- fixed to pass
  `project_root=`. (2) tests/arcpy_smoke_test_step1.py's own GDB-created
  assertion still checked for the old CCM_Project.gdb name instead of
  the new 03_Project.gdb -- fixed to resolve the GDB from
  ccm_project.json's project_gdb key, the same way production code does.
  (3) ccm_step3_advanced.py's _derive_output_path() fallback (used when
  a Step 3 result's own workspace is missing) still looked only for
  CCM_Project.gdb by that literal name, so a brand-new v0.60.0 project's
  03_Project.gdb was never found and derived outputs would have silently
  landed in arcpy.env.scratchGDB instead -- fixed to resolve project_gdb
  from ccm_project.json first, falling back to either GDB name on disk.
  Step 2's "folder holds a Step 0b scan, not a Step 1 project" error
  message was also updated to stop citing the old CCM_Project.gdb name.
  (tests/arcpy_smoke_test_step0.py also gained explicit assertions for
  the new single-root layout/config-write behavior it previously never
  checked at all.) (ccm_step2_mobility.py, ccm_step3_advanced.py,
  tests/arcpy_smoke_test_step0.py, tests/arcpy_smoke_test_step1.py,
  tests/arcpy_smoke_test_step3.py)
- Added tests/arcpy_smoke_test_v060_single_root.py (new, requires a
  licensed ArcGIS Pro session), the licensed-arcpy counterpart to
  test_single_root_pure_python.py above. It is the first test in this
  project to drive updateParameters()/updateMessages() directly without
  calling execute() -- every prior arcpy smoke test only ever exercised
  the run-and-execute path via ccm_project_config.run_tool(), so
  dialog-time behavior (auto-filled defaults, the Vehicle dropdown,
  live validation messages) had never been automatically tested before.
  It covers Step 0's dialog-time single-root layout creation, all three
  Vehicle-dropdown scenarios from MANUAL_TEST_CHECKLIST.md plus
  a Step 0b-only negative control, and Step 3's _derive_output_path()
  GDB-resolution fallback across four scenarios (config-first,
  03_Project.gdb on disk, legacy CCM_Project.gdb on disk, neither).
  Wired into RUN_ARCGIS_SMOKE_TEST.bat and
  MANUAL_TEST_CHECKLIST.md. (tests/arcpy_smoke_test_v060_single_root.py,
  RUN_ARCGIS_SMOKE_TEST.bat, MANUAL_TEST_CHECKLIST.md)
- Fixed: RUN_ARCGIS_SMOKE_TEST.bat crashed at startup, before any test
  could run, with `%\ArcGIS\Pro\bin\Python\Scripts\propy.bat was
  unexpected at this time.` -- a cmd.exe batch-parser error, not an
  ArcGIS or Python error, caused by two layers of the same underlying
  mistake. First, %ProgramFiles(x86)% (and the literal "(x86)" text in
  the fallback error message) was referenced directly inside a
  parenthesized FOR/IF block -- cmd.exe's block parser scans for
  matching parentheses to find where a (...) block ends BEFORE it
  expands %VARS%, so the parentheses inside that variable's own NAME
  were miscounted as block delimiters. Fixing that (copying
  %ProgramFiles%, %ProgramFiles(x86)%, and %LOCALAPPDATA% into
  paren-free variable names PF_64 / PF_86 / PF_LOCAL before entering
  any FOR/IF block) cleared the startup crash but exposed the same bug
  one layer deeper: `call "%PROPY%" ...` inside the
  `for %%T in (step0 step1 step2 step3 v060_single_root) do (...)`
  loop body used immediate (non-delayed) %PROPY% expansion, and
  PROPY's resolved value -- found under "C:\Program Files (x86)\..."
  on the user's machine -- reintroduced the identical
  parenthesis-vs-block-parsing conflict, this time from the variable's
  expanded VALUE rather than its name. Fixed by switching every
  in-block reference to PF_64 / PF_86 / PF_LOCAL / PROPY to delayed
  expansion (!VAR!, already enabled via EnableDelayedExpansion in this
  script) -- delayed expansion resolves at each line's actual
  execution time, after the block's structure is already settled, so a
  paren-bearing value (whether from a variable's name or its value)
  can no longer confuse the parser. Top-level (unblocked) %PROPY%
  references -- the step0b and step0b_integrated calls, and the
  "Using propy.bat" banner -- were left as immediate expansion since
  they carry no such risk. Confirmed fixed against the user's real
  ArcGIS Pro install: all 7 licensed smoke tests now run and pass
  (step0, step1, step2, step3, v060_single_root, step0b,
  step0b_integrated). (RUN_ARCGIS_SMOKE_TEST.bat)
- Fixed the per-tool metadata sidecar gap noted as a known limitation in
  earlier v0.60.0 work-in-progress passes: bump_version.py renames only
  the main .pyt and its .pyt.xml sidecar, not the four per-tool
  `CCM_Tool_v<version>.CCMxxxTool.pyt.xml` metadata sidecars ArcGIS Pro
  generates, so those kept carrying a stale v0.59.7 filename prefix
  through the v0.60.0 rewrite. Renamed all four to the v0.60.1 filename
  by hand for this release. bump_version.py itself is unchanged, so this
  still needs a manual rename on every future release until the script
  is extended to cover them.
- Documentation: README.md, QUICK_START.md/.html, TOOLBOX_INTEGRATION.md,
  and VERSION_INFO.md rewritten for the v0.60.0 single-root architecture,
  the standalone Project Initializer, and the upgraded Data Scanner GUI --
  all four still described the pre-rewrite six-tool, per-step-folder
  workflow. CCM_Tool_v0.60.1_User_Manual.docx updated to match.
  PROJECT_STATUS.md and TASKS.md appended with this release's
  continuation notes.
- Release hygiene: registered ccm_project_init.py,
  build_project_init_exe.py, test_single_root_pure_python.py, and
  tests/arcpy_smoke_test_v060_single_root.py in package_ccm.py's
  VERSION_MODULES/CODE_FILES so the release-blocking static_checks()
  actually covers them (syntax, END OF FILE marker, version sync) --
  both new root-level scripts were missing the project's own
  VERSION-line/END-OF-FILE-marker convention entirely, and the two new
  test scripts were not registered anywhere. Renamed
  MANUAL_TEST_CHECKLIST_v0.60.0.md to the version-agnostic
  MANUAL_TEST_CHECKLIST.md so it no longer needs a manual rename on
  every future release the way the User Manual and toolbox files do; it
  is now also a required release file (package_ccm.py REQUIRED_FILES).
- Version bumped 0.60.0 -> 0.60.1 across all modules, the .pyt and all
  five .pyt.xml sidecars (main + four per-tool), and the User Manual, via
  bump_version.py plus the manual per-tool-sidecar rename above. This is
  the first packaged release ZIP for the v0.60.0 single-root rewrite:
  CCM_Tool_v0.60.1.zip.

## v0.59.7 — Data Intelligence correctness on real field data

### Projection handling (the CRS unification pass)

- Slope is no longer derived from a geographic DEM. `Slope("PERCENT_RISE")`
  is rise/run, and the old call passed neither a projection step nor a
  z-factor: on an EPSG:4326 DEM the rise was metres and the run DEGREES, so
  every slope was wrong by orders of magnitude — silently, feeding F1 and
  therefore every GO/NO-GO decision. SRTM, ASTER and CDEM all ship in 4326,
  so this was the normal case. A geographic DEM is now clipped to the AOI and
  projected (ProjectRaster, BILINEAR) into the project CRS before slope; if
  there is no projected CRS to conform it to, slope is refused with an
  explanation rather than fabricated. An already-projected DEM is left in its
  own CRS exactly as before — conforming it to the extent would resample a
  good UTM raster into whatever the extent happens to use. A DEM with an
  undefined CRS is also left alone, since refusing it would replace a usable
  answer with a flat-terrain assumption that biases toward GO.
  (ccm_step1_setup.py)
- The slope z-factor is computed from the ground unit instead of assumed. A
  foot-based projected CRS (US State Plane ftUS, routine in the SSURGO
  workflow) scaled every slope by 3.28 with no error raised. Unknown units
  fall back to 1.0, preserving previous behaviour. (ccm_step1_setup.py)
- Clip-then-project, not project-then-clip: the AOI is usually a small
  fraction of a national DEM mosaic. (ccm_step1_setup.py)
- Web Mercator is flagged as a project CRS, with the real number. The
  Analysis Extent gate asked only "Geographic or Projected?", and Web
  Mercator — the default CRS of anything digitised over a basemap — answers
  "Projected". Its scale error is 1/cos(latitude): at the Lebanon test AOI
  (34.0 deg N) that is 21% on every length and 46% on every area, so a 10 km
  route reads as 12.1 km and an hour of travel time is off by 12 minutes,
  always in the optimistic direction. Step 1 now warns with the figures
  computed from that AOI and names the UTM zone to use.
  (ccm_step1_setup.py, ccm_data_report.py)
- `recommend_utm_for_extent()` picks a project CRS for a whole AOI rather
  than a point. The centroid rule says nothing about how much of the AOI is
  in the chosen zone: the Lebanon AOI (35.10-37.00 deg E) straddles the 36 deg
  boundary 47/53, so nearly half of it is projected outside whichever zone is
  picked. The new function returns the majority zone plus every zone touched
  and a plain-language caveat. (ccm_data_catalog.py)
- The project CRS is recorded in ccm_project.json (`project_crs_epsg` /
  `project_crs_name`) instead of being re-inferred by each step from
  whichever layer it opens. Only written when actually read, so a failed
  Describe cannot wipe a good recorded value.
  (ccm_project_config.py, ccm_step1_setup.py)

### Corrections found in adversarial review of the above

- Summed coverage never earns GREEN. Adding per-dataset AOI coverage cannot
  distinguish four tiles that mosaic to 100% from three products that each
  cover the same 40% — both sum past 100. GREEN now requires one dataset
  measured to cover the AOI; a sum earns YELLOW labelled as an upper bound
  with overlap unmeasured. (ccm_data_report.py)
- The release-tree exclusion requires the full module signature (both modules
  AND the toolbox), not a lone .pyt. Copying just the toolbox into a working
  folder is a normal ArcGIS habit, and the looser rule would have pruned the
  analyst's own data with it. (ccm_data_catalog.py)
- Skipped folders are now stated in the report. Pruning that is invisible
  reproduces the exact failure this release set out to fix: a role reading
  "not found" because its folder was skipped looks identical to one whose
  data does not exist. (ccm_data_report.py)
- An empty geodatabase is no longer reported as unreadable when a full
  metadata backend is present — it opened fine and simply holds nothing (a
  newly created project GDB, for instance). (ccm_data_report.py)
- Step 2 no longer hard-errors a project whose recorded vehicle CSV is the
  bundled fleet from a previous install; since the tool folder is renamed
  every release, that would have broken every project that accepted Step 1's
  default on the first upgrade. It falls back to this install's copy and says
  so. (ccm_step2_mobility.py)
- Step 1's data-root scan only replaces the seeded vehicle CSV when the
  analyst has not touched the field, so deliberately re-picking the bundled
  fleet now sticks. (ccm_step1_setup.py)
- Coverage is not consulted before checking that an analysis extent was
  supplied, and the report no longer states a fixed "~20%" for Web Mercator
  at any latitude — it describes the 1/cos(latitude) relationship and leaves
  the measured figure to Step 1. (ccm_data_report.py)
- Step 2's new validators no longer return early out of updateMessages(),
  which skipped the GO-threshold, rainfall and Monte-Carlo checks.
  (ccm_step2_mobility.py)


Found by re-running the AOI_Lebanon field dataset (11 SRTM tiles, HWSD soil,
HydroLAKES/HydroRIVERS, Web Mercator AOI) against the v0.59.6 report, which
reported "Model confidence: At-Risk" with every role RED on data that was in
fact present and, for DEM, fully covering the AOI.

- Data Intelligence no longer catalogues the CCM tool's own release tree as
  analyst data. Analysts routinely unzip the release into their data folder;
  its tests/, verification_artifacts/<stamp>/fake_data and pytest_tmp_*/
  trees carry synthetic DEMs, AOIs, hydrology layers and Vehicles_Can.csv
  copies from tests/make_fake_data.py. On the AOI_Lebanon scan those
  fixtures produced 40 duplicate groups, 318 unclassified files and 7
  competing "vehicle databases" (6 of them 3-row fakes) against 1 real one,
  and pushed synthetic rasters into the role rankings. A copied release is
  now detected structurally (the toolbox .pyt, or ccm_data_catalog.py beside
  ccm_version.py), so any version is recognised — but only when the scan is
  not deliberately aimed at it, which keeps the test suite's own temporary
  data roots scannable. Rescan of the same folder: 915 files -> 34, 318
  unclassified -> 4, 7 vehicle CSVs -> 1. Skipped folders are recorded in
  `catalog["skipped_dirs"]`. (ccm_data_catalog.py)
- The scanner no longer catalogues its OWN outputs as datasets. Re-scanning
  a folder picked up ccm_project.json, ccm_data_catalog.json, the score
  JSONs and the HTML/TXT reports it had written there on the previous run —
  one real scan classified ccm_project.json as an "Analysis Extent" dataset
  because it sat in a folder named AOI_Lebanon. mgcp_manifest.json is
  deliberately still catalogued: it is a genuine Step 0 input.
  (ccm_data_catalog.py)
- A role's presence status is now judged on how much of the AOI its datasets
  cover TOGETHER, not on its worst single member. Elevation, land cover and
  soil products ship as tile sets: the AOI_Lebanon scan measured its four
  in-AOI SRTM tiles at 23.6 / 26.2 / 23.6 / 26.2 % (~100% mosaicked, exactly
  right) and the seven neighbouring tiles at 0%, and the worst-first rollup
  painted DEM — and by the same mechanism Soil, Vegetation and Hydrology —
  solid RED on fully covered data. A tile outside the AOI is an unused tile,
  not a defect. The combined figure is an upper bound (overlapping tiles
  count twice) and is labelled as such; genuinely partial coverage still
  reads YELLOW/RED, and unmeasured coverage still reads grey.
  (ccm_data_report.py)
- Step 2 now rejects a Data Intelligence config in place of a project
  config, and reports stale absolute paths. Two different tools write a file
  named ccm_project.json — Step 0b drops one in the DATA ROOT holding only
  scan results, Step 1 writes the real one in the PROJECT FOLDER — and Step
  2 only checked that the file existed. Pointing it at the data root (which
  has a ccm_project.json, so validation passed) left the Vehicle picklist
  and every other config-driven field silently empty, because the picklist
  reads cfg["vehicle_csv"], which a Step 0b config does not have; the
  populate step swallows every failure. The same silence hid a moved or
  copied project, whose recorded absolute paths all stop resolving. Both now
  produce a specific error naming the cause. (ccm_step2_mobility.py)
- Web Mercator is now flagged instead of passing as a clean projected CRS.
  The CRS check asked only "is it projected?", which Web Mercator (EPSG 3857,
  and the legacy 900913 / Esri 102100) passes — so an AOI digitised over a
  basemap, which is what the AOI_Lebanon field test used, read GREEN while
  silently biasing the model: Web Mercator's scale factor is 1/cos(latitude),
  so at ~34 deg N every distance CCM derives is ~20% too long and every area
  ~45% too large, and slope, speed, isochrone and route length inherit that
  error. It now reads YELLOW with the reason and points at UTM (the UTM zone
  recommendation already exists in recommend_utm_epsg()). Geographic CRSs are
  unaffected and still flagged for their own reason. (ccm_data_report.py)
- Regression tests for all of the above (18 new tests; suite 262 -> 280).
  (tests/test_v057_data_intelligence.py)
- Dataset-name normalisation no longer depends on the host OS. Step 0b took
  the leaf of a dataset path with `Path().name`, which resolves separators
  for the platform it runs on, so Windows catalogue paths yielded no leaf
  when the release gate ran on posix. Catalogue paths are data, not host
  paths; both separators are now handled. This was the last failure in the
  portable suite, which is now green on Windows and posix alike (281 passed).
  (ccm_step0b_integration.py)
- bump_version.py rewrites files newline-transparently. It read and wrote in
  text mode, so running a bump from a posix host silently rewrote every CRLF
  source as LF across ~43 files. (bump_version.py)

### Also in v0.59.7 — GDB/project-folder default, Vehicle CSV default, unreadable-container visibility

- Step 0 (Load MGCP Data): the "Output Geodatabase" field now defaults to
  `CCM_Project.gdb` inside the CURRENT ArcGIS Pro project's home folder
  (same name Step 1 already uses) the first time the tool dialog opens,
  instead of having no default at all. Previously the GDB location was
  whatever ArcGIS Pro's file browser last happened to point at, which could
  land in a different folder than the project itself. Never overrides a
  value the analyst already set. (ccm_step0_mgcp.py)
- Step 1 (Project Setup): "Vehicle Definitions CSV" (Required) now defaults
  to the Vehicles_Can.csv shipped in this tool's own Vehicle_Data\ folder
  when the field is empty, instead of having no default and depending
  entirely on the analyst's Data Root folder happening to contain a vehicle
  CSV. This is what left Step 2's Vehicle picklist empty on a fresh project
  — Step 2 only ever reads `vehicle_csv` from `ccm_project.json`, which was
  never written if Step 1's Required field was never filled in. Still fully
  overridable with a custom fleet CSV. (ccm_step1_setup.py)
- Data Intelligence (ccm_data_catalog.py / ccm_data_report.py / CCM Data
  Scanner GUI): a .gdb or .gpkg whose contents could not be enumerated (no
  arcpy and no GDAL/OGR available — the standalone scanner never bundles
  either) is now reported explicitly as an unreadable container, in both the
  text and HTML reports and the scanner's on-screen log, instead of silently
  contributing nothing to every role. Every dataset that lived inside such a
  container previously looked identical to "this data does not exist" —
  this is the most likely explanation for a report where every role reads
  red/missing despite real data being present on disk. New
  `catalog["unreadable_containers"]` / `catalog["stats"]["unreadable_containers"]`
  fields.

## v0.59.6 — Verification and report-output hardening

- Made the recommendations HTML report a required Step 0b output so a failed
  report write cannot be misreported as a successful integrated scan.
- Added explicit report-generation errors and UTF-8 output handling.
- Isolated each verification run's pytest temporary directory and invalidated
  stale pass markers before verification begins.
- Removed stale copied verification artifacts and synchronized the release
  identity to v0.59.6.

## v0.59.5 — Version-synchronized release package

- Bumped the complete release tree, toolbox identity, metadata, manual, and
  package manifest to v0.59.5.
- Kept the v0.59.4 ArcGIS Pro module-isolation and Step 0b null-metadata fixes.

## v0.59.4 — ArcGIS Pro toolbox module-isolation hotfix

- Uses a fresh `CCM_Tool_v0.59.4.pyt` identity to prevent ArcGIS Pro from
  reusing the previously registered toolbox module.
- Moves this toolbox folder to the front of `sys.path` even when it was
  already present, and evicts `ccm_*` modules loaded from another release
  folder before the tool classes are imported.
- Retains the Step 0b null-metadata guard introduced in v0.59.3.

## v0.59.3 — Step 0b null-metadata hotfix

- Made the Step 0b integration boundary replace a missing dataset name with
  the dataset path leaf (or `Unknown dataset` when no path is available).
- Made all fitness-engine case-insensitive comparisons null-safe, including
  dataset names, source types, and optional `Soil_Code` CSV values.
- Added regression tests covering every fitness role and integration-record
  normalisation with a null dataset name.

## v0.59.2 — GDAL-enabled verification correction

- Made degraded-mode CRS tests explicitly disable both ArcPy and GDAL/OSR, so
  they test the intended no-transform-backend contract in every supported
  Anaconda environment.
- Added geographic-coordinate bounds validation before reprojection. An AOI
  labelled geographic but containing projected metre coordinates now remains
  honestly unmeasured instead of producing a misleading coverage value.
- Confirmed that valid GDAL-backed transformations remain available and are
  independently tested when `ccm_tool_gdal` is active.

## v0.59.1 — Release synchronization and packaging

- Rebuilt the release from the complete Steps 0-4 and Step 0b source tree;
  the v0.59.0 folder was a focused update set, not a standalone distribution.
- Retained the cross-CRS AOI coverage regression tests that were absent from
  the update set, including both successful reprojection and safe degraded
  behavior when no transform backend is available.
- Synchronized source modules, toolbox metadata, ArcPy smoke tests, portable
  tests, launchers, documentation, the operator manual, and generated release
  manifest to v0.59.1.
- Made the package and test entry points version-neutral (`package_ccm.py` and
  `RUN_TESTS.bat`) so a future semantic version bump does not retain a stale
  filename.
- Hardened `bump_version.py` to update test modules, renamed DOCX manuals,
  and recover cleanly from a single stale toolbox filename.

## v0.59.0 — CRS-aware coverage computation

Release date: 2026-08-19

## Release focus

This release combines the complete `v0.58.1` toolbox with the scoring and
recommendation modules from `v0.58.1a`. The incomplete `v0.58.1a` extraction is
not used as a standalone toolbox.

## Fixed

- Restored real Step 0 and Step 0b toolbox classes in one coherent release
  folder. Step 0b no longer appears as an empty unavailable stub when the
  toolbox is loaded from the release root.
- Registered the integrated Step 0b workflow through the existing
  `CCMDataIntelligenceTool` entry point.
- Normalized factual catalog records before scoring so structured CRS,
  resolution, schema, coverage, and acquisition metadata are interpreted by
  the scoring engines correctly.
- Corrected the report API call from the nonexistent `write_reports` function
  to the existing `ccm_data_report.write_all` function.
- Added safe defaults for unknown coverage values so vehicle and other
  non-spatial records do not crash recommendation scoring.
- Added a Step 1 display-only recommendation hand-off. Explicit user inputs
  remain authoritative.
- Updated the verifier and release manifest to include all v0.59.1 scoring,
  integration, tests, support assets, and documentation.

## New Step 0b outputs

- `ccm_quality_scores.json`
- `ccm_fitness_scores.json`
- `ccm_confidence_scores.json`
- `ccm_readiness_scores.json`
- `ccm_recommendations.json`
- `CCM_Recommendations_Report.html`

The factual `ccm_data_catalog.json`, HTML report, TXT report, and project
configuration hand-off remain available.

## Verification

The portable release gate includes fixture generation, factual regression
tests, v0.59.1 integration tests, calibration-data audits, syntax checks,
pyflakes, and an end-to-end output check. A separate ArcPy smoke launcher
checks the licensed ArcGIS Pro path.

## Boundary

Readiness is reported as `Not Yet Run` until Step 1 preprocessing produces the
required project outputs. Recommendations are guidance for review, not
certification and not automatic input substitution. Final ArcPy/GDAL metadata
behavior must be confirmed in the user's licensed Anaconda/ArcGIS environment.

# <<< END OF FILE >>>
