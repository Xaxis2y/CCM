# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
r"""
ccm_step0b_intelligence.py -- CCM Step 0b: Data Intelligence Scan
==================================================================
Updated for the integrated v0.60.4 release.

Two entry points, one engine:

  1. ``CCMDataIntelligenceTool``  -- an ArcGIS Pro Python-toolbox tool.
     Register it in the .pyt alongside Steps 0-4.

  2. ``main()``  -- a standalone command-line runner that needs NO ArcGIS.
     Because every metadata probe in ``ccm_data_catalog`` degrades to pure
     Python header parsing, the whole scan runs in a plain conda environment:

         python ccm_step0b_intelligence.py --data-root "D:\Projects\DATA"
         python ccm_step0b_intelligence.py --data-root "D:\DATA" ^
                --aoi "D:\DATA\Extent\aoi.shp" --out "D:\Projects\Lebanon"

     Running it inside the ArcGIS Pro conda environment (so arcpy IS
     importable) gives richer measured metadata, but it is not required to get
     a useful factual inventory.

The default v0.60.4 workflow produces
------------------------------------
    ccm_data_catalog.json              full machine-readable inventory
    CCM_Data_Intelligence_Report.html  styled report for reading/archiving
    CCM_Data_Intelligence_Report.txt   plain-text copy of the console report
    ccm_quality_scores.json            dataset quality scores
    ccm_fitness_scores.json            role fitness evaluations
    ccm_confidence_scores.json         per-role and model confidence
    ccm_readiness_scores.json          readiness status pending Step 1
    ccm_recommendations.json           reviewable role recommendations
    CCM_Recommendations_Report.html    recommendation review report

All three land in the PROJECT folder (never next to the toolbox).  When a
project folder is supplied and ``ccm_project_config`` is importable, the scan
also records ``data_root`` and ``data_catalog_json`` in ``ccm_project.json``
so Step 1 can reuse the catalog instead of re-scanning.

NO NETWORK CALLS.  A scan is offline by definition.
"""

import os
import sys
import json
import argparse
import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

VERSION = "0.60.8"  # v0.59.2 -- integrated factual inventory and scoring workflow.

# --- engine modules (required) ----------------------------------------------
import ccm_data_catalog as _cat          # noqa: E402
import ccm_data_report as _report        # noqa: E402

# --- optional companions ----------------------------------------------------
try:
    import ccm_project_config as _cfg
except Exception:                                        # pragma: no cover
    _cfg = None

try:
    import arcpy
except Exception:                                        # pragma: no cover
    arcpy = None


# ===========================================================================
# Shared engine
# ===========================================================================

def run_scan(data_root, aoi_path=None, project_folder=None,
             write_reports=True, log=None):
    """
    Run a complete Data Intelligence scan.

    Parameters
    ----------
    data_root      : folder holding whatever GIS data the analyst has.
    aoi_path       : optional analysis-extent FC/shapefile -- enables coverage
                     percentages and the CRS recommendation.
    project_folder : optional destination for the three report files.
    write_reports  : set False to compute the catalog without writing files.
    log            : optional callable(str) used for progress lines.

    Returns
    -------
    (catalog_dict, outputs_dict)  where outputs_dict maps
    "json"/"html"/"text" to written paths (empty when write_reports is False).
    """
    def _log(msg):
        if log:
            try:
                log(msg)
            except Exception:
                pass

    _log("[CCM 0b] Scanning data root: %s" % data_root)
    catalog = _cat.build_catalog(data_root, aoi_path=aoi_path,
                                 project_folder=project_folder)
    if catalog.get("error"):
        _log("[CCM 0b] %s" % catalog["error"])
        return catalog, {}

    st = catalog.get("stats") or {}
    _log("[CCM 0b] %s file(s) inspected, %s dataset(s) catalogued, "
         "%s unclassified, %s duplicate group(s)."
         % (st.get("files_scanned", 0), st.get("datasets_catalogued", 0),
            st.get("unclassified", 0), st.get("duplicate_groups", 0)))

    catalog["inventory_version"] = VERSION
    catalog["ccm_version"] = VERSION
    _log("[CCM 0b] Factual inventory complete. No Quality, Fitness, "
         "Confidence, Readiness, or automatic selection was calculated.")

    outputs = {}
    if write_reports and project_folder:
        outputs = _report.write_all(catalog, project_folder)
        for kind, path in outputs.items():
            _log("[CCM 0b] %-4s report: %s" % (kind.upper(), path))
        _save_project_keys(project_folder, data_root, outputs.get("json"),
                           catalog, _log)
    elif write_reports and not project_folder:
        _log("[CCM 0b] No project folder supplied -- reports not written. "
             "(The console/message report below is the full result.)")
    return catalog, outputs


