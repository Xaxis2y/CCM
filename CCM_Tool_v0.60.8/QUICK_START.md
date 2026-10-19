# CCM Tool v0.60.1 — Quick Start

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
RUN_TESTS.bat
```

The blocking gate checks syntax, versions, calibration tables, legacy tests,
factual inventory behavior, integrated scoring/recommendations, and a complete
fixture scan. `test_single_root_pure_python.py` additionally checks every
pure-Python part of the single-root project layout (see step 3 below) without
needing arcpy. Send the generated log if either gate reports a failure.

## 3. Set up a project folder (single-root layout)

Every step now shares ONE **Project Root Folder** instead of a separate
folder per step. You can either:

- let **Step 0** or **Step 0b** create the layout automatically the first
  time you point either one at a folder, or
- create it ahead of time with the standalone **Project Initializer**:
  double-click `ccm_project_init.py` (or the frozen `.exe` built by
  `build_project_init_exe.py`), pick a folder, and it creates:

  ```
  <Project Root>/
      ccm_project.json
      01_Input_Data/
      02_Scan_Index/
      03_Project.gdb        (once Step 0 or Step 1 runs)
  ```

Use the same Project Root Folder in every step from here on.

## 4. Add the toolbox to ArcGIS Pro

1. Open ArcGIS Pro and a project.
2. In the Catalog pane, select **Toolboxes** → **Add Toolbox**.
3. Select `CCM_Tool_v0.60.1.pyt`.
4. Confirm that the toolbox shows Steps 0, 0b, 1, 2, 3, and 4.

## 5. Recommended run order

1. Run **Step 0 — Load MGCP Data** if raw MGCP cells need consolidation.
   Point it at your Project Root Folder.
2. Run **Step 0b — Data Intelligence Scan** on the same Project Root Folder,
   optionally supplying the AOI. It scans `01_Input_Data` if that already
   has data in it, or the root itself otherwise.
3. Review the factual report and the recommendation report in
   `02_Scan_Index`.
4. In **Step 1 — Project Setup & Pre-process**, point at the same Project
   Root Folder, review the displayed recommendations, and supply the actual
   inputs explicitly. The tool does not silently replace a parameter.
5. Run Step 2 for each vehicle — the Vehicle dropdown auto-fills from the
   project's vehicle CSV once Step 1 has run — then Step 3 or Step 4 as
   required.

## 6. Step 0b outputs

`<Project Root>/02_Scan_Index` receives:

- `ccm_data_catalog.json` — factual inventory and normalized scoring records;
- `CCM_Data_Intelligence_Report.html` and `.txt` — factual inventory reports;
- `ccm_quality_scores.json` — quality dimensions and reasoning;
- `ccm_fitness_scores.json` — role-specific fitness evaluations;
- `ccm_confidence_scores.json` — role and model confidence;
- `ccm_readiness_scores.json` — readiness status pending Step 1;
- `ccm_recommendations.json` — reviewable role recommendations; and
- `CCM_Recommendations_Report.html` — readable recommendation report.

`ccm_project.json` itself lives directly in the Project Root Folder.

## 7. Standalone scan options

Integrated scan against a Project Root Folder:

```bat
RUN_DATA_SCAN.bat "D:\GIS\Project" "D:\GIS\Project\01_Input_Data\Extent\AOI.shp"
```

Factual-only compatibility mode:

```bat
python ccm_step0b_intelligence.py --data-root "D:\GIS\Project" --factual-only
```

The GUI launcher is `CCM_Data_Scanner.bat`.

## 8. ArcPy smoke test

ArcPy is part of licensed ArcGIS Pro and is not installed by
`CCM_anaconda.bat`. Open and sign in to ArcGIS Pro, then run from Anaconda
Prompt:

```bat
RUN_ARCGIS_SMOKE_TEST.bat
```

This runs all seven licensed tests: the Steps 0-3 smoke tests, the
single-root dialog-behavior smoke test (Vehicle dropdown scenarios and the
Step 3 GDB-resolution fallback), the factual Step 0b smoke test, and the
integrated Step 0b smoke test. Results and logs land under
`verification_logs\`.

## 9. Help and troubleshooting

- `TOOLBOX_INTEGRATION.md` explains module registration and output hand-off.
- `CHANGELOG.md` records the release changes and known boundaries.
- `CCM_Tool_v0.60.1_User_Manual.docx` is the full operator reference.
- `MANUAL_TEST_CHECKLIST.md` is a step-by-step ArcGIS Pro dialog checklist
  covering the same ground as `RUN_ARCGIS_SMOKE_TEST.bat`, for a human
  walkthrough instead of an automated run.
- If `conda` is not found, restart from Anaconda Prompt.
- If ArcPy initialization fails, open/sign in to ArcGIS Pro and rerun the
  ArcPy smoke test from a clean Anaconda Prompt.
- If a step's dropdown or config-driven field looks empty, confirm every
  step is pointed at the same Project Root Folder, and that Step 1 (which
  writes the project geodatabase and vehicle CSV path) has actually been
  run there.

# <<< END OF FILE >>>
