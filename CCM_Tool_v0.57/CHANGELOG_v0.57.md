<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
<!-- Copyright (c) 2026 Eui Soo SON -->

# CHANGELOG — v0.57 post-review fixes (2026-08-19)

A full logic/plan-conformance review against `CCM_v0.56.0_Implementation_Plan.md`
and `CCM_Implementation_Plan_v2_Roadmap_Aligned.md`, followed by fixes for
every finding. No version-number bump in this pass (see `PROJECT_STATUS.md`);
`ccm_version.py`/`bump_version.py` are ready for the next one.

### Follow-up: `CCM_anaconda.bat` now activates the environment it creates

`CCM_anaconda.bat` used to only *print* `conda activate %ENV_NAME%` as an
instruction and leave the calling Anaconda Prompt in whatever environment it
started in — the operator had to type that command themselves every time.
Fixed so the script actually activates the environment before it exits: this
required leaving the script's `setlocal` scope first (`endlocal & ...` on one
line, the standard idiom — `setlocal` otherwise silently discards
`conda activate`'s `PATH`/`PROMPT`/`CONDA_*` changes when the script ends), with
a fallback warning-and-manual-instruction message if activation still fails
for some reason (e.g. `conda activate` not hooked into a plain, non-Anaconda
`cmd.exe`). `README.md`, `QUICK_START.md`, `QUICK_START.html`, and the User
Manual's "Running Step 0b outside ArcGIS Pro" section updated to describe the
new behaviour instead of instructing a manual `conda activate` step. The
`RUN_*.bat` launchers were already unaffected either way — they all dispatch
via `conda run -n`, which does not depend on the calling shell's activation
state; this fix is about interactive convenience (`python`, `pytest`, etc.
typed directly into the prompt now use the right environment too), not
correctness of the launchers.

### High severity

- **H-1** — `ccm_step3_advanced.py`'s `execute()` logged failures for all 5
  sub-analyses (Reason Map, Reachability/Isochrone, Vehicle Comparison,
  Obstacle Detection, Waypoint Routing) as `AddWarning` only and always
  printed "Advanced Analysis Complete" at the end, so a tool that failed
  every single sub-analysis still reported success. Now tracks a pass/fail
  result per sub-analysis and raises `arcpy.ExecuteError` via `AddError()`
  if any of them failed.
- **H-2** — `soil_rci.csv` shipped a `Pt` (mixed-case) row for peat, but
  `ccm_step2_mobility.py`'s built-in table and lookup code used `"Pt"` in
  one place and normalized-elsewhere logic inconsistently, so a soil polygon
  actually tagged `PT` never matched the CSV's calibrated row and silently
  fell back to the (different) built-in value. All USCS keys are now
  uppercase everywhere (`_BUILTIN_USCS_RCI`, `USCS_TO_SENSITIVITY_KEY`,
  `soil_rci.csv`), and `load_rci_csv()` / `soil_factor()` normalize incoming
  codes to uppercase before lookup, with a warning for any CSV code the
  built-in set doesn't recognize.
- **H-3** — `soil_factor()` looked up the USCS code case-sensitively, so a
  soil FC producing a lower-case or mixed-case `soilType` value (e.g. from a
  hand-edited or third-party soil layer) silently missed every RCI penalty
  and returned full unpenalized speed. Fixed by the same normalization as
  H-2; `compute_stochastic_go()`'s Monte Carlo per-trial override table had
  an identical case-mismatch bug one level deeper (building its one-entry
  override table keyed by the raw, un-normalized code) which the fix for
  this also had to correct.
- **H-4** — `tests/arcpy_smoke_test.py` (the real Step 2 mobility-engine
  licensed smoke test) had a header comment claiming the filename
  `arcpy_smoke_test_step0b.py` — a name already used by the actual Step 0b
  test — so `RUN_ARCGIS_SMOKE_TEST.bat` ran only whichever of the two ended
  up on disk under that name and never exercised the other. Renamed to
  `tests/arcpy_smoke_test_step2.py`; `RUN_ARCGIS_SMOKE_TEST.bat` rewritten
  to auto-detect `propy.bat`, run all five smoke tests (step0, step1, step2,
  step3, step0b) explicitly, and print a combined pass/fail summary.

### Medium severity

