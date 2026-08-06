<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
<!-- Copyright (c) 2026 Eui Soo SON -->

# CHANGELOG — v0.54.7 (2026-07-26)

## Smoke-test detection fix — no production-code change *(confirmed in the field)*

The v0.54.6 fix was re-verified against real ArcGIS Pro 3.7.1 by re-running
`tests/arcpy_smoke_test_step3.py` (log: `smoke_step3_v0546.log`).

### What the real run showed

All structural checks on the Isochrone output passed (output FC exists,
`TIME_BAND` field present, at least one ring produced). But the log
revealed that **both** v0.54.6 mitigations hit `ERROR 160333` again,
identically:

```
[CCM Isochrone] Reclassifying into time bands (in-memory) …
WARNING: [CCM Isochrone] Reclassify (in-memory) hit ERROR 160333 …
Rebuilding raster statistics and retrying once, single-threaded …
WARNING: [CCM Isochrone] Reclassify (retry) hit ERROR 160333 again.
WARNING: [CCM Isochrone] Spatial Analyst method failed (…); falling back
to the vector method so an isochrone is still produced. This result uses
polygon boundaries rather than raster cells and may be less precise.
[CCM Isochrone] Isochrones (vector method) saved to: …
ISOCHRONE COMPLETE
```

This is the third consecutive real-environment confirmation (v0.54.5,
both v0.54.6 mitigations, now this re-run) that surgical raster-level
fixes cannot reliably prevent ERROR 160333 in this environment. The
vector-fallback resilience mechanism added in v0.54.6, however, worked
exactly as designed and produced valid, usable output.

**Decision: no 4th raster-level mitigation was attempted without new
diagnostic evidence.** The vector fallback is the durable fix going
forward — it guarantees a usable Reachability Map regardless of whether
the underlying, still-unexplained ArcGIS Pro bug is ever resolved.

### The actual bug this release fixes

The same log exposed a real bug, but in the *test*, not in
`ccm_isochrone.py`. `tests/arcpy_smoke_test_step3.py` printed:

```
INFO B. Isochrone: produced via Spatial Analyst path (DistanceAccumulation)
```

— the wrong answer. The log's own messages (`"Isochrones (vector method)
saved to: …"`, `ISOCHRONE COMPLETE`) prove the vector fallback is what
actually ran. The check was inspecting `msgs.warnings` for the SA→vector
fallback notice, but `ccm_isochrone.py` logs that notice via the global
`arcpy.AddWarning()` — a process-wide message stream always visible in
the Geoprocessing Messages / stdout — not via the `messages` parameter
object passed into `run_tool()`, which is only populated by explicit
calls on that specific object. These are different channels; the test's
`_FakeMessages.warnings` list was never going to see a global
`arcpy.AddWarning()` call, so the check silently fell through to the
wrong branch every time regardless of which path actually ran.

**Fix:** replaced the `msgs.warnings` inspection with a
`"gridcode" in iso_fields` check. `RasterToPolygon` — the Spatial
Analyst path's last step — always adds a `gridcode` field;
`Dissolve` — the vector path's last step — never does. This was
verified directly against each method's own code in `ccm_isochrone.py`,
not inferred or guessed.

**No change to `ccm_isochrone.py`'s isochrone-generation logic this
round** — the v0.54.6 production-code fix (in-memory Reclassify +
stats/single-thread fallback + vector-method resilience) is confirmed
working; only the smoke test's own diagnostic was wrong.

No new mocked pytest, for the same reason as v0.54.5/v0.54.6: this
depends on real `arcpy.sa` raster objects and a local `import arcpy.sa
as sa`. Validated by the real ArcGIS Pro re-run described above. Pytest
suite unchanged: **165 passed / 3 skipped.**

### Process note

Fifth time in this release series a real ArcGIS Pro run has found or
re-tested something the static review and mocked-arcpy suite could not
(v0.54.3: silent symbology failure; v0.54.4: Union license limit;
v0.54.5: ERROR 160333 first pass; v0.54.6: mitigation didn't hold;
v0.54.7: this — a bug in the *test's own diagnostic*, caught only by
cross-referencing the real log's explicit messages against the test's
reported verdict and noticing the contradiction).

---

# CHANGELOG — v0.54.6 (2026-07-26)

## ERROR 160333 follow-up: the v0.54.5 mitigation didn't hold up *(confirmed in the field)*

The v0.54.5 fix was re-verified against real ArcGIS Pro 3.7.1 by re-running
both affected smoke tests:

- `tests/arcpy_smoke_test_step1.py`: **17/17 PASS**. The `M1` vehicle-name
  fix is confirmed — `[Step 2] Vehicle: <Vehicle M1 road=71.0kph
  vci50=58.0>` and a clean Step 1 → Step 2 hand-off.
- `tests/arcpy_smoke_test_step3.py`: same single failure as before —
  Isochrone. But the log now shows the v0.54.5 mitigation actually running:

```
[CCM Isochrone] Reclassifying into time bands …
WARNING: [CCM Isochrone] Reclassify hit ERROR 160333 ('table was not found'
— a known, non-deterministic ArcGIS Pro raster issue). Rebuilding raster
statistics and retrying once, single-threaded …
WARNING: [Step 3] Reachability Map failed: ERROR 160333: The table was not
found.
Failed to execute (Reclassify).
```

The retry fired exactly as designed — `CalculateStatistics` ran, the retry
used `parallelProcessingFactor="0"` — and hit the **identical** error
again. This rules out stale raster statistics and parallel-tiling-on-a-
small-raster as the (whole) trigger; the v0.54.5 theory was reasonable but
incomplete.

### Fix — two further changes

1. **In-memory Reclassify (new primary attempt).**
   `_reclassify_with_retry()` now runs Reclassify directly on the
   in-memory `cost_dist` Raster object returned by `DistanceAccumulation`/
   `CostDistance`, instead of re-opening `cost_dist_path` from the scratch
   geodatabase immediately after `.save()`. Re-reading a raster by path
   right after writing it is a plausible trigger for "table was not
   found": a geodatabase's catalog/business-table entry for a brand-new
   dataset is not guaranteed to be immediately visible to the very next
   tool that queries it. Operating on the in-memory object skips that
   round-trip entirely. The v0.54.5 mitigation (rebuild statistics, retry
   once single-threaded against the saved path) is kept as a second-line
   fallback in case the in-memory attempt also hits ERROR 160333.

2. **Vector-method fallback in `generate_isochrones()`.** If the Spatial
   Analyst path (now with both of the above mitigations) still fails for
   any reason, `generate_isochrones()` catches it and falls back to
   `_generate_isochrones_vector()` — the module's existing,
   licence-independent method, previously only used automatically when
   Spatial Analyst isn't licensed at all. This guarantees an isochrone is
   produced either way: the vector method is less precise (time bands are
   bounded by polygon edges, not raster cells) but real output beats none.
   A clear warning is logged identifying which path actually ran.

**Honesty note.** This still does not claim to have found or eliminated
the true root cause of ERROR 160333 — Esri's own community says none is
published. It adds a second plausible mitigation (avoiding the disk
round-trip) and, more importantly, makes the feature resilient to this
class of failure regardless of cause: if the raster method cannot be made
to work reliably in a given environment, the tool now degrades to a
working alternative instead of producing no output.

### Test changes

`tests/arcpy_smoke_test_step3.py` now keeps a reference to the
`_FakeMessages` instance passed into `run_tool()` (previously created
inline and discarded) and, after confirming the Isochrone output FC exists,
inspects `msgs.warnings` for the SA→vector fallback notice — reporting via
`note()` which path actually produced the output rather than treating a
raster-path success and a vector-path fallback as indistinguishable passes.
This keeps the check informative without turning either valid outcome into
a failure.

No new mocked pytest, for the same reason as v0.54.5: this logic depends on
real `arcpy.sa` raster objects and a local `import arcpy.sa as sa`, which a
monkeypatched module-level `arcpy` name does not reach. Validated by the
real ArcGIS Pro re-run described above. Pytest suite unchanged:
**165 passed / 3 skipped.**

### Process note

Fourth time in this release series a real ArcGIS Pro run has found or
re-tested something the static review and mocked-arcpy suite could not
(v0.54.3: silent symbology failure; v0.54.4: Union license limit; v0.54.5:
ERROR 160333 first pass; v0.54.6: this). The retry-then-verify loop worked
as intended — the fix that didn't fully work was caught by asking for
another real run rather than assumed correct after one warning-free pass.

---

# CHANGELOG — v0.54.5 (2026-07-26)

## ERROR 160333 Reclassify fix — Reachability Map / Isochrone  *(confirmed in the field)*

Running the 3 new end-to-end smoke tests added in v0.54.4 (Steps 0, 1, 3)
against a real ArcGIS Pro 3.7.1 install found two more issues the mocked-arcpy
suite could not — following directly from the v0.54.4 process note that this
class of defect only surfaces against a real licence.

### Finding 1 — `tests/arcpy_smoke_test_step3.py`: Isochrone

```
[CCM Isochrone] Running DistanceAccumulation …
[CCM Isochrone] Reclassifying into time bands …
WARNING: [Step 3] Reachability Map failed: ERROR 160333: The table was not found.
Failed to execute (Reclassify).
```

All four other Step 3 sub-analyses in the same run passed cleanly: Reason
Map, Vehicle Compare, Obstacle Detection, and Waypoint Routing (including
confirming the No-Go snap fallback genuinely works — a route endpoint placed
in a NO-GO cell was correctly snapped to a passable one). Only the Isochrone
path hit this error.