def run_integrated_scan(data_root, aoi_path=None, project_folder=None,
                        soil_rci_csv=None, vehicles_can_csv=None, log=None):
    """Run the complete v0.60.4 catalog, scoring, and recommendation flow.

    The import is deliberately lazy so the original factual ``run_scan``
    remains usable by lightweight scripts and legacy tests without importing
    the optional scoring engines at module load time.
    """
    from ccm_step0b_integration import Step0bIntegrator

    integrator = Step0bIntegrator(
        data_root,
        aoi_path=aoi_path,
        project_folder=project_folder,
        soil_rci_csv=soil_rci_csv,
        vehicles_can_csv=vehicles_can_csv,
        log_callback=log,
    )
    return integrator.run(verbose=log is not None, log_callback=log)


def _save_project_keys(project_folder, data_root, catalog_json, catalog, _log):
    """
    Record the scan in ccm_project.json (additive keys only).

    Uses ccm_project_config when available so the existing _DEFAULTS merge
    semantics are preserved; falls back to a minimal direct merge otherwise.
    """
    fields = {
        "data_root": str(data_root),
        "data_catalog_json": str(catalog_json) if catalog_json else None,
    }
    if _cfg is not None:
        try:
            _cfg.save_config(project_folder, **fields)
            _log("[CCM 0b] ccm_project.json updated (data_root, "
                 "data_catalog_json).")
            return
        except TypeError:
            # Older config module without these keys in _DEFAULTS: merge by hand.
            pass
        except Exception as exc:
            _log("[CCM 0b] ccm_project.json not updated: %s" % exc)
            return
    path = os.path.join(str(project_folder), "ccm_project.json")
    try:
        existing = {}
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as fh:
                existing = json.load(fh)
        existing.update(fields)
        existing["last_updated"] = datetime.datetime.now().isoformat(
            timespec="seconds")
        _cat.atomic_write_text(
            path, json.dumps(existing, indent=2, ensure_ascii=False) + "\n")
        _log("[CCM 0b] ccm_project.json updated (direct merge).")
    except Exception as exc:
        _log("[CCM 0b] ccm_project.json not updated: %s" % exc)


def _resolve_data_root(project_root):
    """
    v0.60.0 -- Resolve the folder Step 0b should actually scan from a chosen
    Project Root Folder. If <project_root>\01_Input_Data exists and has
    something in it (the layout Step 0 / ccm_project_init.py create), that's
    the real data root -- project_root itself also holds 02_Scan_Index,
    03_Project.gdb and ccm_project.json, which are not source data. Falls
    back to project_root itself when 01_Input_Data doesn't exist yet (e.g.
    Step 0b run standalone, before Step 0), so the scan still finds data
    placed directly in project_root.
    """
    if not project_root:
        return project_root
    candidate = os.path.join(project_root, "01_Input_Data")
    try:
        if os.path.isdir(candidate) and any(os.scandir(candidate)):
            return candidate
    except Exception:
        pass
    return project_root


# ===========================================================================
# ArcGIS Pro tool
# ===========================================================================

