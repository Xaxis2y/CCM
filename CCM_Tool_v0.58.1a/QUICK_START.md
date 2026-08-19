# CCM Tool v0.58.1 — Quick Start

## 1. Prepare the environment

Open **Anaconda Prompt**, change to this folder, and run:

```bat
CCM_anaconda.bat
```

This creates (or refreshes) the `ccm_tool` environment and leaves this
Anaconda Prompt activated inside it — you do not need to run
`conda activate ccm_tool` yourself afterward.

Optional GDAL/OGR support for GeoPackage and file-geodatabase layer
enumeration:

```bat
CCM_anaconda.bat ccm_tool_gdal --with-gdal
set CCM_ENV_NAME=ccm_tool_gdal
```

## 2. Run the verification

```bat
RUN_V058_TESTS.bat
```

The log is saved in `verification_logs`. A successful run ends with
`All blocking verification checks passed`. This includes v0.57 regression tests
plus v0.58.1 scoring engine + auto-selection tests.

## 3. Add the toolbox to ArcGIS Pro

1. Open ArcGIS Pro and a project.
2. In the Catalog pane, right-click **Toolboxes** → **Add Toolbox**.
3. Select `CCM_Tool_v0.58.1.pyt` in this folder.
4. Confirm that the toolbox shows Steps 0, 0b, 1, 2, 3, and 4.

## 4. Recommended first run (v0.58.1 workflow)

1. Run **Step 0 — Load MGCP Data** if raw MGCP cells need consolidation.

2. Run **Step 0b — Data Intelligence Scan** on the complete data-root folder.
   This now includes:
   - Factual inventory (v0.57)
   - Quality, Fitness, Confidence scoring (NEW v0.58.1)
   - Auto-selection recommendations per role (NEW v0.58.1)

3. Review the generated reports:
   - `CCM_Data_Intelligence_Report.html` — factual catalog (v0.57)
   - `CCM_Recommendations_Report.html` — auto-recommended sources (NEW v0.58.1)
   - `ccm_recommendations.json` — machine-readable recommendations (NEW v0.58.1)

4. Accept or override recommendations in **Step 1 — Project Setup & Pre-process**.
   - Recommended sources are displayed at Step 1 startup
   - You can use a different source if you prefer (e.g., based on local experience)
   - Each override is logged for reproducibility

5. Run Step 2 for each vehicle, then Step 3 or Step 4 as required.

## 5. Standalone scan options

Command-line scan:

```bat
RUN_DATA_SCAN.bat "D:\GIS\Source_Data" "D:\GIS\Project" "D:\GIS\Source_Data\Extent\AOI.shp"
```

GUI scan:

```bat
CCM_Data_Scanner.bat
```

## 6. ArcPy smoke test

ArcPy is provided by a licensed ArcGIS Pro installation. Open and sign in to
ArcGIS Pro, then run:

```bat
RUN_ARCGIS_SMOKE_TEST.bat
```

The script creates test data only under `verification_artifacts` and checks
ArcPy metadata, container enumeration, reports, and source-data safety.

## 7. Help and troubleshooting

- Full operator reference: `CCM_Tool_v0.58.1_User_Manual.docx` (Section 2.3 covers auto-selection).
- Integration details: `TOOLBOX_INTEGRATION.md`.
- Release notes: `CHANGELOG_v0.58.1.md` (new features) and `CHANGELOG_v0.57.md` (v0.57 baseline).
- Data Intelligence & Auto-Selection guide: See `CCM_v0.58.1_ROADMAP.md` for architecture + Phase 1–2 details.
- If `conda` is not found, start the command from **Anaconda Prompt**.
- If ArcPy initialization fails, open/sign in to ArcGIS Pro and rerun the
  ArcPy smoke test from a clean Anaconda Prompt.
- For recommendations troubleshooting: Check `ccm_quality_scores.json`, `ccm_fitness_scores.json`,
  and `ccm_recommendations.json` in your project output folder for detailed scoring breakdowns.

# <<< END OF FILE >>>
