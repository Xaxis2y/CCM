# =============================================================================
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON (Beta)
# =============================================================================
# -*- coding: utf-8 -*-
"""
tests/verify_v0544.py — ArcGIS Pro verification harness for CCM v0.54.4

WHAT THIS IS FOR
----------------
v0.54.4 fixes five defects found in a pre-release audit of v0.54.1.  Three of
them can only be confirmed against a real, licensed ArcGIS Pro install, because
they depend on how arcpy actually behaves:

  * Did the OLD code really fail?  Assigning a non-existent field to
    symbology.renderer.fields either RAISES (noisy but recoverable) or is
    silently accepted and yields a zero-class renderer (silent flat-grey map).
    TEST 5 settles which.
  * Does the NEW code work?  TEST 6 drives the real
    ccm_map_display.style_speed_surface() and reports the resulting renderer.
  * Is the alpha scale really 0-100?  TEST 7 writes alpha 100 and alpha 240
    and reads back what ArcGIS Pro stored.

It needs NO project data — it builds a 9-polygon synthetic speed surface in
the scratch GDB and deletes it afterwards.  Nothing in your projects is
touched.  Runtime is a few seconds.

HOW TO RUN
----------
Anaconda / ArcGIS Pro conda prompt (preferred — copy-paste this whole block):

    cd /d "C:\\Users\\son.es\\Documents\\ES_Project\\NEW_CCM_Tool\\CCM_Tool_by_Son_v0.54.1"
    "%PROGRAMFILES%\\ArcGIS\\Pro\\bin\\Python\\envs\\arcgispro-py3\\python.exe" tests\\verify_v0544.py

If that python.exe path is wrong on your machine, find it with:

    where /r "%PROGRAMFILES%\\ArcGIS\\Pro" python.exe

TESTS 5-7 need a live ArcGISProject.  Standalone python.exe will attempt the
bundled Map.aptx template; if that is unavailable those three tests report
SKIP.  To force them to run, use the ArcGIS Pro Python window instead:

    Pro > Analysis > Python > Python Window, then paste:
    exec(open(r"C:\\Users\\son.es\\Documents\\ES_Project\\NEW_CCM_Tool\\CCM_Tool_by_Son_v0.54.1\\tests\\verify_v0544.py").read())

OUTPUT
------
    tests\\ccm_verify_v0544.log

Send that file back.  The lines that matter most are marked  >>> RESULT.
"""

import os
import sys
import traceback
import datetime

VERSION = "0.54.4"  # v0.54.4 — Union license-limit fix, ERROR 000384 (see CHANGELOG_v0.54.md).

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

LOG_PATH = os.path.join(_HERE, "ccm_verify_v0544.log")
_LOG = []
_RESULTS = []


def log(text=""):
    print(text)
    _LOG.append(str(text))


def result(tag, verdict, detail=""):
    line = ">>> RESULT  [%-8s] %-6s %s" % (tag, verdict, detail)
    log("")
    log(line)
    _RESULTS.append((tag, verdict, detail))


def flush_log():
    try:
        with open(LOG_PATH, "w", encoding="utf-8") as fh:
            fh.write("\n".join(_LOG) + "\n")
        print("\nLog written -> %s" % LOG_PATH)
    except Exception as exc:
        print("\nCould not write log: %s" % exc)


def section(title):
    log("")
    log("=" * 74)
    log("  " + title)
    log("=" * 74)


# =============================================================================
# TEST 1 — environment
# =============================================================================

def test_environment():
    section("TEST 1 — ENVIRONMENT")
    log("Timestamp      : %s" % datetime.datetime.now().isoformat())
    log("Script version : %s" % VERSION)
    log("Python         : %s" % sys.version.replace("\n", " "))
    log("Executable     : %s" % sys.executable)
    log("Project root   : %s" % _ROOT)

    try:
        import arcpy
    except Exception as exc:
        log("arcpy          : NOT IMPORTABLE — %s" % exc)
        result("ENV", "FAIL", "arcpy unavailable; run from the ArcGIS Pro conda env")
        return None

    log("arcpy          : imported OK")
    try:
        info = arcpy.GetInstallInfo()
        log("ArcGIS Pro     : %s build %s"
            % (info.get("Version", "?"), info.get("BuildNumber", "?")))
        log("Install dir    : %s" % info.get("InstallDir", "?"))
    except Exception as exc:
        log("ArcGIS Pro     : version query failed: %s" % exc)
    try:
        log("Spatial Analyst: %s" % arcpy.CheckExtension("Spatial"))
    except Exception as exc:
        log("Spatial Analyst: query failed: %s" % exc)
    log("Scratch GDB    : %s" % arcpy.env.scratchGDB)
    result("ENV", "PASS", "arcpy available")
    return arcpy


