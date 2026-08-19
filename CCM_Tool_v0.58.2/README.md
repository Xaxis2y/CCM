# CCM Tool v0.58.2

Integrated Cross-Country Mobility (CCM) toolbox for ArcGIS Pro.

This release combines the complete Steps 0-4 toolbox with the factual Step 0b
Data Intelligence inventory and its Quality, Fitness, Confidence, Readiness,
and reviewable recommendation outputs. The original `v0.58.1` and
`v0.58.1a` folders remain unchanged.

## What v0.58.2 adds

Step 0b scans one complete data-root folder and:

- identifies likely DEM, soil, vegetation, hydrology, contour, MGCP, vehicle,
  moisture, and extent datasets;
- reads available raster, vector, table, CRS, schema, container, duplicate,
  and coverage metadata;
- calculates quality scores across the available evidence;
- evaluates dataset fitness for CCM roles and calculates confidence;
- writes a readiness status that remains `Not Yet Run` until Step 1 outputs are
  available; and
- creates reviewable role recommendations without modifying source data or
  silently replacing a user's Step 1 selection.

## Workflow

1. **Step 0 — Load MGCP Data** (optional): consolidate MGCP source cells.
2. **Step 0b — Data Intelligence Scan**: scan the complete data root and
   review the factual and recommendation reports.
3. **Step 1 — Project Setup & Pre-process**: review recommendations and select
   the actual inputs explicitly.
4. **Step 2 — Generate Mobility Map**: compute vehicle speed surfaces.
5. **Step 3 — Advanced Analysis**: reason maps, reachability, comparison,
   obstacles, and waypoint routing.
6. **Step 4 — Compare Two Vehicles** (optional): compare existing surfaces.

## Quick start in Anaconda Prompt

Run the environment setup from **Anaconda Prompt**, not the base environment:

```bat
CCM_anaconda.bat
RUN_V0582_TESTS.bat
```

The setup creates or refreshes the dedicated `ccm_tool` environment and
installs pytest, pyflakes, and PyInstaller there. Do not install these
packages into `base`; dependency conflicts in the base environment can make
the validation result unreliable.

For optional GDAL/OGR support:

```bat
CCM_anaconda.bat ccm_tool_gdal --with-gdal
set CCM_ENV_NAME=ccm_tool_gdal
RUN_V0582_TESTS.bat
```

For a real data scan:

```bat
RUN_DATA_SCAN.bat "D:\GIS\Source_Data" "D:\GIS\Project" "D:\GIS\Source_Data\Extent\AOI.shp"
```

ArcPy is supplied by a licensed ArcGIS Pro installation. After opening and
signing in to ArcGIS Pro, run the licensed smoke tests from Anaconda Prompt:

```bat
RUN_ARCGIS_SMOKE_TEST.bat
```

## Toolbox registration

In ArcGIS Pro, add `CCM_Tool_v0.58.2.pyt` from this folder. The toolbox should
show six entries: Step 0, Step 0b, Step 1, Step 2, Step 3, and Step 4.

Step 0b writes these files to the selected project folder:

- `ccm_data_catalog.json` — factual inventory plus normalized scoring records;
- `CCM_Data_Intelligence_Report.html` and `.txt` — factual reports;
- `ccm_quality_scores.json` — eight evidence-based quality metrics;
- `ccm_fitness_scores.json` — role-specific dataset evaluations;
- `ccm_confidence_scores.json` — role and model confidence;
- `ccm_readiness_scores.json` — current readiness status;
- `ccm_recommendations.json` — machine-readable reviewable selections; and
- `CCM_Recommendations_Report.html` — human-readable recommendation report.

Step 1 displays the recommendations at startup. Its explicit parameters remain
authoritative, and any override is still the analyst's decision.

## Release files

| File | Purpose |
|---|---|
| `CCM_Tool_v0.58.2.pyt` | ArcGIS Pro toolbox entry point |
| `ccm_step0b_intelligence.py` | Step 0b toolbox class, factual engine, and CLI |
| `ccm_step0b_integration_v058.py` | Integrated scoring and recommendation workflow |
| `ccm_data_quality.py` | Quality scoring engine |
| `ccm_data_fitness.py` | Role fitness engine |
| `ccm_data_confidence.py` | Confidence engine |
| `ccm_data_readiness.py` | Step 1 readiness engine |
| `ccm_data_selector.py` | Reviewable role recommendation engine |
| `ccm_step1_recommendations_ui.py` | Step 1 recommendation display |
| `RUN_V0582_TESTS.bat` | Anaconda verification launcher |
| `RUN_ARCGIS_SMOKE_TEST.bat` | Licensed ArcPy smoke launcher |
| `package_ccm_v0582.py` | Blocking verifier and ZIP packager |
| `CCM_Tool_v0.58.2_User_Manual.docx` | Full English operator manual |

## Verification

`RUN_V0582_TESTS.bat` runs static syntax/version checks, pyflakes, calibration
audits, the legacy regression suite, the factual inventory tests, the v0.58.2
integration tests, fixture generation, and an end-to-end scan that verifies all
factual, scoring, recommendation, and project-config outputs. Generated logs
and fixtures are excluded from the release ZIP.

The ArcPy launcher runs the Steps 0-4 smoke tests, the factual Step 0b smoke
test, and the v0.58.2 integrated Step 0b smoke test. ArcPy and a valid ArcGIS
Pro license are required for that gate.

License: GPL-2.0-or-later. Copyright (c) 2026 Eui Soo SON.

# <<< END OF FILE >>>