**What ERROR 160333 is.** This is a real ArcGIS Pro error, but a poorly
documented one. Esri's own KB article (000027676) documents only an
unrelated cause — file geodatabases created by a pre-upgrade version of
ArcMap/Pro, which does not apply here (the smoke test creates a brand-new
scratch GDB every run). An Esri Community thread titled "ArcGIS Pro 3.4.2:
'The table was not found' error appears frequently without a clear reason"
confirms there is no single, deterministic root cause published — Esri's
own MVP contributors describe it as inconsistent and occasionally
irreproducible. Several independent reports tie adjacent symptoms to
parallel raster tiling on small rasters, which matches this toolbox's
synthetic test fixtures (and plausibly small real AOIs too).

**Fix — two mitigations, both defence-in-depth, both cheap on the happy
path (they only run if something actually fails):**

1. **Consistent environment scoping.** `arcpy.sa` raster objects are
   evaluated *lazily* — `DistanceAccumulation()` may not actually compute
   anything until `.save()` forces materialisation. The old code called
   `.save()` *after* the `with arcpy.EnvManager(parallelProcessingFactor=
   "100%")` block had already exited, so the real raster write could happen
   under a different (default) parallel-processing setting than the one
   that was actually intended. `.save()` now runs *inside* the same
   `EnvManager` block as `DistanceAccumulation()`, for both the
   Pro 3.5+ path and the legacy `CostDistance` path.
2. **New `_reclassify_with_retry()`.** Wraps the `Reclassify` call: on
   success, saves and returns immediately as before. If `arcpy.ExecuteError`
   is raised and the message contains "160333", it logs a warning, forces
   `arcpy.management.CalculateStatistics()` on the input raster (rebuilds
   raster metadata — resolves this error in most community-reported cases
   where it is a stale/missing table, not a real data problem), then retries
   `Reclassify` exactly once with `parallelProcessingFactor="0"` (disables
   parallel tiling — the suspected trigger on small rasters). Any other
   error, or a retry that also fails, re-raises unchanged, so
   `ccm_step3_advanced.py`'s existing handling (degrade to a warning, not a
   crash — already confirmed working by this exact smoke-test run) is
   unaffected.

**Honesty note.** This is not a claim to have found and eliminated the true
root cause of ERROR 160333 — per Esri's own community, nobody has published
one. It is a targeted, low-risk mitigation against the two most plausible
trigger classes (inconsistent parallel-processing scope; parallel tiling on
small rasters), applied only on the failure path so it cannot regress the
happy path. Re-running `tests/arcpy_smoke_test_step3.py` against a real
licence is the only way to confirm it resolves the observed failure.

**No new mocked pytest.** `_reclassify_with_retry()` lives inside
`ccm_isochrone.py`'s Spatial-Analyst path and (matching the surrounding
`_generate_isochrones_sa()` function it serves) depends on a local
`import arcpy.sa as sa` and real raster objects — monkeypatching the
module-level `arcpy` name, as `TestUnionLicenseSafety` does for
`_union_license_safe()`, does not reach that local import. `_generate_
isochrones_sa()` has never had mocked-arcpy coverage for the same reason;
this fix is validated the same way the rest of that function is —
`tests/arcpy_smoke_test_step3.py` against a real licence. Pytest suite
unchanged: **165 passed / 4 skipped.**

### Finding 2 — `tests/arcpy_smoke_test_step1.py`: hand-off vehicle name

```
RuntimeError: Vehicle 'TestTank' not in CSV. Available: M1, M60A1, M109, ...
```

This smoke test deliberately feeds the REAL `Vehicle_Data/Vehicles_Can.csv`
into Step 1 (to exercise the true production data), but then called
`build_speed_surface(project_folder, "TestTank", ...)` for the Step 1 → 2
hand-off check — `"TestTank"` only exists in the synthetic CSVs the *other*
two smoke tests build for themselves. The tool raised exactly the
`RuntimeError` it should have; the test's own hand-off vehicle name was
wrong. Fixed by using `"M1"`, a real row in the shipped CSV. All 12 other
Step 1 checks passed (fixtures, CSV discovery, `execute()`, project GDB,
`ccm_project.json` — every field matched exactly).

### Documentation correction

While updating docs for this release, found that `PROJECT_STATUS.md` and a
trailing comment line in `ccm_step3_advanced.py` / `ccm_vehicle_compare.py`
had the v0.54.1 rebrand-and-relicense story mislabelled "v0.54.4" — a
leftover from an earlier blanket version-string replace (`CHANGELOG_v0.54.md`
itself, and the `.pyt` docstring history, were already correctly labelled
v0.54.1). Corrected all three to the true version.

### Process note

Third time this release series that a real ArcGIS Pro run found something
the static review and mocked-arcpy suite both missed (v0.54.3: silent
symbology failure; v0.54.4: Union license limit; v0.54.5: this). The 4 smoke
tests (Steps 0/1/2/3) should stay part of the standard pre-release
checklist, not a one-time exercise.

