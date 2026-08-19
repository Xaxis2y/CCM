# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""Regression tests for the integrated CCM Tool v0.57 Data Intelligence patch.

The suite intentionally tests inventory facts only.  Quality, Fitness,
Confidence, Readiness, source ranking, and automatic substitution remain
outside this integration release and therefore are not implemented or tested
here.
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
import package_ccm_v057 as packager  # noqa: E402
import make_fake_data as fake  # noqa: E402


VERSION = "0.57"
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

    def test_scoring_module_is_not_shipped(self):
        assert not (ROOT / "ccm_data_quality.py").exists()

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

    def test_mismatched_epsg_never_gets_a_coverage_number(self, data_root):
        candidate = next(c for c in cat.deep_scan(str(data_root))
                         if c["name"] == "DEM_10m.tif")
        aoi = {"extent": list(fake.AOI_BBOX),
               "crs": {"epsg": 4326, "type": "Geographic",
                       "name": "WGS 84"}}
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
        assert payload["ccm_version"] == EXPECTED_VERSION
        assert "readiness" not in payload

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
        packaged = [relative for relative, _path in packager.release_files()]
        assert not any(part.startswith("_pytest_")
                       for relative in packaged for part in relative.parts)


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

# <<< END OF FILE >>>
