# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
r"""
CCM_Data_Scanner_GUI.py -- CCM Data Intelligence desktop application
=====================================================================
Updated for the factual v0.57 release.

A clean, dependency-free desktop front end for the CCM Data Intelligence
engine.  Pick a folder, press one button, read the answer.

    "Give me whatever GIS data you have. I will inventory it, preserve its
     identity, report measured metadata and limitations, and show what is
     missing before any source-selection decision is made."

Why tkinter
-----------
tkinter ships with every CPython install, including the ArcGIS Pro conda
environment (arcgispro-py3).  That means this application runs on an analyst's
machine with NOTHING to install -- no PyQt, no wx, no pip step -- and it also
freezes cleanly into a single .exe with PyInstaller (see build_exe.py).

What it does
------------
    1. Browse to a data folder (optionally an AOI and a report folder).
    2. Press SCAN.  The engine runs on a worker thread, so the window never
       freezes, and progress is streamed into the log panel live.
    3. Review factual per-role dataset counts and missing-role warnings.
    4. Press OPEN HTML REPORT for the full styled report.

The scan is READ-ONLY: nothing in the data folder is modified.

Run it
------
    python CCM_Data_Scanner_GUI.py
    CCM_Data_Scanner.exe                (after build_exe.py)
"""

import os
import sys
import queue
import threading
import traceback
import webbrowser
import subprocess

try:
    import tkinter as tk
    from tkinter import filedialog, font as tkfont
    _HAVE_TKINTER = True
    _TKINTER_IMPORT_ERROR = None
except Exception as _tk_exc:                              # pragma: no cover
    # v0.57 post-review "5.5": tkinter normally ships with every CPython
    # install, including ArcGIS Pro's arcgispro-py3 conda env (see the module
    # docstring above), so this is not expected on an analyst's machine.  But
    # importing it unconditionally at module scope meant this file -- and
    # therefore the whole pytest suite, since tests/test_v057_data_intelligence.py
    # imports it -- failed to even LOAD on any Python built without Tcl/Tk
    # (e.g. a minimal headless CI image). _NoTkinterModule lets the module
    # import and its tk.Frame-based widget classes be *defined* (never
    # instantiated) in that environment; main() below raises a clear error
    # instead of a confusing traceback if someone actually tries to launch
    # the GUI without real tkinter installed.
    _HAVE_TKINTER = False
    _TKINTER_IMPORT_ERROR = _tk_exc

    class _NoTkinterModule:
        def __getattr__(self, name):
            return object

    tk = _NoTkinterModule()
    filedialog = None
    tkfont = None

VERSION = "0.57"
APP_TITLE = "CCM Data Scanner"
APP_SUBTITLE = "Cross-Country Mobility  ·  Data Intelligence"

# ---------------------------------------------------------------------------
# Make the engine importable whether we are running from source or frozen.
# ---------------------------------------------------------------------------
if getattr(sys, "frozen", False):
    _HERE = os.path.dirname(os.path.abspath(sys.executable))
    _BUNDLE = getattr(sys, "_MEIPASS", _HERE)
    for _p in (_BUNDLE, _HERE):
        if _p not in sys.path:
            sys.path.insert(0, _p)
else:
    _HERE = os.path.dirname(os.path.abspath(__file__))
    if _HERE not in sys.path:
        sys.path.insert(0, _HERE)

ENGINE_ERROR = None
try:
    import ccm_data_catalog as _cat
    import ccm_data_report as _report
    # ArcPy geoprocessing is not thread-safe. The desktop GUI scans on a
    # worker thread, so it uses GDAL/OGR or pure-Python readers. Run the ArcGIS
    # Step 0b tool for ArcPy-backed metadata.
    _cat.set_arcpy_enabled(False)
except Exception as _exc:                                # pragma: no cover
    _cat = _report = None
    ENGINE_ERROR = (
        "The CCM Data Intelligence engine could not be loaded.\n\n%s\n\n"
        "These three files must sit next to this application:\n"
        "    ccm_data_catalog.py\n"
        "    ccm_data_report.py\n"
        "    ccm_step0b_intelligence.py" % _exc
    )


# ===========================================================================
# Palette -- the same colours as the HTML report, so the two read as one tool
# ===========================================================================
class C:
    PAGE = "#f4f3ef"
    SURFACE = "#ffffff"
    HEADER = "#1a1a19"
    HEADER_SUB = "#a8a69d"
    INK = "#0b0b0b"
    INK2 = "#52514e"
    MUTED = "#898781"
    BORDER = "#e1e0d9"
    LINE = "#c3c2b7"
    FIELD = "#fcfcfb"

    PRIMARY = "#2a78d6"
    PRIMARY_HOVER = "#1c5cab"
    PRIMARY_DIM = "#9ec5f4"

    GOOD = "#0ca30c"
    WARN = "#fab219"
    SERIOUS = "#ec835a"
    CRIT = "#d03b3b"

    LOG_BG = "#1a1a19"
    LOG_INK = "#d8d7d0"
    LOG_DIM = "#898781"
    LOG_OK = "#4ec94e"
    LOG_WARN = "#fab219"
    LOG_ERR = "#e66767"


