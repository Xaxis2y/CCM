# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON

"""
ccm_map_display.py — shared CCM map display / symbology helpers (v0.51.0)
==========================================================================
Extracted from the ~250-line inline block in ccm_step3_advanced.py
(CODE_REVIEW_v0.49.3 recommendation #2) so every tool renders CCM outputs
with one consistent visual language:

  * ONE filled layer per map — the speed surface (red→green trafficability).
    Red always means No-Go and nothing else.
  * Isochrone / reachability bands  → HOLLOW rings, light→dark blue-purple
    outline ramp with time-band labels (no fills to stack over the surface).
  * Vehicle comparison              → categorical fill on COMPARE_RESULT,
    visible ONLY where the vehicles differ (A_ONLY teal / B_ONLY orange);
    BOTH_GO and DATA_GAP invisible, NEITHER thin grey outline.
  * Obstacle areas                  → red 45° hatching, not a solid fill.
  * Optimal route                   → white-halo + magenta line (unchanged).
  * Start / End markers             → gold / red circles (unchanged).
  * Per-run group layer "CCM — <vehicle> (<moisture>)" keeps repeat runs
    tidy; add order inside the group enforces draw order
    (points > route > obstacles > rings > compare > surface).

All functions are defensive: symbology failures degrade to a plain layer
with a warning, never an execute() failure.
"""

import arcpy
import os
import json
import tempfile

VERSION = "0.54.1"  # v0.54.1 — GPL-2.0-or-later relicense + CCM Tool rebrand (see CHANGELOG_v0.54.md).

MAP_NAME = "CCM_TOOL_MAP"

# Draw order, bottom → top.  Layers are added in this order; each
# addLayerToGroup() call inserts at the top of the group, so the last kind
# added ends up on top.
KIND_ORDER = ["surface", "compare", "isochrone", "obstacles", "route", "point"]

# ── Colour tables ──────────────────────────────────────────────────────────────

# Speed-surface condition numbers 1 (No-Go) → 5 (Go).  Red is reserved for
# No-Go across the whole map.
COND_COLOURS = {
    "1": [139,   0,   0, 240],   # No-Go    — dark red
    "2": [220,  50,  20, 225],   # Poor     — red-orange
    "3": [255, 160,   0, 210],   # Marginal — amber
    "4": [180, 210,  40, 195],   # Fair     — yellow-green
    "5": [  0, 160,  50, 180],   # Go       — green
    "default": [160, 160, 160, 150],
}

# Time-band OUTLINE ramp, light → dark blue-purple (v0.51: no red, no fills —
# red stays reserved for No-Go and fills stay reserved for the speed surface).
ISO_RING_COLOURS = {
    "15":   [144, 202, 249, 255],   # light blue   (innermost)
    "30":   [ 94, 124, 226, 255],   # medium blue
    "60":   [ 69,  39, 160, 255],   # indigo
    "1 hr": [ 69,  39, 160, 255],
    "120":  [123,  31, 162, 255],   # purple
    "2 hr": [123,  31, 162, 255],
    "240":  [ 74,  20,  90, 255],   # dark purple (outermost)
    "default": [ 94, 124, 226, 255],
}

# Vehicle-comparison categories (COMPARE_RESULT field).  Only the areas where
# the two vehicles DIFFER get a fill.
COMPARE_COLOURS = {
    "A_ONLY":  {"fill": [  0, 150, 136, 200], "outline": [0, 0, 0, 0]},    # teal
    "B_ONLY":  {"fill": [230,  81,   0, 200], "outline": [0, 0, 0, 0]},    # orange
    "NEITHER": {"fill": [  0,   0,   0,   0], "outline": [120, 120, 120, 160]},
    "BOTH_GO": {"fill": [  0,   0,   0,   0], "outline": [0, 0, 0, 0]},    # invisible
    "DATA_GAP":{"fill": [  0,   0,   0,   0], "outline": [0, 0, 0, 0]},    # invisible
}


# ── Map / group management ─────────────────────────────────────────────────────

def get_ccm_map(aprx, name=MAP_NAME, basemap="Imagery"):
    """Return (creating if needed) the dedicated CCM map."""
    existing = [m for m in aprx.listMaps() if m.name == name]
    if existing:
        arcpy.AddMessage(f"[CCM display] Found existing map: {name}")
        return existing[0]
    ccm_map = aprx.createMap(name, "MAP")
    arcpy.AddMessage(f"[CCM display] Created new map: {name}")
    try:
        ccm_map.addBasemap(basemap)
        arcpy.AddMessage(f"[CCM display] Basemap added: {basemap}")
    except Exception as e:
        arcpy.AddWarning(f"[CCM display] Basemap not added: {e}")
    return ccm_map


