"""
tests/test_ccm.py
=================
CCM Tool v0.46 — Pytest unit test skeleton.

These tests cover the pure-Python utility functions that do NOT require
arcpy or an ArcGIS Pro licence.  They can be run in any standard Python
environment:

    pip install pytest
    pytest tests/test_ccm.py -v

For tests that require arcpy, mark them with @pytest.mark.arcpy and
run only on a machine with ArcGIS Pro installed:

    pytest tests/test_ccm.py -v -m arcpy

"""

import math
import sys
import os
import datetime
import json
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
# TEST MODULE: MCE_CCM_v0.46.pyt helpers
# ===========================================================================

class TestMCEHelpers:
    """Tests for utility functions in MCE_CCM_v0.46.pyt."""

    # These are plain Python functions — we import the module directly.
    # The .pyt extension confuses normal import; use importlib.
    @pytest.fixture(scope="class")
    def pyt_mod(self):
        import importlib.util
        from importlib.machinery import SourceFileLoader
        # The .pyt extension is not a recognized source suffix, so
        # spec_from_file_location() returns a spec with loader=None.
        # Supply an explicit SourceFileLoader so the toolbox loads as a
        # normal Python source module.
        pyt_path = os.path.join(_ROOT, "MCE_CCM_v0.46.pyt")
        loader = SourceFileLoader("MCE_CCM_v0_46", pyt_path)
        spec = importlib.util.spec_from_loader("MCE_CCM_v0_46", loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        return mod

    def test_validate_distance_valid(self, pyt_mod):
        assert pyt_mod._validate_distance("500") == 500.0
        assert pyt_mod._validate_distance("1000.5") == pytest.approx(1000.5)

    def test_validate_distance_default_on_empty(self, pyt_mod):
        result = pyt_mod._validate_distance("", default_m=750.0)
        assert result == pytest.approx(750.0)

    def test_validate_distance_default_on_none(self, pyt_mod):
        result = pyt_mod._validate_distance(None, default_m=250.0)
        assert result == pytest.approx(250.0)

    def test_validate_distance_negative_raises(self, pyt_mod):
        with pytest.raises((ValueError, Exception)):
            pyt_mod._validate_distance("-100")

    def test_validate_feature_class_empty_path(self, pyt_mod):
        ok, msg = pyt_mod.validate_feature_class("")
        assert not ok
        assert "empty" in msg.lower()

    def test_resolve_obstacle_none(self, pyt_mod):
        path, typ = pyt_mod._resolve_obstacle_source("")
        assert path is None
        assert typ is None

    def test_resolve_obstacle_csv(self, pyt_mod, tmp_path):
        csv_file = tmp_path / "obstacles.csv"
        csv_file.write_text("lat,lon,type\n45.5,-75.5,wall\n")
        path, typ = pyt_mod._resolve_obstacle_source(str(csv_file))
        assert typ == "csv"

    def test_resolve_obstacle_unknown_raises(self, pyt_mod, tmp_path):
        unknown = tmp_path / "something.xyz"
        unknown.write_text("not a known format")
        with pytest.raises(ValueError):
            pyt_mod._resolve_obstacle_source(str(unknown))


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

    def test_version_is_046(self, cfg_mod):
        assert cfg_mod.VERSION == "0.46"

    def test_save_and_load_roundtrip(self, cfg_mod, tmp_path):
        folder = str(tmp_path)
        cfg_mod.save_config(folder, extent_fc="C:/test/extent.shp", moisture_default="wet")
        loaded = cfg_mod.load_config(folder)
        assert loaded["extent_fc"] == "C:/test/extent.shp"
        assert loaded["moisture_default"] == "wet"
        assert loaded["ccm_version"] == "0.46"

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

    def test_version_is_046(self, od_mod):
        assert od_mod.VERSION == "0.46"

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
        pyt_path = os.path.join(_ROOT, "MCE_CCM_v0.46.pyt")
        loader = SourceFileLoader("MCE_CCM_v0_46", pyt_path)
        spec = importlib.util.spec_from_loader("MCE_CCM_v0_46", loader)
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

    def test_version_is_046(self, m):
        assert m.VERSION == "0.46"

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

    # ── combine_speed / classify ──────────────────────────────────────────
    def test_combine_zero_factor_is_nogo(self, m):
        assert m.combine_speed(60, 1.0, 1.0, 0.0, 1.0, 1.0, 1.0, "moist") == 0.0

    def test_combine_all_full_is_max(self, m):
        assert m.combine_speed(60, 1, 1, 1, 1, 1, 1, "moist") == 60.0

    def test_combine_uses_wet_soil_when_moist(self, m):
        # moisture!=dry → F5 (wet) governs; F4 ignored
        s = m.combine_speed(60, 1, 1, 1, 0.0, 1.0, 1, "moist")
        assert s == 60.0  # F4=0 ignored because moist uses F5

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
        assert table["GW"][0] and table["GW"][0] > table["Pt"][0]
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
        # CH wet RCI=45 vs VCI1=25/VCI50=58 → restricted when dry-table…
        base = m.soil_factor("CH", "wet", 25, 58)
        assert 0.0 < base < 1.0
        # …but heavy rain pushes RCI below VCI1 → NO GO
        wet_table = m.apply_weather_to_rci(m.USCS_RCI, 50.0)
        assert m.soil_factor("CH", "wet", 25, 58, wet_table) == 0.0