---

# CHANGELOG — v0.54.4 (2026-07-25)

## Union license-limit fix — ERROR 000384  *(critical, confirmed in the field)*

`tests/arcpy_smoke_test.py` was fixed in v0.54.2 to stop aborting pytest
collection, but had never actually been RUN against a real ArcGIS Pro
install until now. Running it against ArcGIS Pro 3.7.1 (Standard licence)
surfaced a failure the static pre-release review never touched, because it
only exists at runtime, against a real licence:

```
ERROR 000384: Cannot have more than 2 inputs with a Basic or Standard license
Failed to execute (Union).
```

`ccm_step2_mobility.build_speed_surface()` collects the available criteria
layers — soil, vegetation, slope — into `union_inputs` and unioned all of
them in a single call:

```python
arcpy.analysis.Union(union_inputs, unioned, "ALL")
```

Per Esri's own documentation, **Union and Intersect are capped at two inputs
below the Advanced licence tier.** With all three criteria layers present —
the normal case, since soil, vegetation, and one of DEM/slope are all
required inputs per the manual's data-requirements table — this call failed
outright. **Step 2, the toolbox's core output, could not run at all for any
user without an Advanced licence.** This is more severe than any of the
symbology defects fixed in v0.54.2/v0.54.3: those degraded the finished map;
this stopped the map from being generated in the first place.

### Fix

New `_union_license_safe()` in `ccm_step2_mobility.py` folds any number of
inputs pairwise — soil ∪ vegetation → temp, temp ∪ slope → final — so every
`arcpy.analysis.Union` call it issues carries exactly two inputs. This is
Esri's own documented workaround (tool-errors-and-warnings page for error
000384): *"union the tool consecutive times... union the first two, then
union that output with the third."*

The helper does **not** attempt to detect the licence tier first and branch
on it. `arcpy.ProductInfo()`'s naming (`ArcView`/`ArcEditor`/`ArcInfo`) is a
legacy holdover from ArcMap, and licence policy is Esri's to change; unioning
pairwise unconditionally is correct on Basic, Standard, *and* Advanced alike,
so there is nothing to get out of sync. On an Advanced licence this costs a
few extra intermediate `Union` calls versus one N-way call — a fair trade
for never failing outright on the tiers below it.

Edge cases handled: a single input skips `Union` entirely and uses
`CopyFeatures` (Union's single-input behaviour was never exercised by the
old code and is unnecessary here); intermediate chain feature classes are
deleted as the fold proceeds; the original source layers (soil_fc, veg_fc,
slope_fc) are never touched or deleted, only the toolbox's own scratch
intermediates are.

### Tests

Five new tests in `tests/test_v050.py::TestUnionLicenseSafety` replace
`ccm_step2_mobility.arcpy` with a small recorder and assert the invariant
directly — **no `Union` call may ever carry more than two inputs** — for 1,
2, 3 (the exact soil+veg+slope shape that failed), and 5 inputs, plus the
zero-input error case. These are pure-Python tests; they run without arcpy
and would have caught this defect before it ever reached a real licence.

**165 passed / 4 skipped.**

### Process note

This is the second time in this release series that a real ArcGIS Pro run
found something a static review and a mocked-arcpy test suite both missed —
v0.54.3 found the symbology renderer's true (silent) failure mode; v0.54.4
found this. `tests/arcpy_smoke_test.py` exercises the full Step 2 pipeline
end-to-end and should be run against a real licence before every release
going forward, not only when something is suspected.

## New end-to-end coverage for Steps 0, 1, 3

Prompted directly by the process note above: `tests/arcpy_smoke_test.py`
only ever covered Step 2. Steps 0, 1, and 3 had no real-ArcGIS coverage at
all — only unit tests against a mocked `arcpy` — despite Step 3 alone
bundling five sub-analyses (Reason Map, Isochrone, Vehicle Compare, Obstacle
Detection, Waypoint Routing) plus the map auto-load/styling path that
received most of this release series' symbology fixes. Given Step 2 failed
on its very first real-license run, the other steps could not be assumed
clean without the same treatment.

Three new smoke tests, following the exact structure and conventions of the
existing one (synthetic fixtures, no external data, PASS/FAIL check log,
left-on-disk scratch project for inspection):

- **`tests/arcpy_smoke_test_step0.py`** — builds a synthetic "MGCP cell"
  source GDB (FACC-coded `DA010` soil + `BH140` hydro polygons) and runs
  `CCMStep0MGCPTool` twice: a fresh import, then an `APPEND` re-import to
  exercise the merge-cells path. Asserts both feature classes import with
  correct counts, `mgcp_manifest.json` is written with correct `ccm_role`
  classification, and the second run merges rather than duplicates or
  errors.