# ===========================================================================
# Small widgets
# ===========================================================================

class FlatButton(tk.Frame):
    """
    A flat, coloured button with a hover state.

    tk.Button ignores background colour on Windows' native theme, and ttk
    buttons need a whole custom style engine to colour reliably.  A Frame with
    a Label inside is fully controllable on every platform and behaves the
    same everywhere.
    """

    def __init__(self, master, text, command=None, kind="primary",
                 width=None, pad=(18, 11), **kw):
        self.kind = kind
        bg, fg, hover, border = self._palette(kind)
        super().__init__(master, bg=border, bd=0,
                         highlightthickness=0, **kw)
        self._inner = tk.Frame(self, bg=bg, bd=0, highlightthickness=0)
        self._inner.pack(fill="both", expand=True, padx=1, pady=1)
        self._label = tk.Label(
            self._inner, text=text, bg=bg, fg=fg,
            font=("Segoe UI", 10, "bold" if kind == "primary" else "normal"),
            padx=pad[0], pady=pad[1], cursor="hand2")
        self._label.pack(fill="both", expand=True)
        if width:
            self._label.configure(width=width)

        self._bg, self._hover, self._fg = bg, hover, fg
        self._command = command
        self._enabled = True

        for w in (self, self._inner, self._label):
            w.bind("<Button-1>", self._click)
            w.bind("<Enter>", self._enter)
            w.bind("<Leave>", self._leave)

    @staticmethod
    def _palette(kind):
        if kind == "primary":
            return C.PRIMARY, "#ffffff", C.PRIMARY_HOVER, C.PRIMARY
        if kind == "success":
            return C.GOOD, "#ffffff", "#0a8a0a", C.GOOD
        if kind == "ghost":
            return C.SURFACE, C.INK2, "#f0efec", C.LINE
        return C.SURFACE, C.INK2, "#f0efec", C.BORDER

    def _click(self, _e=None):
        if self._enabled and self._command:
            self._command()

    def _enter(self, _e=None):
        if self._enabled:
            self._inner.configure(bg=self._hover)
            self._label.configure(bg=self._hover)

    def _leave(self, _e=None):
        if self._enabled:
            self._inner.configure(bg=self._bg)
            self._label.configure(bg=self._bg)

    def set_text(self, text):
        self._label.configure(text=text)

    def set_enabled(self, enabled):
        self._enabled = bool(enabled)
        if enabled:
            self._inner.configure(bg=self._bg)
            self._label.configure(bg=self._bg, fg=self._fg, cursor="hand2")
            self.configure(bg=self._palette(self.kind)[3])
        else:
            dim = C.PRIMARY_DIM if self.kind == "primary" else "#f0efec"
            self._inner.configure(bg=dim)
            self._label.configure(bg=dim, fg="#ffffff" if
                                  self.kind == "primary" else C.MUTED,
                                  cursor="arrow")
            self.configure(bg=dim)


class PathRow(tk.Frame):
    """A labelled path field with a Browse button and an optional hint."""

    def __init__(self, master, number, label, hint, browse_cmd,
                 required=False):
        super().__init__(master, bg=C.SURFACE)
        self.columnconfigure(1, weight=1)

        badge = tk.Label(self, text=str(number), bg=C.PAGE, fg=C.MUTED,
                         font=("Consolas", 9), width=3, pady=2)
        badge.grid(row=0, column=0, sticky="w", padx=(0, 10), pady=(0, 2))

        head = tk.Frame(self, bg=C.SURFACE)
        head.grid(row=0, column=1, columnspan=2, sticky="w", pady=(0, 2))
        tk.Label(head, text=label, bg=C.SURFACE, fg=C.INK,
                 font=("Segoe UI", 10, "bold")).pack(side="left")
        tk.Label(head, text="  REQUIRED" if required else "  OPTIONAL",
                 bg=C.SURFACE, fg=C.CRIT if required else C.MUTED,
                 font=("Segoe UI", 8, "bold")).pack(side="left")

        self.var = tk.StringVar()
        shell = tk.Frame(self, bg=C.LINE)
        shell.grid(row=1, column=1, sticky="ew", padx=(0, 8))
        self.entry = tk.Entry(shell, textvariable=self.var, bd=0,
                              bg=C.FIELD, fg=C.INK, font=("Segoe UI", 10),
                              insertbackground=C.INK,
                              highlightthickness=0, relief="flat")
        self.entry.pack(fill="x", padx=1, pady=1, ipady=7, ipadx=8)

        btn = FlatButton(self, "Browse", command=browse_cmd, kind="ghost",
                         pad=(16, 8))
        btn.grid(row=1, column=2, sticky="e")

        tk.Label(self, text=hint, bg=C.SURFACE, fg=C.MUTED,
                 font=("Segoe UI", 8), anchor="w", justify="left"
                 ).grid(row=2, column=1, columnspan=2, sticky="w",
                        pady=(4, 0))

    def get(self):
        return self.var.get().strip().strip('"')

    def set(self, value):
        self.var.set(value or "")