- **M-1** — `ccm_data_catalog.py`'s `_polygon_intersection_pct_arcpy()` left
  an `arcpy.da.SearchCursor` unclosed (bare list comprehension instead of a
  `with` block). Wrapped in `with ... as _aoi_cur:`.
- **M-2** — `ccm_soil_validator.py`'s USCS/soil sanity checks existed but
  were never called from `ccm_step1_setup.py`'s `execute()`. Wired in: the
  `elif final_soil_fc:` branch now calls `validate_soil_fc()` and aborts
  with `AddError()` if the result says the tool can't proceed.
- **M-3** — `ccm_step3_advanced.py`'s 5 sub-tool invocations built fixed-
  order positional parameter lists (`xx_params[N].value = ...`), which
  silently break if a sub-tool's `getParameterInfo()` order ever changes.
  Refactored to `ccm_project_config.run_tool(tool, messages, name=value,
  ...)` by parameter name; the Isochrone block's fuzzy name-matching and
  output-direction-scanning loops were replaced with direct keyword
  arguments. New `ccm_project_config.by_name(parameters)` helper added for
  the companion in-tool-own-execute() case.
- **M-4** — `CCM_Tool_v0.57.pyt` carried a dead command-line `CCMAssessment`
  class / `main()` / `if __name__ == "__main__":` path (unreachable from
  ArcGIS Pro, which never runs a `.pyt` as `__main__`) that, if invoked
  directly, wrote a `summary.json` echoing its inputs without running any
  real analysis — a false-success trap. Confirmed via grep that nothing in
  the real Step 0-4 tool classes called any of its helpers, then removed
  the whole block along with its 11 now-orphaned unit tests.
- **M-5** — `package_ccm_v057.py` and `build.py` each hard-coded their own
  release file manifest and had already drifted from each other once.
  `build.py`'s `PY_FILES` is now derived from `package_ccm_v057.CODE_FILES`
  instead of a second hand-maintained list; both now import `VERSION`/
  `RELEASE_NAME` from the new single-source `ccm_version.py`.

### Plan-conformance gaps

- **P-1** (Roadmap alignment) — decision recorded in `PROJECT_STATUS.md`:
  v0.57 stays factual-only as shipped rather than retrofitting the plan's
  "Automatic Data Selection" phase boundary onto it; later roadmap phases
  are understood to shift by one version accordingly.
- **P-2** (Catalog reuse) — Step 0b's `ccm_data_catalog.json` was produced
  but never read back anywhere, so Plan v2 §3.5's "Step 1 reuses the Step
  0b catalog" was unbuilt. Added `ccm_step1_setup.py`'s
  `_load_catalog_for_root()` / `_log_catalog_facts()`, called from
  `execute()`: at run time, Step 1 now surfaces the matching catalog's
  per-role dataset facts (path, CRS, resolution/feature-count, AOI
  coverage) and missing-role warnings in the Results pane.
- **P-3** (Deep-scan mode) — decision recorded in `PROJECT_STATUS.md`: the
  plan's optional `scan_detailed()` deep-inspection mode was not built; the
  existing two-layer discovery/catalog design already covers every current
  consumer.

### Automation / simplification (review section 5)

- **5.1** — Added `ccm_version.py` (single source of truth for `VERSION`/
  `RELEASE_NAME`) and `bump_version.py` (one-command version bump: rewrites
  every `VERSION_MODULES` file plus the `.pyt`'s `toolversion` line, renames
  the `.pyt` and its sidecars/manual, runs the verifier before and after).
- **5.3** — Added `ccm_data_audit.py`: static consistency checks for
  `soil_rci.csv` (RCI monotonicity, USCS code recognition, duplicate rows)
  and `Vehicle_Data/Vehicles_Can.csv` (VCI ordering, required columns,
  numeric sanity, duplicate names), plus USCS_TO_SENSITIVITY_KEY coverage
  against `_BUILTIN_USCS_RCI`. Wired into `package_ccm_v057.py
  --verify-only` as a release-blocking check; 12 new regression tests in
  `tests/test_v050.py`.