class CCMDataIntelligenceTool(object):
    """Step 0b -- Data Intelligence Scan.

    Point CCM at one folder containing whatever GIS data you have.  The tool
    identifies every dataset, measures available metadata, calculates the
    v0.60.4 quality/fitness/confidence outputs, and creates reviewable role
    recommendations. It never changes source data or silently replaces a
    user's selection.

    Nothing is modified: this is a read-only assessment.
    """

    def __init__(self):
        self.label = "Step 0b.  Data Intelligence Scan"
        self.description = (
            "Scan one folder of GIS data and report what CCM found, measured "
            "metadata, quality and fitness scores, confidence, readiness, "
            f"and reviewable recommendations. This v{VERSION} tool does not "
            "modify source data or automatically replace a selection. "
            "Read-only -- no data is modified."
        )
        self.canRunInBackground = False

    # ---------------------------------------------------------------- params
    def getParameterInfo(self):
        # v0.60.0 -- single-root architecture: this is now the SAME
        # Project Root Folder every other step uses, not a separate "data
        # root". execute() scans <project_root>\01_Input_Data if that
        # subfolder already has data in it (the layout Step 0 /
        # ccm_project_init.py create), and falls back to scanning
        # project_root directly otherwise -- so Step 0b still works
        # standalone, as the very first tool someone runs, against a folder
        # with no CCM structure yet.
        p_root = arcpy.Parameter(
            displayName="Project Root Folder  (the one folder for this "
                        "whole CCM project)",
            name="project_root",
            datatype="DEFolder",
            parameterType="Required",
            direction="Input",
        )

        p_aoi = arcpy.Parameter(
            displayName="Analysis Extent  (optional -- enables coverage %% "
                        "and the recommended CRS)",
            name="aoi_fc",
            datatype="DEFeatureClass",
            parameterType="Optional",
            direction="Input",
        )

        # v0.60.0 -- almost never needs to be set: defaults to Project
        # Root Folder above (so ccm_project.json and the 02_Scan_Index
        # reports land where every other step expects them). Only override
        # this for an advanced / non-standard layout.
        p_proj = arcpy.Parameter(
            displayName="Project Folder override  (advanced -- defaults to "
                        "Project Root Folder above)",
            name="project_folder",
            datatype="DEFolder",
            parameterType="Optional",
            direction="Input",
        )

        p_open = arcpy.Parameter(
            displayName="Open the HTML report when finished",
            name="open_report",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input",
        )
        p_open.value = True

        p_out = arcpy.Parameter(
            displayName="Data Catalog JSON",
            name="catalog_json",
            datatype="DEFile",
            parameterType="Derived",
            direction="Output",
        )

        return [p_root, p_aoi, p_proj, p_open, p_out]

    def isLicensed(self):
        return True

    # -------------------------------------------------------------- messages
    def updateParameters(self, parameters):
        # Deliberately empty: all probing happens at execute time so the
        # dialog never stalls while a large folder is walked.
        return

    def updateMessages(self, parameters):
        p_root = parameters[0]
        p_aoi = parameters[1]

        if p_root.value:
            root = str(p_root.valueAsText)
            if not os.path.isdir(root):
                p_root.setErrorMessage("Folder not found: %s" % root)
            else:
                # v0.60.0 -- check the folder Step 0b will actually scan
                # (01_Input_Data under root, once that layout exists), not
                # root itself -- root now also legitimately contains
                # 02_Scan_Index / 03_Project.gdb / ccm_project.json, none of
                # which should trip an "empty folder" warning.
                effective_root = _resolve_data_root(root)
                try:
                    if not any(os.scandir(effective_root)):
                        p_root.setWarningMessage(
                            "No data found yet under this project root "
                            "(checked %s).  Add your data folders there -- "
                            "DEM / Soil / Vegetation / Hydro / MGCP / Vehicle "
                            "-- then re-run the scan." % effective_root)
                except Exception:
                    pass

        if p_aoi.value and not p_aoi.hasError():
            try:
                d = arcpy.Describe(p_aoi.valueAsText)
                if d.spatialReference.type == "Geographic":
                    p_aoi.setWarningMessage(
                        "The Analysis Extent uses a Geographic CRS (%s).\n\n"
                        "The scan will still run and will recommend a UTM "
                        "zone, but CCM itself requires a Projected CRS before "
                        "Step 1.  See User Manual Section 3.4."
                        % d.spatialReference.name)
                elif d.shapeType != "Polygon":
                    p_aoi.setWarningMessage(
                        "The Analysis Extent is a %s feature class; a Polygon "
                        "is expected.  Coverage percentages may be "
                        "meaningless." % d.shapeType)
            except Exception:
                pass

    # --------------------------------------------------------------- execute
    def execute(self, parameters, messages):
        project_root = parameters[0].valueAsText
        aoi_path = parameters[1].valueAsText
        # v0.60.0 -- single-root architecture: scan
        # <project_root>\01_Input_Data when it already has data in it, else
        # project_root itself (see _resolve_data_root() above).
        # project_folder defaults to project_root so ccm_project.json /
        # 02_Scan_Index land where every other step expects them; the
        # Project Folder override parameter still lets an advanced user
        # redirect just the reports.
        data_root = _resolve_data_root(project_root)
        project_folder = parameters[2].valueAsText or project_root
        open_report = bool(parameters[3].value)

        def _log(msg):
            arcpy.AddMessage(msg)

        arcpy.AddMessage("=" * 70)
        arcpy.AddMessage("  CCM Step 0b -- Data Intelligence Scan  v%s"
                         % VERSION)
        arcpy.AddMessage("=" * 70)

        result = run_integrated_scan(
            data_root,
            aoi_path=aoi_path,
            project_folder=project_folder,
            log=_log,
        )

        if result.get("status") != "success":
            arcpy.AddError(result.get("error", "Step 0b integration failed."))
            return

        catalog = result.get("catalog") or {}
        outputs = result

        # Full report into the geoprocessing message pane.
        for line in _report.render_text(catalog):
            arcpy.AddMessage(line)

        for role in catalog.get("missing_roles") or []:
            label = _cat.ROLE_LABELS.get(role, role)
            impact = _report.MISSING_IMPACTS.get(role, "Role is not represented.")
            arcpy.AddWarning("MISSING %s -- %s" % (label, impact))

        if outputs.get("json"):
            parameters[4].value = outputs["json"]
        elif outputs.get("catalog_json"):
            parameters[4].value = outputs["catalog_json"]

        html_report = outputs.get("html") or outputs.get("html_report")
        if open_report and html_report:
            try:
                os.startfile(html_report)          # noqa: S606 (Windows)
            except Exception:
                arcpy.AddMessage("Open the report manually: %s" % html_report)

        arcpy.AddMessage("")
        arcpy.AddMessage("CCM Step 0b integrated scan complete.")
        arcpy.AddMessage("Review the factual inventory and recommendation "
                         "report before running Step 1.")

    def postExecute(self, parameters):
        return


