# CCM Tool v0.60.8 — Version Information & Metadata

**Version:** 0.60.8
**Status:** Production Ready
**License:** GPL-2.0-or-later

---

## Version History

| Version | Status | Key Features |
|---------|--------|--------------|
| **0.60.8** | Production candidate | Step 3 Obstacle Detection rebuilt: inputs projected to AOI UTM before measuring (lake polygons in degrees were all flagged), vehicle CSV columns fixed (0 vehicles loaded), slope threshold from vehicle max off-road grade, contour interval auto-detected, Basic-licence path without the failing FeatureToPolygon attempt, stream-line hydro preferred, point obstacle symbology, group-name and UTM-rounding fixes |
| 0.60.7 | Production candidate | Waypoint Route map display made briefing-legible: route line changed from a magenta glow to a print-safe dark navy line with a directional arrowhead, on-map distance/time label added from fields that already existed but were never shown; End Point marker moved off a soft red (easy to confuse with the No-Go red used elsewhere) to a distinct blue, both points now labelled |
| 0.60.6 | Production candidate | Step 1 no longer falsely reports "Vegetation/Soil pre-processing complete" (and writes a never-created feature class into `ccm_project.json`) when the underlying mosaic or pre-processing actually failed -- `CCMVegPreprocessTool`/`CCMSoilPreprocessTool` now raise on failure instead of logging and returning normally |
| 0.60.5 | Production candidate | Fixed Step 2's "Vehicle CSV not found: None" misdiagnosis of a project where Step 1 had simply never run (project_gdb is no longer a reliable "Step 1 ran" signal since Step 0 also writes it); prerequisite check now driven by `extent_fc` and pulled into a standalone, unit-testable function |
| 0.60.4 | Production candidate | Removed two more unmeasured-AOI-coverage fabrication sites (confidence scoring, auto-recommendation composite score) beyond the one fixed in 0.60.3; fixed stale "v0.59.6"/older self-identifying version strings across module docstrings, log/help text, the recommendations HTML report, and the `.bat` launchers; `bump_version.py` and `package_ccm.py` hardened so this class of bug is auto-fixed on future bumps and gated at release time |
| 0.60.3 | Production candidate | Data Intelligence Scan false "no data" / false "Error" findings fixed: README/LICENSE files no longer catalogued as data, `.bil`/`.hdr` soil rasters no longer reported unclassified, and related report-accuracy defects |
| 0.60.2 | Production candidate | Cross-step state leaks, config contract, and release tooling: seven defects across Step 0-0b-1-2-3, including an `arcpy.env.mask` leak across tool runs and a "Project GDB not found: None" Step 2 failure |
| **0.60.1** | Production candidate | First packaged release of the single-root rewrite: pure-Python + licensed verification suites, three post-rewrite regressions found and fixed, `RUN_ARCGIS_SMOKE_TEST.bat` launcher parser fix, per-tool metadata sidecar rename gap closed |
| **0.60.0** | Production candidate (unpackaged) | Single-root project architecture: every step shares one Project Root Folder / `ccm_project.json` instead of a separate folder parameter per step; standalone Project Initializer GUI; Step 2 Vehicle-dropdown fallback + error fix |
| 0.59.7 | Production candidate | Data Intelligence correctness fixes against real field data (CRS unification) |
| 0.59.6 | Production candidate | Verification and report-output hardening |
| 0.59.5 | Production candidate | Version-synchronized release package |
| 0.59.4 | Production candidate | ArcGIS Pro toolbox module-isolation hotfix |
| 0.59.3 | Production candidate | Step 0b null-metadata hotfix |
| 0.59.2 | Production | All files finalized, comprehensive testing suite, release packaging |
| 0.58 | Production | Data Intelligence (Phases 1-2), Auto-Selection, Recommendations UI |
| 0.57 | Baseline | Factual data catalog scanning, v0.57 mobility models |

See `CHANGELOG.md` for the full, itemized release history (this table is a
summary) and `PROJECT_STATUS.md` / `TASKS.md` for development continuation
notes.

---

## What v0.60.x changed

**Single-root project architecture (v0.60.0).** Steps 0, 0b, 1, 2, and 3
previously each asked for their own folder parameter, independently typed,
with nothing carrying context from one step to the next. Every step now
takes one `project_root` parameter. Step 0 (and Step 0b) auto-create the
shared layout — `01_Input_Data/`, `02_Scan_Index/`, `03_Project.gdb` — and
write `ccm_project.json` as soon as a valid root is set, at dialog-validation
time rather than only at `execute()`. `ccm_project_config.py` is the one
canonical `ccm_project.json` reader/writer every step now shares.