- **`tests/arcpy_smoke_test_step1.py`** — supplies already-CCM-ready soil /
  vegetation / slope feature classes via Step 1's own `soil_preproc_fc` /
  `veg_preproc_fc` / `slope_regions_fc` "skip pre-processing" parameters
  (the 6 raw soil sources and 7 raw vegetation sources already have
  dedicated unit coverage in `test_ccm.py` and are not re-tested here).
  Asserts `ccm_project.json` is written with every field matching what was
  supplied, then — the part no existing test could prove — feeds that REAL
  config straight into `ccm_step2_mobility.build_speed_surface()`, verifying
  the actual Step 1 → Step 2 hand-off works, not just that each step works
  in isolation against a hand-built config.
- **`tests/arcpy_smoke_test_step3.py`** — runs two real Step 2 speed
  surfaces, then invokes `CCMStep3AdvancedTool` with ALL FIVE analyses
  enabled in one call (the "every checkbox ticked" workflow). Asserts real
  outputs for each: `NO_GO_REASON`/`RESTRICT_CODE` added in place (Reason
  Map), a ring FC with `TIME_BAND` (Isochrone), a comparison FC with valid
  `COMPARE_RESULT` categories (Vehicle Compare), an obstacle FC (Obstacle
  Detection — zero obstacles is treated as a valid outcome, matching the
  User Manual's own Troubleshooting guidance), and a route FC or a reported
  "no passable path" outcome (Waypoint Routing — the start/end points are
  deliberately placed in the best and worst grid cells to exercise
  `ccm_waypoints.py`'s documented "No-Go snap fallback" rather than a
  trivially-easy same-cell route). Also confirms the map auto-load path
  degrades safely (a caught warning, not a crash) when run headless with no
  live `arcpy.mp.ArcGISProject("CURRENT")` session.

All three invoke their tool via `ccm_project_config.run_tool()` — the
project's own "invoke by parameter NAME" convention (see CLAUDE.md
Conventions) already used internally by Step 1 and Step 3 for their own
sub-tool calls — rather than hand-building fragile positional parameter
lists, so they stay correct if a tool's parameter list is ever reordered.

These are genuinely new coverage, not a behaviour change, so no version bump
accompanies them (matching the precedent set by `tests/verify_v0542.py` /
`tests/verify_v0543.py` in the sections above). `CLAUDE.md`'s Rule 1 item 4
checklist is updated to include all three so future version bumps reach them
automatically.

---

# CHANGELOG — v0.54.3 (2026-07-25)

## Verification follow-up — confirmed on ArcGIS Pro 3.7.1

`tests/verify_v0543.py` was run against a real install (Pro 3.7.1 build 1901).
9/9 checks executed, 0 failures. Two things came out of it.

### Defect 1 was the silent failure mode  *(confirmed)*

The v0.54.2 changelog noted the old `Condition_Number` renderer would either
raise or silently produce a zero-class renderer, and that the symptom differed.
The verification settled it — **it fails silently**:

```
sym.renderer.fields = ['Condition_Number']
fields assign  : did NOT raise
symbology set  : did NOT raise
   class label : '400'
class count    : 1
>>> RESULT [OLD-BUG] B — SILENT FAILURE (no exception, 1 classes, flat layer)
```

arcpy accepted the non-existent field without complaint and built a renderer
with a single meaningless class. Every speed surface Step 3 rebuilt since
v0.51 drew as **one flat colour, with no warning in the tool output**. This
was the worse of the two possible outcomes and confirms the fix was required,
not merely tidy.

The v0.54.2 renderer verified correct in the same run: field `Mobility`,
exactly three classes, `GO [56,168,0]` / `RESTRICTED [255,170,0]` /
`NO GO [255,0,0]`, layer named `Speed Surface — Leopard`.

### Speed surface lost its transparency  *(regression, fixed here)*

The same run reported `Transparency : 0.0` where 55 was intended.
`style_speed_surface()` set `lyr.transparency` **before** calling
`ApplySymbologyFromLayer()`, which resets it. The finished speed surface was
therefore fully opaque and hid the imagery basemap underneath — a visible
regression introduced by the v0.54.2 restructure.

Transparency is now applied **after** symbology in every branch, via a new
`_set_transparency()` helper, and the percentage lives in one constant
(`SURFACE_TRANSPARENCY = 55`). The helper warns on failure instead of passing
silently. `verify_v0543.py` now asserts the value rather than just printing it.

### Alpha-scale claim — corrected

The v0.54.2 notes asserted arcpy clamps CIM colour alpha above 100. The
verification **did not support that**: writing 240 read back 240, and 50 read
back 50 — arcpy stores whatever it is given and does not validate on
assignment.

The change from a 0-255 to a 0-100 scale is still correct, but for a different
reason than stated: every `CIMRGBColor` that **ArcGIS Pro itself authored** in
the shipped `Mobility_Symbology_Final.lyrx` uses alpha `0` or `100`, and a
fully-opaque symbol stores `100`. That is what establishes the scale. The old
150-255 values were out of range; what Pro does with an out-of-range alpha at
draw time is undefined rather than clamped.