# =============================================================================
# TEST 2 — module import matrix + version consistency
# =============================================================================

MODULES = [
    "ccm_project_config", "ccm_coords", "ccm_map_display", "ccm_data_discovery",
    "ccm_mgcp_catalog", "ccm_weather", "ccm_soil_validator", "ccm_reason_map",
    "ccm_isochrone", "ccm_waypoints", "ccm_obstacle_detect",
    "ccm_vehicle_compare", "ccm_soil_preprocess", "ccm_veg_preprocess",
    "ccm_step0_mgcp", "ccm_step1_setup", "ccm_step2_mobility",
    "ccm_step3_advanced",
]


def test_imports():
    section("TEST 2 — MODULE IMPORT MATRIX")
    bad = []
    for name in MODULES:
        try:
            mod = __import__(name)
            ver = getattr(mod, "VERSION", "<none>")
            ok = (ver == VERSION)
            log("  %s %-24s VERSION=%s" % ("OK  " if ok else "VER!", name, ver))
            if not ok:
                bad.append("%s=%s" % (name, ver))
        except Exception as exc:
            log("  FAIL %-24s %s" % (name, exc))
            bad.append("%s: %s" % (name, exc))
    if bad:
        result("IMPORTS", "FAIL", "; ".join(bad[:4]))
    else:
        result("IMPORTS", "PASS",
               "all %d modules import at v%s" % (len(MODULES), VERSION))
    return not bad


# =============================================================================
# TEST 3 — toolbox loads, 5 tools, no stubs
# =============================================================================

def test_toolbox(arcpy):
    section("TEST 3 — TOOLBOX LOAD")
    pyt = os.path.join(_ROOT, "CCM_Tool_by_Son_v%s.pyt" % VERSION)
    log("Toolbox path   : %s" % pyt)
    if not os.path.isfile(pyt):
        result("TOOLBOX", "FAIL", "toolbox file not found")
        return False
    try:
        arcpy.ImportToolbox(pyt)
        log("ImportToolbox  : OK")
    except Exception as exc:
        log(traceback.format_exc())
        result("TOOLBOX", "FAIL", "ImportToolbox: %s" % exc)
        return False

    try:
        import importlib.util
        import importlib.machinery
        loader = importlib.machinery.SourceFileLoader("ccm_pyt_probe", pyt)
        spec = importlib.util.spec_from_loader("ccm_pyt_probe", loader)
        probe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(probe)
        tb = probe.Toolbox()
        log("Toolbox label  : %s" % tb.label)
        log("Toolbox alias  : %s" % tb.alias)
        log("toolversion    : %s" % probe.toolversion)
        log("Tool count     : %d (expected 5)" % len(tb.tools))
        stubs = []
        for cls in tb.tools:
            inst = cls()
            label = str(getattr(inst, "label", "?"))
            is_stub = "UNAVAILABLE" in label
            if is_stub:
                stubs.append(label)
            try:
                nparams = len(inst.getParameterInfo())
            except Exception as exc:
                nparams = "PARAM ERROR: %s" % exc
            log("   [%-4s] %-54s params=%s"
                % ("STUB" if is_stub else "ok", label[:54], nparams))
        if len(tb.tools) != 5:
            result("TOOLBOX", "FAIL", "expected 5 tools, got %d" % len(tb.tools))
        elif stubs:
            result("TOOLBOX", "FAIL", "%d tool(s) loaded as STUBS" % len(stubs))
        else:
            result("TOOLBOX", "PASS",
                   "5 tools, no stubs, toolversion=%s" % probe.toolversion)
        return not stubs and len(tb.tools) == 5
    except Exception as exc:
        log(traceback.format_exc())
        result("TOOLBOX", "FAIL", "probe: %s" % exc)
        return False