**Verification and launcher fix (v0.60.1).** `test_single_root_pure_python.py`
(45/45 checks, no arcpy needed) and `tests/arcpy_smoke_test_v060_single_root.py`
(26/26 checks, licensed ArcGIS Pro) were added to verify the rewrite,
including the original bug report — Step 2's Vehicle dropdown coming up
empty when pointed at a Step 0b-only folder. That verification pass also
caught three regressions the parameter rename itself introduced (stale
`project_folder=` keyword in two smoke tests; a stale GDB filename check;
Step 3's GDB-resolution fallback never finding the new `03_Project.gdb`
name) and a two-layer `cmd.exe` batch-parser bug in
`RUN_ARCGIS_SMOKE_TEST.bat` (parentheses in `%ProgramFiles(x86)%`, both in
the variable's name and in its expanded value, breaking inside parenthesized
FOR/IF blocks) — all fixed and confirmed against a real licensed ArcGIS Pro
run (all 7 smoke tests passing).

---

## Phase Delivery Status (Data Intelligence / Step 0b family)

### Quality, Fitness, Confidence, Readiness Scoring
**Status:** Complete
- Quality Scoring: 8 metrics
- Fitness Scoring: role-specific
- Confidence Aggregation: model-level status
- Readiness Validation: 9-point checklist

### Auto-Selection Engine & Step 0b Integration
**Status:** Complete
- Auto-Selection: composite scoring with tie-breaking
- Step 0b Integration: 7-phase orchestrator

### Single-root rewrite (v0.60.0-0.60.1)
**Status:** Complete
- One `project_root` parameter shared by Steps 0, 0b, 1, 2, 3
- Canonical `ccm_project_config.py` read/write path
- Standalone Project Initializer GUI (`ccm_project_init.py`)
- Single-root-aware Data Scanner GUI
- Pure-Python + licensed-arcpy verification suites for the rewrite

---

## Scoring Formulas

### Quality Score (1–10)
```
composite = mean(temporal_age, crs_compat, coverage, resolution,
                 schema, duplication, metadata, accuracy)
```

### Fitness Score (1–10, role-specific)
```
DEM:       sum(raster, vertical_accuracy, void_free, resolution)
Soil:      sum(rci_calib, uscs_recognition, schema, moisture)
Vegetation: sum(format, data_type, resolution)
Hydrology:  vector_priority + connectivity + completeness
Contours:   elevation_field + interval + completeness
Extent:     polygon_required + coverage + schema
Vehicle:    csv_format + columns + completeness
```

### Confidence Level
```
High:     (quality+fitness)/2 >= 8 AND coverage >= 95%
Moderate: (quality+fitness)/2 >= 6 AND coverage >= 80%
Low:      (quality+fitness)/2 >= 3 AND coverage >= 50%
Unvetted: below Low threshold
```

### Recommendation Score (1–10)
```
composite = (quality*0.30) + (fitness*0.40) + (confidence*0.20) + (coverage/100*0.10)
```

---

## Test Suites

| Test Suite | Location | Needs arcpy? | Purpose |
|---|---|---|---|
| `tests/test_ccm.py`, `tests/test_v050.py` | `tests/` | No | Legacy regression suite |
| `tests/test_v057_data_intelligence.py`, `tests/test_ccm_step0b_integration.py` | `tests/` | No | Data Intelligence / Step 0b unit + integration tests |
| `test_single_root_pure_python.py` | project root | No | Single-root rewrite: config round-trip, Project Initializer, Step 0b integrator, `package_ccm.py` self-check (45 checks) |
| `tests/arcpy_smoke_test_step0.py` / `step1.py` / `step2.py` / `step3.py` | `tests/` | Yes (licensed ArcGIS Pro) | Steps 0-3 execute()-path smoke tests |
| `tests/arcpy_smoke_test_v060_single_root.py` | `tests/` | Yes (licensed ArcGIS Pro) | Single-root dialog-time behavior: Vehicle dropdown scenarios, GDB-resolution fallback (26 checks) |
| `tests/arcpy_smoke_test_step0b.py` / `step0b_integrated.py` | `tests/` | Yes (licensed ArcGIS Pro) | Factual and integrated Step 0b smoke tests |
| `MANUAL_TEST_CHECKLIST.md` | project root | Manual (ArcGIS Pro) | Human dialog walkthrough covering the same ground as the licensed smoke tests |

**Execution:**
```bat
RUN_TESTS.bat                  :: portable gate (pytest + pyflakes + this project's own verifier)
python test_single_root_pure_python.py    :: single-root rewrite, no arcpy needed
RUN_ARCGIS_SMOKE_TEST.bat      :: all 7 licensed ArcPy smoke tests (ArcGIS Pro open + signed in)
```

---

## Output Files (Step 0b), under `<project_root>/02_Scan_Index/`

