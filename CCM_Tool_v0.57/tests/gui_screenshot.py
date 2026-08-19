# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
r"""
tests/gui_screenshot.py -- v0.57 headless GUI smoke test + screenshots
=================================================================
Drives CCM_Data_Scanner_GUI.py under a virtual display so its layout can be
verified without a human at the keyboard.  Captures three states:

    gui_1_idle.png      window as it opens
    gui_2_scanning.png  mid-scan (log streaming, progress pulsing)
    gui_3_results.png   after the scan, results panel visible

Usage (Linux, needs Xvfb + scrot or ImageMagick):

    xvfb-run -s "-screen 0 1100x1000x24" python3 tests/gui_screenshot.py OUT_DIR

This is a developer/CI aid.  It is not part of the shipped application.
"""

import os
import sys
import time
import subprocess

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (_ROOT, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import tkinter as tk                      # noqa: E402
import CCM_Data_Scanner_GUI as gui        # noqa: E402
import make_fake_data as fake             # noqa: E402


VERSION = "0.57"


def shoot(path):
    """Capture the whole virtual screen."""
    for cmd in (["scrot", "-o", path], ["import", "-window", "root", path]):
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=25)
            return True
        except Exception:
            continue
    return False


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    out_dir = os.path.abspath(argv[0]) if argv else os.path.join(_HERE,
                                                                 "_gui_shots")
    os.makedirs(out_dir, exist_ok=True)

    data_root = os.path.join(out_dir, "DATA")
    fake.build(data_root)
    aoi = os.path.join(data_root, "Extent", "AOI_Lebanon.shp")
    proj = os.path.join(out_dir, "PROJECT")

    root = tk.Tk()
    app = gui.ScannerApp(root)
    # Never launch a browser during an automated run.
    app.chk_open._toggle()
    app.row_data.set(data_root)
    app.row_aoi.set(aoi)
    app.row_out.set(proj)

    results = {}

    def stage_idle():
        root.update()
        results["idle"] = shoot(os.path.join(out_dir, "gui_1_idle.png"))
        root.after(150, stage_scan)

    def stage_scan():
        app._start_scan()
        root.after(160, stage_mid)

    def stage_mid():
        root.update()
        results["scanning"] = shoot(
            os.path.join(out_dir, "gui_2_scanning.png"))
        root.after(1800, stage_done)

    def stage_done():
        deadline = time.time() + 20
        while app.scanning and time.time() < deadline:
            root.update()
            time.sleep(0.05)
        root.update()
        root.update_idletasks()
        time.sleep(0.4)
        root.update()
        results["results"] = shoot(os.path.join(out_dir, "gui_3_results.png"))
        results["catalog"] = app.catalog is not None
        results["html"] = bool(app.outputs.get("html"))
        root.after(120, root.destroy)

    root.after(500, stage_idle)
    root.mainloop()

    print("GUI smoke test results:")
    for k in ("idle", "scanning", "results", "catalog", "html"):
        print("  %-10s %s" % (k, results.get(k)))
    if app.catalog:
        rd = app.catalog.get("readiness") or {}
        print("  readiness  %.1f (%s) can_proceed=%s"
              % (rd.get("score", 0), rd.get("label"), rd.get("can_proceed")))
    print("  output dir %s" % out_dir)
    return 0 if results.get("catalog") else 1


if __name__ == "__main__":
    sys.exit(main())

# <<< END OF FILE >>>
