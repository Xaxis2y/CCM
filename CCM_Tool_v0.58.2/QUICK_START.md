# CCM Tool v0.58.2 — Quick Start

## 1. Prepare the environment

Open **Anaconda Prompt** and run the dedicated environment setup. Do not use
the `base` environment for this project.

```bat
CCM_anaconda.bat
```

This creates or refreshes the `ccm_tool` environment and installs the portable
verification dependencies there.

## 2. Run the portable verification

```bat
RUN_V0582_TESTS.bat
```

The blocking gate checks syntax, versions, calibration tables, legacy tests,
factual inventory behavior, integrated scoring/recommendations, and a complete
fixture scan. Send the generated log if the gate reports a failure.

## 3. Add the toolbox to ArcGIS Pro

1. Open ArcGIS Pro and a project.
2. In the Catalog pane, select **Toolboxes** → **Add Toolbox**.
3. Select `CCM_Tool_v0.58.2.pyt`.
4. Confirm that the toolbox shows Steps 0, 0b, 1, 2, 3, and 4.

## 4. Recommended run order

1. Run **Step 0 — Load MGCP Data** if raw MGCP cells need consolidation.
2. Run **Step 0b — Data Intelligence Scan** on the complete data-root
   folder, optionally supplying the AOI.
3. Review the factual report and the recommendation report.
4. In **Step 1 — Project Setup & Pre-process**, review the displayed
   recommendations and supply the actual inputs explicitly. The tool does not
   silently replace a parameter.
5. Run Step 2 for each vehicle, then Step 3 or Step 4 as required.

## 5. Step 0b outputs

The project folder receives:

- `ccm_data_catalog.json` — factual inventory and normalized scoring records;
- `CCM_Data_Intelligence_Report.html` and `.txt` — factual inventory reports;
- `ccm_quality_scores.json` — quality dimensions and reasoning;
- `ccm_fitness_scores.json` — role-specific fitness evaluations;
- `ccm_confidence_scores.json` — role and model confidence;
- `ccm_readiness_scores.json` — readiness status pending Step 1;
- `ccm_recommendations.json` — reviewable role recommendations; and
- `CCM_Recommendations_Report.html` — readable recommendation report.

## 6. Standalone scan options

Integrated scan:

```bat
RUN_DATA_SCAN.bat "D:\GIS\Source_Data" "D:\GIS\Project" "D:\GIS\Source_Data\Extent\AOI.shp"
```

Factual-only compatibility mode:

```bat
python ccm_step0b_intelligence.py --data-root "D:\GIS\Source_Data" --factual-only
```

The GUI launcher is `CCM_Data_Scanner.bat`.

## 7. ArcPy smoke test

ArcPy is part of licensed ArcGIS Pro and is not installed by
`CCM_anaconda.bat`. Open and sign in to ArcGIS Pro, then run from Anaconda
Prompt:

```bat
RUN_ARCGIS_SMOKE_TEST.bat
```

This runs the Steps 0-4 smoke tests, the factual Step 0b smoke test, and the
v0.58.2 integrated Step 0b smoke test.

## 8. Help and troubleshooting

- `TOOLBOX_INTEGRATION.md` explains module registration and output hand-off.
- `CHANGELOG_v0.58.2.md` records the release changes and known boundaries.
- `CCM_Tool_v0.58.2_User_Manual.docx` is the full operator reference.
- If `conda` is not found, restart from Anaconda Prompt.
- If ArcPy initialization fails, open/sign in to ArcGIS Pro and rerun the
  ArcPy smoke test from a clean Anaconda Prompt.

# <<< END OF FILE >>>
