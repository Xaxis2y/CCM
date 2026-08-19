# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""Licensed ArcGIS/ArcPy smoke test for CCM Tool v0.57 Step 0b."""

import argparse
import datetime
import json
from pathlib import Path
import sys


VERSION = "0.58.2"  # v0.58.2 -- bumped by bump_version.py from v0.57. Review this line's comment.
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for path in (str(ROOT), str(HERE)):
    if path not in sys.path:
        sys.path.insert(0, path)

import ccm_data_catalog as catalog_engine  # noqa: E402
import ccm_step0b_intelligence as step0b  # noqa: E402
import make_fake_data  # noqa: E402


def log(message):
    print("[ArcPy smoke] %s" % message, flush=True)


def source_state(root):
    return {
        str(path.relative_to(root)): (path.stat().st_size,
                                      path.stat().st_mtime_ns)
        for path in root.rglob("*") if path.is_file()
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Licensed ArcPy smoke test for CCM v%s" % VERSION)
    parser.add_argument("--artifact-dir", required=True)
    args = parser.parse_args(argv)

    artifact = Path(args.artifact_dir).resolve()
    artifact.mkdir(parents=True, exist_ok=True)
    data_root = artifact / "arcpy_source_data"
    project = artifact / "arcpy_scan_output"
    project.mkdir(parents=True, exist_ok=True)

    log("CCM Tool v%s Step 0b ArcPy smoke" % VERSION)
    log("Python: %s" % sys.executable)
    try:
        import arcpy
    except Exception as exc:
        raise RuntimeError(
            "ArcPy could not initialize. Open/sign in to ArcGIS Pro and "
            "rerun RUN_ARCGIS_SMOKE_TEST.bat. Original error: %s" % exc)
    product = arcpy.ProductInfo()
    log("ArcGIS product: %s" % product)
    if not product or str(product).lower() in {
            "notinitialized", "notlicensed", "unavailable"}:
        raise RuntimeError(
            "ArcGIS product license is not initialized. Open/sign in to "
            "ArcGIS Pro, then run this script again.")

    make_fake_data.build(str(data_root))
    gdb = data_root / "Hydro" / "HydroLayers.gdb"
    arcpy.management.CreateFileGDB(str(gdb.parent), gdb.name)
    spatial_ref = arcpy.SpatialReference(32636)
    arcpy.management.CreateFeatureclass(
        str(gdb), "Rivers_GDB", "POLYLINE", spatial_reference=spatial_ref)
    arcpy.management.CreateFeatureclass(
        str(gdb), "Lakes_GDB", "POLYGON", spatial_reference=spatial_ref)

    before = source_state(data_root)
    catalog_engine.set_arcpy_enabled(True)
    aoi = data_root / "Extent" / "AOI_Lebanon.shp"
    catalog, outputs = step0b.run_scan(
        str(data_root), aoi_path=str(aoi), project_folder=str(project),
        write_reports=True, log=log)
    after = source_state(data_root)

    if catalog.get("error"):
        raise RuntimeError(catalog["error"])
    if catalog.get("backend") != "arcpy":
        raise RuntimeError(
            "Expected ArcPy backend, found %s" % catalog.get("backend"))
    if before != after:
        raise RuntimeError("The scan changed one or more source files")
    if set(outputs) != {"json", "html", "text"}:
        raise RuntimeError("Expected JSON, HTML, and text outputs")
    if not all(Path(path).is_file() for path in outputs.values()):
        raise RuntimeError("One or more report outputs are missing")

    hydro_records = catalog["roles"][catalog_engine.ROLE_HYDRO]["records"]
    gdb_names = {record["name"] for record in hydro_records
                 if str(record.get("path", "")).startswith(str(gdb))}
    if gdb_names != {"Rivers_GDB", "Lakes_GDB"}:
        raise RuntimeError(
            "File-geodatabase layers were not enumerated correctly: %s" %
            sorted(gdb_names))
    if "readiness" in catalog:
        raise RuntimeError("Out-of-scope Readiness output was created")

    with open(outputs["json"], encoding="utf-8") as stream:
        written = json.load(stream)
    if written.get("ccm_version") != VERSION:
        raise RuntimeError("Written catalog version is incorrect")

    passed = artifact / "ARCPY_SMOKE_PASSED.txt"
    passed.write_text(
        "CCM v%s ArcPy smoke test passed at %s\n" %
        (VERSION, datetime.datetime.now().isoformat(timespec="seconds")),
        encoding="utf-8")
    log("PASS: ArcPy metadata, GDB enumeration, outputs, and source safety")
    log("Artifact: %s" % passed)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("[ArcPy smoke] FAILED: %s" % exc, file=sys.stderr, flush=True)
        sys.exit(1)

# <<< END OF FILE >>>
