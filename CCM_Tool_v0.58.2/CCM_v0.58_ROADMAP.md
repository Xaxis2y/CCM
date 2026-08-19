# CCM Tool v0.58 — Roadmap & Architecture

**Status:** Planning phase (v0.57 release verified and delivered)  
**Target Release:** Q3 2026  
**Model:** Data Quality → Fitness → Confidence → Readiness → Auto-selection

---

## Vision

v0.57 introduced **factual-only** Data Intelligence: Step 0b inventories a data root and reports what exists, with no scoring or automatic selection.

v0.58 adds **scoring and auto-selection**: given a catalog of candidate datasets, the system evaluates each on four dimensions (Quality, Fitness, Confidence, Readiness) and recommends the best source for each role (DEM, Soil, Vegetation, etc.). Step 1 can still accept or override the recommendation.

---

## Architecture Overview

### Layer 1: Data Quality Scoring (`ccm_data_quality.py` — NEW)

**Purpose:** Measure inherent dataset fitness for CCM mobility modeling.

**Inputs:** Catalog JSON (from Step 0b)

**Outputs:** Quality scores per dataset, per metric

**Metrics:**

| Metric | Applies To | Scale | Notes |
|--------|-----------|-------|-------|
| **Temporal Age** | All | 1–10 | Recent (< 2 years) = 10; older = penalty |
| **CRS Compatibility** | All rasters/vectors | 1–10 | Projected = 10; geographic = 5; unknown = 0 |
| **Coverage vs AOI** | All | 1–10 | 100% coverage = 10; <50% = 1 |
| **Resolution/Detail** | DEM, Soil, Vegetation | 1–10 | Finer = higher; scaled to typical CCM resolutions (10–30m) |
| **Schema Completeness** | Soil, Vehicle CSVs | 1–10 | All required columns = 10; missing columns = 0 |
| **Duplication Penalty** | All | -5 per duplicate | Identical copies found → reduce score |
| **Metadata Presence** | All | +2 per type | CRS, schema, units present → bonus |
| **Horizontal Accuracy** | DEM, Ortho | 1–10 | If known (RMSE): <1m=10, 1–5m=8, 5–10m=6, >10m=3 |

**Calculation:**
```
quality_score = (metric_1 + metric_2 + ... + metric_n) / n
```

Result: **1–10 numeric score** per dataset.

---

### Layer 2: CCM Fitness Scoring (`ccm_data_fitness.py` — NEW)

**Purpose:** Measure suitability for the *specific* CCM NG-NRMM workflow.

**Inputs:** Catalog JSON + dataset quality scores + vehicle specs (Vehicles_Can.csv)

**Outputs:** Fitness scores per dataset, per role

**Metrics:**

| Role | Fitness Factors | Scale | Notes |
|------|-----------------|-------|-------|
| **DEM** | Vertical accuracy (±1m min), no voids, raster format | 1–10 | Void-filled SRTM acceptable if vertical ±5m or better |
| **Soil** | Cone Index (RCI/VCI lookup), USCS recognition, moisture support | 1–10 | Presence of calibration data (soil_rci.csv match) = +3 |
| **Vegetation** | Canopy height/density or NDVI, CCM-compatible classes | 1–10 | Raster > vector for CCM speed model |
| **Hydrology** | Stream/flow vector, no classification needed | 1–10 | Presence alone = score; detail boosts |
| **Contours** | Optional; elevations vs DEM agreement within ±5m | 1–10 | Used for validation only; low fitness doesn't block |
| **Extent (AOI)** | Polygon geometry, contains all data | 1–10 | Must be valid; coverage < 90% = warn |
| **Vehicle CSV** | VCI table, required columns (Speed, MMP, P), numeric sanity | 1–10 | Invalid = 1; complete = 10 |

**Calculation per role:**
```
fitness_score = (factor_1 + factor_2 + ...) / n  [adjusted for calibration presence]
```

Result: **1–10 numeric score** per dataset per role.

---

