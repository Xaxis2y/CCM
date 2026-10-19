# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""Regression tests for the factual inventory compatibility contract.

The factual catalog engine remains directly callable, while v0.59.2 adds the
separate integrated scoring and recommendation gate in
``test_ccm_step0b_integration.py``.
"""

import json
import os
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for path in (str(ROOT), str(HERE)):
    if path not in os.sys.path:
        os.sys.path.insert(0, path)

import ccm_data_catalog as cat  # noqa: E402
import ccm_data_report as report  # noqa: E402
import ccm_data_sources as sources  # noqa: E402
import ccm_step0b_intelligence as step0b  # noqa: E402
import CCM_Data_Scanner_GUI as gui  # noqa: E402
import build_exe  # noqa: E402
import package_ccm as packager  # noqa: E402
import make_fake_data as fake  # noqa: E402


VERSION = "0.60.8"  # v0.59.2 -- bumped by bump_version.py from v0.57. Review this line's comment.
EXPECTED_VERSION = VERSION

# GUI scans run on a worker thread, where ArcPy is unsafe.  Keep the automated
# suite deterministic and exercise the same GDAL/header fallback path.
cat.set_arcpy_enabled(False)


@pytest.fixture(scope="module")
def data_root(tmp_path_factory):
    target = tmp_path_factory.mktemp("ccm_v057_data") / "DATA"
    fake.build(str(target))
    return target


@pytest.fixture(scope="module")
def aoi(data_root):
    return data_root / "Extent" / "AOI_Lebanon.shp"


@pytest.fixture(scope="module")
def catalog(data_root, aoi):
    return cat.build_catalog(str(data_root), aoi_path=str(aoi))


def all_records(catalog):
    for bucket in catalog["roles"].values():
        yield from bucket["records"]
    yield from catalog["unclassified"]


class TestReleaseContract:
    def test_all_python_components_share_version(self):
        modules = (cat, report, sources, step0b, gui, build_exe, packager, fake)
        assert {module.VERSION for module in modules} == {EXPECTED_VERSION}

    def test_scoring_modules_are_shipped_with_step0b(self):
        assert (ROOT / "ccm_data_quality.py").is_file()
        assert (ROOT / "ccm_data_selector.py").is_file()

    def test_catalog_is_factual_and_has_no_readiness_summary(self, catalog):
        assert catalog["ccm_version"] == EXPECTED_VERSION
        assert "readiness" not in catalog
        assert "quality_version" not in catalog
        assert "selection" not in catalog
        for record in all_records(catalog):
            # Schema-reserved forward-compatibility fields stay explicitly
            # null.  They are not evidence or scores in this release.
            assert record.get("quality") is None
            assert record.get("fitness") is None
            assert record.get("confidence") is None

    def test_sources_are_descriptive_only(self):
        info = sources.describe("dem", "SRTM")
        assert info["identified"] is True
        assert "Shuttle Radar" in info["full_name"]
        assert info["what"] and info["contains"]

    def test_catalog_schema_is_declared(self):
        assert isinstance(cat.CATALOG_SCHEMA, int)
        assert cat.CATALOG_SCHEMA >= 1

    def test_dedicated_anaconda_script_contract(self):
        script = (ROOT / "CCM_anaconda.bat").read_text(encoding="utf-8")
        assert 'set "ENV_NAME=ccm_tool"' in script
        assert "python=3.11" in script
        assert "pytest pyflakes pyinstaller" in script
        assert "--with-gdal" in script
        assert "ArcPy is licensed ArcGIS Pro software" in script


class TestHeaderReaders:
    def test_geotiff_metadata_is_read_without_arcgis(self, data_root):
        path = data_root / "DEM" / "DEM_10m.tif"
        probe = cat.read_geotiff_header(str(path))
        assert probe["width"] == 200
        assert probe["height"] == 200
        assert probe["cell_size_x"] == pytest.approx(10.0)
        assert probe["cell_size_y"] == pytest.approx(10.0)
        assert probe["epsg"] == 32636
        assert probe["extent"] == pytest.approx(fake.AOI_BBOX)

    def test_shapefile_metadata_and_fields_are_read(self, aoi):
        assert cat.read_shapefile_bbox(str(aoi)) == pytest.approx(fake.AOI_BBOX)
        assert cat.read_shapefile_count(str(aoi)) == 1
        fields = cat.read_dbf_fields(str(aoi.with_suffix(".dbf")))
        assert fields["record_count"] == 1
        assert {f.upper() for f in fields["fields"]} >= {"ID", "NAME"}
        crs = cat.read_prj(str(aoi.with_suffix(".prj")))
        assert crs["type"] == "Projected"
        assert crs["epsg"] == 32636

    def test_vehicle_csv_is_detected_by_schema(self, data_root):
        path = data_root / "Vehicle" / "Vehicles_Can.csv"
        assert cat._is_vehicle_csv(str(path))
        candidates = cat.deep_scan(str(data_root))
        found = [c for c in candidates if c["path"] == str(path)]
        assert found and found[0]["role"] == cat.ROLE_VEHICLE
        assert "headers" in found[0]["role_basis"]


class TestDiscoveryAndLimits:
    def test_expected_roles_and_unclassified_files_are_visible(self, catalog):
        for role in (cat.ROLE_DEM, cat.ROLE_SOIL, cat.ROLE_VEG,
                     cat.ROLE_HYDRO, cat.ROLE_VEHICLE, cat.ROLE_EXTENT):
            assert catalog["roles"][role]["count"] > 0
        names = {record["name"] for record in catalog["unclassified"]}
        assert {"field_notes.csv", "site_photo.jpg", "old_map.pdf"} <= names

    def test_file_cap_applies_to_supported_files(self, tmp_path):
        for number in range(8):
            (tmp_path / ("dem_%02d.tif" % number)).write_bytes(b"II")
        assert len(cat.deep_scan(str(tmp_path), max_files=3)) == 3

    def test_file_cap_applies_to_unsupported_files(self, tmp_path):
        for number in range(8):
            (tmp_path / ("notes_%02d.bin" % number)).write_bytes(b"x")
        result = cat.deep_scan(str(tmp_path), max_files=3)
        assert len(result) == 3
        assert all(item["dataset_type"] == "other" for item in result)

    def test_gdb_layers_are_individual_candidates(self, tmp_path, monkeypatch):
        gdb = tmp_path / "Hydro.gdb"
        gdb.mkdir()

        def enumerate_two(path, root):
            return [
                {"path": str(path) + "::Rivers", "name": "Rivers",
                 "dataset_type": "container_layer", "role": cat.ROLE_HYDRO,
                 "role_basis": "file name", "size": None,
                 "signature": None, "container_path": str(path)},
                {"path": str(path) + "::Lakes", "name": "Lakes",
                 "dataset_type": "container_layer", "role": cat.ROLE_HYDRO,
                 "role_basis": "file name", "size": None,
                 "signature": None, "container_path": str(path)},
            ]

        monkeypatch.setattr(cat, "_enumerate_container", enumerate_two)
        result = cat.deep_scan(str(tmp_path), max_files=20)
        assert [item["name"] for item in result] == ["Rivers", "Lakes"]
        assert all(item["dataset_type"] == "container_layer" for item in result)

    def test_container_layers_obey_file_cap(self, tmp_path, monkeypatch):
        gdb = tmp_path / "many.gdb"
        gdb.mkdir()

        def enumerate_many(path, root):
            return [
                {"path": str(path) + "::layer_%d" % i,
                 "name": "layer_%d" % i, "dataset_type": "container_layer",
                 "role": cat.ROLE_UNKNOWN, "role_basis": "test",
                 "size": None, "signature": None,
                 "container_path": str(path)}
                for i in range(10)
            ]

        monkeypatch.setattr(cat, "_enumerate_container", enumerate_many)
        assert len(cat.deep_scan(str(tmp_path), max_files=4)) == 4

    def test_real_geopackage_layers_and_union_coverage_when_ogr_available(
            self, tmp_path, aoi):
        osgeo = cat._try_osgeo()
        if osgeo is None:
            pytest.skip("GDAL/OGR is not installed in this environment")
        _gdal, ogr, osr = osgeo
        path = tmp_path / "Hydro.gpkg"
        driver = ogr.GetDriverByName("GPKG")
        assert driver is not None
        dataset = driver.CreateDataSource(str(path))
        assert dataset is not None
        spatial_ref = osr.SpatialReference()
        spatial_ref.ImportFromEPSG(32636)
        x0, y0, x1, y1 = fake.AOI_BBOX
        polygon_wkt = (
            "POLYGON (({0} {1}, {2} {1}, {2} {3}, {0} {3}, {0} {1}))"
            .format(x0, y0, x1, y1))
        for layer_name in ("Rivers", "Lakes"):
            layer = dataset.CreateLayer(
                layer_name, spatial_ref, geom_type=ogr.wkbPolygon)
            assert layer is not None
            for _duplicate in range(2 if layer_name == "Rivers" else 1):
                feature = ogr.Feature(layer.GetLayerDefn())
                feature.SetGeometry(ogr.CreateGeometryFromWkt(polygon_wkt))
                assert layer.CreateFeature(feature) == 0
                feature = None
        dataset = None

        candidates = cat.deep_scan(str(tmp_path))
        layers = [item for item in candidates
                  if item["dataset_type"] == "container_layer"]
        assert {item["name"] for item in layers} == {"Rivers", "Lakes"}
        rivers = next(item for item in layers if item["name"] == "Rivers")
        assert cat._polygon_intersection_pct_ogr(
            rivers["path"], str(aoi)) == pytest.approx(100.0)


class TestDuplicateSafety:
    def test_known_raster_copy_is_folded(self, catalog):
        assert catalog["stats"]["duplicate_groups"] >= 1
        groups = catalog["duplicate_groups"]
        assert any(len(group) == 2 and all("DEM_10m.tif" in p for p in group)
                   for group in groups)
        dem_records = catalog["roles"][cat.ROLE_DEM]["records"]
        assert any(len(record["locations"]) == 2 for record in dem_records)

    def test_shapefile_signature_includes_attribute_sidecars(self, tmp_path):
        first = tmp_path / "Hydro" / "same_geometry_a"
        second = tmp_path / "Hydro" / "same_geometry_b"
        first.parent.mkdir()
        fake.write_shapefile(str(first), fake.AOI_BBOX, fields=["ID", "NAME"])
        fake.write_shapefile(str(second), fake.AOI_BBOX, fields=["ID", "CLASS"])
        first_shp = str(first.with_suffix(".shp"))
        second_shp = str(second.with_suffix(".shp"))
        assert cat.file_signature(first_shp) == cat.file_signature(second_shp)
        assert cat.dataset_signature(first_shp) != cat.dataset_signature(second_shp)

    def test_identical_content_in_different_roles_is_not_folded(self, tmp_path):
        first = tmp_path / "DEM" / "shared.tif"
        second = tmp_path / "Vegetation" / "shared.tif"
        first.parent.mkdir()
        second.parent.mkdir()
        first.write_bytes(b"identical")
        second.write_bytes(b"identical")
        candidates = cat.deep_scan(str(tmp_path))
        groups, duplicates = cat.find_duplicates(candidates)
        assert groups == []
        assert duplicates == set()


class TestCoverageAndCrs:
    def test_projected_dem_has_measured_or_approximated_full_coverage(self,
                                                                      catalog):
        records = catalog["roles"][cat.ROLE_DEM]["records"]
        record = next(r for r in records if r["name"] == "DEM_10m.tif")
        assert record["coverage_aoi_pct"] == pytest.approx(100.0)
        assert record["coverage_basis"]

    def test_mismatched_epsg_never_gets_a_coverage_number(
            self, data_root, monkeypatch):
        """A deliberately backend-free scan must stay honestly unmeasured.

        The test explicitly disables both transform backends so it has the
        same result in the standard and GDAL-enabled Anaconda environments.
        """
        monkeypatch.setattr(cat, "_try_arcpy", lambda: None)
        monkeypatch.setattr(cat, "_try_osgeo", lambda: None)
        candidate = next(c for c in cat.deep_scan(str(data_root))
                         if c["name"] == "DEM_10m.tif")
        aoi = {"extent": list(fake.AOI_BBOX),
               "crs": {"epsg": 4326, "type": "Geographic",
                       "name": "WGS 84"}}
        record = cat.build_record(candidate, str(data_root), aoi=aoi)
        assert record["coverage_aoi_pct"] is None
        assert any("coverage not computed" in item for item in record["limitations"])

    def test_mismatched_epsg_computes_coverage_when_transform_is_available(
            self, data_root, monkeypatch):
        """v0.59.2: a CRS mismatch alone must no longer block coverage --
        this is the real-world MGCP-in-Geographic-CRS-vs-Projected-Analysis-
        Extent scenario the fix targets. reproject_extent() is monkeypatched
        so this contract is verified independent of whether arcpy/GDAL
        happen to be installed in whatever environment runs this suite."""
        candidate = next(c for c in cat.deep_scan(str(data_root))
                         if c["name"] == "DEM_10m.tif")
        aoi = {"extent": list(fake.AOI_BBOX),
               "crs": {"epsg": 4326, "type": "Geographic", "name": "WGS 84"}}

        def _fake_reproject(extent, src_crs, dst_crs):
            # Pretend the transform succeeded and landed exactly on the
            # dataset's own extent -- the simplest checkable case, and it
            # mirrors the fixture already used by the 100%-coverage,
            # same-CRS test above.
            return tuple(fake.AOI_BBOX)

        monkeypatch.setattr(cat, "reproject_extent", _fake_reproject)
        record = cat.build_record(candidate, str(data_root), aoi=aoi)
        assert record["coverage_aoi_pct"] == pytest.approx(100.0)
        assert record["coverage_basis"]
        assert not any("coverage not computed" in item
                       for item in record["limitations"])

    def test_mismatched_epsg_stays_honest_when_transform_fails(
            self, data_root, monkeypatch):
        """Even with EPSG known on both sides, if reproject_extent() itself
        cannot produce a transformed extent (here monkeypatched to fail, the
        same outcome the real function returns when neither arcpy nor GDAL
        is available), coverage must stay unmeasured."""
        candidate = next(c for c in cat.deep_scan(str(data_root))
                         if c["name"] == "DEM_10m.tif")
        aoi = {"extent": list(fake.AOI_BBOX),
               "crs": {"epsg": 4326, "type": "Geographic", "name": "WGS 84"}}
        monkeypatch.setattr(cat, "reproject_extent", lambda *a, **k: None)
        record = cat.build_record(candidate, str(data_root), aoi=aoi)
        assert record["coverage_aoi_pct"] is None
        assert any("coverage not computed" in item for item in record["limitations"])

    def test_known_and_unknown_crs_never_get_compared(self, data_root):
        candidate = next(c for c in cat.deep_scan(str(data_root))
                         if c["name"] == "DEM_10m.tif")
        aoi = {"extent": list(fake.AOI_BBOX), "crs": {}}
        record = cat.build_record(candidate, str(data_root), aoi=aoi)
        assert record["coverage_aoi_pct"] is None
        assert any("could not be confirmed" in item.lower()
                   for item in record["limitations"])

    def test_overlap_math_is_bounded(self):
        assert cat.extent_overlap_pct((0, 0, 2, 2), (1, 1, 3, 3)) == 25.0
        assert cat.extent_overlap_pct((0, 0, 8, 8), (1, 1, 3, 3)) == 100.0
        assert cat.extent_overlap_pct((0, 0, 1, 1), (2, 2, 3, 3)) == 0.0

    def test_utm_recommendation(self):
        result = cat.recommend_utm_epsg(35.5, 33.8)
        assert result["epsg"] == 32636
        assert "36N" in result["name"]


class TestReprojectExtent:
    """v0.59.2: direct tests of reproject_extent(), independent of the
    build_record()/coverage_pct() wiring covered above."""

    def test_identity_when_epsg_matches(self):
        extent = (0.0, 0.0, 10.0, 10.0)
        crs = {"epsg": 32636}
        assert cat.reproject_extent(extent, crs, crs) == tuple(extent)

    def test_none_when_epsg_missing_on_either_side(self):
        extent = (0.0, 0.0, 10.0, 10.0)
        assert cat.reproject_extent(extent, {}, {"epsg": 32636}) is None
        assert cat.reproject_extent(extent, {"epsg": 4326}, {}) is None

    def test_none_when_extent_missing(self):
        assert cat.reproject_extent(None, {"epsg": 4326}, {"epsg": 32636}) is None

    def test_rejects_projected_values_labelled_geographic(self):
        assert cat.reproject_extent(
            fake.AOI_BBOX,
            {"epsg": 4326, "type": "Geographic"},
            {"epsg": 32636}) is None

    def test_none_when_no_transform_backend_available(self, monkeypatch):
        # Explicitly simulate the frozen/no-GIS-dependency mode. This keeps
        # the expected degraded behavior stable when GDAL is installed.
        monkeypatch.setattr(cat, "_try_arcpy", lambda: None)
        monkeypatch.setattr(cat, "_try_osgeo", lambda: None)
        extent = (35.0, 33.0, 35.2, 33.2)
        assert cat.reproject_extent(
            extent, {"epsg": 4326}, {"epsg": 32636}) is None

    def test_transforms_a_known_extent_when_gdal_is_available(self):
        og = cat._try_osgeo()
        if og is None:
            pytest.skip("GDAL/OGR bindings not installed in this environment")
        # AOI_BBOX (tests/make_fake_data.py) is defined directly in
        # EPSG:32636 (UTM 36N) projected metres. Converting it to EPSG:4326
        # should land in the same real-world neighbourhood as this fixture
        # module's other geographic-CRS point (origin_x=35.15, origin_y=33.26)
        # -- a broad sanity range, not an exact expected value, since the
        # point of this test is "did a real transform run", not pinpoint
        # geodesy.
        result = cat.reproject_extent(list(fake.AOI_BBOX),
                                      {"epsg": 32636}, {"epsg": 4326})
        assert result is not None
        x0, y0, x1, y1 = result
        assert 34.0 < x0 < x1 < 36.0     # longitude, degrees East
        assert 33.0 < y0 < y1 < 34.0     # latitude, degrees North


class TestReportsAndAtomicWrites:
    def test_text_report_is_factual(self, catalog):
        text = "\n".join(report.render_text(catalog))
        assert "FACTUAL INVENTORY" in text
        assert "DETECTED DATA" in text
        assert "MISSING CCM ROLES" in text
        assert "automatic best-source recommendation" in text.lower()

    def test_html_is_self_contained_and_escapes_data(self, catalog):
        altered = json.loads(json.dumps(catalog))
        altered["unclassified"][0]["path"] = "<unsafe & name>"
        html = report.render_html(altered)
        assert "<!doctype html>" in html.lower()
        assert "<style>" in html.lower()
        assert "&lt;unsafe &amp; name&gt;" in html
        assert "http://" not in html and "https://" not in html

    def test_all_outputs_round_trip_and_leave_no_temp_files(self, catalog,
                                                             tmp_path):
        outputs = report.write_all(catalog, str(tmp_path))
        assert set(outputs) == {"json", "html", "text"}
        assert all(Path(path).is_file() for path in outputs.values())
        loaded = cat.load_catalog_json(outputs["json"])
        assert loaded["ccm_version"] == EXPECTED_VERSION
        assert not list(tmp_path.glob(".ccm_write_*.tmp"))

    def test_atomic_overwrite_replaces_complete_json(self, tmp_path):
        destination = tmp_path / "catalog.json"
        cat.atomic_write_text(str(destination), '{"first": true}\n')
        cat.atomic_write_text(str(destination), '{"second": true}\n')
        assert json.loads(destination.read_text(encoding="utf-8")) == {
            "second": True}
        assert not list(tmp_path.glob(".ccm_write_*.tmp"))


class TestWorkflowIntegration:
    def test_run_scan_writes_reports_and_additive_project_keys(self, data_root,
                                                                aoi, tmp_path,
                                                                monkeypatch):
        project = tmp_path / "project"
        project.mkdir()
        config = project / "ccm_project.json"
        config.write_text('{"preserve_me": 7}\n', encoding="utf-8")
        monkeypatch.setattr(step0b, "_cfg", None)
        catalog, outputs = step0b.run_scan(
            str(data_root), aoi_path=str(aoi), project_folder=str(project))
        assert not catalog.get("error")
        assert set(outputs) == {"json", "html", "text"}
        saved = json.loads(config.read_text(encoding="utf-8"))
        assert saved["preserve_me"] == 7
        assert saved["data_root"] == str(data_root)
        assert saved["data_catalog_json"] == outputs["json"]
        assert "readiness" not in saved

    def test_cli_success_is_scan_success_even_with_missing_roles(self, tmp_path,
                                                                 capsys):
        root = tmp_path / "partial"
        root.mkdir()
        (root / "notes.txt").write_text("inventory me", encoding="utf-8")
        code = step0b.main(["--data-root", str(root), "--no-reports", "--quiet"])
        assert code == 0
        assert "MISSING CCM ROLES" in capsys.readouterr().out

    def test_cli_missing_root_returns_error(self, tmp_path, capsys):
        code = step0b.main(["--data-root", str(tmp_path / "does_not_exist"),
                           "--no-reports", "--quiet"])
        assert code == 2
        assert "ERROR:" in capsys.readouterr().out

    def test_json_only_output_is_machine_readable(self, data_root, capsys):
        code = step0b.main(["--data-root", str(data_root), "--json-only"])
        payload = json.loads(capsys.readouterr().out)
        assert code == 0
        assert payload["catalog"]["ccm_version"] == EXPECTED_VERSION
        assert payload["readiness_scores_json"]

    def test_scan_does_not_modify_source_files(self, data_root, aoi):
        before = {
            path.relative_to(data_root): (path.stat().st_size,
                                          path.stat().st_mtime_ns)
            for path in data_root.rglob("*") if path.is_file()
        }
        cat.build_catalog(str(data_root), aoi_path=str(aoi))
        after = {
            path.relative_to(data_root): (path.stat().st_size,
                                          path.stat().st_mtime_ns)
            for path in data_root.rglob("*") if path.is_file()
        }
        assert after == before

    def test_gui_uses_factual_engine(self):
        assert gui.VERSION == EXPECTED_VERSION
        assert gui.ENGINE_ERROR is None
        assert not hasattr(gui, "_quality")

    def test_frozen_gui_does_not_bundle_arcgis_tool(self):
        assert "ccm_step0b_intelligence" not in build_exe.HIDDEN_IMPORTS

    def test_release_package_excludes_pytest_runtime_folders(self):
        # v0.60.2 -- this asserted only on the prefix "_pytest_", which
        # nothing in the tree is ever named: run_verification() creates
        # "pytest_tmp_<timestamp>". The assertion therefore passed
        # trivially and would have kept passing even if those folders
        # were packaged. Assert on the real names, and on the excluded
        # parents they live under.
        packaged = [relative for relative, _path in packager.release_files()]
        for relative in packaged:
            for part in relative.parts:
                assert not part.startswith("_pytest_"), relative
                assert not part.startswith("pytest_tmp_"), relative
                assert part not in packager.EXCLUDED_PARTS, relative
            assert relative.suffix.lower() != ".log", relative

    def test_is_excluded_dir_matches_real_pytest_basetemp_name(self):
        # The basetemp name run_verification() actually builds.
        assert packager.is_excluded_dir("pytest_tmp_20260911_113105_355001")
        assert packager.is_excluded_dir("verification_artifacts")
        assert packager.is_excluded_dir("__pycache__")
        assert not packager.is_excluded_dir("tests")
        assert not packager.is_excluded_dir("Vehicle_Data")


class TestSourceIntegrity:
    @pytest.mark.parametrize("path", sorted(ROOT.glob("*.py")))
    def test_python_source_has_end_marker(self, path):
        assert path.read_text(encoding="utf-8").rstrip().endswith(
            "# <<< END OF FILE >>>")

    def test_no_runtime_network_dependency(self):
        runtime_files = [
            ROOT / "ccm_data_catalog.py", ROOT / "ccm_data_sources.py",
            ROOT / "ccm_data_report.py", ROOT / "ccm_step0b_intelligence.py",
            ROOT / "CCM_Data_Scanner_GUI.py",
        ]
        forbidden = ("import requests", "from requests", "urllib.request",
                     "import socket", "http.client")
        text = "\n".join(path.read_text(encoding="utf-8")
                         for path in runtime_files)
        assert not any(token in text for token in forbidden)

class TestSelfPollutionExclusion:
    """v0.59.7 -- the scan must never catalogue the CCM tool's own release
    tree, or this scanner's own outputs, as if they were analyst data.

    A real field scan (AOI_Lebanon) had a copy of the release unzipped
    beside the data: it contributed 40 duplicate groups, 318 unclassified
    files and 7 competing "vehicle databases" -- 6 of them 3-row test
    fixtures -- against 1 real one.
    """

    def _make_install(self, folder):
        folder.mkdir(parents=True, exist_ok=True)
        # A release tree is recognised by its MODULE signature -- the two
        # modules AND the toolbox -- so that a lone .pyt copied next to real
        # data is not mistaken for one (see test below).
        (folder / "ccm_data_catalog.py").write_text("x", encoding="utf-8")
        (folder / "ccm_version.py").write_text("x", encoding="utf-8")
        (folder / "CCM_Tool_v9.9.9.pyt").write_text("x", encoding="utf-8")
        (folder / "soil_rci.csv").write_text(
            "uscs_code,rci_dry" + chr(10) + "SM,200" + chr(10),
            encoding="utf-8")
        vehicle = folder / "Vehicle_Data"
        vehicle.mkdir()
        (vehicle / "Vehicles_Can.csv").write_text(
            "name,vci_1,vci_50" + chr(10) + "Fake,1,2" + chr(10),
            encoding="utf-8")

    def test_copied_release_tree_is_skipped(self, tmp_path):
        (tmp_path / "DEM").mkdir()
        (tmp_path / "DEM" / "real_dem.tif").write_bytes(b"II")
        self._make_install(tmp_path / "CCM_Tool_v9.9.9")

        skipped = []
        names = {c["name"] for c in
                 cat.deep_scan(str(tmp_path), skipped=skipped)}
        assert "real_dem.tif" in names
        assert "Vehicles_Can.csv" not in names
        assert "soil_rci.csv" not in names
        assert any("CCM_Tool_v9.9.9" in entry for entry in skipped)

    def test_a_lone_toolbox_file_does_not_prune_the_analyst_data(self,
                                                                 tmp_path):
        """Copying just the .pyt into a working folder is a normal ArcGIS
        habit. Treating that folder as a release tree would delete the
        analyst's own data from the catalogue -- the exact failure this
        whole exclusion exists to prevent, inverted."""
        working = tmp_path / "MyProject"
        working.mkdir()
        (working / "CCM_Tool_v0.59.7.pyt").write_text("x", encoding="utf-8")
        (working / "dem_mosaic.tif").write_bytes(b"II")
        (working / "hydro_rivers.shp").write_bytes(b"\x00" * 100)

        names = {c["name"] for c in cat.deep_scan(str(tmp_path))}
        assert "dem_mosaic.tif" in names
        assert "hydro_rivers.shp" in names

    def test_test_scaffolding_folders_are_skipped(self, tmp_path):
        (tmp_path / "real.tif").write_bytes(b"II")
        for folder in ("verification_artifacts", "fake_data",
                       "pytest_tmp_20260826_134609"):
            target = tmp_path / folder / "DEM"
            target.mkdir(parents=True)
            (target / ("fixture_" + folder + ".tif")).write_bytes(b"II")

        names = {c["name"] for c in cat.deep_scan(str(tmp_path))}
        assert names == {"real.tif"}

    def test_scan_aimed_inside_the_tool_folder_still_works(self, tmp_path,
                                                           monkeypatch):
        """Exclusion is decided against the scan ROOT: deliberately pointing
        the scanner at a release tree -- which this suite's own temporary
        data roots do -- must still scan it."""
        install = tmp_path / "CCM_Tool_v9.9.9"
        self._make_install(install)
        monkeypatch.setattr(cat, "_TOOL_DIR", str(install))
        names = {c["name"] for c in cat.deep_scan(str(install))}
        assert "Vehicles_Can.csv" in names

    def test_scanner_outputs_are_not_catalogued_as_data(self, tmp_path):
        (tmp_path / "real.tif").write_bytes(b"II")
        for output in ("ccm_project.json", "ccm_data_catalog.json",
                       "ccm_quality_scores.json", "ccm_recommendations.json",
                       "CCM_Data_Intelligence_Report.txt",
                       "CCM_Recommendations_Report.html"):
            (tmp_path / output).write_text("{}", encoding="utf-8")
        (tmp_path / "mgcp_manifest.json").write_text("{}", encoding="utf-8")

        names = {c["name"] for c in cat.deep_scan(str(tmp_path))}
        assert "real.tif" in names
        assert "ccm_project.json" not in names
        assert "ccm_data_catalog.json" not in names
        assert "CCM_Data_Intelligence_Report.txt" not in names
        # a genuine Step 0 input, not one of this tool's own outputs
        assert "mgcp_manifest.json" in names


class TestRoleCoverageIsCombined:
    """v0.59.7 -- a tiled product is judged on its mosaic, not its worst
    tile. The AOI_Lebanon scan measured 4 SRTM tiles at 23.6/26.2/23.6/
    26.2% of the AOI (~100% mosaicked) plus 7 neighbouring tiles at 0%,
    and the worst-first rollup reported DEM as RED / not covered."""

    @staticmethod
    def _tiles(*pcts):
        return [{"name": "tile_%d.tif" % index, "dataset_type": "raster",
                 "coverage_aoi_pct": pct, "crs": {"epsg": 4326},
                 "compatibility": "convertible", "limitations": []}
                for index, pct in enumerate(pcts)]

    def test_tiles_that_mosaic_to_full_coverage_are_not_red(self):
        """The 11 real SRTM tiles: four over the AOI, seven neighbours at 0%.
        Worst-first called this RED; the mosaic plainly is not."""
        records = self._tiles(0.2, 0.2, 0.0, 23.6, 26.2, 0.1,
                              23.6, 26.2, 0.1, 0.0, 0.0)
        status, detail = report._status_role_presence(
            "dem", records, True, False)
        assert status == report.YELLOW
        assert "combined" in detail
        assert "upper bound" in detail

    def test_summed_coverage_never_earns_green(self):
        """Three products over the SAME 40% sum to 120% but cover 40%.
        Overlap is not measured, so a sum can never be GREEN."""
        status, detail = report._status_role_presence(
            "dem", self._tiles(40.0, 40.0, 40.0), True, False)
        assert status == report.YELLOW
        assert "overlap between them is not measured" in detail

    def test_green_requires_one_dataset_that_covers_the_aoi(self):
        status, detail = report._status_role_presence(
            "dem", self._tiles(23.6, 26.2, 95.0), True, False)
        assert status == report.GREEN
        assert "best single dataset" in detail

    def test_coverage_is_not_consulted_without_an_extent(self):
        status, detail = report._status_role_presence(
            "dem", self._tiles(95.0), False, False)
        assert status == report.GREY
        assert "no analysis extent" in detail

    def test_genuinely_partial_coverage_stays_red(self):
        status, _ = report._status_role_presence(
            "dem", self._tiles(20.0, 20.0), True, False)
        assert status == report.RED

    def test_single_dataset_covering_the_aoi_is_green(self):
        status, _ = report._status_role_presence(
            "dem", self._tiles(100.0), True, False)
        assert status == report.GREEN

    def test_partial_single_dataset_is_not_inflated(self):
        status, _ = report._status_role_presence(
            "dem", self._tiles(23.6), True, False)
        assert status == report.RED

    def test_half_covered_role_is_yellow(self):
        status, _ = report._status_role_presence(
            "dem", self._tiles(30.0, 30.0), True, False)
        assert status == report.YELLOW

    def test_clearly_insufficient_role_is_still_red(self):
        status, _ = report._status_role_presence(
            "dem", self._tiles(10.0, 12.0), True, False)
        assert status == report.RED

    def test_unmeasured_coverage_is_not_treated_as_covered(self):
        records = self._tiles(0.0)
        records[0]["coverage_aoi_pct"] = None
        status, _ = report._status_role_presence(
            "dem", records, True, False)
        assert status == report.GREY

    def test_non_spatial_role_is_unaffected(self):
        records = [{"name": "Vehicles_Can.csv", "dataset_type": "table",
                    "coverage_aoi_pct": None, "limitations": []}]
        status, _ = report._status_role_presence(
            "vehicle", records, True, False)
        assert status == report.GREEN


class TestWebMercatorIsFlagged:
    """v0.59.7 -- Web Mercator passes an "is it projected?" test but is not
    measurable: scale factor 1/cos(lat) makes distances ~20% long and areas
    ~45% large at the AOI_Lebanon latitude, biasing slope, speed, isochrones
    and route lengths. It must not read as a clean projected CRS."""

    @staticmethod
    def _rec(crs):
        return {"name": "aoi.shp", "dataset_type": "vector", "crs": crs,
                "compatibility": "native", "limitations": []}

    def test_web_mercator_by_epsg_is_yellow(self):
        status, detail = report._status_crs(
            self._rec({"epsg": 3857, "type": "Projected",
                       "name": "WGS_1984_Web_Mercator_Auxiliary_Sphere"}))
        assert status == report.YELLOW
        assert "UTM" in detail

    def test_esri_legacy_web_mercator_code_is_yellow(self):
        status, _ = report._status_crs(
            self._rec({"epsg": 102100, "type": "Projected", "name": ""}))
        assert status == report.YELLOW

    def test_web_mercator_by_name_without_epsg_is_yellow(self):
        status, _ = report._status_crs(
            self._rec({"epsg": None, "type": "Projected",
                       "name": "WGS_1984_Web_Mercator_Auxiliary_Sphere"}))
        assert status == report.YELLOW

    def test_utm_remains_green(self):
        status, detail = report._status_crs(
            self._rec({"epsg": 32636, "type": "Projected",
                       "name": "WGS_1984_UTM_Zone_36N"}))
        assert status == report.GREEN
        assert detail == "Projected"

    def test_geographic_is_still_yellow_for_its_own_reason(self):
        status, detail = report._status_crs(
            self._rec({"epsg": 4326, "type": "Geographic",
                       "name": "GCS_WGS_1984"}))
        assert status == report.YELLOW
        assert "reprojection" in detail

    def test_non_spatial_dataset_is_unaffected(self):
        record = self._rec({})
        record["dataset_type"] = "table"
        assert report._status_crs(record)[0] == report.GREY


class TestProjectCrsRecommendation:
    """v0.59.7 -- picking ONE project CRS for an AOI whose datasets arrive in
    assorted CRSs. The centroid rule alone mis-picks whenever the AOI
    straddles a UTM zone boundary."""

    def test_single_zone_aoi(self):
        result = cat.recommend_utm_for_extent(35.1, 33.0, 35.9, 34.0)
        assert result["epsg"] == 32636
        assert result["spans_zones"] == [36]
        assert result["share"] == 1.0
        assert result["note"] == ""

    def test_straddling_aoi_reports_every_zone_it_touches(self):
        # The Lebanon field AOI: 35.10 - 37.00 deg E crosses the 36 deg boundary.
        result = cat.recommend_utm_for_extent(35.10, 33.04, 37.00, 35.07)
        assert result["spans_zones"] == [36, 37]
        assert 0.0 < result["share"] < 1.0
        assert "spans UTM zones" in result["note"]

    def test_majority_zone_wins_over_the_centroid(self):
        # 34.0 - 36.4 deg E: 83% in zone 36, but the centroid (35.2) is also in
        # zone 36, so pick a case where they disagree instead --
        # 35.9 - 38.0 deg E is 90% zone 37 while its west edge sits in 36.
        result = cat.recommend_utm_for_extent(35.9, 33.0, 38.0, 34.0)
        assert result["zone"] == 37
        assert result["share"] > 0.9

    def test_southern_hemisphere_gets_a_south_zone(self):
        result = cat.recommend_utm_for_extent(20.0, -30.0, 21.0, -29.0)
        assert result["hemisphere"] == "S"
        assert result["epsg"] == 32734

    def test_swapped_bounds_are_tolerated(self):
        assert (cat.recommend_utm_for_extent(37.0, 35.07, 35.1, 33.04)
                == cat.recommend_utm_for_extent(35.1, 33.04, 37.0, 35.07))

    def test_implausible_input_returns_none(self):
        assert cat.recommend_utm_for_extent("x", 0, 1, 1) is None
        assert cat.recommend_utm_for_extent(0, 0, 400, 1) is None
        assert cat.recommend_utm_for_extent(0, -100, 1, 1) is None

    def test_recommendation_is_never_web_mercator(self):
        """The whole point: the replacement CRS must be a measurable one."""
        for bounds in ((35.1, 33.0, 37.0, 35.0), (-75.0, 40.0, -74.0, 41.0),
                       (139.0, 35.0, 140.0, 36.0)):
            result = cat.recommend_utm_for_extent(*bounds)
            assert result["epsg"] not in (3857, 900913, 102100, 102113)
            assert 32601 <= result["epsg"] <= 32760


# <<< END OF FILE >>>