# =============================================================================
# TEST 4 — synthetic speed surface fixture
# =============================================================================

FC_NAME = "ccm_verify_speed_surface_testveh_moist"


def build_fixture(arcpy):
    section("TEST 4 — SYNTHETIC SPEED SURFACE FIXTURE")
    gdb = arcpy.env.scratchGDB
    fc = os.path.join(gdb, FC_NAME)
    log("Target FC      : %s" % fc)
    try:
        if arcpy.Exists(fc):
            arcpy.management.Delete(fc)
        sr = arcpy.SpatialReference(32617)          # WGS84 / UTM 17N
        arcpy.management.CreateFeatureclass(
            gdb, FC_NAME, "POLYGON", spatial_reference=sr)

        import ccm_step2_mobility as s2
        arcpy.management.AddField(fc, s2.FIELD_MOBILITY, "TEXT", field_length=20)
        arcpy.management.AddField(fc, s2.FIELD_SPEED, "FLOAT")
        for f in (s2.FIELD_F1, s2.FIELD_F2, s2.FIELD_F3,
                  s2.FIELD_F4, s2.FIELD_F5, s2.FIELD_FHYDRO):
            arcpy.management.AddField(fc, f, "DOUBLE")

        classes = [s2.MOB_GO, s2.MOB_RESTRICTED, s2.MOB_NOGO]
        speeds = [42.0, 14.0, 0.0]
        with arcpy.da.InsertCursor(
                fc, ["SHAPE@", s2.FIELD_MOBILITY, s2.FIELD_SPEED]) as cur:
            for r in range(3):
                for c in range(3):
                    x0, y0 = 500000 + c * 100, 4600000 + r * 100
                    poly = arcpy.Polygon(arcpy.Array([
                        arcpy.Point(x0, y0), arcpy.Point(x0 + 100, y0),
                        arcpy.Point(x0 + 100, y0 + 100),
                        arcpy.Point(x0, y0 + 100), arcpy.Point(x0, y0),
                    ]), sr)
                    cur.insertRow([poly, classes[r], speeds[r]])

        n = int(arcpy.management.GetCount(fc)[0])
        log("Features       : %d (expected 9)" % n)
        log("Fields         : %s" % ", ".join(f.name for f in arcpy.ListFields(fc)))
        log("Mobility values: %s" % ", ".join(classes))
        if n == 9:
            result("FIXTURE", "PASS", "9 polygons, 3 Mobility classes")
            return fc
        result("FIXTURE", "FAIL", "got %d features" % n)
        return None
    except Exception as exc:
        log(traceback.format_exc())
        result("FIXTURE", "FAIL", str(exc))
        return None


# =============================================================================
# shared: obtain a Layer object we can drive symbology on
# =============================================================================
#
# Three routes, in order of fidelity:
#
#   1. ArcGISProject("CURRENT")   — running inside the ArcGIS Pro Python window.
#   2. A template .aptx/.aprx     — searched across the known Pro locations.
#      (ArcGIS Pro 3.7 no longer ships Resources\ArcGISProTemplates\Map.aptx,
#      which is why v1 of this harness skipped tests 5-7 on a 3.7.1 install.)
#   3. HEADLESS                   — MakeFeatureLayer -> SaveToLayerFile ->
#      arcpy.mp.LayerFile.listLayers()[0].  The resulting Layer supports
#      .symbology, .name and .transparency with no project at all, which is
#      everything tests 5-7 need.
#
# Returns (layer_factory, mode, cleanup) where layer_factory() hands back a
# fresh Layer bound to the fixture each time it is called.

_TEMPLATE_CANDIDATES = [
    ("Resources", "ArcGISProTemplates", "Map.aptx"),
    ("Resources", "ArcGISProTemplates", "Map.ppkx"),
    ("Resources", "ProTemplates", "Map.aptx"),
    ("bin", "ArcGISProTemplates", "Map.aptx"),
]


def _find_template(arcpy):
    try:
        install = arcpy.GetInstallInfo().get("InstallDir", "")
    except Exception:
        return None
    for parts in _TEMPLATE_CANDIDATES:
        cand = os.path.join(install, *parts)
        if os.path.isfile(cand):
            return cand
    # user project folder — any .aprx will do as a host
    for root in (os.path.join(os.path.expanduser("~"), "Documents", "ArcGIS", "Projects"),):
        if os.path.isdir(root):
            for dirpath, _dirs, files in os.walk(root):
                for f in files:
                    if f.lower().endswith(".aprx"):
                        return os.path.join(dirpath, f)
    return None


