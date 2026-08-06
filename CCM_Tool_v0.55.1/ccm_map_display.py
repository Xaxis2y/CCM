# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
ccm_map_display.py — shared CCM map display / symbology helpers
==========================================================================
Extracted from the ~250-line inline block in ccm_step3_advanced.py
(CODE_REVIEW_v0.49.3 recommendation #2) so every tool renders CCM outputs
with one consistent visual language:

  * ONE filled layer per map — the speed surface, coloured by the Mobility
    class (GO green / RESTRICTED amber / NO GO red).  Red always means
    No-Go and nothing else.
  * Isochrone / reachability bands  → HOLLOW rings, light→dark blue-purple
    outline ramp with time-band labels (no fills to stack over the surface).
  * Vehicle comparison              → categorical fill on COMPARE_RESULT,
    visible ONLY where the vehicles differ (A_ONLY teal / B_ONLY orange);
    BOTH_GO and DATA_GAP invisible, NEITHER thin grey outline.
  * Obstacle areas                  → red 45° hatching, not a solid fill.
  * Optimal route                   → white-halo + magenta line.
  * Start / End markers             → gold / red circles.
  * Per-run group layer "CCM — <vehicle> (<moisture>)" keeps repeat runs
    tidy; add order inside the group enforces draw order
    (points > route > obstacles > rings > compare > surface).

All functions are defensive: symbology failures degrade to a plain layer
with a warning, never an execute() failure.

v0.54.4 changes
---------------
  - FIX (critical): style_speed_surface() rendered on "Condition_Number",
    a field that NO CCM module has ever produced.  The real Step 2 output
    contract field is "Mobility" (values GO / RESTRICTED / NO GO — see
    ccm_step2_mobility.FIELD_MOBILITY).  The speed surface — the primary
    deliverable of the whole toolbox — therefore rendered either as a flat
    default colour or not at all whenever Step 3 rebuilt the map.  The
    renderer now resolves the Mobility field, and the field's existence is
    verified BEFORE the renderer is assigned.
  - FIX (critical): every colour table used a 0-255 alpha channel, but
    arcpy's CIM colour dict — {"RGB": [r, g, b, a]} — takes alpha on a
    0-100 scale (confirmed by the packaged Mobility_Symbology_Final.lyrx,
    whose every CIMRGBColor uses alpha 0 or 100).  Alpha values of 150-255
    were silently clamped to opaque, so the intended per-class transparency
    never rendered.  All tables are now on the correct 0-100 scale.
  - FIX: the .lyrx fallback in style_speed_surface() was wrapped in a bare
    `except Exception: pass`, so a missing Symbology/ folder produced an
    unstyled layer with no diagnostic at all.  Fallbacks now report.
  - The packaged Symbology/Mobility_Symbology*.lyrx is now the single
    source of truth for the speed-surface look: style_speed_surface()
    applies it first, exactly as Step 2 does via its derived output
    parameter, so a map built by Step 2 and one rebuilt by Step 3 are
    identical (they previously used two different palettes).
    MOBILITY_COLOURS is the programmatic fallback for when the Symbology
    folder is missing.
  - The .lyrx legend previously carried four classes Step 2 can never
    emit — SLOW, VERY SLOW, NO GO - Hydro Feature, NO GO - Vegetation —
    so every finished map showed a seven-entry legend with four blank
    rows.  Both .lyrx files are pruned to GO / RESTRICTED / NO GO.
  - kind_of() returns None for unrecognised outputs instead of silently
    mislabelling them "surface" (which applied speed-surface symbology to
    whatever it was).  sort_for_draw_order() places unknowns at the bottom.
  See CHANGELOG_v0.54.md.
"""

import arcpy
import os
import json
import tempfile

VERSION = "0.55.1"  # v0.55.1 -- version bump only: added QUICK_START.html and CCM_anaconda_environment.bat (Anaconda Prompt environment setup script); no code/logic changes. See CHANGELOG_v0.55.md.

MAP_NAME = "CCM_TOOL_MAP"

# Layer-level see-through for the speed surface, as a 0-100 PERCENTAGE
# (lyr.transparency is a percentage; it is unrelated to the 0-100 alpha in the
# CIM colour dicts below).  55 keeps the imagery basemap legible underneath.
SURFACE_TRANSPARENCY = 55

# Draw order, bottom → top.  Layers are added in this order; each
# addLayerToGroup() call inserts at the top of the group, so the last kind
# added ends up on top.
KIND_ORDER = ["surface", "compare", "isochrone", "obstacles", "route", "point"]

# ── Colour tables ──────────────────────────────────────────────────────────────
#
# IMPORTANT — ALPHA SCALE.  arcpy's CIM colour dictionary takes alpha on a
# 0-100 scale (0 = fully transparent, 100 = fully opaque), NOT 0-255.  This
# matches the CIMRGBColor "values" arrays in the packaged .lyrx files.  Values
# above 100 are clamped to opaque by ArcGIS Pro, which is what silently broke
# the per-class transparency before v0.54.4.  Per-LAYER see-through is set
# separately via lyr.transparency, which IS a 0-100 percentage.

# Speed-surface Mobility classes.  Keys are the UPPERCASED values written by
# ccm_step2_mobility (MOB_GO / MOB_RESTRICTED / MOB_NOGO).  Red is reserved
# for NO GO across the whole map.
#
# This is the FALLBACK palette, used only when the packaged .lyrx cannot be
# found or applied.  The .lyrx itself is the primary source of truth (see
# style_speed_surface) and uses the same GO/RESTRICTED hues; its NO GO class
# is a red cross-hatch rather than the solid red used here, because a
# UniqueValueRenderer built through arcpy cannot express a hatch fill.
MOBILITY_COLOURS = {
    "GO":         [ 56, 168,   0, 100],   # green
    "RESTRICTED": [255, 170,   0, 100],   # amber
    "NO GO":      [255,   0,   0, 100],   # red — No-Go only
    "NOGO":       [255,   0,   0, 100],   # tolerate an unspaced variant
    "default":    [160, 160, 160, 100],   # grey — unclassified / no data
}

# Deprecated alias kept so any external caller that still imports the old
# name keeps working.  Retarget new code at MOBILITY_COLOURS.
COND_COLOURS = MOBILITY_COLOURS

# Field names that may carry the mobility class, best first.
MOBILITY_FIELD_CANDIDATES = (
    "Mobility", "MOBILITY", "mobility", "Mobility_Class", "MobilityClass",
)

# Time-band OUTLINE ramp, light → dark blue-purple (no red, no fills — red
# stays reserved for No-Go and fills stay reserved for the speed surface).
ISO_RING_COLOURS = {
    "15":   [144, 202, 249, 100],   # light blue   (innermost)
    "30":   [ 94, 124, 226, 100],   # medium blue
    "60":   [ 69,  39, 160, 100],   # indigo
    "1 hr": [ 69,  39, 160, 100],
    "120":  [123,  31, 162, 100],   # purple
    "2 hr": [123,  31, 162, 100],
    "240":  [ 74,  20,  90, 100],   # dark purple (outermost)
    "default": [ 94, 124, 226, 100],
}

# Vehicle-comparison categories (COMPARE_RESULT field).  Only the areas where
# the two vehicles DIFFER get a fill.
COMPARE_COLOURS = {
    "A_ONLY":  {"fill": [  0, 150, 136, 100], "outline": [0, 0, 0, 0]},    # teal
    "B_ONLY":  {"fill": [230,  81,   0, 100], "outline": [0, 0, 0, 0]},    # orange
    "NEITHER": {"fill": [  0,   0,   0,   0], "outline": [120, 120, 120, 65]},
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

def _field_names(fc):
    """Field names on *fc*, or [] when the FC cannot be described."""
    try:
        return [f.name for f in arcpy.ListFields(fc)]
    except Exception:
        return []


def _field_has_data(fc, field_name):
    try:
        if field_name not in _field_names(fc):
            return False
        with arcpy.da.SearchCursor(fc, [field_name]) as sc:
            for r in sc:
                if r[0] is not None and r[0] not in ("Unknown", -1):
                    return True
        return False
    except Exception:
        return False


def _set_transparency(lyr, pct):
    """
    Set layer transparency, AFTER symbology has been applied.

    v0.54.4: this used to run before ApplySymbologyFromLayer, which reset it
    back to 0 — the ArcGIS Pro verification run reported
    "Transparency : 0.0" where 55 was intended, so the finished speed surface
    was fully opaque and hid the imagery basemap underneath it.
    """
    try:
        lyr.transparency = pct
    except Exception as e:
        arcpy.AddWarning(f"[CCM display] Could not set transparency on "
                         f"{getattr(lyr, 'name', '?')}: {e}")


def _classes_of(sym):
    for grp in sym.renderer.groups:
        for cls in (getattr(grp, "classes", None) or getattr(grp, "items", [])):
            yield cls


def resolve_field(fc, candidates):
    """
    Return the first name in *candidates* that actually exists on *fc*.

    Returns None when none of them do.  Resolving BEFORE assigning
    renderer.fields is what keeps a renaming mistake from producing a
    zero-class renderer (the v0.54.4 Condition_Number defect).
    """
    names = _field_names(fc)
    if not names:
        return None
    lowered = {n.lower(): n for n in names}
    for cand in candidates:
        if cand in names:
            return cand
        hit = lowered.get(cand.lower())
        if hit:
            return hit
    return None


def find_lyrx(tool_dir):
    """Locate the packaged mobility .lyrx next to the toolbox."""
    for ln in ("Mobility_Symbology_Final.lyrx", "Mobility_Symbology.lyrx"):
        c = os.path.join(tool_dir, "Symbology", ln)
        if os.path.exists(c):
            return c
    return None


# ── Per-output styling ─────────────────────────────────────────────────────────

def style_speed_surface(lyr, fc, veh_label="", lyrx_path=None):
    """
    Style the speed surface — the ONLY filled layer on the map.

    Order of preference:

      1. Apply the packaged Symbology/Mobility_Symbology*.lyrx.  This is the
         SAME artefact Step 2 attaches to its derived output parameter, so a
         map built by Step 2 and one rebuilt by Step 3 are pixel-identical
         (review item C3).  It also carries the red cross-hatch for NO GO,
         which reads better than a flat fill and stays legible to colour-blind
         users — a texture a programmatic UniqueValueRenderer cannot build.
      2. If no .lyrx is available, build a UniqueValueRenderer on the Mobility
         field using MOBILITY_COLOURS (GO green / RESTRICTED amber / NO GO
         solid red).
      3. If the Mobility field is absent too, say so loudly rather than
         leaving a silently mis-rendered layer on the map.

    Layer transparency is applied AFTER symbology in every branch — applying
    it first lets ApplySymbologyFromLayer reset it (see _set_transparency).
    """
    lyr.name = f"Speed Surface — {veh_label}" if veh_label else "Speed Surface"

    # ── 1. Packaged .lyrx — the single source of truth ───────────────────────
    if lyrx_path:
        try:
            arcpy.management.ApplySymbologyFromLayer(
                lyr, lyrx_path, None, "MAINTAIN")
            _set_transparency(lyr, SURFACE_TRANSPARENCY)
            arcpy.AddMessage(
                "[CCM display] Speed Surface: applied "
                f"{os.path.basename(lyrx_path)} "
                "(GO green / RESTRICTED amber / NO GO red hatch)."
            )
            return
        except Exception as e:
            arcpy.AddWarning(
                f"[CCM display] Speed Surface: {os.path.basename(lyrx_path)} "
                f"could not be applied ({e}) — building the renderer directly."
            )

    # ── 2. Programmatic fallback on the Mobility field ───────────────────────
    field = resolve_field(fc, MOBILITY_FIELD_CANDIDATES)
    if not field:
        arcpy.AddWarning(
            "[CCM display] Speed Surface has no Mobility field (looked for "
            f"{', '.join(MOBILITY_FIELD_CANDIDATES)}) and no usable .lyrx — "
            "the layer will draw with ArcGIS Pro's default random symbology. "
            "Confirm this feature class came from Step 2 and that the "
            "Symbology folder shipped alongside the toolbox."
        )
        return

    try:
        sym = lyr.symbology
        sym.updateRenderer("UniqueValueRenderer")
        sym.renderer.fields = [field]
        lyr.symbology = sym
        sym2 = lyr.symbology
        n_classes = 0
        for cls in _classes_of(sym2):
            n_classes += 1
            key = str(cls.label).strip().upper()
            rgba = MOBILITY_COLOURS.get(key, MOBILITY_COLOURS["default"])
            cls.symbol.color        = {"RGB": list(rgba)}
            cls.symbol.outlineColor = {"RGB": [0, 0, 0, 0]}
        if n_classes == 0:
            arcpy.AddWarning(
                f"[CCM display] Speed Surface renderer on '{field}' produced "
                "no classes — the field exists but appears to be empty. "
                "Check that Step 2 completed successfully."
            )
            return
        lyr.symbology = sym2
        _set_transparency(lyr, SURFACE_TRANSPARENCY)
        arcpy.AddMessage(
            f"[CCM display] Speed Surface: UniqueValues on '{field}' "
            f"({n_classes} classes — GO green / RESTRICTED amber / NO GO red)."
        )
    except Exception as e:
        arcpy.AddWarning(
            f"[CCM display] Speed Surface symbology failed entirely: {e}"
        )


def style_isochrone_rings(lyr, fc):
    """Hollow rings — coloured outlines only, blue→purple by time band."""
    lyr.name = "Reachability Rings (minutes from start)"
    try:
        lyr.transparency = 0        # outlines carry the information
    except Exception:
        pass
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
            cls.symbol.outlineColor = {"RGB": list(rgba)}
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
    """Categorical COMPARE_RESULT renderer — only differences visible."""
    lyr.name = f"Vehicle Comparison — {name_a} vs {name_b}"
    try:
        lyr.transparency = 25
    except Exception:
        pass
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
            cls.symbol.color        = {"RGB": list(spec["fill"])}
            cls.symbol.outlineColor = {"RGB": list(spec["outline"])}
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
    """Red 45-degree hatching instead of a near-opaque solid fill."""
    lyr.name = "Obstacle Areas"
    try:
        lyr.transparency = 0
    except Exception:
        pass
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
                sym.renderer.symbol.outlineColor = {"RGB": [198, 40, 40, 100]}
                sym.renderer.symbol.outlineWidth = 2.0
                lyr.symbology = sym
        except Exception as e2:
            arcpy.AddWarning(
                f"[CCM display] Obstacle outline fallback also failed: {e2}"
            )


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
                sym.renderer.symbol.color = {"RGB": [255, 0, 200, 100]}
                sym.renderer.symbol.size  = 3
                lyr.symbology = sym
        except Exception as e2:
            arcpy.AddWarning(f"[CCM display] Route fallback also failed: {e2}")


def style_point(lyr, kind="start"):
    """Gold (start) / red (end) circle markers."""
    colours = {"start": [255, 215, 0, 100], "end": [255, 80, 80, 100]}
    lyr.name = "Start Point" if kind == "start" else "End Point"
    try:
        lyr.showLabels = False
        sym = lyr.symbology
        if hasattr(sym, "renderer") and hasattr(sym.renderer, "symbol"):
            try:
                sym.renderer.symbol.applySymbolFromGallery("Circle 1")
            except Exception:
                pass
            sym.renderer.symbol.color        = {"RGB": colours.get(kind, colours["start"])}
            sym.renderer.symbol.outlineColor = {"RGB": [30, 30, 30, 100]}
            sym.renderer.symbol.size         = 22
            lyr.symbology = sym
    except Exception as e:
        arcpy.AddWarning(f"[CCM display] {kind} point symbology skipped: {e}")


# ── Kind classification ────────────────────────────────────────────────────────

def kind_of(fc_path):
    """
    Classify an output FC path into a display kind (see KIND_ORDER).

    Returns None for a path that matches no known output.  Before v0.54.4
    unknowns fell through to "surface", which applied speed-surface
    symbology to whatever it happened to be; callers should now skip
    styling and leave such a layer with its default rendering.
    """
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
    return None


def sort_for_draw_order(fc_paths):
    """
    Sort output FCs bottom→top so add order produces the right stacking.

    Unrecognised outputs (kind_of() -> None) sort to the very bottom, below
    the speed surface, so they can never obscure a classified layer.
    """
    rank = {k: i for i, k in enumerate(KIND_ORDER)}

    def _rank(f):
        k = kind_of(f)
        return rank[k] if k in rank else -1

    return sorted((f for f in fc_paths if f), key=_rank)

# <<< END OF FILE >>>
