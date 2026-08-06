<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
<!-- Copyright (c) 2026 Eui Soo SON -->

# CHANGELOG — v0.53.3 (2026-07-07)

## Lint cleanup + copyright update

- **Source modules are now pyflakes-clean.** Removed unused imports (`math` in
  `ccm_coords` / `ccm_vehicle_compare`, `os` in `ccm_weather`, `sys` in
  `ccm_soil_preprocess` / `ccm_veg_preprocess`, `arcpy.sa` in
  `ccm_obstacle_detect`, the `_veg_mod` alias in `ccm_step1_setup`), removed dead
  local variables (`pt`, `speeds_sorted`, `p_vehicle`, `desc`, `_COORD_HINT`),
  made the `ccm_data_discovery` module docstring raw to fix an invalid `\.`
  escape sequence, and dropped the `f` prefix from three placeholder-less
  f-strings. No behavioural change — all 152 tests still pass.
- **Copyright headers simplified.** Every module header, the README copyright
  section, and the CHANGELOG v0.49 author line now read simply
  `Copyright (c) 2026  Eui Soo Son` / `All Rights Reserved.` The former rank,
  GETESS / Mapping and Charting Establishment (MCE) / Canadian Armed Forces
  attribution and the proprietary / authorized-use boilerplate were removed.
- Version bumped 0.53.2 → 0.53.3 across all modules, the `.pyt`
  (`CCM_Tool_by_Son_v0.53.3.pyt`) and its `.pyt.xml` sidecars, `build.py`, the test
  suite, README / PROJECT_STATUS / TASKS, and the user manual.

---

# CHANGELOG — v0.53.2 (2026-07-07)

## Bug fix — restored truncated Waypoint routing tool

- **`ccm_waypoints.py` — `CCMWaypointTool.execute()` was truncated.** The
  method extracted its parameters, converted the start/end coordinates and
  loaded the vehicle CSV, then the file ended at the `# <<< END OF FILE >>>`
  marker without ever calling `find_route()`. The tool therefore produced no
  route polyline or points feature class. Because the file still parsed and
  carried the end marker, `build.py`'s syntax/integrity check and pyflakes
  both passed it (exactly the silent-truncation failure Rule 2 warns about).
  `execute()` now calls `find_route(...)` with the extracted parameters and
  surfaces failures / the no-route case.
- **`ccm_step3_advanced.py` — hardened the Step 3 waypoint call.** Step 3
  invoked the waypoint tool and unconditionally logged "Waypoint Routing
  complete" and queued the output for map display. It now only reports
  success and adds the layer when the route feature class actually exists;
  otherwise it warns and adds nothing (prevents a false-success message and a
  missing-layer error when no passable path is found).
- Version bumped 0.53.1 → 0.53.2 across all modules, the `.pyt`
  (`CCM_Tool_by_Son_v0.53.2.pyt`) and its `.pyt.xml` sidecars, `build.py`, the test
  suite, README / PROJECT_STATUS / TASKS, and the user manual.

---

# CHANGELOG — v0.53.1 (2026-07-07)

## Repository cleanup — removed redundant / superseded files

A housekeeping release: no code-behaviour changes to the CCM tools, only
removal of files that were no longer needed and were being swept into the
release zip by `build.py`.

- **Removed the standalone `MGCP Data Loader/` folder** (`LoadMGCPData`
  v0.10 / v0.11 / v0.12 plus their `.pyt.xml` sidecars, three user manuals,
  and README). That toolbox was the predecessor of Step 0; its logic was
  merged into `ccm_step0_mgcp.py` (see the module header, "Merged from
  LoadMGCPData_v0.12"), so the standalone copy was dead weight and a
  drift risk.
- **Removed orphaned sidecar** `CCM_Tool_by_Son_v0.49.2.CCMStep0MGCPTool.pyt.xml`
  (leftover from an old version; was being zipped into releases).
- **Removed superseded user manuals** `CCM_Tool_by_Son_v0.46 / v0.49 / v0.50.2
  _User_Manual.docx` — version history is preserved in §10.4 of the current
  manual.
- **Removed `__pycache__/`** (auto-generated, already excluded from the zip).

### Version bump

- All module `VERSION` constants → `0.53.1`; toolbox renamed
  `CCM_Tool_by_Son_v0.53.0.pyt` → `CCM_Tool_by_Son_v0.53.1.pyt` (sidecars, `build.py`,
  README, PROJECT_STATUS, TASKS, tests, and the user manual updated to match).

---

# CHANGELOG — v0.53.0 (2026-07-03)

## Expanded vehicle database — Vehicles_Can.csv (Canada / US / Russia)

The vehicle definitions file grew from 13 legacy entries to **64 platforms**
covering the combat- and mobility-relevant fleets of three nations:

- **Canada (16)** — Leopard 2A4 / 2A4M CAN / 2A6M CAN, Leopard 2 AEV Kodiak /
  ARV Beaver, Badger AEV, Beaver AVLB, LAV 6.0 (+ Mk II), ACSV, TAPV, Bison,
  Coyote, MSVS SMP, LSVW, LUVW G-Wagon.
- **United States (26)** — legacy M1 / M60 / M109 / M113 / M2 / M3 / MLRS /
  AVLBs kept, plus M1A2 SEPv3, M2A3 Bradley, M109A7 Paladin, AMPV, Stryker
  ICV / DVH-A1, M88A2, M9 ACE, HIMARS, JLTV, HMMWV M1151, MaxxPro, FMTV,
  HEMTT, PLS.
- **Russia (22)** — legacy T-62 / T-72, plus T-72B3, T-80U, T-90M, T-14
  Armata, BMP-1/2/3, BMD-4, MT-LB, BTR-80 / 82A, 2S1 / 2S3 / 2S19 SP
  artillery, BM-21 Grad, Ural-4320, KamAZ Typhoon, Tigr, BREM-1, IMR-2.

### New provenance columns (self-documenting; loader ignores them)

Three columns appended: **nation**, **source** (`NRMM published` vs
`derived`), and **note**. The 13 legacy rows keep their published NRMM
VCI/MMP values verbatim; the 51 new rows are marked `derived`.

### How the derived figures were produced

`vci_1`/`vci_50` (Vehicle Cone Index) and `mmp_kpa` (Mean Maximum Pressure)
are not public for most modern platforms, so they were estimated from
vehicle class, weight, track/tyre geometry and locomotion type, anchored to
the published legacy rows and kept **internally consistent wit