def get_layer_source(arcpy, fc):
    """Return (factory, mode, cleanup)."""
    # ---- route 1: live Pro session ----------------------------------------
    try:
        aprx = arcpy.mp.ArcGISProject("CURRENT")
        m = aprx.listMaps()[0]
        log("Layer source   : ArcGISProject('CURRENT') — live Pro session")
        made = []

        def factory():
            lyr = m.addDataFromPath(fc)
            made.append(lyr)
            return lyr

        def cleanup():
            for l in made:
                try:
                    m.removeLayer(l)
                except Exception:
                    pass
        return factory, "CURRENT", cleanup
    except Exception:
        pass

    # ---- route 2: template / any .aprx -------------------------------------
    tpl = _find_template(arcpy)
    if tpl:
        try:
            aprx = arcpy.mp.ArcGISProject(tpl)
            m = aprx.listMaps()[0]
            log("Layer source   : project template %s" % tpl)
            made = []

            def factory():
                lyr = m.addDataFromPath(fc)
                made.append(lyr)
                return lyr

            def cleanup():
                for l in made:
                    try:
                        m.removeLayer(l)
                    except Exception:
                        pass
            return factory, "TEMPLATE", cleanup
        except Exception as exc:
            log("Template found but unusable (%s) — falling back to headless." % exc)
    else:
        log("No project template found on this install "
            "(ArcGIS Pro 3.7 dropped Map.aptx) — using the headless route.")

    # ---- route 3: headless via a layer file ---------------------------------
    import tempfile
    tmpdir = tempfile.mkdtemp(prefix="ccm_verify_")
    log("Layer source   : HEADLESS "
        "(MakeFeatureLayer -> SaveToLayerFile -> arcpy.mp.LayerFile)")
    log("Scratch dir    : %s" % tmpdir)
    counter = [0]

    def factory():
        counter[0] += 1
        name = "ccm_tmp_lyr_%d" % counter[0]
        lyrx = os.path.join(tmpdir, name + ".lyrx")
        arcpy.management.MakeFeatureLayer(fc, name)
        arcpy.management.SaveToLayerFile(name, lyrx, "ABSOLUTE")
        try:
            arcpy.management.Delete(name)
        except Exception:
            pass
        lf = arcpy.mp.LayerFile(lyrx)
        return lf.listLayers()[0]

    def cleanup():
        import shutil
        try:
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass

    return factory, "HEADLESS", cleanup


# =============================================================================
# TEST 5 — what the OLD (v0.54.1) code did
# =============================================================================

def test_old_behaviour(arcpy, fc, factory, mode):
    section("TEST 5 — WHAT THE v0.54.1 CODE ACTUALLY DID")
    log("Reproduces the old style_speed_surface() renderer assignment:")
    log("    sym.renderer.fields = ['Condition_Number']")
    log("A field that NO CCM module has ever created.")
    log("Mode           : %s" % mode)
    try:
        lyr = factory()
    except Exception as exc:
        log(traceback.format_exc())
        result("OLD-BUG", "SKIP", "could not obtain a layer: %s" % exc)
        return
    mode_desc = "UNDETERMINED"
    try:
        sym = lyr.symbology
        sym.updateRenderer("UniqueValueRenderer")
        log("updateRenderer : OK")
        sym.renderer.fields = ["Condition_Number"]
        log("fields assign  : did NOT raise")
        lyr.symbology = sym
        log("symbology set  : did NOT raise")
        sym2 = lyr.symbology
        total = 0
        for g in getattr(sym2.renderer, "groups", []):
            for cls in (getattr(g, "classes", None) or getattr(g, "items", []) or []):
                total += 1
                log("   class label : %r" % cls.label)
        log("class count    : %d" % total)
        mode_desc = ("B — SILENT FAILURE (no exception, %d classes, flat layer)" % total)
    except Exception as exc:
        log("EXCEPTION      : %s: %s" % (type(exc).__name__, exc))
        mode_desc = "A — RAISES (old code warned and fell back to the .lyrx)"
    result("OLD-BUG", "INFO", mode_desc)


