# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""Blocking verifier and release packager for the integrated CCM Tool v0.57."""

import argparse
import ast
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent

# v0.57 post-review "5.1"/"M-5": VERSION and RELEASE_NAME now come from
# ccm_version.py (single source of truth) instead of a literal repeated in
# both this file and build.py, which had already drifted from each other's
# release-file lists once (see "M-5" below and CHANGELOG_v0.57.md).
sys.path.insert(0, str(ROOT))
from ccm_version import VERSION, RELEASE_NAME  # noqa: E402

VERSION_MODULES = [
    "ccm_version.py",
    "ccm_debug.py",
    "ccm_data_audit.py",
    "ccm_coords.py",
    "ccm_data_discovery.py",
    "ccm_data_catalog.py",
    "ccm_data_sources.py",
    "ccm_data_report.py",
    "ccm_step0b_intelligence.py",
    "ccm_isochrone.py",
    "ccm_map_display.py",
    "ccm_mgcp_catalog.py",
    "ccm_obstacle_detect.py",
    "ccm_project_config.py",
    "ccm_reason_map.py",
    "ccm_soil_preprocess.py",
    "ccm_soil_validator.py",
    "ccm_step0_mgcp.py",
    "ccm_step1_setup.py",
    "ccm_step2_mobility.py",
    "ccm_step3_advanced.py",
    "ccm_veg_preprocess.py",
    "ccm_vehicle_compare.py",
    "ccm_waypoints.py",
    "ccm_weather.py",
    "CCM_Data_Scanner_GUI.py",
    "build_exe.py",
    "tests/arcpy_smoke_test_step0.py",
    "tests/arcpy_smoke_test_step1.py",
    "tests/arcpy_smoke_test_step2.py",
    "tests/arcpy_smoke_test_step3.py",
    "tests/arcpy_smoke_test_step0b.py",
    "tests/gui_screenshot.py",
    "tests/make_fake_data.py",
    "tests/test_v057_data_intelligence.py",
]

TOOLBOX_FILENAME = "%s.pyt" % RELEASE_NAME       # was a literal "CCM_Tool_v0.57.pyt"

CODE_FILES = VERSION_MODULES + [
    "build.py",
    "bump_version.py",
    # v0.57 post-review "5.1"/"M-5" follow-up: package_ccm_v057.py itself is
    # syntax/marker-checked here like every other release file, but is NOT
    # in VERSION_MODULES -- it imports VERSION from ccm_version.py rather
    # than defining its own literal `VERSION = "0.57"` line, so the
    # version_pattern regex check in static_checks() would always fail
    # against it (that regex is what previously caught it, when this file
    # briefly ended up double-counted: present in VERSION_MODULES without
    # the literal line the check requires).
    "package_ccm_v057.py",
    TOOLBOX_FILENAME,
    "tests/test_ccm.py",
    "tests/test_v050.py",
]

REQUIRED_FILES = CODE_FILES + [
    "CCM_Data_Scanner.bat",
    "CCM_anaconda.bat",
    "RUN_ARCGIS_SMOKE_TEST.bat",
    "RUN_DATA_SCAN.bat",
    "RUN_V057_TESTS.bat",
    "README.md",
    "QUICK_START.md",
    "QUICK_START.html",
    "CHANGELOG_v0.57.md",
    "PROJECT_STATUS.md",
    "TASKS.md",
    "%s.pyt.xml" % RELEASE_NAME,          # was a literal "CCM_Tool_v0.57.pyt.xml"
    "%s_User_Manual.docx" % RELEASE_NAME, # was a literal "CCM_Tool_v0.57_User_Manual.docx"
    "TOOLBOX_INTEGRATION.md",
    "VERSION.txt",
    "ccm.ico",
]

EXCLUDED_PARTS = {
    "__pycache__", ".pytest_cache", "verification_artifacts",
    "verification_logs", "_pytest_runtime", "build", "dist",
}


class VerificationError(RuntimeError):
    """Raised when a release-blocking verification step fails."""


def log(message):
    print("[verify] %s" % message, flush=True)


