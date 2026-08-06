# =============================================================================
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON (Beta)
# =============================================================================
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
        assert step0.VERSION == "0.54.1"

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
        assert disp.VERSION == "0.54.1"

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

    def test_condition_colours_no_go_is_red(self):
        r, g, b, a = disp.COND_COLOURS["1"]
        assert r > 100 and g < 60 and b < 60
        r5, g5, b5, a5 = disp.COND_COLOURS["5"]
        assert g5 > r5


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
        assert ddisc.VERSION == "0.54.1"

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
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            "Vehicles_Can.csv")
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
                            "Vehicles_Can.csv")
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

# <<< END OF FILE >>>
