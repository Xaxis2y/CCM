# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# -*- coding: utf-8 -*-
# ccm_coords.py
# CCM Coordinate Utilities — multi-format parsing, validation, conversion
#
# VERSION = "0.55.0"
#
# Supported input formats (auto-detected):
#   MGRS  — 18TVR1234567890  or  18T VR 12345 67890
#   DD    — 37.1234, -127.5678   or   37.1234N 127.5678W
#   DMS   — 37°07'24.5"N 127°34'04.1"W
#   DDM   — 37°07.408'N 127°34.068'W
#   UTM   — 52S 123456 7890123   or   52 S 123456E 7890123N
#
# Conversion uses arcpy.management.ConvertCoordinateNotation via an
# in-memory scratch table so no external packages are required.
#
# Public API
# ----------
#   any_to_latlon(coord_str)          → (lat, lon) or raises ValueError
#   latlon_to_all_formats(lat, lon)   → dict with keys: mgrs, dd, dms, ddm, utm
#   detect_format(coord_str)          → format name string or "Unknown"
#   validate_mgrs(mgrs_str)           → (bool, error_msg)
#   normalise_mgrs(mgrs_str)          → canonical MGRS string
#
# ─────────────────────────────────────────────────────────────────────────────

import re
import arcpy

VERSION = "0.55.1"  # v0.55.1 -- version bump only: added QUICK_START.html and CCM_anaconda_environment.bat (Anaconda Prompt environment setup script); no code/logic changes. See CHANGELOG_v0.55.md.

# ─── FIELD-NAME HELPER ───────────────────────────────────────────────────────
#
# ConvertCoordinateNotation field names vary by ArcGIS Pro version:
#   Older versions : DDY  / DDX    (lat / lon in DD output)
#   Newer versions : DDLat / DDLon
#   Some versions  : POINT_Y / POINT_X,  LAT / LON
#   MGRS output    : MGRS  (or prefixed SOMETHING_MGRS)
#   UTM output     : UTM   (or prefixed)
#
# _CCN_ALIASES maps a canonical name → ordered list of alternatives to try.
_CCN_ALIASES = {
    # latitude  (Y)
    "DDY":  ["DDY",  "DDLAT", "LAT",  "LATITUDE",  "POINT_Y", "Y"],
    # longitude (X)
    "DDX":  ["DDX",  "DDLON", "LON",  "LONGITUDE", "POINT_X", "X"],
    # MGRS output field
    "MGRS": ["MGRS"],
    # UTM output field
    "UTM":  ["UTM"],
}


def _find_ccn_fields(out_table, expected_names):
    """
    Locate ConvertCoordinateNotation output fields by canonical name.

    Tries multiple known naming conventions (DDY/DDLat/LAT…) and also
    handles version-specific prefixes (e.g. MGRS_STR_DDLat).

    Parameters
    ----------
    out_table      : str   path to the CCN output table
    expected_names : list  canonical names to find, e.g. ["DDY", "DDX"]

    Returns
    -------
    list of actual field names found, in the same order as expected_names

    Raises
    ------
    ValueError with a diagnostic listing available fields.
    """
    actual = {f.name.upper(): f.name for f in arcpy.ListFields(out_table)}
    result = []

    for want in expected_names:
        # Build the list of alternatives to try for this canonical name
        aliases = _CCN_ALIASES.get(want.upper(), [want])
        # Also add the canonical name itself in case it's not in the map
        if want.upper() not in [a.upper() for a in aliases]:
            aliases = [want] + aliases

        found = None
        for alias in aliases:
            au = alias.upper()
            # 1. Exact match
            if au in actual:
                found = actual[au]
                break
            # 2. Suffix match: e.g. MGRS_STR_DDLAT → alias=DDLAT
            match = next(
                (v for k, v in actual.items() if k.endswith("_" + au)),
                None,
            )
            if match:
                found = match
                break

        if found is None:
            # Last-resort: scan every field — return first one whose value
            # falls within valid lat/lon range when read from the table.
            # This handles any completely unexpected field naming.
            raise ValueError(
                f"Cannot find field '{want}' (tried: {aliases}) in "
                f"ConvertCoordinateNotation output.\n"
                f"Available fields: {list(actual.values())}"
            )
        result.append(found)

    return result


