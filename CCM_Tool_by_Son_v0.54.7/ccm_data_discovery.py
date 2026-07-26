# =============================================================================
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON (Beta)
# =============================================================================
r"""
ccm_data_discovery.py — one-folder data root scanner (v0.52.0)
================================================================
Put every raw dataset under ONE parent folder (subfolders named for their
contents) and Step 0 / Step 1 auto-fill their inputs from it:

    MyProject_Data\
        MGCP\...            (gpkg / gdb / cell shapefile trees)
        Soil\HWSD\...       (or SLC, SSURGO, SoilGrids, generic FC)
        DEM\site_dtm.tif
        Contours\contours.shp
        Vegetation\worldcover.tif
        Hydro\rivers.shp
        Vehicle\Vehicles_Can.csv
        Extent\aoi.shp

Detection is two-pass: subfolder-name KEYWORDS first, then CONTENT SNIFFING
(file signatures) for anything unnamed or ambiguous — so a folder called
"data2" full of AP030/BH080 shapefiles still classifies as MGCP.

When SEVERAL candidates exist for one role, they are ranked by expected
accuracy and the best is chosen; the alternatives are kept in the report so
the analyst can override:

    Soil : SSURGO (US ~1:24k) > SLC/DSS (Canada) > SoilGrids (250 m)
           > HWSD (1 km) > generic soil FC
    DEM  : LiDAR/HRDEM name hints > CDEM/SRTM/ASTER hints > largest file
    Veg  : Canada Bio (LAI/fCOVER/canopy) > GEDI > WorldCover/NLCD > generic
    Hydro: ALL detected layers load (multi-value; duplicates removed)

Pure-python (os / re / csv) so the scan is unit-testable without arcpy;
callers do any geometry-level validation with arcpy at fill time.
"""

import os
import re
import csv

VERSION = "0.54.7"  # v0.54.7 — smoke-test detection fix (see CHANGELOG_v0.54.md).

RASTER_EXTS = (".tif", ".tiff", ".img", ".dem", ".asc", ".bil", ".vrt")

# FACC/MGCP feature-code pattern (AP030, BH080, ...)
_FACC_RE = re.compile(r"\b([A-Z]{2}\d{3})", re.IGNORECASE)

# ── Role keywords (folder or file names, lower-case substring match) ──────────
KEYWORDS = {
    "mgcp":     ("mgcp", "facc", "trd"),
    "soil":     ("soil", "slc", "ssurgo", "statsgo", "hwsd", "soilgrid"),
    "dem":      ("dem", "dtm", "dsm", "elevation", "elev", "srtm", "cdem",
                 "hrdem", "lidar", "height"),
    "contours": ("contour", "hypso", "isoline"),
    "veg":      ("veg", "vegetation", "landcover", "land_cover", "land-cover",
                 "lulc", "canopy", "forest", "bio", "lai", "fcover",
                 "worldcover", "nlcd", "gedi"),
    "hydro":    ("hydro", "water", "river", "lake", "stream"),
    "vehicle":  ("vehicle", "fleet", "platform"),
    "extent":   ("extent", "aoi", "boundary", "study_area", "studyarea",
                 "area_of_interest"),
}

# Accuracy ranking (lower = better) used when several candidates share a role
SOIL_PRIORITY = ["SSURGO", "SLC", "SoilGrids", "HWSD", "Generic"]
DEM_HINT_RANK = (
    ("lidar", 0), ("hrdem", 0),
    ("cdem", 1), ("srtm", 1), ("aster", 1), ("dtm", 1), ("dem", 2),
)
VEG_HINT_RANK = (
    ("lai", 0), ("fcover", 0), ("bio", 0),
    ("gedi", 1), ("canopy", 1),
    ("worldcover", 2), ("nlcd", 2), ("landcover", 2), ("lulc", 2),
)


def _role_of_name(name):
    low = str(name).lower()
    for role, kws in KEYWORDS.items():
        if any(k in low for k in kws):
            return role
    return None


def _list_files(folder, exts=None, recurse=True, limit=5000):
    out = []
    if recurse:
        for root, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if not d.lower().endswith(".gdb")]
            for fn in sorted(files):
                if exts is None or fn.lower().endswith(exts):
                    out.append(os.path.join(root, fn))
                    if len(out) >= limit:
                        return out
    else:
        try:
            for fn in sorted(os.listdir(folder)):
                p = os.path.join(folder, fn)
                if os.path.isfile(p) and (exts is None or fn.lower().endswith(exts)):
                    out.append(p)
        except Exception:
            pass
    return out


def _list_gdbs(folder):
    out = []
    for root, dirs, _files in os.walk(folder):
        for d in list(dirs):
            if d.lower().endswith(".gdb"):
                out.append(os.path.join(root, d))
                dirs.remove(d)
    return out