### Layer 3: Confidence Scoring (`ccm_data_confidence.py` — NEW)

**Purpose:** Estimate modeling confidence given data limitations.

**Inputs:** Catalog JSON + fitness scores + Step 1 preprocessing decisions

**Outputs:** Confidence flag + confidence_reason (text)

**Rules:**

```
IF (DEM quality >= 8 AND DEM fitness >= 8 AND DEM coverage >= 95%):
    DEM_confidence = "High"
ELIF (DEM quality >= 6 AND DEM fitness >= 6 AND DEM coverage >= 80%):
    DEM_confidence = "Moderate"
ELSE:
    DEM_confidence = "Low" OR "Unvetted"

[Apply same pattern to Soil, Vegetation, AOI, Vehicle]

IF all_roles confidence >= "Moderate":
    model_confidence = "Acceptable"
ELIF any_role confidence = "Low" AND no_critical_workaround:
    model_confidence = "Conditional" (warn: "Soil data unvetted; validate RCI manually")
ELSE:
    model_confidence = "At-Risk"
```

Result: **Confidence level** (High / Moderate / Low / Unvetted) + **confidence_reason** (human-readable text).

---

### Layer 4: Readiness Scoring (`ccm_data_readiness.py` — NEW)

**Purpose:** Measure preprocessing completion before Step 2.

**Inputs:** Step 1 preprocessing output (reprojected layers, merged grids, etc.)

**Outputs:** Readiness checklist + readiness_status

**Checklist:**

```
□ DEM: exists, valid CRS, no voids, raster format
□ Slope: derived from DEM, valid values [0–90], raster format
□ Soil: merged/reprojected, RCI table linked, raster format
□ Vegetation: merged/reprojected, height/NDVI extracted, raster format
□ Hydro: reprojected, network valid (if present)
□ Extent (AOI): valid polygon, contains all data
□ Vehicle CSV: required columns present, numeric sanity passed
□ Scratch workspace: clean, writeable
□ Configuration: all paths valid, no circular refs
```

**Scoring:**
```
readiness_pct = (checked_items / total_items) * 100

IF readiness_pct == 100:
    readiness_status = "Ready"
ELIF readiness_pct >= 80:
    readiness_status = "Mostly Ready" (minor rework)
ELIF readiness_pct >= 50:
    readiness_status = "Partial" (significant rework)
ELSE:
    readiness_status = "Incomplete"
```

Result: **Readiness status** + **missing_items** list.

---

### Layer 5: Auto-Selection Engine (`ccm_data_selector.py` — NEW)

**Purpose:** Recommend the best dataset source for each role.

**Inputs:** All prior scores (Quality, Fitness, Confidence, Readiness) + user preferences

**Outputs:** `recommended_sources.json` + ranking reasons

**Algorithm:**

```python
For each role (DEM, Soil, Vegetation, Hydro, Contours, Vehicle):
    candidate_datasets = [d for d in catalog if d.role == role]
    
    For each candidate:
        score = (
            quality_score * 0.30 +      # base data quality
            fitness_score * 0.40 +      # CCM-specific fit
            confidence_level_numeric * 0.20 +  # modeling confidence
            coverage_pct / 100 * 0.10   # AOI coverage
        )
        
        recommendation_reason = f"{candidate.name}: Quality {q}/10, Fitness {f}/10, {cov}% coverage, {confidence} confidence"
    
    best = max(candidates, key=lambda c: score)
    
    IF best.score < 5.0:
        recommendation = "MANUAL_SELECTION_REQUIRED"
        reason = f"No dataset meets fitness threshold; review catalog for alternatives"
    ELSE:
        recommendation = best
        reason = recommendation_reason
```

