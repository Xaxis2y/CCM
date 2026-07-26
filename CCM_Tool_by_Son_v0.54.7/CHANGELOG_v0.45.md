# CHANGELOG — v0.45 (June 11, 2026)

Version re-baselined from V2.44 → **v0.45**. All `VERSION` constants, the toolbox
label, tests, and docs now read 0.45.

## Added
- **`ccm_step2_mobility.py` — Step 2: Generate Mobility Map (the core MCE engine).**
  V2.44 had no Step 2: the toolbox registered only Steps 1/3/Compare, nothing
  created a `SpeedKMH` speed surface, and `mobility_map_fc` was never written, so
  the entire Step 3 suite had no valid input. The new module:
  - Unions soil/veg/slope criteria layers within the analysis extent, flags water
    via the hydro FCs, and computes per-polygon factors: F1 slope (taper to the
    vehicle's max off-road gradient), F2 vegetation density (from VTI), F3
    manoeuvre/override (tree spacing & stem diameter vs vehicle width & override
    capability), F4/F5 soil dry/wet (USCS→RCI vs vehicle VCI1/VCI50), F_hydro.
  - Produces `speed_surface_{vehicle}_{moisture}` in the project GDB with the
    exact field contract required by the Step 3 tools and the symbology .lyrx.
  - Updates `ccm_project.json` (`mobility_map_fc`, `last_run_output`,
    `last_vehicles`) so Step 3 auto-fills.
  - Trafficability math is pure Python (no arcpy) and unit-tested.
- `run_tool(tool, messages, **kwargs)` in `ccm_project_config.py` — programmatic
  tool invocation by parameter name with fail-fast on unknown names and
  multi-value support.
- Stub-tool factory in `CCM_Tool_by_Son_V2.pyt` — failed module imports now surface as a
  visible "[UNAVAILABLE — failed to load]" tool reporting the error.
- 23 new unit tests covering the Step 2 factor functions, speed combination,
  mobility classification, vehicle CSV parsing, and `run_tool`.

## Fixed
- **File truncation/corruption** (cause of "files truncated at the end"):
  - `CCM_Tool_by_Son_V2.pyt` was cut off mid-`main()` (invalid UTF-8 tail); reconstructed.
  - `ccm_step1_setup.py` carried 238 trailing NULL bytes; stripped.
  - `ccm_project_config.py` had a mangled footer; rebuilt.
  - All .py/.pyt files now verified: no NULL bytes, valid UTF-8, parse clean,
    single trailing newline, `# <<< END OF FILE >>>` terminator.
- Step 1 no longer drives the soil (21 positional slots) and vegetation (9 slots)
  sub-tools via hard-coded index-ordered fake parameter lists — replaced with
  named-parameter `run_tool` calls (legacy positional path kept as fallback).
- `_resolve_obstacle_source()` CSV detection: header is now split into column
  names, so `x,y` / `lat,lon` / `latitude,longitude` are recognised in any
  position (previously `x,y` as the first columns was missed).
- Toolbox now registers Step 2 between Steps 1 and 3 (the "Step 1 → Step 3"
  numbering gap is closed).

## Changed
- `README.md` rewritten to describe the actual three-step workflow and module map.
- Build scripts replaced by version-agnostic `build.py` / `build.ps1`: the release
  version and zip name derive from `ccm_project_config.VERSION`, and the build
  fails on NULL bytes or a missing END-OF-FILE marker (truncation guard).
- User manual updated and renamed to `CCM_Tool_by_Son_v0.45_User_Manual.docx`
  (rebuilt Step 2 section, corrected field contract, VCI ramp formula,
  module architecture, version history).
- Tests updated to cover the rebuilt Step 2 mobility math; suite now at
  63 passing / 3 skipped without arcpy.
