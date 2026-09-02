# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
r"""Factual text and HTML reports for CCM Data Intelligence v0.59.6.

This release reports measured or directly observed inventory facts only.
Quality, Fitness, automatic selection, substitution scoring, Confidence, and
project Readiness are computed by the *other* Step 0b engines
(``ccm_data_quality``, ``ccm_data_fitness``, ``ccm_data_confidence``,
``ccm_data_readiness``, ``ccm_data_selector``) -- this module still computes
none of them itself.

What changed for the Green / Yellow / Red status overlay
----------------------------------------------------------
This module now accepts two OPTIONAL, already-computed dicts from the
caller: ``quality_scores`` (the exact object written to
``ccm_quality_scores.json``) and ``recommendations`` (the exact object
written to ``ccm_recommendations.json``), both produced by
``ccm_step0b_integration.Step0bIntegrator``. When supplied, the report reads
values out of them to colour a status badge; it never derives a new score.
When omitted -- as they always are for the legacy, scoring-free
``run_scan()`` / ``--factual-only`` path -- every score-dependent badge
degrades honestly to a grey "not scored" / "not available" marker instead of
guessing. The underlying ``catalog`` object is never mutated (the "quality",
"fitness", "confidence" keys already reserved on every record stay ``None``,
exactly as the factual catalog contract requires).

Status colour rules (identical wording appears in the in-report legend)
-------------------------------------------------------------------------
  CRS          green = measured + Projected. yellow = measured + Geographic
               (works, but needs reprojection before Step 1). red = not
               measured.
  Completeness green = AOI coverage >=90%. yellow = 50-89%. red = <50%.
               grey when no analysis extent was supplied to Step 0b at all
               (nothing to measure against, not a data problem).
  Error        green = native compatibility, no limitations, one copy.
               yellow = convertible compatibility, or limitations present,
               or duplicate copies found. red = unsupported/incompatible.
  Accuracy     from the caller-supplied quality_score (the 0-10 composite
               ccm_data_quality.DataQualityScorer already computes): green
               >=7, yellow 4-6.9, red <4. grey when quality_scores was not
               supplied.
  Suggested    from the caller-supplied recommendations
               (ccm_data_selector.DataSelector): green = recommended with
               High confidence, yellow = recommended with Moderate/Low
               confidence, red = MANUAL_SELECTION_REQUIRED or Unvetted. grey
               when recommendations was not supplied.

A role's overall badge, and the report-wide banner, are the worst
(red > yellow > green) of their non-grey dimensions; all-grey rolls up to
grey rather than being treated as bad.
"""

import html
import os
import textwrap

import ccm_data_catalog as _cat

VERSION = "0.59.7"  # v0.59.2 -- bumped by bump_version.py from v0.57. Review this line's comment.
TEXT_FILENAME = "CCM_Data_Intelligence_Report.txt"
HTML_FILENAME = "CCM_Data_Intelligence_Report.html"


MISSING_IMPACTS = {
    "dem": ("No slope source is available. Step 1 would otherwise use a "
            "flat-terrain assumption, which can overestimate trafficability."),
    "soil": ("Soil strength cannot be prepared from a dedicated source. "
             "Soft-ground effects would remain unverified."),
    "veg": ("Vegetation density and spacing cannot be prepared from a "
            "dedicated source."),
    "hydro": ("Water obstacles may be absent from later mobility analysis."),
    "contours": ("Contour support is unavailable. This is usually non-blocking "
                 "when a valid DEM is present."),
    "moisture": ("Spatial soil-moisture variation is unavailable; a later run "
                 "must use another configured moisture method."),
    "vehicle": ("A valid vehicle table is required before mobility analysis."),
    "extent": ("A projected polygon analysis extent is required before "
               "preprocessing and mobility analysis."),
}

# Roles whose absence is documented above as non-blocking / backed by a
# configured fallback elsewhere in the workflow. Missing anything NOT in
# this set is treated as a red (blocking) status; missing one of these is
# yellow instead of red.
_SOFT_MISSING_ROLES = {"contours", "moisture"}

# ccm_data_selector.DataSelector.recommend_all_roles() only evaluates these
# seven roles today, keyed by Title-Case strings that do NOT line up 1:1
# with ccm_data_catalog's lowercase role keys and ROLE_LABELS text (e.g.
# role key "vehicle" maps to selector key "Vehicle", not to ROLE_LABELS'
# "Vehicle Database"; role key "extent" maps to selector key "Extent", not
# to ROLE_LABELS' "Analysis Extent (AOI)"). This is the explicit bridge
# between the two vocabularies. "moisture" and "mgcp" have no counterpart in
# the recommendation engine and always render as not-available here.
_ROLE_KEY_TO_SELECTOR_KEY = {
    _cat.ROLE_DEM: "DEM",
    _cat.ROLE_SOIL: "Soil",
    _cat.ROLE_VEG: "Vegetation",
    _cat.ROLE_HYDRO: "Hydrology",
    _cat.ROLE_CONTOURS: "Contours",
    _cat.ROLE_EXTENT: "Extent",
    _cat.ROLE_VEHICLE: "Vehicle",
}


def _basename(path):
    text = str(path or "")
    if _cat._CONTAINER_SEPARATOR in text:
        container, layer = text.split(_cat._CONTAINER_SEPARATOR, 1)
        return "%s :: %s" % (os.path.basename(container), layer)
    return os.path.basename(text)


def _resolution(rec):
    res = rec.get("resolution") or {}
    if res.get("display"):
        return str(res["display"])
    if res.get("cell_size_m") is not None:
        prefix = "~" if res.get("cell_size_is_approximate") else ""
        return "%s%.4g m" % (prefix, float(res["cell_size_m"]))
    if res.get("feature_count") is not None:
        return "%s feature(s)" % res["feature_count"]
    if res.get("row_count") is not None:
        suffix = "+" if res.get("row_count_is_lower_bound") else ""
        return "%s%s row(s)" % (res["row_count"], suffix)
    return "not measured"


def _crs(rec):
    crs = rec.get("crs") or {}
    name = crs.get("name") or "not measured"
    epsg = crs.get("epsg")
    if epsg and "EPSG:%s" % epsg not in str(name):
        return "%s (EPSG:%s)" % (name, epsg)
    return str(name)