def _read_latlon_from_ccn_table(out_table):
    """
    Robustly extract (lat, lon) from a ConvertCoordinateNotation output table.

    Tries in order:
      1. Hardcoded DD attribute field pairs (DDLat/DDLon, DDY/DDX, etc.)
         These always contain decimal degrees regardless of arcpy.env.outputCoordinateSystem.
      2. SHAPE@ geometry with WGS84 sanity check (|Y|<=90, |X|<=180).
         Skipped if arcpy.env.outputCoordinateSystem is a projected CRS —
         the geometry would contain projected metres, not degrees.
      3. _find_ccn_fields alias lookup as final fallback.

    Returns (lat, lon) floats or raises ValueError.
    """
    # ── 1. Hardcoded attribute field pairs — always decimal degrees ───────────
    _actual_up = {f.name.upper(): f.name for f in arcpy.ListFields(out_table)}
    for _lat_up, _lon_up in [
        ("DDLAT", "DDLON"),
        ("DDY",   "DDX"),
        ("LAT",   "LON"),
        ("LATITUDE", "LONGITUDE"),
        ("POINT_Y",  "POINT_X"),
        ("Y",        "X"),
    ]:
        if _lat_up in _actual_up and _lon_up in _actual_up:
            _lf = _actual_up[_lat_up]
            _xf = _actual_up[_lon_up]
            try:
                with arcpy.da.SearchCursor(out_table, [_lf, _xf]) as _cur:
                    for _row in _cur:
                        if _row[0] is not None and _row[1] is not None:
                            _lat_v = float(_row[0])
                            _lon_v = float(_row[1])
                            # Basic range check — lat/lon must be within WGS84 bounds
                            if abs(_lat_v) <= 90.0 and abs(_lon_v) <= 180.0:
                                return (_lat_v, _lon_v)
            except Exception:
                continue

    # ── 2. Geometry — only if the values are within valid WGS84 ranges ────────
    # arcpy.env.outputCoordinateSystem can cause the geometry to be in a
    # projected CRS (e.g. UTM metres), so we sanity-check before trusting it.
    try:
        with arcpy.da.SearchCursor(out_table, ["SHAPE@"]) as _cur:
            for _row in _cur:
                if _row[0]:
                    _pt = _row[0].firstPoint
                    _y, _x = float(_pt.Y), float(_pt.X)
                    if abs(_y) <= 90.0 and abs(_x) <= 180.0:
                        return (_y, _x)
    except Exception:
        pass

    # ── 3. Alias lookup fallback ──────────────────────────────────────────────
    try:
        lat_f, lon_f = _find_ccn_fields(out_table, ["DDY", "DDX"])
        with arcpy.da.SearchCursor(out_table, [lat_f, lon_f]) as _cur:
            for _row in _cur:
                if _row[0] is not None and _row[1] is not None:
                    return (float(_row[0]), float(_row[1]))
    except Exception:
        pass

    raise ValueError(
        f"ConvertCoordinateNotation produced no readable output in {out_table!r}"
    )


# ─── MGRS ────────────────────────────────────────────────────────────────────

_MGRS_RE = re.compile(
    r"^\d{1,2}[C-HJ-NP-X][A-HJ-NP-Z][A-HJ-NP-V](\d{2}|\d{4}|\d{6}|\d{8}|\d{10})?$"
)


def normalise_mgrs(mgrs_str):
    """Return the canonical (no-space, upper-case) form of an MGRS string."""
    return mgrs_str.strip().replace(" ", "").upper()


def validate_mgrs(mgrs_str):
    """Check whether *mgrs_str* looks like a valid MGRS coordinate.
    Returns (is_valid: bool, error_msg: str)."""
    if not mgrs_str or not mgrs_str.strip():
        return False, "MGRS coordinate is empty."
    s = normalise_mgrs(mgrs_str)
    if _MGRS_RE.match(s):
        return True, ""
    return (
        False,
        f"'{mgrs_str}' is not a valid MGRS coordinate.\n"
        "Expected format: 18TVR1234567890  or  18T VR 12345 67890",
    )


