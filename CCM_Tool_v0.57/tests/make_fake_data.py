# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
r"""
tests/make_fake_data.py -- build a synthetic CCM data root for testing
=======================================================================
Maintained for the factual v0.57 verification suite.

Creates a folder tree containing REAL, structurally valid files -- not empty
stubs -- so the Data Intelligence scan exercises its actual header readers:

    * genuine classic GeoTIFFs written byte-by-byte with ModelPixelScale,
      ModelTiepoint and GeoKeyDirectory tags (so cell size, extent and EPSG
      are truly parsed, not faked)
    * genuine ESRI shapefiles (.shp + .shx + .dbf + .prj) with a correct
      100-byte header and bounding box
    * a vehicle CSV with the real CCM column names
    * a deliberately duplicated DEM, to exercise duplicate detection
    * a deliberately unclassifiable file, to exercise the unclassified list
    * a geographic-CRS raster, to exercise the CRS warning path

Usage
-----
    python tests/make_fake_data.py  [target_folder]

Defaults to ``./_fake_data`` next to this script.  Safe to re-run: the target
folder is rebuilt from scratch each time.
"""

import os
import sys
import csv
import shutil
import struct

VERSION = "0.57"


# ---------------------------------------------------------------------------
# Minimal but REAL classic GeoTIFF writer
# ---------------------------------------------------------------------------

def write_geotiff(path, width, height, cell_size, origin_x, origin_y,
                  epsg, projected=True, fill=128):
    """
    Write a valid single-band 8-bit classic GeoTIFF with GeoTIFF tags.

    The pixel payload is a constant `fill` value -- content is irrelevant to
    the scanner; the point is that the IFD and GeoKey structures are correct
    so ccm_data_catalog.read_geotiff_header() has something genuine to parse.
    Callers pass a DISTINCT fill per raster so that two unrelated fixtures are
    not byte-identical, which would trip duplicate detection for the wrong
    reason.
    """
    end = "<"
    n_pixels = width * height
    pixel_data = bytes(bytearray([fill & 0xFF]) * n_pixels)

    # Tags we will write: (tag, type, count, values)
    #   256 ImageWidth (SHORT)      257 ImageLength (SHORT)
    #   258 BitsPerSample (SHORT)   259 Compression (SHORT)
    #   262 PhotometricInterp       273 StripOffsets (LONG)
    #   277 SamplesPerPixel         278 RowsPerStrip
    #   279 StripByteCounts (LONG)  33550 ModelPixelScale (DOUBLE x3)
    #   33922 ModelTiepoint (DOUBLE x6)
    #   34735 GeoKeyDirectory (SHORT x N)
    geokeys = [1, 1, 0, 2]                       # version, rev, minor, n_keys
    if projected:
        geokeys += [1024, 0, 1, 1]               # GTModelType = projected
        geokeys += [3072, 0, 1, epsg]            # ProjectedCSTypeGeoKey
    else:
        geokeys += [1024, 0, 1, 2]               # GTModelType = geographic
        geokeys += [2048, 0, 1, epsg]            # GeographicTypeGeoKey

    pixel_scale = [float(cell_size), float(cell_size), 0.0]
    tiepoint = [0.0, 0.0, 0.0, float(origin_x), float(origin_y), 0.0]

    entries = [
        (256, 3, 1, [width]),
        (257, 3, 1, [height]),
        (258, 3, 1, [8]),
        (259, 3, 1, [1]),
        (262, 3, 1, [1]),
        (273, 4, 1, [0]),          # StripOffsets  -- patched below
        (277, 3, 1, [1]),
        (278, 3, 1, [height]),
        (279, 4, 1, [n_pixels]),
        (33550, 12, 3, pixel_scale),
        (33922, 12, 6, tiepoint),
        (34735, 3, len(geokeys), geokeys),
    ]
    entries.sort(key=lambda e: e[0])

    type_size = {3: 2, 4: 4, 12: 8}
    header_size = 8
    ifd_size = 2 + 12 * len(entries) + 4
    data_start = header_size + ifd_size

    # Lay out the values that do not fit in the 4-byte inline slot.
    ext_blobs = []
    ext_offset = data_start
    packed_entries = []
    for tag, typ, cnt, vals in entries:
        size = type_size[typ] * cnt
        fmt = {3: "H", 4: "I", 12: "d"}[typ]
        raw = struct.pack(end + fmt * cnt, *vals)
        if size <= 4:
            payload = raw + b"\x00" * (4 - size)
            packed_entries.append((tag, typ, cnt, payload, None))
        else:
            packed_entries.append((tag, typ, cnt, None, len(ext_blobs)))
            ext_blobs.append(raw)
            ext_offset += size

    pixel_offset = ext_offset

    out = bytearray()
    out += b"II" + struct.pack(end + "HI", 42, header_size)
    out += struct.pack(end + "H", len(packed_entries))

    running = data_start
    blob_offsets = []
    for blob in ext_blobs:
        blob_offsets.append(running)
        running += len(blob)

    for tag, typ, cnt, payload, blob_idx in packed_entries:
        if tag == 273:                       # StripOffsets -> real pixel start
            payload = struct.pack(end + "I", pixel_offset)
        if payload is not None:
            out += struct.pack(end + "HHI", tag, typ, cnt) + payload
        else:
            out += struct.pack(end + "HHI", tag, typ, cnt)
            out += struct.pack(end + "I", blob_offsets[blob_idx])
    out += struct.pack(end + "I", 0)         # no next IFD

    for blob in ext_blobs:
        out += blob
    out += pixel_data

    with open(path, "wb") as fh:
        fh.write(bytes(out))
    return path