`verify_v0543.py`'s alpha test is rewritten to be decisive: it reports the
in-memory read-back, round-trips the symbol through a saved `.lyrx` to show
what gets serialised, and prints the alpha values Pro authored in the
reference file for comparison.

---

# CHANGELOG — v0.54.2 (2026-07-25)

## Pre-release audit — five defects fixed

A full pre-release inspection of v0.54.1 (`PRE_RELEASE_REVIEW_v0.54.1.md`)
found five defects. All are fixed here. No geoprocessing / mobility-model
logic changed — every fix is in symbology, packaging, or test plumbing.

### 1. Speed surface rendered on a field that does not exist  *(critical)*

`ccm_map_display.style_speed_surface()` built its renderer on
`Condition_Number`, trying six spellings of it. **None of the six has ever
been produced by any CCM module.** The Step 2 output contract
(`ccm_step2_mobility.FIELD_MOBILITY`) is `Mobility`, carrying
`GO` / `RESTRICTED` / `NO GO`.

Consequently, whenever Step 3 rebuilt the map, the speed surface — the
primary deliverable of the whole toolbox — either drew as a single flat
default colour with no warning, or emitted
`[CCM display] Speed Surface symbology skipped: …` on every run. The
`COND_COLOURS` red→green ramp the module docstring advertised was dead code.

`style_speed_surface()` now:

- applies the packaged `Symbology/Mobility_Symbology*.lyrx` **first**. This
  is the same artefact Step 2 attaches to its derived output parameter, so a
  map built by Step 2 and one rebuilt by Step 3 are now identical — they
  previously used two unrelated palettes. It also preserves the red
  cross-hatch on NO GO, which a programmatic renderer cannot express.
- falls back to a `UniqueValueRenderer` on the resolved Mobility field
  (`MOBILITY_COLOURS`: GO green / RESTRICTED amber / NO GO red) when no
  `.lyrx` is available;
- **verifies the field exists before assigning it** (`resolve_field()`), so a
  future rename cannot silently produce a zero-class renderer again;
- reports every fallback. The old code wrapped the `.lyrx` fallback in a bare
  `except Exception: pass`, so a missing `Symbology/` folder produced an
  unstyled layer with no diagnostic whatsoever.

### 2. Colour alpha channel used the wrong scale  *(critical)*

Every colour table in `ccm_map_display.py` specified alpha on a 0-255 scale
(`240`, `225`, `210`, `195`, `180`, `255`, `200`, `160`, `150`). arcpy's CIM
colour dictionary — `{"RGB": [r, g, b, a]}` — takes alpha on a **0-100**
scale, as the packaged `.lyrx` files confirm (every `CIMRGBColor` in them
uses alpha `0` or `100`).

ArcGIS Pro clamps anything above 100 to fully opaque, so none of the intended
per-class transparency had ever rendered. `MOBILITY_COLOURS`,
`ISO_RING_COLOURS` and `COMPARE_COLOURS` are all corrected, and a regression
test now asserts the range.

### 3. The release zip shipped 17 stale files  *(critical)*

`build.py` walked the project folder and packaged anything matching an
extension, with no version filter. The v0.54.1 release zip therefore
contained:

- two obsolete toolboxes carrying old, pre-rename filenames — they appear
  in ArcGIS Pro's Catalog beside the real one and display old version
  labels while executing current code;
- two superseded user manuals still carrying pre-rename filenames;
- twelve orphan `.pyt.xml` sidecars;
- a Word lock file left over from editing one of those manuals.

A user unzipping the release saw three toolboxes and three manuals. Fixed by:

- `should_include()` — screens Office lock files, obsolete pre-rename
  artifacts, internal dev documents (`CLAUDE.md`, `CODE_REVIEW_*.md`,
  `CCM_Improvement_Research.md`) and any `_v<x.y.z>` tag that is not the
  current release; excluded files are listed at the end of the build;
- a **stale-toolbox guard** that aborts the build when a second `.pyt` is
  found, so this cannot recur silently;
- the stale files themselves deleted from the project folder;
- `PY_FILES` now derives the toolbox filename from `VERSION` instead of
  hardcoding it, which is what `build.py`'s docstring always claimed;
- the duplicate root `Vehicles_Can.csv` removed — `Vehicle_Data/` is the
  single copy, matching Step 1's own help text. Tests updated to match.

### 4. The arcpy smoke test aborted the whole pytest run  *(medium)*

`tests/arcpy_smoke_test.py` did a bare top-level `import arcpy`, which fails
at pytest **collection** time on any machine without ArcGIS Pro:

```
ERROR tests/arcpy_smoke_test.py
!!!!!! Interrupted: 1 error during collection !!!!!!
```

