# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# ccm_data_audit.py
# Static sanity checks over the toolbox's shipped reference data
# (soil_rci.csv, Vehicle_Data/Vehicles_Can.csv, and the USCS cross-reference
# tables in ccm_step2_mobility.py).
#
# VERSION = "0.57"
"""
Why this exists
----------------
v0.57 post-review item "5.3": the two calibration CSVs that ship with this
toolbox (soil_rci.csv and Vehicle_Data/Vehicles_Can.csv) are analyst-editable
data, not code -- nothing previously checked that an edit to either one was
internally consistent before it silently changed GO/RESTRICTED/NO GO
outcomes in the field. This module is a pure-Python (arcpy-optional, same
pattern as ccm_step2_mobility.py), dependency-light auditor that:

    1. soil_rci.csv -- every row's USCS code is one this toolbox actually
       recognises (matches ccm_step2_mobility._BUILTIN_USCS_RCI), and each
       row's (dry, moist, wet) RCI triple is monotonically non-increasing
       (soil only gets weaker as it gets wetter -- a row where wet > moist
       or moist > dry is almost certainly a data-entry error, not a real
       soil property).
    2. Vehicle_Data/Vehicles_Can.csv -- every row has the columns
       load_vehicles_csv() actually reads, vci_1 <= vci_50 (a vehicle cannot
       need MORE bearing capacity for sustained fifty-pass traffic than it
       does to survive a single pass), all numeric fields parse and are
       non-negative, and vehicle names are unique (a duplicate silently
       shadows the earlier row -- see load_vehicles_csv()'s dict-by-name
       behaviour).
    3. USCS_TO_SENSITIVITY_KEY (ccm_weather rainfall-adjustment bridge)
       covers exactly the same USCS codes as _BUILTIN_USCS_RCI -- a code
       present in one but not the other silently drops out of
       apply_weather_to_rci()'s round-trip (see that function's
       back-mapping).

This is a facts-reporting auditor, not a fixer: it never modifies the CSVs.
It is wired into package_ccm_v057.py's ``--verify-only`` gate, so a bad
calibration edit fails the release verifier the same way a missing file or
a version-string mismatch does.

Usage
-----
    python ccm_data_audit.py                  # human-readable report, exit
                                                # code 0 = clean, 1 = problems

    import ccm_data_audit
    problems = ccm_data_audit.audit_all()      # list[str], empty = clean
"""

import csv
import os

VERSION = "0.57"

_HERE = os.path.dirname(os.path.abspath(__file__))

SOIL_RCI_CSV = os.path.join(_HERE, "soil_rci.csv")
VEHICLES_CSV = os.path.join(_HERE, "Vehicle_Data", "Vehicles_Can.csv")

_REQUIRED_VEHICLE_COLUMNS = ("name", "vci_1", "vci_50")


def _to_float(val):
    if val is None:
        return None
    s = str(val).strip()
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


# =============================================================================
# soil_rci.csv
# =============================================================================