# ─── FORMAT DETECTION ────────────────────────────────────────────────────────

# Regex patterns for format detection
_DD_RE = re.compile(
    # Matches all common DD forms, e.g.:
    #   "45.64 -75.59"         ← signed second number (no hemisphere letters)
    #   "45.64N 75.59W"        ← hemisphere letters
    #   "45.64, -75.59"        ← comma-separated with sign
    #   "-45.64 -75.59"        ← both negative
    r"^[-+]?\d{1,3}(\.\d+)?"   # first number (lat)
    r"(?:\s*[NSns])?"           # optional N/S — group is optional so backtrack
    r"[\s,]+"                    # separator: one or more spaces/commas
    r"[-+]?\d{1,3}(\.\d+)?"    # second number (lon) with optional sign
    r"(?:\s*[EWew])?$"          # optional E/W hemisphere
)
_DMS_RE = re.compile(
    r"\d{1,3}\s*[°d]\s*\d{1,2}\s*[\'′]\s*\d{1,2}(\.\d+)?\s*[\"″]?\s*[NSns]"
)
_DDM_RE = re.compile(
    r"\d{1,3}\s*[°d]\s*\d{1,2}(\.\d+)?\s*[\'′]\s*[NSns]"
)
_UTM_RE = re.compile(
    r"^\d{1,2}\s*[C-HJ-NP-X]\s+\d{3,7}(\s*[EW])?\s+\d{4,8}(\s*[NS])?$",
    re.IGNORECASE
)


def detect_format(coord_str):
    """
    Auto-detect the coordinate format of *coord_str*.
    Returns one of: 'MGRS', 'DD', 'DMS', 'DDM', 'UTM', or 'Unknown'.
    """
    if not coord_str or not coord_str.strip():
        return "Unknown"

    s = coord_str.strip()

    # Try MGRS first (strict regex)
    if _MGRS_RE.match(normalise_mgrs(s)):
        return "MGRS"

    # DMS must be checked before DDM (more specific)
    if _DMS_RE.search(s):
        return "DMS"

    if _DDM_RE.search(s):
        return "DDM"

    # UTM: zone + band + easting + northing
    if _UTM_RE.match(s):
        return "UTM"

    # DD: two decimal numbers with optional N/S/E/W
    if _DD_RE.match(s.replace(",", " ")):
        return "DD"

    return "Unknown"


# ─── PARSERS ─────────────────────────────────────────────────────────────────

def _parse_dd(coord_str):
    """
    Parse Decimal Degrees: '37.1234, -127.5678' or '37.1234N 127.5678W'.
    Returns (lat, lon).
    """
    s = coord_str.strip().replace(",", " ")
    # Extract all numeric tokens + optional hemisphere letters
    tokens = re.findall(r"[-+]?\d+\.?\d*|[NSnsEWew]", s)
    nums = []
    hems = []
    for t in tokens:
        if t.upper() in "NSEW":
            hems.append(t.upper())
        else:
            nums.append(float(t))
    if len(nums) < 2:
        raise ValueError(f"Cannot parse DD coordinate: {coord_str!r}")
    lat, lon = nums[0], nums[1]
    # Apply hemisphere signs
    for h in hems:
        if h == "S":
            lat = -abs(lat)
        elif h == "W":
            lon = -abs(lon)
    return lat, lon


def _dms_part_to_decimal(deg, minutes, seconds, hemisphere):
    """Convert DMS components to signed decimal degrees."""
    dd = abs(float(deg)) + float(minutes) / 60.0 + float(seconds) / 3600.0
    if hemisphere.upper() in ("S", "W"):
        dd = -dd
    return dd


def _parse_dms(coord_str):
    """
    Parse Degrees Minutes Seconds: '37°07\'24.5"N 127°34\'04.1"W'.
    Returns (lat, lon).
    """
    # Match pattern: degrees° minutes' seconds" hemisphere
    pat = re.compile(
        r"(\d{1,3})\s*[°d]\s*(\d{1,2})\s*[\'′]\s*(\d{1,2}(?:\.\d+)?)\s*[\"″]?\s*([NSEWnsew])"
    )
    matches = pat.findall(coord_str)
    if len(matches) < 2:
        raise ValueError(f"Cannot parse DMS coordinate: {coord_str!r}")
    lat = _dms_part_to_decimal(*matches[0])
    lon = _dms_part_to_decimal(*matches[1])
    return lat, lon


