# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
r"""
ccm_data_catalog.py -- CCM Data Intelligence: deep folder scan + dataset catalog
================================================================================
Updated for the factual v0.57 release.

Purpose
-------
Point CCM at ONE folder that holds whatever GIS data the analyst happens to
have, and produce a complete, factual, provenance-preserving INVENTORY of it:

    * what every dataset is                (type + likely CCM role + source type)
    * where it is                          (all locations, duplicates collapsed)
    * what it contains                     (schema / fields / feature count)
    * how good the geometry basis is       (resolution, CRS, extent, coverage)
    * how old it is                        (metadata / file date)
    * what is duplicated                   (same dataset in several places)
    * what could not be identified         (never silently ignored)
    * which CCM roles have NOTHING         (missing-data list)

This module answers "WHAT IS THIS DATA".  It deliberately does not calculate
Quality, Fitness, Confidence, Readiness, source rankings, or substitutions;
those decisions belong to later roadmap releases.

Design rules
------------
1. NEVER imports arcpy at module level.  Every geometry/metadata probe is
   attempted through the best backend available, in this order:

       arcpy  ->  osgeo (GDAL/OGR)  ->  pure-Python header readers  ->  None

   A probe that cannot run returns None and records the fact in ``basis``;
   nothing ever raises out of a scan.  Failure is DATA, not an exception.

2. The pure-Python header readers are real, not placeholders.  They parse:
       * GeoTIFF  IFD tags  -> cell size, raster size, extent, EPSG
       * Shapefile .shp     -> bounding box
       * Shapefile .shx     -> feature count
       * Shapefile .dbf     -> field names + record count
       * .prj  WKT          -> CRS name, projected/geographic, EPSG
   This means the whole scanner runs in a plain Python environment with no
   ArcGIS and no GDAL installed -- which is what makes it unit-testable and
   what makes the standalone CLI useful before ArcGIS Pro is even open.

3. NO NETWORK CALLS.  A scan is offline by definition.

4. Provenance is never destroyed (Roadmap 13/14): the original file name,
   the original MGCP/FACC code and the containing workspace are always kept
   on the record alongside any human-readable display name.

Reuse
-----
Classification keywords, the soil-source classifier and the accuracy hint
ranks are REUSED from ``ccm_data_discovery`` (v0.52) when that module is
importable, so there is exactly one source of truth for "what counts as a
DEM folder".  Local fallback copies are used only if the import fails.

This file is ADDITIVE: it modifies no existing v0.57 module.
"""

import os
import re
import csv
import json
import struct
import hashlib
import datetime
import tempfile

VERSION = "0.58.1"  # v0.58.1 -- bumped by bump_version.py from v0.57. Review this line's comment.
CATALOG_SCHEMA = 1
CATALOG_FILENAME = "ccm_data_catalog.json"
_ARCPY_ENABLED = True

# ---------------------------------------------------------------------------
# Companion modules (all optional)
# ---------------------------------------------------------------------------
try:
    import ccm_data_discovery as _disc
except Exception:                                        # pragma: no cover
    _disc = None

try:
    import ccm_mgcp_catalog as _mgcp
except Exception:                                        # pragma: no cover
    _mgcp = None

try:
    import ccm_data_sources as _sources
except Exception:                                        # pragma: no cover
    _sources = None


# ---------------------------------------------------------------------------
# File-type vocabulary
# ---------------------------------------------------------------------------
RASTER_EXTS = (".tif", ".tiff", ".img", ".dem", ".asc", ".bil", ".vrt",
               ".jp2", ".hgt")
VECTOR_EXTS = (".shp", ".gpkg", ".geojson", ".json", ".kml", ".gml")
TABLE_EXTS = (".csv", ".dbf", ".txt", ".mdb", ".accdb")
IGNORE_EXTS = (".lock", ".sr.lock", ".xml", ".cpg", ".sbn", ".sbx", ".qix",
               ".idx", ".aux", ".ovr", ".rrd", ".tfw", ".prj", ".shx",
               ".pyc", ".zip", ".7z", ".rar", ".log", ".tmp")
IGNORE_PREFIXES = ("~$", ".~", "._")

# Roles the CCM mobility model can consume.
ROLE_DEM = "dem"
ROLE_SOIL = "soil"
ROLE_VEG = "veg"
ROLE_HYDRO = "hydro"
ROLE_CONTOURS = "contours"
ROLE_MOISTURE = "moisture"
ROLE_MGCP = "mgcp"
ROLE_VEHICLE = "vehicle"
ROLE_EXTENT = "extent"
ROLE_UNKNOWN = "unclassified"

CCM_ROLES = [ROLE_DEM, ROLE_SOIL, ROLE_VEG, ROLE_HYDRO, ROLE_CONTOURS,
             ROLE_MOISTURE, ROLE_MGCP, ROLE_VEHICLE, ROLE_EXTENT]

ROLE_LABELS = {
    ROLE_DEM: "DEM / Elevation",
    ROLE_SOIL: "Soil",
    ROLE_VEG: "Vegetation",
    ROLE_HYDRO: "Hydrology",
    ROLE_CONTOURS: "Contours",
    ROLE_MOISTURE: "Soil Moisture",
    ROLE_MGCP: "MGCP",
    ROLE_VEHICLE: "Vehicle Database",
    ROLE_EXTENT: "Analysis Extent (AOI)",
    ROLE_UNKNOWN: "Unclassified",
}

# Fallback keyword table -- used ONLY when ccm_data_discovery cannot be
# imported.  Kept deliberately identical to that module's KEYWORDS, plus the
# two roles v0.52 did not model (moisture) .
_FALLBACK_KEYWORDS = {
    ROLE_MGCP: ("mgcp", "facc", "trd"),
    ROLE_SOIL: ("soil", "slc", "ssurgo", "statsgo", "hwsd", "soilgrid"),
    ROLE_DEM: ("dem", "dtm", "dsm", "elevation", "elev", "srtm", "cdem",
               "hrdem", "lidar", "height"),
    ROLE_CONTOURS: ("contour", "hypso", "isoline"),
    ROLE_VEG: ("veg", "vegetation", "landcover", "land_cover", "land-cover",
               "lulc", "canopy", "forest", "bio", "lai", "fcover",
               "worldcover", "nlcd", "gedi"),
    ROLE_HYDRO: ("hydro", "water", "river", "lake", "stream"),
    ROLE_VEHICLE: ("vehicle", "fleet", "platform"),
    ROLE_EXTENT: ("extent", "aoi", "boundary", "study_area", "studyarea",
                  "area_of_interest"),
}

# Moisture is new in v0.56 (v0.52 discovery had no moisture role).
_MOISTURE_KEYWORDS = ("moisture", "vwc", "smap", "swi", "soil_water",
                      "soilmoisture", "wetness")

_FACC_RE = re.compile(r"\b([A-Z]{2}\d{3})", re.IGNORECASE)


def _keywords():
    """Role keyword table -- discovery's if available, else the fallback."""
    kw = dict(_FALLBACK_KEYWORDS)
    if _disc is not None and hasattr(_disc, "KEYWORDS"):
        kw = dict(_disc.KEYWORDS)
    kw[ROLE_MOISTURE] = _MOISTURE_KEYWORDS
    return kw


# ---------------------------------------------------------------------------
# Source-type identification (name-based -- the content probes refine it)
# ---------------------------------------------------------------------------
# (role, ordered list of (substring, source_type))
_SOURCE_HINTS = {
    ROLE_DEM: [
        ("hrdem", "HRDEM"), ("lidar", "LiDAR"), ("cdem", "CDEM"),
        ("srtm", "SRTM"), ("aster", "ASTER"), ("copernicus", "COP-DEM"),
        ("alos", "ALOS"), ("dtm", "DTM"), ("dsm", "DSM"), ("dem", "DEM"),
    ],
    ROLE_VEG: [
        ("lai", "CanadaBio"), ("fcover", "CanadaBio"), ("glad", "GLAD"),
        ("gedi", "GEDI"), ("worldcover", "WorldCover"), ("nlcd", "NLCD"),
        ("corine", "CORINE"), ("canopy", "CanopyHeight"),
        ("landcover", "LandCover"), ("land_cover", "LandCover"),
        ("lulc", "LandCover"), ("dmti", "DMTI"),
    ],
    ROLE_SOIL: [
        ("ssurgo", "SSURGO"), ("statsgo", "SSURGO"), ("gssurgo", "SSURGO"),
        ("slc", "SLC"), ("dss", "SLC"), ("hwsd", "HWSD"),
        ("soilgrid", "SoilGrids"), ("soil", "Generic"),
    ],
    ROLE_HYDRO: [
        ("mgcp", "MGCP"), ("nhn", "NHN"), ("nhd", "NHD"),
        ("river", "Generic"), ("lake", "Generic"), ("water", "Generic"),
    ],
    ROLE_MOISTURE: [
        ("smap", "SMAP"), ("era5", "ERA5"), ("openmeteo", "Open-Meteo"),
        ("open_meteo", "Open-Meteo"), ("vwc", "Generic"),
    ],
    ROLE_CONTOURS: [
        ("mgcp", "MGCP"), ("ca010", "MGCP"), ("contour", "Generic"),
    ],
}


def identify_source_type(role, name):
    """
    Best-effort source-product identification from a file/folder name.

    Returns a short source tag ("SSURGO", "SRTM", "WorldCover", ...) or
    "Generic" when the role is known but the product is not, or None when the
    role itself is unknown.  Name-based only -- callers mark this in `basis`.
    """
    if not role or role == ROLE_UNKNOWN:
        return None
    low = str(name).lower()
    for hint, src in _SOURCE_HINTS.get(role, []):
        if hint in low:
            return src
    return "Generic"


# ---------------------------------------------------------------------------
# Pure-Python header readers  (no arcpy, no GDAL required)
# ---------------------------------------------------------------------------

_TIFF_TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4,
                   10: 8, 11: 4, 12: 8}