def _coverage(rec):
    value = rec.get("coverage_aoi_pct")
    if value is None:
        return "not measured"
    return "%.1f%% (%s)" % (
        float(value), rec.get("coverage_basis") or "method not recorded")


def _schema(rec):
    schema = rec.get("schema") or {}
    if not schema:
        return "not evaluated"
    required = schema.get("required") or []
    if not required:
        return "no role-specific required fields"
    present = schema.get("present") or []
    return "%d/%d required field(s) present" % (len(present), len(required))


def _wrap(lines, prefix, text, width):
    wrapped = textwrap.wrap(str(text), width=max(20, width - len(prefix))) or [""]
    lines.append(prefix + wrapped[0])
    pad = " " * len(prefix)
    lines.extend(pad + part for part in wrapped[1:])


# ===========================================================================
# Status model -- four flat colour states, "worst wins" rollups.
#
# Every function below either reads a fact already present on a catalog
# record, or looks up a value in a pre-computed dict the caller supplied.
# None of them compute a new judgement that ccm_data_quality,
# ccm_data_confidence, or ccm_data_selector do not already make.
# ===========================================================================
GREEN, YELLOW, RED, GREY = "green", "yellow", "red", "grey"
_RANK = {GREEN: 0, GREY: 1, YELLOW: 2, RED: 3}
_WORD = {GREEN: "GREEN", YELLOW: "YELLOW", RED: "RED", GREY: "N/A"}
_HTML_ICON = {GREEN: "✓", YELLOW: "⚠", RED: "✕", GREY: "–"}

_LEGEND = (
    (GREEN, "Green", "good -- no action needed"),
    (YELLOW, "Yellow", "review recommended"),
    (RED, "Red", "action required"),
    (GREY, "Grey", "not measured / not scored"),
)


def _worse(a, b):
    """Return whichever of two statuses ranks worse (red > yellow > grey > green)."""
    return a if _RANK[a] >= _RANK[b] else b


def _rollup(statuses):
    """Worst-of a list of statuses, ignoring GREY unless everything is GREY."""
    informative = [s for s in statuses if s != GREY]
    if not informative:
        return GREY
    worst = informative[0]
    for status in informative[1:]:
        worst = _worse(worst, status)
    return worst


# Dataset types with no spatial reference of their own (a plain CSV/table,
# or a file type CCM does not otherwise classify). CRS and AOI-coverage
# percentage are not meaningful for these -- a Vehicle CSV table, for
# instance, always legitimately has crs={} and coverage_aoi_pct=None, and
# that must read as "not applicable", never as a red flag on an otherwise
# fine dataset.
_NON_SPATIAL_TYPES = {"table", "csv", "other"}


# v0.59.7 -- Web Mercator is PROJECTED but not measurable. Its scale factor
# is 1/cos(latitude): ~1.19 at 33 deg N, ~1.22 at 35 deg N, so at the AOI_Lebanon
# test site every distance CCM derives is ~20% too long, every area ~45% too
# large, and slope, speed, isochrone and route length inherit the same error.
# The old check asked only "is it projected?", which Web Mercator passes, so a
# Web Mercator AOI -- the default CRS of anything digitised over a basemap,
# and exactly what the field test used -- sailed through green while silently
# biasing the whole mobility model. EPSG 3857 is the current code; 900913 and
# Esri's 102100/102113 are the legacy ones still stamped on older data.
_WEB_MERCATOR_EPSG = frozenset((3857, 900913, 102100, 102113))


def _is_web_mercator(crs):
    epsg = (crs or {}).get("epsg")
    try:
        if epsg is not None and int(epsg) in _WEB_MERCATOR_EPSG:
            return True
    except (TypeError, ValueError):
        pass
    name = str((crs or {}).get("name") or "").lower()
    return "mercator_auxiliary_sphere" in name or "web_mercator" in name \
        or "web mercator" in name or "pseudo-mercator" in name


def _status_crs(rec):
    if rec.get("dataset_type") in _NON_SPATIAL_TYPES:
        return GREY, "not applicable (non-spatial dataset)"
    crs = rec.get("crs") or {}
    kind = crs.get("type")
    if kind == "Projected":
        if _is_web_mercator(crs):
            # No fixed percentage here: Mercator scale error is
            # 1/cos(latitude) -- 0.4% at 5 deg, 21% at 34 deg, 100% at 60 deg --
            # and this module reports observed facts, not assumed ones.
            # Step 1 computes the actual figure from the AOI centroid.
            return YELLOW, ("Web Mercator -- projected but not measurable "
                            "(scale error grows as 1/cos(latitude)); "
                            "use the local UTM zone")
        return GREEN, "Projected"
    if kind == "Geographic":
        return YELLOW, "Geographic -- needs reprojection before Step 1"
    return RED, "not measured"


def _status_coverage(rec, aoi_supplied):
    if rec.get("dataset_type") in _NON_SPATIAL_TYPES:
        return GREY, "not applicable (non-spatial dataset)"
    if not aoi_supplied:
        return GREY, "not evaluated (no analysis extent supplied)"
    value = rec.get("coverage_aoi_pct")
    if value is None:
        return GREY, "not measured"
    try:
        pct = float(value)
    except (TypeError, ValueError):
        return GREY, "not measured"
    detail = "%.0f%% of AOI" % pct
    if pct >= 90:
        return GREEN, detail
    if pct >= 50:
        return YELLOW, detail
    return RED, detail


def _status_error(rec):
    compat = rec.get("compatibility")
    status = GREEN
    reasons = []
    if compat not in ("native", "convertible"):
        status = _worse(status, RED)
        reasons.append("compatibility: %s" % (compat or "not determined"))
    elif compat == "convertible":
        status = _worse(status, YELLOW)
        reasons.append("needs conversion")
    copies = len(rec.get("locations") or [])
    if copies > 1:
        status = _worse(status, YELLOW)
        reasons.append("%d duplicate copy/copies" % (copies - 1))
    limitations = rec.get("limitations") or []
    if limitations:
        status = _worse(status, YELLOW)
        reasons.append("%d limitation(s) noted" % len(limitations))
    if not reasons:
        reasons.append("no known issues")
    return status, ", ".join(reasons)


