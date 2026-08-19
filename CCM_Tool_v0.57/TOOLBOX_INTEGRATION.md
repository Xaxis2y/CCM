# CCM Tool v0.57 Integration Guide

This folder is the isolated v0.57 integration copy. It combines the original
v0.55.1 ArcGIS Pro toolbox with the validated Data Intelligence modules from
v0.56.4. The two source folders remain unchanged.

## Integrated modules

The following modules are beside `CCM_Tool_v0.57.pyt`:

- `ccm_data_catalog.py` — factual inventory and metadata probes;
- `ccm_data_sources.py` — descriptive source/product reference data;
- `ccm_data_report.py` — TXT and self-contained HTML reports; and
- `ccm_step0b_intelligence.py` — Step 0b toolbox class and standalone CLI.

`ccm_data_catalog.py` reuses the existing `ccm_data_discovery.py` vocabulary
when available, so role keywords remain consistent with the legacy Step 1
workflow. It does not add a quality score or automatic source choice.

## Toolbox registration

`CCM_Tool_v0.57.pyt` imports `CCMDataIntelligenceTool` with the same guarded
stub pattern used by the existing steps and registers it between Step 0 and
Step 1. If an import fails, ArcGIS displays an unavailable tool with the
underlying error instead of silently hiding Step 0b.

The toolbox sidecar is:

```text
CCM_Tool_v0.57.CCMDataIntelligenceTool.pyt.xml
```

## Project hand-off

Step 0b writes these additive keys to `ccm_project.json`:

```json
{
  "data_root": "D:/GIS/Source_Data",
  "data_catalog_json": "D:/GIS/Project/ccm_data_catalog.json"
}
```

Existing keys are preserved. Step 1 may present catalog candidates, but it must
not automatically select, replace, or rank an input on behalf of the analyst.
If the catalog is missing, stale, unreadable, or schema-incompatible, Step 1
must retain its existing manual-input behavior.

## Runtime modes

1. **ArcGIS Pro toolbox mode** — ArcPy can read richer metadata and enumerate
   file-geodatabase layers.
2. **Anaconda CLI/GUI mode** — the scanner uses GDAL/OGR when installed, then
   built-in GeoTIFF, shapefile, DBF, PRJ, and CSV readers. It remains useful
   without ArcGIS Pro.

The Anaconda environment is created by `CCM_anaconda.bat`. ArcPy is licensed
ArcGIS Pro software and is intentionally not installed by that script.

## Verification checklist

From Anaconda Prompt:

```bat
CCM_anaconda.bat
RUN_V057_TESTS.bat
```

Then, with ArcGIS Pro open and signed in:

```bat
RUN_ARCGIS_SMOKE_TEST.bat
```

The blocking tests check syntax, pyflakes, legacy regression tests, the v0.57
Data Intelligence suite, fixture scanning, JSON/HTML/TXT outputs, project
configuration hand-off, ArcPy metadata, GDB enumeration, and source safety.

## Scope boundary

This integration release reports factual inventory only. Data Quality, CCM
Fitness, Confidence, Readiness, automatic selection, and substitution remain
future roadmap work. They must not be inferred from record order or from the
presence of a catalog file.

# <<< END OF FILE >>>