- **5.5** (smaller cleanups) — Guarded `CCM_Data_Scanner_GUI.py`'s
  unconditional `import tkinter` so the module (and therefore the whole
  pytest suite, which imports it via `tests/test_v057_data_intelligence.py`)
  loads cleanly on a Python without Tcl/Tk; `main()` now prints a clear
  error instead of crashing if someone tries to actually launch the GUI in
  that situation. Fixed `ccm_soil_preprocess.py`'s SLC-GDB table-discovery
  helper, which set `arcpy.env.workspace = gdb_path` and then unconditionally
  clobbered it to `None` afterwards instead of restoring the caller's prior
  workspace — now saved/restored via `try`/`finally`, matching the same
  pattern already used elsewhere in that file. Removed
  `ccm_project_config.find_latest_speed_surface()` — zero callers anywhere
  in the codebase (grep-verified) and had the identical workspace-clobber
  bug; `ccm_step3_advanced.py` already has its own correct, purpose-built
  equivalent (`_list_speed_surfaces(project_gdb)`). Added `ccm_debug.py`, an
  opt-in (`CCM_DEBUG=1`) diagnostic hook for the codebase's ~105 defensive
  `except Exception: pass` handlers — infrastructure only; individual call
  sites can adopt it incrementally.
- **5.6** — Doc pass: fixed `PROJECT_STATUS.md`'s stale references to the
  H-4-affected smoke-test filename and the removed
  `find_latest_speed_surface`, updated the stale test-count claim, and
  renamed 5 tests across `tests/test_ccm.py` that were named
  `test_version_is_047`/`_049`/`_054` (relics from when each was first
  written, but always correctly asserting the *current* `VERSION`) to
  `test_version_is_current` so the name no longer needs updating at every
  future version bump.

### Explicitly deferred (not done in this pass)

- **5.4** — a headless CLI wrapper for Steps 1-3 (parity with Step 0b's
  existing `--data-root`/`--aoi`/`--out` CLI mode).
- Full `.bat` launcher consolidation, beyond the `RUN_ARCGIS_SMOKE_TEST.bat`
  rewrite (H-4).
- An actual version-number bump — `ccm_version.py`/`bump_version.py` are
  ready; `VERSION` remains `"0.57"` pending a decision on when to cut the
  next release.