class CheckRow(tk.Frame):
    """A checkbox that matches the rest of the palette."""

    def __init__(self, master, text, initial=True):
        super().__init__(master, bg=C.SURFACE)
        self.var = tk.BooleanVar(value=initial)
        self._box = tk.Label(self, width=2, height=1, bd=0,
                             bg=C.PRIMARY if initial else C.SURFACE,
                             fg="#ffffff", text="✓" if initial else "",
                             font=("Segoe UI", 9, "bold"),
                             highlightthickness=1,
                             highlightbackground=C.LINE, cursor="hand2")
        self._box.pack(side="left")
        lbl = tk.Label(self, text=text, bg=C.SURFACE, fg=C.INK2,
                       font=("Segoe UI", 9), cursor="hand2")
        lbl.pack(side="left", padx=(9, 0))
        for w in (self._box, lbl):
            w.bind("<Button-1>", self._toggle)

    def _toggle(self, _e=None):
        self.var.set(not self.var.get())
        on = self.var.get()
        self._box.configure(bg=C.PRIMARY if on else C.SURFACE,
                            text="✓" if on else "")

    def get(self):
        return self.var.get()


def card(master, **kw):
    """A white panel with a hairline border."""
    outer = tk.Frame(master, bg=C.BORDER, bd=0, highlightthickness=0, **kw)
    inner = tk.Frame(outer, bg=C.SURFACE, bd=0, highlightthickness=0)
    inner.pack(fill="both", expand=True, padx=1, pady=1)
    return outer, inner