def _parse_ddm(coord_str):
    """
    Parse Degrees Decimal Minutes: '37°07.408\'N 127°34.068\'W'.
    Returns (lat, lon).
    """
    pat = re.compile(
        r"(\d{1,3})\s*[°d]\s*(\d{1,2}(?:\.\d+)?)\s*[\'′]\s*([NSEWnsew])"
    )
    matches = pat.findall(coord_str)
    if len(matches) < 2:
        raise ValueError(f"Cannot parse DDM coordinate: {coord_str!r}")

    def ddm_to_dd(deg, dec_min, hem):
        dd = float(deg) + float(dec_min) / 60.0
        if hem.upper() in ("S", "W"):
            dd = -dd
        return dd

    lat = ddm_to_dd(*matches[0])
    lon = ddm_to_dd(*matches[1])
    return lat, lon


def _parse_utm(coord_str):
    """
    Parse UTM: '52S 123456 7890123' or '52 S 123456E 7890123N'.
    Uses arcpy ConvertCoordinateNotation (positional args).
    Returns (lat, lon).
    """
    tmp_in  = r"memory\ccm_utm_in"
    tmp_out = r"memory\ccm_utm_out"

    # Normalise UTM string — keep zone+band + easting + northing
    s = coord_str.strip().upper()

    try:
        for tbl in (tmp_in, tmp_out):
            if arcpy.Exists(tbl):
                arcpy.management.Delete(tbl)

        arcpy.management.CreateTable("memory", "ccm_utm_in")
        arcpy.management.AddField(tmp_in, "UTM_STR", "TEXT", field_length=40)

        with arcpy.da.InsertCursor(tmp_in, ["UTM_STR"]) as cur:
            cur.insertRow([s])

        # Clear outputCoordinateSystem so ConvertCoordinateNotation output
        # geometry is always in WGS84 (not a projected CRS from Step 2).
        _saved_ocs = arcpy.env.outputCoordinateSystem
        arcpy.env.outputCoordinateSystem = None
        try:
            arcpy.management.ConvertCoordinateNotation(
                tmp_in, tmp_out,
                "UTM_STR", "UTM_STR",
                "UTM", "DD",
                "",
                arcpy.SpatialReference(4326),
            )
        finally:
            arcpy.env.outputCoordinateSystem = _saved_ocs

        # Use the robust helper — DD attribute fields first, then SHAPE@
        # with sanity check, then alias lookup.
        return _read_latlon_from_ccn_table(tmp_out)

    except arcpy.ExecuteError as ae:
        raise ValueError(f"Failed to convert UTM '{coord_str}': {ae}") from ae

    finally:
        for tbl in (tmp_in, tmp_out):
            try:
                if arcpy.Exists(tbl):
                    arcpy.management.Delete(tbl)
            except Exception:
                pass


def _mgrs_to_latlon_arcpy(mgrs_clean):
    """
    Convert a clean (no-space) MGRS string to (lat, lon) via arcpy.
    Uses positional arguments for ConvertCoordinateNotation.
    """
    tmp_in  = r"memory\ccm_mgrs_in"
    tmp_out = r"memory\ccm_mgrs_out"

    try:
        for tbl in (tmp_in, tmp_out):
            if arcpy.Exists(tbl):
                arcpy.management.Delete(tbl)

        arcpy.management.CreateTable("memory", "ccm_mgrs_in")
        arcpy.management.AddField(tmp_in, "MGRS_STR", "TEXT", field_length=30)

        with arcpy.da.InsertCursor(tmp_in, ["MGRS_STR"]) as cur:
            cur.insertRow([mgrs_clean])

        # NOTE: Clear outputCoordinateSystem before conversion so that the
        # output geometry (and attribute fields) is always in WGS84 decimal
        # degrees — not re-projected to whatever projected CRS Step 2 set.
        _saved_ocs = arcpy.env.outputCoordinateSystem
        arcpy.env.outputCoordinateSystem = None
        try:
            arcpy.management.ConvertCoordinateNotation(
                tmp_in, tmp_out,
                "MGRS_STR", "MGRS_STR",
                "MGRS", "DD",
                "",
                arcpy.SpatialReference(4326),
            )
        finally:
            arcpy.env.outputCoordinateSystem = _saved_ocs

        # Use the robust helper — tries DD attribute fields first (always
        # decimal degrees), then SHAPE@ with sanity check, then alias lookup.
        return _read_latlon_from_ccn_table(tmp_out)

    except arcpy.ExecuteError as ae:
        raise ValueError(f"Failed to convert MGRS '{mgrs_clean}': {ae}") from ae

    finally:
        for tbl in (tmp_in, tmp_out):
            try:
                if arcpy.Exists(tbl):
                    arcpy.management.Delete(tbl)
            except Exception:
                pass