# ---------------------------------------------------------------------------
# Minimal but REAL shapefile writer (polygon or point)
# ---------------------------------------------------------------------------

_WKT_UTM36N = (
    'PROJCS["WGS_1984_UTM_Zone_36N",GEOGCS["GCS_WGS_1984",'
    'DATUM["D_WGS_1984",SPHEROID["WGS_1984",6378137.0,298.257223563]],'
    'PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]],'
    'PROJECTION["Transverse_Mercator"],PARAMETER["False_Easting",500000.0],'
    'PARAMETER["Central_Meridian",33.0],PARAMETER["Scale_Factor",0.9996],'
    'PARAMETER["Latitude_Of_Origin",0.0],UNIT["Meter",1.0],'
    'AUTHORITY["EPSG","32636"]]'
)
_WKT_WGS84 = (
    'GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",'
    'SPHEROID["WGS_1984",6378137.0,298.257223563]],'
    'PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433],'
    'AUTHORITY["EPSG","4326"]]'
)


def write_shapefile(base_path, bbox, n_features=1, fields=None, wkt=None):
    """
    Write a structurally valid polygon shapefile (.shp/.shx/.dbf/.prj).

    Only the headers need to be correct for the CCM scanner -- it reads the
    bounding box from the .shp header, the record count from the .shx size,
    and the field names from the .dbf header.  One real rectangle record per
    feature is written so those structures are internally consistent.
    """
    fields = fields or ["ID"]
    xmin, ymin, xmax, ymax = bbox

    # ---- .shp -------------------------------------------------------------
    records = bytearray()
    shx_records = bytearray()
    offset_words = 50                            # 100-byte header / 2
    for i in range(n_features):
        # Polygon record content: type(4) box(32) numParts(4) numPoints(4)
        # parts(4) points(5 * 16)
        content = bytearray()
        content += struct.pack("<i", 5)                       # shape type 5
        content += struct.pack("<4d", xmin, ymin, xmax, ymax)
        content += struct.pack("<ii", 1, 5)
        content += struct.pack("<i", 0)
        ring = [(xmin, ymin), (xmin, ymax), (xmax, ymax),
                (xmax, ymin), (xmin, ymin)]
        for x, y in ring:
            content += struct.pack("<2d", x, y)
        content_words = len(content) // 2
        records += struct.pack(">ii", i + 1, content_words)
        records += content
        shx_records += struct.pack(">ii", offset_words, content_words)
        offset_words += 4 + content_words

    def _hdr(file_length_words):
        h = bytearray()
        h += struct.pack(">i", 9994)
        h += b"\x00" * 20
        h += struct.pack(">i", file_length_words)
        h += struct.pack("<ii", 1000, 5)
        h += struct.pack("<4d", xmin, ymin, xmax, ymax)
        h += struct.pack("<4d", 0, 0, 0, 0)
        return bytes(h)

    shp_path = base_path + ".shp"
    with open(shp_path, "wb") as fh:
        fh.write(_hdr((100 + len(records)) // 2))
        fh.write(bytes(records))

    with open(base_path + ".shx", "wb") as fh:
        fh.write(_hdr((100 + len(shx_records)) // 2))
        fh.write(bytes(shx_records))

    # ---- .dbf -------------------------------------------------------------
    n_fields = len(fields)
    header_len = 32 + 32 * n_fields + 1
    record_len = 1 + 10 * n_fields
    dbf = bytearray()
    dbf += struct.pack("<B3B", 0x03, 126, 1, 1)
    dbf += struct.pack("<IHH", n_features, header_len, record_len)
    dbf += b"\x00" * 20
    for name in fields:
        fname = name.encode("latin-1", "ignore")[:10]
        dbf += fname + b"\x00" * (11 - len(fname))
        dbf += b"C"
        dbf += b"\x00" * 4
        dbf += struct.pack("<BB", 10, 0)
        dbf += b"\x00" * 14
    dbf += b"\x0d"
    for _ in range(n_features):
        dbf += b" "
        for _f in fields:
            dbf += b" " * 10
    dbf += b"\x1a"
    with open(base_path + ".dbf", "wb") as fh:
        fh.write(bytes(dbf))

    # ---- .prj -------------------------------------------------------------
    with open(base_path + ".prj", "w", encoding="utf-8") as fh:
        fh.write(wkt if wkt is not None else _WKT_UTM36N)

    return shp_path


def write_polygon_shapefile(base_path, features, fields=None, wkt=None):
    """
    Write a Polygon shapefile from EXPLICIT ring coordinates (v0.56.2 test
    helper) -- unlike write_shapefile() above, which always derives a
    rectangle from a bbox, this can write any real shape.

    `features` is a list of rings, one polygon feature per ring:
        [[(x, y), (x, y), ...], [(x, y), ...], ...]
    Each ring is closed automatically if the first point is not repeated
    at the end.  Used to prove true polygon intersection catches a gap
    that a bounding-box comparison cannot see -- e.g. a triangle whose
    bounding box is a full square but whose actual area is half of it.
    """
    fields = fields or ["ID"]
    all_x = [p[0] for ring in features for p in ring]
    all_y = [p[1] for ring in features for p in ring]
    xmin, xmax = min(all_x), max(all_x)
    ymin, ymax = min(all_y), max(all_y)

    records = bytearray()
    shx_records = bytearray()
    offset_words = 50
    for i, ring in enumerate(features):
        pts = list(ring)
        if pts[0] != pts[-1]:
            pts = pts + [pts[0]]
        rxs = [p[0] for p in pts]
        rys = [p[1] for p in pts]
        content = bytearray()
        content += struct.pack("<i", 5)                       # shape type 5
        content += struct.pack("<4d", min(rxs), min(rys),
                               max(rxs), max(rys))
        content += struct.pack("<ii", 1, len(pts))
        content += struct.pack("<i", 0)
        for x, y in pts:
            content += struct.pack("<2d", x, y)
        content_words = len(content) // 2
        records += struct.pack(">ii", i + 1, content_words)
        records += content
        shx_records += struct.pack(">ii", offset_words, content_words)
        offset_words += 4 + content_words

    def _hdr(file_length_words):
        h = bytearray()
        h += struct.pack(">i", 9994)
        h += b"\x00" * 20
        h += struct.pack(">i", file_length_words)
        h += struct.pack("<ii", 1000, 5)
        h += struct.pack("<4d", xmin, ymin, xmax, ymax)
        h += struct.pack("<4d", 0, 0, 0, 0)
        return bytes(h)

    shp_path = base_path + ".shp"
    with open(shp_path, "wb") as fh:
        fh.write(_hdr((100 + len(records)) // 2))
        fh.write(bytes(records))

    with open(base_path + ".shx", "wb") as fh:
        fh.write(_hdr((100 + len(shx_records)) // 2))
        fh.write(bytes(shx_records))

    n_features = len(features)
    n_fields = len(fields)
    header_len = 32 + 32 * n_fields + 1
    record_len = 1 + 10 * n_fields
    dbf = bytearray()
    dbf += struct.pack("<B3B", 0x03, 126, 1, 1)
    dbf += struct.pack("<IHH", n_features, header_len, record_len)
    dbf += b"\x00" * 20
    for name in fields:
        fname = name.encode("latin-1", "ignore")[:10]
        dbf += fname + b"\x00" * (11 - len(fname))
        dbf += b"C"
        dbf += b"\x00" * 4
        dbf += struct.pack("<BB", 10, 0)
        dbf += b"\x00" * 14
    dbf += b"\x0d"
    for _ in range(n_features):
        dbf += b" "
        for _f in fields:
            dbf += b" " * 10
    dbf += b"\x1a"
    with open(base_path + ".dbf", "wb") as fh:
        fh.write(bytes(dbf))

    with open(base_path + ".prj", "w", encoding="utf-8") as fh:
        fh.write(wkt if wkt is not None else _WKT_UTM36N)

    return shp_path


# ---------------------------------------------------------------------------
# The synthetic project
# ---------------------------------------------------------------------------
# A 2 km x 2 km AOI in UTM 36N (Lebanon-ish), so the CRS recommender has
# something realistic to reason about and the raster fixtures stay small
# while still genuinely covering the extent.
AOI_BBOX = (700000.0, 3700000.0, 702000.0, 3702000.0)


def build(target):
    """Create the synthetic data root at `target`.  Returns the path."""
    if os.path.isdir(target):
        shutil.rmtree(target)
    os.makedirs(target)

    def d(*parts):
        p = os.path.join(target, *parts)
        os.makedirs(p, exist_ok=True)
        return p

    x0, y0, x1, y1 = AOI_BBOX

    # ---- DEM: three candidates, one duplicated ----------------------------
    dem_dir = d("DEM")
    write_geotiff(os.path.join(dem_dir, "DEM_10m.tif"),
                  width=200, height=200, cell_size=10.0,
                  origin_x=x0, origin_y=y1, epsg=32636, fill=10)
    # A genuinely geographic raster: EPSG:4326 with DEGREE coordinates and a
    # degree cell size (~30 m at this latitude).  Writing it with metre
    # coordinates would be internally inconsistent and would exercise the
    # error path rather than the normal geographic path.
    write_geotiff(os.path.join(dem_dir, "SRTM_30m.tif"),
                  width=67, height=67, cell_size=0.000277778,
                  origin_x=35.15, origin_y=33.26, epsg=4326, projected=False,
                  fill=20)
    # Deliberately offset half a kilometre east -> partial AOI coverage.
    write_geotiff(os.path.join(dem_dir, "ASTER_30m.tif"),
                  width=67, height=67, cell_size=30.0,
                  origin_x=x0 + 500, origin_y=y1, epsg=32636, fill=30)
    backup = d("Backup")
    shutil.copy2(os.path.join(dem_dir, "DEM_10m.tif"),
                 os.path.join(backup, "DEM_10m.tif"))

    # ---- Soil: SoilGrids property rasters ---------------------------------
    soil_dir = d("Soil", "SoilGrids")
    for i, prop in enumerate(("sand_0-5cm", "silt_0-5cm", "clay_0-5cm")):
        write_geotiff(os.path.join(soil_dir, "%s.tif" % prop),
                      width=8, height=8, cell_size=250.0,
                      origin_x=x0, origin_y=y1, epsg=32636, fill=40 + i)

    # ---- Vegetation -------------------------------------------------------
    veg_dir = d("Vegetation")
    write_geotiff(os.path.join(veg_dir, "worldcover_2024.tif"),
                  width=200, height=200, cell_size=10.0,
                  origin_x=x0, origin_y=y1, epsg=32636, fill=60)

    # ---- Hydrology --------------------------------------------------------
    hyd_dir = d("Hydro")
    write_shapefile(os.path.join(hyd_dir, "Rivers"),
                    (x0, y0, x1, y1), n_features=48,
                    fields=["ID", "NAME", "TYPE"])
    write_shapefile(os.path.join(hyd_dir, "Lakes"),
                    (x0 + 200, y0 + 200, x1 - 200, y1 - 200),
                    n_features=7, fields=["ID", "NAME"])

    # ---- Extent -----------------------------------------------------------
    ext_dir = d("Extent")
    write_shapefile(os.path.join(ext_dir, "AOI_Lebanon"),
                    AOI_BBOX, n_features=1, fields=["ID", "NAME"])

    # ---- Vehicles ---------------------------------------------------------
    veh_dir = d("Vehicle")
    with open(os.path.join(veh_dir, "Vehicles_Can.csv"), "w",
              newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["name", "vci_1", "vci_50", "max_road_spd_kph",
                    "max_off_road_grad", "vehicle_width_m", "mmp_kpa"])
        w.writerow(["LAV III", "22", "40", "100", "60", "2.83", "180"])
        w.writerow(["Leopard 2A4", "18", "32", "68", "60", "3.75", "205"])
        w.writerow(["M1", "20", "36", "67", "60", "3.66", "210"])

    # ---- Unclassifiable noise --------------------------------------------
    misc = d("Misc")
    with open(os.path.join(misc, "field_notes.csv"), "w",
              newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerow(["note", "author"])
    with open(os.path.join(misc, "site_photo.jpg"), "wb") as fh:
        fh.write(b"\xff\xd8\xff\xe0" + b"\x00" * 512)
    with open(os.path.join(misc, "old_map.pdf"), "wb") as fh:
        fh.write(b"%PDF-1.4\n" + b"\x00" * 256)

    return target


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    target = (os.path.abspath(argv[0]) if argv
              else os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "_fake_data"))
    build(target)
    print("Synthetic CCM data root created:")
    print("  %s" % target)
    print()
    print("Scan it with:")
    print('  python ccm_step0b_intelligence.py --data-root "%s" \\' % target)
    print('         --aoi "%s"'
          % os.path.join(target, "Extent", "AOI_Lebanon.shp"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

# <<< END OF FILE >>>
