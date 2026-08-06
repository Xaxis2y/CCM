<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
<!-- Copyright (c) 2026 Eui Soo SON -->

# CCM Tool — working rules for AI sessions

## Rule 1 — every change is a versioned release

Any code/behaviour modification bumps the version (patch for fixes, minor for
features) and the bump must reach ALL of:

1. Every module `VERSION` constant (`*.py`) and the `.pyt` `toolversion`
2. Toolbox filename `CCM_Tool_v<ver>.pyt` + ALL `.pyt.xml` sidecars (rename)
3. `build.py` PY_FILES entry for the .pyt
4. Test assertions (`tests/test_ccm.py`, `tests/test_v050.py`,
   `tests/arcpy_smoke_test.py`)
5. `README.md` title + component table, `PROJECT_STATUS.md` current-version
   line, `TASKS.md` release row
6. `CHANGELOG_v<minor>.md` — new section describing the change
7. **User manual** — `CCM_Tool_v<ver>_User_Manual.docx`: title-page
   version, section 10.4 version-history row, and content updates when the
   change is user-facing
8. Rebuild `CCM_Tool_v<ver>.zip` via `python build.py` (version is read
   from `ccm_project_config.VERSION` automatically)

Nothing ships until `build.py` reports N/N files OK and the pytest suite
passes.

## Rule 2 — verify every file write (this folder truncates writes!)

The mounted folder has silently truncated large writes multiple times
(v0.45, v0.50.2 both shipped repairs for it). The `# <<< END OF FILE >>>`
marker alone is NOT proof — truncated files can still parse. After EVERY
write to this folder:

1. Write to a local temp path first, then copy in and **compare md5 of
   source vs destination** — never trust a Write/Edit result unverified
2. `ast.parse` + pyflakes undefined-name scan for .py/.pyt (build.py does
   this automatically)
3. For .md/.docx: check the tail is intact (docx: validate + text-extract
   spot check)
4. Every .py/.pyt (except build.py, test_ccm.py) must end with
   `# <<< END OF FILE >>>`

## Conventions

- Config keys live in `ccm_project_config._DEFAULTS`; tools are invoked by
  parameter NAME via `run_tool` (never positional index lists)
- Map rendering goes through `ccm_map_display.py` — one visual language
  (speed surface = only filled layer, red = No-Go only)
- New tool parameters are APPENDED to preserve existing indices