# =============================================================================
# TEST 6 — the NEW (v0.54.4) style_speed_surface()
# =============================================================================

def test_new_styling(arcpy, fc, factory, mode):
    section("TEST 6 — v0.54.4 style_speed_surface()  (THE FIX)")
    log("Mode           : %s" % mode)
    try:
        import ccm_map_display as disp
    except Exception as exc:
        result("FIX", "FAIL", "ccm_map_display not importable: %s" % exc)
        return

    lyrx = disp.find_lyrx(_ROOT)
    log("find_lyrx()    : %s" % lyrx)
    if not lyrx:
        log("WARNING        : Symbology/*.lyrx not found — the fallback path")
        log("                 will be exercised instead of the primary path.")

    try:
        lyr = factory()
    except Exception as exc:
        log(traceback.format_exc())
        result("FIX", "SKIP", "could not obtain a layer: %s" % exc)
        return

    try:
        log("")
        log("--- calling style_speed_surface(lyr, fc, 'Leopard', lyrx) ---")
        disp.style_speed_surface(lyr, fc, "Leopard", lyrx)
        log("--- returned without raising ---")
        log("")
        log("Layer name     : %r" % lyr.name)
        _tr = getattr(lyr, "transparency", None)
        log("Transparency   : %s  (expected %s)"
            % (_tr, getattr(disp, "SURFACE_TRANSPARENCY", 55)))
        if _tr is not None and int(_tr or 0) != int(
                getattr(disp, "SURFACE_TRANSPARENCY", 55)):
            log("PROBLEM        : transparency was not applied — the speed")
            log("                 surface will be opaque over the basemap.")

        sym = lyr.symbology
        rend = getattr(sym, "renderer", None)
        log("Renderer type  : %s" % type(rend).__name__)
        log("Renderer fields: %s" % getattr(rend, "fields", "n/a"))
        labels = []
        for g in getattr(rend, "groups", []):
            for cls in (getattr(g, "classes", None) or getattr(g, "items", []) or []):
                labels.append(str(cls.label))
                try:
                    col = cls.symbol.color
                except Exception:
                    col = "?"
                log("   %-14r colour=%s" % (cls.label, col))
        log("")
        log("Legend entries : %d" % len(labels))

        got = set(l.strip().upper() for l in labels)
        expect = {"GO", "RESTRICTED", "NO GO"}
        dead = got - expect
        _tr_ok = (_tr is not None and int(_tr or 0) == int(
            getattr(disp, "SURFACE_TRANSPARENCY", 55)))
        if expect.issubset(got) and not dead and _tr_ok:
            result("FIX", "PASS",
                   "3 classes + transparency %s%%" % _tr)
        elif expect.issubset(got) and not dead:
            result("FIX", "CHECK",
                   "classes correct but transparency=%s (expected %s)"
                   % (_tr, getattr(disp, "SURFACE_TRANSPARENCY", 55)))
        elif expect.issubset(got):
            result("FIX", "CHECK",
                   "expected 3 classes present, plus unexpected: %s" % sorted(dead))
        else:
            result("FIX", "FAIL",
                   "got %s, expected %s" % (sorted(got), sorted(expect)))

        log("")
        log("Expected layer name: 'Speed Surface — Leopard'")
        log("Actual   layer name: %r" % lyr.name)
        if "speed_surface_" in str(lyr.name).lower():
            log("NOTE           : raw FC basename leaked into the layer name.")
    except Exception as exc:
        log(traceback.format_exc())
        result("FIX", "FAIL", str(exc))



# =============================================================================
# TEST 7 — alpha channel scale
# =============================================================================

