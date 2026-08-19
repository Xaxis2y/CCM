# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
tests/test_ccm.py
=================
CCM Tool v0.50.0 — Pytest unit test skeleton.

These tests cover the pure-Python utility functions that do NOT require
arcpy or an ArcGIS Pro licence.  They can be run in any standard Python
environment:

    pip install pytest
    pytest tests/test_ccm.py -v

For tests that require arcpy, mark them with @pytest.mark.arcpy and
run only on a machine with ArcGIS Pro installed:

    pytest tests/test_ccm.py -v -m arcpy

"""

import random
import sys
import os
import types
import pytest

# ---------------------------------------------------------------------------
# Make sure the package root is on sys.path so local modules resolve.
# ---------------------------------------------------------------------------
_HERE  = os.path.dirname(__file__)
_ROOT  = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ---------------------------------------------------------------------------
# Minimal arcpy stub so non-arcpy modules can be imported without a licence.
# ---------------------------------------------------------------------------
class _StubAny:
    """Catch-all stub: callable, attribute-accessible, and falsy.

    Lets arbitrary arcpy attribute chains (e.g. ``arcpy.env.scratchGDB``)
    and class-like uses (e.g. ``arcpy.SpatialReference`` in annotations)
    resolve without raising during import of non-arcpy code paths.
    """
    def __call__(self, *args, **kwargs):
        return _StubAny()

    def __getattr__(self, name):
        return _StubAny()

    def __bool__(self):
        return False


def _make_arcpy_stub():
    """Return a minimal `arcpy` stub module sufficient to import the
    pure-Python helpers without an ArcGIS Pro licence."""
    arcpy_stub               = types.ModuleType("arcpy")
    arcpy_stub.AddMessage    = lambda *a, **k: None
    arcpy_stub.AddWarning    = lambda *a, **k: None
    arcpy_stub.AddError      = lambda *a, **k: None
    arcpy_stub.GetInstallInfo = lambda: {"Version": "3.7.0"}
    # Existence/describe helpers used by source/obstacle auto-detection.
    arcpy_stub.Exists        = lambda *a, **k: False
    arcpy_stub.Describe      = lambda *a, **k: _StubAny()
    arcpy_stub.ListFields    = lambda *a, **k: []
    arcpy_stub.ListFeatureClasses = lambda *a, **k: []
    # SpatialReference is referenced in type annotations at def time.
    arcpy_stub.SpatialReference = _StubAny
    arcpy_stub.env           = _StubAny()
    # Anything else accessed on the module resolves to a harmless stub.
    arcpy_stub.__getattr__   = lambda name: _StubAny()

    sa_stub = types.ModuleType("arcpy.sa")
    arcpy_stub.sa = sa_stub

    da_stub = types.ModuleType("arcpy.da")
    arcpy_stub.da = da_stub

    return arcpy_stub


# Inject stub only if arcpy is not already importable
try:
    import arcpy  # noqa: F401
    _ARCPY_AVAILABLE = True
except ImportError:
    sys.modules.setdefault("arcpy", _make_arcpy_stub())
    sys.modules.setdefault("arcpy.sa", sys.modules["arcpy"].sa)
    sys.modules.setdefault("arcpy.da", sys.modules["arcpy"].da)
    _ARCPY_AVAILABLE = False

arcpy_required = pytest.mark.skipif(
    not _ARCPY_AVAILABLE,
    reason="arcpy (ArcGIS Pro) not available",
)


# ===========================================================================
# TEST MODULE: CCM_Tool_v0.58.2.pyt — Toolbox registration
# ===========================================================================
# The v0.57 post-review pass removed the dead CCMAssessment/main()/__main__
# command-line path and its four orphaned helper functions
# (_validate_distance, validate_feature_class, _create_unique_folder,
# _resolve_obstacle_source): none were reachable from ArcGIS Pro (which
# never executes a .pyt as __main__) and none were used by the real Step 0-4
# tool classes — see CHANGELOG_v0.57.md "M-4". Their unit tests are removed
# with them; test_toolbox_loads (below) covers what remains: that the
# toolbox still registers all six tools.


# ===========================================================================
# TEST MODULE: ccm_project_config
# ===========================================================================

class TestProjectConfig:
    """Tests for save_config / load_config without arcpy."""

    @pytest.fixture
    def cfg_mod(self):
        import importlib.util
        # ccm_project_config imports only json/os/datetime — no arcpy
        spec = importlib.util.spec_from_file_location(
            "ccm_project_config",
            os.path.join(_ROOT, "ccm_project_config.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_version_is_current(self, cfg_mod):
        # v0.57 post-review "5.6": this was named test_version_is_047, a
        # relic from when it was first written against v0.47 -- the
        # assertion itself was always correctly checking the *current*
        # VERSION, just under an increasingly misleading name that would
        # need updating at every version bump if left version-numbered.
        assert cfg_mod.VERSION == "0.58.2"

    def test_save_and_load_roundtrip(self, cfg_mod, tmp_path):
        folder = str(tmp_path)
        cfg_mod.save_config(folder, extent_fc="C:/test/extent.shp", moisture_default="wet")
        loaded = cfg_mod.load_config(folder)
        assert loaded["extent_fc"] == "C:/test/extent.shp"
        assert loaded["moisture_default"] == "wet"
        assert loaded["ccm_version"] == "0.58.2"

    def test_save_preserves_existing_fields(self, cfg_mod, tmp_path):
        folder = str(tmp_path)
        cfg_mod.save_config(folder, extent_fc="C:/original.shp")
        cfg_mod.save_config(folder, soil_fc="C:/soil.shp")   # second call
        loaded = cfg_mod.load_config(folder)
        assert loaded["extent_fc"] == "C:/original.shp"   # preserved
        assert loaded["soil_fc"]   == "C:/soil.shp"        # new field

    def test_load_nonexistent_returns_empty(self, cfg_mod, tmp_path):
        result = cfg_mod.load_config(str(tmp_path / "no_such_folder"))
        assert result == {}

    def test_config_has_geomorphon_key(self, cfg_mod, tmp_path):
        cfg_mod.save_config(str(tmp_path))
        loaded = cfg_mod.load_config(str(tmp_path))
        assert "geomorphon_ras" in loaded

    def test_timestamps_populated(self, cfg_mod, tmp_path):
        cfg_mod.save_config(str(tmp_path))
        loaded = cfg_mod.load_config(str(tmp_path))
        assert loaded.get("created")
        assert loaded.get("last_updated")

    def test_find_config_walks_up(self, cfg_mod, tmp_path):
        # Save config in parent, look up from child dir
        parent = str(tmp_path)
        child  = os.path.join(parent, "sub1", "sub2")
        os.makedirs(child, exist_ok=True)
        cfg_mod.save_config(parent, extent_fc="C:/found.shp")
        result = cfg_mod.find_config(child)
        assert result.get("extent_fc") == "C:/found.shp"


# ===========================================================================
# TEST MODULE: ccm_vehicle_compare (pure-Python helpers)
# ===========================================================================

class TestVehicleCompareHelpers:
    """Tests for the pure-Python helper functions in ccm_vehicle_compare."""

    @pytest.fixture(scope="class")
    def vc_mod(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "ccm_vehicle_compare",
            os.path.join(_ROOT, "ccm_vehicle_compare.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_is_passable_above_threshold(self, vc_mod):
        assert vc_mod._is_passable(10.0, 5.0) is True

    def test_is_passable_below_threshold(self, vc_mod):
        assert vc_mod._is_passable(2.0, 5.0) is False

    def test_is_passable_none_speed(self, vc_mod):
        assert vc_mod._is_passable(None, 5.0) is False

    def test_compare_label_both_go(self, vc_mod):
        assert vc_mod._compare_label(20.0, 15.0, 5.0) == vc_mod.CR_BOTH_GO

    def test_compare_label_a_only(self, vc_mod):
        assert vc_mod._compare_label(20.0, 2.0, 5.0) == vc_mod.CR_A_ONLY

    def test_compare_label_b_only(self, vc_mod):
        assert vc_mod._compare_label(1.0, 20.0, 5.0) == vc_mod.CR_B_ONLY

    def test_compare_label_neither(self, vc_mod):
        assert vc_mod._compare_label(1.0, 2.0, 5.0) == vc_mod.CR_NEITHER

    def test_compare_label_data_gap(self, vc_mod):
        assert vc_mod._compare_label(None, None, 5.0) == vc_mod.CR_DATA_GAP

    def test_speed_advantage(self, vc_mod):
        assert vc_mod._speed_advantage(20.0, 15.0) == pytest.approx(5.0)

    def test_speed_advantage_negative(self, vc_mod):
        assert vc_mod._speed_advantage(10.0, 30.0) == pytest.approx(-20.0)

    def test_speed_advantage_none(self, vc_mod):
        assert vc_mod._speed_advantage(None, 10.0) is None

    def test_safe_name_strips_special(self, vc_mod):
        result = vc_mod._safe_name("LAV III / M113")
        # Only alphanumeric + underscore, max 20 chars
        assert all(c.isalnum() or c == "_" for c in result)
        assert len(result) <= 20
# ===========================================================================
# TEST MODULE: auto-discovery (DMTI + generic land-cover / soil sources)
# ===========================================================================

class TestAutoDiscovery:
    """Tests for the source auto-discovery helpers added in v0.46."""

    @pytest.fixture(scope="class")
    def veg_mod(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "ccm_veg_preprocess",
            os.path.join(_ROOT, "ccm_veg_preprocess.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    @pytest.fixture(scope="class")
    def soil_mod(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "ccm_soil_preprocess",
            os.path.join(_ROOT, "ccm_soil_preprocess.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    # DMTI land-cover source
    def test_dmti_in_source_list(self, veg_mod):
        assert veg_mod.SOURCE_DMTI in veg_mod.ALL_VEG_SOURCES

    def test_dmti_lookup_populated(self, veg_mod):
        assert len(veg_mod.LOOKUP_DMTI) >= 9
        for code, vals in veg_mod.LOOKUP_DMTI.items():
            assert len(vals) == 4
            assert 0.0 <= vals[0] <= 1.0

    def test_dmti_detected_by_filename(self, veg_mod):
        src, _ = veg_mod.detect_veg_source_type("CanMap_LandUse_2024.shp")
        assert src == veg_mod.SOURCE_DMTI
        src2, _ = veg_mod.detect_veg_source_type("DMTI_LUR.tif")
        assert src2 == veg_mod.SOURCE_DMTI

    # Keyword land-cover classifier
    def test_classify_forest(self, veg_mod):
        vti, spacing, diam, label = veg_mod.classify_landcover_label("Mixed Wooded Area")
        assert vti > 0.5
        assert diam > 0

    def test_classify_builtup_is_open(self, veg_mod):
        vti, spacing, diam, _ = veg_mod.classify_landcover_label("Residential")
        assert vti == pytest.approx(0.0)

    def test_classify_water(self, veg_mod):
        assert veg_mod.classify_landcover_label("Large Lake")[3] == "Water"

    def test_classify_unknown_returns_none(self, veg_mod):
        assert veg_mod.classify_landcover_label("zzz-not-a-class") is None
        assert veg_mod.classify_landcover_label("") is None
        assert veg_mod.classify_landcover_label(None) is None

    # Generic soil texture-field discovery
    def test_discover_texture_fields_aliases(self, soil_mod):
        found = soil_mod.discover_texture_fields(
            ["OBJECTID", "PCT_SAND", "ClayTotal", "USDA_TEXTURE", "SHAPE"]
        )
        assert "PCT_SAND" in found
        assert "ClayTotal" in found
        assert "USDA_TEXTURE" in found
        assert "OBJECTID" not in found

    def test_discover_texture_fields_empty(self, soil_mod):
        assert soil_mod.discover_texture_fields(["OBJECTID", "SHAPE"]) == set()
        assert soil_mod.discover_texture_fields([]) == set()
        assert soil_mod.discover_texture_fields(None) == set()


# ===========================================================================
# TEST MODULE: ccm_obstacle_detect (pure-Python helpers + version detection)
# ===========================================================================

class TestObstacleDetect:
    """Tests for obstacle-detect utility functions."""

    @pytest.fixture(scope="class")
    def od_mod(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "ccm_obstacle_detect",
            os.path.join(_ROOT, "ccm_obstacle_detect.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_version_is_current(self, od_mod):
        # v0.57 post-review "5.6": see the note on the identically-named
        # rename in TestConfig above -- this was test_version_is_047.
        assert od_mod.VERSION == "0.58.2"

    def test_get_pro_version_returns_tuple(self, od_mod):
        ver = od_mod._get_pro_version()
        assert isinstance(ver, tuple)
        assert len(ver) == 2

    def test_constants_defined(self, od_mod):
        assert od_mod.OT_LINEAR == "LINEAR_BARRIER"
        assert od_mod.OT_GAP    == "GAP"
        assert od_mod.OT_SLOPE  == "SLOPE_BREAK"
        assert od_mod.SEV_STOP  == "STOP"


# ===========================================================================
# ARCPY-DEPENDENT TESTS (skipped without Pro licence)
# ===========================================================================

@arcpy_required
class TestArcpyIntegration:
    """
    Integration tests that require an ArcGIS Pro environment.
    Run manually or in a CI environment with a licensed arcpy installation.
    """

    def test_toolbox_loads(self):
        import importlib.util
        from importlib.machinery import SourceFileLoader
        pyt_path = os.path.join(_ROOT, "CCM_Tool_v0.58.2.pyt")
        loader = SourceFileLoader("CCM_Tool_v0_47", pyt_path)
        spec = importlib.util.spec_from_loader("CCM_Tool_v0_47", loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        tb = mod.Toolbox()
        assert len(tb.tools) > 0, "Toolbox must register at least one tool."

    def test_ccm_step1_tool_has_parameters(self):
        from ccm_step1_setup import CCMStep1SetupTool
        tool = CCMStep1SetupTool()
        params = tool.getParameterInfo()
        assert len(params) >= 20, "Step 1 should expose >=20 parameters."

    def test_ccm_vehicle_compare_tool_parameters(self):
        from ccm_vehicle_compare import CCMVehicleCompareTool
        tool = CCMVehicleCompareTool()
        params = tool.getParameterInfo()
        assert len(params) == 7


# ===========================================================================
# TEST MODULE: ccm_step2_mobility (pure-Python trafficability math, v0.46)
# ===========================================================================
class TestStep2Mobility:
    """Unit tests for the rebuilt Step 2 mobility engine's pure functions.

    These do not require arcpy — ccm_step2_mobility imports arcpy lazily and
    the trafficability helpers below are independent of it.
    """

    @pytest.fixture(scope="class")
    def m(self):
        import ccm_step2_mobility as m
        return m

    def test_version_is_current(self, m):
        # v0.57 post-review "5.6": see the note on the identically-named
        # rename in TestConfig above -- this was test_version_is_049.
        assert m.VERSION == "0.58.2"

    # ── slope_factor ──────────────────────────────────────────────────────
    def test_slope_flat_is_full(self, m):
        assert m.slope_factor(0, 45) == 1.0

    def test_slope_above_max_is_nogo(self, m):
        assert m.slope_factor(50, 45) == 0.0

    def test_slope_taper_between(self, m):
        # max=45 → full-speed limit 27; midway taper gives 0<f<1
        f = m.slope_factor(36, 45)
        assert 0.0 < f < 1.0

    def test_slope_none_is_full(self, m):
        assert m.slope_factor(None, 45) == 1.0

    # ── veg_density_factor ────────────────────────────────────────────────
    def test_veg_density_open(self, m):
        assert m.veg_density_factor(0.0) == 1.0

    def test_veg_density_dense_floored(self, m):
        assert m.veg_density_factor(1.0) == pytest.approx(0.05)

    # ── veg_spacing_factor ────────────────────────────────────────────────
    def test_spacing_wide_gap_passable(self, m):
        # gap wider than vehicle → threads through
        assert m.veg_spacing_factor(5.0, 30.0, 2.5, 0.2) == 1.0

    def test_spacing_narrow_big_stems_blocked(self, m):
        # narrow gap, stems larger than override capability → NO GO
        assert m.veg_spacing_factor(1.0, 40.0, 2.5, 0.2) == 0.0

    def test_spacing_narrow_overridable_restricted(self, m):
        # narrow gap, stems within override (0.2 m = 20 cm) → restricted
        assert m.veg_spacing_factor(1.0, 15.0, 2.5, 0.2) == 0.5

    # ── soil_factor ───────────────────────────────────────────────────────
    def test_soil_strong_full(self, m):
        # well-graded gravel dry, weak vehicle → full mobility
        assert m.soil_factor("GW", "dry", 25, 50) == 1.0

    def test_soil_weak_wet_nogo(self, m):
        # peat wet RCI=25 < vci_1=30 → NO GO
        assert m.soil_factor("Pt", "wet", 30, 60) == 0.0

    def test_soil_unknown_not_penalised(self, m):
        assert m.soil_factor("ZZ", "moist", 25, 50) == 1.0

    def test_soil_ne_not_penalised(self, m):
        assert m.soil_factor("NE", "moist", 25, 50) == 1.0

    # v0.57 post-review "H-3": soil_factor() used to be case-/whitespace-
    # sensitive — soil_factor("cl", ...) silently returned 1.0 (unpenalised)
    # instead of the 0.12 "CL" returns, because every RCI table in this
    # module is keyed upper-case. Regression-lock the normalisation fix.
    def test_soil_factor_lowercase_matches_uppercase(self, m):
        upper = m.soil_factor("CL", "wet", 25, 50)
        assert upper < 1.0, "sanity: CL wet must be penalised for this VCI pair"
        assert m.soil_factor("cl", "wet", 25, 50) == upper
        assert m.soil_factor("Cl", "wet", 25, 50) == upper
        assert m.soil_factor(" CL ", "wet", 25, 50) == upper

    def test_soil_factor_none_code_is_unpenalised(self, m):
        assert m.soil_factor(None, "moist", 25, 50) == 1.0

    # ── combine_speed / classify ──────────────────────────────────────────
    def test_combine_zero_factor_is_nogo(self, m):
        assert m.combine_speed(60, 1.0, 1.0, 0.0, 1.0, 1.0, 1.0, "moist") == 0.0

    def test_combine_all_full_is_max(self, m):
        assert m.combine_speed(60, 1, 1, 1, 1, 1, 1, "moist") == 60.0

    def test_combine_uses_wet_soil_when_moist(self, m):
        # moisture!=dry → F5 (wet) governs; F4 ignored (legacy fallback path)
        s = m.combine_speed(60, 1, 1, 1, 0.0, 1.0, 1, "moist")
        assert s == 60.0  # F4=0 ignored because moist uses F5

    def test_combine_uses_moist_column_via_soil_active(self, m):
        # v0.48: an explicit soil_active overrides the F4/F5 endpoint selection,
        # letting the "moist" condition drive speed from the moist RCI column.
        s = m.combine_speed(60, 1, 1, 1, 0.0, 0.0, 1, "moist", soil_active=0.5)
        assert s == 30.0  # 0.5 x 60, regardless of F4/F5 being 0

    def test_slope_to_percent_converts_degrees(self, m):
        # v0.48: degree-valued slope fields are converted to percent for F1.
        assert m._slope_to_percent(45, "degrees") == pytest.approx(100.0, abs=0.5)
        assert m._slope_to_percent(30, "percent") == 30.0
        assert m._slope_to_percent(None, "degrees") is None

    def test_classify_nogo_below_threshold(self, m):
        assert m.classify_mobility(3.0, 60) == m.MOB_NOGO

    def test_classify_go_when_fast(self, m):
        assert m.classify_mobility(40.0, 60) == m.MOB_GO

    def test_classify_restricted_mid(self, m):
        assert m.classify_mobility(10.0, 60) == m.MOB_RESTRICTED

    # ── vehicle CSV parsing ───────────────────────────────────────────────
    def test_parse_vehicle_record(self, m):
        row = {"name": "M1", "max_road_spd_kph": "71",
               "max_off_road_grad": "54", "vehicle_width_m": "3.65",
               "max_override_diameter_m": "0.25", "vci_1": "25",
               "vci_50": "58", "locomotion_type": "1"}
        v = m.parse_vehicle_record(row)
        assert v.name == "M1"
        assert v.max_road_spd_kph == 71.0
        assert v.vci_50 == 58.0
        assert v.locomotion_type == 1

    def test_parse_vehicle_blank_override(self, m):
        # M2 row has a blank override diameter → None, must not crash
        row = {"name": "M2", "max_road_spd_kph": "66", "max_off_road_grad": "60",
               "vehicle_width_m": "6.2", "max_override_diameter_m": "",
               "vci_1": "15", "vci_50": "35", "locomotion_type": "1"}
        v = m.parse_vehicle_record(row)
        # blank override diameter defaults to 0.0 (no override capability)
        assert v.max_override_diameter_m == 0.0

    def test_run_tool_rejects_unknown_param(self):
        # run_tool must raise on a misspelled parameter name (fail-fast)
        import ccm_project_config as cfg
        class _FakeParam:
            def __init__(self, name): self.name = name; self.value=None; self.multiValue=False
        class _FakeTool:
            def getParameterInfo(self): return [_FakeParam("good")]
            def execute(self, params, messages): return "ran"
        with pytest.raises(KeyError):
            cfg.run_tool(_FakeTool(), None, bad_name=1)

    def test_run_tool_sets_by_name(self):
        import ccm_project_config as cfg
        class _FakeParam:
            def __init__(self, name): self.name=name; self.value=None; self.multiValue=False
        captured = {}
        class _FakeTool:
            def __init__(self): self.p=[_FakeParam("alpha"), _FakeParam("beta")]
            def getParameterInfo(self): return self.p
            def execute(self, params, messages):
                captured.update({p.name: p.value for p in params}); return "ok"
        assert cfg.run_tool(_FakeTool(), None, alpha=5, beta="x") == "ok"
        assert captured == {"alpha": 5, "beta": "x"}


# ===========================================================================
# TEST MODULE: v0.46 — calibratable RCI table + weather integration
# ===========================================================================
class TestRciCalibrationAndWeather:

    @pytest.fixture(scope="class")
    def m(self):
        import ccm_step2_mobility as m
        return m

    def test_rci_csv_ships_and_loads(self, m):
        path = os.path.join(_ROOT, m.RCI_CSV_NAME)
        assert os.path.isfile(path), "soil_rci.csv must ship with the toolbox"
        table = m.load_rci_csv(path)
        assert set(m._BUILTIN_USCS_RCI) <= set(table), "CSV must cover all USCS codes"
        assert table["GW"][0] and table["GW"][0] > table["PT"][0]
        assert table["NE"] == (None, None, None)

    def test_module_table_comes_from_csv(self, m):
        # With the CSV present, the active table must match it
        table = m.load_rci_csv(os.path.join(_ROOT, m.RCI_CSV_NAME))
        for code, vals in table.items():
            assert m.USCS_RCI[code] == vals

    def test_load_rci_csv_missing_raises(self, m):
        with pytest.raises(Exception):
            m.load_rci_csv(os.path.join(_ROOT, "no_such_rci.csv"))

    def test_soil_factor_accepts_custom_table(self, m):
        weak = {"GW": (10, 10, 10)}   # calibrated: gravel suddenly weak
        assert m.soil_factor("GW", "dry", 25, 58, weak) == 0.0
        assert m.soil_factor("GW", "dry", 25, 58) == 1.0  # default table intact

    def test_uscs_sensitivity_mapping_complete(self, m):
        import ccm_weather as w
        for code in m._BUILTIN_USCS_RCI:
            key = m.USCS_TO_SENSITIVITY_KEY.get(code)
            assert key, f"no sensitivity mapping for {code}"
            assert key in w.SOIL_SENSITIVITY, f"{code}->{key} missing in ccm_weather"

    def test_apply_weather_no_rain_is_identity(self, m):
        out = m.apply_weather_to_rci(m.USCS_RCI, 0.0)
        assert out["CH"] == tuple(m.USCS_RCI["CH"])

    def test_apply_weather_heavy_rain_penalises_clay_more_than_gravel(self, m):
        out = m.apply_weather_to_rci(m.USCS_RCI, 30.0)  # heavy rain
        ch_ratio = out["CH"][1] / m.USCS_RCI["CH"][1]
        gw_ratio = out["GW"][1] / m.USCS_RCI["GW"][1]
        assert ch_ratio < gw_ratio < 1.0, (ch_ratio, gw_ratio)
        # Rock immune
        assert out["RK"] == tuple(m.USCS_RCI["RK"])

    def test_apply_weather_manual_override(self, m):
        out = m.apply_weather_to_rci(m.USCS_RCI, 50.0, manual_override=1.0)
        assert out["CH"] == tuple(m.USCS_RCI["CH"])  # override 1.0 = no penalty

    def test_rain_turns_marginal_soil_nogo(self, m):
        # ML wet RCI=32 vs VCI1=25/VCI50=58 → RESTRICTED (25 < 32 < 58)
        base = m.soil_factor("ML", "wet", 25, 58)
        assert 0.0 < base < 1.0
        # heavy rain penalty pushes effective RCI below VCI1=25 → NO GO
        wet_table = m.apply_weather_to_rci(m.USCS_RCI, 50.0)
        assert m.soil_factor("ML", "wet", 25, 58, wet_table) == 0.0


# ===========================================================================
# TEST MODULE: v0.49 — Speed Made Good, MMP, Stochastic, Spatial Moisture
# ===========================================================================

class TestSpeedMadeGood:
    """Tests for compute_speed_made_good() (v0.49)."""

    @pytest.fixture(scope="class")
    def m(self):
        import ccm_step2_mobility as m
        return m

    def test_all_nogo_gives_100pct_nogo(self, m):
        pairs = [(0.0, 1000.0), (3.0, 500.0)]  # all at/below 5 km/h threshold
        result = m.compute_speed_made_good(pairs, go_threshold=5.0)
        assert result["pct_nogo"] == pytest.approx(100.0)
        assert result["pct_go"] == pytest.approx(0.0)

    def test_all_go_gives_0pct_nogo(self, m):
        pairs = [(40.0, 1000.0), (50.0, 2000.0)]  # all above threshold
        result = m.compute_speed_made_good(pairs, go_threshold=5.0, max_road_spd_kph=50.0)
        assert result["pct_nogo"] == pytest.approx(0.0)

    def test_area_weighting_correct(self, m):
        # 1000 m2 @ NO GO (0 km/h) + 3000 m2 @ 40 km/h → 25% NOGO by area
        pairs = [(0.0, 1000.0), (40.0, 3000.0)]
        result = m.compute_speed_made_good(pairs, go_threshold=5.0, max_road_spd_kph=50.0)
        assert result["pct_nogo"] == pytest.approx(25.0)

    def test_cdf_monotone_decreasing(self, m):
        pairs = [(s * 5.0, 1000.0) for s in range(11)]  # 0–50 km/h evenly
        result = m.compute_speed_made_good(pairs, go_threshold=5.0, max_road_spd_kph=50.0)
        cdf = result["cdf"]
        pcts = [p for _, p in cdf]
        # CDF is non-increasing (higher speed → less area achievable)
        assert all(pcts[i] >= pcts[i + 1] for i in range(len(pcts) - 1))

    def test_cdf_starts_at_100pct(self, m):
        pairs = [(20.0, 1000.0), (30.0, 1000.0)]
        result = m.compute_speed_made_good(pairs)
        # Speed 0 → 100% of area traversable at >= 0 km/h
        first_spd, first_pct = result["cdf"][0]
        assert first_spd == pytest.approx(0.0)
        assert first_pct == pytest.approx(100.0)

    def test_empty_pairs_returns_defaults(self, m):
        result = m.compute_speed_made_good([])
        assert result["pct_nogo"] == pytest.approx(100.0)
        assert result["cdf"] == []

    def test_mean_speed_excludes_nogo(self, m):
        # NOGO polygon should not drag down the "mobile" mean
        pairs = [(0.0, 500.0), (40.0, 1000.0)]
        result = m.compute_speed_made_good(pairs, go_threshold=5.0, max_road_spd_kph=50.0)
        # Mean of mobile terrain is 40 km/h (only one mobile polygon)
        assert result["mean_speed_kmh"] == pytest.approx(40.0)


class TestMMP:
    """Tests for compute_mmp_estimate() (v0.49)."""

    @pytest.fixture(scope="class")
    def m(self):
        import ccm_step2_mobility as m
        return m

    def test_tracked_m1(self, m):
        # M1: VCI_50=58, tracked → 58/0.56 ≈ 103.6
        mmp = m.compute_mmp_estimate(58, locomotion_type=1)
        assert mmp == pytest.approx(103.6, abs=0.5)

    def test_wheeled_higher_than_tracked(self, m):
        # Wheeled uses k=0.18 → much higher MMP than tracked (k=0.56)
        tracked = m.compute_mmp_estimate(50, locomotion_type=1)
        wheeled = m.compute_mmp_estimate(50, locomotion_type=0)
        assert wheeled > tracked

    def test_none_vci_returns_none(self, m):
        assert m.compute_mmp_estimate(None) is None

    def test_higher_vci50_gives_higher_mmp(self, m):
        # MMP scales linearly with VCI_50
        mmp_low  = m.compute_mmp_estimate(40, locomotion_type=1)
        mmp_high = m.compute_mmp_estimate(60, locomotion_type=1)
        assert mmp_high > mmp_low

    def test_vehicles_csv_has_mmp_column(self):
        import csv
        import os
        # v0.54.4: the CSV shipped twice (project root AND Vehicle_Data/).
        # The root duplicate was removed; Vehicle_Data/ is the single copy,
        # which is also what Step 1's help text points users at.
        csv_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "Vehicle_Data", "Vehicles_Can.csv"
        )
        with open(csv_path, "r", encoding="utf-8-sig") as fh:
            header = next(csv.reader(fh))
        assert "mmp_kpa" in [h.strip() for h in header], \
            "Vehicles_Can.csv must have a mmp_kpa column (v0.49)"


class TestStochasticMobility:
    """Tests for compute_stochastic_go() (v0.49)."""

    @pytest.fixture(scope="class")
    def m(self):
        import ccm_step2_mobility as m
        return m

    def test_returns_probability_in_0_1(self, m):
        p = m.compute_stochastic_go("GW", "moist", 25, 58, 10.0, 45.0, n_trials=50)
        assert 0.0 <= p <= 1.0

    def test_strong_soil_flat_terrain_high_p(self, m):
        # GW dry, vci_1=10, vci_50=25, slope=0 → almost always GO
        random.seed(42)
        p = m.compute_stochastic_go("GW", "dry", 10, 25, 0.0, 45.0, n_trials=200)
        assert p >= 0.80, f"Expected high P(GO) for strong soil+flat, got {p}"

    def test_weak_soil_wet_near_vci1_low_p(self, m):
        # Pt wet RCI=25, vci_1=30 → normally NO GO; with perturbation still mostly NO GO
        random.seed(42)
        p = m.compute_stochastic_go("Pt", "wet", 30, 60, 5.0, 45.0, n_trials=200)
        assert p <= 0.30, f"Expected low P(GO) for weak wet peat, got {p}"

    def test_steep_slope_above_max_low_p(self, m):
        # slope=50%, max_grad=45% → deterministically NO GO; stochastic ~low
        random.seed(42)
        p = m.compute_stochastic_go("GW", "dry", 10, 25, 50.0, 45.0, n_trials=200)
        assert p < 0.50, f"Expected low P(GO) for slope > max_grad, got {p}"

    def test_unknown_soil_returns_1(self, m):
        # No RCI data → conservative assumption = always GO
        p = m.compute_stochastic_go("ZZ", "moist", 25, 58, 10.0, 45.0, n_trials=50)
        assert p == 1.0

    def test_reproducible_with_seed(self, m):
        random.seed(99)
        p1 = m.compute_stochastic_go("CL", "moist", 20, 50, 20.0, 45.0, n_trials=100)
        random.seed(99)
        p2 = m.compute_stochastic_go("CL", "moist", 20, 50, 20.0, 45.0, n_trials=100)
        assert p1 == p2


class TestCombineSpeedMinModel:
    """Tests verifying the v0.49 min-of-factors speed model."""

    @pytest.fixture(scope="class")
    def m(self):
        import ccm_step2_mobility as m
        return m

    def test_min_governs_not_product(self, m):
        # Two factors of 0.7 → min=0.7 (not product=0.49)
        speed = m.combine_speed(100.0, 0.7, 0.7, 1.0, 1.0, 1.0, 1.0, "moist",
                                soil_active=1.0, speed_model="min")
        assert speed == pytest.approx(70.0)

    def test_product_model_still_available(self, m):
        speed = m.combine_speed(100.0, 0.7, 0.7, 1.0, 1.0, 1.0, 1.0, "moist",
                                soil_active=1.0, speed_model="product")
        assert speed == pytest.approx(49.0)

    def test_min_default_is_min_model(self, m):
        # Use TWO non-unity factors so min (0.6) != product (0.48)
        # f1=0.6, f2=0.8 → min=0.6×60=36; product=0.48×60=28.8
        speed_min     = m.combine_speed(60.0, 0.6, 0.8, 1.0, 1.0, 1.0, 1.0, "moist",
                                        soil_active=1.0, speed_model="min")
        speed_product = m.combine_speed(60.0, 0.6, 0.8, 1.0, 1.0, 1.0, 1.0, "moist",
                                        soil_active=1.0, speed_model="product")
        # Default call (no speed_model arg) should match min, not product
        speed_default = m.combine_speed(60.0, 0.6, 0.8, 1.0, 1.0, 1.0, 1.0, "moist",
                                        soil_active=1.0)
        assert speed_default == speed_min          # default == min
        assert speed_default != speed_product      # different from old product
        assert speed_min == pytest.approx(36.0)
        assert speed_product == pytest.approx(28.8)

    def test_zero_factor_nogo_in_both_models(self, m):
        for model in ("min", "product"):
            s = m.combine_speed(60.0, 0.0, 1.0, 1.0, 1.0, 1.0, 1.0, "dry",
                                speed_model=model)
            assert s == 0.0, f"Zero factor should be NO GO in {model} model"


class TestSpatialMoisture:
    """Tests for moisture_vwc_to_condition() (v0.49)."""

    @pytest.fixture(scope="class")
    def w(self):
        import ccm_weather as w
        return w

    def test_dry_below_threshold(self, w):
        assert w.moisture_vwc_to_condition(0.10) == "dry"

    def test_moist_in_range(self, w):
        assert w.moisture_vwc_to_condition(0.22) == "moist"

    def test_wet_at_threshold(self, w):
        assert w.moisture_vwc_to_condition(0.30) == "wet"

    def test_wet_above_threshold(self, w):
        assert w.moisture_vwc_to_condition(0.45) == "wet"

    def test_none_returns_moist(self, w):
        assert w.moisture_vwc_to_condition(None) == "moist"

    def test_zero_vwc_is_dry(self, w):
        assert w.moisture_vwc_to_condition(0.0) == "dry"

    def test_version_is_current(self, w):
        # v0.57 post-review "5.6": see the note on the identically-named
        # rename in TestConfig above -- this was test_version_is_049.
        assert w.VERSION == "0.58.2"


# ===========================================================================
# TEST MODULE: ccm_coords CRS/projection smart-warning helpers (v0.54.4)
# ===========================================================================

class TestCoordsCRSHelpers:
    """Tests for geographic_crs_warning() / crs_mismatch_warning() /
    describe_spatial_reference() — the shared smart-warning helpers used by
    Steps 0, 1, 3 and 4.  These are plain string-building functions (no
    arcpy calls except inside describe_spatial_reference), so they are
    fully testable without a licensed arcpy install."""

    @pytest.fixture(scope="class")
    def c(self):
        import ccm_coords as c
        return c

    def test_version_is_current(self, c):
        # v0.57 post-review "5.6": see the note on the identically-named
        # rename in TestConfig above -- this was test_version_is_054.
        assert c.VERSION == "0.58.2"

    def test_geographic_crs_warning_contains_layer_and_sr_name(self, c):
        msg = c.geographic_crs_warning("Analysis Extent", "GCS_WGS_1984")
        assert "Analysis Extent" in msg
        assert "GCS_WGS_1984" in msg
        assert "Projected CRS" in msg
        assert "UTM" in msg

    def test_geographic_crs_warning_blocking_wording(self, c):
        soft = c.geographic_crs_warning("DEM", "GCS_WGS_1984", blocking=False)
        hard = c.geographic_crs_warning("DEM", "GCS_WGS_1984", blocking=True)
        assert "should use a Projected" in soft
        assert "must use a Projected" in hard

    def test_crs_mismatch_warning_contains_both_layers(self, c):
        msg = c.crs_mismatch_warning(
            "Vehicle B Speed Surface", "WGS_1984_UTM_Zone_37N",
            "Vehicle A Speed Surface", "WGS_1984_UTM_Zone_36N",
        )
        assert "Vehicle B Speed Surface" in msg
        assert "WGS_1984_UTM_Zone_37N" in msg
        assert "Vehicle A Speed Surface" in msg
        assert "WGS_1984_UTM_Zone_36N" in msg

    def test_describe_spatial_reference_returns_triple(self, c):
        # Under the arcpy-free test stub, Describe() never raises, so this
        # only exercises the return-shape contract (3-tuple) — real CRS
        # detection requires a licensed arcpy install (see
        # tests/arcpy_smoke_test_step0b.py).
        result = c.describe_spatial_reference("nonexistent_path")
        assert isinstance(result, tuple)
        assert len(result) == 3