def read_geotiff_header(path):
    """
    Parse a (classic) GeoTIFF's first IFD without any GIS library.

    Returns dict with any of: width, height, cell_size_x, cell_size_y,
    extent (xmin, ymin, xmax, ymax), epsg  -- or None if the file is not a
    parseable classic TIFF (BigTIFF and other formats return None cleanly).
    """
    try:
        with open(path, "rb") as fh:
            head = fh.read(8)
            if len(head) < 8:
                return None
            bo = head[:2]
            if bo == b"II":
                end = "<"
            elif bo == b"MM":
                end = ">"
            else:
                return None
            version = struct.unpack(end + "H", head[2:4])[0]
            if version != 42:          # 43 = BigTIFF -> not handled here
                return None
            ifd_off = struct.unpack(end + "I", head[4:8])[0]

            fh.seek(ifd_off)
            n_raw = fh.read(2)
            if len(n_raw) < 2:
                return None
            n_entries = struct.unpack(end + "H", n_raw)[0]
            if n_entries <= 0 or n_entries > 4096:
                return None
            entries = {}
            raw = fh.read(12 * n_entries)
            if len(raw) < 12 * n_entries:
                return None
            for i in range(n_entries):
                off = 12 * i
                tag, typ, cnt = struct.unpack(end + "HHI", raw[off:off + 8])
                val_raw = raw[off + 8:off + 12]
                size = _TIFF_TYPE_SIZE.get(typ, 0) * cnt
                if size == 0:
                    continue
                if size <= 4:
                    payload = val_raw[:size]
                else:
                    ptr = struct.unpack(end + "I", val_raw)[0]
                    cur = fh.tell()
                    fh.seek(ptr)
                    payload = fh.read(size)
                    fh.seek(cur)
                    if len(payload) < size:
                        continue
                entries[tag] = (typ, cnt, payload)

        def _vals(tag):
            if tag not in entries:
                return None
            typ, cnt, payload = entries[tag]
            fmt = {3: "H", 4: "I", 12: "d", 11: "f", 8: "h", 9: "i"}.get(typ)
            if not fmt:
                return None
            try:
                return list(struct.unpack(end + fmt * cnt, payload))
            except Exception:
                return None

        out = {}
        w = _vals(256)
        h = _vals(257)
        if w:
            out["width"] = int(w[0])
        if h:
            out["height"] = int(h[0])

        scale = _vals(33550)          # ModelPixelScaleTag
        if scale and len(scale) >= 2 and scale[0]:
            out["cell_size_x"] = abs(float(scale[0]))
            out["cell_size_y"] = abs(float(scale[1]))

        tie = _vals(33922)            # ModelTiepointTag (i,j,k, x,y,z)
        if (tie and len(tie) >= 6 and "cell_size_x" in out
                and "width" in out and "height" in out):
            x0 = float(tie[3]) - float(tie[0]) * out["cell_size_x"]
            y0 = float(tie[4]) + float(tie[1]) * out["cell_size_y"]
            xmax = x0 + out["width"] * out["cell_size_x"]
            ymin = y0 - out["height"] * out["cell_size_y"]
            out["extent"] = (x0, ymin, xmax, y0)

        gk = _vals(34735)             # GeoKeyDirectoryTag
        if gk and len(gk) >= 4:
            n_keys = gk[3]
            for k in range(n_keys):
                base = 4 + 4 * k
                if base + 3 >= len(gk):
                    break
                key_id, loc, _cnt, value = gk[base:base + 4]
                if loc != 0:
                    continue
                if key_id == 3072 and value not in (0, 32767):      # Projected
                    out["epsg"] = int(value)
                    out["crs_type"] = "Projected"
                elif key_id == 2048 and "epsg" not in out and \
                        value not in (0, 32767):                    # Geographic
                    out["epsg"] = int(value)
                    out["crs_type"] = "Geographic"
        return out or None
    except Exception:
        return None