def audit_soil_rci(csv_path=None):
    """
    Return a list of human-readable problem strings for soil_rci.csv.
    Empty list = clean.  Never raises -- an unreadable/missing file is
    reported as a single problem string, not an exception.
    """
    problems = []
    path = csv_path or SOIL_RCI_CSV

    try:
        import ccm_step2_mobility as _step2
        known_codes = set(_step2._BUILTIN_USCS_RCI)
    except Exception as exc:
        problems.append(
            "soil_rci.csv audit: could not import ccm_step2_mobility to get "
            "the known USCS code set (%s) -- skipping code-recognition check."
            % exc
        )
        known_codes = None

    if not os.path.isfile(path):
        problems.append("soil_rci.csv audit: file not found at %r" % path)
        return problems

    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh))
    except Exception as exc:
        problems.append("soil_rci.csv audit: could not read/parse file (%s)" % exc)
        return problems

    if not rows:
        problems.append("soil_rci.csv audit: file has no data rows")
        return problems

    seen_codes = {}
    for i, row in enumerate(rows, start=2):  # header is row 1
        low = {str(k).strip().lower(): v for k, v in row.items() if k}
        code = (low.get("uscs_code") or "").strip().upper()
        if not code:
            problems.append("soil_rci.csv row %d: blank uscs_code" % i)
            continue

        if code in seen_codes:
            problems.append(
                "soil_rci.csv row %d: duplicate uscs_code %r (first seen row %d) "
                "-- the later row silently wins in load_rci_csv()"
                % (i, code, seen_codes[code])
            )
        seen_codes[code] = i

        if known_codes is not None and code not in known_codes:
            problems.append(
                "soil_rci.csv row %d: uscs_code %r is not in the built-in "
                "USCS set %s -- it will never be looked up unless a soil FC "
                "actually produces this exact code"
                % (i, code, sorted(known_codes))
            )

        dry, moist, wet = (
            _to_float(low.get("rci_dry")),
            _to_float(low.get("rci_moist")),
            _to_float(low.get("rci_wet")),
        )
        vals = [v for v in (dry, moist, wet) if v is not None]
        if len(vals) < 2:
            continue  # not enough data points to check monotonicity
        if dry is not None and moist is not None and dry < moist:
            problems.append(
                "soil_rci.csv row %d (%s): rci_dry (%s) < rci_moist (%s) -- "
                "soil should not get STRONGER as it gets wetter"
                % (i, code, dry, moist)
            )
        if moist is not None and wet is not None and moist < wet:
            problems.append(
                "soil_rci.csv row %d (%s): rci_moist (%s) < rci_wet (%s) -- "
                "soil should not get STRONGER as it gets wetter"
                % (i, code, moist, wet)
            )
        if dry is not None and wet is not None and dry < wet:
            problems.append(
                "soil_rci.csv row %d (%s): rci_dry (%s) < rci_wet (%s) -- "
                "soil should not get STRONGER as it gets wetter"
                % (i, code, dry, wet)
            )

    return problems


# =============================================================================
# Vehicle_Data/Vehicles_Can.csv
# =============================================================================

def audit_vehicles_csv(csv_path=None):
    """
    Return a list of human-readable problem strings for Vehicles_Can.csv.
    Empty list = clean.
    """
    problems = []
    path = csv_path or VEHICLES_CSV

    if not os.path.isfile(path):
        problems.append("Vehicles_Can.csv audit: file not found at %r" % path)
        return problems

    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            fieldnames = [str(f).strip().lower() for f in (reader.fieldnames or [])]
            rows = list(reader)
    except Exception as exc:
        problems.append("Vehicles_Can.csv audit: could not read/parse file (%s)" % exc)
        return problems

    missing_cols = [c for c in _REQUIRED_VEHICLE_COLUMNS if c not in fieldnames]
    if missing_cols:
        problems.append(
            "Vehicles_Can.csv audit: missing expected column(s) %s "
            "(load_vehicles_csv() also accepts a few aliases -- this check "
            "only looks for the canonical names)" % missing_cols
        )

    if not rows:
        problems.append("Vehicles_Can.csv audit: file has no data rows")
        return problems

    seen_names = {}
    for i, row in enumerate(rows, start=2):
        low = {str(k).strip().lower(): v for k, v in row.items() if k}
        name = (low.get("name") or "").strip()
        if not name:
            problems.append("Vehicles_Can.csv row %d: blank name" % i)
            continue

        if name in seen_names:
            problems.append(
                "Vehicles_Can.csv row %d: duplicate vehicle name %r (first "
                "seen row %d) -- load_vehicles_csv() keys by name, so the "
                "later row silently overwrites the earlier one"
                % (i, name, seen_names[name])
            )
        seen_names[name] = i

        vci_1 = _to_float(low.get("vci_1"))
        vci_50 = _to_float(low.get("vci_50"))
        if vci_1 is not None and vci_50 is not None and vci_1 > vci_50:
            problems.append(
                "Vehicles_Can.csv row %d (%s): vci_1 (%s) > vci_50 (%s) -- "
                "a vehicle needing MORE bearing capacity for a single pass "
                "than for sustained fifty-pass traffic is almost certainly "
                "a data-entry error (columns swapped?)"
                % (i, name, vci_1, vci_50)
            )

        for col in (
            "max_road_spd_kph", "max_on_road_grad", "max_off_road_grad",
            "vehicle_width_m", "max_override_diameter_m",
            "min_turning_radius_m", "vci_1", "vci_50",
        ):
            if col not in low:
                continue
            raw = low.get(col)
            if raw is None or str(raw).strip() == "":
                continue
            val = _to_float(raw)
            if val is None:
                problems.append(
                    "Vehicles_Can.csv row %d (%s): column %r has a "
                    "non-numeric value %r" % (i, name, col, raw)
                )
            elif val < 0:
                problems.append(
                    "Vehicles_Can.csv row %d (%s): column %r is negative "
                    "(%s)" % (i, name, col, val)
                )

    return problems


