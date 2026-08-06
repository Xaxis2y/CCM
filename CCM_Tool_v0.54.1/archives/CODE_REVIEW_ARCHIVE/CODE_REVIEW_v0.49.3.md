<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
<!-- Copyright (c) 2026 Eui Soo SON -->

# Logic Review — CCM Tool v0.49.3

Date: 2026-07-01
Scope: data loading (Step 0 / Step 1), automatic data recognition, MGCP feature identification, and per-step map display.

---

## 1. Verified Bugs (fix these first)

### BUG-1 — CRITICAL: Step 1 crashes when saving ccm_project.json
`ccm_step1_setup.py` line 710:

```python
_cfg_mod.save_config(project_folder, config)      # config passed positionally
```

but `ccm_project_config.save_config` is declared as:

```python
def save_config(project_folder, **fields):        # keyword-only fields
```

Result: `TypeError: save_config() takes 1 positional argument but 2 were given` at the very end of Step 1 — **the config file is never written via this path**, so Steps 2/3 cannot auto-populate. (Step 2 line 1195 calls it correctly with kwargs; only Step 1 is wrong.)

**Fix:**
```python
_cfg_mod.save_config(project_folder, **config)
```
Note: `save_config` force-overwrites `project_folder` internally, so remove it from the dict or leave it — it is harmless — but the `**` is mandatory.

### BUG-2 — MAJOR: Multiple hydrology layers are stored as one broken string
`ccm_step1_setup.py` lines 701–703:

```python
"hydro_fcs": ([hydro_param.valueAsText] if ... else []),
```

`valueAsText` of a multi-value parameter is a single semicolon-joined string, with single quotes around paths containing spaces (e.g. `'C:\a b\riv.shp';C:\x\lake.shp`). Step 2 (line 947) then runs `arcpy.Exists()` on that whole string → all hydro layers silently dropped whenever more than one layer (or a path with spaces) is supplied. F_hydro = 1.0 everywhere → rivers/lakes not treated as NO-GO.

**Fix:** the module already has the right helper — use it:
```python
"hydro_fcs": _parse_multi(hydro_param.valueAsText),
```

### BUG-3 — MODERATE: Step 3 assumes the newest layer is index 0
`ccm_step3_advanced.py` line 1043:

```python
_ccm_map.addDataFromPath(_fc)
_new_lyr = _ccm_map.listLayers()[0]
```

`listLayers()[0]` is not guaranteed to be the just-added layer (group layers, basemap ordering, user-moved layers). All symbology/renaming can silently land on the wrong layer.

**Fix:** `addDataFromPath` returns the layer object:
```python
_new_lyr = _ccm_map.addDataFromPath(_fc)
```

### BUG-4 — MINOR: Step 0 clobbers `overwriteOutput` mid-run
`ccm_step0_mgcp.py` line 596 sets `arcpy.env.overwriteOutput = False` after each copy instead of restoring the saved value. The outer `finally` fixes it at the end, so impact is limited to within-run behaviour — but restore `saved_overwrite` instead of hard-coding `False`.

---

## 2. Architecture Gap: Step 0 → Step 1 are not actually connected

Step 0's docstring says *"Run this BEFORE Step 1 so all terrain data is in a single GDB that Step 1 can reference"* — but Step 0 writes **nothing machine-readable** that Step 1 consumes. After Step 0 the user faces a GDB with dozens of FCs named `AP030`, `BH140`, `EC015`, `DA010`… and must manually figure out which one is soil, which are hydro, which are vegetation. This is exactly the pain you described.

### The core insight: MGCP names are not random — they are FACC codes
Every MGCP feature class name is a 5-character DIGEST/FACC code, and **the first letter is the theme**:

| First letter | Theme | CCM relevance |
|---|---|---|
| A (AL/AN/AP/AQ…) | Culture — settlement, rail, **roads** | Roads (on-road speed), built-up = obstacle |
| B (BA/BH…) | **Hydrography** | `hydro_fcs` — water = NO-GO |
| C (CA…) | Hypsography (contours, spot heights) | Slope input if no DEM |
| D (DA/DB…) | **Physiography** — ground surface, landforms | **DA010 carries the SMC (Surface Material Category) attribute = your soil source**; DB = dunes/cuts/embankments = obstacles |
| E (EA/EB/EC/ED…) | **Vegetation** | `veg` input — forest, scrub, swamp/marsh |
| F | Demarcation/boundaries | not used by CCM |
| G | Aeronautical | not used by CCM |
| Z | General/metadata | not used by CCM |

So "which of these 60 shapefiles is soil?" has a deterministic answer: **DA010 (Ground Surface Element) with the SMC field** — which is exactly what `detect_source_type()` already keys on (`SMC`/`SMCL` fields → `SOURCE_MGCP`). The knowledge exists in the codebase; it just isn't surfaced to the user or to Step 1.

### Recommended solution (cheap, high value)

**(a) Add a feature-code catalog module** (`ccm_mgcp_catalog.py`) — a plain dict, no dependencies:

```python
MGCP_CATALOG = {
    "AP030": ("Road",                  "Transportation"),
    "AP010": ("Cart Track",            "Transportation"),
    "AN010": ("Railway",               "Transportation"),
    "AL020": ("Built-up Area",         "Obstacle"),
    "BH140": ("River",                 "Hydrography"),
    "BH080": ("Lake",                  "Hydrography"),
    "BH090": ("Land Subject to Inundation", "Hydrography"),
    "BA040": ("Tidal Water",           "Hydrography"),
    "CA010": ("Contour Line",          "Elevation"),
    "DA010": ("Ground Surface Element (SMC = soil)", "Soil"),
    "DB170": ("Sand Dunes",            "Obstacle"),
    "DB090": ("Embankment",            "Obstacle"),
    "EA010": ("Crop Land",             "Vegetation"),
    "EB010": ("Grassland",             "Vegetation"),
    "EB020": ("Thicket / Scrub",       "Vegetation"),
    "EC015": ("Forest",                "Vegetation"),
    "ED010": ("Marsh",                 "Vegetation/Wet"),
    "ED020": ("Swamp",                 "Vegetation/Wet"),
    # ... extend from the MGCP TRD feature catalogue
    }

def classify(fc_name):
    code = fc_name.uppper_strip_prefix()   # strip cell prefixes, keep 5-char code
    if code in MGCP_CATALOG:
        return MGCP_CATALOG[code]
    return ({"A":"Culture","B":"Hydrography","C":"Elevation","D":"Physiography",
             "E":"Vegetation","F":"Boundary","G":"Aeronautical"}.get(code[:1], "Other"), )
```
Fallback on first letter means **every** FC gets at least a theme, even codes not in the dict.

**(b) Step 0 UX changes** (all driven by the catalog):
- FC filter pick-list shows `AP030 — Road (Transportation)` instead of bare `AP030`.
- New option: *"Import only CCM-relevant themes (Soil / Vegetation / Hydrography / Transportation / Obstacles / Elevation)"* — typically cuts a huge MGCP delivery down to ~15 FCs.
- Map layers grouped **by theme**, not by GDB name, with layer aliases set to the human-readable name.

**(c) Step 0 writes a manifest** — `mgcp_manifest.json` next to the output GDB:

```json
{ "gdb": "...", "features": [
    {"fc": "DA010", "name": "Ground Surface Element", "theme": "Soil",
     "geometry": "Polygon", "count": 1240, "sr": "WGS84", "has_field_SMC": true},
    {"fc": "BH140", "name": "River", "theme": "Hydrography", ...}
]}
```

**(d) Step 1 reads the manifest** and auto-populates:
- Soil FC → the manifest entry with theme `Soil` / `has_field_SMC` (source type auto = MGCP).
- `hydro_fcs` → all Hydrography polygons.
- Contours → CA010 if no DEM given.
- Everything remains overridable — the manifest only pre-fills defaults.

This closes the Step 0 → Step 1 loop with one JSON file and one dict. No new dependencies, no schema parsing at runtime.