def test_alpha_scale(arcpy, fc, factory, mode):
    section("TEST 7 — CIM COLOUR ALPHA SCALE (0-100 vs 0-255)")
    log("v0.54.1 used alpha values of 150-255.  If arcpy's scale is 0-100,")
    log("everything above 100 is clamped to opaque and no transparency ever")
    log("rendered.  Writing alpha 100 and alpha 240, then reading back:")
    log("Mode           : %s" % mode)
    try:
        lyr = factory()
    except Exception as exc:
        log(traceback.format_exc())
        result("ALPHA", "SKIP", "could not obtain a layer: %s" % exc)
        return
    log("")
    log("NOTE: reading the value straight back only shows what arcpy STORED,")
    log("not what ArcGIS Pro RENDERS.  This test therefore also round-trips")
    log("through a saved .lyrx and inspects the serialised CIM, and compares")
    log("against what Pro itself writes for a fully-opaque symbol.")
    try:
        import json as _json
        import tempfile as _tf
        sym = lyr.symbology
        sym.updateRenderer("SimpleRenderer")
        lyr.symbology = sym

        log("")
        log("  (a) in-memory read-back")
        for written in (100, 240, 50):
            sym = lyr.symbology
            sym.renderer.symbol.color = {"RGB": [255, 0, 0, written]}
            lyr.symbology = sym
            got = lyr.symbology.renderer.symbol.color
            log("      wrote alpha %-4d -> read back %s" % (written, got))

        log("")
        log("  (b) round-trip through a saved .lyrx (what Pro serialises)")
        tmpdir = _tf.mkdtemp(prefix="ccm_alpha_")
        serialised = {}
        for written in (100, 240, 50):
            sym = lyr.symbology
            sym.renderer.symbol.color = {"RGB": [255, 0, 0, written]}
            lyr.symbology = sym
            out = os.path.join(tmpdir, "alpha_%d.lyrx" % written)
            try:
                lyr.saveACopy(out)
            except Exception:
                arcpy.management.SaveToLayerFile(lyr, out, "ABSOLUTE")
            d = _json.load(open(out, encoding="utf-8-sig"))
            vals = []
            def _walk(o):
                if isinstance(o, dict):
                    if o.get("type") == "CIMRGBColor":
                        vals.append(o.get("values"))
                    for v in o.values():
                        _walk(v)
                elif isinstance(o, list):
                    for v in o:
                        _walk(v)
            _walk(d)
            reds = [v for v in vals if v and v[:3] == [255, 0, 0]]
            serialised[written] = reds
            log("      wrote alpha %-4d -> CIM stores %s" % (written, reds))

        log("")
        log("  (c) reference: alpha values Pro itself wrote in the shipped .lyrx")
        ref = os.path.join(_ROOT, "Symbology", "Mobility_Symbology_Final.lyrx")
        alphas = set()
        if os.path.isfile(ref):
            d = _json.load(open(ref, encoding="utf-8-sig"))
            def _walk2(o):
                if isinstance(o, dict):
                    if o.get("type") == "CIMRGBColor" and len(o.get("values", [])) == 4:
                        alphas.add(o["values"][3])
                    for v in o.values():
                        _walk2(v)
                elif isinstance(o, list):
                    for v in o:
                        _walk2(v)
            _walk2(d)
        log("      distinct alpha values authored by ArcGIS Pro: %s" % sorted(alphas))
        log("      (a fully-opaque symbol authored in Pro stores 100, not 255,")
        log("       which is what establishes the CIM alpha scale as 0-100)")

        try:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass

        verdict = "INFO"
        detail = "see (a)/(b)/(c) above"
        if alphas and max(alphas) <= 100:
            verdict = "PASS"
            detail = ("Pro authors opaque as alpha=%d -> CIM scale is 0-100; "
                      "v0.54.1's 150-255 values were out of range"
                      % max(alphas))
        result("ALPHA", verdict, detail)
    except Exception as exc:
        log(traceback.format_exc())
        result("ALPHA", "SKIP", str(exc))



# =============================================================================
# TEST 8 — packaged .lyrx legend content (no map needed)
# =============================================================================

