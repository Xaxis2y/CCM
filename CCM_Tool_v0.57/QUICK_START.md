# CCM Tool v0.57 — Quick Start

## 1. Prepare the environment

Open **Anaconda Prompt**, change to this folder, and run:

```bat
CCM_anaconda.bat
```

Optional GDAL/OGR support for GeoPackage and file-geodatabase layer
enumeration:

```bat
CCM_anaconda.bat ccm_tool_gdal --with-gdal
set CCM_ENV_NAME=ccm_tool_gdal
```

## 2. Run the verification

```bat
RUN_V057_TESTS.bat
```

The log is saved in `verification_logs`. A successful run ends with
`All blocking verification checks passed`.

## 3. Add the toolbox to ArcGIS Pro

1. Open ArcGIS Pro and a project.
2. In the Catalog pane, right-click **Toolboxes** → **Add Toolbox**.
3. Select `CCM_Tool_v0.57.pyt` in this folder.
4. Confirm that the toolbox shows Steps 0, 0b, 1, 2, 3, and 4.

## 4. Recommended first run

1. Run **Step 0 — Load MGCP Data** if raw MGCP cells need consolidation.
2. Run **Step 0b — Data Intelligence Scan** on the complete data-root folder.
3. Review `CCM_Data_Intelligence_Report.html` and
   `ccm_data_catalog.json` in the project output folder.
4. Confirm the data paths manually in **Step 1 — Project Setup & Pre-process**.
5. Run Step 2 for each vehicle, then Step 3 or Step 4 as required.

Step 0b reports factual inventory only. It does not automatically select a
dataset or calculate Quality, Fitness, Confidence, or Readiness scores.

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

- Full operator reference: `CCM_Tool_v0.57_User_Manual.docx`.
- Integration details: `TOOLBOX_INTEGRATION.md`.
- Release notes: `CHANGELOG_v0.57.md`.
- If `conda` is not found, start the command from **Anaconda Prompt**.
- If ArcPy initialization fails, open/sign in to ArcGIS Pro and rerun the
  ArcPy smoke test from a clean Anaconda Prompt.

# <<< END OF FILE >>>
