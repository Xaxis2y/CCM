<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
<!-- Copyright (c) 2026 Eui Soo SON -->

# CCM Tool by Son — Improvement Research
*Researched: June 7, 2026*

---

## 1. ArcGIS Pro 3.5–3.7 Native Tool Upgrades

### Distance Accumulation (Pro 3.5+) — up to 50× faster
- Applies to: `ccm_isochrone.py`, `ccm_waypoints.py`
- With Vertical/Horizontal Factor parameters, Pro 3.5 dramatically improved `Distance Accumulation` performance.
- Action: Bump minimum Pro version requirement and verify the tool is called with the updated API.
- Source: https://www.esri.com/arcgis-blog/products/arcgis-pro/analytics/whats-new-for-spatial-analyst-in-arcgis-pro-3-5

### Contour List Tool — polygon output (Pro 3.7+)
- Applies to: `ccm_obstacle_detect.py` → `_detect_slope_breaks_from_contours()`
- New `Contour Type` parameter outputs contours as polygons instead of lines, potentially replacing the expensive `GenerateNearTable` O(n²) approach.
- Action: Evaluate replacing near-table slope break detection with polygon-based contour spacing analysis.
- Source: https://www.esri.com/arcgis-blog/products/spatial-analyst/announcements/whats-new-for-spatial-analyst-in-arcgis-pro-3-7

### Geomorphon Landforms Tool (Pro 3.5+)
- Applies to: main CCM analysis, slope/vegetation classification
- Classifies terrain into landform types (ridges, valleys, slopes, etc.) at high speed from a DEM.
- Action: Evaluate as a supplement or replacement for the current slope region polygon approach in `ccm_step1_setup.py`.
- Source: https://www.esri.com/arcgis-blog/products/arcgis-pro/analytics/whats-new-for-spatial-analyst-in-arcgis-pro-3-5

---

## 2. Performance: Parallel Processing for Raster Steps

- Applies to: `ccm_soil_preprocess.py` (SoilGrids depth layer loop), `ccm_veg_preprocess.py`
- Esri testing shows ~4× speedup going from 1 to 4 processes for raster analysis.
- **Constraint**: Multiprocessing does NOT work with File GDB feature classes (schema locking). Apply only to raster computation steps *before* the final vector write.

### Pattern:
```python
from multiprocessing import Pool

def process_depth_layer(depth):
    # ... raster math for one depth layer ...
    return result

with Pool(processes=4) as pool:
    results = pool.map(process_depth_layer, SOILGRIDS_TOPSOIL_DEPTHS)
```

- Source: https://community.esri.com/t5/arcgis-spatial-analyst-blog/multiprocessing-with-arcgis-raster-analysis/ba-p/885908

---

## 3. Performance: NumPy Vectorization for Cursor Loops

- Applies to: `ccm_obstacle_detect.py` → `_detect_hydro_gaps()` and `_detect_linear_barriers()`
- Row-by-row `SearchCursor` iteration is 50–100× slower than NumPy vectorized operations.
- Use `arcpy.da.FeatureClassToNumPyArray()` and perform vectorized geometry width comparisons on the array.

### Pattern:
```python
arr = arcpy.da.FeatureClassToNumPyArray(clipped, ["SHAPE@LENGTH", "SHAPE@X", "SHAPE@Y"])
mask = arr["SHAPE@LENGTH"] <= ditch_max_width_m
gaps = arr[mask]
```

- Also: the `GenerateNearTable` call in `_detect_slope_breaks_from_contours()` scales O(n²) with contour density. A spatial index + `SelectLayerByLocation` on pre-binned segments would be more efficient for large/dense datasets.
- Source: https://geospatialtraining.com/arcgis-pro-performance-tuning-speed-up-your-workflows-by-50/

---

## 4. Quick Win: Disable Metadata Logging

- Applies to: all `execute()` methods in Step 1, Step 2, Step 3 tools
- Accumulated geoprocessing history metadata in the GDB degrades performance over repeated runs.
- Add one line at the start of each `execute()`:

```python
arcpy.SetLogMetadata(False)
```

- Zero risk, ~5 min to implement across all tools.
- Source: https://desktop.arcgis.com/en/arcmap/latest/analyze/sharing-workflows/performance-tips-for-geoprocessing-services.htm

---

## 5. ML-Based USCS Soil Classification (Longer Term)

- Applies to: `ccm_soil_preprocess.py` → SoilGrids and GENERIC source handlers
- Current approach: lookup-table binning of sand/silt/clay % → USCS code.
- Proposed: train a `sklearn` classifier (Random Forest or MLP) on sand/silt/clay/organic fractions → USCS code. Achieves R² of 0.92–0.97 for soil strength/moisture prediction.
- 2025 research shows ML models outperform traditional interpolation and lookup methods for soil texture classification.
- Published SoilGrids → USDA texture pipeline (Zenodo, July 2025) is a direct reference implementation.

### References:
- https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12491579/ (deep learning soil texture classification)
- https://zenodo.org/records/16965039 (SoilGrids → SWAT+ Python pipeline, July 2025)
- https://www.preprints.org/manuscript/202501.1059 (ML-enhanced mobility system selection)

---

## 6. High-Resolution Passability Mapping (Research Direction)

- 2025 paper in *Transactions in GIS*: terrain passability maps at 0.1m resolution using UAV multispectral + LiDAR data with Random Forest / deep learning.
- Multi-layer perceptron outperformed traditional GIS overlay for soil moisture and strength.
- Not a near-term code change, but informs future data input requirements (higher-res DEMs, multispectral imagery).
- Source: https://onlinelibrary.wiley.com/doi/10.1111/tgis.70035

---

## Priority / Effort Matrix

| # | Improvement | Files Affected | Effort | Impact |
|---|---|---|---|---|
| 4 | `arcpy.SetLogMetadata(False)` | Step 1, 2, 3 | 5 min | Low–Med |
| 1a | Distance Accumulation (Pro 3.5+) | ccm_isochrone, ccm_waypoints | Config only | High for isochrones |
| 3 | NumPy vectorize cursor loops | ccm_obstacle_detect | 1–2 hrs | Med–High on large data |
| 1b | Geomorphon Landforms tool | ccm_step1_setup | 1–2 days | Med–High |
| 1c | Contour List polygon output | ccm_obstacle_detect | 1–2 days | Med (large contour datasets) |
| 2 | Multiprocessing for SoilGrids rasters | ccm_soil_preprocess, ccm_veg_preprocess | 1–2 days | High on large AOIs |
| 5 | ML-based USCS classification | ccm_soil_preprocess | Weeks | High accuracy gain |
| 6 | High-res passability mapping | Architecture change | Long-term R&D | High |