def _status_accuracy(quality_score):
    if quality_score is None:
        return GREY, "not scored"
    try:
        score = float(quality_score)
    except (TypeError, ValueError):
        return GREY, "not scored"
    detail = "%.1f/10" % score
    if score >= 7:
        return GREEN, detail
    if score >= 4:
        return YELLOW, detail
    return RED, detail


def _status_suggested(role_key, recommendations):
    if not recommendations:
        return GREY, "not available (run the integrated Step 0b scan)"
    selector_key = _ROLE_KEY_TO_SELECTOR_KEY.get(role_key)
    if not selector_key:
        return GREY, "not evaluated for this role"
    selection = (recommendations.get("selections") or {}).get(selector_key)
    if not selection:
        return GREY, "not evaluated for this role"
    recommended = selection.get("recommended")
    if not recommended or recommended == "MANUAL_SELECTION_REQUIRED":
        return RED, "manual selection required"
    confidence = (selection.get("metrics") or {}).get("confidence")
    if confidence == "High":
        return GREEN, "%s (High confidence)" % recommended
    if confidence in ("Moderate", "Low"):
        return YELLOW, "%s (%s confidence)" % (recommended, confidence)
    return RED, "%s (%s)" % (recommended, confidence or "Unvetted")


def _status_role_presence(role_key, records, aoi_supplied, is_missing):
    """``is_missing`` comes from ``catalog["missing_roles"]`` -- the same
    list section 4 (Missing CCM roles) already treats as authoritative --
    rather than being re-derived from an empty ``records`` list here. The
    two can disagree: MGCP, for example, is tracked outside the normal
    per-role bucket and is never placed in ``missing_roles`` even when its
    bucket has zero records, so a naive "no records -> red" rule would
    contradict section 4. Trusting ``is_missing`` keeps this dashboard and
    section 4 in agreement."""
    if is_missing:
        if role_key in _SOFT_MISSING_ROLES:
            return YELLOW, "no dataset detected (non-blocking role)"
        return RED, "no dataset detected"
    if not records:
        return GREY, "not evaluated for this role"
    if all(rec.get("dataset_type") in _NON_SPATIAL_TYPES for rec in records):
        # A role that is inherently non-spatial (e.g. the Vehicle CSV table)
        # has nothing further to check for "completeness" once detected --
        # AOI coverage simply does not apply, so presence is Green rather
        # than an uninformative Grey.
        return GREEN, "%d dataset(s) detected (non-spatial)" % len(records)
    # v0.59.7 -- Judge the ROLE on how much of the AOI its datasets cover
    # TOGETHER, not on its worst single member -- but never claim more
    # confidence than the arithmetic supports.
    #
    # Elevation, land cover and soil products ship as TILE SETS. A real scan
    # of a Lebanon AOI held 11 SRTM tiles: the four over the AOI measured
    # 23.6 / 26.2 / 23.6 / 26.2 % each (~100% mosaicked, exactly as expected),
    # while the seven neighbours simply lie outside it and measured 0%.
    # Rolling those up worst-first painted DEM -- and by the same mechanism
    # Soil, Vegetation and Hydrology -- solid RED on fully covered data. A
    # tile outside the AOI is an unused tile, not a defect.
    #
    # But summing per-dataset coverage cannot tell four tiles that mosaic to
    # 100% from three products that each cover the SAME 40%: both sum to
    # >=100. Overlap is not measured here, so the sum is an upper bound and
    # only ever earns YELLOW ("verify the mosaic"), never GREEN. GREEN
    # requires one dataset that covers the AOI on its own -- something
    # actually measured. Per-dataset coverage stays visible in section 2.
    if not aoi_supplied:
        return GREY, ("%d dataset(s) detected; coverage not evaluated "
                      "(no analysis extent supplied)" % len(records))

    cov_pcts = []
    for rec in records:
        if rec.get("dataset_type") in _NON_SPATIAL_TYPES:
            continue
        value = rec.get("coverage_aoi_pct")
        if value is None:
            continue
        try:
            cov_pcts.append(float(value))
        except (TypeError, ValueError):
            continue

    if not cov_pcts:
        cov_status = _rollup(
            [_status_coverage(rec, aoi_supplied)[0] for rec in records])
        if cov_status == GREY:
            return GREY, ("%d dataset(s) detected; coverage not evaluated"
                          % len(records))
        return cov_status, "%d dataset(s) detected" % len(records)

    best = max(cov_pcts)
    if best >= 90.0:
        return GREEN, ("%d dataset(s) detected; best single dataset covers "
                       "%.0f%% of AOI" % (len(records), best))

    contributing = [pct for pct in cov_pcts if pct > 0.0]
    combined = min(100.0, sum(cov_pcts))
    if len(contributing) > 1:
        detail = ("%d dataset(s) detected; up to ~%.0f%% of AOI combined "
                  "across %d (upper bound -- overlap between them is not "
                  "measured, verify the mosaic)"
                  % (len(records), combined, len(contributing)))
    else:
        detail = "%d dataset(s) detected; covers %.0f%% of AOI" % (
            len(records), best)

    if combined >= 50.0:
        return YELLOW, detail
    return RED, detail


def _quality_map(quality_scores):
    scores = (quality_scores or {}).get("scores") or []
    return {s.get("dataset"): s.get("quality_score")
            for s in scores if s.get("dataset")}


def _role_best_quality(records, qmap):
    values = [qmap[rec.get("name")] for rec in records
              if rec.get("name") in qmap and qmap[rec.get("name")] is not None]
    return max(values) if values else None


