<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
<!-- Copyright (c) 2026 Eui Soo SON -->

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

- **`tests/arcpy_smoke_test.py`** — `CCM_Tool_v0.54.1`'s copy does a bare
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