Result: JSON structure:
```json
{
  "timestamp": "2026-08-19T...",
  "selections": {
    "DEM": {
      "recommended": "ASTER_30m.tif",
      "score": 7.8,
      "quality": 8,
      "fitness": 8,
      "confidence": "High",
      "coverage_pct": 95.0,
      "reason": "ASTER_30m: Quality 8/10, Fitness 8/10, 95% coverage, High confidence"
    },
    "Soil": {
      "recommended": "MANUAL_SELECTION_REQUIRED",
      "score": 2.1,
      "reason": "No soil dataset matches CCM RCI requirements; recommend acquiring SoilGrids or SSURGO"
    },
    ...
  },
  "model_confidence": "Conditional",
  "readiness": "Mostly Ready",
  "next_steps": [
    "Accept DEM recommendation or override in Step 1",
    "Manually resolve Soil selection",
    "Verify Vehicle CSV sanity before Step 2"
  ]
}
```

---

## Step 0b Enhancements (v0.58)

**Existing:** Factual catalog (JSON, HTML, TXT)

**New:** Call auto-selection engine at end:

```python
# In ccm_step0b_intelligence.py::run_step0b()

catalog = load_catalog(data_root, aoi)

# v0.57 behavior
write_catalog_json(catalog, project_output / "ccm_data_catalog.json")
write_html_report(catalog, project_output / "CCM_Data_Intelligence_Report.html")
write_txt_report(catalog, project_output / "CCM_Data_Intelligence_Report.txt")
update_project_config(catalog)

# v0.58 new behavior
quality_scores = quality_engine(catalog)
fitness_scores = fitness_engine(catalog, vehicles_can_csv)
confidence_scores = confidence_engine(catalog, fitness_scores)
readiness_scores = readiness_engine(project_output)
recommendations = selector_engine(
    catalog, quality_scores, fitness_scores, 
    confidence_scores, readiness_scores,
    user_prefs={}  # empty for defaults; user can override
)

write_recommendations_json(recommendations, project_output / "ccm_recommendations.json")
write_recommendations_html(recommendations, project_output / "CCM_Recommendations_Report.html")

# Update Step 1 input form with recommended sources
update_project_config(catalog, recommendations)
```

---

## Step 1 Enhancements (v0.58)

**Existing:** Manual source selection per role, input validation

**New:** Display recommendations at step start:

```python
# In ccm_step1_setup.py::getParameterInfo()

# Load recommendations if available
recommendations_path = project_output / "ccm_recommendations.json"
if recommendations_path.exists():
    recommendations = json.load(recommendations_path)
    
    for role, rec_data in recommendations["selections"].items():
        if rec_data["recommended"] != "MANUAL_SELECTION_REQUIRED":
            recommended_source = rec_data["recommended"]
            rec_reason = rec_data["reason"]
            
            # Add info message to tool interface
            arcpy.AddMessage(
                f"Recommended {role}: {recommended_source} ({rec_reason})"
            )
        else:
            arcpy.AddWarning(
                f"⚠ {role}: {rec_data['reason']}"
            )
    
    # Set parameter defaults (but user can override)
    # dem_param.value = recommendations["selections"]["DEM"]["recommended"]
    # soil_param.value = recommendations["selections"]["Soil"]["recommended"]
    # etc.
```

---

## Phasing & Scope

### Phase 1: Core Scoring Engines (Weeks 1–2)
- [ ] `ccm_data_quality.py` — metric implementations + test suite
- [ ] `ccm_data_fitness.py` — role-specific fitness + test suite
- [ ] `ccm_data_confidence.py` — confidence rules + test suite
- [ ] `ccm_data_readiness.py` — readiness checklist + test suite
- [ ] Unit tests: 80+ new assertions covering edge cases

### Phase 2: Auto-Selection & Integration (Weeks 3–4)
- [ ] `ccm_data_selector.py` — recommendation engine + test suite
- [ ] Step 0b integration: call selector at end, write recommendations.json + HTML
- [ ] Step 1 integration: display recommendations, allow override
- [ ] End-to-end test: catalog → scores → recommendations → Step 1 auto-fill

