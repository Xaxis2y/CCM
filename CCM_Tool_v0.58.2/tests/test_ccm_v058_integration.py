# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""Portable release-gate tests for the v0.58.2 Step 0b integration."""

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


VERSION = "0.58.2"


def test_integrated_scan_writes_all_v0582_outputs(tmp_path):
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

    expected = {
        "catalog_json": "ccm_data_catalog.json",
        "html_report": "CCM_Data_Intelligence_Report.html",
        "txt_report": "CCM_Data_Intelligence_Report.txt",
        "quality_scores_json": "ccm_quality_scores.json",
        "fitness_scores_json": "ccm_fitness_scores.json",
        "confidence_scores_json": "ccm_confidence_scores.json",
        "readiness_scores_json": "ccm_readiness_scores.json",
        "recommendations_json": "ccm_recommendations.json",
        "recommendations_html": "CCM_Recommendations_Report.html",
        "project_config": "ccm_project.json",
    }
    for result_key, filename in expected.items():
        output_path = Path(result[result_key])
        assert output_path == project / filename
        assert output_path.is_file(), output_path

    with (project / "ccm_quality_scores.json").open(encoding="utf-8") as stream:
        quality = json.load(stream)
    with (project / "ccm_recommendations.json").open(encoding="utf-8") as stream:
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
    assert Path(result[required_key]).parent == project


# <<< END OF FILE >>>