# ─── PUBLIC API ──────────────────────────────────────────────────────────────

def any_to_latlon(coord_str):
    """
    Convert any supported coordinate string to (lat, lon) WGS84 decimal degrees.

    Supported formats: MGRS, DD, DMS, DDM, UTM.
    Auto-detects the format.

    Parameters
    ----------
    coord_str : str
        Coordinate in any supported format.

    Returns
    -------
    (lat, lon) : tuple of float
        WGS84 decimal degrees.

    Raises
    ------
    ValueError
        If the format cannot be detected or conversion fails.
    """
    if not coord_str or not coord_str.strip():
        raise ValueError("Empty coordinate string.")

    fmt = detect_format(coord_str)

    if fmt == "MGRS":
        mgrs_clean = normalise_mgrs(coord_str)
        return _mgrs_to_latlon_arcpy(mgrs_clean)
    elif fmt == "DD":
        return _parse_dd(coord_str)
    elif fmt == "DMS":
        return _parse_dms(coord_str)
    elif fmt == "DDM":
        return _parse_ddm(coord_str)
    elif fmt == "UTM":
        return _parse_utm(coord_str)
    else:
        raise ValueError(
            f"Unrecognised coordinate format: {coord_str!r}\n"
            "Supported: MGRS, Decimal Degrees (DD), DMS, DDM, UTM"
        )


# Keep backward-compatible alias
def mgrs_to_latlon(mgrs_str):
    """Backward-compatible wrapper. Use any_to_latlon() for new code."""
    mgrs_clean = normalise_mgrs(mgrs_str)
    ok, err = validate_mgrs(mgrs_clean)
    if not ok:
        raise ValueError(err)
    return _mgrs_to_latlon_arcpy(mgrs_clean)