def ensure_group(ccm_map, group_name):
    """
    Return an (existing or new) group layer named *group_name*.
    Creation uses a temporary CIMGroupLayer .lyrx (same technique as Step 0).
    Returns None when group layers are unsupported — callers add layers flat.
    """
    try:
        hits = [l for l in ccm_map.listLayers(group_name) if l.isGroupLayer]
        if hits:
            return hits[0]
        doc = {
            "type": "CIMLayerDocument",
            "version": "3.0.0",
            "build": "36057",
            "layers": ["layers/0.json"],
            "layerDefinitions": [{
                "type": "CIMGroupLayer",
                "name": group_name,
                "uRI": "layers/0",
                "visible": True,
                "showLegends": True,
                "transparency": 0,
                "groupExpanded": True,
                "layers": []
            }],
            "binaryReferences": [],
            "layerElevationSurfaces": []
        }
        safe = "".join(c if c.isalnum() else "_" for c in group_name)[:60]
        tmp = os.path.join(tempfile.gettempdir(), f"{safe}_grp.lyrx")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f)
        ccm_map.addLayer(arcpy.mp.LayerFile(tmp))
        hits = [l for l in ccm_map.listLayers(group_name) if l.isGroupLayer]
        return hits[0] if hits else None
    except Exception as e:
        arcpy.AddWarning(f"[CCM display] Group layer '{group_name}' not created: {e}")
        return None


def existing_sources(ccm_map):
    """Normalised dataSource paths already in the map (duplicate guard)."""
    seen = set()
    for lyr in ccm_map.listLayers():
        try:
            if hasattr(lyr, "dataSource"):
                seen.add(str(lyr.dataSource).replace("\\", "/").lower())
        except Exception:
            pass
    return seen


def add_layer(ccm_map, fc_path, group=None):
    """
    Add *fc_path* to the map (nested into *group* when given).
    Returns the Layer object, or None on failure.
    """
    try:
        lyr = ccm_map.addDataFromPath(fc_path)
        if lyr is None:
            lyr = ccm_map.listLayers()[0]
        if group is not None and lyr is not None:
            try:
                ccm_map.addLayerToGroup(group, lyr)
                ccm_map.removeLayer(lyr)
                nested = [l for l in ccm_map.listLayers(lyr.name)
                          if not l.isGroupLayer]
                if nested:
                    lyr = nested[0]
            except Exception:
                pass   # leave flat if reparenting unsupported
        try:
            lyr.showLabels = False   # default: no per-feature labels
        except Exception:
            pass
        return lyr
    except Exception as e:
        arcpy.AddWarning(
            f"[CCM display] Could not add {os.path.basename(str(fc_path))}: {e}"
        )
        return None


# ── Internal helpers ───────────────────────────────────────────────────────────

def _field_has_data(fc, field_name):
    try:
        if field_name not in [f.name for f in arcpy.ListFields(fc)]:
            return False
        with arcpy.da.SearchCursor(fc, [field_name]) as sc:
            for r in sc:
                if r[0] is not None and r[0] not in ("Unknown", -1):
                    return True
        return False
    except Exception:
        return False


def _classes_of(sym):
    for grp in sym.renderer.groups:
        for cls in (getattr(grp, "classes", None) or getattr(grp, "items", [])):
            yield cls


def find_lyrx(tool_dir):
    """Locate the packaged mobility .lyrx next to the toolbox."""
    for ln in ("Mobility_Symbology_Final.lyrx", "Mobility_Symbology.lyrx"):
        c = os.path.join(tool_dir, "Symbology", ln)
        if os.path.exists(c):
            return c
    return None


# ── Per-output styling ─────────────────────────────────────────────────────────