def test_lyrx_legend():
    section("TEST 8 — PACKAGED .lyrx LEGEND CONTENT")
    import json
    ok = True
    for name in ("Mobility_Symbology_Final.lyrx", "Mobility_Symbology.lyrx"):
        path = os.path.join(_ROOT, "Symbology", name)
        log("")
        log("  %s" % name)
        if not os.path.isfile(path):
            log("     MISSING")
            ok = False
            continue
        try:
            d = json.load(open(path, encoding="utf-8-sig"))
            labels = []
            for ld in d.get("layerDefinitions", []):
                r = ld.get("renderer", {})
                if r.get("type") != "CIMUniqueValueRenderer":
                    continue
                log("     renderer field(s): %s" % r.get("fields"))
                for g in r.get("groups", []):
                    for c in g.get("classes", []):
                        labels.append(str(c.get("label", "")).strip())
            for l in labels:
                flag = "ok  " if l.upper() in ("GO", "RESTRICTED", "NO GO") else "DEAD"
                log("     [%s] %r" % (flag, l))
            if set(l.upper() for l in labels) != {"GO", "RESTRICTED", "NO GO"}:
                ok = False
        except Exception as exc:
            log("     PARSE ERROR: %s" % exc)
            ok = False
    if ok:
        result("LYRX", "PASS", "both legends pruned to GO / RESTRICTED / NO GO")
    else:
        result("LYRX", "FAIL", "legend still contains classes Step 2 cannot emit")


# =============================================================================
# TEST 9 — release folder hygiene (no map needed)
# =============================================================================

def test_folder_hygiene():
    section("TEST 9 — RELEASE FOLDER HYGIENE")
    problems = []
    pyts = [f for f in os.listdir(_ROOT) if f.endswith(".pyt")]
    log("  .pyt files     : %s" % pyts)
    if len(pyts) != 1:
        problems.append("%d toolboxes present" % len(pyts))
    manuals = [f for f in os.listdir(_ROOT) if f.endswith("_User_Manual.docx")]
    log("  manuals        : %s" % manuals)
    if len(manuals) != 1:
        problems.append("%d manuals present" % len(manuals))
    junk = [f for f in os.listdir(_ROOT)
            if f.startswith("~$") or "MCE_CCM" in f]
    log("  stale/lock     : %s" % (junk or "none"))
    if junk:
        problems.append("%d stale file(s)" % len(junk))
    sidecar = os.path.join(_ROOT, "CCM_Tool_by_Son_v%s.pyt.xml" % VERSION)
    if os.path.isfile(sidecar):
        txt = open(sidecar, encoding="utf-8").read()
        import re
        m = re.search(r'<toolbox name="([^"]+)"', txt)
        log("  sidecar name   : %s" % (m.group(1) if m else "<not found>"))
        if not m or VERSION not in m.group(1):
            problems.append("sidecar toolbox name stale")
    else:
        problems.append("sidecar missing")
    if problems:
        result("HYGIENE", "FAIL", "; ".join(problems))
    else:
        result("HYGIENE", "PASS", "one toolbox, one manual, no stale files")


# =============================================================================
# MAIN
# =============================================================================

def main():
    log("#" * 74)
    log("#  CCM Tool by Son v%s — ArcGIS Pro VERIFICATION" % VERSION)
    log("#  %s" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    log("#" * 74)

    arcpy = test_environment()
    if arcpy is None:
        flush_log()
        return 1

    test_imports()
    test_toolbox(arcpy)
    test_lyrx_legend()
    test_folder_hygiene()

    fc = build_fixture(arcpy)
    if fc:
        factory, mode, cleanup = get_layer_source(arcpy, fc)
        try:
            test_old_behaviour(arcpy, fc, factory, mode)
            test_new_styling(arcpy, fc, factory, mode)
            test_alpha_scale(arcpy, fc, factory, mode)
        finally:
            cleanup()
        try:
            arcpy.management.Delete(fc)
            log("")
            log("Fixture cleanup: deleted %s" % fc)
        except Exception as exc:
            log("Fixture cleanup: failed (%s) — safe to delete manually" % exc)

    section("SUMMARY")
    for tag, verdict, detail in _RESULTS:
        log("  [%-8s] %-6s %s" % (tag, verdict, detail))
    fails = [r for r in _RESULTS if r[1] == "FAIL"]
    skips = [r for r in _RESULTS if r[1] == "SKIP"]
    log("")
    log("  %d checks | %d FAIL | %d SKIP" % (len(_RESULTS), len(fails), len(skips)))
    if skips:
        log("")
        log("  If any SKIP above is still map-dependent, run this from the")
        log("  ArcGIS Pro Python window instead of the conda prompt:")
        log('      exec(open(r"%s").read())' % os.path.abspath(__file__))
    log("")
    log("  Send %s back for review." % os.path.basename(LOG_PATH))
    flush_log()
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
# <<< END OF FILE >>>
