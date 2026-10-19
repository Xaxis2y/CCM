# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
VERSION = "0.60.8"
"""
ccm_project_init.py -- CCM Tool v0.60.8 standalone Project Initializer
========================================================================
Single-root architecture: pick ONE folder for a whole CCM project, and this
tool creates the folder layout every step (Step 0, 0b, 1, 2, 3) expects,
plus the initial ccm_project.json every step reads through
ccm_project_config.load_config().

Layout created under the chosen root:

    <root>/
        ccm_project.json    -- via ccm_project_config.save_config()
        01_Input_Data/       -- put your source GIS data here
        02_Scan_Index/       -- Data Intelligence Scan (Step 0b) output
        03_Project.gdb       -- the project geodatabase (created here if
                                arcpy is available; otherwise Step 0 or
                                Step 1 inside ArcGIS Pro creates it the
                                first time either one runs)

Run as a script (needs only the Python standard library -- tkinter ships
with stock CPython, no arcpy needed):

    python ccm_project_init.py

Or freeze it into a standalone .exe with build_project_init_exe.py -- see
that script's docstring. The frozen exe needs no Python installed on the
target machine and does not need or bundle arcpy.
"""

import os
import sys

# ccm_project_config.py lives alongside this script in the CCM_Tool folder.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:
    import ccm_project_config as _cfg_mod
except Exception:
    _cfg_mod = None

SUBFOLDERS = ("01_Input_Data", "02_Scan_Index")
GDB_NAME = "03_Project.gdb"


def initialize_project(root_path, log=print):
    """
    Create the single-root project layout under root_path and write the
    initial ccm_project.json. Pure logic, no Tkinter -- callable headlessly
    (see test_single_root_pure_python.py) and from the GUI below.

    Returns a dict: {"root", "data_root", "scan_index_dir", "project_gdb",
    "config_path", "gdb_created", "warnings"}.

    Raises OSError if the subfolders can't be created (e.g. permissions);
    everything else (GDB creation, config write) degrades to a warning
    rather than an exception, since a partially-set-up project the analyst
    can still see and fix is better than a bare traceback.
    """
    warnings = []
    root_path = os.path.abspath(root_path)
    os.makedirs(root_path, exist_ok=True)

    data_root = os.path.join(root_path, "01_Input_Data")
    scan_index_dir = os.path.join(root_path, "02_Scan_Index")
    for d in (data_root, scan_index_dir):
        os.makedirs(d, exist_ok=True)

    project_gdb = os.path.join(root_path, GDB_NAME)
    gdb_created = os.path.isdir(project_gdb)
    if not gdb_created:
        try:
            import arcpy  # optional -- most machines running this GUI/exe
                          # will NOT have arcpy, and that's fine.
            arcpy.management.CreateFileGDB(root_path, GDB_NAME)
            gdb_created = True
        except ImportError:
            warnings.append(
                "arcpy is not available here, so %s was not created yet -- "
                "Step 0 or Step 1 inside ArcGIS Pro will create it "
                "automatically the first time either one runs against this "
                "project root." % GDB_NAME)
        except Exception as exc:
            warnings.append("Could not create %s: %s" % (GDB_NAME, exc))

    config_path = None
    if _cfg_mod is not None:
        try:
            config_path = _cfg_mod.save_config(
                root_path,
                project_root=root_path,
                data_root=data_root,
                scan_index_dir=scan_index_dir,
                project_gdb=project_gdb,
            )
        except Exception as exc:
            warnings.append("Could not write ccm_project.json: %s" % exc)
    else:
        warnings.append(
            "ccm_project_config.py could not be imported -- ccm_project.json "
            "was not written. Make sure this script sits in the same "
            "folder as the rest of the CCM Tool.")

    for msg in warnings:
        log("[WARN] %s" % msg)
    log("Project root ready: %s" % root_path)
    log("  Data root:      %s" % data_root)
    log("  Scan index dir: %s" % scan_index_dir)
    log("  Project GDB:    %s (%s)" % (
        project_gdb, "created" if gdb_created else "not yet created"))
    if config_path:
        log("  Config written: %s" % config_path)

    return {
        "root": root_path,
        "data_root": data_root,
        "scan_index_dir": scan_index_dir,
        "project_gdb": project_gdb,
        "config_path": config_path,
        "gdb_created": gdb_created,
        "warnings": warnings,
    }


# ===========================================================================
# Tkinter GUI
# ===========================================================================

def run_gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext

    root_win = tk.Tk()
    root_win.title("CCM Project Initializer")
    root_win.geometry("640x420")
    root_win.minsize(520, 340)

    header = tk.Label(
        root_win,
        text="CCM Tool -- New Project",
        font=("Segoe UI", 14, "bold"),
        pady=8,
    )
    header.pack(fill="x")

    subtext = tk.Label(
        root_win,
        text=("Pick ONE folder for the whole project. This creates "
              "01_Input_Data, 02_Scan_Index and 03_Project.gdb inside it, "
              "plus the ccm_project.json every CCM step reads."),
        wraplength=600,
        justify="left",
        fg="#444444",
    )
    subtext.pack(fill="x", padx=16)

    path_var = tk.StringVar(value="(no folder selected)")
    path_label = tk.Label(root_win, textvariable=path_var, fg="#0a5c36",
                          font=("Segoe UI", 9, "bold"))
    path_label.pack(fill="x", padx=16, pady=(8, 0))

    log_box = scrolledtext.ScrolledText(root_win, height=14, state="disabled",
                                        font=("Consolas", 9))
    log_box.pack(fill="both", expand=True, padx=16, pady=8)

    def _log(msg):
        log_box.configure(state="normal")
        log_box.insert("end", str(msg) + "\n")
        log_box.see("end")
        log_box.configure(state="disabled")
        root_win.update_idletasks()

    def _pick_and_init():
        chosen = filedialog.askdirectory(
            title="Select Project Root Folder for CCM Project")
        if not chosen:
            return
        path_var.set(chosen)
        log_box.configure(state="normal")
        log_box.delete("1.0", "end")
        log_box.configure(state="disabled")
        try:
            result = initialize_project(chosen, log=_log)
            if result["warnings"]:
                messagebox.showwarning(
                    "Project created with warnings",
                    "Project root is set up, but see the log for %d "
                    "warning(s)." % len(result["warnings"]))
            else:
                messagebox.showinfo(
                    "Project ready",
                    "Project root is set up:\n%s" % chosen)
        except Exception as exc:
            _log("[ERROR] %s" % exc)
            messagebox.showerror("Setup failed", str(exc))

    btn = tk.Button(
        root_win,
        text="Select Project Root Folder...",
        command=_pick_and_init,
        font=("Segoe UI", 10),
        padx=12,
        pady=6,
    )
    btn.pack(pady=(0, 16))

    root_win.mainloop()


if __name__ == "__main__":
    run_gui()
# <<< END OF FILE >>>