def latlon_to_all_formats(lat, lon):
    """
    Convert WGS84 (lat, lon) decimal degrees to all supported formats.

    Returns
    -------
    dict with keys: 'mgrs', 'dd', 'dms', 'ddm', 'utm'
    Values are human-readable strings.
    """
    result = {}

    # ── DD ──────────────────────────────────────────────────────────────────
    lat_hem = "N" if lat >= 0 else "S"
    lon_hem = "E" if lon >= 0 else "W"
    result["dd"] = f"{abs(lat):.6f}°{lat_hem}  {abs(lon):.6f}°{lon_hem}"

    # ── DMS ─────────────────────────────────────────────────────────────────
    def dd_to_dms_str(dd, pos_hem, neg_hem):
        hem = pos_hem if dd >= 0 else neg_hem
        dd_abs = abs(dd)
        deg = int(dd_abs)
        mins_float = (dd_abs - deg) * 60
        mins = int(mins_float)
        secs = (mins_float - mins) * 60
        return f"{deg:03d}°{mins:02d}'{secs:05.2f}\"{hem}"

    result["dms"] = (
        dd_to_dms_str(lat, "N", "S") + "  " + dd_to_dms_str(lon, "E", "W")
    )

    # ── DDM ─────────────────────────────────────────────────────────────────
    def dd_to_ddm_str(dd, pos_hem, neg_hem):
        hem = pos_hem if dd >= 0 else neg_hem
        dd_abs = abs(dd)
        deg = int(dd_abs)
        mins = (dd_abs - deg) * 60
        return f"{deg:03d}°{mins:08.5f}'{hem}"

    result["ddm"] = (
        dd_to_ddm_str(lat, "N", "S") + "  " + dd_to_ddm_str(lon, "E", "W")
    )

    # ── MGRS and UTM via arcpy ───────────────────────────────────────────────
    tmp_in  = r"memory\ccm_fmt_in"
    tmp_out = r"memory\ccm_fmt_out"

    def _arcpy_convert(out_fmt, out_fields):
        """Run arcpy ConvertCoordinateNotation and return requested fields."""
        try:
            for tbl in (tmp_in, tmp_out):
                if arcpy.Exists(tbl):
                    arcpy.management.Delete(tbl)

            arcpy.management.CreateTable("memory", "ccm_fmt_in")
            arcpy.management.AddField(tmp_in, "LAT", "DOUBLE")
            arcpy.management.AddField(tmp_in, "LON", "DOUBLE")

            with arcpy.da.InsertCursor(tmp_in, ["LAT", "LON"]) as cur:
                cur.insertRow([lat, lon])

            # Positional arguments only
            arcpy.management.ConvertCoordinateNotation(
                tmp_in, tmp_out,
                "LON", "LAT",
                "DD", out_fmt,
                "",
                arcpy.SpatialReference(4326),
            )

            actual_fields = _find_ccn_fields(tmp_out, out_fields)
            with arcpy.da.SearchCursor(tmp_out, actual_fields) as cur:
                for row in cur:
                    return list(row)

        except Exception:
            return None
        finally:
            for tbl in (tmp_in, tmp_out):
                try:
                    if arcpy.Exists(tbl):
                        arcpy.management.Delete(tbl)
                except Exception:
                    pass
        return None

    mgrs_vals = _arcpy_convert("MGRS", ["MGRS"])
    result["mgrs"] = mgrs_vals[0].strip() if mgrs_vals else "N/A"

    utm_vals = _arcpy_convert("UTM", ["UTM"])
    result["utm"] = utm_vals[0].strip() if utm_vals else "N/A"

    return result


def format_coord_display(lat, lon, source_fmt=None):
    """
    Return a multi-line string showing the coordinate in all formats.
    Used to populate the read-only display parameter in tool UIs.

    Example output:
        Detected Format : MGRS
        MGRS            : 52SBB1234567890
        DD              : 37.123456°N  127.654321°E
        DMS             : 037°07'24.44"N  127°39'15.56"E
        DDM             : 037°07.40733'N  127°39.25933'E
        UTM             : 52 S 612345 4112345
    """
    try:
        fmts = latlon_to_all_formats(lat, lon)
        lines = []
        if source_fmt:
            lines.append(f"Detected Format : {source_fmt}")
        lines.append(f"MGRS            : {fmts['mgrs']}")
        lines.append(f"DD              : {fmts['dd']}")
        lines.append(f"DMS             : {fmts['dms']}")
        lines.append(f"DDM             : {fmts['ddm']}")
        lines.append(f"UTM             : {fmts['utm']}")
        return "\n".join(lines)
    except Exception as e:
        return f"(Could not compute equivalent formats: {e})"


def format_latlon_as_mgrs(lat, lon, precision=5):
    """
    Convert WGS84 (lat, lon) decimal degrees to an MGRS string.
    Uses positional arguments for ConvertCoordinateNotation.

    precision : int  (1=10km … 5=1m)  — kept for API compatibility; arcpy
                     always returns 1-m precision, we truncate if needed.
    """
    tmp_in  = r"memory\ccm_dd_in"
    tmp_out = r"memory\ccm_dd_out"

    try:
        for tbl in (tmp_in, tmp_out):
            if arcpy.Exists(tbl):
                arcpy.management.Delete(tbl)

        arcpy.management.CreateTable("memory", "ccm_dd_in")
        arcpy.management.AddField(tmp_in, "LAT", "DOUBLE")
        arcpy.management.AddField(tmp_in, "LON", "DOUBLE")

        with arcpy.da.InsertCursor(tmp_in, ["LAT", "LON"]) as cur:
            cur.insertRow([lat, lon])

        # Positional arguments only
        arcpy.management.ConvertCoordinateNotation(
            tmp_in, tmp_out,
            "LON", "LAT",
            "DD", "MGRS",
            "",
            arcpy.SpatialReference(4326),
        )

        mgrs_f, = _find_ccn_fields(tmp_out, ["MGRS"])
        with arcpy.da.SearchCursor(tmp_out, [mgrs_f]) as cur:
            for row in cur:
                return str(row[0]).strip()

        raise ValueError(f"ConvertCoordinateNotation produced no MGRS output for ({lat}, {lon})")

    except arcpy.ExecuteError as ae:
        raise ValueError(f"Failed to convert ({lat}, {lon}) to MGRS: {ae}") from ae

    finally:
        for tbl in (tmp_in, tmp_out):
            try:
                if arcpy.Exists(tbl):
                    arcpy.management.Delete(tbl)
            except Exception:
                pass