The 157 real tests never executed. Now guarded with
`pytest.importorskip("arcpy")` when running under pytest, while a direct
`python tests/arcpy_smoke_test.py` still raises normally — which is correct
for a deliberate smoke run. Its header also still referenced a v0.53.3 path.

### 5. Toolbox metadata sidecar was four versions stale  *(medium)*

The toolbox's `.pyt.xml` sidecar internally still read
`<toolbox name="...v0.50.1">` / `<resTitle>…v0.50.1</resTitle>`.
The file had been renamed at each release but its contents never rewritten,
so ArcGIS Pro's Catalog properties showed the wrong version. Rewritten to
v0.54.2, with `ModDate` refreshed and an abstract + credit block added.

## Output presentation

- **Legend pruned.** `Mobility_Symbology.lyrx` and
  `Mobility_Symbology_Final.lyrx` defined seven unique-value classes, but
  Step 2 only ever writes three. `SLOW`, `VERY SLOW`,
  `NO GO - Hydro Feature` and `NO GO - Vegetation` were leftovers from an
  earlier classification scheme and appeared as permanently blank rows in
  every finished map's legend. Both files are now `GO` / `RESTRICTED` /
  `NO GO`, in that order, with `RESTRICTED` recoloured amber
  (`255,170,0`) — the previous pale green read poorly next to `GO` green.
- **Layer names.** Step 3's `_veh_label` fell back to the raw feature-class
  basename whenever Vehicle Compare was not run (its source, `p[12]`, is the
  Vehicle A name), producing Contents entries like
  `CCM — speed_surface_leopard_moist (moist)` /
  `Speed Surface — speed_surface_leopard_moist`. The label is now derived by
  stripping the `speed_surface_` prefix and trailing moisture token:
  `CCM — Leopard (moist)` / `Speed Surface — Leopard`.
- **Unknown outputs.** `kind_of()` returned `"surface"` for anything it did
  not recognise, so speed-surface symbology was applied to arbitrary layers.
  It now returns `None`; Step 3 adds such a layer with default symbology and
  says so. `sort_for_draw_order()` places unknowns at the bottom.
- The `★` prefix was dropped from the Start/End point layer names.

## Tests

`test_condition_colours_no_go_is_red` asserted `COND_COLOURS["1"]` and
`["5"]` — it was **locking in defect 1**, which is why the bug survived four
releases. Replaced with four regression guards:

- `test_mobility_colours_keyed_on_real_field_values` — palette keys must be
  the values `ccm_step2_mobility` actually writes;
- `test_mobility_colours_semantics` — NO GO red, GO green-dominant;
- `test_alpha_channel_is_on_the_0_100_cim_scale` — defect 2;
- `test_kind_of_returns_none_for_unknown`.

`COND_COLOURS` is retained as an alias of `MOBILITY_COLOURS` for any external
caller. Unused imports removed from `tests/test_ccm.py`.

**160 passed / 4 skipped** (skips require a licensed ArcGIS Pro).

`tests/verify_v0542.py` is provided to confirm the symbology fixes against a
real ArcGIS Pro install — see the README of that file for how to run it.

---

# CHANGELOG — v0.54.1 (2026-07-21)

## Rename + relicense

The toolbox's product name is standardized throughout the project, and
the toolbox is relicensed under **SPDX-License-Identifier: GPL-2.0-or-later**
(previously "All Rights Reserved"). No functional / geoprocessing behaviour
changed.

### Naming

- Toolbox filename, all `.pyt.xml` sidecars, the `toolname` constant, and
  the toolbox `alias` all renamed to the current `CCM_Tool` naming
  convention, replacing the product name used through v0.54.0.
