# CHANGELOG — CCM Tool v0.56.x

SPDX-License-Identifier: GPL-2.0-or-later
Copyright (c) 2026 Eui Soo SON

---

## v0.56.0 — 2026-08-07 — Step 0 usability: geometry groups, no more "Unknown feature"

A **Step 0 (Load MGCP Data)** release. Nothing in the Step 1/2/3/4
geoprocessing chain changed; the mobility model, its factors and every
output feature class are byte-for-byte the same as v0.55.1.

The trigger: loading a full MGCP delivery worked, but the result was hard
to *use*. Every feature class arrived as its own top-level layer inside
one group per MGCP theme — a dozen groups, dozens of layers — and a large
share of them were labelled `Unknown feature (XXnnn)` because the FACC
code was not in the built-in catalog.

---

### 1. Map layers now group by geometry — Point / Line / Polygon

**New parameter (index 16): "Group Layers in Map By"** — `Geometry` /
`Theme` / `GDB Name` / `None` / `(legacy)`. Default is **Geometry**.

- Creates exactly three groups: **Point**, **Line**, **Polygon** (plus
  `Other` only if a geometry cannot be determined).
- Groups are inserted in **cartographic draw order** — Point at the top of
  the Contents pane, then Line, then Polygon — so points are not buried
  under polygon fills. This is the opposite of the order they are created
  in, because each group is inserted at the top.
- Geometry comes from `arcpy.Describe().shapeType`. When that is
  unavailable, `ccm_mgcp_catalog.geometry_group()` falls back to the MGCP /
  DIGEST name-suffix conventions: `...Pnt` / `...Crv` / `...Srf`,
  `_P` / `_L` / `_A`, and `AP030L`-style single-letter suffixes.
- Re-running Step 0 **reuses** an existing group of the same name instead
  of stacking a second "Point" group.

The two old checkboxes (parameter 9 "Group by GDB Name", parameter 13
"Group by Theme") still exist so no saved model or script breaks. They are
now inert unless "Group Layers in Map By" is set to the legacy sentinel,
and the tool dialog says so if you tick one while a real mode is selected.
Parameter indices 0–15 are unchanged; every new parameter is appended.

### 2. "Unknown feature (XXnnn)" is gone

`ccm_mgcp_catalog.lookup()` now resolves a feature-class name through five
ordered tiers and reports which one fired in a new `match` key:

| tier | `match` | what it means |
|---|---|---|
| 1 | `user` | your own override from `mgcp_catalog_user.csv` |
| 2 | `exact` | the FACC code is in the built-in `MGCP_CATALOG` |
| 3 | `category` | the code is not catalogued, but its **2-letter FACC category** is |
| 4 | `keyword` | no FACC code at all — classified from the **name** |
| 5 | `none` | nothing matched → theme `Other` |

**Tier 3** is the main fix. The FACC category structure is stable across
TRD revisions, so `AP999` is reliably a *"Road / track feature
(Transportation)"* even though its exact meaning is unknown here — a real
classification with the correct theme, not a guess at the feature name.
No `ccm_role` is inferred at this tier: an unverified layer must never be
fed silently into the mobility model.

**Tier 4** handles MGCP TRD 4.x thematic deliveries, whose feature classes
(`HydrographySrf`, `TransportationGroundCrv`, `VegetationSrf`, …) carry no
FACC code at all and previously all collapsed into theme `Other`. Roles
are inferred here only for the two unambiguous cases — a *soil* layer and
a *contour* layer. Note that "contour" specifically, not "elevation": a
spot-height layer given `ROLE_CONTOURS` would have silently produced a
wrong slope surface in Step 1.

**Deliberately not done:** inventing human-readable names for FACC codes
that could not be verified against an authoritative MGCP TRD feature
catalogue. A wrong name is worse than an honest category. A modest number
of well-attested codes were added to the built-in catalog (`AA050`,
`AF030`, `AF040`, `AJ050`, `AJ051`, `AJ110`, `AK030`, `AK120`, `AL208`,
`AP040`, `AP041`, `AQ070`, `AQ125`, `AQ150`, `AQ170`, `AT005`, `ZD020`);
everything else is covered by the category fallback and by:

### 3. `mgcp_catalog_user.csv` — name the codes in *your* delivery

Step 0 now lists the codes that only reached a category match, and writes
an editable template beside the output GDB:

```
code,name,theme,ccm_role
AP999,,Transportation,
AZ123,,Culture,
```

Fill in the `name` column from your own TRD Feature and Attribute
Catalogue and re-run — the map layers, the aliases and the manifest all
pick your names up. Rows you have already filled in are preserved when the
template is refreshed. The file is looked up, in order, from
`$CCM_MGCP_CATALOG_USER`, the output-GDB folder, then the toolbox folder.
Controlled by new parameter 17 (default on).

### 4. Readable feature-class aliases (new parameter 18, default on)

`AL015` keeps its MGCP code as the feature-class **name** — so the
manifest, Step 1 auto-fill and the FC filter all still resolve by code —
but gains the **alias** `Building (AL015)`, which is what ArcGIS Pro shows
in Catalog view and in layer properties. Alias-only; the schema is never
touched.

### 5. Reusable `.lyrx` group templates (new parameter 19, default off)

Exports each finished group to `<GDB folder>/Layer_Templates/MGCP_<group>.lyrx`.
Dragging one onto a new map reapplies the group structure and the readable
layer naming, so the Contents pane never has to be rebuilt by hand for the
next delivery.

### 6. Scale-dependent drawing for dense layers (new parameter 20, default 0 = off)

Set it to, say, `10000` and dense Line/Polygon layers draw only at
1:10,000 or closer. Point layers are cheap and are left alone; **road and
rail layers are exempt** — they are the mobility network, and losing them
when zoomed out defeats the purpose of the map.

### 7. Unknown-CRS handling hardened

- **Ordering fix.** When an Output Coordinate System is set, arcpy
  reprojects on copy. A source with no `.prj` has an *undefined* CRS, so
  that reprojection was undefined too — and until now the WGS84 repair ran
  **after** `CopyFeatures`, i.e. too late to help. WGS84 is now assigned to
  the **source** first (a `.prj` sidecar; coordinates untouched), so the
  reprojection starts from a defined CRS. If the source is read-only the
  tool now says so loudly, because the output may be mispositioned.
- **Post-run sweep.** Any output feature class still lacking a CRS after an
  APPEND into a pre-existing FC is assigned WGS84. The pre-copy repair only
  covers the `CopyFeatures` path.
- **Less noise.** The per-feature-class `[NO CRS]` warnings are
  consolidated into a single summary line.

### 8. Also in this release

- Layers are **always** renamed to their catalog label, not only when
  grouping by theme.
- `mgcp_manifest.json` gains `match`, `geometry_group` per feature and a
  top-level `unclassified_codes` list.
- Step 0 logs a **classification-by-geometry** summary alongside the
  existing classification-by-theme summary.
- `soil_preprocess_concept.html` now has a **light theme** in addition to
  its dark one. Every colour moved into CSS variables; the light palette is
  applied automatically when the OS asks for it and can be forced either
  way with a toggle in the top-right corner. All body/background pairs were
  checked to at least WCAG AA (4.5:1) contrast.
- `build.py` no longer double-packages a release zip that has been
  unpacked *inside* the project folder — `os.walk()` used to descend into
  `CCM_Tool_v<ver>/CCM_Tool_v<ver>/...` and add every file a second time
  under a nested arc-path. Such directories are now pruned and reported.

---

### Files changed in v0.56.0

| File | Change |
|---|---|
| `ccm_mgcp_catalog.py` | Category/keyword fallback tiers, `match` key, user-override CSV, `geometry_group()` / `sort_geometry_groups()` / `alias()`, catalog additions |
| `ccm_step0_mgcp.py` | Parameters 16–20, geometry grouping, alias pass, `.lyrx` export, scale thresholds, CRS ordering fix + sweep, unclassified reporting |
| `build.py` | Release-extraction prune + report |
| `soil_preprocess_concept.html` | Light theme + toggle |
| all other `ccm_*.py`, `.pyt`, tests, docs | Version bump to 0.56.0 |

### Compatibility

- Parameter indices 0–15 are unchanged; 16–20 are appended. Existing
  scripts, models and `run_tool` calls keep working.
- `mgcp_manifest.json` only gains keys; Step 1's reader is unaffected.
- `ccm_mgcp_catalog.lookup()` gains a `match` key; existing keys keep their
  meaning. Code that assumed the literal string `"Unknown feature (…)"`
  will no longer see it — that is the point of the release.

# <<< END OF FILE >>>
