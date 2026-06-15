# MCE CCM Tool — Project Status & Continuation Notes

*Current: **v0.46** — June 11, 2026 (see CHANGELOG files).*

---

## 1. Where the project stands

v0.46 is a repair-and-rebuild release line. The toolbox is
end-to-end functional again: Step 1 (setup/pre-process) → Step 2 (mobility map)
→ Step 3 (advanced analyses). The test suite (63 tests) passes without arcpy.

### What was fixed (see CHANGELOG files for detail)
- **Rebuilt the missing Step 2 engine** (`ccm_step2_mobility.py`). An earlier build shipped
  without the core mobility-map generator: nothing produced the `SpeedKMH` speed
  surface or wrote `mobility_map_fc` to the config, so every Step 3 tool had no
  valid input. Step 2 was reverse-engineered from the downstream tools' contracts.
- **Repaired truncated/corrupted files**: `MCE_CCM_v0.46.pyt` was cut off mid-`main()`,
  `ccm_step1_setup.py` had 238 trailing null bytes, `ccm_project_config.py` had a
  mangled footer. All files now end with `# <<< END OF FILE >>>` and verify clean.
- **Decoupled sub-tool invocation**: new `run_tool(tool, **kwargs)` in
  `ccm_project_config.py` calls tools by parameter *name*; Step 1 no longer builds
  fragile fixed-order positional parameter lists.
- **No more silently vanishing tools**: if a module fails to import, the toolbox
  registers a stub tool that displays the import error instead of dropping the tool.
- **Minor fixes**: obstacle CSV header detection now parses columns properly;
  version constants unified.

## 2. The Step 2 output contract (do not break)

Downstream tools consume these exact field names on the speed-surface FC:

| Field | Type | Consumed by |
|---|---|---|
| `Mobility` | TEXT ("GO"/"RESTRICTED"/"NO GO") | symbology .lyrx, reason map |
| `SpeedKMH` | FLOAT | isochrone, waypoints, vehicle compare |
| `F1_slope` | DOUBLE 0..1 | reason map |
| `F2_vegetation` | DOUBLE 0..1 | reason map |
| `F3_veg_spacing` | DOUBLE 0..1 | reason map |
| `F4_soil_dry` | DOUBLE 0..1 | reason map |
| `F5_soil_wet` | DOUBLE 0..1 | reason map |
| `F_hydro` | DOUBLE 0..1 | reason map |

FC naming: `speed_surface_{vehicle_tag}_{moisture}` inside the project GDB
(`ccm_project_config.find_latest_speed_surface` depends on this pattern).
Step 2 writes `mobility_map_fc`, `last_run_output`, `last_vehicles` back to
`ccm_project.json` so Step 3 auto-fills.

## 3. Open items / next steps

1. ~~Calibrate the soil RCI table~~ — MECHANISM DONE in v0.46: edit
   **`soil_rci.csv`** (per-USCS dry/moist/wet RCI) — loaded automatically,
   built-ins as fallback. Remaining: populate it with doctrinal values
   (FM 5-430-00-1 / FM 5-170 / NRMM cone-index data) and validate GO/NO-GO
   boundaries against a trusted CCM overlay for a known AOI.
   ~~Weather wiring~~ — DONE in v0.46: Step 2 has "Use Live Weather" and
   "Manual Rainfall Override (mm/hr)" parameters; rainfall penalises RCI via
   ccm_weather before F4/F5 are computed.
2. **Slope field detection**: Step 2 auto-detects slope-value fields by name
   (`_SLOPE_FIELD_CANDIDATES`). If your slope-regions FC uses another field name,
   add it to the list — or better, record the field name in `ccm_project.json`
   at Step 1 time.
3. **Validate Step 2 in ArcGIS Pro** — SCRIPT READY in v0.46: run
   `tests/arcpy_smoke_test.py` in the ArcGIS Pro Python window
   (`exec(open(r"...\tests\arcpy_smoke_test.py").read())`). It builds a
   synthetic project, runs Step 2 end-to-end (plain + rainfall override) and
   prints a PASS/FAIL verdict plus a scratch GDB you can inspect visually.
   This still needs to be EXECUTED once on a licensed machine.
4. ~~Rename build scripts~~ — DONE: `build.py` / `build.ps1` are version-agnostic;
   the zip name derives from `ccm_project_config.VERSION` (single bump point).
   The build also fails on NULL bytes or a missing END-OF-FILE marker
   (guards against the truncation issue that corrupted an earlier build).
5. ~~Update the user manual~~ — DONE: `MCE_CCM_Tool_v0.46_User_Manual.docx`
   covers the rebuilt Step 2, the field contract, and the v0.46 changes.
6. **Split `ccm_soil_preprocess.py`** (3,900 lines) into per-source driver modules
   (deferred by decision — keep-single-file for low risk).
7. **Performance backlog** from `CCM_Improvement_Research.md`: Distance
   Accumulation (Pro 3.5+) for isochrone/waypoints, NumPy vectorization in
   obstacle detect, multiprocessing for SoilGrids rasters, ML-based USCS
   classification (long term).

## 4. How to verify the baseline

    pip install pytest
    pytest tests/test_ccm.py -v        # 63 passed, 3 skipped expected
    python build.py                    # integrity check + builds MCE_CCM_Tool_v<VERSION>.zip

## 5. File inventory (v0.46)

- `MCE_CCM_v0.46.pyt` — toolbox entry; registers Step 1, Step 2, Step 3, Vehicle Compare
- `ccm_step1_setup.py` — Step 1: project setup + soil/veg pre-processing
- `ccm_step2_mobility.py` — **Step 2: mobility map / speed-surface engine (new in v0.46)**
- `ccm_step3_advanced.py` — Step 3: reason map, isochrone, compare, obstacles, route
- `ccm_soil_preprocess.py`, `ccm_soil_validator.py` — soil ingestion → USCS
- `ccm_veg_preprocess.py` — vegetation rasters → VTI/spacing/stem diameter
- `ccm_reason_map.py`, `ccm_isochrone.py`, `ccm_waypoints.py`,
  `ccm_obstacle_detect.py`, `ccm_vehicle_compare.py` — Step 3 analysis modules
- `ccm_weather.py` — live rainfall → soil RCI adjustment
- `ccm_coords.py` — coordinate format parsing / conversion
- `ccm_project_config.py` — `ccm_project.json` read/write + `run_tool` dispatcher
- `build.py` — integrity check + zip packager (reads `VERSION`)
- `soil_rci.csv` — per-USCS dry/moist/wet RCI calibration table
- `Vehicles_Can.csv` — vehicle definitions
- `Symbology/Mobility_Symbology_Final.lyrx` — mobility layer symbology
