<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
<!-- Copyright (c) 2026 Eui Soo SON -->

# CCM Tool — CHANGELOG v0.49.0

*Release date: 2026-06-19*
*Author: Eui Soo Son*

---

## Summary

v0.49.0 is a doctrinal modelling upgrade release, aligning the tool's outputs
and mathematics with the NATO Next-Generation NRMM (NG-NRMM) lineage.  All
changes are backward-compatible: no output field names were renamed and no
Step 3 tools require modification.

---

## 1. Speed Made Good (SMG) + %NOGO area-weighted summary

**File:** `ccm_step2_mobility.py` — `compute_speed_made_good()` + Step 2 completion block

The canonical NG-NRMM output for a mapped area is NOT a per-polygon speed
value — it is the **area-weighted Speed Made Good curve**: a CDF showing, for
each speed threshold *v*, what percentage of the AOI area is traversable at
≥ *v* km/h; paired with a **%NOGO by area** figure.

### What changed
- New pure-Python function `compute_speed_made_good(speed_area_pairs, ...)` that
  accepts `(speed_kmh, area_m2)` pairs and returns the full SMG dict:
  `pct_nogo`, `pct_restricted`, `pct_go`, `mean_speed_kmh`, `median_speed_kmh`,
  and `cdf` (list of `(speed_kmh, pct_area_achievable_at_or_above)`).
- The scoring cursor now collects `(speed, SHAPE@AREA)` per polygon.
- After the cursor, `compute_speed_made_good()` is called and the doctrinal
  summary is logged to arcpy messages:
  ```
  NG-NRMM SPEED MADE GOOD (area-weighted):
    %NOGO by area  :  18.3%  (0.412 km2)
    Mean speed     :  32.4 km/h  (mobile terrain)
    Median speed   :  35.0 km/h
    SMG CDF (speed -> % area achievable at >= that speed):
       0.0 km/h  [####################]  100.0%
      12.5 km/h  [################....]   81.7%
      25.0 km/h  [#############.......]   64.2%
      ...
  ```
- %NOGO by area is the most operationally relevant single number for
  cross-country mobility assessment (vs. the old polygon-count %NOGO).

---

## 2. Speed model: product → min-of-limiting-factors (doctrinal)

**File:** `ccm_step2_mobility.py` — `combine_speed()`

### Problem
The previous multiplicative product `speed = max_speed × F1 × F2 × F3 × Fsoil × Fhydro`
**compounds mild penalties**: two independent ×0.7 constraints produce ×0.49
(slower than either constraint alone warrants).  This violates the NG-NRMM
doctrine that **the most restrictive constraint governs**.

### Change
`combine_speed()` now defaults to `speed_model="min"`:
```
speed = max_speed × min(F1, F2, F3, Fsoil, Fhydro)
```
The backward-compatible `speed_model="product"` keyword restores the old
behaviour for comparison.

### Effect on predicted speeds
- Areas with a **single dominant constraint** (e.g., steep slope OR weak soil,
  but not both) are **unchanged** — the minimum equals the product when only one
  factor is non-unity.
- Areas with **multiple mild constraints** produce **higher predicted speeds**
  under the new model (less conservative), which is doctrinally correct.
- Example: F_slope=0.80, F_veg=0.85 → old product=0.68 × max; new min=0.80 × max.

### Tests
All existing `TestStep2Mobility` tests pass unchanged.  Four new tests in
`TestCombineSpeedMinModel` verify the min/product difference explicitly.

---

## 3. Mean Maximum Pressure (MMP) metric

**File:** `ccm_step2_mobility.py` — `compute_mmp_estimate()` + Step 2 summary
**File:** `Vehicles_Can.csv` — new `mmp_kpa` column

MMP (kPa) is the modern cross-vehicle ground-pressure comparison metric
(cited in NG-NRMM literature as a replacement for the empirical VCI-only
approach).  Added via the ERDC empirical relationship (Shoop 2000,
ERDC/CRREL TR-00-20):

| Locomotion | Relationship | Notes |
|---|---|---|
| Tracked | VCI_50 ≈ 0.56 × MMP_kPa | k_tracked = 0.56 |
| Wheeled | VCI_50 ≈ 0.18 × MMP_kPa | k_wheeled = 0.18 |

The MMP estimate is:
- Logged in the Step 2 completion summary alongside VCI_50 and locomotion type.
- Available as `compute_mmp_estimate(vci_50, locomotion_type)` for use in
  Vehicle Compare and future analyses.
- Stored in the new `mmp_kpa` column of `Vehicles_Can.csv` (formula-derived;
  replace with measured values when available from vehicle technical manuals).

**Interpretation:** lower MMP = distributed ground contact = less soil damage
and better trafficability on weak soils.  Tracked vehicles (M1: ~104 kPa)
generally have lower MMP than wheeled vehicles (M35A2: ~328 kPa), which is
why tracks outperform wheels on soft ground.

---

## 4. Stochastic GO/NOGO — P(GO) field (opt-in)

**File:** `ccm_step2_mobility.py` — `compute_stochastic_go()` + new `P_GO` field

Implements the **reliability-based stochastic mobility map** concept from
NG-NRMM (ASME reference in research notes): instead of a binary GO/NOGO,
output a **probability of GO** per polygon that propagates uncertainty in
soil strength and terrain slope.

