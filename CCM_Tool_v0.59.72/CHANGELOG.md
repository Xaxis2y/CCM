# CCM Tool v0.59.7 — Changelog

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