def _dashboard_rows(catalog, quality_scores=None, recommendations=None):
    """One status summary per CCM role -- the shared source of truth for
    both the HTML dashboard/badges and the text-report status lines."""
    aoi_supplied = bool(catalog.get("aoi"))
    qmap = _quality_map(quality_scores)
    roles = catalog.get("roles") or {}
    missing_roles = set(catalog.get("missing_roles") or [])
    rows = []
    for role in _cat.CCM_ROLES:
        records = (roles.get(role) or {}).get("records") or []
        label = _cat.ROLE_LABELS.get(role, role)

        presence_status, presence_detail = _status_role_presence(
            role, records, aoi_supplied, role in missing_roles)
        crs_status = (_rollup([_status_crs(rec)[0] for rec in records])
                      if records else GREY)
        error_status = (_rollup([_status_error(rec)[0] for rec in records])
                        if records else GREY)
        accuracy_status, accuracy_detail = _status_accuracy(
            _role_best_quality(records, qmap))
        suggested_status, suggested_detail = _status_suggested(
            role, recommendations)

        overall = _rollup([presence_status, crs_status, error_status,
                            accuracy_status, suggested_status])

        rows.append({
            "role": role,
            "label": label,
            "count": len(records),
            "presence": (presence_status, presence_detail),
            "crs": (crs_status, None),
            "error": (error_status, None),
            "accuracy": (accuracy_status, accuracy_detail),
            "suggested": (suggested_status, suggested_detail),
            "overall": overall,
        })
    return rows


def _banner_status(recommendations, rows):
    model_conf = (recommendations or {}).get("model_confidence")
    mapping = {"Acceptable": GREEN, "Conditional": YELLOW,
               "At-Risk": RED, "Incomplete": RED}
    if model_conf in mapping:
        return mapping[model_conf], "Model confidence: %s" % model_conf
    fallback = _rollup([row["overall"] for row in rows])
    fallback_text = {
        GREEN: "No blocking issues found in the factual inventory",
        YELLOW: "Some roles need review before Step 1",
        RED: "One or more roles need attention before Step 1",
        GREY: "Not enough information to summarise yet",
    }[fallback]
    return fallback, fallback_text


def _recommended_name_for_role(role_key, recommendations):
    """The dataset name the recommendation engine picked for this role, if
    any -- used to flag the matching card in section 2 with a star."""
    if not recommendations:
        return None
    selector_key = _ROLE_KEY_TO_SELECTOR_KEY.get(role_key)
    if not selector_key:
        return None
    selection = (recommendations.get("selections") or {}).get(selector_key)
    if not selection:
        return None
    recommended = selection.get("recommended")
    if not recommended or recommended == "MANUAL_SELECTION_REQUIRED":
        return None
    return recommended