def atomic_write_text(path, text):
    """Write UTF-8 text by replacing a complete temporary file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=".ccm_package_", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def run_command(label, command, artifact_dir):
    """Run one verification command, persist output, and block on failure."""
    log("Running %s" % label)
    result = subprocess.run(
        command, cwd=str(ROOT), stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8",
        errors="replace", env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
        check=False)
    output = result.stdout or ""
    artifact_path = Path(artifact_dir) / (label.replace(" ", "_") + ".log")
    atomic_write_text(artifact_path, output)
    if output.strip():
        print(output.rstrip(), flush=True)
    if result.returncode:
        raise VerificationError(
            "%s failed with exit code %d; see %s" %
            (label, result.returncode, artifact_path))
    log("%s passed" % label)


def static_checks():
    """Validate the release structure without importing GIS dependencies."""
    missing = [name for name in REQUIRED_FILES if not (ROOT / name).is_file()]
    if missing:
        raise VerificationError("Missing release file(s): %s" % ", ".join(missing))
    if (ROOT / "ccm_data_quality.py").exists():
        raise VerificationError(
            "ccm_data_quality.py is out of scope and must not ship in v0.57")

    version_pattern = re.compile(
        r'^VERSION\s*=\s*["\']%s["\'](?:\s*#.*)?$' % re.escape(VERSION),
        re.MULTILINE)
    for relative in CODE_FILES:
        path = ROOT / relative
        source = path.read_text(encoding="utf-8")
        try:
            ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            raise VerificationError("Syntax error in %s: %s" %
                                    (relative, exc)) from exc
        marker_exempt = {"build.py", "tests/test_ccm.py", "tests/test_v050.py"}
        if (relative.endswith((".py", ".pyt"))
                and relative not in marker_exempt
                and not source.rstrip().endswith("# <<< END OF FILE >>>")):
            raise VerificationError("Missing end marker: %s" % relative)
        if relative in VERSION_MODULES and not version_pattern.search(source):
            raise VerificationError(
                "VERSION is missing or not %s in %s" % (VERSION, relative))

    readme = (ROOT / "README.md").read_text(
        encoding="utf-8")
    integration = (ROOT / "TOOLBOX_INTEGRATION.md").read_text(
        encoding="utf-8")
    if "data intelligence" not in readme.lower() or "factual inventory" not in readme.lower():
        raise VerificationError("README does not state the integrated factual scope")
    if "must not" not in integration.lower() or "auto" not in integration.lower():
        raise VerificationError("Integration guide lacks the no-auto-selection rule")
    log("Static structure, syntax, scope, and version checks passed")


def data_calibration_audit():
    """
    v0.57 post-review "5.3": soil_rci.csv and Vehicle_Data/Vehicles_Can.csv
    are analyst-editable calibration data, not code. ccm_data_audit.py checks
    them for internal consistency (RCI monotonicity, VCI ordering, USCS code
    recognition, duplicate rows) without needing arcpy. A bad calibration
    edit is a release-blocking problem the same way a missing file is.
    """
    sys.path.insert(0, str(ROOT))
    import ccm_data_audit as _audit
    problems = _audit.audit_all()
    if problems:
        raise VerificationError(
            "Data calibration audit found %d problem(s):\n  - %s" %
            (len(problems), "\n  - ".join(problems)))
    log("Data calibration audit (soil_rci.csv, Vehicles_Can.csv, USCS "
        "cross-reference) passed")


def validate_end_to_end(artifact_dir):
    """Build real fixtures, scan them, and inspect all output artifacts."""
    artifact_dir = Path(artifact_dir)
    fake_root = artifact_dir / "fake_data"
    scan_output = artifact_dir / "scan_output"
    scan_output.mkdir(parents=True, exist_ok=True)

    run_command(
        "fixture_generation",
        [sys.executable, "-B", str(ROOT / "tests" / "make_fake_data.py"),
         str(fake_root)], artifact_dir)
    aoi = fake_root / "Extent" / "AOI_Lebanon.shp"
    run_command(
        "end_to_end_scan",
        [sys.executable, "-B", str(ROOT / "ccm_step0b_intelligence.py"),
         "--data-root", str(fake_root), "--aoi", str(aoi),
         "--out", str(scan_output), "--quiet"], artifact_dir)

    json_path = scan_output / "ccm_data_catalog.json"
    html_path = scan_output / "CCM_Data_Intelligence_Report.html"
    text_path = scan_output / "CCM_Data_Intelligence_Report.txt"
    project_path = scan_output / "ccm_project.json"
    missing = [str(path) for path in (json_path, html_path, text_path,
                                      project_path) if not path.is_file()]
    if missing:
        raise VerificationError("End-to-end output missing: %s" % ", ".join(missing))

    with json_path.open(encoding="utf-8") as stream:
        catalog = json.load(stream)
    if catalog.get("ccm_version") != VERSION:
        raise VerificationError("End-to-end catalog version mismatch")
    if catalog.get("error"):
        raise VerificationError("End-to-end catalog contains an error")
    if "readiness" in catalog or "quality_version" in catalog:
        raise VerificationError("Out-of-scope scoring output found in catalog")
    if (catalog.get("stats") or {}).get("datasets_catalogued", 0) < 1:
        raise VerificationError("End-to-end catalog contains no datasets")
    for bucket in (catalog.get("roles") or {}).values():
        for record in bucket.get("records") or []:
            if any(record.get(key) is not None
                   for key in ("quality", "fitness", "confidence")):
                raise VerificationError("Reserved score field is not null")

    with project_path.open(encoding="utf-8") as stream:
        project = json.load(stream)
    if project.get("data_catalog_json") != str(json_path):
        raise VerificationError("ccm_project.json catalog link is incorrect")
    if "readiness" in project:
        raise VerificationError("Out-of-scope readiness key found in project config")
    log("End-to-end outputs and factual schema passed validation")


def verify(artifact_dir):
    """Run all release-blocking checks."""
    artifact_dir = Path(artifact_dir).resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    log("CCM Tool v%s integrated verification" % VERSION)
    log("Python: %s" % sys.executable)
    log("Artifacts: %s" % artifact_dir)
    static_checks()
    data_calibration_audit()

    if importlib.util.find_spec("pyflakes") is None:
        raise VerificationError(
            "pyflakes is not installed; run CCM_anaconda.bat")
    if importlib.util.find_spec("pytest") is None:
        raise VerificationError(
            "pytest is not installed; run CCM_anaconda.bat")

    run_command(
        "pyflakes",
        [sys.executable, "-B", "-m", "pyflakes"] +
        [str(ROOT / name) for name in CODE_FILES
         if name not in {"tests/test_ccm.py", "tests/test_v050.py"}], artifact_dir)
    run_command(
        "pytest",
        [sys.executable, "-B", "-m", "pytest",
         str(ROOT / "tests" / "test_ccm.py"),
         str(ROOT / "tests" / "test_v050.py"),
         str(ROOT / "tests" / "test_v057_data_intelligence.py"), "-q",
         "-p", "no:cacheprovider", "--basetemp",
         str(artifact_dir / "pytest_tmp")], artifact_dir)
    validate_end_to_end(artifact_dir)
    atomic_write_text(
        artifact_dir / "VERIFICATION_PASSED.txt",
        "CCM Data Intelligence v%s verification passed at %s\n" %
        (VERSION, datetime.datetime.now().isoformat(timespec="seconds")))
    log("All blocking verification checks passed")


def release_files(include_version=True):
    """Yield sorted package files while excluding generated artifacts."""
    files = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if any(part in EXCLUDED_PARTS or part.startswith("_pytest_")
               for part in relative.parts):
            continue
        if path.suffix.lower() in {".pyc", ".pyo", ".zip"}:
            continue
        if path.name.startswith(".ccm_") and path.suffix == ".tmp":
            continue
        if not include_version and relative.as_posix() == "VERSION.txt":
            continue
        files.append((relative, path))
    yield from sorted(files, key=lambda item: item[0].as_posix().lower())


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_version_manifest():
    """Write the English release manifest with SHA-256 checksums."""
    lines = [
        "CCM Tool v%s" % VERSION,
        "Release type: integrated ArcGIS toolbox and factual Data Intelligence scan",
        "Generated: %s" % datetime.datetime.now().isoformat(timespec="seconds"),
        "Scope: Steps 0-4 plus Step 0b factual inventory; no automatic "
        "source selection, scoring, substitution, Confidence, or Readiness.",
        "",
        "SHA-256 file manifest",
        "----------------------",
    ]
    for relative, path in release_files(include_version=False):
        lines.append("%s  %10d  %s" %
                     (sha256_file(path), path.stat().st_size,
                      relative.as_posix()))
    atomic_write_text(ROOT / "VERSION.txt", "\n".join(lines) + "\n")
    log("VERSION.txt updated")


def build_zip(output_path):
    """Build an atomic ZIP and write SHA-256/MD5 sidecar checksums."""
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=".%s_" % RELEASE_NAME, suffix=".zip.tmp",
        dir=str(output_path.parent))
    os.close(fd)
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED,
                             allowZip64=True) as archive:
            for relative, path in release_files(include_version=True):
                arcname = "%s/%s" % (RELEASE_NAME, relative.as_posix())
                archive.write(str(path), arcname)
        os.replace(temporary, output_path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise

    payload = output_path.read_bytes()
    sha256 = hashlib.sha256(payload).hexdigest()
    md5 = hashlib.md5(payload).hexdigest()  # nosec - compatibility checksum
    atomic_write_text(str(output_path) + ".sha256",
                      "%s  %s\n" % (sha256, output_path.name))
    atomic_write_text(str(output_path) + ".md5",
                      "%s  %s\n" % (md5, output_path.name))
    log("Package: %s" % output_path)
    log("SHA-256: %s" % sha256)
    log("MD5: %s" % md5)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Verify and package CCM Data Intelligence v%s" % VERSION)
    parser.add_argument(
        "--verify-only", action="store_true",
        help="Run blocking checks without updating the manifest or ZIP.")
    parser.add_argument(
        "--artifact-dir",
        help="Folder for pytest, fixture, scan, and command logs.")
    parser.add_argument(
        "--output",
        help="ZIP path. Defaults beside this working folder.")
    args = parser.parse_args(argv)

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    artifact_dir = (Path(args.artifact_dir) if args.artifact_dir else
                    ROOT / "verification_artifacts" / (stamp + "_package"))
    output = (Path(args.output) if args.output else
              ROOT.parent / (RELEASE_NAME + ".zip"))
    try:
        verify(artifact_dir)
        if not args.verify_only:
            write_version_manifest()
            build_zip(output)
    except (VerificationError, OSError, ValueError, zipfile.BadZipFile) as exc:
        print("[verify] FAILED: %s" % exc, file=sys.stderr, flush=True)
        return 1
    log("Verification-only run complete" if args.verify_only
        else "Verified release package complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# <<< END OF FILE >>>
