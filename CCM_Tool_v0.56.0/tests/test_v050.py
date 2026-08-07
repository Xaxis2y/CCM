# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
tests/test_v050.py — v0.50.0 regression tests.

Covers:
  * BUG-1 fix — Step 1 save_config keyword invocation
  * BUG-2 fix — hydro_fcs parsed into a list
  * ccm_mgcp_catalog — code extraction, lookup, labels, themes, manifest
  * Step 1 manifest auto-fill (_apply_manifest)

Run:  pytest tests/test_v050.py -v
"""

import json
import os
import sys

import pytest

_HERE = os.path.dirname(__file__)
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# Installing the arcpy stub from the main test module makes ccm_* modules
# importable without an ArcGIS licence.
import test_ccm  # noqa: F401  (side effect: sys.modules["arcpy"] stub)

import ccm_mgcp_catalog as cat
import ccm_project_config as cfg_mod
import ccm_step1_setup as step1


# ─────────────────────────────────────────────────────────────────────────────
# ccm_mgcp_catalog
# ─────────────────────────────────────────────────────────────────────────────

class TestCatalogCodeExtraction:
    def test_bare_code(self):
        assert cat.extract_code("AP030") == "AP030"

    def test_shapefile_path(self):
        assert cat.extract_code(r"C:\MGCP\cell1\FC\BH140.shp") == "BH140"

    def test_prefixed_and_suffixed(self):
        assert cat.extract_code("main_AP030") == "AP030"
        assert cat.extract_code("AP030_1") == "AP030"
        assert cat.extract_code("ap030") == "AP030"

    def test_no_code(self):
        assert cat.extract_code("soil_ccm") is None
        assert cat.extract_code("") is None
        assert cat.extract_code(None) is None


class TestCatalogLookup:
    def test_soil_is_da010(self):
        info = cat.lookup("DA010")
        assert info["theme"] == cat.THEME_SOIL
        assert info["ccm_role"] == cat.ROLE_SOIL

    def test_river_is_hydro(self):
        info = cat.lookup("BH140")
        assert info["theme"] == cat.THEME_HYDRO
        assert info["ccm_role"] == cat.ROLE_HYDRO

    def test_forest_is_veg(self):
        assert cat.lookup("EC015")["ccm_role"] == cat.ROLE_VEG

    def test_road_is_transport(self):
        info = cat.lookup("AP030")
        assert info["name"] == "Road"
        assert info["theme"] == cat.THEME_TRANSPORT

    def test_contours(self):
        assert cat.lookup("CA010")["ccm_role"] == cat.ROLE_CONTOURS

    def test_unknown_code_falls_back_to_letter_theme(self):
        info = cat.lookup("BH999")           # not in catalog
        assert info["theme"] == cat.THEME_HYDRO
        assert info["ccm_role"] is None
        info = cat.lookup("EZ999")
        assert info["theme"] == cat.THEME_VEG

    def test_non_mgcp_name(self):
        info = cat.lookup("my_random_layer")
        assert info["code"] is None
        assert info["theme"] == cat.THEME_OTHER


class TestCatalogLabels:
    def test_label_format(self):
        assert cat.label("AP030") == "AP030 — Road (Transportation)"

    def test_name_from_label_roundtrip(self):
        for fc in ["AP030", "BH140", "DA010", "EC015", "ZZ_unknown"]:
            assert cat.name_from_label(cat.label(fc)) == fc

    def test_name_from_label_passthrough(self):
        assert cat.name_from_label("AP030") == "AP030"
        assert cat.name_from_label("'AP030'") == "AP030"

    def test_ccm_relevance(self):
        assert cat.is_ccm_relevant("DA010")
        assert cat.is_ccm_relevant("BH140")
        assert cat.is_ccm_relevant("AP030")
        assert not cat.is_ccm_relevant("GB055")   # runway
        assert not cat.is_ccm_relevant("FA000")   # admin boundary


class TestManifestHelpers:
    def _write_manifest(self, tmp_path):
        m = {
            "manifest_version": 1,
            "output_gdb": str(tmp_path / "MGCP.gdb"),
            "features": [
                {"fc": "DA010", "path": str(tmp_path / "MGCP.gdb" / "DA010"),
                 "ccm_role": "soil", "geometry": "Polygon"},
                {"fc": "BH140", "path": str(tmp_path / "MGCP.gdb" / "BH140"),
                 "ccm_role": "hydro", "geometry": "Polygon"},
                {"fc": "BH080", "path": str(tmp_path / "MGCP.gdb" / "BH080"),
                 "ccm_role": "hydro", "geometry": "Polygon"},
                {"fc": "CA010", "path": str(tmp_path / "MGCP.gdb" / "CA010"),
                 "ccm_role": "contours", "geometry": "Polyline"},
                {"fc": "AP030", "path": str(tmp_path / "MGCP.gdb" / "AP030"),
                 "ccm_role": "road", "geometry": "Polyline"},
            ],
        }
        p = tmp_path / cat.MANIFEST_FILENAME
        p.write_text(json.dumps(m), encoding="utf-8")
        return p, m

    def test_load_by_path_folder_and_gdb(self, tmp_path):
        p, _ = self._write_manifest(tmp_path)
        assert cat.load_manifest(str(p))["manifest_version"] == 1
        assert cat.load_manifest(str(tmp_path))["manifest_version"] == 1
        assert cat.load_manifest(
            str(tmp_path / "MGCP.gdb"))["manifest_version"] == 1

    def test_load_missing_returns_empty(self, tmp_path):
        assert cat.load_manifest(str(tmp_path / "nope.json")) == {}

    def test_features_by_role(self, tmp_path):
        _, m = self._write_manifest(tmp_path)
        assert len(cat.features_by_role(m, "hydro")) == 2
        assert cat.features_by_role(m, "soil")[0]["fc"] == "DA010"
        assert cat.features_by_role({}, "soil") == []


# ─────────────────────────────────────────────────────────────────────────────
# BUG-1 / BUG-2 — Step 1 config handling
# ─────────────────────────────────────────────────────────────────────────────

class TestBugFixes:
    def test_save_config_keyword_style_roundtrip(self, tmp_path):
        """BUG-1: the call style used by Step 1 must not raise."""
        config = {"extent_fc": "x", "hydro_fcs": ["a", "b"]}
        cfg_mod.save_config(str(tmp_path), **config)      # must not TypeError
        loaded = cfg_mod.load_config(str(tmp_path))
        assert loaded["extent_fc"] == "x"
        assert loaded["hydro_fcs"] == ["a", "b"]

    def test_parse_multi_semicolons_and_quotes(self):
        """BUG-2: hydro multi-value strings become clean path lists."""
        v = r"'C:\data a\riv.shp';C:\data\lake.shp"
        assert step1._parse_multi(v) == [r"C:\data a\riv.shp",
                                         r"C:\data\lake.shp"]
        assert step1._parse_multi(None) == []
        assert step1._parse_multi("single") == ["single"]


# ─────────────────────────────────────────────────────────────────────────────
# Step 1 manifest auto-fill
# ─────────────────────────────────────────────────────────────────────────────

class _FakeParam:
    def __init__(self, value=None):
        self.value = value
        self.values = None
        self.enabled = True

    @property
    def valueAsText(self):
        return str(self.value) if self.value is not None else None


def _fake_params(manifest_path=None):
    params = [_FakeParam() for _ in range(26)]
    if manifest_path:
        params[25].value = manifest_path
    return params


class TestStep1ManifestAutoFill:
    def _manifest(self, tmp_path):
        m = {
            "features": [
                {"fc": "DA010", "path": "/gdb/DA010", "ccm_role": "soil",
                 "geometry": "Polygon"},
                {"fc": "BH140", "path": "/gdb/BH140", "ccm_role": "hydro",
                 "geometry": "Polygon"},
                {"fc": "BH080", "path": "/gdb/BH080", "ccm_role": "hydro",
                 "geometry": "Polygon"},
                {"fc": "CA010", "path": "/gdb/CA010", "ccm_role": "contours",
                 "geometry": "Polyline"},
            ]
        }
        p = tmp_path / "mgcp_manifest.json"
        p.write_text(json.dumps(m), encoding="utf-8")
        return str(p)

    def test_fills_empty_fields(self, tmp_path):
        tool = step1.CCMStep1SetupTool()
        params = _fake_params(self._manifest(tmp_path))
        filled = tool._apply_manifest(params)
        assert params[8].value == "/gdb/DA010"            # soil
        assert params[21].values == ["/gdb/BH140", "/gdb/BH080"]  # hydro
        assert params[4].value == "/gdb/CA010"            # contours
        assert filled                                     # something reported

    def test_does_not_overwrite_user_values(self, tmp_path):
        tool = step1.CCMStep1SetupTool()
        params = _fake_params(self._manifest(tmp_path))
        params[8].value  = "user_soil"
        params[21].value = "user_hydro"
        params[4].value  = "user_contours"
        tool._apply_manifest(params)
        assert params[8].value == "user_soil"
        assert params[21].value == "user_hydro"
        assert params[4].value == "user_contours"

    def test_no_manifest_is_noop(self):
        tool = step1.CCMStep1SetupTool()
        params = _fake_params()
        assert tool._apply_manifest(params) == []

    def test_skips_soil_when_preprocessed_given(self, tmp_path):
        tool = step1.CCMStep1SetupTool()
        params = _fake_params(self._manifest(tmp_path))
        params[18].value = "preprocessed_soil"            # skip-preproc field
        tool._apply_manifest(params)
        assert params[8].value is None


# ─────────────────────────────────────────────────────────────────────────────
# Step 0 — theme filter / label mapping units
# ─────────────────────────────────────────────────────────────────────────────

class TestStep0CatalogIntegration:
    def test_step0_imports_catalog(self):
        import ccm_step0_mgcp as step0
        assert step0._catalog is not None
        assert step0.VERSION == "0.56.0"

    def test_label_selection_maps_back_to_fc_names(self):
        labels = [cat.label(n) for n in ["AP030", "BH140", "DA010"]]
        names = {cat.name_from_label(v) for v in labels}
        assert names == {"AP030", "BH140", "DA010"}

    def test_ccm_relevant_theme_expansion(self):
        assert set(cat.CCM_RELEVANT_THEMES) == {
            cat.THEME_SOIL, cat.THEME_VEG, cat.THEME_HYDRO,
            cat.THEME_TRANSPORT, cat.THEME_ELEVATION, cat.THEME_PHYSIO,
        }


# ─────────────────────────────────────────────────────────────────────────────
# v0.54.0 — ccm_map_display (shared map display / symbology module)
# ─────────────────────────────────────────────────────────────────────────────
import ccm_map_display as disp


class TestMapDisplayModule:
    def test_version(self):
        assert disp.VERSION == "0.56.0"

    def test_kind_classification(self):
        assert disp.kind_of(r"C:\x\g.gdb\speed_surface_m1a2_moist") == "surface"
        assert disp.kind_of(r"C:\x\g.gdb\m1a2_moist_isochrone")     == "isochrone"
        assert disp.kind_of(r"C:\x\g.gdb\m1a2_moist_obstacles")     == "obstacles"
        assert disp.kind_of(r"C:\x\g.gdb\m1a2_moist_vehicle_compare") == "compare"
        assert disp.kind_of(r"C:\x\g.gdb\m1a2_moist_route")         == "route"
        assert disp.kind_of(r"C:\x\g.gdb\waypoint_line")            == "route"

    def test_sort_for_draw_order_bottom_up(self):
        fcs = [
            r"g.gdb\m1_route",
            r"g.gdb\m1_obstacles",
            r"g.gdb\speed_surface_m1_moist",
            r"g.gdb\m1_isochrone",
            r"g.gdb\m1_vehicle_compare",
            None,
        ]
        kinds = [disp.kind_of(f) for f in disp.sort_for_draw_order(fcs)]
        assert kinds == ["surface", "compare", "isochrone", "obstacles", "route"]

    def test_kind_order_covers_all_kinds(self):
        for k in ("surface", "compare", "isochrone", "obstacles", "route", "point"):
            assert k in disp.KIND_ORDER

    def test_iso_ring_ramp_has_no_red(self):
        # Red is reserved for No-Go — every ring colour must be blue-dominant.
        for key, (r, g, b, a) in (
            (k, v) for k, v in disp.ISO_RING_COLOURS.items()
        ):
            assert b > r, f"ring colour '{key}' is red-dominant ({r},{g},{b})"

    def test_compare_agreement_categories_invisible(self):
        for key in ("BOTH_GO", "DATA_GAP"):
            spec = disp.COMPARE_COLOURS[key]
            assert spec["fill"][3] == 0 and spec["outline"][3] == 0

    def test_compare_difference_categories_visible(self):
        for key in ("A_ONLY", "B_ONLY"):
            assert disp.COMPARE_COLOURS[key]["fill"][3] > 0

    def test_mobility_colours_keyed_on_real_field_values(self):
        # v0.54.4 regression guard.  Until v0.54.1 this palette was keyed on
        # "1".."5" for a "Condition_Number" field that NO CCM module has ever
        # produced, so the speed surface never rendered its intended ramp.
        # The keys must be the Mobility values ccm_step2_mobility actually
        # writes.
        import ccm_step2_mobility as _m2
        for value in (_m2.MOB_GO, _m2.MOB_RESTRICTED, _m2.MOB_NOGO):
            assert value.upper() in disp.MOBILITY_COLOURS, value

    def test_mobility_colours_semantics(self):
        r, g, b, a = disp.MOBILITY_COLOURS["NO GO"]
        assert r > 100 and g < 60 and b < 60, "NO GO must be red"
        rg, gg, bg, ag = disp.MOBILITY_COLOURS["GO"]
        assert gg > rg, "GO must be green-dominant"

    def test_alpha_channel_is_on_the_0_100_cim_scale(self):
        # v0.54.4 regression guard.  arcpy's {"RGB": [r, g, b, a]} takes alpha
        # as 0-100, not 0-255; values above 100 are clamped to opaque, which
        # silently discarded every intended transparency before v0.54.4.
        tables = [disp.MOBILITY_COLOURS.values(), disp.ISO_RING_COLOURS.values()]
        for table in tables:
            for rgba in table:
                assert 0 <= rgba[3] <= 100, rgba
        for spec in disp.COMPARE_COLOURS.values():
            assert 0 <= spec["fill"][3] <= 100, spec
            assert 0 <= spec["outline"][3] <= 100, spec

    def test_kind_of_returns_none_for_unknown(self):
        # v0.54.4: unknown outputs used to be mislabelled "surface", which
        # applied speed-surface symbology to whatever they were.
        assert disp.kind_of(r"C:\x\g.gdb\something_unexpected") is None
        assert disp.sort_for_draw_order(
            [r"g.gdb\speed_surface_m1_moist", r"g.gdb\mystery"]
        )[0].endswith("mystery")


# ─────────────────────────────────────────────────────────────────────────────
# v0.54.0 — ccm_data_discovery (one-folder data root scanner)
# ─────────────────────────────────────────────────────────────────────────────
import ccm_data_discovery as ddisc


@pytest.fixture()
def data_root(tmp_path):
    def mk(rel, content=b"x"):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
    mk("MGCP/cell_e013n62/FC/AP030.shp"); mk("MGCP/cell_e013n62/FC/BH080.shp")
    mk("MGCP/cell_e014n62/FC/AP030.shp"); mk("MGCP/cell_e014n62/FC/EC015.shp")
    mk("DEM/site_srtm.tif", b"a" * 100)
    mk("DEM/site_lidar_dtm.tif", b"a" * 50)
    mk("Contours/contours_50m.shp")
    mk("Soil/HWSD/HWSD.mdb")
    mk("Soil/SoilGrids/sand_0-5cm.tif"); mk("Soil/SoilGrids/clay_0-5cm.tif")
    mk("Vegetation/worldcover_2021.tif"); mk("Vegetation/gedi_canopy.tif")
    mk("Hydro/rivers.shp"); mk("Hydro/lakes.shp")
    mk("Extent/aoi_boundary.shp")
    (tmp_path / "Vehicle").mkdir(exist_ok=True)
    (tmp_path / "Vehicle" / "Vehicles_Can.csv").write_text(
        "name,vci_1,vci_50,max_road_spd_kph\nLeopard 2,25,60,68\n")
    # unnamed folder full of FACC-coded shapefiles -> content-sniffed as MGCP
    mk("randomstuff/AA010.shp"); mk("randomstuff/BH140.shp"); mk("randomstuff/DB170.shp")
    return str(tmp_path)


class TestDataDiscovery:
    def test_version(self):
        assert ddisc.VERSION == "0.56.0"

    def test_mgcp_by_name_and_by_content(self, data_root):
        res = ddisc.scan(data_root)
        names = {os.path.basename(f) for f in res["mgcp_shp_folders"]}
        assert "MGCP" in names
        assert "randomstuff" in names   # content sniffing, no keyword

    def test_dem_prefers_lidar_over_larger_srtm(self, data_root):
        res = ddisc.scan(data_root)
        assert "lidar" in os.path.basename(res["dem"]).lower()

    def test_soil_ranked_soilgrids_over_hwsd(self, data_root):
        res = ddisc.scan(data_root)
        assert res["soil"]["source_type"] == "SoilGrids"
        assert [c["source_type"] for c in res["soil_alternatives"]] == ["HWSD"]

    def test_veg_best_product_family_only(self, data_root):
        res = ddisc.scan(data_root)
        basenames = [os.path.basename(v) for v in res["veg_rasters"]]
        assert basenames == ["gedi_canopy.tif"]   # beats worldcover

    def test_hydro_loads_all(self, data_root):
        res = ddisc.scan(data_root)
        assert len(res["hydro"]) == 2

    def test_vehicle_csv_by_headers(self, data_root):
        res = ddisc.scan(data_root)
        assert os.path.basename(res["vehicle_csv"]) == "Vehicles_Can.csv"

    def test_extent_and_contours(self, data_root):
        res = ddisc.scan(data_root)
        assert "aoi" in os.path.basename(res["extent_fc"])
        assert "contour" in os.path.basename(res["contours"])

    def test_empty_or_missing_root(self, tmp_path):
        assert ddisc.scan(str(tmp_path / "nope"))["dem"] is None
        assert ddisc.scan(None)["soil"] is None

    def test_report_names_alternatives(self, data_root):
        res = ddisc.scan(data_root)
        roles = [r[0] for r in res["report"]]
        assert "Soil alternative" in roles and "DEM alternative" in roles


# ─────────────────────────────────────────────────────────────────────────────
# v0.54.0 — Vehicles_Can.csv real-file load + integrity
# ─────────────────────────────────────────────────────────────────────────────
import ccm_step2_mobility as _mob


class TestVehicleDatabase:
    def _load(self):
        # v0.54.4: Vehicle_Data/ is now the only copy of the CSV.
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            "Vehicle_Data", "Vehicles_Can.csv")
        return _mob.load_vehicles_csv(path)

    def test_loads_and_has_all_nations(self):
        vs = self._load()
        assert len(vs) >= 60
        # spot-check one platform per nation
        assert "Leopard_2A6M_CAN" in vs
        assert "M1A2_SEPv3" in vs
        assert "T-90M" in vs

    def test_every_vehicle_valid(self):
        for name, v in self._load().items():
            assert v.max_road_spd_kph > 0, name
            assert v.vehicle_width_m > 0, name
            assert v.locomotion_type in (0, 1), name
            if v.vci_1 is not None and v.vci_50 is not None:
                assert 0 < v.vci_1 <= v.vci_50, name

    def test_mmp_consistent_for_derived(self):
        # MMP column, where present, must match the model's own formula.
        import csv as _csv
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            "Vehicle_Data", "Vehicles_Can.csv")
        with open(path, encoding="utf-8-sig") as fh:
            for r in _csv.DictReader(fh):
                if r.get("source") != "derived" or not r.get("mmp_kpa"):
                    continue
                exp = _mob.compute_mmp_estimate(float(r["vci_50"]),
                                                int(r["locomotion_type"]))
                assert abs(float(r["mmp_kpa"]) - exp) <= 1.0, r["name"]

    def test_extra_columns_ignored(self):
        # nation/source/note must not break the name-based loader.
        v = next(iter(self._load().values()))
        assert v.name


# ─────────────────────────────────────────────────────────────────────────────
# v0.54.4 — ERROR 000384 regression guard: Union must never receive >2 inputs
# ─────────────────────────────────────────────────────────────────────────────
# arcpy.analysis.Union raises "ERROR 000384: Cannot have more than 2 inputs
# with a Basic or Standard license" whenever it is called with more than two
# inputs on a licence below Advanced.  This was hit for real running
# tests/arcpy_smoke_test.py against ArcGIS Pro 3.7.1 (Standard tier):
# build_speed_surface() passed soil_fc + veg_fc + slope_fc — three inputs —
# to a single Union call, so Step 2 (the tool's core output) failed outright
# for any user without an Advanced licence.  _union_license_safe() folds any
# number of inputs pairwise instead.  These tests replace arcpy on the module
# with a small recorder so the union chain can be inspected without a real
# ArcGIS licence, and assert the invariant directly: no Union call may ever
# carry more than two inputs, regardless of how many feature classes are
# supplied.
# ─────────────────────────────────────────────────────────────────────────────

class _FakeGpTools:
    """Records every Union / CopyFeatures / Delete call and tracks which
    fake paths currently 'exist', without touching a real geodatabase."""

    def __init__(self):
        self.union_calls = []      # list of (inputs_list, out_fc, join_attrs)
        self.copy_calls = []       # list of (src, dst)
        self.delete_calls = []     # list of paths
        self._existing = set()

    # -- arcpy.analysis.* ------------------------------------------------
    def Union(self, inputs, out_fc, join_attrs="ALL"):
        inputs = list(inputs)
        assert len(inputs) <= 2, (
            "ERROR 000384 regression: Union called with "
            f"{len(inputs)} inputs {inputs} — Basic/Standard licences cap "
            "this tool at 2 inputs."
        )
        assert len(inputs) >= 1, "Union called with no inputs"
        self.union_calls.append((inputs, out_fc, join_attrs))
        self._existing.add(out_fc)

    # -- arcpy.management.* -----------------------------------------------
    def CopyFeatures(self, src, dst):
        self.copy_calls.append((src, dst))
        self._existing.add(dst)

    def Delete(self, path):
        self.delete_calls.append(path)
        self._existing.discard(path)

    # -- arcpy.Exists -------------------------------------------------------
    def Exists(self, path):
        return path in self._existing


class _FakeArcpyModule:
    """Stands in for the whole `arcpy` name inside ccm_step2_mobility during
    these tests.  Deliberately minimal — only what _union_license_safe()
    touches."""

    def __init__(self):
        self._gp = _FakeGpTools()

        class _Analysis:
            Union = self._gp.Union

        class _Management:
            CopyFeatures = self._gp.CopyFeatures
            Delete = self._gp.Delete

        class _Env:
            scratchGDB = "FAKE_SCRATCH.gdb"

        self.analysis = _Analysis()
        self.management = _Management()
        self.env = _Env()
        self.Exists = self._gp.Exists

    def AddMessage(self, *a, **k):
        pass

    def AddWarning(self, *a, **k):
        pass

    def AddError(self, *a, **k):
        pass


class TestUnionLicenseSafety:
    def _swap_arcpy(self, monkeypatch):
        fake = _FakeArcpyModule()
        monkeypatch.setattr(_mob, "arcpy", fake)
        return fake

    def test_single_input_uses_copyfeatures_not_union(self, monkeypatch):
        fake = self._swap_arcpy(monkeypatch)
        out = _mob._union_license_safe(["soil"], "OUT")
        assert out == "OUT"
        assert fake._gp.union_calls == []
        assert fake._gp.copy_calls == [("soil", "OUT")]

    def test_two_inputs_single_union_call(self, monkeypatch):
        fake = self._swap_arcpy(monkeypatch)
        _mob._union_license_safe(["soil", "veg"], "OUT")
        assert len(fake._gp.union_calls) == 1
        inputs, out_fc, _ = fake._gp.union_calls[0]
        assert inputs == ["soil", "veg"]
        assert out_fc == "OUT"

    def test_three_inputs_chain_pairwise_never_exceeds_two(self, monkeypatch):
        # The exact shape that hit ERROR 000384 in the wild: soil + veg + slope.
        fake = self._swap_arcpy(monkeypatch)
        _mob._union_license_safe(["soil", "veg", "slope"], "OUT")
        assert len(fake._gp.union_calls) == 2
        for inputs, _out, _join in fake._gp.union_calls:
            assert len(inputs) == 2
        # final call must write directly to OUT (no extra rename/copy step)
        assert fake._gp.union_calls[-1][1] == "OUT"
        # exactly one intermediate feature class was created and cleaned up
        assert len(fake._gp.delete_calls) == 1

    def test_five_inputs_chain_pairwise_never_exceeds_two(self, monkeypatch):
        fake = self._swap_arcpy(monkeypatch)
        inputs = ["a", "b", "c", "d", "e"]
        _mob._union_license_safe(inputs, "OUT")
        assert len(fake._gp.union_calls) == len(inputs) - 1
        for call_inputs, _out, _join in fake._gp.union_calls:
            assert len(call_inputs) == 2
        assert fake._gp.union_calls[-1][1] == "OUT"
        # original source inputs are never deleted, only chain intermediates
        for original in inputs:
            assert original not in fake._gp.delete_calls

    def test_no_inputs_raises(self, monkeypatch):
        self._swap_arcpy(monkeypatch)
        with pytest.raises(ValueError):
            _mob._union_license_safe([], "OUT")


# ─────────────────────────────────────────────────────────────────────────────
# v0.56.0 — geometry grouping + fallback classification (Step 0 usability)
# ─────────────────────────────────────────────────────────────────────────────

class TestGeometryGrouping:
    """ccm_mgcp_catalog.geometry_group() / sort_geometry_groups()."""

    def test_shape_type_is_authoritative(self):
        assert cat.geometry_group("Point")      == cat.GEOM_POINT
        assert cat.geometry_group("Multipoint") == cat.GEOM_POINT
        assert cat.geometry_group("Polyline")   == cat.GEOM_LINE
        assert cat.geometry_group("Polygon")    == cat.GEOM_POLYGON

    def test_shape_type_wins_over_name(self):
        # a name that looks like a surface, described as a line
        assert cat.geometry_group("Polyline", "HydrographySrf") == cat.GEOM_LINE

    def test_trd4_name_suffixes(self):
        assert cat.geometry_group(None, "StructurePnt")            == cat.GEOM_POINT
        assert cat.geometry_group(None, "TransportationGroundCrv") == cat.GEOM_LINE
        assert cat.geometry_group(None, "HydrographySrf")          == cat.GEOM_POLYGON

    def test_digest_letter_suffixes(self):
        assert cat.geometry_group(None, "BH140_P") == cat.GEOM_POINT
        assert cat.geometry_group(None, "AP030L")  == cat.GEOM_LINE
        assert cat.geometry_group(None, "AL015_A") == cat.GEOM_POLYGON

    def test_undeterminable_geometry_is_other(self):
        assert cat.geometry_group(None, "AP030")   == cat.GEOM_OTHER
        assert cat.geometry_group("MultiPatch")    == cat.GEOM_OTHER

    def test_group_order_is_cartographic_top_down(self):
        # Point must sort first: it is drawn ABOVE lines, lines above polygons.
        got = cat.sort_geometry_groups(["Polygon", "Other", "Point", "Line"])
        assert got == [cat.GEOM_POINT, cat.GEOM_LINE,
                       cat.GEOM_POLYGON, cat.GEOM_OTHER]

    def test_sort_is_deduplicating_and_gap_tolerant(self):
        assert cat.sort_geometry_groups(["Line", "Line", "Point"]) == \
            [cat.GEOM_POINT, cat.GEOM_LINE]
        assert cat.sort_geometry_groups([]) == []


class TestFallbackClassification:
    """No feature class should ever be labelled 'Unknown feature' again."""

    def test_exact_catalog_hit(self):
        info = cat.lookup("AP030")
        assert info["match"] == cat.MATCH_EXACT
        assert info["name"] == "Road"
        assert info["ccm_role"] == cat.ROLE_ROAD

    def test_uncatalogued_code_uses_facc_category_not_unknown(self):
        info = cat.lookup("AP999")
        assert info["match"] == cat.MATCH_CATEGORY
        assert "Unknown" not in info["name"]
        assert info["theme"] == cat.THEME_TRANSPORT
        # never infer a role from a category-level guess
        assert info["ccm_role"] is None

    def test_category_fallback_across_facc_letters(self):
        assert cat.lookup("BH999")["theme"] == cat.THEME_HYDRO
        assert cat.lookup("EC999")["theme"] == cat.THEME_VEG
        assert cat.lookup("DB999")["theme"] == cat.THEME_PHYSIO
        assert cat.lookup("GB999")["theme"] == cat.THEME_AERO

    def test_unrecognised_letter_falls_back_to_other(self):
        info = cat.lookup("QQ777")
        assert info["match"] == cat.MATCH_CATEGORY
        assert info["theme"] == cat.THEME_OTHER

    def test_trd4_thematic_names_are_classified_by_keyword(self):
        for name, theme in [("HydrographySrf",          cat.THEME_HYDRO),
                            ("TransportationGroundCrv", cat.THEME_TRANSPORT),
                            ("VegetationSrf",           cat.THEME_VEG),
                            ("SettlementSrf",           cat.THEME_CULTURE),
                            ("PhysiographySrf",         cat.THEME_PHYSIO),
                            ("BoundaryCrv",             cat.THEME_BOUNDARY)]:
            info = cat.lookup(name)
            assert info["match"] == cat.MATCH_KEYWORD, name
            assert info["theme"] == theme, name

    def test_only_contours_earn_the_contours_role(self):
        # a spot-height layer given ROLE_CONTOURS would silently produce a
        # wrong Step 1 slope surface
        assert cat.lookup("ElevationContourCrv")["ccm_role"] == cat.ROLE_CONTOURS
        assert cat.lookup("SpotElevationPnt")["ccm_role"] is None
        assert cat.lookup("SpotElevationPnt")["theme"] == cat.THEME_ELEVATION

    def test_unmatched_name_is_match_none(self):
        assert cat.lookup("random_layer_42")["match"] == cat.MATCH_NONE

    def test_is_classified_only_for_named_features(self):
        assert cat.is_classified("AP030") is True
        assert cat.is_classified("AP999") is False
        assert cat.is_classified("HydrographySrf") is False

    def test_unclassified_codes_lists_only_category_matches(self):
        got = cat.unclassified_codes(
            ["AP030", "AP999", "QQ777", "HydrographySrf", "random"])
        assert got == ["AP999", "QQ777"]

    def test_label_round_trips_through_every_tier(self):
        for n in ["AP030", "AP999", "QQ777", "HydrographySrf",
                  "AL015_A", "random_layer_42"]:
            assert cat.name_from_label(cat.label(n)) == n, n

    def test_alias_is_name_first_and_keeps_the_code(self):
        assert cat.alias("AL015") == "Building (AL015)"
        assert cat.alias("AP999") == "Road / track feature (AP999)"
        # nothing to add -> unchanged
        assert cat.alias("random_layer_42") == "random_layer_42"


class TestUserCatalogOverride:
    """mgcp_catalog_user.csv lets the user name codes we could not verify."""

    def _reset(self):
        cat.load_user_catalog(None, reset=True)

    def test_template_seeds_the_unclassified_codes(self, tmp_path):
        self._reset()
        path = cat.write_user_catalog_template(str(tmp_path), ["AP999", "QQ777"])
        assert path and os.path.isfile(path)
        body = open(path, encoding="utf-8").read()
        assert "AP999,," in body and "QQ777,," in body
        # the theme column is pre-filled from the FACC category
        assert "AP999,,Transportation," in body

    def test_override_wins_and_supplies_name_and_role(self, tmp_path):
        self._reset()
        p = tmp_path / cat.USER_CATALOG_FILENAME
        p.write_text("code,name,theme,ccm_role\nAP999,Farm Road,Transportation,road\n",
                     encoding="utf-8")
        n, srcs = cat.load_user_catalog(str(tmp_path))
        try:
            assert n == 1 and srcs
            info = cat.lookup("AP999")
            assert info["match"] == cat.MATCH_USER
            assert info["name"] == "Farm Road"
            assert info["ccm_role"] == "road"
            assert cat.unclassified_codes(["AP999"]) == []
            assert cat.name_from_label(cat.label("AP999")) == "AP999"
        finally:
            self._reset()

    def test_refresh_preserves_rows_already_filled_in(self, tmp_path):
        self._reset()
        p = tmp_path / cat.USER_CATALOG_FILENAME
        p.write_text("code,name,theme,ccm_role\nAP999,Farm Road,Transportation,road\n",
                     encoding="utf-8")
        cat.write_user_catalog_template(str(tmp_path), ["AP999", "BB404"])
        body = p.read_text(encoding="utf-8")
        assert "AP999,Farm Road,Transportation,road" in body
        assert "BB404,," in body

    def test_blank_and_malformed_rows_are_ignored(self, tmp_path):
        self._reset()
        p = tmp_path / cat.USER_CATALOG_FILENAME
        p.write_text("# comment\ncode,name,theme,ccm_role\n"
                     "AP999,,Transportation,\n"      # no name -> skip
                     "nonsense,Foo,Transportation,\n"  # bad code -> skip
                     "BB404,Jetty,NotATheme,\n",       # bad theme -> category
                     encoding="utf-8")
        n, _ = cat.load_user_catalog(str(tmp_path))
        try:
            assert n == 1
            info = cat.lookup("BB404")
            assert info["name"] == "Jetty"
            assert info["theme"] == cat.THEME_HYDRO   # from the FACC category
        finally:
            self._reset()


class TestStep0GroupMode:
    """Parameter 16 supersedes the legacy checkboxes without breaking them."""

    class _P:
        def __init__(self, value=None):
            self.value = value
        @property
        def valueAsText(self):
            return None if self.value is None else str(self.value)

    def _params(self, mode=None, by_theme=False, by_gdb=False):
        p = [self._P() for _ in range(17)]
        p[9]  = self._P(by_gdb)
        p[13] = self._P(by_theme)
        p[16] = self._P(mode)
        return p

    def _tool(self):
        import ccm_step0_mgcp as step0
        return step0.CCMStep0MGCPTool()

    def test_geometry_is_the_default_mode(self):
        import ccm_step0_mgcp as step0
        params = step0.CCMStep0MGCPTool().getParameterInfo()
        assert params[16].value == step0.GROUP_MODE_GEOMETRY
        assert len(params) == 21          # 16-20 appended, 0-15 preserved

    def test_each_mode_resolves(self):
        import ccm_step0_mgcp as step0
        for text, key in [(step0.GROUP_MODE_GEOMETRY, "geometry"),
                          (step0.GROUP_MODE_THEME,    "theme"),
                          (step0.GROUP_MODE_GDB,      "gdb"),
                          (step0.GROUP_MODE_FLAT,     "none")]:
            got = self._tool()._resolve_group_mode(self._params(text))
            assert got == key, text

    def test_parameter_16_overrides_the_legacy_checkboxes(self):
        import ccm_step0_mgcp as step0
        got = self._tool()._resolve_group_mode(
            self._params(step0.GROUP_MODE_GEOMETRY, by_theme=True, by_gdb=True))
        assert got == "geometry"

    def test_legacy_sentinel_falls_back_to_the_checkboxes(self):
        import ccm_step0_mgcp as step0
        L = step0.GROUP_MODE_LEGACY
        t = self._tool()
        assert t._resolve_group_mode(self._params(L, by_theme=True)) == "theme"
        assert t._resolve_group_mode(self._params(L, by_gdb=True))   == "gdb"
        assert t._resolve_group_mode(self._params(L))                == "none"

    def test_toolbox_without_parameter_16_still_works(self):
        # a saved model invoking the pre-v0.56.0 parameter list
        p = [self.__class__._P() for _ in range(16)]
        p[9], p[13] = self.__class__._P(False), self.__class__._P(True)
        assert self._tool()._resolve_group_mode(p) == "theme"

# <<< END OF FILE >>>