def render_text(catalog, width=88, quality_scores=None, recommendations=None):
    """Return a factual, line-oriented inventory report.

    ``quality_scores`` / ``recommendations`` are optional pre-computed dicts
    (see module docstring); when omitted, every status line honestly reads
    N/A instead of a colour.
    """
    lines = []
    rule = "=" * width
    thin = "-" * width
    lines.extend([
        rule,
        "CCM DATA INTELLIGENCE - FACTUAL INVENTORY",
        "Version: %s" % (catalog.get("ccm_version") or VERSION),
        "Created: %s" % (catalog.get("created") or "unknown"),
        "Data root: %s" % (catalog.get("data_root") or "not supplied"),
        "Metadata backend: %s" % (catalog.get("backend") or "unknown"),
        rule,
        "",
    ])
    if catalog.get("error"):
        lines.append("ERROR: %s" % catalog["error"])
        return lines

    # v0.59.7 -- A .gdb/.gpkg this scan could not open shows up nowhere else
    # in the report: everything inside it is simply absent from every role
    # below, which reads exactly like "no data found" even when the data is
    # sitting right there in the file. Say so explicitly, up front, before
    # the analyst reads a wall of red/missing roles and concludes the wrong
    # thing.
    # v0.59.7 -- Folders deliberately left out of the scan are stated, never
    # merely dropped: a role that reads "not found" because its folder was
    # pruned looks exactly like a role whose data does not exist.
    skipped = catalog.get("skipped_dirs") or []
    if skipped:
        lines.append(
            "NOTE: %d folder(s) were skipped as CCM tool files or test "
            "scaffolding, not analyst data:" % len(skipped))
        for entry in skipped[:10]:
            lines.append("    - %s" % entry)
        if len(skipped) > 10:
            lines.append("    ... and %d more" % (len(skipped) - 10))
        lines.append(
            "  If your own data lives in one of these, move it outside that "
            "folder and re-scan.")
        lines.append("")

    unreadable = catalog.get("unreadable_containers") or []
    if unreadable:
        _no_backend = (catalog.get("backend") or "") == "header"
        lines.append("!" * width)
        lines.append(
            "%s: %d geodatabase/GeoPackage container(s) yielded no readable "
            "dataset -- nothing inside them is reflected below:"
            % ("WARNING" if _no_backend else "NOTE", len(unreadable)))
        for u in unreadable[:15]:
            lines.append("    - %s" % u)
        if len(unreadable) > 15:
            lines.append("    ... and %d more" % (len(unreadable) - 15))
        if _no_backend:
            lines.append(
                "  Reason: this scan ran without arcpy or GDAL available "
                "(pure-Python header reader only), which cannot look inside "
                "a File Geodatabase or GeoPackage.")
            lines.append(
                "  Fix: run the CCM Data Intelligence tool from inside "
                "ArcGIS Pro (Geoprocessing pane -- it has arcpy), or run "
                "this scanner from a Python environment with GDAL/OGR "
                "installed.")
        else:
            # arcpy/GDAL WAS available, so the container opened fine and
            # simply held nothing -- an empty project GDB, for instance.
            # Saying "could not be read" here would be a false alarm.
            lines.append(
                "  This scan had a full metadata backend, so these opened "
                "correctly and are empty (a newly created project GDB, for "
                "example). No action needed unless you expected data in one.")
        lines.append("!" * width)
        lines.append("")

    rows = _dashboard_rows(catalog, quality_scores=quality_scores,
                           recommendations=recommendations)
    banner_status, banner_text = _banner_status(recommendations, rows)

    lines.extend([
        "STATUS LEGEND: " + "  ".join(
            "[%-6s] %s" % (_WORD[status], meaning)
            for status, _name, meaning in _LEGEND),
        "",
        "0. STATUS DASHBOARD", thin,
        "[%-6s] %s" % (_WORD[banner_status], banner_text),
        "",
    ])
    for row in rows:
        lines.append("  [%-6s] %-24s presence=%s crs=%s error=%s "
                     "accuracy=%s suggested=%s"
                     % (_WORD[row["overall"]], row["label"],
                        _WORD[row["presence"][0]], _WORD[row["crs"][0]],
                        _WORD[row["error"][0]], _WORD[row["accuracy"][0]],
                        _WORD[row["suggested"][0]]))
    lines.append("")

    stats = catalog.get("stats") or {}
    lines.extend([
        "1. SCAN SUMMARY", thin,
        "Files inspected: %s" % stats.get("files_scanned", 0),
        "Datasets catalogued: %s" % stats.get("datasets_catalogued", 0),
        "Unclassified files: %s" % stats.get("unclassified", 0),
        "Duplicate groups: %s" % stats.get("duplicate_groups", 0),
        "", "2. DETECTED DATA", thin,
    ])

    roles = catalog.get("roles") or {}
    for role in _cat.CCM_ROLES:
        records = (roles.get(role) or {}).get("records") or []
        label = _cat.ROLE_LABELS.get(role, role)
        row = next(r for r in rows if r["role"] == role)
        lines.append("%s (%d)  [%-6s overall]"
                     % (label, len(records), _WORD[row["overall"]]))
        if not records:
            lines.append("  - none detected")
            continue
        recommended_name = _recommended_name_for_role(role, recommendations)
        qmap = _quality_map(quality_scores)
        for rec in records:
            crs_status, crs_detail = _status_crs(rec)
            cov_status, cov_detail = _status_coverage(rec, bool(catalog.get("aoi")))
            err_status, err_detail = _status_error(rec)
            acc_status, acc_detail = _status_accuracy(qmap.get(rec.get("name")))
            star = "  *** RECOMMENDED SOURCE FOR THIS ROLE ***" \
                if recommended_name and rec.get("name") == recommended_name else ""
            lines.append("  - %s%s" % (_basename(rec.get("path")), star))
            lines.append("      Role basis: %s" % (rec.get("role_basis") or "unknown"))
            lines.append("      Dataset type: %s" % (rec.get("dataset_type") or "unknown"))
            lines.append("      Source type: %s" % (rec.get("source_type") or "unidentified"))
            lines.append("      Resolution/detail: %s" % _resolution(rec))
            lines.append("      CRS: %s  [%-6s %s]"
                         % (_crs(rec), _WORD[crs_status], crs_detail))
            lines.append("      AOI coverage: %s  [%-6s %s]"
                         % (_coverage(rec), _WORD[cov_status], cov_detail))
            lines.append("      Schema: %s" % _schema(rec))
            lines.append("      Compatibility / duplicates / limitations: "
                         "[%-6s %s]" % (_WORD[err_status], err_detail))
            lines.append("      Accuracy (quality score): [%-6s %s]"
                         % (_WORD[acc_status], acc_detail))
            if len(rec.get("locations") or []) > 1:
                lines.append("      Locations: %d identical copies" % len(rec["locations"]))
            for limitation in rec.get("limitations") or []:
                _wrap(lines, "      Limitation: ", limitation, width)
        lines.append("")

    lines.extend(["3. DUPLICATES", thin])
    groups = catalog.get("duplicate_groups") or []
    if not groups:
        lines.append("No duplicate groups detected.")
    else:
        for idx, group in enumerate(groups, 1):
            lines.append("Group %d:  [%-6s duplicate copies found]"
                         % (idx, _WORD[YELLOW]))
            lines.extend("  - %s" % path for path in group)
    lines.append("")

    lines.extend(["4. MISSING CCM ROLES", thin])
    missing = catalog.get("missing_roles") or []
    if not missing:
        lines.append("No inventory role is empty.")
    else:
        for role in missing:
            role_status = YELLOW if role in _SOFT_MISSING_ROLES else RED
            lines.append("- %s  [%-6s]"
                         % (_cat.ROLE_LABELS.get(role, role), _WORD[role_status]))
            if role in MISSING_IMPACTS:
                _wrap(lines, "  Model impact: ", MISSING_IMPACTS[role], width)
    lines.append("")

    lines.extend(["5. COORDINATE SYSTEM", thin])
    recommendation = catalog.get("recommended_crs")
    if recommendation:
        crs_ok = bool(recommendation.get("aoi_matches"))
        lines.append("Suggested project CRS: %s (EPSG:%s)  [%-6s]"
                     % (recommendation.get("name"), recommendation.get("epsg"),
                        _WORD[GREEN if crs_ok else YELLOW]))
        lines.append("Suggestion basis: %s" %
                     (recommendation.get("basis") or "unknown"))
        lines.append("This is a location-based suggestion, not an automatic conversion.")
    else:
        lines.append("A projected CRS suggestion could not be derived from the "
                     "inventory.  [%-6s]" % _WORD[RED])
    lines.append("")

    lines.extend(["6. UNCLASSIFIED FILES", thin])
    unclassified = catalog.get("unclassified") or []
    if not unclassified:
        lines.append("No unclassified files detected.")
    else:
        for rec in unclassified:
            lines.append("- %s (%s)" %
                         (rec.get("path"), rec.get("role_basis") or "unknown"))
    lines.append("")

    lines.extend(["7. SUGGESTED DATA (RECOMMENDATIONS OVERVIEW)", thin])
    if not recommendations:
        lines.append("Not available in this run.  [%-6s] Suggested sources are "
                     "produced by the integrated Step 0b scan (the default); "
                     "re-run without --factual-only to see them here."
                     % _WORD[GREY])
    else:
        for role in _cat.CCM_ROLES:
            selector_key = _ROLE_KEY_TO_SELECTOR_KEY.get(role)
            if not selector_key:
                continue
            status, detail = _status_suggested(role, recommendations)
            lines.append("- %-24s [%-6s] %s"
                         % (_cat.ROLE_LABELS.get(role, role), _WORD[status], detail))
        lines.append("Full alternatives and reasoning: "
                     "CCM_Recommendations_Report.html (written alongside this report).")
    lines.append("")

    lines.extend([
        "8. NEXT STEPS", thin,
        "1. Confirm that each detected role is correct.",
        "2. Resolve CRS, coverage, schema, or compatibility limitations.",
        "3. Select inputs explicitly in CCM Step 1.",
        "4. Treat missing data as unknown/insufficient information, never as No-Go.",
        "",
        "Methodology note: this report is the factual inventory subreport in "
        "v0.59.6. It does not itself calculate Quality, Fitness, Confidence, "
        "Readiness, or an automatic best-source recommendation -- when a "
        "caller supplies pre-computed scores (as CCM Step 0b's integrated "
        "workflow does), sections 0, 2, and 7 above display them as a "
        "read-only overlay sourced entirely from those separate engines.",
        rule,
    ])
    return lines


