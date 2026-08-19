# CCM Tool v0.57

Integrated Cross-Country Mobility (CCM) toolbox for ArcGIS Pro.

This release combines the stable v0.55.1 Steps 0-4 toolbox with the validated
v0.56 Data Intelligence engine. The original `CCM_Tool_v0.55.1` and
`CCM_DataIntelligence_v0.56.4_work` folders are not modified.

## What v0.57 adds

Step 0b, **Data Intelligence Scan**, is now registered in the toolbox between
Step 0 and Step 1. It performs a factual inventory of a data root:

- identifies likely DEM, soil, vegetation, hydrology, contour, MGCP, vehicle,
  moisture, and extent datasets;
- reads available raster, vector, table, CRS, schema, and container metadata;
- enumerates readable GeoPackage and file-geodatabase layers when ArcPy or
  GDAL/OGR is available;
- records duplicate locations, unsupported files, limitations, and missing
  roles; and
- writes JSON, HTML, TXT, and additive `ccm_project.json` hand-off fields.

The scan reports facts only. Data Quality, CCM Fitness, Confidence, Readiness,
automatic source selection, and substitution recommendations are not silently
calculated in this release.

## Workflow

1. **Step 0 — Load MGCP Data** (optional): consolidate MGCP source cells.
2. **Step 0b — Data Intelligence Scan** (recommended): inventory the complete
   data root and review the factual report.
3. **Step 1 — Project Setup & Pre-process**: select and preprocess the inputs.
4. **Step 2 — Generate Mobility Map**: compute vehicle speed surfaces.
5. **Step 3 — Advanced Analysis**: reason maps, reachability, comparison,
   obstacles, and waypoint routing.
6. **Step 4 — Compare Two Vehicles** (optional): compare existing surfaces.

The existing mobility engine and Steps 0-4 behavior remain intact. Step 0b does
not auto-select a source; the analyst confirms each Step 1 input.

## Quick start in Anaconda Prompt

From this folder:

```bat
CCM_anaconda.bat
RUN_V057_TESTS.bat
```

The environment defaults to `ccm_tool` and installs Python 3.11, pytest,
pyflakes, and PyInstaller. `CCM_anaconda.bat` also runs `conda activate` for
you, so this Anaconda Prompt is left inside the `ccm_tool` environment when
it finishes — no separate `conda activate ccm_tool` step needed. (The
`RUN_*.bat` launchers dispatch into the environment themselves via
`conda run -n`, so they work either way; activation just makes plain
`python`/`pytest` commands typed directly in this prompt use the right
environment too.) Optional GeoPackage/file-geodatabase enumeration:

```bat
CCM_anaconda.bat ccm_tool_gdal --with-gdal
set CCM_ENV_NAME=ccm_tool_gdal
RUN_V057_TESTS.bat
```

ArcPy is supplied by a licensed ArcGIS Pro installation and is not installed by
the Anaconda script. Run the licensed smoke test from Anaconda Prompt after
ArcGIS Pro has been opened and signed in:

```bat
RUN_ARCGIS_SMOKE_TEST.bat
```

For a real data scan:

```bat
RUN_DATA_SCAN.bat "D:\GIS\Source_Data" "D:\GIS\Project" "D:\GIS\Source_Data\Extent\AOI.shp"
```

The GUI launcher is `CCM_Data_Scanner.bat`.

## Toolbox registration

In ArcGIS Pro, add `CCM_Tool_v0.57.pyt` from this folder. The toolbox should
show six entries: Step 0, Step 0b, Step 1, Step 2, Step 3, and Step 4.

Step 0b writes these files to the selected project folder:

- `ccm_data_catalog.json` — machine-readable factual inventory;
- `CCM_Data_Intelligence_Report.html` — human-readable report;
- `CCM_Data_Intelligence_Report.txt` — plain-text report; and
- additive `data_root` and `data_catalog_json` keys in `ccm_project.json`.

Existing project configuration keys are preserved. Step 1 may display catalog
candidates, but it must not silently choose or replace an input.

## Release files

| File | Purpose |
|---|---|
| `CCM_Tool_v0.57.pyt` | ArcGIS Pro toolbox entry point |
| `ccm_step0b_intelligence.py` | Step 0b toolbox class and CLI |
| `ccm_data_catalog.py` | Inventory, metadata, duplicates, and coverage |
| `ccm_data_report.py` | Factual TXT and HTML reports |
| `ccm_data_sources.py` | Descriptive source/product reference data |
| `CCM_anaconda.bat` | Dedicated Anaconda environment setup |
| `RUN_V057_TESTS.bat` | Blocking integrated verification |
| `RUN_ARCGIS_SMOKE_TEST.bat` | Licensed ArcPy/GDB smoke test |
| `QUICK_START.html` | One-page operator guide |
| `CCM_Tool_v0.57_User_Manual.docx` | Full English operator manual |
| `package_ccm_v057.py` | Verification and release packager |
| `build.py` | Syntax/integrity checker and ZIP packager |
| `ccm_version.py` | Single-source `VERSION`/`RELEASE_NAME` |
| `bump_version.py` | One-command version-bump automation |
| `ccm_data_audit.py` | Calibration-data (`soil_rci.csv`/`Vehicles_Can.csv`) sanity checker |
| `ccm_debug.py` | Opt-in (`CCM_DEBUG=1`) diagnostic hook |

## Verification

`RUN_V057_TESTS.bat` runs static checks, pyflakes, the legacy v0.55 regression
suite, the v0.57 Data Intelligence tests, fixture generation, an end-to-end
scan, and output-schema validation. Logs and generated fixtures are written
under `verification_logs` and `verification_artifacts`; they are excluded from
the release ZIP.

The ArcPy smoke test validates ArcGIS metadata probing, GeoPackage/file-GDB
enumeration, report outputs, and source-data safety. A valid ArcGIS Pro product
license is required for that test. `RUN_ARCGIS_SMOKE_TEST.bat` runs all five
step smoke tests (Step 0, 1, 2, 3, and 0b) explicitly and prints a combined
pass/fail summary.

## Version and scope

`VERSION.txt`, `CHANGELOG_v0.57.md`, the toolbox sidecars, tests, and documents
are aligned to v0.57. Historical release notes remain under `archives/`.

License: GPL-2.0-or-later. Copyright (c) 2026 Eui Soo SON.

# <<< END OF FILE >>>
