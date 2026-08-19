# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""Factual text and HTML reports for CCM Data Intelligence v0.57.

This release reports measured or directly observed inventory facts only.
Quality, Fitness, automatic selection, substitution scoring, Confidence, and
project Readiness belong to later roadmap releases and are intentionally not
calculated here.
"""

import html
import os
import textwrap

import ccm_data_catalog as _cat

VERSION = "0.57"
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


def render_text(catalog, width=88):
    """Return a factual, line-oriented inventory report."""
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
        lines.append("%s (%d)" % (label, len(records)))
        if not records:
            lines.append("  - none detected")
            continue
        for rec in records:
            lines.append("  - %s" % _basename(rec.get("path")))
            lines.append("      Role basis: %s" % (rec.get("role_basis") or "unknown"))
            lines.append("      Dataset type: %s" % (rec.get("dataset_type") or "unknown"))
            lines.append("      Source type: %s" % (rec.get("source_type") or "unidentified"))
            lines.append("      Resolution/detail: %s" % _resolution(rec))
            lines.append("      CRS: %s" % _crs(rec))
            lines.append("      AOI coverage: %s" % _coverage(rec))
            lines.append("      Schema: %s" % _schema(rec))
            lines.append("      Compatibility: %s" % (rec.get("compatibility") or "unknown"))
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
            lines.append("Group %d:" % idx)
            lines.extend("  - %s" % path for path in group)
    lines.append("")

    lines.extend(["4. MISSING CCM ROLES", thin])
    missing = catalog.get("missing_roles") or []
    if not missing:
        lines.append("No inventory role is empty.")
    else:
        for role in missing:
            lines.append("- %s" % _cat.ROLE_LABELS.get(role, role))
            if role in MISSING_IMPACTS:
                _wrap(lines, "  Model impact: ", MISSING_IMPACTS[role], width)
    lines.append("")

    lines.extend(["5. COORDINATE SYSTEM", thin])
    recommendation = catalog.get("recommended_crs")
    if recommendation:
        lines.append("Suggested project CRS: %s (EPSG:%s)" %
                     (recommendation.get("name"), recommendation.get("epsg")))
        lines.append("Suggestion basis: %s" %
                     (recommendation.get("basis") or "unknown"))
        lines.append("This is a location-based suggestion, not an automatic conversion.")
    else:
        lines.append("A projected CRS suggestion could not be derived from the inventory.")
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

    lines.extend([
        "7. NEXT STEPS", thin,
        "1. Confirm that each detected role is correct.",
        "2. Resolve CRS, coverage, schema, or compatibility limitations.",
        "3. Select inputs explicitly in CCM Step 1.",
        "4. Treat missing data as unknown/insufficient information, never as No-Go.",
        "",
        "Methodology note: v0.57 reports inventory facts only. It does not "
        "calculate Data Quality, CCM Fitness, Confidence, Readiness, or an "
        "automatic best-source recommendation.",
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
"""


def _e(value):
    return html.escape(str(value if value is not None else ""), quote=True)


def render_html(catalog):
    """Return a self-contained factual inventory HTML document."""
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
            parts.append("<article class=\"role\"><h3>%s <small>(%d)</small></h3>" %
                         (_e(_cat.ROLE_LABELS.get(role, role)), len(records)))
            if not records:
                parts.append("<p>No dataset detected for this role.</p>")
            for rec in records:
                parts.append("<div class=\"dataset\"><div class=\"name\">%s</div>" %
                             _e(_basename(rec.get("path"))))
                for value in (rec.get("dataset_type"), rec.get("source_type"),
                              rec.get("compatibility")):
                    if value:
                        parts.append("<span class=\"pill\">%s</span>" % _e(value))
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
            parts.append("<h3>Group %d</h3><ul>%s</ul>" % (idx, items))
        parts.append("</div></section>")

        parts.append("<section><h2>4. Missing CCM roles</h2><div class=\"panel missing\">")
        missing = catalog.get("missing_roles") or []
        if not missing:
            parts.append("<p>No inventory role is empty.</p>")
        else:
            parts.append("<ul>")
            for role in missing:
                parts.append("<li><b>%s</b> - %s</li>" %
                             (_e(_cat.ROLE_LABELS.get(role, role)),
                              _e(MISSING_IMPACTS.get(role, "Role is not represented."))))
            parts.append("</ul>")
        parts.append("</div></section>")

        parts.append("<section><h2>5. Coordinate system</h2><div class=\"panel\">")
        recommendation = catalog.get("recommended_crs")
        if recommendation:
            parts.append("<p><b>Suggested project CRS:</b> %s (EPSG:%s)</p>"
                         "<p>Basis: %s. This is a location-based suggestion, not an automatic conversion.</p>" %
                         (_e(recommendation.get("name")), _e(recommendation.get("epsg")),
                          _e(recommendation.get("basis"))))
        else:
            parts.append("<p>A projected CRS suggestion could not be derived.</p>")
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

        parts.append("<section><h2>7. Next steps</h2><div class=\"panel\"><ol>"
                     "<li>Confirm that each detected role is correct.</li>"
                     "<li>Resolve CRS, coverage, schema, or compatibility limitations.</li>"
                     "<li>Select inputs explicitly in CCM Step 1.</li>"
                     "<li>Treat missing data as unknown, never as No-Go.</li>"
                     "</ol></div></section>")

    parts.append("<footer>CCM Data Intelligence v%s &middot; factual inventory only &middot; "
                 "no Quality, Fitness, Confidence, Readiness, or automatic source selection.</footer>" %
                 _e(catalog.get("ccm_version") or VERSION))
    parts.append("</div></body></html>")
    return "\n".join(parts)


def _write(path, payload):
    _cat.atomic_write_text(path, payload)
    return path


def write_text(catalog, out_folder, filename=TEXT_FILENAME):
    os.makedirs(str(out_folder), exist_ok=True)
    return _write(os.path.join(str(out_folder), filename),
                  "\n".join(render_text(catalog)) + "\n")


def write_json(catalog, out_folder):
    return _cat.write_catalog_json(catalog, out_folder)


def write_html(catalog, out_folder, filename=HTML_FILENAME):
    os.makedirs(str(out_folder), exist_ok=True)
    return _write(os.path.join(str(out_folder), filename), render_html(catalog))


def write_all(catalog, out_folder):
    return {
        "json": write_json(catalog, out_folder),
        "html": write_html(catalog, out_folder),
        "text": write_text(catalog, out_folder),
    }


# <<< END OF FILE >>>