class ScrollFrame(tk.Frame):
    """
    A vertically scrollable container.

    The results panel appears only after a scan, so the window's content
    height changes at runtime and can exceed a laptop screen.  Rather than
    guessing a window size that fits every case, the whole body scrolls --
    nothing can ever be clipped out of reach, on any display.
    """

    def __init__(self, master, bg=C.PAGE, **kw):
        super().__init__(master, bg=bg, **kw)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.vbar = tk.Scrollbar(self, orient="vertical", bd=0,
                                 highlightthickness=0, width=11,
                                 troughcolor=C.PAGE, bg=C.LINE,
                                 activebackground=C.MUTED,
                                 command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self._on_scroll)
        self.canvas.pack(side="left", fill="both", expand=True)

        self.body = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.body,
                                              anchor="nw")

        self.body.bind("<Configure>", self._on_body_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.canvas.bind_all(seq, self._on_wheel)

    def _on_scroll(self, first, last):
        # Show the scrollbar only when there is something to scroll to.
        if float(first) <= 0.0 and float(last) >= 1.0:
            self.vbar.pack_forget()
        else:
            self.vbar.pack(side="right", fill="y")
        self.vbar.set(first, last)

    def _on_body_configure(self, _e=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfigure(self._win, width=event.width)

    def _on_wheel(self, event):
        if not self.canvas.winfo_exists():
            return
        try:
            first, last = self.canvas.yview()
        except Exception:
            return
        if first <= 0.0 and last >= 1.0:
            return                                   # nothing to scroll
        if getattr(event, "num", None) == 4:
            delta = -1
        elif getattr(event, "num", None) == 5:
            delta = 1
        else:
            delta = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(delta * 2, "units")

    def scroll_to_bottom(self):
        self.update_idletasks()
        self.canvas.yview_moveto(1.0)


def section_label(master, text):
    return tk.Label(master, text=text, bg=C.SURFACE, fg=C.MUTED,
                    font=("Segoe UI", 8, "bold"), anchor="w")


# ===========================================================================
# The application
# ===========================================================================

class ScannerApp(object):

    def __init__(self, root):
        self.root = root
        self.queue = queue.Queue()
        self.catalog = None
        self.outputs = {}
        self.scanning = False

        root.title("%s  v%s" % (APP_TITLE, VERSION))
        root.configure(bg=C.PAGE)
        root.minsize(820, 560)
        self._centre(root, 960, 820)
        self._set_icon(root)

        self._build_header()
        self._build_footer()          # packed to the bottom before the body

        self.scroller = ScrollFrame(root, bg=C.PAGE)
        self.scroller.pack(fill="both", expand=True)
        body = tk.Frame(self.scroller.body, bg=C.PAGE)
        body.pack(fill="both", expand=True, padx=22, pady=(18, 18))

        self._build_inputs(body)
        self._build_run(body)
        self._build_results(body)
        self._build_log(body)

        if ENGINE_ERROR:
            self._log(ENGINE_ERROR, "err")
            self.run_btn.set_enabled(False)
        else:
            self._log("Ready. Choose the folder that holds your GIS data, "
                      "then press SCAN DATA FOLDER.", "dim")
            self._log("The scan is read-only — nothing in that folder "
                      "is modified.", "dim")

        self.root.after(80, self._drain_queue)

    # ------------------------------------------------------------------ chrome
    @staticmethod
    def _centre(win, w, h):
        win.update_idletasks()
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        x, y = max(0, (sw - w) // 2), max(0, (sh - h) // 3)
        win.geometry("%dx%d+%d+%d" % (w, h, x, y))

    @staticmethod
    def _set_icon(win):
        try:
            ico = os.path.join(_HERE, "ccm.ico")
            if os.path.isfile(ico):
                win.iconbitmap(ico)
        except Exception:
            pass

    def _build_header(self):
        head = tk.Frame(self.root, bg=C.HEADER, height=92)
        head.pack(fill="x")
        head.pack_propagate(False)

        inner = tk.Frame(head, bg=C.HEADER)
        inner.pack(fill="both", expand=True, padx=24, pady=16)

        tk.Label(inner, text=APP_TITLE, bg=C.HEADER, fg="#ffffff",
                 font=("Segoe UI", 19, "bold")).pack(anchor="w")
        tk.Label(inner, text=APP_SUBTITLE, bg=C.HEADER, fg=C.HEADER_SUB,
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(1, 0))

        ver = tk.Label(head, text="v%s" % VERSION, bg=C.HEADER,
                       fg=C.HEADER_SUB, font=("Consolas", 9))
        ver.place(relx=1.0, x=-24, y=22, anchor="ne")

        # accent stripe -- the release palette, left to right
        stripe = tk.Canvas(self.root, height=4, bg=C.HEADER,
                           highlightthickness=0, bd=0)
        stripe.pack(fill="x")
        self._stripe = stripe
        stripe.bind("<Configure>", self._draw_stripe)

    def _draw_stripe(self, event):
        cv = self._stripe
        cv.delete("all")
        colours = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
                   "#e87ba4", "#008300"]
        w = max(1, event.width)
        seg = w / float(len(colours))
        for i, col in enumerate(colours):
            cv.create_rectangle(i * seg, 0, (i + 1) * seg + 1, 4,
                                fill=col, outline=col)

    # ------------------------------------------------------------------ inputs
    def _build_inputs(self, parent):
        outer, inner = card(parent)
        outer.pack(fill="x")
        pad = tk.Frame(inner, bg=C.SURFACE)
        pad.pack(fill="x", padx=20, pady=18)

        section_label(pad, "WHAT TO SCAN").pack(anchor="w", pady=(0, 12))

        self.row_data = PathRow(
            pad, 1, "Data folder",
            "Every subfolder is scanned. Put DEM, Soil, Vegetation, Hydro, "
            "MGCP … anywhere inside it.",
            self._browse_data, required=True)
        self.row_data.pack(fill="x", pady=(0, 14))

        self.row_aoi = PathRow(
            pad, 2, "Analysis extent (AOI)",
            "A polygon shapefile. Enables coverage percentages and the "
            "recommended coordinate system.",
            self._browse_aoi)
        self.row_aoi.pack(fill="x", pady=(0, 14))

        self.row_out = PathRow(
            pad, 3, "Report folder",
            "Where the HTML / JSON / TXT reports are written. Defaults to the "
            "folder above the data folder.",
            self._browse_out)
        self.row_out.pack(fill="x", pady=(0, 14))

        self.chk_open = CheckRow(pad, "Open the HTML report when the scan "
                                      "finishes", True)
        self.chk_open.pack(anchor="w")

    # --------------------------------------------------------------------- run
    def _build_run(self, parent):
        bar = tk.Frame(parent, bg=C.PAGE)
        bar.pack(fill="x", pady=(16, 0))

        self.run_btn = FlatButton(bar, "SCAN DATA FOLDER",
                                  command=self._start_scan, kind="primary",
                                  pad=(30, 13))
        self.run_btn.pack(side="left")

        self.clear_btn = FlatButton(bar, "Clear", command=self._reset,
                                    kind="ghost", pad=(18, 12))
        self.clear_btn.pack(side="left", padx=(10, 0))

        self.status = tk.Label(bar, text="", bg=C.PAGE, fg=C.MUTED,
                               font=("Segoe UI", 9))
        self.status.pack(side="left", padx=(16, 0))

        self.progress = tk.Canvas(parent, height=4, bg=C.BORDER,
                                  highlightthickness=0, bd=0)
        self.progress.pack(fill="x", pady=(12, 0))
        self._pulse_x = 0
        self._pulsing = False

    # ----------------------------------------------------------------- results
    def _build_results(self, parent):
        self.res_outer, self.res_inner = card(parent)
        pad = tk.Frame(self.res_inner, bg=C.SURFACE)
        pad.pack(fill="both", expand=True, padx=20, pady=16)
        self._res_pad = pad

        top = tk.Frame(pad, bg=C.SURFACE)
        top.pack(fill="x")

        self.dataset_count_lbl = tk.Label(
            top, text="--", bg=C.SURFACE, fg=C.INK,
            font=("Segoe UI", 40, "bold"))
        self.dataset_count_lbl.pack(side="left")
        self.dataset_count_suffix = tk.Label(
            top, text="datasets", bg=C.SURFACE,
            fg=C.MUTED, font=("Segoe UI", 13))
        self.dataset_count_suffix.pack(
            side="left", padx=(6, 0), pady=(16, 0))

        meta = tk.Frame(top, bg=C.SURFACE)
        meta.pack(side="left", padx=(18, 0), pady=(8, 0))
        self.label_lbl = tk.Label(meta, text="", bg=C.SURFACE, fg=C.INK,
                                  font=("Segoe UI", 13, "bold"), anchor="w")
        self.label_lbl.pack(anchor="w")
        self.verdict_lbl = tk.Label(meta, text="", bg=C.SURFACE, fg=C.INK2,
                                    font=("Segoe UI", 9), anchor="w")
        self.verdict_lbl.pack(anchor="w")

        btns = tk.Frame(top, bg=C.SURFACE)
        btns.pack(side="right", pady=(10, 0))
        self.open_btn = FlatButton(btns, "OPEN HTML REPORT",
                                   command=self._open_report, kind="success",
                                   pad=(20, 11))
        self.open_btn.pack(side="left")
        self.folder_btn = FlatButton(btns, "Open folder",
                                     command=self._open_folder, kind="ghost",
                                     pad=(16, 10))
        self.folder_btn.pack(side="left", padx=(8, 0))

        self.bars = tk.Canvas(pad, bg=C.SURFACE, highlightthickness=0, bd=0,
                              height=150)
        self.bars.pack(fill="x", pady=(16, 0))
        # Re-draw the bars whenever the window is resized, so they always
        # span the available width instead of a width measured once.
        self.bars.bind("<Configure>", self._on_bars_resize)

        self.gates_frame = tk.Frame(pad, bg=C.SURFACE)
        self.gates_frame.pack(fill="x", pady=(12, 0))

    def _on_bars_resize(self, _e=None):
        if self.catalog:
            self._draw_bars(self._inventory_rows(self.catalog))

    def _show_results(self, show):
        if show:
            self.res_outer.pack(fill="x", pady=(16, 0), before=self.log_outer)
        else:
            self.res_outer.pack_forget()

    # --------------------------------------------------------------------- log
    def _build_log(self, parent):
        self.log_outer = tk.Frame(parent, bg=C.LOG_BG)
        self.log_outer.pack(fill="x", pady=(16, 0))

        bar = tk.Frame(self.log_outer, bg=C.LOG_BG)
        bar.pack(fill="x", padx=14, pady=(10, 0))
        tk.Label(bar, text="SCAN LOG", bg=C.LOG_BG, fg=C.LOG_DIM,
                 font=("Segoe UI", 8, "bold")).pack(side="left")

        wrap = tk.Frame(self.log_outer, bg=C.LOG_BG)
        wrap.pack(fill="both", expand=True, padx=14, pady=(6, 12))

        sb = tk.Scrollbar(wrap, bd=0, highlightthickness=0,
                          troughcolor=C.LOG_BG, bg="#3a3a37",
                          activebackground="#4a4a46", width=10)
        sb.pack(side="right", fill="y")

        self.log = tk.Text(wrap, bg=C.LOG_BG, fg=C.LOG_INK, bd=0,
                           highlightthickness=0, relief="flat",
                           font=("Consolas", 9), wrap="word", height=9,
                           yscrollcommand=sb.set, padx=2, pady=2,
                           insertbackground=C.LOG_INK)
        self.log.pack(side="left", fill="both", expand=True)
        sb.configure(command=self.log.yview)

        self.log.tag_configure("dim", foreground=C.LOG_DIM)
        self.log.tag_configure("ok", foreground=C.LOG_OK)
        self.log.tag_configure("warn", foreground=C.LOG_WARN)
        self.log.tag_configure("err", foreground=C.LOG_ERR)
        self.log.tag_configure("head", foreground="#86b6ef")
        self.log.configure(state="disabled")

    def _build_footer(self):
        foot = tk.Frame(self.root, bg=C.PAGE)
        foot.pack(side="bottom", fill="x")
        tk.Frame(foot, bg=C.BORDER, height=1).pack(fill="x")
        inner = tk.Frame(foot, bg=C.PAGE)
        inner.pack(fill="x", padx=22, pady=(9, 11))
        self.foot_lbl = tk.Label(
            inner,
            text="v0.57 reports factual inventory only. It does not calculate "
                 "Quality, Fitness, Confidence, Readiness, or automatic source "
                 "selection. Missing data is never interpreted as No-Go.",
            bg=C.PAGE, fg=C.MUTED, font=("Segoe UI", 8),
            wraplength=880, justify="left", anchor="w")
        self.foot_lbl.pack(fill="x")
        inner.bind("<Configure>",
                   lambda e: self.foot_lbl.configure(
                       wraplength=max(300, e.width - 8)))

    # ----------------------------------------------------------------- browsing
    def _browse_data(self):
        start = self.row_data.get() or os.path.expanduser("~")
        path = filedialog.askdirectory(
            title="Select the folder that holds your GIS data",
            initialdir=start if os.path.isdir(start) else os.path.expanduser("~"))
        if path:
            self.row_data.set(os.path.normpath(path))
            if not self.row_out.get():
                parent = os.path.dirname(os.path.normpath(path))
                self.row_out.set(parent or path)
            if not self.row_aoi.get():
                self._guess_aoi(path)

    def _guess_aoi(self, root):
        """Offer an obvious AOI candidate without forcing one."""
        try:
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames
                               if not d.lower().endswith(".gdb")]
                for fn in filenames:
                    low = fn.lower()
                    if low.endswith(".shp") and any(
                            k in low for k in ("aoi", "extent", "boundary",
                                               "study")):
                        self.row_aoi.set(
                            os.path.normpath(os.path.join(dirpath, fn)))
                        self._log("Found a likely analysis extent: %s"
                                  % fn, "dim")
                        return
        except Exception:
            pass

    def _browse_aoi(self):
        start = self.row_data.get() or os.path.expanduser("~")
        path = filedialog.askopenfilename(
            title="Select the analysis extent (AOI) polygon (.shp)",
            initialdir=start if os.path.isdir(start) else os.path.expanduser("~"),
            # This standalone scanner only ever has the pure-Python
            # metadata reader available (no arcpy, no GDAL -- both are kept
            # out of the frozen .exe on purpose), and that reader only
            # understands .shp.  A GeoPackage filter here used to imply
            # support that silently didn't exist outside ArcGIS Pro.
            filetypes=[("Shapefile", "*.shp"),
                       ("All files -- arcpy/GDAL environments only", "*.*")])
        if path:
            self.row_aoi.set(os.path.normpath(path))

    def _browse_out(self):
        start = self.row_out.get() or self.row_data.get() or \
            os.path.expanduser("~")
        path = filedialog.askdirectory(
            title="Where should the reports be written?",
            initialdir=start if os.path.isdir(start) else os.path.expanduser("~"))
        if path:
            self.row_out.set(os.path.normpath(path))

    # ------------------------------------------------------------------ logging
    def _log(self, text, tag=None):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n", tag or ())
        self.log.see("end")
        self.log.configure(state="disabled")

    def _reset(self):
        if self.scanning:
            return
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self._show_results(False)
        self.catalog = None
        self.outputs = {}
        self.status.configure(text="")
        self._log("Cleared. Choose a data folder and press SCAN.", "dim")

    # ------------------------------------------------------------------- scan
    def _start_scan(self):
        if self.scanning or ENGINE_ERROR:
            return
        data_root = self.row_data.get()
        if not data_root:
            self._log("Choose a data folder first — press Browse next to "
                      "“Data folder”.", "warn")
            self._flash(self.row_data.entry)
            return
        if not os.path.isdir(data_root):
            self._log("That folder does not exist:\n    %s" % data_root, "err")
            self._flash(self.row_data.entry)
            return

        aoi = self.row_aoi.get() or None
        if aoi and not os.path.exists(aoi):
            self._log("The analysis extent was not found, continuing without "
                      "it:\n    %s" % aoi, "warn")
            aoi = None

        out = self.row_out.get() or \
            (os.path.dirname(os.path.normpath(data_root)) or data_root)

        self.scanning = True
        self.run_btn.set_enabled(False)
        self.run_btn.set_text("SCANNING…")
        self._show_results(False)
        self.status.configure(text="Working…")
        self._start_pulse()

        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self._log("CCM DATA INTELLIGENCE SCAN", "head")
        self._log("Data folder : %s" % data_root, "dim")
        self._log("Extent      : %s" % (aoi or "(none supplied)"), "dim")
        self._log("Reports     : %s" % out, "dim")
        self._log("")

        t = threading.Thread(target=self._worker,
                             args=(data_root, aoi, out), daemon=True)
        t.start()

    def _worker(self, data_root, aoi, out):
        """Runs OFF the UI thread.  Talks back only through the queue."""
        def emit(kind, payload):
            self.queue.put((kind, payload))

        try:
            emit("log", ("Scanning folder tree…", "dim"))
            catalog = _cat.build_catalog(data_root, aoi_path=aoi,
                                         project_folder=out)
            if catalog.get("error"):
                emit("log", (catalog["error"], "err"))
                emit("done", (None, {}))
                return

            st = catalog.get("stats") or {}
            emit("log", ("%d file(s) inspected." % st.get("files_scanned", 0),
                         None))
            emit("log", ("%d dataset(s) catalogued, %d unclassified, "
                         "%d duplicate group(s)."
                         % (st.get("datasets_catalogued", 0),
                            st.get("unclassified", 0),
                            st.get("duplicate_groups", 0)), None))
            emit("log", ("Metadata backend: %s"
                         % {"arcpy": "arcpy (full metadata)",
                            "gdal": "GDAL/OGR (full metadata)",
                            "header": "pure-Python header readers"}
                         .get(catalog.get("backend"),
                              catalog.get("backend")), "dim"))
            if catalog.get("aoi_unreadable"):
                emit("log", ("AOI was supplied but could not be read in "
                             "this environment -- coverage %% and the CRS "
                             "recommendation will be unavailable. This "
                             "scanner only reads .shp; use arcpy/GDAL for "
                             "other formats.", "warn"))

            for role in ("dem", "soil", "veg", "hydro", "contours",
                         "moisture", "vehicle", "extent"):
                block = catalog["roles"].get(role) or {}
                recs = block.get("records") or []
                title = _cat.ROLE_LABELS.get(role, role)
                if recs:
                    emit("log", ("  %-22s %d dataset(s)"
                                 % (title, len(recs)), "ok"))
                else:
                    emit("log", ("  %-22s not found" % title, "warn"))

            emit("log", ("Writing reports…", "dim"))
            outputs = _report.write_all(catalog, out)
            for kind in ("html", "json", "text"):
                if outputs.get(kind):
                    emit("log", ("  %-4s  %s"
                                 % (kind.upper(), outputs[kind]), None))

            self._save_project_keys(catalog, data_root, outputs, out, emit)

            emit("log", (""))
            emit("log", ("Factual inventory complete — review detected "
                         "roles and limitations before Step 1.", "ok"))
            emit("done", (catalog, outputs))
        except Exception:
            emit("log", ("The scan failed:\n%s" % traceback.format_exc(),
                         "err"))
            emit("done", (None, {}))

    @staticmethod
    def _save_project_keys(catalog, data_root, outputs, out, emit):
        """Record the scan in ccm_project.json (additive keys only)."""
        try:
            import json
            import datetime
            path = os.path.join(out, "ccm_project.json")
            existing = {}
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as fh:
                    existing = json.load(fh)
            existing.update({
                "data_root": data_root,
                "data_catalog_json": outputs.get("json"),
                "last_updated":
                    datetime.datetime.now().isoformat(timespec="seconds"),
            })
            _cat.atomic_write_text(
                path, json.dumps(existing, indent=2, ensure_ascii=False) + "\n")
            emit("log", ("  ccm_project.json updated", "dim"))
        except Exception as exc:
            emit("log", ("  ccm_project.json not updated: %s" % exc, "warn"))

    # ------------------------------------------------------------ queue / UI
    def _drain_queue(self):
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "log":
                    if isinstance(payload, tuple):
                        self._log(payload[0], payload[1])
                    else:
                        self._log(str(payload))
                elif kind == "done":
                    self._on_done(*payload)
        except queue.Empty:
            pass
        self.root.after(80, self._drain_queue)

    def _on_done(self, catalog, outputs):
        self.scanning = False
        self._stop_pulse()
        self.run_btn.set_enabled(True)
        self.run_btn.set_text("SCAN DATA FOLDER")
        self.catalog = catalog
        self.outputs = outputs or {}

        if not catalog:
            self.status.configure(text="Scan failed", fg=C.CRIT)
            return

        self.status.configure(
            text="Done — %d dataset(s) catalogued"
                 % (catalog.get("stats") or {}).get("datasets_catalogued", 0),
            fg=C.MUTED)
        self._show_results(True)
        self._render_results(catalog)
        # Bring the freshly revealed results panel into view.
        self.root.after(60, self._scroll_to_results)

        if self.chk_open.get() and self.outputs.get("html"):
            self._open_report()

    def _scroll_to_results(self):
        try:
            self.scroller.update_idletasks()
            canvas = self.scroller.canvas
            total = self.scroller.body.winfo_height()
            target = self.res_outer.winfo_y()
            if total > 0:
                canvas.yview_moveto(max(0.0, (target - 12) / float(total)))
        except Exception:
            pass

    @staticmethod
    def _inventory_rows(catalog):
        roles = catalog.get("roles") or {}
        return [{"role": role,
                 "label": _cat.ROLE_LABELS.get(role, role),
                 "count": len((roles.get(role) or {}).get("records") or [])}
                for role in _cat.CCM_ROLES if role != _cat.ROLE_MGCP]

    def _render_results(self, catalog):
        total = (catalog.get("stats") or {}).get("datasets_catalogued", 0)
        self.dataset_count_lbl.configure(text=str(total), fg=C.PRIMARY)
        self.label_lbl.configure(text="FACTUAL INVENTORY", fg=C.PRIMARY)
        self.verdict_lbl.configure(
            text="Review every role and limitation before selecting Step 1 inputs",
            fg=C.INK2)

        rows = self._inventory_rows(catalog)
        self._draw_bars(rows)

        # ---- role presence ------------------------------------------------
        for w in self.gates_frame.winfo_children():
            w.destroy()
        tk.Label(self.gates_frame, text="INVENTORY STATUS", bg=C.SURFACE,
                 fg=C.MUTED, font=("Segoe UI", 8, "bold")).pack(anchor="w",
                                                                pady=(0, 6))
        for item in rows:
            row = tk.Frame(self.gates_frame, bg=C.SURFACE)
            row.pack(fill="x", pady=1)
            ok = item["count"] > 0
            tk.Label(row, text="✓" if ok else "!", width=2,
                     bg=C.GOOD if ok else C.CRIT, fg="#ffffff",
                     font=("Segoe UI", 8, "bold")).pack(side="left")
            tk.Label(row, text=item["label"], bg=C.SURFACE, fg=C.INK,
                     font=("Segoe UI", 9)).pack(side="left", padx=(9, 6))
            tk.Label(row, text=("%d dataset(s)" % item["count"]
                               if ok else "not detected"),
                     bg=C.SURFACE, fg=C.MUTED,
                     font=("Segoe UI", 8)).pack(side="left")

    def _draw_bars(self, rows):
        """Draw one factual dataset-count bar per CCM role."""
        cv = self.bars
        cv.delete("all")
        if not rows:
            return
        row_h = 25
        want_h = row_h * len(rows) + 8
        if int(cv.cget("height")) != want_h:
            cv.configure(height=want_h)
        width = cv.winfo_width()
        if width <= 1:                       # not laid out yet
            width = 820
        label_w, val_w, band_w = 152, 46, 86
        track_x0 = label_w
        track_x1 = max(track_x0 + 60, width - val_w - band_w - 14)
        max_count = max([r.get("count", 0) for r in rows] or [1]) or 1

        for i, row in enumerate(rows):
            cy = 8 + i * row_h + 8
            cv.create_text(0, cy, text=row["label"], anchor="w",
                           fill=C.INK2, font=("Segoe UI", 9))
            cv.create_rectangle(track_x0, cy - 5, track_x1, cy + 5,
                                fill=C.BORDER, outline=C.BORDER)
            count = row.get("count") or 0
            pct = float(count) / float(max_count)
            if pct > 0:
                fill = C.PRIMARY
                cv.create_rectangle(track_x0, cy - 5,
                                    track_x0 + (track_x1 - track_x0) * pct,
                                    cy + 5, fill=fill, outline=fill)
            cv.create_text(track_x1 + val_w - 10, cy, text=str(count),
                           anchor="e", fill=C.INK,
                           font=("Segoe UI", 9, "bold"))
            band = "FOUND" if count else "MISSING"
            bcol = C.GOOD if count else C.LINE
            bx = track_x1 + val_w
            cv.create_rectangle(bx, cy - 8, bx + band_w - 10, cy + 8,
                                fill=bcol, outline=bcol)
            cv.create_text(bx + (band_w - 10) / 2, cy, text=band,
                           fill="#ffffff", font=("Segoe UI", 7, "bold"))

    # ----------------------------------------------------------------- pulse
    def _start_pulse(self):
        self._pulsing = True
        self._pulse_x = 0
        self._pulse()

    def _stop_pulse(self):
        self._pulsing = False
        self.progress.delete("all")

    def _pulse(self):
        if not self._pulsing:
            return
        cv = self.progress
        cv.delete("all")
        w = cv.winfo_width() or 800
        bar_w = max(80, w // 5)
        self._pulse_x = (self._pulse_x + 14) % (w + bar_w)
        x0 = self._pulse_x - bar_w
        cv.create_rectangle(x0, 0, x0 + bar_w, 4,
                            fill=C.PRIMARY, outline=C.PRIMARY)
        self.root.after(28, self._pulse)

    def _flash(self, widget):
        """Briefly tint a field to point at what needs attention."""
        try:
            original = widget.cget("bg")
            widget.configure(bg="#fdecec")
            self.root.after(700, lambda: widget.configure(bg=original))
        except Exception:
            pass

    # ------------------------------------------------------------------ open
    def _open_report(self):
        path = self.outputs.get("html")
        if not path or not os.path.isfile(path):
            self._log("No HTML report available yet — run a scan first.",
                      "warn")
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)                       # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                webbrowser.open("file://" + os.path.abspath(path))
            self._log("Opened %s" % os.path.basename(path), "dim")
        except Exception as exc:
            self._log("Could not open the report (%s).\nIt is here:\n    %s"
                      % (exc, path), "warn")

    def _open_folder(self):
        path = (self.outputs.get("html") or self.outputs.get("json"))
        folder = os.path.dirname(path) if path else self.row_out.get()
        if not folder or not os.path.isdir(folder):
            self._log("No report folder yet — run a scan first.", "warn")
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(folder)                     # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception as exc:
            self._log("Could not open the folder (%s):\n    %s"
                      % (exc, folder), "warn")


# ===========================================================================

def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not _HAVE_TKINTER:
        print(
            "CCM Data Scanner GUI cannot start: tkinter is not available in "
            "this Python (%s).\n"
            "tkinter ships with every standard CPython install and with "
            "ArcGIS Pro's arcgispro-py3 conda environment; if this is a "
            "custom/minimal Python build, install the OS Tcl/Tk package "
            "(e.g. 'python3-tk' on Debian/Ubuntu) and reinstall/rebuild "
            "Python against it." % _TKINTER_IMPORT_ERROR,
            file=sys.stderr,
        )
        return 1
    root = tk.Tk()
    try:
        # Crisper text on high-DPI Windows displays.
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    try:
        default = tkfont.nametofont("TkDefaultFont")
        default.configure(family="Segoe UI", size=9)
    except Exception:
        pass

    app = ScannerApp(root)

    # Accept a data folder as the first command-line argument, so the app can
    # be used as a drop target or launched from a shortcut with a preset path.
    if argv and os.path.isdir(argv[0]):
        app.row_data.set(os.path.normpath(argv[0]))
        parent = os.path.dirname(os.path.normpath(argv[0]))
        app.row_out.set(parent or argv[0])

    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

# <<< END OF FILE >>>