- `ccm_map_display.MAP_NAME` constant updated to match (the Step 3
  auto-load group/map name shown in ArcGIS Pro's Contents pane); updated
  everywhere it's referenced in `ccm_step3_advanced.py`.
- Release zip (`build.py`) and user manual filenames renamed to match the
  current naming convention.
- All old product-name text mentions updated across every module, test,
  and doc — **including the historical `CHANGELOG_v0.45.md`–
  `CHANGELOG_v0.53.md` files** (product-name mentions only; version
  numbers and other historical facts in those files are untouched). The
  two mentions of the technique-name acronym (Multi-Criteria Evaluation,
  e.g. in `ccm_step2_mobility.py` and the manual's Section 1.1) describe
  the analysis method rather than the product name, and were out of scope
  for this rename.

### License

- New header on every module / test / `.pyt` file:
  ```
  # SPDX-License-Identifier: GPL-2.0-or-later
  # Copyright (c) 2026 Eui Soo SON
  ```
  replacing the previous `Copyright (c) 2026  Eui Soo Son` / `All Rights
  Reserved.` block. `README.md`'s Copyright section and the user manual's
  title page updated to match; the manual's Section 10.4 Version History
  gains this row.

### Version bump

- All module `VERSION` constants → `0.54.1`; `.pyt` `toolversion` → `0.54.1`.
  `README.md` / `PROJECT_STATUS.md` / `TASKS.md` / `CLAUDE.md` updated to
  match (current-version lines bumped; historical rows/mentions left as
  written).

---

# CHANGELOG — v0.54.0 (2026-07-21)

## Smart CRS/projection warnings (Steps 0, 1, 3, 4) + User Manual CRS chapter

Step 1's Analysis Extent has always blocked on a Geographic CRS ("CCM
requires a Projected CRS... e.g. UTM"). This release extends the same idea —
non-blocking warnings, not hard errors — to every other step that consumes
spatial data, and adds a beginner-level explanation of *why* to the User
Manual.

### New shared helpers — `ccm_coords.py`

- **`describe_spatial_reference(path)`** — safe `arcpy.Describe` wrapper;
  returns `(sr_type, sr_name, factory_code)` or `(None, None, None)` on any
  failure (missing/locked/corrupt data), so callers never need their own
  try/except around it.
- **`geographic_crs_warning(layer_label, sr_name, blocking=False)`** —
  standard explanatory text for a layer using a Geographic CRS: why CCM
  needs metres, and how to fix it (Export Features → UTM zone).
- **`crs_mismatch_warning(layer_label, layer_sr, ref_label, ref_sr)`** —
  standard text for two layers that are both projected but use *different*
  systems (still misaligns results even though neither is "wrong" on its
  own).
- 5 new unit tests (160 total, 157 passed / 3 skipped).

### Step 0 — Load MGCP Data (`ccm_step0_mgcp.py`)

- **Output Coordinate System** now warns (non-blocking) if left blank or set
  to a Geographic CRS: MGCP source data is WGS84 by specification, so doing
  nothing here means Step 1 will need a separate Export Features pass later.
  Recommends setting this to the target UTM zone now instead.

### Step 1 — Project Setup & Pre-process (`ccm_step1_setup.py`)

- Analysis Extent's existing blocking Geographic-CRS check is unchanged.
- **New:** once the Extent is confirmed Projected, DEM, Slope Regions,
  Contour Lines, Raw Soil FC/Raster, Pre-processed Soil FC, Pre-processed
  Vegetation FC, and every Hydrology layer are each checked — warning if the
  layer is Geographic, or if it's Projected but uses a **different** system
  than the Analysis Extent (factory/EPSG code comparison). Hydrology
  (multi-value) aggregates all offending layers into one message per
  parameter so warnings don't overwrite each other.

### Step 3 — Advanced Analysis (`ccm_step3_advanced.py`)

- Speed Surface FC — normally auto-filled from Step 1's already-validated
  CRS, but a manual override is now checked: warns if Geographic. (Combined
  with the existing missing-output-fields check into one message so neither
  overwrites the other.)
- Obstacle Detection's Contour Lines FC / Hydro FC — warns if Geographic, or
  if projected but mismatched against the Speed Surface FC.

### Step 4 — Compare Two Vehicles (`ccm_vehicle_compare.py`)

- `updateMessages()` was a no-op (`pass`) — implemented from scratch: warns
  if either Vehicle A/B Speed Surface is Geographic, and warns if both are
  projected but use **different** coordinate systems (a cross-projection
  comparison would silently misalign, producing meaningless BOTH_GO /
  A_ONLY / B_ONLY output).

### User Manual

- **New Section 3.4 — Coordinate Reference System (CRS) Requirements.**
  Beginner-level explanation of Geographic vs. Projected CRS, why CCM's
  geoprocessing needs metres, how to find/apply the right UTM zone in
  ArcGIS Pro, a worked example, and a summary table of which parameter in
  each step now carries a smart warning.
- Section 1.4 heading and the step-overview table extended to cover Step 4;
  Section 2.2's "three tools" quick-start line corrected to five. Sections
  2.5 (Step 0), 4.1 (Step 1 core parameters), 5 (Step 2 intro), and 6.3
  (Vehicle Comparison / standalone Step 4) each gained a short
  data-requirements-and-projection note.
- Section 3.3's Data Requirements table and 4.1's Core Parameters table
  Notes/Description columns now mention the same-CRS expectation. Appendix C
  gained a CRS row. Section 9.1 (Troubleshooting) gained four new rows for
  the new warnings, plus a stale outdated-version filename reference
  corrected to the current version.
- Section 10.4 Version History: this row.
- Title page and all body version references bumped 0.53.3 → 0.54.0.

### Version bump

- All module `VERSION` constants → `0.54.0`; toolbox renamed
  `CCM_Tool_v0.53.3.pyt` → `CCM_Tool_v0.54.0.pyt` (sidecars, `build.py`, the
  test suite, README / PROJECT_STATUS / TASKS, and the user manual updated
  to match).

---
