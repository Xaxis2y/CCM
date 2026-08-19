# CCM Tool v0.58.2 — Changelog

Release date: 2026-08-19

## Release focus

This release combines the complete `v0.58.1` toolbox with the scoring and
recommendation modules from `v0.58.1a`. The incomplete `v0.58.1a` extraction is
not used as a standalone toolbox.

## Fixed

- Restored real Step 0 and Step 0b toolbox classes in one coherent release
  folder. Step 0b no longer appears as an empty unavailable stub when the
  toolbox is loaded from the release root.
- Registered the integrated Step 0b workflow through the existing
  `CCMDataIntelligenceTool` entry point.
- Normalized factual catalog records before scoring so structured CRS,
  resolution, schema, coverage, and acquisition metadata are interpreted by
  the scoring engines correctly.
- Corrected the report API call from the nonexistent `write_reports` function
  to the existing `ccm_data_report.write_all` function.
- Added safe defaults for unknown coverage values so vehicle and other
  non-spatial records do not crash recommendation scoring.
- Added a Step 1 display-only recommendation hand-off. Explicit user inputs
  remain authoritative.
- Updated the verifier and release manifest to include all v0.58.2 scoring,
  integration, tests, support assets, and documentation.

## New Step 0b outputs

- `ccm_quality_scores.json`
- `ccm_fitness_scores.json`
- `ccm_confidence_scores.json`
- `ccm_readiness_scores.json`
- `ccm_recommendations.json`
- `CCM_Recommendations_Report.html`

The factual `ccm_data_catalog.json`, HTML report, TXT report, and project
configuration hand-off remain available.

## Verification

The portable release gate includes fixture generation, factual regression
tests, v0.58.2 integration tests, calibration-data audits, syntax checks,
pyflakes, and an end-to-end output check. A separate ArcPy smoke launcher
checks the licensed ArcGIS Pro path.

## Boundary

Readiness is reported as `Not Yet Run` until Step 1 preprocessing produces the
required project outputs. Recommendations are guidance for review, not
certification and not automatic input substitution. Final ArcPy/GDAL metadata
behavior must be confirmed in the user's licensed Anaconda/ArcGIS environment.

# <<< END OF FILE >>>