### Implementation
`compute_stochastic_go(soil_code, moisture, vci_1, vci_50, slope_pct, max_grad,
rci_table, n_trials=200, rci_cv=0.15, slope_cv=0.10)`:
- Draws `n_trials` perturbations of RCI from Normal(μ=rci_base, σ=μ×0.15)
  and slope from Normal(μ=slope_pct, σ=μ×0.10).
- CV=0.15 for RCI is consistent with ERDC field cone-index variability data.
- CV=0.10 for slope reflects DEM vertical accuracy (~2–5 m RMSE → ~10% slope
  uncertainty at typical polygon sizes).
- Returns P(GO) = fraction of trials where both `soil_factor > 0` AND
  `slope_factor > 0`.

### Usage
Opt-in via the new `enable_stochastic=True` parameter (default False — adds
~200 × n_polygons function calls).  When enabled:
- A `P_GO` (DOUBLE, 0.0–1.0) field is added to the speed-surface FC.
- The completion summary notes how many trials were run.
- Recommended: `stochastic_trials=200` for operations, `500` for products.

### Toolbox
Two new parameters under the **Advanced** category:
- *Enable Stochastic P(GO)* (Boolean, default False)
- *Monte Carlo Trials* (Long, default 200)

---

## 5. Spatial soil moisture — per-polygon conditions (opt-in)

**File:** `ccm_weather.py` — `get_spatial_soil_moisture()` + `moisture_vwc_to_condition()`
**File:** `ccm_step2_mobility.py` — spatial moisture pre-pass in `build_speed_surface()`

### Problem
The v0.47/v0.48 weather integration fetches a **single rainfall value at the
AOI centroid** and applies it uniformly.  For large or topographically varied
AOIs, this is unrealistic — soil moisture varies spatially with drainage,
aspect, and precipitation gradients.

### Implementation
- `get_spatial_soil_moisture(bbox_wgs84, n_grid=3)`: queries Open-Meteo
  ERA5 soil moisture (0–7 cm layer, m³/m³) at an *n×n* grid of points
  across the AOI.  Returns `{(lat, lon): vwc}`.  Default 3×3 = 9 queries (~3 s).
- `moisture_vwc_to_condition(vwc)`: maps VWC to `"dry"/"moist"/"wet"` using
  USDA field-capacity thresholds (0.15 / 0.30 m³/m³).
- A **pre-pass cursor** (before the main scoring cursor) assigns each polygon
  the moisture condition of the nearest grid point.  The per-polygon condition
  then drives `soil_factor()` in the scoring cursor.

### SMAP substitution
The Open-Meteo ERA5 product is the free/keyless baseline (~9 km resolution).
The NASA SMAP L4 product (true 9 km, 3-hourly, with freeze/thaw layer) is the
NG-NRMM gold standard but requires NASA Earthdata credentials.  A SMAP client
can replace `_query_open_meteo_soil()` without changing any other interface.

### Usage
Opt-in via new parameter **Use Spatial Soil Moisture** (Weather category,
Boolean, default False).

---

## Files changed

| File | Change |
|---|---|
| `ccm_step2_mobility.py` | VERSION→0.49.0; SMG; min-model; stochastic; spatial moisture pre-pass; MMP logging; new tool params |
| `ccm_weather.py` | VERSION→0.49.0; `get_spatial_soil_moisture()`; `moisture_vwc_to_condition()` |
| `Vehicles_Can.csv` | New `mmp_kpa` column (formula-derived from VCI_50) |
| `Vehicle_Data/Vehicles_Can.csv` | Sync copy |
| `tests/test_ccm.py` | New: TestSpeedMadeGood, TestMMP, TestStochasticMobility, TestCombineSpeedMinModel, TestSpatialMoisture |
| `CHANGELOG_v0.49.md` | This file |
| `PROJECT_STATUS.md` | Updated open items + file inventory |

---

## Test count

```
pytest tests/test_ccm.py -v
# Expected: 107+ passed, 3 skipped  (was 74 passed / 3 skipped in v0.48)
```

---

## 6. RCI table calibration (post-release fix, 2026-06-19)

**Files:** `soil_rci.csv`, `ccm_step2_mobility.py` (`_BUILTIN_USCS_RCI`)

Previous values were defensible engineering estimates with no cited source.
Updated to values traceable to **ERDC/GL TR-02-6 Table 2**, **FM 5-430-00-1
Appendix E**, and the **NRMM soil-strength database (Turnage 1971)**.

Key changes and doctrinal rationale:
- Fine-grained soils in wet conditions dramatically reduced:
  `CL wet: 60→28`, `ML wet: 55→32`, `CH wet: 45→15`, `MH wet: 45→16`,
  `OL wet: 45→14`, `OH wet: 35→12`, `Pt wet: 25→8`
- Coarse soils (GW, GP) increased in dry/moist to reflect gravel's true strength;
  GM/GC/SW/SP values adjusted proportionally
- Rock ceiling raised 400→500 (unlimited bearing, no practical threshold)

Validation: each value produces the expected mobility class for the four
reference vehicles (M1 vci1/50=25/58, M113=17/40, M35A2=26/59, M151=19/44):
- Gravels and sands: **GO all conditions** ✓
- SC/ML/CL wet: **RESTRICTED all vehicles** ✓
- OL/MH/CH/OH wet: **NOGO all vehicles** ✓
- Pt wet: **NOGO all vehicles** ✓; dry/moist: **RESTRICTED heavy, GO light** ✓

Test updated: `test_rain_turns_marginal_soil_nogo` switched from CH (now always NOGO)
to ML wet (RCI=32, sits between VCI1=25 and VCI50=58 → RESTRICTED; rain → NOGO).
