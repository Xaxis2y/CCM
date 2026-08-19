# CCM Tool v0.58.2 Integration Guide

This is the combined release copy of the complete Steps 0-4 toolbox and the
Step 0b Data Intelligence/scoring modules. The original `v0.58.1` and
`v0.58.1a` folders are not modified.

## Toolbox registration

`CCM_Tool_v0.58.2.pyt` imports and registers six tools:

1. Step 0 — Load MGCP Data
2. Step 0b — Data Intelligence Scan
3. Step 1 — Project Setup & Pre-process
4. Step 2 — Generate Mobility Map
5. Step 3 — Advanced Analysis
6. Step 4 — Compare Two Vehicles

The toolbox uses guarded imports so ArcGIS displays an actionable unavailable
tool if a module cannot load. The normal v0.58.2 Step 0b import is
`ccm_step0b_intelligence.CCMDataIntelligenceTool`; that class calls the
integrated workflow in `ccm_step0b_integration_v058.py`.

## Step 0b flow

The integrated flow is:

1. Build the factual catalog using `ccm_data_catalog.py`.
2. Normalize the factual role records into the scoring-engine contract.
3. Calculate quality, fitness, and confidence outputs.
4. Write the current readiness status (`Not Yet Run` until Step 1).
5. Generate role recommendations.
6. Write factual reports, scoring JSON files, recommendation JSON/HTML, and
   additive project configuration links.

The factual `run_scan()` function remains available for compatibility and can
be selected with the CLI `--factual-only` option. The default CLI and ArcGIS
toolbox entry point use the integrated workflow.

## Project hand-off

Step 0b preserves existing `ccm_project.json` keys and adds:

```json
{
  "data_root": "D:/GIS/Source_Data",
  "data_catalog_json": "D:/GIS/Project/ccm_data_catalog.json",
  "data_quality_scores": "D:/GIS/Project/ccm_quality_scores.json",
  "data_fitness_scores": "D:/GIS/Project/ccm_fitness_scores.json",
  "data_confidence_scores": "D:/GIS/Project/ccm_confidence_scores.json",
  "data_readiness_scores": "D:/GIS/Project/ccm_readiness_scores.json",
  "data_recommendations": "D:/GIS/Project/ccm_recommendations.json",
  "data_recommendations_report": "D:/GIS/Project/CCM_Recommendations_Report.html",
  "ccm_version": "0.58.2"
}
```

Step 1 displays the recommendation file at startup. It does not automatically
select, replace, or mutate an input. The recommendation layer **must not** be
treated as an automatic substitute for explicit Step 1 parameters. Explicit
Step 1 parameters remain the source of truth, and recommendation overrides
remain reviewable.

## Runtime modes

- **ArcGIS Pro toolbox mode:** ArcPy can read richer metadata and enumerate
  file-geodatabase layers.
- **Anaconda CLI mode:** built-in readers and optional GDAL/OGR provide a
  useful offline scan without ArcGIS Pro.

The environment setup is `CCM_anaconda.bat`. Run it from **Anaconda Prompt**
and use the dedicated `ccm_tool` environment; do not install project
dependencies into `base`.

## Verification checklist

From Anaconda Prompt:

```bat
CCM_anaconda.bat
RUN_V0582_TESTS.bat
```

Then, with ArcGIS Pro open and signed in:

```bat
RUN_ARCGIS_SMOKE_TEST.bat
```

The portable gate checks syntax, version synchronization, calibration files,
legacy regressions, factual inventory, scoring/recommendation outputs, and
release packaging. The licensed gate additionally checks toolbox parameter
loading and the integrated Step 0b path through ArcPy.

## Scope boundary

Recommendations are evidence-based guidance for analyst review. They do not
constitute official certification, do not alter source data, and do not
silently replace Step 1 inputs. ArcPy/GDAL-dependent metadata should be
verified on the user's licensed environment before production modeling.

# <<< END OF FILE >>>