_CSS = """
:root{--page:#f4f6f8;--surface:#fff;--ink:#17202a;--muted:#5d6d7e;
--line:#d9e2ea;--accent:#1f5f99;--warn:#9a5b00}
*{box-sizing:border-box}body{margin:0;background:var(--page);color:var(--ink);
font:15px/1.55 "Segoe UI",Arial,sans-serif}.wrap{max-width:1180px;margin:auto;padding:28px}
header{background:#123b5d;color:#fff;padding:28px;border-radius:12px}
h1{margin:0 0 6px;font-size:30px}h2{margin:32px 0 12px;font-size:21px}
.sub{opacity:.86}.summary,.role,.panel{background:var(--surface);border:1px solid var(--line);
border-radius:10px;padding:18px;margin:12px 0}.grid{display:grid;
grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px}.fact{background:#f7f9fb;
border-radius:7px;padding:10px}.k{display:block;color:var(--muted);font-size:11px;
text-transform:uppercase;letter-spacing:.06em}.dataset{border-top:1px solid var(--line);
padding:14px 0}.dataset:first-of-type{border-top:0}.name{font-weight:700;font-size:17px}
.pill{display:inline-block;border:1px solid #b8cad8;border-radius:999px;padding:2px 8px;
margin:3px 4px 3px 0;font-size:12px}.lim{color:var(--warn);margin:5px 0}
.missing{border-left:4px solid var(--warn)}code{background:#edf2f5;padding:2px 5px;
border-radius:4px;word-break:break-all}ul{padding-left:22px}footer{color:var(--muted);
border-top:1px solid var(--line);margin-top:32px;padding:18px 0}
@media(max-width:620px){.wrap{padding:12px}header{padding:20px}h1{font-size:24px}}
.badge{display:inline-flex;align-items:center;gap:5px;border-radius:6px;padding:3px 9px;
margin:2px 6px 2px 0;font-size:12.5px;font-weight:700;border:1px solid transparent;
white-space:normal;max-width:100%}
.badge-green{background:#e6f6ec;border-color:#3fa76b;color:#155724}
.badge-yellow{background:#fff8e1;border-color:#d69e2e;color:#7a5b00}
.badge-red{background:#fdecea;border-color:#d64545;color:#7a1f1f}
.badge-grey{background:#eef1f4;border-color:#adb5bd;color:#495057}
.badges{margin:8px 0}
.legend{display:flex;flex-wrap:wrap;gap:16px;font-size:12.5px;color:var(--muted);
align-items:center;margin:14px 0 0}
.legend .badge{margin:0}
.dashboard{background:var(--surface);border:1px solid var(--line);border-radius:12px;
padding:20px;margin:14px 0}
.dash-banner{border-radius:9px;padding:14px 18px;font-size:16px;font-weight:700;
margin-bottom:14px;display:flex;align-items:center;gap:10px;border:1px solid transparent}
.dash-banner.banner-green{background:#e6f6ec;color:#155724;border-color:#3fa76b}
.dash-banner.banner-yellow{background:#fff8e1;color:#7a5b00;border-color:#d69e2e}
.dash-banner.banner-red{background:#fdecea;color:#7a1f1f;border-color:#d64545}
.dash-banner.banner-grey{background:#eef1f4;color:#495057;border-color:#adb5bd}
.dash-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(215px,1fr));gap:10px}
.dash-chip{border:1px solid var(--line);border-radius:9px;padding:10px 12px;background:#fbfcfd}
.dash-chip .role-name{font-weight:700;margin-bottom:6px;display:flex;justify-content:space-between;
gap:8px}
.dash-chip .dims{display:flex;flex-wrap:wrap;gap:4px}
.star{color:#155724;font-weight:700}
.rec-table{width:100%;border-collapse:collapse;margin-top:8px}
.rec-table td{padding:8px 6px;border-top:1px solid var(--line);font-size:13.5px;vertical-align:top}
.rec-table td:first-child{font-weight:600;white-space:nowrap}
"""


def _e(value):
    return html.escape(str(value if value is not None else ""), quote=True)


def _badge(status, label, detail=None):
    text = label if detail is None else "%s: %s" % (label, detail)
    return ('<span class="badge badge-%s" title="%s">%s %s</span>'
            % (status, _e(_WORD[status]), _HTML_ICON[status], _e(text)))


def _legend_html():
    chips = "".join(
        '<span class="badge badge-%s">%s %s -- %s</span>'
        % (status, _HTML_ICON[status], _e(name), _e(meaning))
        for status, name, meaning in _LEGEND)
    return '<div class="legend">%s</div>' % chips


def _dashboard_html(rows, recommendations):
    banner_status, banner_text = _banner_status(recommendations, rows)
    chips = []
    for row in rows:
        dims = "".join([
            _badge(row["presence"][0], "Complete", row["presence"][1]),
            _badge(row["crs"][0], "CRS"),
            _badge(row["error"][0], "Error"),
            _badge(row["accuracy"][0], "Accuracy", row["accuracy"][1]),
            _badge(row["suggested"][0], "Suggested"),
        ])
        chips.append(
            '<div class="dash-chip"><div class="role-name">%s'
            '<span class="badge badge-%s">%s %s</span></div>'
            '<div class="dims">%s</div></div>'
            % (_e(row["label"]), row["overall"], _HTML_ICON[row["overall"]],
               _e(_WORD[row["overall"]]), dims))
    return (
        '<section class="dashboard"><h2 style="margin-top:0">Status dashboard</h2>'
        '<div class="dash-banner banner-%s">%s %s</div>'
        '<div class="dash-grid">%s</div>%s</section>'
        % (banner_status, _HTML_ICON[banner_status], _e(banner_text),
           "".join(chips), _legend_html())
    )