def style_speed_surface(lyr, fc, veh_label="", lyrx_path=None):
    """Red→green Condition_Number fills — the ONLY filled layer on the map."""
    lyr.name = f"Speed Surface — {veh_label}" if veh_label else "Speed Surface"
    lyr.transparency = 55           # imagery basemap stays readable
    field = "Condition_Number"
    try:
        names = [f.name for f in arcpy.ListFields(fc)]
        for cand in ("Condition_Number", "ConditionNumber", "Condition Number",
                     "CONDITION_NUMBER", "cond_num", "CondNum"):
            if cand in names:
                field = cand
                break
    except Exception:
        pass
    try:
        sym = lyr.symbology
        sym.updateRenderer("UniqueValueRenderer")
        sym.renderer.fields = [field]
        lyr.symbology = sym
        sym2 = lyr.symbology
        for cls in _classes_of(sym2):
            rgba = COND_COLOURS.get(str(cls.label).strip(), COND_COLOURS["default"])
            cls.symbol.color        = {"RGB": rgba[:3] + [rgba[3]]}
            cls.symbol.outlineColor = {"RGB": [0, 0, 0, 0]}
        lyr.symbology = sym2
        arcpy.AddMessage(f"[CCM display] Speed Surface: UniqueValues on '{field}'.")
    except Exception as e:
        arcpy.AddWarning(f"[CCM display] Speed Surface symbology skipped: {e}")
        if lyrx_path:
            try:
                arcpy.management.ApplySymbologyFromLayer(lyr, lyrx_path, None, "MAINTAIN")
            except Exception:
                pass


def style_isochrone_rings(lyr, fc):
    """v0.51: hollow rings — coloured outlines only, blue→purple by time band."""
    lyr.name = "Reachability Rings (minutes from start)"
    lyr.transparency = 0            # outlines carry the information
    use_field = "TIME_BAND" if _field_has_data(fc, "TIME_BAND") else "gridcode"
    try:
        sym = lyr.symbology
        sym.updateRenderer("UniqueValueRenderer")
        sym.renderer.fields = [use_field]
        lyr.symbology = sym
        sym2 = lyr.symbology
        for cls in _classes_of(sym2):
            lbl  = str(cls.label)
            rgba = ISO_RING_COLOURS["default"]
            for key, col in ISO_RING_COLOURS.items():
                if key != "default" and key in lbl:
                    rgba = col
                    break
            cls.symbol.color        = {"RGB": [0, 0, 0, 0]}          # hollow
            cls.symbol.outlineColor = {"RGB": rgba[:3] + [rgba[3]]}
            cls.symbol.outlineWidth = 2.5
        lyr.symbology = sym2
        arcpy.AddMessage(
            f"[CCM display] Isochrone: hollow rings on '{use_field}' "
            "(blue→purple ramp)."
        )
    except Exception as e:
        arcpy.AddWarning(f"[CCM display] Isochrone ring symbology skipped: {e}")
    try:
        lyr.showLabels = True
        lc = lyr.listLabelClasses()
        if lc:
            lc[0].expression = f"$feature.{use_field}"
            lc[0].SQLQuery   = ""
    except Exception as e:
        arcpy.AddWarning(f"[CCM display] Isochrone labels skipped: {e}")


def style_compare(lyr, name_a="Vehicle A", name_b="Vehicle B"):
    """v0.51: categorical COMPARE_RESULT renderer — only differences visible."""
    lyr.name = f"Vehicle Comparison — {name_a} vs {name_b}"
    lyr.transparency = 25
    try:
        sym = lyr.symbology
        sym.updateRenderer("UniqueValueRenderer")
        sym.renderer.fields = ["COMPARE_RESULT"]
        lyr.symbology = sym
        sym2 = lyr.symbology
        for cls in _classes_of(sym2):
            key  = str(cls.label).strip().upper()
            spec = COMPARE_COLOURS.get(key)
            if spec is None:
                spec = {"fill": [0, 0, 0, 0], "outline": [0, 0, 0, 0]}
            cls.symbol.color        = {"RGB": spec["fill"]}
            cls.symbol.outlineColor = {"RGB": spec["outline"]}
            cls.symbol.outlineWidth = 0.7
            if key == "A_ONLY":
                cls.label = f"{name_a} only"
            elif key == "B_ONLY":
                cls.label = f"{name_b} only"
        lyr.symbology = sym2
        arcpy.AddMessage(
            "[CCM display] Vehicle Compare: categorical renderer "
            f"({name_a} teal / {name_b} orange; agreement areas hidden)."
        )
    except Exception as e:
        arcpy.AddWarning(f"[CCM display] Vehicle Compare symbology skipped: {e}")


