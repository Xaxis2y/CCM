# MCE CCM Tool — v0.46

Cross-Country Mobility (CCM) assessment toolbox for ArcGIS Pro. Estimates where a
given vehicle can travel across terrain by combining slope, soil strength,
vegetation, hydrology and weather into a per-area mobility/speed surface.

## Workflow (run in order in ArcGIS Pro)

1. **Step 1 — Project Setup & Pre-process** (`ccm_step1_setup.py`)
   Enter all raw inputs once. Pre-processes soil and vegetation into CCM-ready
   polygon layers and writes `ccm_project.json` so later steps auto-populate.
2. **Step 2 — Generate Mobility Map** (`ccm_step2_mobility.py`)
   Runs the multi-criteria mobility model for a chosen vehicle and produces the
   speed-surface feature class (`SpeedKMH`, `Mobility`, and the `F1..F5`/`F_hydro`
   factor fields). This output is the input for every Step 3 analysis.
3. **Step 3 — Advanced Analysis** (`ccm_step3_advanced.py`)
   Reason map, reachability (isochrone), vehicle comparison, obstacle detection,
   and fastest-route (waypoint) tools, all driven by the Step 2 speed surface.

## Main components

- `MCE_CCM_v0.46.pyt` — ArcGIS Python Toolbox entry point (registers Steps 1-3 and
  the Vehicle Compare tool; shows a stub tool with the error if a module fails
  to import rather than silently dropping it).
- `ccm_step2_mobility.py` — core mobility (speed-surface) engine.
- `ccm_soil_preprocess.py` / `ccm_soil_validator.py` — soil source ingestion
  (DSS, SLC, SSURGO, HWSD, SoilGrids, MGCP, TDS, GGDM, generic) into USCS codes.
- `ccm_veg_preprocess.py` — vegetation rasters into VTI / tree spacing / stem diameter.
- `ccm_reason_map.py`, `ccm_isochrone.py`, `ccm_waypoints.py`,
  `ccm_obstacle_detect.py`, `ccm_vehicle_compare.py` — Step 3 analyses.
- `ccm_weather.py` — live rainfall into soil RCI adjustment.
- `ccm_project_config.py` — `ccm_project.json` read/write plus the `run_tool`
  helper used to invoke sub-tools by parameter name.
- `ccm_coords.py` — coordinate format parsing/conversion.
- `Vehicles_Can.csv` — vehicle definitions.
- `Symbology/Mobility_Symbology_Final.lyrx` — mobility layer symbology.

## Tests

Pure-Python helpers (no arcpy required):

    pip install pytest
    pytest tests/test_ccm.py -v
