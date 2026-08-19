# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# ccm_debug.py
# Opt-in diagnostic helper for the many "except Exception: pass" handlers
# spread across the CCM Tool codebase.
#
# VERSION = "0.57"
"""
Why this exists
----------------
v0.57 post-review finding "5.5" counted roughly 105 bare
``except Exception: pass`` handlers across the toolbox. Each one is
individually defensible -- a probe against optional/malformed GIS data that
should degrade gracefully rather than abort a long-running geoprocessing
tool -- but collectively they make field problems very hard to diagnose,
because nothing is ever recorded about *what* was swallowed or *where*.

Rewriting all 105 call sites to add rich error handling was explicitly
scoped OUT of this pass (see the review): the goal here is infrastructure
only -- a single opt-in helper that individual call sites can adopt
incrementally, one at a time, without changing the swallow-and-continue
control flow that is often the correct behaviour.

Usage
-----
    try:
        risky_probe()
    except Exception as exc:
        _debug(exc, "reading optional XYZ field")
        # ... existing fallback / pass behaviour unchanged ...

By default this is a silent no-op (matching today's behaviour exactly), so
adopting it at a call site is a zero-risk, zero-behaviour-change edit until
someone actually opts in via the environment variable below.

Turning it on
--------------
Set the environment variable ``CCM_DEBUG=1`` (any of ``1``, ``true``, ``yes``,
case-insensitive) before launching ArcGIS Pro / running a tool, and every
adopted call site will additionally emit a one-line
``arcpy.AddWarning`` (if arcpy is available and messages/AddWarning can be
reached) or ``print`` to stderr, of the form::

    [CCM_DEBUG] <context>: <ExceptionType>: <message>

This is deliberately terse (a summary line, not a full traceback) so it is
safe to leave scattered through a long geoprocessing run without flooding
the Results pane; set ``CCM_DEBUG_TRACEBACK=1`` in addition for the full
``traceback.format_exc()`` text when actively troubleshooting.
"""

import os
import sys
import traceback

VERSION = "0.57"


def _debug_enabled():
    return os.environ.get("CCM_DEBUG", "").strip().lower() in ("1", "true", "yes")


def _traceback_enabled():
    return os.environ.get("CCM_DEBUG_TRACEBACK", "").strip().lower() in ("1", "true", "yes")


def _debug(exc, context="", messages=None):
    """
    Opt-in diagnostic hook for an otherwise-swallowed exception.

    Parameters
    ----------
    exc : BaseException
        The exception object caught by the call site (from ``except
        Exception as exc:``).
    context : str
        A short human-readable description of what was being attempted,
        e.g. ``"reading optional MGCP attribute"``.
    messages : optional
        The ArcGIS ``messages`` object passed into a tool's ``execute()``,
        if available at the call site. When given and CCM_DEBUG is enabled,
        the note is also routed through ``messages.addWarningMessage()`` so
        it shows up in the Geoprocessing Results pane, not just stderr.

    Returns
    -------
    None.  Never raises -- a diagnostic helper must not itself become a new
    source of failure in a swallow-and-continue handler.
    """
    if not _debug_enabled():
        return
    try:
        line = "[CCM_DEBUG] %s: %s: %s" % (
            context or "(no context)", type(exc).__name__, exc,
        )
        if _traceback_enabled():
            line += "\n" + traceback.format_exc()

        wrote_to_messages = False
        if messages is not None:
            try:
                messages.addWarningMessage(line)
                wrote_to_messages = True
            except Exception:
                wrote_to_messages = False

        if not wrote_to_messages:
            try:
                import arcpy
                arcpy.AddWarning(line)
            except Exception:
                print(line, file=sys.stderr)
    except Exception:
        # A diagnostic helper must never mask or replace the original,
        # already-handled exception at the call site.
        pass

# <<< END OF FILE >>>
