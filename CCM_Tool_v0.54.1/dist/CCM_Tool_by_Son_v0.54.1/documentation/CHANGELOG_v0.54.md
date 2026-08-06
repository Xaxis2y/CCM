# CHANGELOG — v0.54.1 (2026-07-21)

## Rebrand + relicense — "CCM Tool by Son"

"MCE CCM Tool" is renamed **"CCM Tool by Son"** throughout the project, and
the toolbox is relicensed under **SPDX-License-Identifier: GPL-2.0-or-later**
(previously "All Rights Reserved"). No functional / geoprocessing behaviour
changed.

### Naming

- Toolbox renamed `MCE_CCM_v0.54.0.pyt` → `CCM_Tool_by_Son_v0.54.1.pyt`
  (all `.pyt.xml` sidecars renamed to match); `toolname` constant
  `"MCE_CCM_Tool"` → `"CCM_Tool_by_Son"`; toolbox `alias` `"MCECCMTool"` →
  `"CCMToolBySon"`.
- `ccm_map_display.MAP_NAME` constant `"MCE_CCM_MAP"` → `"CCM_TOOL_BY_SON_MAP"`
  (the Step 3 auto-load group/map name shown in ArcGIS Pro's Contents pane);
  updated everywhere it's referenced in `ccm_step3_advanced.py`.
- Release zip renamed `MCE_CCM_Tool_v<VERSION>.zip` → `CCM_Tool_by_Son_v<VERSION>.zip`
  (`build.py`); user manual renamed to `CCM_Tool_by_Son_v0.54.1_User_Manual.docx`.
- All "MCE CCM Tool" / "MCE_CCM_Tool" / "MCE_CCM" text mentions updated across
  every module, test, and doc — **including the historical
  `CHANGELOG_v0.45.md`–`CHANGELOG_v0.53.md` files** (product-name mentions
  only; version numbers and other historical facts in those files are
  untouched). The two mentions of "MCE" as the *technique* name (Multi-Criteria
  Evaluation, e.g. in `ccm_step2_mobility.py` and the manual's Section 1.1) are
  intentionally left as-is — that acronym describes the analysis method, not
  the product name.

### License

- New header on every module / test / `.pyt` file:
  ```
  # SPDX-License-Identifier: GPL-2.0-or-later
  # Copyright (c) 2026 Eui Soo SON (Beta)
  ```
  replacing the previous `Copyright (c) 2026  Eui Soo Son` / `All Rights
  Reserved.` block. `README.md`'s Copyright section and the user manual's
  title page updated to match; the manual's Section 10.4 Version History
  gains this row.

### Version bump

- All module `VERSION` constants → `0.54.1`; `.pyt` `toolversion` → `0.54.1`.
  `README.md` / `PROJECT_STATUS.md` / `TASKS.md` / `CLAUDE.md` updated to
  match (current-version lines bumped; historical rows/mentions left as
  written).

---

# CHANGELOG — v0.54.0 (2026-07-21)

## Smart CRS/projection warnings (Steps 0, 1, 3, 4) + User Manual CRS chapter

Step 1's Analysis Extent has always blocked on a Geographic CRS ("CCM
requires a Projected CRS... e.g. UTM"). This release extends the same idea —
non-blocking warnings, not hard errors — to every other step that consumes
spatial data, and adds a beginner-level explanation of *why* to the User
Manual.

### New shared helpers — `ccm_coords.py`

- **`describe_spatial_reference(path)`** — safe `arcpy.Describe` wrapper;
  returns `(sr_type, sr_name, factory_code)` or `(None, None, None)` on any
  failure (missing/locked/corrupt data), so callers never need their own
  try/except around it.
- **`geographic_crs_warning(layer_label, sr_name, blocking=False)`** —
  standard explanatory text for a layer using a Geographic CRS: why CCM
  needs metres, and how to fix it (Export Features → UTM zone).
- **`crs_mismatch_warning(layer_label, layer_sr, ref_label, ref_sr)`** —
  standard text for two layers that are both projected but use *different*
  systems (still misaligns results even though neither is "wrong" on its
  own).
- 5 new unit tests (160 total, 157 passed / 3 skipped).

### Step 0 — Load MGCP Data (`ccm_step0_mgcp.py`)

- **Output Coordinate System** now warns (non-blocking) if left blank or set
  to a Geographic CRS: MGCP source data is WGS84 by specification, so doing
  nothing here means Step 1 will need a separate Export Features pass later.
  Recommends setting this to the target UTM zone now instead.

### Step 1 — Project Setup & Pre-process (`ccm_step1_setup.py`)

- Analysis Extent's existing blocking Geographic-CRS check is unchanged.
- **New:** once the Extent is confirmed Projected, DEM, Slope Regions,
  Contour Lines, Raw Soil FC/Raster, Pre-processed Soil FC, Pre-processed
  Vegetation FC, and every Hydrology layer are each checked — warning if the
  layer is Geographic, or if it's Projected but uses a **different** system
  than the Analysis Extent (factory/EPSG code comparison). Hydrology
  (multi-value) aggregates all offending layers into one message per
  parameter so warnings don't overwrite each other.

### Step 3 — Advanced Analysis (`ccm_step3_advanced.py`)

- Speed Surface FC — normally auto-filled from Step 1's already-validated
  CRS, but a manual override is now checked: warns if Geographic. (Combined
  with the existing missing-output-fields check into one message so neither
  overwrites the other.)
- Obstacle Detection's Contour Lines FC / Hydro FC — warns if Geographic, or
  if projected but mismatched against the Speed Surface FC.

### Step 4 — Compare Two Vehicles (`ccm_vehicle_compare.py`)

- `updateMessages()` was a no-op (`pass`) — implemented from scratch: warns
  if either Vehicle A/B Speed Surface is Geographic, and warns if both are
  projected but use **different** coordinate systems (a cross-projection
  comparison would silently misalign, producing meaningless BOTH_GO /
  A_ONLY / B_ONLY output).

### User Manual (`CCM_Tool_by_Son_v0.54.0_User_Manual.docx`)

- **New Section 3.4 — Coordinate Reference System (CRS) Requirements.**
  Beginner-level explanation of Geographic vs. Projected CRS, why CCM's
  geoprocessing needs metres, how to find/apply the right UTM zone in
  ArcGIS Pro, a worked example, and a summary table of which parameter in
  each step now carries a smart warning.
- Section 1.4 heading and the step-overview table extended to cover Step 4;
  Section 2.2's "three tools" quick-start line corrected to five. Sections
  2.5 (Step 0), 4.1 (Step 1 core parameters), 5 (Step 2 intro), and 6.3
  (Vehicle Comparison / standalone Step 4) each gained a short
  data-requirements-and-projection note.
- Section 3.3's Data Requirements table and 4.1's Core Parameters table
  Notes/Description columns now mention the same-CRS expectation. Appendix C
  gained a CRS row. Section 9.1 (Troubleshooting) gained four new rows for
  the new warnings, plus a stale `CCM_Tool_by_Son_v0.51.0.pyt` filename reference
  corrected to the current version.
- Section 10.4 Version History: this row.
- Title page and all body version references bumped 0.53.3 → 0.54.0.

### Version bump

- All module `VERSION` constants → `0.54.0`; toolbox renamed
  `CCM_Tool_by_Son_v0.53.3.pyt` → `CCM_Tool_by_Son_v0.54.0.pyt` (sidecars, `build.py`, the
  test suite, README / PROJECT_STATUS / TASKS, and the user manual updated
  to match).

---
