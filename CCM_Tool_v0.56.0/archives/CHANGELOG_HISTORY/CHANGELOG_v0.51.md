<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
<!-- Copyright (c) 2026 Eui Soo SON -->

# CHANGELOG — v0.51.0 (2026-07-03)

## Map display rework — one visual language (readability release)

Running all five Step 3 analyses used to stack three full-extent polygon
fills (speed surface + isochrone bands + vehicle compare) over the imagery
basemap, with red meaning three different things (No-Go, 120-min band,
obstacles) and Vehicle Compare left with a random single-colour fill.

### New module — `ccm_map_display.py`

The ~250-line inline display block in `ccm_step3_advanced.py` is extracted
into a shared module (CODE_REVIEW_v0.49.3 recommendation #2). Step 3 now
calls it; Step 0/2 display paths are unchanged and can migrate later.

### Visual language rules (enforced by the module)

- **One filled layer per map** — the speed surface (red→green
  `Condition_Number` classes, 55 % transparency). Red now means No-Go and
  nothing else.
- **Reachability rings are hollow** — coloured outlines only, light→dark
  **blue→purple** time ramp (15 → 240 min) with time-band labels. No more
  warm fills stacking over the surface.
- **Vehicle Comparison shows only differences** — categorical renderer on
  `COMPARE_RESULT`: *A only* teal, *B only* orange, `NEITHER` thin grey
  outline, `BOTH_GO`/`DATA_GAP` invisible. Class labels carry the actual
  vehicle names.
- **Obstacles are red 45° hatching** (CIM hatch fill) instead of a
  near-opaque solid fill — terrain beneath stays visible.
- **Per-run group layer** `CCM — <vehicle> (<moisture>)` keeps repeat runs
  tidy in the Contents pane.
- **Enforced draw order** (bottom→top): speed surface → compare → rings →
  obstacles → route → start/end markers, via sorted add order into the
  group.
- Route (white-halo magenta line) and start/end markers (gold/red circles)
  keep their v0.50 look; markers are now nested in the run group too.

### Robustness

- Every styling call degrades to a plain layer with a warning — symbology
  can never fail the analysis run.
- If `ccm_map_display.py` is missing, Step 3 falls back to unstyled layers
  in the active map (with a warning) instead of erroring.

## Tests

- 8 new unit tests (kind classification, draw-order sort, colour-table
  invariants: no red in the ring ramp, agreement categories invisible,
  No-Go red / Go green). Suite: **138 passed / 3 skipped**, arcpy-free.

## Version

- All module `VERSION` constants → `0.51.0`; toolbox renamed
  `CCM_Tool_v0.50.2.pyt` → `CCM_Tool_v0.51.0.pyt` (sidecar XMLs, `build.py`
  incl. new module in PY_FILES, README, PROJECT_STATUS, TASKS, tests,
  user manual updated).

---

# v0.51.1 (2026-07-03) — Unknown-CRS auto-repair (Step 0)

`[SR MISMATCH] ... (GCS_WGS_1984, Unknown)` was reported when some MGCP cell
shapefiles lack their `.prj` sidecar. The coordinates in such files are still
WGS84 (the MGCP specification CRS) — only the label is missing — so the fix
is to ASSIGN the CRS (DefineProjection), never to reproject.

- **Pre-run detection** — the tool dialog now warns on the Shapefile Folders
  parameter when input shapefiles have no `.prj`, naming the first files
  found and stating how they will be handled.
- **New Step 0 parameter 14** — *Assume WGS84 (EPSG:4326) for Sources With
  Unknown CRS* (default ON). After each import from an Unknown-CRS source,
  the output FC gets `DefineProjection(WGS84)` — label only, coordinates
  untouched. Disable it if your data is not MGCP-spec WGS84.
- **Smarter mismatch warning** — `[SR MISMATCH]` now names WHICH cells use
  which CRS (e.g. `GCS_WGS_1984: cell_e013n62; Unknown: cell_e014n62`),
  distinguishes repairable Unknown cases (`[SR REPAIR]` note) from genuine
  multi-CRS conflicts (reprojection still requires an Output Coordinate
  System), and flags FCs where NO source has a CRS (`[NO CRS]`).
- Manual repair alternative (no tool needed): copy the `.prj` from any
  sibling MGCP cell next to the orphan `.shp` (same base filename), or run
  ArcGIS *Define Projection* with WGS84 on the shapefile.

# <<< END OF FILE >>>