- Licensed ArcPy verification of the arcpy-dependent changes (H-1, M-2,
  M-3, P-2, the 5.5 workspace fixes) — these were verified with
  `py_compile`/`pyflakes` and, where testable without arcpy, `pytest`, but
  `execute()` paths that need a real ArcGIS Pro license still need this
  project's own `RUN_ARCGIS_SMOKE_TEST.bat` run and its logs reviewed
  before being called fully verified (see `CLAUDE.md`'s release protocol).

---

# CHANGELOG — v0.57 (2026-08-18)

## Integrated toolbox release

v0.57 creates a new isolated integration copy. The original v0.55.1 toolbox
and the validated v0.56.4 Data Intelligence work folder remain unchanged.

### Integration

- Added `ccm_data_catalog.py`, `ccm_data_sources.py`, `ccm_data_report.py`,
  and `ccm_step0b_intelligence.py` beside the ArcGIS toolbox.
- Registered **Step 0b — Data Intelligence Scan** between Step 0 and Step 1.
- Added the v0.57 toolbox sidecar and updated the project-config defaults with
  additive `data_root` and `data_catalog_json` keys.
- Preserved the existing Steps 0-4 mobility engine and manual-input behavior.

### Operator experience

- Added a v0.57 `CCM_anaconda.bat` environment setup script with optional
  GDAL/OGR support.
- Added logged `RUN_DATA_SCAN.bat`, `RUN_V057_TESTS.bat`, and
  `RUN_ARCGIS_SMOKE_TEST.bat` launchers.
- Rebuilt `QUICK_START.md` and `QUICK_START.html` as a one-page operator path.
- Updated the README, integration guide, project status, task register, and
  English User Manual to describe the six-tool workflow.

### Scope boundary

Step 0b reports factual inventory only. Data Quality, CCM Fitness, Confidence,
Readiness, automatic source selection, and substitution remain future roadmap
work and are not inferred from record order or missing-role results.

### Verification target

The v0.57 blocking verifier runs the legacy v0.55 regression suite together
with the Data Intelligence suite, pyflakes, fixture generation, end-to-end
scan/output validation, and the licensed ArcPy smoke test when ArcGIS Pro is
available.

---

# CHANGELOG — v0.55.0 (2026-08-06)

## Multi-PC consolidation release

This project had been worked on across more than one PC and diverged past
v0.54.1 in two different directions with no single copy ahead on every
axis. v0.55.0 reconciles them. No new features and no behaviour changes
beyond what v0.54.2-v0.54.7 already shipped — this release is entirely
about making sure every fix and every cleanup that had been made *anywhere*
actually ends up in the one folder going forward.

### The two folders

**`CCM_Tool_v0.54.1`** — today's most recently modified folder. A cleanup
pass had been run against it: the toolbox renamed and standardized
throughout, the old copyright-line suffix dropped, copyright headers
standardized to the two-line GPL-2.0-or-later form, old changelogs
(v0.45-v0.53) moved into `archives/CHANGELOG_HISTORY/`, and an old code
review into `archives/CODE_REVIEW_ARCHIVE/`. However, the source snapshot
that cleanup started from predated v0.54.2 — none of the six patch
releases below (v0.54.2 through v0.54.7) had reached this folder.

**`CCM_Tool_v0.54.7`** — a second machine's copy, still carrying the
pre-cleanup name and copyright suffix, but carrying every fix through
v0.54.7. Its file set matches what `build.py`'s packager actually
ships (internal dev docs like `CLAUDE.md` and `CCM_Improvement_Research.md`
are excluded from the zip by design — see `build.py`'s `EXCLUDE_EXACT` —
so this folder was missing them too; they existed only in the v0.54.1
working folder).

Being "modified today" made `CCM_Tool_v0.54.1` look newest, but a newer
mtime is not the same as being ahead in content — see `CLAUDE.md` Rule 3,
added in this release specifically because of this.

### Method

Every file in both folders was diffed. Of the 19 core Python modules, 14
differed **only** in cosmetics (the copyright header block, the old
copyright suffix, and the `VERSION` string) — for those, this release is
a straight debrand-and-renumber of the v0.54.7 content. Five files carried real
logic differences, and the packaged `Symbology/*.lyrx` differed in content,
not just metadata. In every one of these cases, `CCM_Tool_v0.54.7`
was strictly ahead — confirmed by inspecting the actual code, not inferred
from the changelog text alone:

- **`ccm_step2_mobility.py`** — `CCM_Tool_v0.54.1` still called
  `arcpy.analysis.Union(union_inputs, unioned, "ALL")` directly with all
  of soil + vegetation + slope in one call. On any licence below Advanced
  this raises `ERROR 000384: Cannot have more than 2 inputs with a Basic
  or Standard license` — **Step 2, the toolbox's core output, cannot
  complete at all** for such a user. `CCM_Tool_v0.54.7` has the
  v0.54.4 fix, `_union_license_safe()`, which folds inputs pairwise so no
  `Union` call ever exceeds two inputs, on any licence tier. This is the
  single most severe defect reconciled by this release and the main
  reason "just use today's folder" would have been the wrong call.

- **`ccm_map_display.py`** — `CCM_Tool_v0.54.1` still builds the speed
  surface renderer on a field called `Condition_Number`, which — per the
  v0.54.2 pre-release audit — no CCM module has ever produced (the real
  Step 2 output field is `Mobility`, values `GO`/`RESTRICTED`/`NO GO`).
  Confirmed in `CCM_Tool_v0.54.1`'s own code: `field = "Condition_Number"`
  with a handful of alternate spellings tried, none of which match
  `Mobility`. This fails **silently** — arcpy accepts the bogus field name
  and renders a single flat colour with no warning (verified against real
  ArcGIS Pro in the original v0.54.3 release, see `archives/
  CHANGELOG_HISTORY/CHANGELOG_v0.54.md`). `CCM_Tool_v0.54.7` has
  `resolve_field()` + `MOBILITY_COLOURS` keyed on the real field, verifies
  the field exists before assigning the renderer, and reports loudly if it
  can't. Also confirmed: `CCM_Tool_v0.54.1`'s colour tables still use a
  0-255 alpha channel where arcpy's CIM colour dict takes 0-100 (values
  150-255 silently clamp to opaque), and `lyr.transparency` was still being
  set *before* `ApplySymbologyFromLayer()` resets it — both fixed in the
  v0.54.7 side.