| File | Format | Purpose |
|------|--------|---------|
| ccm_data_catalog.json | JSON | Factual inventory + normalized scoring records |
| ccm_quality_scores.json | JSON | Quality scores (8 metrics per dataset) |
| ccm_fitness_scores.json | JSON | Fitness scores (per dataset per role) |
| ccm_confidence_scores.json | JSON | Confidence levels + model aggregation |
| ccm_readiness_scores.json | JSON | Preprocessing readiness validation |
| ccm_recommendations.json | JSON | Machine-readable recommendations |
| CCM_Data_Intelligence_Report.html / .txt | HTML/text | Factual inventory report |
| CCM_Recommendations_Report.html | HTML | Styled recommendations with scores |

`ccm_project.json` itself lives directly in `<project_root>`, not in
`02_Scan_Index`.

---

## System Requirements

**Software:**
- Python 3.11+
- ArcGIS Pro (licensed, for toolbox integration and licensed smoke tests)
- Anaconda (for environment management)

**Environment:**
- `ccm_tool` conda environment (created via `CCM_anaconda.bat`)
- Dependencies: pytest, pyflakes (stdlib otherwise)

**Optional:**
- GDAL/OGR (GeoPackage + file-geodatabase enumeration)

---

## Module Inventory (partial — see README.md's Release files table for the full list)

### Core Scoring Engines
- `ccm_data_quality.py` — 8-metric quality scoring
- `ccm_data_fitness.py` — Role-specific fitness evaluation
- `ccm_data_confidence.py` — Confidence aggregation
- `ccm_data_readiness.py` — Preprocessing readiness checklist
- `ccm_data_selector.py` — Auto-selection recommendation engine

### Integration & Workflow
- `ccm_step0b_integration.py` — 7-phase orchestrator
- `ccm_step1_recommendations_ui.py` — Step 1 recommendations display
- `ccm_project_config.py` — canonical `ccm_project.json` read/write + `run_tool()`

### Standalone tools
- `ccm_project_init.py` — Project Initializer GUI (no arcpy needed)
- `CCM_Data_Scanner_GUI.py` — standalone, single-root-aware Data Intelligence scanner GUI

### Release tooling
- `ccm_version.py` — single source of truth for `VERSION` / `RELEASE_NAME`
- `bump_version.py` — automated version bump across modules + filenames
- `package_ccm.py` — blocking verifier + release ZIP packager

---

## Backward Compatibility

v0.57 output formats are preserved: catalog JSON structure, project config
keys (additive only), and v0.57 test suites all still pass. The v0.60.0
single-root rewrite is a parameter/config-location change, not an output
schema change — `02_Scan_Index/ccm_data_catalog.json` and its siblings keep
the same internal structure they always had, just at a new, consistent
per-project path.

---

## Deployment Checklist

**Before Release:**
- Portable verification (`RUN_TESTS.bat`) passing
- `test_single_root_pure_python.py` passing (45/45)
- Licensed ArcPy smoke tests (`RUN_ARCGIS_SMOKE_TEST.bat`) passing on a real
  ArcGIS Pro install (all 7)
- Version bumped via `bump_version.py`, including the four per-tool
  `.pyt.xml` metadata sidecars it does not rename automatically
- Release package built via `package_ccm.py` (updates `VERSION.txt`, builds
  the ZIP with SHA-256/MD5 sidecars)

**Installation:**
1. Extract ZIP: `unzip CCM_Tool_v0.60.1.zip && cd CCM_Tool_v0.60.1`
2. Create environment: `CCM_anaconda.bat`
3. Verify: `RUN_TESTS.bat`
4. Add to ArcGIS Pro: Toolboxes → Add Toolbox → `CCM_Tool_v0.60.1.pyt`

**Workflow:**
1. (Optional) `ccm_project_init.py` to create the project layout ahead of time
2. Step 0 / Step 0b: Load MGCP Data / Data Intelligence Scan
3. Step 1: Project Setup & Preprocess (review + override + preprocessing)
4. Steps 2-4: Mobility analysis, all pointed at the same Project Root Folder

---

## Support & Documentation

- **QUICK_START.md** — Operator workflow guide
- **CHANGELOG.md** — Complete release notes
- **README.md** — Project overview
- **TOOLBOX_INTEGRATION.md** — Module registration and hand-off details
- **CCM_Tool_v0.60.1_User_Manual.docx** — Complete manual
- **MANUAL_TEST_CHECKLIST.md** — Manual ArcGIS Pro verification walkthrough
- **PROJECT_STATUS.md** / **TASKS.md** — Development continuation notes

---

## Contact & License

**Copyright:** (c) 2026 Eui Soo SON
**License:** GPL-2.0-or-later

---

**CCM Tool v0.60.1 — Production Ready**

# <<< END OF FILE >>>