### Phase 3: UI & Documentation (Weeks 5–6)
- [ ] Update QUICK_START: new v0.58 recommendation workflow
- [ ] Update User Manual: Section 2.3 "Data Intelligence & Auto-Selection"
- [ ] Add `CCM_Recommendations_Report.html` styling (match Step 0b report)
- [ ] Add recommendation-override callouts in Step 1 parameter help
- [ ] Changelog: full v0.58 feature list

### Phase 4: Testing & Release (Week 7)
- [ ] ArcPy smoke tests: Steps 0b + 1 with recommendations enabled
- [ ] Regression tests: all v0.57 tests still pass
- [ ] Release: `bump_version.py 0.58`, build ZIP, update docs

---

## Data Structures

### `ccm_recommendations.json`

```json
{
  "version": "0.58",
  "timestamp": "2026-08-19T16:34:14Z",
  "data_root": "/path/to/data",
  "aoi_file": "/path/to/AOI.shp",
  "model_confidence": "Acceptable",
  "readiness": "Ready",
  "selections": {
    "DEM": {
      "recommended": "ASTER_30m.tif",
      "score": 7.8,
      "metrics": {
        "quality": 8,
        "fitness": 8,
        "confidence": "High",
        "coverage_pct": 95.0
      },
      "alternatives": [
        {"name": "SRTM_30m.tif", "score": 6.2, "reason": "Geographic CRS; requires reprojection"},
        {"name": "DEM_10m.tif", "score": 7.1, "reason": "Higher resolution but 2 duplicate copies found"}
      ],
      "reason": "ASTER_30m: Quality 8/10, Fitness 8/10, 95% coverage, High confidence"
    },
    "Soil": {...},
    "Vegetation": {...},
    "Hydro": {...},
    "Extent": {...},
    "Vehicle": {...}
  },
  "warnings": [
    "No contour dataset found (optional but recommended for validation)",
    "Soil RCI table incomplete for clay_0-5cm.tif; manual calibration required"
  ],
  "next_steps": [
    "Accept DEM recommendation in Step 1 or select an alternative",
    "Resolve soil fitness issue: acquire SSURGO or validate RCI table",
    "Verify Vehicle CSV sanity before proceeding to Step 2"
  ]
}
```

### Quality/Fitness/Confidence/Readiness Outputs (internal)

Each module writes a `.json` file for audit/debugging:

```
verification_artifacts/
  ccm_quality_scores.json      # Per-dataset quality metrics
  ccm_fitness_scores.json      # Per-dataset per-role fitness
  ccm_confidence_scores.json   # Per-role confidence levels
  ccm_readiness_scores.json    # Preprocessing checklist results
```

---

## Dependencies & Compatibility

**New Imports:**
- `json` (stdlib)
- `datetime` (stdlib)
- `re` (stdlib)

**No new external packages required.**

**Backward Compatibility:**
- v0.58 reads v0.57's `ccm_data_catalog.json` unchanged
- Existing `ccm_project.json` keys preserved
- Step 2–4 behavior unchanged (recommendations are Step 0b/1 only)

---

## Testing Strategy

### Unit Tests (80+ assertions)

```python
# test_ccm_v058.py

class TestQualityScoring:
    def test_quality_temporal_age_recent()
    def test_quality_temporal_age_stale()
    def test_quality_crs_projected_vs_geographic()
    def test_quality_coverage_100_vs_partial()
    def test_quality_duplication_penalty()
    # ... 15 total

class TestFitnessScoring:
    def test_fitness_dem_vertical_accuracy()
    def test_fitness_dem_void_detection()
    def test_fitness_soil_rci_calibration()
    def test_fitness_soil_uscs_recognition()
    def test_fitness_vegetation_raster_vs_vector()
    # ... 20 total

class TestConfidenceScoring:
    def test_confidence_high_all_good()
    def test_confidence_moderate_one_weak()
    def test_confidence_low_multiple_issues()
    def test_confidence_unvetted_no_data()
    # ... 12 total

class TestReadinessScoring:
    def test_readiness_complete_all_checked()
    def test_readiness_partial_missing_dem()
    def test_readiness_incomplete_multiple_missing()
    # ... 8 total

class TestAutoSelector:
    def test_selector_picks_highest_score()
    def test_selector_handles_ties_alphabetically()
    def test_selector_marks_manual_when_below_threshold()
    def test_selector_includes_alternatives()
    # ... 20 total
```

