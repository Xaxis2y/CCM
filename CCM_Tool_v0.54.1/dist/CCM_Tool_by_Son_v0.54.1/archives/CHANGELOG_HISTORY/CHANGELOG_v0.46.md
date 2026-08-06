<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
<!-- Copyright (c) 2026 Eui Soo SON -->

# CHANGELOG — v0.46 (June 11, 2026)

This release resolves the three "Known limitations" carried from v0.45.

## 1. Calibratable soil strength (was: "RCI values are nominal")
- New **`soil_rci.csv`** ships next to the modules: one row per USCS code with
  `rci_dry`, `rci_moist`, `rci_wet` columns. `ccm_step2_mobility` loads it at
  import (`load_rci_csv()`); the built-in defaults remain as fallback when the
  CSV is missing or malformed.
- Analysts calibrate trafficability against FM 5-430-00-1 / FM 5-170 / NRMM
  cone-index data by editing the CSV — no code changes, same pattern as
  `Vehicles_Can.csv`.
- `soil_factor()` also accepts an explicit `rci_table` argument for scripted
  what-if analyses.

## 2. Live weather wired into Step 2 (was: "rainfall→RCI not wired in")
- Step 2 gains two parameters (Weather category):
  - **Use Live Weather** — fetches current rainfall for the AOI centroid via
    `ccm_weather` (NOAA METAR primary, Open-Meteo fallback) and applies
    `adjust_rci_for_rainfall()` to the RCI table before computing F4/F5.
  - **Manual Rainfall Override (mm/hr)** — takes precedence over the live
    lookup; for exercises or commander's local knowledge.
- New `USCS_TO_SENSITIVITY_KEY` mapping bridges USCS codes (CH, Pt, …) to
  `ccm_weather`'s soil-sensitivity keys (fatClay, peat, …); rock/evaporite
  remain immune, fine clays are penalised hardest, exactly per the existing
  rainfall model.
- Engine API: `build_speed_surface(..., use_live_weather=, rainfall_override_mm=)`.

## 3. arcpy validation path (was: "not validated under licensed arcpy")
- New **`tests/arcpy_smoke_test.py`** — a self-contained end-to-end Step 2
  validation you run on a machine with ArcGIS Pro (Python window or
  arcgispro-py3 prompt). It synthesises a complete miniature project
  (soil grid GW/CH/Pt, vegetation strips open/overridable/blocking, slope,
  water body, 2-vehicle CSV, ccm_project.json), runs `build_speed_surface()`
  twice (plain + rainfall override), and asserts the output contract, sane
  GO/RESTRICTED/NO GO distribution, water = NO GO, speed bounds, and config
  registration. Verdict plus inspectable scratch GDB path printed at the end.

## Tests
- 9 new unit tests (RCI CSV loading, custom-table soil factors, mapping
  completeness, rainfall penalties incl. clay-vs-gravel ordering, manual
  override, rain-induced NO GO transitions).
- All VERSION constants and assertions now 0.46.

# <<< END OF FILE >>>