def style_obstacles(lyr):
    """v0.51: red 45-degree hatching instead of a near-opaque solid fill."""
    lyr.name = "Obstacle Areas"
    lyr.transparency = 0
    try:
        cim = lyr.getDefinition("V3")
        cim.renderer.symbol.symbol = {
            "type": "CIMPolygonSymbol",
            "symbolLayers": [
                {
                    "type": "CIMSolidStroke",
                    "enable": True,
                    "capStyle": "Round",
                    "joinStyle": "Round",
                    "width": 1.5,
                    "color": {"type": "CIMRGBColor", "values": [198, 40, 40, 100]}
                },
                {
                    "type": "CIMHatchFill",
                    "enable": True,
                    "lineSymbol": {
                        "type": "CIMLineSymbol",
                        "symbolLayers": [{
                            "type": "CIMSolidStroke",
                            "enable": True,
                            "width": 1.2,
                            "color": {"type": "CIMRGBColor",
                                      "values": [198, 40, 40, 100]}
                        }]
                    },
                    "rotation": 45,
                    "separation": 5
                }
            ]
        }
        lyr.setDefinition(cim)
        arcpy.AddMessage("[CCM display] Obstacles: red hatching applied.")
    except Exception as e:
        arcpy.AddWarning(f"[CCM display] Obstacle hatching fallback (solid outline): {e}")
        try:
            sym = lyr.symbology
            if hasattr(sym, "renderer") and hasattr(sym.renderer, "symbol"):
                sym.renderer.symbol.color        = {"RGB": [0, 0, 0, 0]}
                sym.renderer.symbol.outlineColor = {"RGB": [198, 40, 40, 255]}
                sym.renderer.symbol.outlineWidth = 2.0
                lyr.symbology = sym
        except Exception:
            pass


def style_route(lyr):
    """White-halo + magenta 'glow' line (2-layer CIM symbol)."""
    lyr.name = "Optimal Route"
    try:
        cim = lyr.getDefinition("V3")
        cim.renderer.symbol.symbol = {
            "type": "CIMLineSymbol",
            "symbolLayers": [
                {
                    "type": "CIMSolidStroke",
                    "enable": True,
                    "capStyle": "Round",
                    "joinStyle": "Round",
                    "width": 2.5,
                    "color": {"type": "CIMRGBColor", "values": [255, 0, 200, 100]}
                },
                {
                    "type": "CIMSolidStroke",
                    "enable": True,
                    "capStyle": "Round",
                    "joinStyle": "Round",
                    "width": 6,
                    "color": {"type": "CIMRGBColor", "values": [255, 255, 255, 80]}
                }
            ]
        }
        lyr.setDefinition(cim)
        arcpy.AddMessage("[CCM display] Route: magenta glow line applied.")
    except Exception as e:
        arcpy.AddWarning(f"[CCM display] Route glow fallback: {e}")
        try:
            sym = lyr.symbology
            if hasattr(sym, "renderer") and hasattr(sym.renderer, "symbol"):
                sym.renderer.symbol.color = {"RGB": [255, 0, 200, 255]}
                sym.renderer.symbol.size  = 3
                lyr.symbology = sym
        except Exception:
            pass


def style_point(lyr, kind="start"):
    """Gold (start) / red (end) circle markers."""
    colours = {"start": [255, 215, 0, 255], "end": [255, 80, 80, 255]}
    lyr.name = "★ Start Point" if kind == "start" else "★ End Point"
    try:
        lyr.showLabels = False
        sym = lyr.symbology
        if hasattr(sym, "renderer") and hasattr(sym.renderer, "symbol"):
            try:
                sym.renderer.symbol.applySymbolFromGallery("Circle 1")
            except Exception:
                pass
            sym.renderer.symbol.color        = {"RGB": colours.get(kind, colours["start"])}
            sym.renderer.symbol.outlineColor = {"RGB": [30, 30, 30, 255]}
            sym.renderer.symbol.size         = 22
            lyr.symbology = sym
    except Exception as e:
        arcpy.AddWarning(f"[CCM display] {kind} point symbology skipped: {e}")


# ── Kind classification ────────────────────────────────────────────────────────

def kind_of(fc_path):
    """Classify an output FC path into a display kind (see KIND_ORDER)."""
    base = os.path.basename(str(fc_path)).lower()
    if "speed_surface" in base:
        return "surface"
    if "isochrone" in base:
        return "isochrone"
    if "obstacle" in base:
        return "obstacles"
    if "compare" in base:
        return "compare"
    if "route" in base or "waypoint" in base:
        return "route"
    return "surface"   # unknown area outputs sit at the bottom


def sort_for_draw_order(fc_paths):
    """Sort output FCs bottom→top so add order produces the right stacking."""
    rank = {k: i for i, k in enumerate(KIND_ORDER)}
    return sorted((f for f in fc_paths if f), key=lambda f: rank[kind_of(f)])

# <<< END OF FILE >>>