### Integration Tests

```python
# test_ccm_v058_integration.py

def test_step0b_with_recommendations():
    """End-to-end: scan catalog → score → recommend → write JSON/HTML"""
    
def test_step1_loads_recommendations():
    """Step 1 displays recommendations at startup"""
    
def test_step1_override_recommendation():
    """User selects alternative source despite recommendation"""
```

### Regression Tests

```python
# Verify all v0.57 tests still pass
pytest tests/ -k "not v058" --tb=short
```

---

## Risk & Mitigation

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Scoring metrics too harsh / all "Low" | Medium | Unusable | Calibrate against real data roots; adjust weights |
| AutoSelector flip-flops between ties | Low | Confusion | Add deterministic tie-breaker (name alphabetical) |
| Recommendations out-of-date after Step 1 | Medium | User confusion | Timestamp recommendations; re-run 0b if data changes |
| Performance: scoring 50+ datasets | Low | Slowdown | Profile per dataset; optimize metadata reads |
| Missing calibration data (RCI, VCI) | Medium | False negatives | Clear warnings; don't auto-fail on missing |

---

## Deferred / Future (v0.59+)

- **Deep-scan option:** Spatial cross-validation (does candidate DEM match known benchmarks?) — see PROJECT_STATUS "Data Intelligence deep-scan" note
- **User preferences:** Allow user to weight metrics (prefer 10m resolution over recency?) — stored in `ccm_project.json`
- **Automatic substitution:** If recommended source fails preprocessing, auto-fall-back to next-best — for now, manual override only
- **Mobile-specific fitness:** Terrain & terrain-interaction factors (Class II vs VIII terrain, rock types) — NG-NRMM v2 scope

---

## Files to Create (v0.58)

| File | Purpose | LOC | Tests |
|------|---------|-----|-------|
| `ccm_data_quality.py` | Quality scoring engine | ~250 | 15+ |
| `ccm_data_fitness.py` | Fitness scoring engine | ~300 | 20+ |
| `ccm_data_confidence.py` | Confidence scoring engine | ~200 | 12+ |
| `ccm_data_readiness.py` | Readiness checklist engine | ~150 | 8+ |
| `ccm_data_selector.py` | Auto-selection recommendations | ~200 | 20+ |
| `tests/test_ccm_v058.py` | Unit + integration tests | ~600 | 80+ |

**Total new code:** ~1,700 LOC + ~600 LOC tests = ~2,300 LOC.

---

## Version Bump Checklist (at release)

- [ ] `ccm_version.py`: VERSION = "0.58"
- [ ] All module headers: VERSION = "0.58"
- [ ] `CCM_Tool_v0.58.pyt`: version attribute
- [ ] `CCM_Tool_v0.58_User_Manual.docx`: title page, version history
- [ ] `README.md`: "Current: v0.58"
- [ ] `QUICK_START.md`: "v0.58"
- [ ] `CHANGELOG_v0.58.md`: new file
- [ ] `PROJECT_STATUS.md`: add v0.58 blockquote
- [ ] `package_ccm_v058.py`: VERSION check
- [ ] `bump_version.py` test: v0.58 → 0.59 works
- [ ] Release ZIP: `CCM_Tool_v0.58.zip`

---

## Success Criteria

✅ All 80+ new unit tests pass  
✅ All 241 v0.57 regression tests still pass  
✅ End-to-end smoke test: Step 0b → recommendations → Step 1 override  
✅ `CCM_Recommendations_Report.html` renders correctly  
✅ User Manual documents new features  
✅ Zero regressions in Steps 2–4  
✅ Licensed ArcPy smoke test passes (Steps 0, 0b, 1)  

---

**Next:** Ready to begin Phase 1 (Core Scoring Engines) on your go.

