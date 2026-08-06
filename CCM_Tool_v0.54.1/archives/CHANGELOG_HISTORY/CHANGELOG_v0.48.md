<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
<!-- Copyright (c) 2026 Eui Soo SON -->

# CHANGELOG — v0.48.0 (June 19, 2026)

A correctness / polish release. No changes to the Step 2 output field contract
(`Mobility`, `SpeedKMH`, `F1_slope`..`F5_soil_wet`, `F_hydro`), so existing
projects and downstream tools keep working. One additive field (`MOIST_SCEN`)
appears on the Reason Map output when a strategic moisture scenario is used.

## Modelling fixes

### 1. Three-way soil moisture (`ccm_step2_mobility.py`)
Previously the speed surface only ever used the **dry** soil factor (for the
"dry" condition) or the **wet** soil factor (for "moist" *and* "wet") — the
middle `rci_moist` column in `soil_rci.csv` was never consulted. The
speed-driving soil factor is now computed for the **actual** moisture condition
(`dry` / `moist` / `wet`), so selecting "moist" now uses the moist RCI column.
`combine_speed()` gained an optional `soil_active` argument; `F4_soil_dry` and
`F5_soil_wet` are still written as the dry/wet endpoints for the Reason Map, so
the legacy fallback is unchanged and still unit-tested.

### 2. Slope field name & units (`ccm_step1_setup.py`, `ccm_project_config.py`, `ccm_step2_mobility.py`)
`slope_factor()` expects slope **percent**, but the slope-regions FC could carry
degrees, producing a silent unit mismatch. Step 1 now exposes **Slope Value
Field** and **Slope Field Units** (`percent` / `degrees`, default `percent`)
and records them in `ccm_project.json` (`slope_field`, `slope_units`). Step 2
prefers the recorded field and converts degrees to percent (`tan θ × 100`)
before computing F1. With no recorded metadata the behaviour matches v0.47.

### 3. Antecedent scenario annotation (`ccm_reason_map.py`)
v0.47 wrote `moisture_scenario` into `ccm_project.json` but nothing consumed it.
The Reason Map now reads it back and, when a strategic preset was used (anything
other than "Live Weather"), stamps a `MOIST_SCEN` text field on every feature.

## Polish

- **Isochrone band labels (`ccm_step3_advanced.py`)**: Step 3 passes integer
  time bands, so labels read "15-30 min" rather than "15.0-30.0 min".
- **Docs**: corrected the v0.47 spot-check (3-Day adjusted lean-clay RCI is
  ~94 / 59%, not ~66); the toolbox docstring now lists all four registered
  tools (Step 2 was missing); refreshed `PROJECT_STATUS.md`; normalised the
  stale "aligned with toolbox-wide v0.46 release" version comments.

## Version / packaging

- All module `VERSION` constants bumped to `"0.48.0"`.
- Toolbox entry renamed `CCM_Tool_by_Son_v0.47.pyt` -> `CCM_Tool_by_Son_v0.48.pyt` (+ `.pyt.xml`);
  `build.py`, `tests/test_ccm.py`, `README.md` updated to match.

## Tests

- Added `test_combine_uses_moist_column_via_soil_active` and
  `test_slope_to_percent_converts_degrees`.
- Full suite: 74 passed / 3 skipped (arcpy integration tests skipped off-Pro).
# <<< END OF FILE >>>
