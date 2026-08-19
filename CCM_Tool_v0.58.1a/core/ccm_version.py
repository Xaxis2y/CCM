# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# -*- coding: utf-8 -*-
"""
ccm_version.py — single source of truth for the CCM Tool release number.

v0.57 post-review "5.1" (see CCM_Tool_v0.57_Review.md and CHANGELOG_v0.57.md):
before this file existed, "0.57" was a literal string repeated in 33+ module
docstrings/`VERSION = "0.57"` lines, plus embedded in 6+ filenames (the .pyt,
its .pyt.xml sidecars, and the User Manual), all of which had to be edited by
hand — and had already drifted once (test method names like
`test_version_is_047` asserting `"0.57"`; two independent release-file
manifests in build.py and package_ccm_v057.py that no longer agreed; see
CHANGELOG_v0.57.md "M-5").

This module does NOT change how any of the 27 existing production modules
report their own version today — each still carries its own literal
`VERSION = "0.57"` line, and package_ccm_v057.py's static_checks() still
verifies every one of them says the same thing. What changes is *tooling*:

  - package_ccm_v057.py and build.py both import VERSION from here instead
    of each hard-coding their own literal (this alone was already a source
    of drift — see M-5), and build.py's file manifest is now DERIVED from
    package_ccm_v057.py's, so there is exactly one list to maintain instead
    of two that can silently disagree.
  - bump_version.py (companion script, same folder) is what actually
    performs a version bump: it rewrites this file, every module's
    `VERSION = "..."` line, the .pyt + its .pyt.xml sidecars' filenames and
    embedded version text, and the User Manual filename, all from one
    invocation — `python bump_version.py 0.57.1` — instead of the ~40-file,
    6-rename manual sweep the project's own CHANGELOG entries describe
    doing by hand for every prior release.

Running bump_version.py is a real release action (renames the toolbox ArcGIS
Pro has registered) — follow the project's existing release protocol
afterwards: package_ccm_v057.py --verify-only in a clean environment, then
the licensed ArcPy smoke tests on a machine with ArcGIS Pro, before calling
any release done. This file being introduced does NOT itself constitute a
version bump; TOOLNAME/VERSION below are set to match the current v0.57
release exactly.
"""

TOOLNAME = "CCM_Tool"
VERSION = "0.58.1"  # v0.58.1 -- bumped by bump_version.py from v0.57. Review this line's comment.
RELEASE_NAME = f"{TOOLNAME}_v{VERSION}"
TOOLBOX_FILENAME = f"{RELEASE_NAME}.pyt"

# <<< END OF FILE >>>
