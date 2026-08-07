<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
<!-- Copyright (c) 2026 Eui Soo SON -->

# CHANGELOG — v0.47 (June 18, 2026)

Two targeted performance and capability improvements. No breaking changes to
existing project files, outputs, or downstream tool contracts.

## 1. Isochrone parallel processing (`ccm_isochrone.py`)

`DistanceAccumulation` (Pro 3.5+) now runs inside
`arcpy.EnvManager(parallelProcessingFactor="100%")`, directing ArcGIS to use
all available CPU cores for raster traversal. On large MGCP datasets this can
reduce isochrone generation time by up to 50×. The `EnvManager` context resets
automatically on exit — no effect on other geoprocessing steps.

The legacy `CostDistance` fallback (for Pro < 3.5) is unchanged.

## 2. Antecedent Moisture Scenarios (`ccm_weather.py`, `ccm_step2_mobility.py`)

A single hourly METAR reading cannot represent multi-day or seasonal ground
conditions. A new `Antecedent Moisture Scenario` dropdown appears in Step 2's
**Weather** parameter group with four options:

| Scenario | Equiv. rainfall | Antecedent multiplier |
|---|---|---|
| Live Weather *(default)* | fetched live | ×1.00 |
| Summer Dry Baseline | 0 mm/hr | ×1.00 |
| 3-Day Continuous Rainfall | 10 mm/hr | ×1.40 |
| Spring Thaw / Freeze-Thaw Cycle (해빙기) | 25 mm/hr | ×1.50 |

**Priority order** (highest wins):
1. Manual Rainfall Override mm/hr — analyst-supplied number
2. Scenario ≠ "Live Weather" — strategic preset
3. Use Live Weather = True — real-time METAR/Open-Meteo fetch
4. No setting — standard tabulated dry RCI values

**How the penalty works:**  
`effective_penalty = (1 − base_rainfall_factor) × antecedent_multiplier`  
`per-soil factor = 1 − effective_penalty × (2 − soil_sensitivity)`  
Rock and evaporite remain immune. Fine-grained cohesive soils (peat, fat clay,
organic clay) receive the largest penalty per STANAG 4234 / FM 5-170.

Spot-check for lean clay (dry RCI = 160):

| Scenario | Adjusted RCI | % of original |
|---|---|---|
| Summer Dry Baseline | 160.0 | 100% |
| 3-Day Continuous Rainfall | ~94 | ~59% |
| Spring Thaw | ~33 | ~20% |

The active scenario name is written to `ccm_project.json` (`moisture_scenario`
key) so the Reason Map and downstream tools can annotate outputs accordingly.

## Bug fix

Pre-existing unit test `test_heavy_rain_reduces_clay_more_than_gravel` was
comparing absolute RCI drops rather than proportional ones. Gravel starts at a
higher absolute value so its raw drop always exceeds clay's, even though clay
degrades proportionally more — which is the correct behaviour. Fixed assertion
to compare retained fraction (clay_frac < gravel_frac). The test had been
silently non-executing in v0.46 due to a missing `unittest.main()` call.

## Files changed

- `ccm_isochrone.py` — `parallelProcessingFactor` wrapping
- `ccm_weather.py` — `ANTECEDENT_SCENARIOS`, `SCENARIO_NAMES`,
  `antecedent_multiplier` param in `adjust_rci_for_rainfall()`,
  `apply_antecedent_scenario()` helper, updated `apply_live_weather_to_rci()`
- `ccm_step2_mobility.py` — scenario dropdown parameter (index 6),
  `antecedent_multiplier` forwarded through `apply_weather_to_rci()` and
  `build_speed_surface()`, `SetParameterAsText` updated to index 7,
  `moisture_scenario` saved to project config
- All modules — `VERSION` bumped to `"0.47"`
- `CCM_Tool_v0.47.pyt` / `CCM_Tool_v0.47.pyt.xml` — toolbox entry point renamed