def read_shapefile_bbox(path):
    """Bounding box (xmin, ymin, xmax, ymax) from a .shp header."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(100)
        if len(head) < 100:
            return None
        code = struct.unpack(">I", head[0:4])[0]
        if code != 9994:
            return None
        xmin, ymin, xmax, ymax = struct.unpack("<4d", head[36:68])
        return (xmin, ymin, xmax, ymax)
    except Exception:
        return None


def read_shapefile_count(shp_path):
    """Feature count from the companion .shx index (8 bytes per record)."""
    try:
        shx = os.path.splitext(shp_path)[0] + ".shx"
        if not os.path.isfile(shx):
            return None
        size = os.path.getsize(shx)
        if size <= 100:
            return 0
        return int((size - 100) // 8)
    except Exception:
        return None


# Shapefile shape-type code -> display geometry name.  Z/M variants (+10/+20)
# collapse to the same 2-D label, since only X/Y ever feed coverage math.
_SHP_GEOM_MAP = {
    1: "Point", 11: "Point", 21: "Point",
    3: "Polyline", 13: "Polyline", 23: "Polyline",
    5: "Polygon", 15: "Polygon", 25: "Polygon",
    8: "MultiPoint", 18: "MultiPoint", 28: "MultiPoint",
}


def _shapefile_geometry_type(path):
    """Shape-type code from a .shp header (offset 32), mapped to a name.

    NEW in v0.56.2.  The pure-Python probe used to leave ``geometry``
    unset entirely, which silently disabled every geometry-aware feature
    (including AOI-coverage intersection below) whenever arcpy/GDAL were
    both absent -- exactly the case the frozen .exe always runs in.
    """
    try:
        with open(path, "rb") as fh:
            head = fh.read(36)
        if len(head) < 36:
            return None
        if struct.unpack(">I", head[0:4])[0] != 9994:
            return None
        return _SHP_GEOM_MAP.get(struct.unpack("<I", head[32:36])[0])
    except Exception:
        return None


def read_shapefile_polygons(path, max_features=2000, max_points_per_feature=5000):
    """
    Read actual ring vertices from a Polygon-type shapefile (v0.56.2).

    Unlike ``read_shapefile_bbox()``, which only reads the header envelope,
    this walks every feature record and returns its real geometry:

        [[ring, ring, ...], [ring, ...], ...]        # one entry per feature
        ring = [(x, y), (x, y), ...]                 # closing point dropped

    Returns None if the file is not a valid Polygon/PolygonZ/PolygonM
    shapefile.  Bounded by `max_features` / `max_points_per_feature` (a
    feature over the point cap is skipped, not fatal) so a huge or
    malformed file cannot make a scan hang -- same philosophy as
    ``deep_scan()``'s own `max_files` cap.
    """
    SHP_POLYGON = (5, 15, 25)
    try:
        with open(path, "rb") as fh:
            head = fh.read(100)
            if len(head) < 100 or struct.unpack(">I", head[0:4])[0] != 9994:
                return None
            if struct.unpack("<I", head[32:36])[0] not in SHP_POLYGON:
                return None

            features = []
            while len(features) < max_features:
                rec_head = fh.read(8)
                if len(rec_head) < 8:
                    break
                content_bytes = struct.unpack(">I", rec_head[4:8])[0] * 2
                body = fh.read(content_bytes)
                if len(body) < content_bytes or len(body) < 4:
                    break
                if struct.unpack("<I", body[0:4])[0] not in SHP_POLYGON:
                    continue
                if len(body) < 44:
                    continue
                num_parts, num_points = struct.unpack("<II", body[36:44])
                if num_parts <= 0 or num_points <= 0 \
                        or num_points > max_points_per_feature:
                    continue
                parts_end = 44 + num_parts * 4
                if len(body) < parts_end:
                    continue
                parts = list(struct.unpack("<%dI" % num_parts,
                                           body[44:parts_end]))
                pts_bytes = num_points * 16
                if len(body) < parts_end + pts_bytes:
                    continue
                coords = struct.unpack("<%dd" % (num_points * 2),
                                       body[parts_end:parts_end + pts_bytes])
                all_pts = [(coords[2 * i], coords[2 * i + 1])
                          for i in range(num_points)]
                bounds = parts + [num_points]
                rings = []
                for i in range(num_parts):
                    ring = all_pts[bounds[i]:bounds[i + 1]]
                    if len(ring) >= 2 and ring[0] == ring[-1]:
                        ring = ring[:-1]
                    if len(ring) >= 3:
                        rings.append(ring)
                if rings:
                    features.append(rings)
        return features if features else None
    except Exception:
        return None


def read_dbf_fields(dbf_path):
    """
    Field names + record count from a .dbf header.

    Returns {"fields": [...], "record_count": n} or None.
    """
    try:
        with open(dbf_path, "rb") as fh:
            head = fh.read(32)
            if len(head) < 32:
                return None
            rec_count = struct.unpack("<I", head[4:8])[0]
            hdr_len = struct.unpack("<H", head[8:10])[0]
            n_fields = max(0, (hdr_len - 33) // 32)
            fields = []
            for _ in range(n_fields):
                desc = fh.read(32)
                if len(desc) < 32 or desc[0:1] in (b"\r", b""):
                    break
                name = desc[0:11].split(b"\x00")[0].decode(
                    "latin-1", "ignore").strip()
                if name:
                    fields.append(name)
        return {"fields": fields, "record_count": int(rec_count)}
    except Exception:
        return None


_EPSG_IN_WKT = re.compile(
    r'AUTHORITY\s*\[\s*"EPSG"\s*,\s*"(\d+)"\s*\]', re.IGNORECASE)
_WKT_NAME = re.compile(
    r'^\s*(PROJCS|GEOGCS|PROJCRS|GEOGCRS)\s*\[\s*"([^"]+)"', re.IGNORECASE)


def read_prj(prj_path):
    """
    CRS from an ESRI .prj / WKT sidecar, without any GIS library.

    Returns {"type": "Projected"|"Geographic", "name": str, "epsg": int|None}
    """
    try:
        with open(prj_path, encoding="utf-8-sig", errors="ignore") as fh:
            wkt = fh.read()
    except Exception:
        return None
    if not wkt.strip():
        return None
    m = _WKT_NAME.match(wkt)
    kind = (m.group(1).upper() if m else "")
    name = (m.group(2) if m else "Unknown")
    crs_type = ("Projected" if kind.startswith("PROJ") else
                "Geographic" if kind.startswith("GEOG") else None)
    epsg = None
    codes = _EPSG_IN_WKT.findall(wkt)
    if codes:
        epsg = int(codes[-1])          # last AUTHORITY is the CRS itself
    return {"type": crs_type, "name": name, "epsg": epsg}


# ---------------------------------------------------------------------------
# Backend probes  (arcpy -> osgeo -> pure python)
# ---------------------------------------------------------------------------

def _try_arcpy():
    if not _ARCPY_ENABLED:
        return None
    try:
        import arcpy                                   # noqa: F401
        return arcpy
    except Exception:
        return None


def set_arcpy_enabled(enabled):
    """Enable ArcPy probes. GUI worker threads disable them for safety."""
    global _ARCPY_ENABLED
    _ARCPY_ENABLED = bool(enabled)


def _try_osgeo():
    try:
        from osgeo import gdal, ogr, osr               # noqa: F401
        # The scanner's contract is graceful fallback, including with GDAL 4
        # where exceptions become the default. Failed probes stay local and
        # become factual limitations instead of changing scan control flow.
        for module in (gdal, ogr):
            disable = getattr(module, "DontUseExceptions", None)
            if disable is not None:
                disable()
        return (gdal, ogr, osr)
    except Exception:
        return None


def probe_raster(path):
    """
    Raster metadata.  Returns dict with keys among:
        cell_size_m, width, height, extent, crs{type,name,epsg}, backend
    Missing keys simply were not measurable.
    """
    out = {"backend": None}
    arcpy = _try_arcpy()
    if arcpy is not None:
        try:
            d = arcpy.Describe(path)
            sr = getattr(d, "spatialReference", None)
            out["backend"] = "arcpy"
            try:
                out["cell_size_m"] = float(
                    arcpy.management.GetRasterProperties(
                        path, "CELLSIZEX").getOutput(0).replace(",", "."))
            except Exception:
                pass
            try:
                out["width"] = int(d.width)
                out["height"] = int(d.height)
            except Exception:
                pass
            try:
                out["bands"] = int(d.bandCount)
            except Exception:
                pass
            try:
                ext = d.extent
                out["extent"] = (ext.XMin, ext.YMin, ext.XMax, ext.YMax)
            except Exception:
                pass
            if sr is not None and getattr(sr, "name", None):
                out["crs"] = {
                    "type": getattr(sr, "type", None),
                    "name": sr.name,
                    "epsg": (int(sr.factoryCode)
                             if getattr(sr, "factoryCode", 0) else None),
                }
            if len(out) > 1:
                return out
        except Exception:
            pass

    og = _try_osgeo()
    if og is not None:
        gdal, _ogr, osr = og
        try:
            gdal.UseExceptions()
        except Exception:
            pass
        try:
            ds = gdal.Open(path)
            if ds is not None:
                out["backend"] = "gdal"
                gt = ds.GetGeoTransform()
                out["width"] = ds.RasterXSize
                out["height"] = ds.RasterYSize
                out["bands"] = ds.RasterCount
                if gt:
                    out["cell_size_m"] = abs(float(gt[1]))
                    xmin = gt[0]
                    ymax = gt[3]
                    xmax = xmin + ds.RasterXSize * gt[1]
                    ymin = ymax + ds.RasterYSize * gt[5]
                    out["extent"] = (min(xmin, xmax), min(ymin, ymax),
                                     max(xmin, xmax), max(ymin, ymax))
                wkt = ds.GetProjection()
                if wkt:
                    srs = osr.SpatialReference()
                    srs.ImportFromWkt(wkt)
                    code = srs.GetAuthorityCode(None)
                    out["crs"] = {
                        "type": ("Geographic" if srs.IsGeographic()
                                 else "Projected"),
                        "name": (srs.GetName() if hasattr(srs, "GetName")
                                 else "Unknown"),
                        "epsg": int(code) if code else None,
                    }
                ds = None
                return out
        except Exception:
            pass

    # Pure-python fallback
    hdr = read_geotiff_header(path)
    if hdr:
        out["backend"] = "header"
        if "cell_size_x" in hdr:
            out["cell_size_m"] = hdr["cell_size_x"]
        for k in ("width", "height", "extent"):
            if k in hdr:
                out[k] = hdr[k]
        if hdr.get("epsg"):
            out["crs"] = {"type": hdr.get("crs_type"),
                          "name": "EPSG:%d" % hdr["epsg"],
                          "epsg": hdr["epsg"]}
    prj = os.path.splitext(path)[0] + ".prj"
    if "crs" not in out and os.path.isfile(prj):
        c = read_prj(prj)
        if c:
            out["backend"] = out["backend"] or "header"
            out["crs"] = c
    return out


def probe_vector(path):
    """
    Vector metadata.  Returns dict with keys among:
        geometry, feature_count, fields, extent, crs{type,name,epsg}, backend
    """
    out = {"backend": None}
    container_path, layer_name = _split_container_ref(path)
    arcpy = _try_arcpy()
    if arcpy is not None and layer_name is None:
        try:
            d = arcpy.Describe(path)
            out["backend"] = "arcpy"
            out["geometry"] = getattr(d, "shapeType", None)
            try:
                out["feature_count"] = int(
                    arcpy.management.GetCount(path)[0])
            except Exception:
                pass
            try:
                out["fields"] = [f.name for f in arcpy.ListFields(path)]
            except Exception:
                pass
            try:
                ext = d.extent
                out["extent"] = (ext.XMin, ext.YMin, ext.XMax, ext.YMax)
            except Exception:
                pass
            sr = getattr(d, "spatialReference", None)
            if sr is not None and getattr(sr, "name", None):
                out["crs"] = {
                    "type": getattr(sr, "type", None),
                    "name": sr.name,
                    "epsg": (int(sr.factoryCode)
                             if getattr(sr, "factoryCode", 0) else None),
                }
            if len(out) > 1:
                return out
        except Exception:
            pass

    og = _try_osgeo()
    if og is not None and (layer_name is not None or
                           str(path).lower().endswith(
                               (".shp", ".gpkg", ".gdb", ".geojson",
                                ".json", ".gml", ".kml"))):
        _gdal, ogr, osr = og
        try:
            ds = ogr.Open(container_path)
            if ds is not None and ds.GetLayerCount() > 0:
                lyr = (ds.GetLayerByName(layer_name) if layer_name
                       else ds.GetLayer(0))
                if lyr is None:
                    return out
                out["backend"] = "ogr"
                out["feature_count"] = int(lyr.GetFeatureCount())
                defn = lyr.GetLayerDefn()
                out["fields"] = [defn.GetFieldDefn(i).GetName()
                                 for i in range(defn.GetFieldCount())]
                try:
                    x0, x1, y0, y1 = lyr.GetExtent()
                    out["extent"] = (x0, y0, x1, y1)
                except Exception:
                    pass
                srs = lyr.GetSpatialRef()
                if srs is not None:
                    code = srs.GetAuthorityCode(None)
                    out["crs"] = {
                        "type": ("Geographic" if srs.IsGeographic()
                                 else "Projected"),
                        "name": (srs.GetName() if hasattr(srs, "GetName")
                                 else "Unknown"),
                        "epsg": int(code) if code else None,
                    }
                geom_map = {1: "Point", 2: "Polyline", 3: "Polygon",
                            5: "Polyline", 6: "Polygon"}
                out["geometry"] = geom_map.get(lyr.GetGeomType())
                ds = None
                return out
        except Exception:
            pass

    # Pure-python shapefile fallback
    if layer_name is None and str(path).lower().endswith(".shp"):
        out["backend"] = "header"
        out["geometry"] = _shapefile_geometry_type(path)
        bbox = read_shapefile_bbox(path)
        if bbox:
            out["extent"] = bbox
        cnt = read_shapefile_count(path)
        if cnt is not None:
            out["feature_count"] = cnt
        dbf = read_dbf_fields(os.path.splitext(path)[0] + ".dbf")
        if dbf:
            out["fields"] = dbf["fields"]
            if out.get("feature_count") is None:
                out["feature_count"] = dbf["record_count"]
        prj = os.path.splitext(path)[0] + ".prj"
        if os.path.isfile(prj):
            c = read_prj(prj)
            if c:
                out["crs"] = c
    return out


def probe_recency(path):
    """Age of a dataset in days from file mtime (basis = 'file mtime')."""
    try:
        target = path
        if os.path.isdir(path):
            newest = 0
            for root, _dirs, files in os.walk(path):
                for fn in files:
                    try:
                        newest = max(newest,
                                     os.path.getmtime(os.path.join(root, fn)))
                    except Exception:
                        pass
                break
            if not newest:
                return None
            mtime = newest
        else:
            mtime = os.path.getmtime(target)
        age_days = (datetime.datetime.now()
                    - datetime.datetime.fromtimestamp(mtime)).days
        return {"date": datetime.datetime.fromtimestamp(mtime).strftime(
            "%Y-%m-%d"), "age_days": max(0, age_days), "basis": "file mtime"}
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Coverage vs AOI
# ---------------------------------------------------------------------------

def extent_overlap_pct(dataset_extent, aoi_extent):
    """
    Percentage of the AOI bounding box covered by the dataset bounding box.

    This is an EXTENT-level upper-bound estimate, not a geometry intersection:
    a dataset whose bbox covers the AOI may still have holes inside it.  The
    report always labels it as such.  Returns float 0..100 or None.
    """
    if not dataset_extent or not aoi_extent:
        return None
    try:
        dx0, dy0, dx1, dy1 = [float(v) for v in dataset_extent]
        ax0, ay0, ax1, ay1 = [float(v) for v in aoi_extent]
    except Exception:
        return None
    aoi_area = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    if aoi_area <= 0:
        return None
    ix0, iy0 = max(dx0, ax0), max(dy0, ay0)
    ix1, iy1 = min(dx1, ax1), min(dy1, ay1)
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    return round(100.0 * inter / aoi_area, 1)


# ---------------------------------------------------------------------------
# Real (non-bounding-box) coverage  --  NEW in v0.56.2
#
# extent_overlap_pct() above answers "does the dataset's bounding RECTANGLE
# reach this part of the AOI" -- it cannot see a dataset that is genuinely
# only half there (a NoData-riddled raster, an irregular tile grid with a
# gap) as long as the box itself looks big enough.  The functions below try
# to measure the ACTUAL geometry/pixels instead, in whichever backend is
# available, and fall back to the bounding-box estimate only when nothing
# better is possible.  Every result records which method produced it, so
# the report never claims more precision than it actually has.
# ---------------------------------------------------------------------------

def _polygon_area(points):
    """Shoelace-formula signed area of an open ring (first point not
    repeated). Positive if `points` winds counter-clockwise."""
    n = len(points)
    if n < 3:
        return 0.0
    total = 0.0
    for i in range(n):
        x0, y0 = points[i]
        x1, y1 = points[(i + 1) % n]
        total += x0 * y1 - x1 * y0
    return total / 2.0


def _ensure_ccw(points):
    """Reorder a ring counter-clockwise if needed (positive shoelace area).
    Sutherland-Hodgman clipping below assumes a consistent winding."""
    return list(reversed(points)) if _polygon_area(points) < 0 else list(points)


def _clip_polygon(subject, clip):
    """
    Sutherland-Hodgman polygon clipping.  Both `subject` and `clip` are
    open rings (no repeated closing point), already wound the same way.

    `clip` should be convex for a mathematically guaranteed-correct result.
    A mildly non-convex AOI boundary still produces a reasonable, usually-
    correct approximation -- the same trade-off every lightweight GIS tool
    makes when it does not carry a full geometry engine.  Returns the
    clipped ring's points, or [] when there is no overlap at all.
    """
    def inside(p, a, b):
        return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]) >= 0

    def intersection(p1, p2, a, b):
        x1, y1 = p1
        x2, y2 = p2
        x3, y3 = a
        x4, y4 = b
        d = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        if abs(d) < 1e-12:
            return p2
        t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / d
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))

    output = list(subject)
    n = len(clip)
    for i in range(n):
        if not output:
            break
        a, b = clip[i], clip[(i + 1) % n]
        input_pts, output = output, []
        m = len(input_pts)
        for j in range(m):
            cur, prev = input_pts[j], input_pts[j - 1]
            cur_in, prev_in = inside(cur, a, b), inside(prev, a, b)
            if cur_in:
                if not prev_in:
                    output.append(intersection(prev, cur, a, b))
                output.append(cur)
            elif prev_in:
                output.append(intersection(prev, cur, a, b))
    return output


def _polygon_intersection_pct_arcpy(dataset_path, aoi_path):
    """True intersection area of every polygon feature in `dataset_path`
    against the (unioned) AOI polygon, as a percentage of the AOI's own
    area. None if arcpy is unavailable or either input is not polygonal."""
    arcpy = _try_arcpy()
    if arcpy is None:
        return None
    try:
        # v0.57 post-review "M-1": opened in a with-block like every other
        # cursor in the codebase — previously the only one that wasn't,
        # which on Windows/ArcGIS can leave a schema lock on the AOI feature
        # class until the interpreter garbage-collects the cursor.
        with arcpy.da.SearchCursor(aoi_path, ["SHAPE@"]) as _aoi_cur:
            aoi_geoms = [r[0] for r in _aoi_cur if r[0]]
        if not aoi_geoms:
            return None
        aoi_geom = aoi_geoms[0]
        for extra in aoi_geoms[1:]:
            aoi_geom = aoi_geom.union(extra)
        aoi_area = aoi_geom.area
        if not aoi_area or aoi_area <= 0:
            return None
        dataset_geom = None
        with arcpy.da.SearchCursor(dataset_path, ["SHAPE@"]) as cur:
            for (geom,) in cur:
                if geom is None:
                    continue
                try:
                    dataset_geom = (geom if dataset_geom is None
                                    else dataset_geom.union(geom))
                except Exception:
                    continue
        if dataset_geom is None:
            return None
        inter_area = dataset_geom.intersect(aoi_geom, 4).area
        return round(min(100.0, 100.0 * inter_area / aoi_area), 1)
    except Exception:
        return None


def _polygon_intersection_pct_ogr(dataset_path, aoi_path):
    """Same idea as the arcpy version, via OGR. None if GDAL/OGR is
    unavailable or either input has no readable polygon layer."""
    og = _try_osgeo()
    if og is None:
        return None
    _gdal, ogr, _osr = og
    try:
        container_path, layer_name = _split_container_ref(dataset_path)
        aoi_ds = ogr.Open(aoi_path)
        ds_ds = ogr.Open(container_path)
        if aoi_ds is None or ds_ds is None:
            return None
        aoi_lyr = aoi_ds.GetLayer(0)
        if aoi_lyr is None:
            return None
        aoi_geom = None
        for feat in aoi_lyr:
            g = feat.GetGeometryRef()
            if g is None:
                continue
            aoi_geom = g.Clone() if aoi_geom is None else aoi_geom.Union(g)
        if aoi_geom is None:
            return None
        aoi_area = aoi_geom.GetArea()
        if not aoi_area or aoi_area <= 0:
            return None
        ds_lyr = (ds_ds.GetLayerByName(layer_name) if layer_name
                  else ds_ds.GetLayer(0))
        if ds_lyr is None:
            return None
        dataset_geom = None
        for feat in ds_lyr:
            g = feat.GetGeometryRef()
            if g is None:
                continue
            try:
                dataset_geom = (g.Clone() if dataset_geom is None
                                else dataset_geom.Union(g))
            except Exception:
                continue
        if dataset_geom is None:
            return None
        inter = dataset_geom.Intersection(aoi_geom)
        inter_area = 0.0 if inter is None or inter.IsEmpty() else inter.GetArea()
        return round(min(100.0, 100.0 * inter_area / aoi_area), 1)
    except Exception:
        return None


def _polygon_intersection_pct_pure(dataset_path, aoi_path):
    """
    Pure-Python fallback: Sutherland-Hodgman ring clipping against the
    AOI's first feature's outer ring (holes and multi-feature AOIs are not
    modelled -- documented limitation, not silently assumed away). Sums the
    clipped area of every ring of every dataset feature against it.

    This is what the frozen .exe uses -- the only backend it ever has.
    """
    aoi_features = read_shapefile_polygons(aoi_path, max_features=1)
    if not aoi_features:
        return None
    aoi_ring = _ensure_ccw(aoi_features[0][0])
    aoi_area = _polygon_area(aoi_ring)
    if aoi_area <= 0:
        return None
    ds_features = read_shapefile_polygons(dataset_path)
    if not ds_features:
        return None
    inter_area = 0.0
    for rings in ds_features:
        for ring in rings:
            if len(ring) < 3:
                continue
            clipped = _clip_polygon(_ensure_ccw(ring), aoi_ring)
            if len(clipped) >= 3:
                inter_area += abs(_polygon_area(clipped))
    return round(min(100.0, 100.0 * inter_area / aoi_area), 1)


def _raster_aoi_valid_pct_arcpy(path, aoi_extent):
    """
    Fraction of the AOI actually covered by valid (non-NoData) pixels, via
    arcpy -- reads only the window where the raster and the AOI overlap
    (not the whole raster), so NoData padding outside the AOI cannot
    distort the number either way. Returns 0..100 or None.
    """
    arcpy = _try_arcpy()
    if arcpy is None or not aoi_extent:
        return None
    try:
        r = arcpy.Raster(path)
        ext = r.extent
        ix0 = max(ext.XMin, aoi_extent[0])
        iy0 = max(ext.YMin, aoi_extent[1])
        ix1 = min(ext.XMax, aoi_extent[2])
        iy1 = min(ext.YMax, aoi_extent[3])
        if ix1 <= ix0 or iy1 <= iy0:
            return 0.0
        cw, ch = r.meanCellWidth, r.meanCellHeight
        if not cw or not ch:
            return None
        ncols = max(1, int(round((ix1 - ix0) / cw)))
        nrows = max(1, int(round((iy1 - iy0) / ch)))
        arr = arcpy.RasterToNumPyArray(
            r, arcpy.Point(ix0, iy0), ncols, nrows, nodata_to_value=None)
        if arr is None or arr.size == 0:
            return None
        nodata = r.noDataValue
        valid_frac = (1.0 if nodata is None else
                      float((arr != nodata).sum()) / float(arr.size))
        aoi_area = max(0.0, aoi_extent[2] - aoi_extent[0]) * \
            max(0.0, aoi_extent[3] - aoi_extent[1])
        if aoi_area <= 0:
            return None
        window_frac = min(1.0, ((ix1 - ix0) * (iy1 - iy0)) / aoi_area)
        return round(100.0 * valid_frac * window_frac, 1)
    except Exception:
        return None


def _raster_aoi_valid_pct_gdal(path, aoi_extent):
    """Same idea as the arcpy version, via GDAL. Returns 0..100 or None."""
    og = _try_osgeo()
    if og is None or not aoi_extent:
        return None
    gdal, _ogr, _osr = og
    try:
        ds = gdal.Open(path)
        if ds is None:
            return None
        gt = ds.GetGeoTransform()
        if not gt or gt[1] == 0 or gt[5] == 0:
            return None
        origin_x, px_w, _, origin_y, _, px_h = gt
        cols, rows = ds.RasterXSize, ds.RasterYSize
        rx0, rx1 = sorted((origin_x, origin_x + px_w * cols))
        ry0, ry1 = sorted((origin_y, origin_y + px_h * rows))
        ax0, ay0, ax1, ay1 = aoi_extent
        ix0, ix1 = max(rx0, ax0), min(rx1, ax1)
        iy0, iy1 = max(ry0, ay0), min(ry1, ay1)
        if ix1 <= ix0 or iy1 <= iy0:
            return 0.0
        c0, c1 = sorted((int((ix0 - origin_x) / px_w),
                         int((ix1 - origin_x) / px_w)))
        r0, r1 = sorted((int((iy0 - origin_y) / px_h),
                         int((iy1 - origin_y) / px_h)))
        c0, r0 = max(0, c0), max(0, r0)
        c1, r1 = min(cols, c1), min(rows, r1)
        xsize, ysize = c1 - c0, r1 - r0
        if xsize <= 0 or ysize <= 0:
            return 0.0
        band = ds.GetRasterBand(1)
        nodata = band.GetNoDataValue()
        arr = band.ReadAsArray(c0, r0, xsize, ysize)
        if arr is None or arr.size == 0:
            return None
        valid_frac = (1.0 if nodata is None else
                      float((arr != nodata).sum()) / float(arr.size))
        aoi_area = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
        if aoi_area <= 0:
            return None
        window_frac = min(1.0, ((ix1 - ix0) * (iy1 - iy0)) / aoi_area)
        return round(100.0 * valid_frac * window_frac, 1)
    except Exception:
        return None


def coverage_pct(rec, probe, aoi, path, dtype):
    """
    Best available AOI-coverage estimate for one dataset (v0.56.2).

    Tries the most accurate method the current backend allows and falls
    back gracefully.  Returns (pct, basis_label) -- pct is 0..100 or None,
    and basis_label always says exactly how it was computed, so nothing is
    ever displayed as more precise than it actually is:

        "true polygon intersection (arcpy|ogr|pure-python)"
            Both the dataset and the AOI are polygons -- their actual rings
            were clipped against each other, not just their bounding boxes.
        "valid-pixel ratio (arcpy|gdal)"
            The dataset is a raster and a real backend is available -- the
            NoData mask was read (windowed to the AOI overlap) instead of
            assumed absent.
        "bounding-box overlap (upper bound)"
            The universal fallback: extent rectangles only.  May overstate
            true coverage if the dataset has interior gaps.
    """
    aoi_path = aoi.get("path")
    aoi_extent = aoi.get("extent")

    if dtype in ("vector", "gpkg", "container_layer") and aoi_path and \
            rec.get("geometry") == "Polygon" and aoi.get("geometry") == "Polygon":
        for fn, label in (
                (_polygon_intersection_pct_arcpy,
                 "true polygon intersection (arcpy)"),
                (_polygon_intersection_pct_ogr,
                 "true polygon intersection (ogr)"),
                (_polygon_intersection_pct_pure,
                 "polygon clipping approximation (pure-python)")):
            pct = fn(path, aoi_path)
            if pct is not None:
                return pct, label

    if dtype == "raster" and aoi_extent:
        for fn, label in (
                (_raster_aoi_valid_pct_arcpy, "valid-pixel ratio (arcpy)"),
                (_raster_aoi_valid_pct_gdal, "valid-pixel ratio (gdal)")):
            pct = fn(path, aoi_extent)
            if pct is not None:
                return pct, label

    if aoi_extent and probe.get("extent"):
        pct = extent_overlap_pct(probe["extent"], aoi_extent)
        if pct is not None:
            return pct, "bounding-box overlap (upper bound)"
    return None, None


# ---------------------------------------------------------------------------
# UTM recommendation
# ---------------------------------------------------------------------------

def recommend_utm_epsg(lon, lat, datum="WGS84"):
    """
    Recommend the UTM zone EPSG for a location.  Pure arithmetic.

    WGS84  : 326xx (north) / 327xx (south)
    NAD83  : 269xx (north, zones 1-23 only)

    Returns {"epsg": int, "name": str, "zone": int, "hemisphere": "N"|"S"}
    or None when the inputs are not plausible lon/lat degrees.
    """
    try:
        lon = float(lon)
        lat = float(lat)
    except Exception:
        return None
    if not (-180.0 <= lon <= 180.0) or not (-90.0 <= lat <= 90.0):
        return None
    zone = int((lon + 180.0) // 6.0) + 1
    zone = min(60, max(1, zone))
    north = lat >= 0
    if str(datum).upper().startswith("NAD") and north and 1 <= zone <= 23:
        epsg = 26900 + zone
        name = "NAD 1983 UTM Zone %d%s" % (zone, "N")
    else:
        epsg = (32600 if north else 32700) + zone
        name = "WGS 1984 UTM Zone %d%s" % (zone, "N" if north else "S")
    return {"epsg": epsg, "name": name, "zone": zone,
            "hemisphere": "N" if north else "S"}


def latlon_from_extent(extent, crs):
    """
    Best-effort AOI centroid in lon/lat.

    If the CRS is geographic the extent already IS degrees.  If it is a known
    UTM EPSG the zone's central meridian and the northing give a usable
    approximation -- enough to recommend a zone, which is all this is for.
    Returns (lon, lat) or None.
    """
    if not extent:
        return None
    try:
        x0, y0, x1, y1 = [float(v) for v in extent]
    except Exception:
        return None
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    epsg = (crs or {}).get("epsg")
    ctype = (crs or {}).get("type")
    if ctype == "Geographic" or (
            abs(cx) <= 180.0 and abs(cy) <= 90.0 and ctype is None):
        return (cx, cy)
    if epsg:
        zone = None
        south = False
        if 32601 <= epsg <= 32660:
            zone = epsg - 32600
        elif 32701 <= epsg <= 32760:
            zone, south = epsg - 32700, True
        elif 26901 <= epsg <= 26923:
            zone = epsg - 26900
        if zone:
            central = -180.0 + 6.0 * zone - 3.0
            northing = cy - (10000000.0 if south else 0.0)
            lat = northing / 111320.0
            lat = max(-90.0, min(90.0, lat))
            lon = central + (cx - 500000.0) / (
                111320.0 * max(0.15, abs(_cos_deg(lat))))
            lon = max(-180.0, min(180.0, lon))
            return (lon, lat)
    return None


def _cos_deg(deg):
    import math
    return math.cos(math.radians(deg))


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------

def file_signature(path, sample=65536):
    """
    Cheap content signature: size + sha1 of the first and last `sample` bytes.

    Full hashing of multi-GB rasters is not acceptable during an interactive
    scan; head+tail+size is decisive enough for "the same file copied twice",
    which is the case this exists to catch.
    """
    try:
        size = os.path.getsize(path)
        h = hashlib.sha1()
        h.update(str(size).encode())
        with open(path, "rb") as fh:
            h.update(fh.read(sample))
            if size > sample * 2:
                fh.seek(-sample, os.SEEK_END)
                h.update(fh.read(sample))
        return "%d:%s" % (size, h.hexdigest()[:16])
    except Exception:
        return None


def dataset_signature(path, dataset_type=None):
    """Signature a logical dataset rather than only its primary file.

    A shapefile's attributes and CRS live in sidecars.  Hashing only ``.shp``
    can incorrectly collapse two datasets that share geometry but have
    different attributes or coordinate systems.
    """
    low = str(path).lower()
    if (dataset_type == "vector" or low.endswith(".shp")) and \
            low.endswith(".shp"):
        base = os.path.splitext(path)[0]
        parts = []
        for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
            part = base + ext
            if os.path.isfile(part):
                parts.append((ext, file_signature(part)))
        if not parts:
            return None
        h = hashlib.sha1()
        for ext, sig in parts:
            h.update(ext.encode("ascii"))
            h.update(str(sig).encode("ascii", "replace"))
        return "shapefile:%s" % h.hexdigest()[:20]
    return file_signature(path)


# ---------------------------------------------------------------------------
# Deep scan
# ---------------------------------------------------------------------------

def _should_ignore(fname):
    low = fname.lower()
    if low.startswith(IGNORE_PREFIXES):
        return True
    if low.endswith(".shp.xml"):
        return True
    for ext in IGNORE_EXTS:
        if low.endswith(ext):
            return True
    return False


def _dataset_type(path):
    low = str(path).lower()
    if os.path.isdir(path):
        if low.endswith(".gdb"):
            return "gdb"
        return "folder"
    if low.endswith(RASTER_EXTS):
        return "raster"
    if low.endswith(".gpkg"):
        return "gpkg"
    if low.endswith(VECTOR_EXTS):
        return "vector"
    if low.endswith(TABLE_EXTS):
        return "table"
    return "other"


_CONTAINER_SEPARATOR = "::"


def _split_container_ref(path):
    text = str(path)
    if _CONTAINER_SEPARATOR in text:
        return tuple(text.split(_CONTAINER_SEPARATOR, 1))
    return text, None


def _enumerate_container(path, root):
    """Return one candidate per readable GDB/GeoPackage dataset layer."""
    out = []
    arcpy = _try_arcpy()
    if arcpy is not None and str(path).lower().endswith(".gdb"):
        try:
            for dirpath, _dirnames, names in arcpy.da.Walk(
                    path, datatype=["FeatureClass", "RasterDataset", "Table"]):
                for name in names:
                    full = os.path.join(dirpath, name)
                    try:
                        desc = arcpy.Describe(full)
                        dt = str(getattr(desc, "dataType", "")).lower()
                    except Exception:
                        dt = ""
                    dtype = ("raster" if "raster" in dt else
                             "table" if "table" in dt else "vector")
                    role, basis = _classify_path(
                        os.path.join(path, name), root)
                    out.append({
                        "path": full, "name": name, "dataset_type": dtype,
                        "role": role, "role_basis": basis,
                        "size": None, "signature": None,
                        "container_path": path,
                    })
            if out:
                return out
        except Exception:
            out = []

    og = _try_osgeo()
    if og is not None:
        _gdal, ogr, _osr = og
        try:
            ds = ogr.Open(path)
            if ds is not None:
                for idx in range(ds.GetLayerCount()):
                    lyr = ds.GetLayer(idx)
                    if lyr is None:
                        continue
                    name = lyr.GetName() or "layer_%d" % (idx + 1)
                    role, basis = _classify_path(
                        os.path.join(path, name), root)
                    out.append({
                        "path": "%s%s%s" % (path, _CONTAINER_SEPARATOR, name),
                        "name": name, "dataset_type": "container_layer",
                        "role": role, "role_basis": basis,
                        "size": None, "signature": None,
                        "container_path": path,
                    })
        except Exception:
            return []
    return out


def _classify_path(path, root):
    """
    Determine the CCM role of a path from its own name and every folder name
    between it and the scan root (nearest folder wins, then the file name).
    """
    kw = _keywords()
    rel = os.path.relpath(path, root)
    parts = rel.replace("\\", "/").split("/")
    file_name = parts[-1]
    folders = parts[:-1]

    def _match(text):
        low = str(text).lower()
        for role, words in kw.items():
            if any(w in low for w in words):
                return role
        return None

    # File name first -- it is the most specific statement of intent.
    role = _match(os.path.splitext(file_name)[0])
    if role:
        return role, "file name"
    # Then folders, nearest first.
    for folder in reversed(folders):
        role = _match(folder)
        if role:
            return role, "folder name '%s'" % folder
    # Content sniff: FACC-coded shapefiles mean MGCP.
    if _FACC_RE.search(os.path.splitext(file_name)[0].upper()):
        return ROLE_MGCP, "FACC feature code in name"
    return ROLE_UNKNOWN, "no keyword match"


def _is_vehicle_csv(path):
    # v0.57 post-review "5.5": this was a byte-identical copy of
    # ccm_data_discovery._is_vehicle_csv() — this module already imports
    # ccm_data_discovery as _disc (optional), so delegate to it when
    # available and keep the inline implementation only as the fallback for
    # the case _disc failed to import (this module's own arcpy-optional
    # design philosophy: never hard-require a companion module).
    if _disc is not None:
        return _disc._is_vehicle_csv(path)
    try:
        with open(path, encoding="utf-8-sig", newline="") as fh:
            headers = {h.strip().lower() for h in next(csv.reader(fh))}
        return {"name", "vci_1", "vci_50"} <= headers
    except Exception:
        return False


def deep_scan(root, max_files=20000):
    """
    Walk `root` and return a list of raw candidate dicts:
        {path, name, dataset_type, role, role_basis, size, signature}

    Shapefile sidecars, lock files and Office temp files are filtered out, so
    one shapefile is ONE candidate, not seven.
    """
    out = []
    if not root or not os.path.isdir(root):
        return out
    n = 0
    for dirpath, dirnames, filenames in os.walk(root):
        # A .gdb is a dataset, not a folder to walk into.
        gdbs = [d for d in dirnames if d.lower().endswith(".gdb")]
        dirnames[:] = [d for d in dirnames
                       if not d.lower().endswith(".gdb")
                       and not d.startswith((".", "__"))]
        for g in gdbs:
            gp = os.path.join(dirpath, g)
            layers = _enumerate_container(gp, root)
            if layers:
                for cand in layers:
                    out.append(cand)
                    n += 1
                    if n >= max_files:
                        return out
            else:
                role, basis = _classify_path(gp, root)
                out.append({"path": gp, "name": g, "dataset_type": "gdb",
                            "role": role, "role_basis": basis,
                            "size": None, "signature": None})
                n += 1
                if n >= max_files:
                    return out
        # A shapefile is ONE dataset, not four.  Its .dbf attribute table is a
        # sidecar, not a standalone table -- but a .dbf with no companion .shp
        # (an SLC/DSS component or layer table, for example) IS a real dataset
        # and must still be catalogued.
        shp_bases = {os.path.splitext(f)[0].lower() for f in filenames
                     if f.lower().endswith(".shp")}
        for fn in sorted(filenames):
            if _should_ignore(fn):
                continue
            if fn.lower().endswith(".dbf") and \
                    os.path.splitext(fn)[0].lower() in shp_bases:
                continue
            fp = os.path.join(dirpath, fn)
            dtype = _dataset_type(fp)
            if dtype == "gpkg":
                layers = _enumerate_container(fp, root)
                if layers:
                    for cand in layers:
                        out.append(cand)
                        n += 1
                        if n >= max_files:
                            return out
                    continue
            if dtype == "other":
                # Keep it visible as unclassified rather than dropping it.
                out.append({"path": fp, "name": fn, "dataset_type": "other",
                            "role": ROLE_UNKNOWN,
                            "role_basis": "unsupported file type",
                            "size": _safe_size(fp), "signature": None})
                n += 1
                if n >= max_files:
                    return out
                continue
            role, basis = _classify_path(fp, root)
            if dtype == "table" and fn.lower().endswith(".csv"):
                if _is_vehicle_csv(fp):
                    role, basis = ROLE_VEHICLE, "vci_1/vci_50 headers found"
            out.append({"path": fp, "name": fn, "dataset_type": dtype,
                        "role": role, "role_basis": basis,
                        "size": _safe_size(fp),
                        "signature": dataset_signature(fp, dtype)})
            n += 1
            if n >= max_files:
                return out
    return out


def _safe_size(path):
    try:
        return os.path.getsize(path)
    except Exception:
        return None


def find_duplicates(candidates):
    """
    Group candidates that are byte-identical copies OF THE SAME CCM ROLE.

    Grouping is keyed on (role, signature), not on the signature alone.  Two
    byte-identical files that serve DIFFERENT roles are two datasets, not one:
    collapsing them would silently delete a role from the inventory.  The
    real-world case is a single land-cover raster legitimately supplied both
    as the vegetation source and as a soil approximation -- CCM must see it
    once per role, not once in total.

    Returns (groups, dup_paths) where groups is a list of lists of paths
    (length >= 2) and dup_paths is the set of NON-primary duplicate paths.
    """
    by_key = {}
    for c in candidates:
        sig = c.get("signature")
        if not sig:
            continue
        by_key.setdefault((c.get("role"), sig), []).append(c["path"])
    groups = [sorted(paths) for paths in by_key.values() if len(paths) > 1]
    groups.sort()
    dup_paths = set()
    for g in groups:
        dup_paths.update(g[1:])
    return groups, dup_paths


# ---------------------------------------------------------------------------
# MGCP manifest ingest
# ---------------------------------------------------------------------------

def find_mgcp_manifest(root):
    """Locate an mgcp_manifest.json anywhere under root (first hit)."""
    if not root or not os.path.isdir(root):
        return None
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.lower().endswith(".gdb")]
        for fn in filenames:
            if fn.lower() == "mgcp_manifest.json":
                return os.path.join(dirpath, fn)
    return None


def ingest_mgcp_manifest(manifest_path):
    """
    Read a Step-0 mgcp_manifest.json into a per-CCM-role summary.

    The manifest already records code / theme / ccm_role / feature_count /
    spatial_reference / fields per feature class, so no geodatabase access is
    needed.  Returns None when the file is unusable.
    """
    if not manifest_path or not os.path.isfile(manifest_path):
        return None
    try:
        with open(manifest_path, encoding="utf-8") as fh:
            man = json.load(fh)
    except Exception:
        return None
    feats = man.get("features") or []
    by_role = {}
    themes = {}
    unused = 0
    for f in feats:
        role = f.get("ccm_role")
        theme = f.get("theme") or "Other"
        themes[theme] = themes.get(theme, 0) + 1
        if not role:
            unused += 1
            continue
        by_role.setdefault(role, []).append({
            "name": f.get("name"),
            "path": f.get("path"),
            "code": f.get("code"),
            "label": f.get("label"),
            "geometry": f.get("geometry"),
            "feature_count": f.get("feature_count"),
            "spatial_reference": f.get("spatial_reference"),
            "fields": f.get("fields") or [],
        })
    return {
        "manifest_path": manifest_path,
        "output_gdb": man.get("output_gdb"),
        "created": man.get("created"),
        "feature_total": len(feats),
        "unused_features": unused,
        "themes": themes,
        "by_role": by_role,
    }


# ---------------------------------------------------------------------------
# Required-schema expectations (for completeness scoring downstream)
# ---------------------------------------------------------------------------
REQUIRED_FIELDS = {
    (ROLE_SOIL, "MGCP"): ["SMC"],
    (ROLE_SOIL, "SLC"): ["CMP", "SLOPE"],
    (ROLE_SOIL, "SSURGO"): ["mukey"],
    (ROLE_SOIL, "Generic"): [],
    (ROLE_VEG, "PREPROCESSED"): ["vegetationTrafficImpact", "treeSpacing",
                                 "stemDiameter"],
    (ROLE_VEHICLE, "CSV"): ["name", "vci_1", "vci_50", "max_road_spd_kph"],
}


def _schema_check(record, probe):
    """Attach a schema completeness block to a record when expectations exist."""
    role = record["ccm_role"]
    src = record.get("source_type") or "Generic"
    key = (role, src)
    required = REQUIRED_FIELDS.get(key)
    if required is None and role == ROLE_VEHICLE:
        required = REQUIRED_FIELDS[(ROLE_VEHICLE, "CSV")]
    if required is None:
        return None
    present = []
    fields = [str(f).lower() for f in (probe.get("fields") or [])]
    if role == ROLE_VEHICLE and record["dataset_type"] == "table":
        try:
            with open(record["path"], encoding="utf-8-sig", newline="") as fh:
                fields = [h.strip().lower() for h in next(csv.reader(fh))]
        except Exception:
            fields = []
    for r in required:
        if r.lower() in fields:
            present.append(r)
    pct = (100.0 if not required
           else round(100.0 * len(present) / len(required), 1))
    return {"required": required, "present": present,
            "missing": [r for r in required if r not in present],
            "completeness_pct": pct,
            "basis": "field list read" if fields else "fields unavailable"}


# ---------------------------------------------------------------------------
# Record construction
# ---------------------------------------------------------------------------

def build_record(cand, root, aoi=None, duplicate_of=None, locations=None):
    """
    Turn one raw scan candidate into a full inventory record.

    `aoi` is an optional {"extent": (...), "crs": {...}} describing the
    analysis extent, used for coverage.  All probes degrade gracefully.
    """
    path = cand["path"]
    physical_path, layer_name = _split_container_ref(path)
    role = cand["role"]
    dtype = cand["dataset_type"]
    rec = {
        "path": path,
        "name": cand["name"],
        "locations": locations or [path],
        "dataset_type": dtype,
        "ccm_role": role,
        "role_basis": cand.get("role_basis"),
        "source_type": identify_source_type(role, path),
        "coverage_aoi_pct": None,
        "coverage_basis": None,
        "resolution": {},
        "crs": {},
        "acquired": None,
        "schema": None,
        "compatibility": "unknown",
        "limitations": [],
        "status": "candidate",
        "duplicate_of": duplicate_of,
        "provenance": {
            "original_name": cand["name"],
            "container": cand.get("container_path") or os.path.dirname(path),
            "relative_path": os.path.relpath(physical_path, root),
            "facc_code": None,
        },
        "size_bytes": cand.get("size"),
        "basis": [],
        # Reserved nullable schema fields for later roadmap releases.
        "quality": None,
        "fitness": None,
        "confidence": None,
    }

    # Provenance: keep the original MGCP/FACC identity when present.
    code_m = _FACC_RE.search(os.path.splitext(cand["name"])[0].upper())
    if code_m:
        rec["provenance"]["facc_code"] = code_m.group(1)
        if _mgcp is not None:
            try:
                info = _mgcp.lookup(cand["name"])
                rec["provenance"]["facc_label"] = info.get("name")
                rec["provenance"]["facc_theme"] = info.get("theme")
            except Exception:
                pass

    probe = {}
    if dtype == "raster":
        probe = probe_raster(path) or {}
        cs = probe.get("cell_size_m")
        if cs:
            # A raster's cell size is expressed in the units of its OWN CRS.
            # For a geographic CRS that is DEGREES, not metres -- 0.000278 deg
            # is roughly 30 m, not 0.0003 m.  Reporting or scoring the raw
            # number would rank a coarse global DEM as the finest data in the
            # project, so it is converted to a metre equivalent here, with the
            # native value kept for transparency.
            crs_probe = probe.get("crs") or {}
            native = float(cs)
            unit = "m"
            approx = False
            if crs_probe.get("type") == "Geographic" and native < 1.0:
                lat = _centre_latitude(probe.get("extent"))
                native_m = _degrees_to_metres(native, lat)
                rec["resolution"] = {
                    "cell_size_m": round(native_m, 4),
                    "cell_size_native": native,
                    "cell_size_unit": "degrees",
                    "cell_size_is_approximate": True,
                    "basis": probe.get("backend"),
                }
                unit, approx = "degrees", True
            else:
                rec["resolution"] = {"cell_size_m": round(native, 4),
                                     "cell_size_native": native,
                                     "cell_size_unit": unit,
                                     "basis": probe.get("backend")}
            rec["basis"].append(
                "resolution: %s%s" % (probe.get("backend"),
                                      " (degrees converted to metres)"
                                      if approx else ""))
        if probe.get("width"):
            rec["resolution"]["width"] = probe["width"]
            rec["resolution"]["height"] = probe.get("height")
            rec["resolution"]["pixels"] = (
                int(probe["width"]) * int(probe.get("height") or 0)) or None
        if probe.get("bands"):
            rec["resolution"]["bands"] = probe["bands"]
    elif dtype in ("vector", "gpkg", "container_layer"):
        probe = probe_vector(path) or {}
        if probe.get("feature_count") is not None:
            rec["resolution"] = {"feature_count": probe["feature_count"],
                                 "basis": probe.get("backend")}
    elif dtype == "table":
        probe = probe_table(path) or {}
        if probe.get("row_count") is not None:
            rec["resolution"] = {"row_count": probe["row_count"],
                                 "column_count": len(probe.get("fields") or []),
                                 "basis": probe.get("backend")}
    elif dtype == "gdb":
        probe = {}
        rec["limitations"].append(
            "File geodatabase -- contents not enumerated without ArcGIS")

    if probe.get("crs"):
        rec["crs"] = probe["crs"]
        rec["basis"].append("crs: %s" % probe.get("backend"))
        if rec["crs"].get("type") == "Geographic":
            rec["limitations"].append(
                "Geographic CRS (%s) -- CCM requires a Projected CRS"
                % rec["crs"].get("name"))

    if probe.get("geometry"):
        rec["geometry"] = probe["geometry"]
    if probe.get("fields"):
        rec["fields"] = probe["fields"]
    if probe.get("extent"):
        rec["extent"] = list(probe["extent"])

    rec["acquired"] = probe_recency(physical_path)
    if rec["acquired"]:
        rec["basis"].append("date: file mtime")

    # Coverage vs AOI (same-CRS comparison only -- otherwise meaningless).
    # v0.56.2: tries a true geometry/pixel measurement before falling back
    # to the bounding-box estimate -- see coverage_pct()'s docstring.
    if aoi and probe.get("extent"):
        aoi_epsg = ((aoi.get("crs") or {}).get("epsg"))
        ds_epsg = (rec["crs"] or {}).get("epsg")
        aoi_crs = aoi.get("crs") or {}
        ds_crs = rec.get("crs") or {}
        same_crs = bool(aoi_epsg and ds_epsg and aoi_epsg == ds_epsg)
        if not same_crs and not aoi_epsg and not ds_epsg:
            same_crs = bool(
                aoi_crs.get("name") and ds_crs.get("name") and
                str(aoi_crs.get("name")).strip().lower() ==
                str(ds_crs.get("name")).strip().lower() and
                aoi_crs.get("type") == ds_crs.get("type"))
        if aoi.get("extent") and same_crs:
            pct, cov_basis = coverage_pct(rec, probe, aoi, path, dtype)
            if pct is not None:
                rec["coverage_aoi_pct"] = pct
                rec["coverage_basis"] = cov_basis
                rec["basis"].append("coverage: %s" % cov_basis)
                if pct < 99.0:
                    rec["limitations"].append(
                        "Covers ~%.0f%% of the analysis extent (%s)"
                        % (pct, cov_basis))
                if cov_basis and "approximation" in cov_basis:
                    rec["limitations"].append(
                        "Coverage uses lightweight polygon clipping; holes and "
                        "complex multi-part AOIs may require ArcPy/GDAL validation")
        elif aoi_epsg and ds_epsg and aoi_epsg != ds_epsg:
            rec["limitations"].append(
                "CRS differs from the analysis extent (EPSG:%s vs EPSG:%s) -- "
                "coverage not computed" % (ds_epsg, aoi_epsg))
        elif aoi.get("extent"):
            rec["limitations"].append(
                "Coverage not computed because matching dataset/AOI CRS could "
                "not be confirmed")

    rec["schema"] = _schema_check(rec, probe)
    if rec["schema"] and rec["schema"]["missing"]:
        rec["limitations"].append(
            "Missing expected field(s): %s" % ", ".join(rec["schema"]["missing"]))

    rec["compatibility"] = _compatibility(rec)
    _attach_descriptive_facts(rec)
    return rec


def _attach_descriptive_facts(rec):
    """
    Add the human-facing description of the dataset (v0.56.1).

    Two additions, both purely explanatory -- neither influences any score:

      source_info  what this data PRODUCT is, from ccm_data_sources
      ground_size  the real-world size of the dataset's extent, so a reader can
                   see at a glance whether it plausibly covers the AOI
      resolution.class  fine / moderate / coarse, judged per CCM role, because
                   250 m is unusable for slope yet normal for global soil
    """
    role = rec.get("ccm_role")
    src = rec.get("source_type")

    if _sources is not None:
        rec["source_info"] = _sources.describe(role, src)
        cs = (rec.get("resolution") or {}).get("cell_size_m")
        if cs:
            klass = _sources.resolution_class(role, cs)
            if klass:
                rec["resolution"]["class"] = klass["label"]
                rec["resolution"]["class_meaning"] = klass["meaning"]
            rec["resolution"]["display"] = _sources.format_resolution(cs)
    else:                                                # pragma: no cover
        rec["source_info"] = None

    ext = rec.get("extent")
    if ext and len(ext) == 4:
        try:
            span_x = abs(float(ext[2]) - float(ext[0]))
            span_y = abs(float(ext[3]) - float(ext[1]))
            crs_type = (rec.get("crs") or {}).get("type")
            # A geographic CRS means the extent is in DEGREES -- but only if
            # the numbers are actually plausible as degrees.  Real deliveries
            # do contain files whose georeferencing is internally inconsistent
            # (a projected grid tagged with a geographic EPSG, usually from a
            # bad export).  Trusting the tag blindly would print nonsense like
            # "2010 deg x 2010 deg", so the numbers get the final say and the
            # contradiction is reported as a limitation instead.
            plausible_degrees = (span_x <= 360.0 and span_y <= 180.0)
            if crs_type == "Geographic" and plausible_degrees:
                rec["ground_size"] = {
                    "width": round(span_x, 6), "height": round(span_y, 6),
                    "unit": "degrees",
                    "display": "%.4g deg x %.4g deg" % (span_x, span_y),
                }
            elif crs_type == "Geographic" and not plausible_degrees:
                rec["ground_size"] = {
                    "width": round(span_x, 1), "height": round(span_y, 1),
                    "unit": "unknown",
                    "display": "%.6g x %.6g (units unclear)"
                               % (span_x, span_y),
                }
                rec["limitations"].append(
                    "Georeferencing looks inconsistent: the CRS is geographic "
                    "but the extent spans %.6g x %.6g, which is far too large "
                    "for degrees. Verify this file before using it."
                    % (span_x, span_y))
            elif not plausible_degrees or crs_type == "Projected":
                rec["ground_size"] = {
                    "width": round(span_x, 1), "height": round(span_y, 1),
                    "unit": "m",
                    "display": _format_ground(span_x, span_y),
                    "area_km2": round(span_x * span_y / 1e6, 2),
                }
            else:
                # CRS unknown and the numbers could be degrees -- say so
                # rather than assert a unit that was never measured.
                rec["ground_size"] = {
                    "width": round(span_x, 6), "height": round(span_y, 6),
                    "unit": "unknown",
                    "display": "%.4g x %.4g (CRS unknown -- unit unverified)"
                               % (span_x, span_y),
                }
        except Exception:
            pass


def _format_ground(width_m, height_m):
    """'2.0 x 2.0 km' or '850 x 640 m'."""
    if max(width_m, height_m) >= 1000:
        return "%.3g x %.3g km" % (width_m / 1000.0, height_m / 1000.0)
    return "%.3g x %.3g m" % (width_m, height_m)


# One degree of latitude is very nearly constant; one degree of longitude
# shrinks with the cosine of latitude.  A raster cell is reported at its
# latitude spacing, which is the conservative (larger) of the two and is what
# "30 m SRTM" conventionally refers to.
_METRES_PER_DEGREE_LAT = 111320.0


def _centre_latitude(extent):
    """Mid-latitude of a geographic extent, or 0 when unknown."""
    try:
        if extent and len(extent) == 4:
            return (float(extent[1]) + float(extent[3])) / 2.0
    except Exception:
        pass
    return 0.0


def _degrees_to_metres(degrees, latitude=0.0):
    """
    Approximate ground distance of an angular cell size.

    Used only to make a geographic raster's resolution comparable with a
    projected one; it is flagged as approximate wherever it is reported.
    """
    try:
        return abs(float(degrees)) * _METRES_PER_DEGREE_LAT
    except Exception:
        return 0.0


def probe_table(path):
    """
    Row/column counts for a CSV or standalone DBF table.

    Reading a CSV's row count means reading the file, so this is capped: past
    the cap the count is reported as a lower bound rather than blocking a scan
    on a multi-million-row table.
    """
    out = {"backend": "header"}
    low = str(path).lower()
    try:
        if low.endswith(".csv"):
            with open(path, encoding="utf-8-sig", newline="") as fh:
                reader = csv.reader(fh)
                header = next(reader, None)
                if header is None:
                    return out
                out["fields"] = [h.strip() for h in header]
                n = 0
                for n, _row in enumerate(reader, start=1):
                    if n >= 200000:
                        out["row_count_is_lower_bound"] = True
                        break
                out["row_count"] = n
        elif low.endswith(".dbf"):
            info = read_dbf_fields(path)
            if info:
                out["fields"] = info["fields"]
                out["row_count"] = info["record_count"]
    except Exception:
        pass
    return out


def _compatibility(rec):
    """
    Can the existing CCM pre-processing pipeline consume this as-is?

        native      -- a supported source type in a supported container
        convertible -- usable but needs conversion/reprojection first
        unsupported -- CCM has no ingestion path for it
    """
    role = rec["ccm_role"]
    dtype = rec["dataset_type"]
    src = rec.get("source_type")
    if role == ROLE_UNKNOWN:
        return "unsupported"
    if rec.get("crs", {}).get("type") == "Geographic":
        return "convertible"
    if role == ROLE_SOIL and src in ("SSURGO", "SLC", "HWSD", "SoilGrids",
                                     "MGCP"):
        return "native"
    if role == ROLE_DEM and dtype == "raster":
        return "native"
    if role == ROLE_VEG and dtype == "raster":
        return "native"
    if role in (ROLE_HYDRO, ROLE_CONTOURS, ROLE_EXTENT) and \
            dtype in ("vector", "gpkg", "gdb", "container_layer"):
        return "native"
    if role == ROLE_VEHICLE and dtype == "table":
        return "native"
    if role == ROLE_MOISTURE and dtype == "raster":
        return "native"
    return "convertible"


# ---------------------------------------------------------------------------
# AOI description
# ---------------------------------------------------------------------------

def describe_aoi(aoi_path):
    """
    Describe the analysis-extent feature class / shapefile.

    Returns {"path", "extent", "crs", "feature_count", "geometry"} or None.
    """
    if not aoi_path or not os.path.exists(aoi_path):
        return None
    probe = probe_vector(aoi_path) or {}
    if not probe:
        return None
    out = {"path": aoi_path,
           "extent": list(probe["extent"]) if probe.get("extent") else None,
           "crs": probe.get("crs") or {},
           "feature_count": probe.get("feature_count"),
           "geometry": probe.get("geometry"),
           "backend": probe.get("backend")}
    return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_catalog(data_root, aoi_path=None, project_folder=None,
                  max_files=20000):
    """
    Scan `data_root` and return the complete catalog dict.

    Structure
    ---------
        {
          "catalog_schema": 1,
          "ccm_version": "0.57",
          "created": "...",
          "data_root": "...",
          "aoi": {...} | None,
          "recommended_crs": {...} | None,
          "backend": "arcpy" | "gdal" | "header" | "none",
          "roles": { role: {"records": [...], "count": n} },
          "unclassified": [records],
          "duplicate_groups": [[path, path], ...],
          "mgcp": {...} | None,
          "missing_roles": [role, ...],
          "stats": {...}
        }

    This release returns observed inventory facts only.  Reserved Quality,
    Fitness, and Confidence fields on records remain null, and no Readiness or
    automatic-selection summary is created.
    """
    created = datetime.datetime.now().isoformat(timespec="seconds")
    catalog = {
        "catalog_schema": CATALOG_SCHEMA,
        "ccm_version": VERSION,
        "created": created,
        "data_root": str(data_root) if data_root else None,
        "project_folder": str(project_folder) if project_folder else None,
        "aoi": None,
        "recommended_crs": None,
        "backend": _backend_name(),
        "roles": {r: {"records": [], "count": 0} for r in CCM_ROLES},
        "unclassified": [],
        "duplicate_groups": [],
        "mgcp": None,
        "missing_roles": [],
        "stats": {},
    }

    if not data_root or not os.path.isdir(str(data_root)):
        catalog["error"] = "Data root not found: %s" % data_root
        catalog["missing_roles"] = list(CCM_ROLES)
        return catalog

    root = str(data_root)

    # ---- AOI --------------------------------------------------------------
    aoi = describe_aoi(aoi_path) if aoi_path else None
    catalog["aoi"] = aoi
    # v0.56.2: an AOI path can exist on disk yet be unreadable by every
    # available backend (e.g. a .gpkg handed to the frozen exe, which only
    # ever has the pure-Python .shp reader). describe_aoi() still returns a
    # stub dict in that case, so `aoi` alone can't distinguish "not
    # supplied" from "supplied but empty" -- record it explicitly instead
    # of letting coverage %% silently never appear with no explanation.
    catalog["aoi_unreadable"] = bool(aoi_path) and aoi is not None \
        and not aoi.get("extent")

    # ---- Raw scan ---------------------------------------------------------
    candidates = deep_scan(root, max_files=max_files)
    groups, dup_paths = find_duplicates(candidates)
    catalog["duplicate_groups"] = groups

    # Map every duplicate to its primary so records carry all locations.
    primary_of = {}
    locations_of = {}
    for g in groups:
        primary = g[0]
        locations_of[primary] = list(g)
        for p in g[1:]:
            primary_of[p] = primary

    # ---- Records ----------------------------------------------------------
    for cand in candidates:
        path = cand["path"]
        if path in dup_paths:
            continue                    # folded into its primary's locations
        rec = build_record(cand, root, aoi=aoi,
                           duplicate_of=None,
                           locations=locations_of.get(path, [path]))
        if len(rec["locations"]) > 1:
            rec["limitations"].append(
                "%d identical copies found in the data root"
                % len(rec["locations"]))
        role = rec["ccm_role"]
        if role == ROLE_UNKNOWN:
            catalog["unclassified"].append(rec)
        else:
            catalog["roles"][role]["records"].append(rec)

    # ---- MGCP manifest ----------------------------------------------------
    man_path = find_mgcp_manifest(root)
    catalog["mgcp"] = ingest_mgcp_manifest(man_path) if man_path else None
    if catalog["mgcp"]:
        _apply_manifest_roles(catalog)

    # ---- Counts / missing -------------------------------------------------
    for role in CCM_ROLES:
        catalog["roles"][role]["count"] = len(catalog["roles"][role]["records"])
    catalog["missing_roles"] = [
        r for r in (ROLE_DEM, ROLE_SOIL, ROLE_VEG, ROLE_HYDRO, ROLE_CONTOURS,
                    ROLE_MOISTURE, ROLE_VEHICLE, ROLE_EXTENT)
        if catalog["roles"][r]["count"] == 0
    ]

    # ---- Recommended CRS --------------------------------------------------
    catalog["recommended_crs"] = _recommend_crs(catalog)

    # ---- Stats ------------------------------------------------------------
    catalog["stats"] = {
        "files_scanned": len(candidates),
        "datasets_catalogued": sum(catalog["roles"][r]["count"]
                                   for r in CCM_ROLES),
        "unclassified": len(catalog["unclassified"]),
        "duplicate_groups": len(groups),
        "duplicate_files": len(dup_paths),
    }
    return catalog


def _backend_name():
    if _try_arcpy() is not None:
        return "arcpy"
    if _try_osgeo() is not None:
        return "gdal"
    return "header"


def _apply_manifest_roles(catalog):
    """
    Add MGCP manifest feature classes as records for the roles they serve.

    The manifest is authoritative for MGCP content (Step 0 wrote it after a
    real import), so these records are marked with basis "mgcp_manifest.json"
    and never re-probed.
    """
    man = catalog["mgcp"]
    role_map = {"soil": ROLE_SOIL, "hydro": ROLE_HYDRO, "veg": ROLE_VEG,
                "contours": ROLE_CONTOURS}
    for man_role, entries in (man.get("by_role") or {}).items():
        role = role_map.get(man_role)
        if not role:
            continue
        for e in entries:
            rec = {
                "path": e.get("path"),
                "name": e.get("name"),
                "locations": [e.get("path")],
                "dataset_type": "vector",
                "ccm_role": role,
                "role_basis": "mgcp_manifest.json (Step 0 output)",
                "source_type": "MGCP",
                "coverage_aoi_pct": None,
                "resolution": {"feature_count": e.get("feature_count"),
                               "basis": "mgcp_manifest.json"},
                "crs": {"name": e.get("spatial_reference"), "type": None,
                        "epsg": None},
                "acquired": {"date": (man.get("created") or "")[:10],
                             "age_days": None,
                             "basis": "manifest created date"},
                "schema": None,
                "compatibility": "native",
                "limitations": [],
                "status": "candidate",
                "duplicate_of": None,
                "geometry": e.get("geometry"),
                "fields": e.get("fields") or [],
                "provenance": {
                    "original_name": e.get("name"),
                    "container": man.get("output_gdb"),
                    "relative_path": e.get("name"),
                    "facc_code": e.get("code"),
                    "facc_label": e.get("label"),
                },
                "size_bytes": None,
                "basis": ["mgcp_manifest.json"],
                "quality": None, "fitness": None, "confidence": None,
            }
            if role == ROLE_SOIL:
                flds = [str(f).lower() for f in (e.get("fields") or [])]
                rec["schema"] = {
                    "required": ["SMC"],
                    "present": ["SMC"] if "smc" in flds else [],
                    "missing": [] if "smc" in flds else ["SMC"],
                    "completeness_pct": 100.0 if "smc" in flds else 0.0,
                    "basis": "manifest field list",
                }
                if "smc" not in flds:
                    rec["limitations"].append(
                        "DA010 present but no SMC attribute -- soil strength "
                        "cannot be derived from it")
            _attach_descriptive_facts(rec)
            catalog["roles"][role]["records"].append(rec)


def _recommend_crs(catalog):
    """Recommend a projected CRS from the AOI, or from any dataset extent."""
    aoi = catalog.get("aoi")
    lonlat = None
    basis = None
    if aoi and aoi.get("extent"):
        lonlat = latlon_from_extent(aoi["extent"], aoi.get("crs"))
        basis = "analysis extent"
    if lonlat is None:
        for role in (ROLE_DEM, ROLE_EXTENT, ROLE_VEG, ROLE_SOIL, ROLE_HYDRO):
            for rec in catalog["roles"][role]["records"]:
                if rec.get("extent"):
                    lonlat = latlon_from_extent(rec["extent"], rec.get("crs"))
                    if lonlat:
                        basis = "extent of %s" % rec["name"]
                        break
            if lonlat:
                break
    if not lonlat:
        return None
    lon, lat = lonlat
    datum = "NAD83" if (-141.0 <= lon <= -52.0 and 41.0 <= lat <= 84.0) \
        else "WGS84"
    rec = recommend_utm_epsg(lon, lat, datum=datum)
    if rec:
        rec["basis"] = basis
        rec["centroid"] = [round(lon, 4), round(lat, 4)]
        # Is anything already in that CRS?
        current = None
        if aoi and (aoi.get("crs") or {}).get("epsg"):
            current = aoi["crs"]["epsg"]
        rec["aoi_epsg"] = current
        rec["aoi_matches"] = (current == rec["epsg"]) if current else None
    return rec


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def write_catalog_json(catalog, out_folder, filename=CATALOG_FILENAME):
    """Write the catalog to <out_folder>/ccm_data_catalog.json."""
    os.makedirs(str(out_folder), exist_ok=True)
    path = os.path.join(str(out_folder), filename)
    payload = json.dumps(catalog, indent=2, ensure_ascii=False, default=str)
    atomic_write_text(path, payload + "\n")
    return path


def atomic_write_text(path, text):
    """Write UTF-8 text atomically in the destination directory."""
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".ccm_write_", suffix=".tmp",
                                     dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp_path, path)
    except Exception:
        try:
            os.remove(temp_path)
        except Exception:
            pass
        raise


def load_catalog_json(path_or_folder, filename=CATALOG_FILENAME):
    """Load a previously written catalog.  Returns {} when unavailable."""
    p = str(path_or_folder)
    if os.path.isdir(p):
        p = os.path.join(p, filename)
    if not os.path.isfile(p):
        return {}
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}

# <<< END OF FILE >>>