- **`ccm_isochrone.py`** — `CCM_Tool_v0.54.1` has no
  `_reclassify_with_retry()` and no vector-method fallback in
  `generate_isochrones()`. Confirmed by real-ArcGIS-Pro testing across
  v0.54.5/v0.54.6/v0.54.7 (see archived changelog), the Reachability Map /
  Isochrone tool can hit `ERROR 160333: The table was not found` on
  `Reclassify` — a real, Esri-acknowledged, non-deterministic raster issue
  with no published root cause. `CCM_Tool_v0.54.7` retries against
  the in-memory raster, then a saved-path/single-threaded retry, then
  falls back to the already-existing vector method rather than producing
  no output at all. `CCM_Tool_v0.54.1` has none of these three layers.

- **`build.py`** — `CCM_Tool_v0.54.1`'s copy is the **pre-v0.54.2**
  version: no `should_include()` screening, no stale-toolbox guard, and
  `PY_FILES` hardcodes the literal filename `CCM_Tool_v0.54.1.pyt` instead
  of deriving it from `VERSION`. This is exactly the packaging defect
  v0.54.2 fixed (the original v0.54.1 zip shipped 17 stale files,
  including two obsolete toolboxes and a Word lock file) — using this
  folder's `build.py` unchanged would have reintroduced it.

- **`ccm_step3_advanced.py`** — `CCM_Tool_v0.54.1` lacks the v0.54.4 fix
  that derives a clean vehicle label (`CCM — Leopard (moist)`) instead of
  the raw feature-class basename, and lacks the v0.54.4
  `kind_of() is None` handling (an unrecognised output used to silently
  get speed-surface symbology applied to it).

- **`Symbology/Mobility_Symbology.lyrx` and `_Final.lyrx`** —
  `CCM_Tool_v0.54.1`'s copies still carry the old 7-class legend (`GO`,
  `RESTRICTED`, `SLOW`, `VERY SLOW`, `NO GO - Hydro Feature`, `NO GO`,
  `NO GO - Vegetation`) — four of those seven are values Step 2 has never
  produced, so every finished map showed four permanently blank legend
  rows. `CCM_Tool_v0.54.7`'s copies are pruned to the three classes
  Step 2 actually emits (`GO` / `RESTRICTED` / `NO GO`), per the v0.54.2
  fix.

- **Duplicate `Vehicles_Can.csv`** — `CCM_Tool_v0.54.1` has the vehicle
  CSV both at the project root AND in `Vehicle_Data/` — the exact
  stale-duplicate state v0.54.2 removed (`Vehicle_Data/` is the single
  source of truth; Step 1's own help text points there). Not carried
  forward.

- **`tests/arcpy_smoke_test_step0b.py`** — `CCM_Tool_v0.54.1`'s copy does a bare
  top-level `import arcpy`, which aborts pytest **collection** on any
  machine without a licensed ArcGIS Pro install — the exact defect v0.54.2
  fixed with `pytest.importorskip`. Confirmed directly: running this
  project's test suite in an environment with no `arcpy` package (as used
  to validate this very release) reproduces the collection abort against
  the v0.54.1-folder copy of this file. `CCM_Tool_v0.54.1` is also simply
  missing `tests/arcpy_smoke_test_step0.py`, `tests/
  arcpy_smoke_test_step1.py`, `tests/arcpy_smoke_test_step3.py`, and
  `tests/verify_v0544.py` outright (added in v0.54.4).

- **User Manual** — `CCM_Tool_v0.54.1`'s manual is internally
  inconsistent: the title page and filename use the current naming
  (`CCM_Tool_v0.54.1`), but the body text (Section 2.2) still instructs
  the user to navigate to a folder and open a `.pyt` file under the old
  pre-rename naming pattern — a file that does not exist under that name
  in that folder. The rename evidently touched the title page and
  filename but not every body reference.

The remaining 14 modules (`ccm_coords.py`, `ccm_data_discovery.py`,
`ccm_mgcp_catalog.py`, `ccm_obstacle_detect.py`, `ccm_project_config.py`,
`ccm_reason_map.py`, `ccm_soil_preprocess.py`, `ccm_soil_validator.py`,
`ccm_step0_mgcp.py`, `ccm_step1_setup.py`, `ccm_veg_preprocess.py`,
`ccm_vehicle_compare.py`, `ccm_waypoints.py`, `ccm_weather.py`), the main
`.pyt`, the 5 per-tool `.pyt.xml` sidecars, `Vehicle_Data/Vehicles_Can.csv`,
and `soil_rci.csv` were confirmed identical in substance between the two
folders (header/version-only, or byte-identical).

### Resolution