---

## 3. Data recognition — current state

`detect_source_type()` (ccm_soil_preprocess.py:791) is well designed: name patterns → GDB fingerprinting → field fingerprinting → generic-texture fallback, with a safe `SOURCE_GENERIC` default. Two weaknesses:

1. It only exists for **soil**. Vegetation and hydro have no equivalent auto-detection; the manifest approach in §2 fixes this for the MGCP path.
2. Step 1 hard-codes `mgcp_smc_field="SMC"` (line 611). Some deliveries use `SMCL` or lowercase. Detect the field with the same candidate list used in `detect_source_type` instead of a literal.

Also: the detection result is never reported to the user as a confirmation ("Detected: MGCP via SMC field — override the Source Type if wrong"). One `AddMessage` line would make auto-detect trustworthy instead of invisible.

---

## 4. Map display after each step — inconsistent by design

Current behaviour differs per step:

| Step | Target map | Symbology |
|---|---|---|
| Step 0 | active map | none (ArcGIS defaults, random colors) |
| Step 1 | nothing added | — |
| Step 2 | derived-output auto-add | **none** — the lyrx in `Symbology\` is never applied by Step 2 |
| Step 3 | dedicated `CCM_TOOL_MAP` | ~250 lines of inline hard-coded renderer logic |

Recommendations:

1. **Step 2 one-line fix:** set the derived parameter's symbology so ArcGIS applies the lyrx automatically on add:
   ```python
   # in getParameterInfo(), on the derived output parameter:
   p_out.symbology = os.path.join(_HERE, "Symbology", "Mobility_Symbology_Final.lyrx")
   ```
   This alone fixes "Step 2 output appears in a random single color."
2. **Extract a shared `ccm_map_display.py`** with `get_ccm_map(aprx)`, `add_layer(map, fc, name, transparency)`, and one renderer function per output type. Step 0, 2, 3 all call it. The 250-line block in `ccm_step3_advanced.py` (968–1231) becomes ~30 lines and the same colors/behaviour apply no matter which tool created the layer.
3. **Pick one target-map policy.** Step 0 uses the active map, Step 3 creates `CCM_TOOL_MAP`. Suggest: all CCM outputs go to `CCM_TOOL_MAP`; Step 0 source data goes to the active map (it is input, not result) — but document this in the tool descriptions.
4. **Harden the label→color matching.** Isochrone colors are matched by substring (`"15" in label`), which mis-fires on labels like "150 min". Match on exact parsed integer values instead.
5. Replace hard-coded RGBA dicts with values read from the lyrx (or keep the dicts but move them to the display module as named constants) so the legend and the renderer can never drift apart.

---

## 5. Smaller observations

- `ccm_step0_mgcp.py` `_out_name()`: two cells whose FC names sanitize to the same `ValidateTableName` result will silently merge; log when sanitization changes a name.
- Step 0 `Append(schema_type="NO_TEST")` across mixed TRD versions is already documented as lossy in the loader README — with the catalog in place you could at least warn when appended cells have differing field sets for the same code.
- `find_config()` walks up only 2 parent levels — fine, but undocumented in tool help.
- The three superseded loader versions (`LoadMGCPData_v0.10/0.11`) plus the integrated Step 0 mean four copies of the same logic in the repo; the standalone v0.12 and Step 0 have already begun to drift (Step 0 lacks nothing today, but any future fix must be made twice). Consider making the standalone toolbox a thin wrapper that imports `ccm_step0_mgcp`.

---

## 6. Suggested v0.50 work order

1. BUG-1, BUG-2, BUG-3, BUG-4 (an hour, immediate correctness gain).
2. Step 2 derived-parameter lyrx symbology (one line).
3. `ccm_mgcp_catalog.py` + Step 0 pick-list labels + theme filter + theme group layers.
4. `mgcp_manifest.json` write (Step 0) / read (Step 1 auto-fill).
5. Extract `ccm_map_display.py`; migrate Step 3's inline block.
6. Report auto-detect decisions to the user in messages.