def _facc_fraction(shp_paths):
    """Fraction of shapefile basenames containing a FACC code."""
    if not shp_paths:
        return 0.0
    hits = sum(1 for p in shp_paths
               if _FACC_RE.search(os.path.splitext(os.path.basename(p))[0]))
    return hits / float(len(shp_paths))


def _is_vehicle_csv(path):
    try:
        with open(path, encoding="utf-8-sig", newline="") as fh:
            headers = {h.strip().lower() for h in next(csv.reader(fh))}
        return {"name", "vci_1", "vci_50"} <= headers
    except Exception:
        return False


def _rank_by_hints(paths, hint_rank, default_rank=9):
    """Sort paths: best hint rank first, then largest file first."""
    def _key(p):
        low = os.path.basename(p).lower()
        rank = default_rank
        for hint, r in hint_rank:
            if hint in low:
                rank = min(rank, r)
        try:
            size = os.path.getsize(p)
        except Exception:
            size = 0
        return (rank, -size)
    return sorted(paths, key=_key)


# ── Soil source classification ─────────────────────────────────────────────────

def _classify_soil(folder):
    """
    Return a list of soil-source candidate dicts found under *folder*,
    each: {source_type, paths: {param_name: path}, detail}.
    """
    cands = []
    # HWSD — Access .mdb under a soil folder (+ companion raster nearby)
    mdbs = _list_files(folder, (".mdb",))
    if mdbs:
        cands.append({"source_type": "HWSD",
                      "paths": {"hwsd_mdb": mdbs[0]},
                      "detail": os.path.basename(mdbs[0])})
    # SLC / DSS Canada — cmp/lyr/snt .dbf tables + polygon shapefile
    dbfs = {os.path.basename(p).lower(): p for p in _list_files(folder, (".dbf",))}
    cmp_t = next((p for n, p in dbfs.items() if n.startswith("cmp")), None)
    lyr_t = next((p for n, p in dbfs.items() if n.startswith(("lyr", "layer"))), None)
    if cmp_t:
        poly = next((p for p in _list_files(folder, (".shp",))), None)
        cands.append({"source_type": "SLC",
                      "paths": {"cmp_table": cmp_t, "layer_table": lyr_t,
                                "soil_raw": poly},
                      "detail": os.path.basename(cmp_t)})
    # SSURGO — tabular folder of pipe-delimited .txt (chorizon/component/mapunit)
    txts = {os.path.basename(p).lower() for p in _list_files(folder, (".txt",))}
    if {"chorizon.txt", "comp.txt"} & txts or {"chorizon.txt", "component.txt"} & txts:
        cands.append({"source_type": "SSURGO",
                      "paths": {"ssurgo": folder},
                      "detail": "SSURGO tabular folder"})
    # gSSURGO file GDB
    for gdb in _list_gdbs(folder):
        if "ssurgo" in os.path.basename(gdb).lower():
            cands.append({"source_type": "SSURGO",
                          "paths": {"slc_gdb": gdb},
                          "detail": os.path.basename(gdb)})
    # SoilGrids — folder of property rasters (sand/silt/clay/bdod/...)
    sg_props = ("sand", "silt", "clay", "bdod", "cfvo", "soc", "phh2o")
    sg_hits = [p for p in _list_files(folder, RASTER_EXTS)
               if any(k in os.path.basename(p).lower() for k in sg_props)]
    if len(sg_hits) >= 2:
        cands.append({"source_type": "SoilGrids",
                      "paths": {"sg_folder": os.path.dirname(sg_hits[0])},
                      "detail": f"{len(sg_hits)} property raster(s)"})
    # Generic polygon soil FC (fallback)
    if not cands:
        poly = next((p for p in _list_files(folder, (".shp",))), None)
        if poly:
            cands.append({"source_type": "Generic",
                          "paths": {"soil_raw": poly},
                          "detail": os.path.basename(poly)})
    order = {s: i for i, s in enumerate(SOIL_PRIORITY)}
    cands.sort(key=lambda c: order.get(c["source_type"], 99))
    return cands


# ── Main scan ──────────────────────────────────────────────────────────────────