# ===========================================================================
# Standalone CLI  (no ArcGIS required)
# ===========================================================================

def main(argv=None):
    """Command-line entry point.  Returns a process exit code."""
    ap = argparse.ArgumentParser(
        prog="ccm_step0b_intelligence",
        description="CCM Step 0b -- inventory, score, and recommend inputs "
                    "for a folder of GIS data. Runs with or without ArcGIS.")
    ap.add_argument("--data-root", "-d", required=True,
                    help="Folder containing your source data.")
    ap.add_argument("--aoi", "-a", default=None,
                    help="Analysis extent polygon (shapefile / FC). Enables "
                         "coverage %% and the CRS recommendation.")
    ap.add_argument("--out", "-o", default=None,
                    help="Project folder for the JSON / HTML / TXT reports. "
                         "Defaults to the data root itself when omitted.")
    ap.add_argument("--no-reports", action="store_true",
                    help="Use the factual-only scan and write no files.")
    ap.add_argument("--factual-only", action="store_true",
                    help="Run the legacy factual inventory without scoring.")
    ap.add_argument("--quiet", "-q", action="store_true",
                    help="Suppress progress lines (report still printed).")
    ap.add_argument("--json-only", action="store_true",
                    help="Print the catalog as JSON to stdout and nothing "
                         "else (for scripting).")
    ap.add_argument("--version", action="version",
                    version="CCM Data Intelligence v%s" % VERSION)
    args = ap.parse_args(argv)

    data_root = os.path.abspath(os.path.expanduser(args.data_root))
    aoi = os.path.abspath(os.path.expanduser(args.aoi)) if args.aoi else None
    if args.no_reports:
        out_folder = None
    elif args.out:
        out_folder = os.path.abspath(os.path.expanduser(args.out))
    else:
        # v0.60.0 -- no longer defaults to the data root's PARENT (removed to
        # match the same fix in Step0bIntegrator / ccm_step0b_integration.py);
        # falls back to the data root itself, at least a location the caller
        # actually pointed at.
        out_folder = data_root

    def _log(msg):
        if not args.quiet and not args.json_only:
            print(msg)

    if not args.json_only:
        print("=" * 78)
        print("  CCM Step 0b -- Integrated Data Intelligence   v%s" % VERSION)
        print("=" * 78)

    if args.factual_only or args.no_reports:
        catalog, outputs = run_scan(
            data_root,
            aoi_path=aoi,
            project_folder=out_folder,
            write_reports=not args.no_reports and not args.json_only,
            log=_log,
        )
        result = {"status": "error" if catalog.get("error") else "success",
                  "catalog": catalog, **outputs}
    else:
        result = run_integrated_scan(
            data_root,
            aoi_path=aoi,
            project_folder=out_folder,
            log=_log if not args.json_only else None,
        )
        catalog = result.get("catalog") or {}
        outputs = result

    if args.json_only:
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        return 0 if result.get("status") == "success" else 2

    if result.get("status") != "success" or catalog.get("error"):
        print("\nERROR: %s" % (result.get("error") or catalog.get("error")))
        return 2

    print()
    for line in _report.render_text(catalog):
        print(line)

    if outputs:
        print("-" * 78)
        print("REPORTS WRITTEN")
        for key in (
            "html_report", "catalog_json", "txt_report", "quality_scores_json",
            "fitness_scores_json", "confidence_scores_json",
            "readiness_scores_json", "recommendations_json", "recommendations_html",
        ):
            if outputs.get(key):
                print("  %-24s %s" % (key.upper(), outputs[key]))
        print("-" * 78)

    return 0


if __name__ == "__main__":
    sys.exit(main())

# <<< END OF FILE >>>