# =============================================================================
# USCS_TO_SENSITIVITY_KEY <-> _BUILTIN_USCS_RCI coverage
# =============================================================================

def audit_uscs_sensitivity_coverage():
    """
    Return a list of human-readable problem strings for a mismatch between
    ccm_step2_mobility._BUILTIN_USCS_RCI and .USCS_TO_SENSITIVITY_KEY.
    Empty list = clean.
    """
    problems = []
    try:
        import ccm_step2_mobility as _step2
    except Exception as exc:
        problems.append(
            "USCS coverage audit: could not import ccm_step2_mobility (%s) "
            "-- skipping." % exc
        )
        return problems

    rci_codes = set(_step2._BUILTIN_USCS_RCI)
    sens_codes = set(_step2.USCS_TO_SENSITIVITY_KEY)

    only_in_rci = sorted(rci_codes - sens_codes)
    only_in_sens = sorted(sens_codes - rci_codes)

    if only_in_rci:
        problems.append(
            "USCS coverage audit: code(s) %s are in _BUILTIN_USCS_RCI but "
            "missing from USCS_TO_SENSITIVITY_KEY -- apply_weather_to_rci() "
            "will pass these through unmapped, so rainfall adjustment "
            "silently skips them" % only_in_rci
        )
    if only_in_sens:
        problems.append(
            "USCS coverage audit: code(s) %s are in USCS_TO_SENSITIVITY_KEY "
            "but missing from _BUILTIN_USCS_RCI -- dead entries with no "
            "corresponding RCI values" % only_in_sens
        )

    sens_values = list(_step2.USCS_TO_SENSITIVITY_KEY.values())
    if len(sens_values) != len(set(sens_values)):
        seen = {}
        for code, val in _step2.USCS_TO_SENSITIVITY_KEY.items():
            seen.setdefault(val, []).append(code)
        dupes = {v: codes for v, codes in seen.items() if len(codes) > 1}
        problems.append(
            "USCS coverage audit: USCS_TO_SENSITIVITY_KEY has duplicate "
            "target value(s) %s -- apply_weather_to_rci()'s reverse mapping "
            "(back = {v: k for k, v in ...}) keeps only one USCS code per "
            "target, silently dropping the other(s) on the round trip back"
            % dupes
        )

    return problems


# =============================================================================
# Driver
# =============================================================================

def audit_all():
    """Run every audit and return a combined list of problem strings."""
    problems = []
    problems.extend(audit_soil_rci())
    problems.extend(audit_vehicles_csv())
    problems.extend(audit_uscs_sensitivity_coverage())
    return problems


def main():
    problems = audit_all()
    if not problems:
        print("ccm_data_audit: OK -- soil_rci.csv, Vehicles_Can.csv, and "
              "USCS_TO_SENSITIVITY_KEY are all internally consistent.")
        return 0
    print("ccm_data_audit: %d problem(s) found:\n" % len(problems))
    for p in problems:
        print("  - %s" % p)
    return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())

# <<< END OF FILE >>>