def scan(root):
    """
    Scan *root* and classify contents.  Returns a dict:

      mgcp_gpkg / mgcp_gdb / mgcp_shp_folders : lists for Step 0
      dem, contours, vehicle_csv, extent_fc   : single best paths (or None)
      veg_rasters, hydro                      : lists (all detected)
      soil        : best candidate {source_type, paths{...}} or None
      soil_alternatives : remaining ranked soil candidates
      report      : [(role, chosen-or-info, reason), ...] for logging
    """
    res = {
        "mgcp_gpkg": [], "mgcp_gdb": [], "mgcp_shp_folders": [],
        "dem": None, "contours": None, "veg_rasters": [], "hydro": [],
        "vehicle_csv": None, "extent_fc": None,
        "soil": None, "soil_alternatives": [],
        "report": [],
    }
    if not root or not os.path.isdir(root):
        return res

    dem_cands, veg_cands, contour_cands, extent_cands, vcsv_cands = [], [], [], [], []
    soil_cands = []

    entries = [root] + [os.path.join(root, d) for d in sorted(os.listdir(root))
                        if os.path.isdir(os.path.join(root, d))
                        and not d.lower().endswith(".gdb")]

    for folder in entries:
        top = (folder == root)
        role = None if top else _role_of_name(os.path.basename(folder))

        shps = _list_files(folder, (".shp",), recurse=not top)
        gpkgs = _list_files(folder, (".gpkg",), recurse=not top)
        gdbs  = [] if top else _list_gdbs(folder)
        rasters = _list_files(folder, RASTER_EXTS, recurse=not top)
        csvs  = _list_files(folder, (".csv",), recurse=not top)

        # content sniffing when the name says nothing
        if role is None and not top:
            if gpkgs or gdbs or (_facc_fraction(shps) >= 0.3 and len(shps) >= 3):
                role = "mgcp"

        if role == "mgcp" or (top and (gpkgs or _facc_fraction(shps) >= 0.5)):
            res["mgcp_gpkg"].extend(gpkgs)
            res["mgcp_gdb"].extend(gdbs)
            if shps and _facc_fraction(shps) >= 0.3:
                res["mgcp_shp_folders"].append(folder)
        elif role == "soil":
            soil_cands.extend(_classify_soil(folder))
        elif role == "dem":
            dem_cands.extend(rasters)
        elif role == "contours":
            contour_cands.extend(shps + gdbs)
        elif role == "veg":
            veg_cands.extend(rasters)
        elif role == "hydro":
            res["hydro"].extend(shps)
        elif role == "vehicle":
            vcsv_cands.extend([c for c in csvs if _is_vehicle_csv(c)])
        elif role == "extent":
            extent_cands.extend(shps)
        else:
            # unnamed / root: sniff individual files
            for r in rasters:
                fr = _role_of_name(os.path.basename(r))
                if fr == "dem":
                    dem_cands.append(r)
                elif fr == "veg":
                    veg_cands.append(r)
            for s in shps:
                fr = _role_of_name(os.path.basename(s))
                if fr == "contours":
                    contour_cands.append(s)
                elif fr == "extent":
                    extent_cands.append(s)
                elif fr == "hydro":
                    res["hydro"].append(s)
            for c in csvs:
                if _is_vehicle_csv(c):
                    vcsv_cands.append(c)

    rep = res["report"]

    if dem_cands:
        ranked = _rank_by_hints(dem_cands, DEM_HINT_RANK)
        res["dem"] = ranked[0]
        rep.append(("DEM", ranked[0],
                    "best of %d candidate(s)" % len(ranked) if len(ranked) > 1
                    else "single candidate"))
        for alt in ranked[1:3]:
            rep.append(("DEM alternative", alt, "lower rank"))

    if contour_cands:
        res["contours"] = contour_cands[0]
        rep.append(("Contours", contour_cands[0], "first match"))

    if veg_cands:
        ranked = _rank_by_hints(veg_cands, VEG_HINT_RANK)
        # load ALL tiles of the winning product family (multi-value input)
        def _rank_of(p):
            low = os.path.basename(p).lower()
            return min((r for h, r in VEG_HINT_RANK if h in low), default=9)
        chosen = [p for p in ranked if _rank_of(p) == _rank_of(ranked[0])]
        res["veg_rasters"] = chosen
        rep.append(("Vegetation", "%d raster(s)" % len(chosen),
                    "best product family of %d candidate(s)" % len(ranked)))

    if res["hydro"]:
        res["hydro"] = sorted(set(res["hydro"]))
        rep.append(("Hydrology", "%d layer(s)" % len(res["hydro"]),
                    "all detected layers load"))

    if vcsv_cands:
        res["vehicle_csv"] = vcsv_cands[0]
        rep.append(("Vehicle CSV", vcsv_cands[0], "vci_1/vci_50 headers found"))

    if extent_cands:
        res["extent_fc"] = extent_cands[0]
        rep.append(("Extent", extent_cands[0], "first match"))

    if soil_cands:
        res["soil"] = soil_cands[0]
        res["soil_alternatives"] = soil_cands[1:]
        rep.append(("Soil", soil_cands[0]["source_type"] + " — " +
                    soil_cands[0]["detail"],
                    "best of %d candidate(s) by accuracy ranking" % len(soil_cands)))
        for alt in soil_cands[1:]:
            rep.append(("Soil alternative", alt["source_type"] + " — " +
                        alt["detail"], "lower accuracy rank"))

    if res["mgcp_gpkg"] or res["mgcp_gdb"] or res["mgcp_shp_folders"]:
        rep.insert(0, ("MGCP", "%d gpkg / %d gdb / %d shp folder(s)" % (
            len(res["mgcp_gpkg"]), len(res["mgcp_gdb"]),
            len(res["mgcp_shp_folders"])), "FACC-coded content"))

    return res

# <<< END OF FILE >>>