# ─── CRS / PROJECTION VALIDATION HELPERS (v0.54.4) ────────────────────────────
#
# CCM's terrain-analysis geoprocessing (cost-distance / DistanceAccumulation,
# slope derivation, buffers, area & length statistics) requires linear units
# in metres.  A Geographic CRS (e.g. WGS84 / GCS_WGS_1984) stores coordinates
# in degrees, which are not a constant real-world distance — 1 degree of
# longitude shrinks from ~111 km at the equator toward the poles — so running
# those tools on unprojected data would silently compute wrong distances and
# areas rather than raise an error.  These helpers build the standard
# smart-warning text shared by Step 0 (output_sr), Step 1 (Analysis Extent —
# blocking error — and its supporting layers), Step 3 (Speed Surface FC /
# obstacle layers) and Step 4 (Vehicle A/B Speed Surfaces), so the wording and
# the "how to fix" guidance stay consistent across the toolbox.  See User
# Manual Section 3.4 for the full beginner-level explanation.

def describe_spatial_reference(path):
    """
    Return (sr_type, sr_name, factory_code) for a feature class / raster
    path, or (None, None, None) if it cannot be described (missing, locked,
    corrupt, etc.).  Never raises — callers can use this inside
    updateMessages() without wrapping every call site in its own try/except.
    """
    try:
        sr = arcpy.Describe(path).spatialReference
        return sr.type, sr.name, getattr(sr, "factoryCode", None)
    except Exception:
        return None, None, None


def geographic_crs_warning(layer_label, sr_name, blocking=False):
    """
    Standard warning/error text for a layer that uses a Geographic CRS
    instead of a Projected CRS.

    layer_label : str   -- human-readable parameter/layer name, e.g. "DEM"
    sr_name     : str   -- d.spatialReference.name from arcpy.Describe
    blocking    : bool  -- wording only ("must" vs "should"); the caller
                           decides whether to call setErrorMessage() or
                           setWarningMessage() with the returned text
    """
    verb = "must" if blocking else "should"
    return (
        f"{layer_label} uses a Geographic CRS ({sr_name}).\n\n"
        f"CCM {verb} use a Projected CRS (e.g. UTM) so that distances and "
        "areas are computed in metres — a Geographic CRS stores coordinates "
        "in degrees, which are not a constant real-world distance.\n"
        "How to fix: right-click the layer in ArcGIS Pro -> Data -> Export "
        "Features -> set the output CRS to the UTM zone covering your study "
        "area, then use the reprojected feature class here.  See User "
        "Manual Section 3.4 for details."
    )


def crs_mismatch_warning(layer_label, layer_sr_name, ref_label, ref_sr_name):
    """
    Standard warning text for two layers that are both projected but use
    DIFFERENT coordinate systems.  Being "Projected" is not enough by
    itself — mismatched projections still misalign layers and can skew
    distance/area results even though neither would fail a Geographic-CRS
    check on its own.
    """
    return (
        f"{layer_label} ({layer_sr_name}) uses a different coordinate "
        f"system than {ref_label} ({ref_sr_name}).\n\n"
        "Mixing coordinate systems across CCM inputs can silently misalign "
        "layers even though both are projected.\n"
        f"How to fix: reproject {layer_label} to match {ref_label} "
        "(ArcGIS Pro -> Data -> Export Features, set the output CRS), then "
        "use the reprojected feature class here."
    )
# <<< END OF FILE >>>
