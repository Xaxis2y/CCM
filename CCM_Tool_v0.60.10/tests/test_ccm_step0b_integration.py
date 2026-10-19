# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""Portable release-gate tests for the v0.59.6 Step 0b integration."""

import json
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
ROOT = TESTS_DIR.parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from make_fake_data import build  # noqa: E402
from ccm_step0b_intelligence import run_integrated_scan, run_scan  # noqa: E402
from ccm_step0b_integration import Step0bIntegrator  # noqa: E402


VERSION = "0.60.10"


def test_integrated_scan_writes_all_step0b_outputs(tmp_path):
    data_root = tmp_path / "data"
    project = tmp_path / "project"
    build(str(data_root))

    result = run_integrated_scan(
        data_root,
        aoi_path=data_root / "Extent" / "AOI_Lebanon.shp",
        project_folder=project,
    )

    assert result["status"] == "success", result
    assert result["version"] == VERSION
    assert result["catalog"]["ccm_version"] == VERSION
    assert len(result["catalog"]["datasets"]) >= 1

    # v0.60.0 -- single-root architecture: ccm_project.json stays directly
    # in project (== project_root, every other step's load_config() looks
    # for it there); every OTHER Step 0b output now lives in a
    # 02_Scan_Index subfolder instead, kept separate on purpose so scan
    # artifacts never sit next to -- and can't be confused with -- the
    # shared project config. See ccm_step0b_integration.py's report_dir.
    scan_index = project / "02_Scan_Index"
    expected = {
        "catalog_json": scan_index / "ccm_data_catalog.json",
        "html_report": scan_index / "CCM_Data_Intelligence_Report.html",
        "txt_report": scan_index / "CCM_Data_Intelligence_Report.txt",
        "quality_scores_json": scan_index / "ccm_quality_scores.json",
        "fitness_scores_json": scan_index / "ccm_fitness_scores.json",
        "confidence_scores_json": scan_index / "ccm_confidence_scores.json",
        "readiness_scores_json": scan_index / "ccm_readiness_scores.json",
        "recommendations_json": scan_index / "ccm_recommendations.json",
        "recommendations_html": scan_index / "CCM_Recommendations_Report.html",
        "project_config": project / "ccm_project.json",
    }
    for result_key, expected_path in expected.items():
        output_path = Path(result[result_key])
        assert output_path == expected_path
        assert output_path.is_file(), output_path

    with (scan_index / "ccm_quality_scores.json").open(encoding="utf-8") as stream:
        quality = json.load(stream)
    with (scan_index / "ccm_recommendations.json").open(encoding="utf-8") as stream:
        recommendations = json.load(stream)
    assert quality["version"] == VERSION
    assert quality["scores"]
    assert recommendations["version"] == VERSION
    assert set(recommendations["selections"]) >= {"DEM", "Extent", "Vehicle"}


def test_factual_scan_remains_available_as_explicit_legacy_mode(tmp_path):
    data_root = tmp_path / "data"
    build(str(data_root))

    catalog, outputs = run_scan(data_root, write_reports=False)

    assert not catalog.get("error")
    assert catalog["inventory_version"] == VERSION
    assert catalog["ccm_version"] == VERSION
    assert outputs == {}


def test_normalise_dataset_replaces_a_null_name_with_the_path_leaf():
    record = {"name": None, "path": r"C:\\data\\Soil\\sample.tif"}

    normalised = Step0bIntegrator._normalise_dataset(record)

    assert normalised["name"] == "sample.tif"


@pytest.mark.parametrize(
    "required_key",
    [
        "quality_scores_json",
        "fitness_scores_json",
        "confidence_scores_json",
        "readiness_scores_json",
        "recommendations_json",
    ],
)
def test_integrated_result_paths_are_project_local(tmp_path, required_key):
    data_root = tmp_path / "data"
    project = tmp_path / "project"
    build(str(data_root))

    result = run_integrated_scan(data_root, project_folder=project)

    assert result["status"] == "success"
    # v0.60.0 -- scan artifacts live in project/02_Scan_Index/, not
    # directly in project/ (see ccm_step0b_integration.py's report_dir
    # separation; ccm_project.json alone stays at project/ directly).
    assert Path(result[required_key]).parent == project / "02_Scan_Index"


# <<< END OF FILE >>>