v0.55.0 = the `CCM_Tool_v0.54.7` codebase (all fixes) with the
`CCM_Tool_v0.54.1` debrand/relicense treatment re-applied on top:

- Toolbox `toolname`/`alias`, filenames, and docs renamed and
  standardized throughout to the current `CCM_Tool` naming.
- Old copyright-line suffix dropped: `Copyright (c) 2026 Eui Soo
  SON`.
- Copyright headers standardized to the two-line form (no box comment).
- The main `.pyt.xml` sidecar rewritten — `CCM_Tool_v0.54.1`'s own copy
  of this file was independently stale (it still read `<toolbox
  name="CCM_Tool_v0.50.1">` internally, four renames out of date; this
  was the exact defect v0.54.2 fixed on the v0.54.7 side but the fix
  never reached this file on the v0.54.1 side). v0.55.0's copy carries
  the current name, alias, today's `ModDate`, and the descriptive
  `idAbs`/`idCredit` block from the v0.54.7 side with the old copyright
  suffix removed.
- `archives/CHANGELOG_HISTORY/` carries forward from the v0.54.1 folder
  (v0.45-v0.53, already cleaned of old-naming filename references) plus
  `CHANGELOG_v0.54.md` (added here, now that v0.54 is fully closed out).
  `archives/CODE_REVIEW_ARCHIVE/CODE_REVIEW_v0.49.3.md` likewise carried
  forward.
- `CLAUDE.md` and `CCM_Improvement_Research.md` carried forward from the
  v0.54.1 working folder (the v0.54.7 folder never had them — see above).
  `CLAUDE.md` gains a new Rule 3 about checking for divergence across
  machines before trusting one folder's version number or mtime.
- One-time reports specific to today's now-superseded v0.54.1 cleanup
  pass (`CLEANUP_STATUS_v0.54.1.md`, `CLEANUP_SUMMARY.md`,
  `FINAL_CLEANUP_REPORT.txt`, a stale-toolbox deletion list,
  `ZIP_CONTENTS.md`, `verify_cleanup.sh`) are retired — their content is
  superseded by this changelog entry, and the obsolete pre-rename
  toolboxes they reference do not exist in either source folder.
- New `QUICK_START.md` — a one-page setup/first-run guide, split out from
  the User Manual's Section 2 so a new user isn't required to open a
  40-table Word document just to get the toolbox loaded.
- User Manual regenerated from the `CCM_Tool_v0.54.7` base (the
  internally-consistent one): debranded, version bumped, the stale
  Section 2.2 folder/filename reference corrected, a new Section 10.4
  Version History row added for v0.55.0.
- Version bumped 0.54.7 → 0.55.0 across every module `VERSION` constant,
  the `.pyt` `toolversion`, all `.pyt.xml` sidecars (renamed), `build.py`,
  the test suite, `README.md`, `PROJECT_STATUS.md`, `TASKS.md`, and the
  user manual.

### Verification

- `ast.parse` + pyflakes undefined-name scan clean on all 19 modules,
  `build.py`, and the `.pyt` (no arcpy required for this check).
- `python build.py` — integrity check passes, stale-toolbox guard passes
  (exactly one `.pyt` in the release folder), `CCM_Tool_v0.55.0.zip`
  built.
- `pytest tests/` — runs in an environment with no licensed ArcGIS Pro
  install; the `pytest.importorskip("arcpy")` guard (present in this
  release, absent from the v0.54.1 folder's copy of this file) allows
  collection to complete and the arcpy-independent tests to run rather
  than aborting outright. See the session's own build/test log for the
  pass/skip counts obtained in this environment.
- The five real-ArcGIS-Pro smoke tests (`tests/arcpy_smoke_test*.py`) and
  the `tests/verify_v0544.py` script still require a licensed ArcGIS Pro
  install to execute meaningfully and were **not** re-run against real
  ArcGIS Pro as part of this consolidation — their code is carried over
  unchanged from the already-verified v0.54.7 line (see
  `archives/CHANGELOG_HISTORY/CHANGELOG_v0.54.md` for the real-environment
  runs that originally validated them). Re-running them on a licensed
  machine before production use is recommended; see `QUICK_START.md` /
  `README.md` for how.

---

*(For v0.54.0 - v0.54.7 release notes, see `archives/CHANGELOG_HISTORY/CHANGELOG_v0.54.md`.)*