def render_html(catalog, quality_scores=None, recommendations=None):
    """Return a self-contained factual inventory HTML document.

    ``quality_scores`` / ``recommendations`` are optional pre-computed dicts
    (see module docstring); when omitted, every status badge honestly reads
    grey/"not scored" instead of guessing.
    """
    parts = [
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">",
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">",
        "<title>CCM Data Intelligence - Factual Inventory</title>",
        "<style>%s</style></head><body><div class=\"wrap\">" % _CSS,
        "<header><h1>CCM Data Intelligence</h1>",
        "<div class=\"sub\">Factual Inventory &middot; v%s &middot; %s</div></header>" %
        (_e(catalog.get("ccm_version") or VERSION), _e(catalog.get("created"))),
    ]
    if catalog.get("error"):
        parts.append("<section class=\"panel missing\"><h2>Scan error</h2><p>%s</p></section>" %
                     _e(catalog["error"]))
    else:
        # v0.59.7 -- see render_text()'s matching block: a .gdb/.gpkg this
        # scan could not open contributes NOTHING to any role below, which
        # otherwise reads identically to "this data does not exist". Flag it
        # before the dashboard so it can't be missed.
        unreadable = catalog.get("unreadable_containers") or []
        if unreadable:
            items = "".join("<li><code>%s</code></li>" % _e(u)
                            for u in unreadable[:15])
            more = ("<li>&hellip; and %d more</li>" % (len(unreadable) - 15)
                    if len(unreadable) > 15 else "")
            reason = ""
            if (catalog.get("backend") or "") == "header":
                reason = (
                    "<p><b>Reason:</b> this scan ran without arcpy or GDAL "
                    "available (pure-Python header reader only), which "
                    "cannot look inside a File Geodatabase or GeoPackage.</p>"
                    "<p><b>Fix:</b> run the CCM Data Intelligence tool from "
                    "inside ArcGIS Pro (Geoprocessing pane &mdash; it has "
                    "arcpy), or run this scanner from a Python environment "
                    "with GDAL/OGR installed.</p>")
            parts.append(
                "<section class='panel missing'>"
                "<h2>&#9888; %d geodatabase/GeoPackage container(s) could "
                "NOT be read</h2>"
                "<p>Their contents are <b>not reflected</b> in the roles "
                "below -- this is not the same as the data being absent.</p>"
                "<ul>%s%s</ul>%s</section>"
                % (len(unreadable), items, more, reason))

        rows = _dashboard_rows(catalog, quality_scores=quality_scores,
                               recommendations=recommendations)
        qmap = _quality_map(quality_scores)
        aoi_supplied = bool(catalog.get("aoi"))
        parts.append(_dashboard_html(rows, recommendations))

        stats = catalog.get("stats") or {}
        parts.append("<section><h2>1. Scan summary</h2><div class=\"summary grid\">")
        for key, label in (("files_scanned", "Files inspected"),
                           ("datasets_catalogued", "Datasets catalogued"),
                           ("unclassified", "Unclassified"),
                           ("duplicate_groups", "Duplicate groups")):
            parts.append("<div class=\"fact\"><span class=\"k\">%s</span>%s</div>" %
                         (_e(label), _e(stats.get(key, 0))))
        parts.append("</div><p><span class=\"k\">Data root</span><code>%s</code></p>"
                     "<p><span class=\"k\">Metadata backend</span>%s</p></section>" %
                     (_e(catalog.get("data_root")), _e(catalog.get("backend"))))

        parts.append("<section><h2>2. Detected data</h2>")
        roles = catalog.get("roles") or {}
        for role in _cat.CCM_ROLES:
            records = (roles.get(role) or {}).get("records") or []
            row = next(r for r in rows if r["role"] == role)
            recommended_name = _recommended_name_for_role(role, recommendations)
            parts.append(
                "<article class=\"role\"><h3>%s <small>(%d)</small> %s</h3>" %
                (_e(_cat.ROLE_LABELS.get(role, role)), len(records),
                 _badge(row["overall"], "Overall")))
            if not records:
                parts.append("<p>No dataset detected for this role.</p>")
            for rec in records:
                crs_status, crs_detail = _status_crs(rec)
                cov_status, cov_detail = _status_coverage(rec, aoi_supplied)
                err_status, err_detail = _status_error(rec)
                acc_status, acc_detail = _status_accuracy(qmap.get(rec.get("name")))
                is_recommended = (recommended_name is not None and
                                  rec.get("name") == recommended_name)
                parts.append("<div class=\"dataset\"><div class=\"name\">%s%s</div>" %
                             (_e(_basename(rec.get("path"))),
                              ' <span class="star">&#9733; Recommended source</span>'
                              if is_recommended else ""))
                for value in (rec.get("dataset_type"), rec.get("source_type"),
                              rec.get("compatibility")):
                    if value:
                        parts.append("<span class=\"pill\">%s</span>" % _e(value))
                parts.append('<div class="badges">%s%s%s%s</div>' % (
                    _badge(crs_status, "CRS", crs_detail),
                    _badge(cov_status, "Completeness", cov_detail),
                    _badge(err_status, "Error", err_detail),
                    _badge(acc_status, "Accuracy", acc_detail),
                ))
                parts.append("<div class=\"grid\">")
                facts = (("Role basis", rec.get("role_basis") or "unknown"),
                         ("Resolution/detail", _resolution(rec)),
                         ("CRS", _crs(rec)),
                         ("AOI coverage", _coverage(rec)),
                         ("Schema", _schema(rec)),
                         ("File date", (rec.get("acquired") or {}).get("date") or "not measured"))
                for label, value in facts:
                    parts.append("<div class=\"fact\"><span class=\"k\">%s</span>%s</div>" %
                                 (_e(label), _e(value)))
                parts.append("</div>")
                for limitation in rec.get("limitations") or []:
                    parts.append("<p class=\"lim\">Limitation: %s</p>" % _e(limitation))
                parts.append("<p><span class=\"k\">Source path</span><code>%s</code></p></div>" %
                             _e(rec.get("path")))
            parts.append("</article>")
        parts.append("</section>")

        parts.append("<section><h2>3. Duplicates</h2><div class=\"panel\">")
        groups = catalog.get("duplicate_groups") or []
        if not groups:
            parts.append("<p>No duplicate groups detected.</p>")
        for idx, group in enumerate(groups, 1):
            items = "".join("<li><code>%s</code></li>" % _e(x) for x in group)
            parts.append("<h3>Group %d %s</h3><ul>%s</ul>" %
                         (idx, _badge(YELLOW, "Duplicate"), items))
        parts.append("</div></section>")

        parts.append("<section><h2>4. Missing CCM roles</h2><div class=\"panel missing\">")
        missing = catalog.get("missing_roles") or []
        if not missing:
            parts.append("<p>No inventory role is empty.</p>")
        else:
            parts.append("<ul>")
            for role in missing:
                role_status = YELLOW if role in _SOFT_MISSING_ROLES else RED
                parts.append("<li>%s <b>%s</b> - %s</li>" %
                             (_badge(role_status, "Missing"),
                              _e(_cat.ROLE_LABELS.get(role, role)),
                              _e(MISSING_IMPACTS.get(role, "Role is not represented."))))
            parts.append("</ul>")
        parts.append("</div></section>")

        parts.append("<section><h2>5. Coordinate system</h2><div class=\"panel\">")
        recommendation = catalog.get("recommended_crs")
        if recommendation:
            crs_ok = bool(recommendation.get("aoi_matches"))
            parts.append(
                "<p>%s <b>Suggested project CRS:</b> %s (EPSG:%s)</p>"
                "<p>Basis: %s. This is a location-based suggestion, not an automatic conversion.</p>" %
                (_badge(GREEN if crs_ok else YELLOW, "CRS recommendation"),
                 _e(recommendation.get("name")), _e(recommendation.get("epsg")),
                 _e(recommendation.get("basis"))))
        else:
            parts.append("<p>%s A projected CRS suggestion could not be derived.</p>" %
                         _badge(RED, "CRS recommendation"))
        parts.append("</div></section>")

        parts.append("<section><h2>6. Unclassified files</h2><div class=\"panel\">")
        unclassified = catalog.get("unclassified") or []
        if not unclassified:
            parts.append("<p>No unclassified files detected.</p>")
        else:
            items = "".join("<li><code>%s</code> - %s</li>" %
                            (_e(rec.get("path")), _e(rec.get("role_basis") or "unknown"))
                            for rec in unclassified)
            parts.append("<ul>%s</ul>" % items)
        parts.append("</div></section>")

        parts.append("<section><h2>7. Suggested data (recommendations overview)</h2>"
                     "<div class=\"panel\">")
        if not recommendations:
            parts.append(
                "<p>%s Not available in this run. Suggested sources are produced "
                "by the integrated Step 0b scan (the default); re-run without "
                "the legacy factual-only option to see them here.</p>" %
                _badge(GREY, "Suggested data"))
        else:
            rec_rows = []
            for role in _cat.CCM_ROLES:
                selector_key = _ROLE_KEY_TO_SELECTOR_KEY.get(role)
                if not selector_key:
                    continue
                status, detail = _status_suggested(role, recommendations)
                rec_rows.append(
                    "<tr><td>%s</td><td>%s</td><td>%s</td></tr>" %
                    (_e(_cat.ROLE_LABELS.get(role, role)),
                     _badge(status, "Status"), _e(detail)))
            parts.append('<table class="rec-table">%s</table>' % "".join(rec_rows))
            parts.append(
                "<p style=\"margin-top:12px;color:var(--muted);font-size:13px\">"
                "Full alternatives and reasoning: "
                "<a href=\"CCM_Recommendations_Report.html\">"
                "CCM_Recommendations_Report.html</a> (written alongside this report).</p>")
        parts.append("</div></section>")

        parts.append("<section><h2>8. Next steps</h2><div class=\"panel\"><ol>"
                     "<li>Confirm that each detected role is correct.</li>"
                     "<li>Resolve CRS, coverage, schema, or compatibility limitations.</li>"
                     "<li>Select inputs explicitly in CCM Step 1.</li>"
                     "<li>Treat missing data as unknown, never as No-Go.</li>"
                     "</ol></div></section>")

    parts.append("<footer>CCM Data Intelligence v%s &middot; factual inventory subreport &middot; "
                 "Green/Yellow/Red badges overlay pre-computed scores read-only, when supplied."
                 "</footer>" %
                 _e(catalog.get("ccm_version") or VERSION))
    parts.append("</div></body></html>")
    return "\n".join(parts)


def _write(path, payload):
    _cat.atomic_write_text(path, payload)
    return path


def write_text(catalog, out_folder, filename=TEXT_FILENAME,
               quality_scores=None, recommendations=None):
    os.makedirs(str(out_folder), exist_ok=True)
    return _write(os.path.join(str(out_folder), filename),
                  "\n".join(render_text(catalog, quality_scores=quality_scores,
                                        recommendations=recommendations)) + "\n")


def write_json(catalog, out_folder):
    return _cat.write_catalog_json(catalog, out_folder)


def write_html(catalog, out_folder, filename=HTML_FILENAME,
               quality_scores=None, recommendations=None):
    os.makedirs(str(out_folder), exist_ok=True)
    return _write(os.path.join(str(out_folder), filename),
                  render_html(catalog, quality_scores=quality_scores,
                             recommendations=recommendations))


def write_all(catalog, out_folder, quality_scores=None, recommendations=None):
    return {
        "json": write_json(catalog, out_folder),
        "html": write_html(catalog, out_folder, quality_scores=quality_scores,
                           recommendations=recommendations),
        "text": write_text(catalog, out_folder, quality_scores=quality_scores,
                           recommendations=recommendations),
    }


# <<< END OF FILE >>>
