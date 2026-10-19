# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['C:/Users/Son/Documents/CCM_Tool/CCM_Tool_v0.60.10/CCM_Data_Scanner_GUI.py'],
    pathex=[],
    binaries=[],
    datas=[('C:/Users/Son/Documents/CCM_Tool/CCM_Tool_v0.60.10/ccm.ico', '.'), ('C:/Users/Son/Documents/CCM_Tool/CCM_Tool_v0.60.10/ccm_data_catalog.py', '.'), ('C:/Users/Son/Documents/CCM_Tool/CCM_Tool_v0.60.10/ccm_data_sources.py', '.'), ('C:/Users/Son/Documents/CCM_Tool/CCM_Tool_v0.60.10/ccm_data_report.py', '.'), ('C:/Users/Son/Documents/CCM_Tool/CCM_Tool_v0.60.10/ccm_step0b_integration.py', '.'), ('C:/Users/Son/Documents/CCM_Tool/CCM_Tool_v0.60.10/ccm_data_quality.py', '.'), ('C:/Users/Son/Documents/CCM_Tool/CCM_Tool_v0.60.10/ccm_data_fitness.py', '.'), ('C:/Users/Son/Documents/CCM_Tool/CCM_Tool_v0.60.10/ccm_data_confidence.py', '.'), ('C:/Users/Son/Documents/CCM_Tool/CCM_Tool_v0.60.10/ccm_data_readiness.py', '.'), ('C:/Users/Son/Documents/CCM_Tool/CCM_Tool_v0.60.10/ccm_data_selector.py', '.')],
    hiddenimports=['ccm_data_catalog', 'ccm_data_sources', 'ccm_data_report', 'ccm_step0b_integration', 'ccm_data_quality', 'ccm_data_fitness', 'ccm_data_confidence', 'ccm_data_readiness', 'ccm_data_selector'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['numpy', 'scipy', 'pandas', 'matplotlib', 'PIL', 'IPython', 'jupyter', 'notebook', 'pytest', 'setuptools', 'pip', 'sqlalchemy', 'cryptography', 'arcpy', 'arcgis', 'osgeo', 'gdal', 'PyQt5', 'PySide2', 'PySide6', 'tornado', 'zmq', 'sklearn', 'numba', 'llvmlite', 'h5py', 'networkx'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='CCM_Data_Scanner',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['C:/Users/Son/Documents/CCM_Tool/CCM_Tool_v0.60.10/ccm.ico'],
)
