# CCM Tool by Son — v0.54.1

**Release Date:** August 6, 2026  
**Version:** 0.54.1  
**Status:** Production

---

## Directory Structure

### `/source`
All Python source code modules:
- **Core Modules:** `ccm_project_config.py`, `ccm_map_display.py`, `ccm_reason_map.py`
- **Data Processing:** `ccm_coords.py`, `ccm_isochrone.py`, `ccm_data_discovery.py`, `ccm_soil_validator.py`, `ccm_soil_preprocess.py`, `ccm_veg_preprocess.py`, `ccm_obstacle_detect.py`, `ccm_mgcp_catalog.py`, `ccm_weather.py`, `ccm_waypoints.py`
- **Tools:** `ccm_step0_mgcp.py`, `ccm_step1_setup.py`, `ccm_step2_mobility.py`, `ccm_step3_advanced.py`, `ccm_vehicle_compare.py`
- **Build:** `build.py` (versioning & packaging)

### `/toolbox`
ArcGIS toolbox files:
- `CCM_Tool_by_Son_v0.54.1.pyt` (main toolbox)
- `CCM_Tool_by_Son_v0.54.1.pyt.xml` (metadata)
- Individual step toolboxes (.pyt.xml files for each tool)

### `/documentation`
- `README.md` — Project overview
- `PROJECT_STATUS.md` — Status and roadmap
- `TASKS.md` — Current task list
- `CHANGELOG_v0.54.md` — v0.54 release notes
- `CLAUDE.md` — AI session rules & conventions
- `CCM_Tool_by_Son_v0.54.1_User_Manual.docx` — Complete user manual
- `CCM_Improvement_Research.md` — Research notes
- `CLEANUP_STATUS_v0.54.1.md` — Cleanup records

### `/data`
- `Vehicles_Can.csv` — Canadian vehicle database
- `Vehicles_Can.csv.xml` — Vehicle data metadata
- `soil_rci.csv` — Soil classification data
- `/Vehicle_Data/` — Additional vehicle data files

### `/symbology`
ArcGIS layer symbology and styling files

### `/tests`
Test suite:
- `test_ccm.py` — Main test suite
- `test_v050.py` — Version 0.50 regression tests
- `arcpy_smoke_test.py` — ArcPy integration tests

### `/archives`
Historical records:
- `/CHANGELOG_HISTORY/` — Previous release notes (v0.45 → v0.53)
- `/CODE_REVIEW_ARCHIVE/` — Code review records

---

## Quick Start

1. **For ArcGIS:** Copy `/toolbox/*.pyt` files to your ArcGIS Pro toolbox directory
2. **For Development:** See `/source/README.md` and `/documentation/CLAUDE.md`
3. **For Users:** Read `/documentation/CCM_Tool_by_Son_v0.54.1_User_Manual.docx`
4. **For Testing:** Run `python tests/test_ccm.py` with ArcPy environment

---

## Key Files by Purpose

| Purpose | File |
|---------|------|
| **Deploy Tool** | `toolbox/CCM_Tool_by_Son_v0.54.1.pyt` |
| **Read Manual** | `documentation/CCM_Tool_by_Son_v0.54.1_User_Manual.docx` |
| **Check Status** | `documentation/PROJECT_STATUS.md` |
| **Build Release** | `source/build.py` |
| **Review Code** | `source/*.py` |
| **Run Tests** | `tests/test_ccm.py` |

---

## Version Tracking

All components follow semantic versioning:
- **Patch** (0.54.x): Bug fixes, internal refactoring
- **Minor** (0.x.0): New features
- **Major** (x.0.0): Breaking changes

Current: **0.54.1**

