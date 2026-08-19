# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
r"""
ccm_data_sources.py -- what each GIS data product actually IS
==============================================================
Updated for the factual v0.57 release.

A pure-Python reference catalog, in the same spirit as ``ccm_mgcp_catalog.py``
(which explains FACC codes).  This one explains DATA PRODUCTS.

The problem it solves
---------------------
A scan can report "SoilGrids, 250 m" perfectly correctly and still leave the
analyst none the wiser.  What IS SoilGrids?  Is 250 m good?  What does CCM do
with it?  How does it differ from SSURGO?  Answering that inside the report
turns an inventory into something an analyst can act on without already being
a specialist in every data product they happen to have on disk.

For every (CCM role, source product) this module supplies:

    full_name   the product's real name, spelled out
    what        one sentence: what the dataset is and who makes it
    contains    what is actually inside it (the measured quantity)
    resolution  the resolution the product is normally published at
    ccm_use     which CCM factor consumes it, and how
    watch       the honest caveat -- what this product gets wrong

Nothing here is measured; it is documentation of published products, and is
used to explain a dataset, never to score, rank, select, or substitute it.
Where a stated resolution varies by product version or region, the text says
so rather than inventing a single number.

Pure Python: no arcpy, no GDAL, no network.
"""

VERSION = "0.57"

# Roles (mirrored so this module also stands alone)
ROLE_DEM = "dem"
ROLE_SOIL = "soil"
ROLE_VEG = "veg"
ROLE_HYDRO = "hydro"
ROLE_CONTOURS = "contours"
ROLE_MOISTURE = "moisture"
ROLE_VEHICLE = "vehicle"
ROLE_EXTENT = "extent"
ROLE_MGCP = "mgcp"


# ===========================================================================
# Resolution classes -- how fine is fine, per role
# ===========================================================================
# (upper bound in metres, label, one-line meaning for a CCM analyst)
RESOLUTION_CLASSES = {
    ROLE_DEM: [
        (2, "VERY FINE", "Resolves individual ditches, banks and tracks."),
        (10, "FINE", "Resolves micro-relief that stops or slows a vehicle."),
        (30, "MODERATE", "Good regional slope; misses small obstacles."),
        (100, "COARSE", "Broad terrain shape only; local slope is smoothed."),
        (float("inf"), "VERY COARSE",
         "Too smooth for vehicle-scale slope; expect optimistic GO area."),
    ],
    ROLE_VEG: [
        (10, "FINE", "Individual stands and clearings are separable."),
        (30, "MODERATE", "Stand-level cover; small clearings are lost."),
        (100, "COARSE", "Regional cover classes only."),
        (float("inf"), "VERY COARSE", "Landscape averages; not stand-level."),
    ],
    ROLE_SOIL: [
        (30, "FINE", "Field-scale soil bodies are separable."),
        (100, "MODERATE", "Local soil variation is partly resolved."),
        (250, "COARSE", "Mapping units span several terrain features."),
        (float("inf"), "VERY COARSE",
         "One value covers a wide area; local soft ground is invisible."),
    ],
    ROLE_MOISTURE: [
        (1000, "FINE", "Sub-kilometre wetness variation."),
        (10000, "MODERATE", "Regional wetness pattern."),
        (float("inf"), "COARSE", "Synoptic scale; not local wetness."),
    ],
}

DEFAULT_RESOLUTION_CLASSES = [
    (10, "FINE", "High detail."),
    (30, "MODERATE", "Moderate detail."),
    (100, "COARSE", "Low detail."),
    (float("inf"), "VERY COARSE", "Very low detail."),
]


def resolution_class(role, cell_size_m):
    """
    Classify a raster cell size for a CCM role.

    Returns {"label", "meaning", "cell_size_m"} or None when no cell size was
    measured.  The bands differ per role on purpose: 250 m is unusable for
    slope but entirely normal for a global soil product.
    """
    if not cell_size_m:
        return None
    try:
        cs = float(cell_size_m)
    except Exception:
        return None
    bands = RESOLUTION_CLASSES.get(role, DEFAULT_RESOLUTION_CLASSES)
    for limit, label, meaning in bands:
        if cs <= limit:
            return {"cell_size_m": cs, "label": label, "meaning": meaning}
    return {"cell_size_m": cs, "label": bands[-1][1], "meaning": bands[-1][2]}


def format_resolution(cell_size_m):
    """Human-friendly cell size: '10 m', '0.5 m', '250 m', '1.2 km'."""
    if not cell_size_m:
        return None
    try:
        cs = float(cell_size_m)
    except Exception:
        return None
    if cs >= 1000:
        return "%.3g km" % (cs / 1000.0)
    if cs >= 1:
        return "%.4g m" % cs
    return "%.2f m" % cs


# ===========================================================================
# Product descriptions
# ===========================================================================
# key: (role, source_type)
SOURCE_INFO = {

    # ---- DEM / elevation --------------------------------------------------
    (ROLE_DEM, "HRDEM"): {
        "full_name": "HRDEM — High Resolution Digital Elevation Model",
        "what": "Canada's lidar-derived elevation product (NRCan), published "
                "for selected, mostly populated or surveyed areas.",
        "contains": "Bare-earth ground elevation in metres.",
        "resolution": "typically 1–2 m where available",
        "ccm_use": "Slope (F1). The best available input — micro-relief that "
                   "actually stops a vehicle is resolved.",
        "watch": "Coverage is partial. Confirm it spans your whole AOI before "
                 "relying on it.",
    },
    (ROLE_DEM, "LiDAR"): {
        "full_name": "LiDAR-derived elevation",
        "what": "Airborne laser scanning, processed to a ground surface.",
        "contains": "Bare-earth ground elevation in metres.",
        "resolution": "commonly 0.5–2 m",
        "ccm_use": "Slope (F1). The highest-fidelity slope source CCM can use.",
        "watch": "Check whether the product is bare-earth (DTM) or first-return "
                 "(DSM) — a DSM includes canopy and buildings and inflates slope.",
    },
    (ROLE_DEM, "CDEM"): {
        "full_name": "CDEM — Canadian Digital Elevation Model",
        "what": "National elevation coverage for Canada (NRCan), derived from "
                "topographic source data.",
        "contains": "Ground elevation in metres.",
        "resolution": "varies with latitude; roughly 20 m ground spacing",
        "ccm_use": "Slope (F1). Solid national-scale slope.",
        "watch": "Derived from contour-era sources, so fine detail is smoothed "
                 "relative to lidar.",
    },
    (ROLE_DEM, "SRTM"): {
        "full_name": "SRTM — Shuttle Radar Topography Mission",
        "what": "NASA's global elevation dataset from the 2000 Shuttle radar "
                "mission. The most widely available global DEM.",
        "contains": "Surface elevation in metres.",
        "resolution": "30 m (1 arc-second); 90 m in some older releases",
        "ccm_use": "Slope (F1). A dependable global fallback.",
        "watch": "Radar returns come from the canopy top in dense forest, so "
                 "slope can be overstated there. Coverage stops near the poles.",
    },
    (ROLE_DEM, "ASTER"): {
        "full_name": "ASTER GDEM — Global Digital Elevation Model",
        "what": "Global elevation built from stereo optical satellite imagery "
                "(NASA/METI).",
        "contains": "Surface elevation in metres.",
        "resolution": "30 m (1 arc-second)",
        "ccm_use": "Slope (F1). Use when SRTM is unavailable for the area.",
        "watch": "Noisier than SRTM, with known artefacts over cloud-prone and "
                 "low-contrast terrain.",
    },
    (ROLE_DEM, "COP-DEM"): {
        "full_name": "Copernicus DEM",
        "what": "ESA's global elevation model, derived from the TanDEM-X radar "
                "mission.",
        "contains": "Surface elevation in metres.",
        "resolution": "30 m (GLO-30); 90 m (GLO-90)",
        "ccm_use": "Slope (F1). Generally cleaner than SRTM or ASTER.",
        "watch": "A surface model — canopy and buildings are included.",
    },
    (ROLE_DEM, "ALOS"): {
        "full_name": "ALOS World 3D (AW3D30)",
        "what": "JAXA's global elevation model from PRISM stereo imagery.",
        "contains": "Surface elevation in metres.",
        "resolution": "30 m",
        "ccm_use": "Slope (F1). A capable global alternative.",
        "watch": "A surface model, like most global DEMs.",
    },
    (ROLE_DEM, "DTM"): {
        "full_name": "DTM — Digital Terrain Model",
        "what": "A bare-earth elevation surface: vegetation and structures "
                "have been removed.",
        "contains": "Ground elevation in metres.",
        "resolution": "depends on the source",
        "ccm_use": "Slope (F1). The correct kind of elevation model for "
                   "mobility work.",
        "watch": "Verify the vertical datum and units if slope looks wrong.",
    },
    (ROLE_DEM, "DSM"): {
        "full_name": "DSM — Digital Surface Model",
        "what": "An elevation surface that INCLUDES canopy, buildings and "
                "other structures.",
        "contains": "Surface (top-of-feature) elevation in metres.",
        "resolution": "depends on the source",
        "ccm_use": "Slope (F1) — usable, but not ideal.",
        "watch": "Forest edges and buildings appear as cliffs, so derived "
                 "slope is overstated. Prefer a DTM when one exists.",
    },
    (ROLE_DEM, "DEM"): {
        "full_name": "Digital Elevation Model",
        "what": "A gridded elevation surface; the specific product could not "
                "be identified from the file name.",
        "contains": "Elevation in metres (assumed).",
        "resolution": "as measured from the file",
        "ccm_use": "Slope (F1) — ArcGIS Slope is run on this raster.",
        "watch": "Confirm whether it is bare-earth or a surface model, and "
                 "that the vertical unit is metres.",
    },

    # ---- Soil -------------------------------------------------------------
    (ROLE_SOIL, "SSURGO"): {
        "full_name": "SSURGO / gSSURGO — Soil Survey Geographic Database",
        "what": "The USDA-NRCS detailed soil survey of the United States — "
                "field-mapped, with laboratory-characterised horizons.",
        "contains": "Map units linked to component and horizon tables: "
                    "texture, particle-size fractions, depth, drainage.",
        "resolution": "mapped at roughly 1:12,000–1:24,000",
        "ccm_use": "Soil strength (F4 dry / F5 wet). Texture maps directly to "
                   "a USCS class, then to cone index / RCI.",
        "watch": "United States only. Needs the tabular data, not just the "
                 "polygons — the attributes live in the linked tables.",
    },
    (ROLE_SOIL, "SLC"): {
        "full_name": "SLC / DSS — Soil Landscapes of Canada",
        "what": "Canada's national soil polygon coverage with component (CMP) "
                "and layer (LYR) attribute tables, from AAFC.",
        "contains": "Soil polygons plus per-component, per-layer texture and "
                    "profile attributes.",
        "resolution": "national mapping, around 1:1,000,000",
        "ccm_use": "Soil strength (F4 / F5). Layer texture yields USCS class.",
        "watch": "Coarse polygons: one unit can span very different ground. "
                 "The .dbf component and layer tables must be supplied too.",
    },
    (ROLE_SOIL, "MGCP"): {
        "full_name": "MGCP DA010 — Ground Surface Element",
        "what": "The soil / surface-material layer of an MGCP military "
                "topographic delivery.",
        "contains": "The SMC attribute — Surface Material Category — a coded "
                    "description of the ground surface.",
        "resolution": "vector polygons, MGCP TRD specification",
        "ccm_use": "Soil strength (F4 / F5). SMC maps directly to USCS.",
        "watch": "Useless without the SMC field populated. Run Step 0 first "
                 "so the MGCP cells are merged and catalogued.",
    },
    (ROLE_SOIL, "SoilGrids"): {
        "full_name": "SoilGrids 2.0 (ISRIC)",
        "what": "Global machine-learned predictions of soil properties, "
                "produced by ISRIC from a worldwide profile database.",
        "contains": "Separate rasters per property and depth — sand, silt, "
                    "clay, bulk density, coarse fragments, organic carbon, pH.",
        "resolution": "250 m",
        "ccm_use": "Soil strength (F4 / F5). CCM combines the sand/silt/clay "
                   "fractions to DERIVE a USCS class.",
        "watch": "Predicted, not surveyed, and the USCS class is one inference "
                 "step removed from the data. 250 m cells average across "
                 "local soft ground.",
    },
    (ROLE_SOIL, "HWSD"): {
        "full_name": "HWSD v2 — Harmonized World Soil Database",
        "what": "A global soil database (FAO/IIASA) pairing a raster of "
                "mapping units with an attribute database.",
        "contains": "Mapping-unit raster plus texture and profile attributes "
                    "in an Access database.",
        "resolution": "approximately 1 km",
        "ccm_use": "Soil strength (F4 / F5) — a global last resort.",
        "watch": "Very coarse. One mapping unit can cover an entire manoeuvre "
                 "area, so soft-ground detail is simply absent.",
    },
    (ROLE_SOIL, "Generic"): {
        "full_name": "Soil polygons (product not identified)",
        "what": "A soil map whose source product could not be recognised from "
                "the file name.",
        "contains": "Unknown until the attribute table is inspected.",
        "resolution": "unknown",
        "ccm_use": "Soil strength (F4 / F5), if it carries a texture or USCS "
                   "attribute.",
        "watch": "Open the attribute table and confirm a usable texture field "
                 "exists before trusting soil results.",
    },
    (ROLE_SOIL, "LandCover"): {
        "full_name": "Land cover used as a soil proxy",
        "what": "A land-cover raster being pressed into service as a soil "
                "source.",
        "contains": "Surface cover classes — not soil physics.",
        "resolution": "as measured",
        "ccm_use": "Soil strength (F4 / F5) — only as a crude approximation.",
        "watch": "Carries no bearing-capacity information whatsoever. USCS can "
                 "only be guessed from the cover class. Treat soil results as "
                 "unverified.",
    },

    # ---- Vegetation -------------------------------------------------------
    (ROLE_VEG, "WorldCover"): {
        "full_name": "ESA WorldCover",
        "what": "ESA's global land-cover map from Sentinel-1 and Sentinel-2 "
                "imagery.",
        "contains": "Land-cover classes (tree cover, shrubland, grassland, "
                    "cropland, built-up, water, wetland, bare, and others).",
        "resolution": "10 m",
        "ccm_use": "Vegetation density (F2) and stem spacing (F3), via "
                   "class-based estimates.",
        "watch": "Class only. Tree spacing and stem diameter are ESTIMATED "
                 "from the class, not measured, so wooded-terrain speed is "
                 "less certain than the fine pixel size suggests.",
    },
    (ROLE_VEG, "NLCD"): {
        "full_name": "NLCD — National Land Cover Database",
        "what": "The USGS land-cover product for the United States.",
        "contains": "Land-cover classes plus, in some releases, percent tree "
                    "canopy and impervious surface.",
        "resolution": "30 m",
        "ccm_use": "Vegetation density (F2) and spacing (F3), class-based.",
        "watch": "United States only; class-based spacing estimates.",
    },
    (ROLE_VEG, "CORINE"): {
        "full_name": "CORINE Land Cover",
        "what": "The European land-cover inventory (EEA).",
        "contains": "Hierarchical land-cover classes.",
        "resolution": "typically 100 m raster; large minimum mapping unit",
        "ccm_use": "Vegetation density (F2) and spacing (F3), class-based.",
        "watch": "The large minimum mapping unit removes small clearings and "
                 "narrow tree belts that matter for movement.",
    },
    (ROLE_VEG, "GEDI"): {
        "full_name": "GEDI — Global Ecosystem Dynamics Investigation",
        "what": "NASA spaceborne lidar on the ISS, measuring forest structure "
                "directly.",
        "contains": "Canopy height and biomass metrics.",
        "resolution": "footprint-based; gridded products vary by release",
        "ccm_use": "Vegetation spacing (F3) — height drives the spacing and "
                   "stem-diameter estimate.",
        "watch": "Real structure measurement rather than a class guess, but "
                 "sampling is not wall-to-wall; check coverage over the AOI.",
    },
    (ROLE_VEG, "GLAD"): {
        "full_name": "GLAD canopy height",
        "what": "Global canopy-height mapping from the University of Maryland "
                "GLAD laboratory, calibrated against lidar.",
        "contains": "Canopy height in metres.",
        "resolution": "commonly 30 m",
        "ccm_use": "Vegetation spacing (F3) and height normalisation.",
        "watch": "Modelled height; accuracy varies by forest type.",
    },
    (ROLE_VEG, "CanopyHeight"): {
        "full_name": "Canopy height raster",
        "what": "A gridded forest-height product.",
        "contains": "Canopy height in metres.",
        "resolution": "as measured",
        "ccm_use": "Vegetation spacing (F3).",
        "watch": "Confirm the units are metres and that the product is height "
                 "rather than biomass.",
    },
    (ROLE_VEG, "CanadaBio"): {
        "full_name": "Canada biophysical products (LAI / fCOVER)",
        "what": "Canadian satellite-derived biophysical variables describing "
                "how much leaf area and ground cover vegetation presents.",
        "contains": "Leaf Area Index and fractional cover; often paired with a "
                    "canopy-height raster.",
        "resolution": "product-dependent",
        "ccm_use": "The strongest vegetation input CCM accepts: LAI and fCOVER "
                   "support BOTH density (F2) and spacing (F3).",
        "watch": "Supply the LAI, fCOVER and height rasters together — the "
                 "combination is what makes this input strong.",
    },
    (ROLE_VEG, "DMTI"): {
        "full_name": "DMTI Spatial land cover",
        "what": "A commercial Canadian land-cover product.",
        "contains": "Land-cover classes.",
        "resolution": "product-dependent",
        "ccm_use": "Vegetation density (F2) and spacing (F3), class-based.",
        "watch": "Licensed data; class-based spacing estimates.",
    },
    (ROLE_VEG, "MGCP"): {
        "full_name": "MGCP vegetation features",
        "what": "Vegetation polygons from an MGCP delivery (forest, scrub, "
                "orchard, cropland and similar).",
        "contains": "Vegetation feature classes coded by FACC.",
        "resolution": "vector, MGCP TRD specification",
        "ccm_use": "Vegetation density (F2) and spacing (F3).",
        "watch": "Broad polygon classes; no measured canopy structure.",
    },
    (ROLE_VEG, "LandCover"): {
        "full_name": "Land cover (product not identified)",
        "what": "A land-cover raster whose specific product could not be "
                "recognised.",
        "contains": "Cover classes, coding scheme unknown.",
        "resolution": "as measured",
        "ccm_use": "Vegetation density (F2) and spacing (F3).",
        "watch": "The class coding must be mapped to CCM vegetation classes "
                 "before the numbers mean anything.",
    },

    # ---- Hydrology --------------------------------------------------------
    (ROLE_HYDRO, "MGCP"): {
        "full_name": "MGCP hydrography (BH140 rivers, BH080 lakes, …)",
        "what": "Water features from an MGCP military topographic delivery.",
        "contains": "Rivers, streams, lakes, ponds, canals and inundated land.",
        "resolution": "vector, MGCP TRD specification",
        "ccm_use": "Hydrology (F_hydro). Water bodies become NO-GO areas.",
        "watch": "Run Step 0 first so the features are merged across cells.",
    },
    (ROLE_HYDRO, "NHN"): {
        "full_name": "NHN — National Hydro Network (Canada)",
        "what": "Canada's authoritative surface-water network.",
        "contains": "Watercourses, waterbodies and flow direction.",
        "resolution": "vector, 1:10,000–1:50,000 source scales",
        "ccm_use": "Hydrology (F_hydro).",
        "watch": "Seasonal channels may be shown as permanent.",
    },
    (ROLE_HYDRO, "NHD"): {
        "full_name": "NHD — National Hydrography Dataset (US)",
        "what": "The USGS surface-water network for the United States.",
        "contains": "Flowlines, waterbodies and drainage areas.",
        "resolution": "vector; high-resolution and medium-resolution versions",
        "ccm_use": "Hydrology (F_hydro).",
        "watch": "Check whether you have the high-resolution version; the "
                 "medium one omits small channels.",
    },
    (ROLE_HYDRO, "Generic"): {
        "full_name": "Water features (product not identified)",
        "what": "River / lake / water polygons of unrecognised origin.",
        "contains": "Water features.",
        "resolution": "vector",
        "ccm_use": "Hydrology (F_hydro) — water becomes NO-GO.",
        "watch": "Polygons are used as barriers. Line-only rivers with no "
                 "width will not block movement correctly.",
    },

    # ---- Contours ---------------------------------------------------------
    (ROLE_CONTOURS, "MGCP"): {
        "full_name": "MGCP CA010 — Elevation Contours",
        "what": "Contour lines from an MGCP delivery.",
        "contains": "Elevation contour lines with a height attribute.",
        "resolution": "vector; interval per the MGCP specification",
        "ccm_use": "Supports vegetation height normalisation; a fallback "
                   "elevation source when no DEM exists.",
        "watch": "A surface interpolated from contours is much coarser than a "
                 "real DEM.",
    },
    (ROLE_CONTOURS, "Generic"): {
        "full_name": "Contour lines",
        "what": "Elevation contour lines.",
        "contains": "Lines with an elevation attribute.",
        "resolution": "depends on the contour interval",
        "ccm_use": "Vegetation height normalisation; fallback elevation.",
        "watch": "The contour interval decides how useful this is — 100 m "
                 "contours cannot produce vehicle-scale slope.",
    },

    # ---- Soil moisture ----------------------------------------------------
    (ROLE_MOISTURE, "SMAP"): {
        "full_name": "SMAP L4 — Soil Moisture Active Passive",
        "what": "NASA's soil-moisture mission product, assimilated into a "
                "land-surface model.",
        "contains": "Surface and root-zone volumetric water content, with a "
                    "freeze/thaw state.",
        "resolution": "9 km, 3-hourly",
        "ccm_use": "Adjusts soil RCI between the dry / moist / wet cases — the "
                   "NG-NRMM reference source.",
        "watch": "Requires NASA Earthdata credentials. Not yet wired into CCM "
                 "(planned; Open-Meteo is used today).",
    },
    (ROLE_MOISTURE, "ERA5"): {
        "full_name": "ERA5 reanalysis soil moisture",
        "what": "ECMWF's global atmospheric and land reanalysis.",
        "contains": "Volumetric soil water content by depth layer.",
        "resolution": "roughly 9–31 km depending on the product",
        "ccm_use": "Spatial soil-moisture adjustment to RCI in Step 2.",
        "watch": "Coarse cells give a regional wetness trend, not local "
                 "wetness. A single cell can span a whole AOI.",
    },
    (ROLE_MOISTURE, "Open-Meteo"): {
        "full_name": "Open-Meteo soil moisture",
        "what": "A free weather API that serves reanalysis and forecast soil "
                "moisture.",
        "contains": "Volumetric water content by depth, plus rainfall.",
        "resolution": "follows the underlying model, around 9–11 km",
        "ccm_use": "The live moisture source CCM Step 2 already uses.",
        "watch": "Needs an internet connection at Step 2 run time. This scan "
                 "never calls it.",
    },
    (ROLE_MOISTURE, "Generic"): {
        "full_name": "Soil moisture raster",
        "what": "A gridded soil-moisture product of unrecognised origin.",
        "contains": "Presumed volumetric water content.",
        "resolution": "as measured",
        "ccm_use": "Soil RCI adjustment.",
        "watch": "Confirm the units — volumetric fraction, percent and mm are "
                 "all in common use and are not interchangeable.",
    },

    # ---- Supporting -------------------------------------------------------
    (ROLE_VEHICLE, "Generic"): {
        "full_name": "CCM vehicle database (CSV)",
        "what": "The platform table CCM reads vehicle mobility parameters "
                "from.",
        "contains": "Per vehicle: VCI-1 and VCI-50 cone indices, maximum road "
                    "speed, gradient limit, width, and mean maximum pressure.",
        "resolution": "tabular",
        "ccm_use": "Defines every speed and trafficability limit in the model. "
                   "Nothing runs without it.",
        "watch": "Requires the columns name, vci_1, vci_50 and "
                 "max_road_spd_kph. The shipped Vehicles_Can.csv holds 64 "
                 "platforms.",
    },
    (ROLE_EXTENT, "Generic"): {
        "full_name": "Analysis extent (AOI)",
        "what": "The polygon defining the study area.",
        "contains": "One or more boundary polygons.",
        "resolution": "vector",
        "ccm_use": "Every CCM step is clipped to this polygon, and its CRS "
                   "becomes the project CRS.",
        "watch": "Must use a Projected CRS (UTM). A geographic AOI makes all "
                 "distance and area calculations wrong.",
    },
    (ROLE_MGCP, "MGCP"): {
        "full_name": "MGCP — Multinational Geospatial Co-production Program",
        "what": "A standardised military topographic dataset delivered as "
                "cells of FACC-coded feature classes.",
        "contains": "Dozens of feature classes: roads, hydrography, "
                    "vegetation, soil (DA010), contours, obstacles.",
        "resolution": "vector, MGCP TRD specification",
        "ccm_use": "A single delivery can supply soil, hydrology, vegetation "
                   "and contours at once. Step 0 imports and merges it.",
        "watch": "Feature-class names are opaque codes. Step 0 writes "
                 "mgcp_manifest.json so later steps know what is inside.",
    },
}

# Fallback text per role when the product could not be identified at all.
ROLE_FALLBACK = {
    ROLE_DEM: {
        "full_name": "Elevation raster",
        "what": "A gridded elevation surface.",
        "contains": "Elevation values.",
        "ccm_use": "Slope (F1).",
        "watch": "Product unidentified — confirm units and whether it is "
                 "bare-earth or a surface model.",
    },
    ROLE_SOIL: {
        "full_name": "Soil dataset",
        "what": "A soil map or soil property dataset.",
        "contains": "Soil attributes.",
        "ccm_use": "Soil strength (F4 / F5).",
        "watch": "Product unidentified — confirm a texture or USCS attribute "
                 "exists.",
    },
    ROLE_VEG: {
        "full_name": "Vegetation dataset",
        "what": "A vegetation or land-cover dataset.",
        "contains": "Vegetation classes or structure metrics.",
        "ccm_use": "Vegetation density (F2) and spacing (F3).",
        "watch": "Product unidentified — the class coding must be mapped to "
                 "CCM vegetation classes.",
    },
    ROLE_HYDRO: {
        "full_name": "Hydrography dataset",
        "what": "Surface-water features.",
        "contains": "Water features.",
        "ccm_use": "Hydrology (F_hydro).",
        "watch": "Polygons act as barriers; lines without width do not.",
    },
    ROLE_CONTOURS: {
        "full_name": "Contour dataset",
        "what": "Elevation contour lines.",
        "contains": "Contour lines with heights.",
        "ccm_use": "Vegetation height normalisation; fallback elevation.",
        "watch": "Usefulness depends on the contour interval.",
    },
    ROLE_MOISTURE: {
        "full_name": "Soil moisture dataset",
        "what": "A soil-moisture product.",
        "contains": "Moisture values.",
        "ccm_use": "Soil RCI adjustment.",
        "watch": "Confirm the units.",
    },
}


def describe(role, source_type):
    """
    Return the description dict for a (role, source_type) pair.

    Falls back to a role-level description when the specific product is not in
    the catalog, and to None when even the role is unknown.  The returned dict
    always carries the same keys, so callers never need to test for presence.
    """
    info = SOURCE_INFO.get((role, source_type))
    if info is None:
        info = ROLE_FALLBACK.get(role)
    if info is None:
        return None
    out = {
        "full_name": info.get("full_name", ""),
        "what": info.get("what", ""),
        "contains": info.get("contains", ""),
        "resolution": info.get("resolution", ""),
        "ccm_use": info.get("ccm_use", ""),
        "watch": info.get("watch", ""),
        "identified": (role, source_type) in SOURCE_INFO,
    }
    return out


def known_sources(role=None):
    """List the source products the catalog knows, optionally for one role."""
    if role is None:
        return sorted(SOURCE_INFO.keys())
    return sorted(s for (r, s) in SOURCE_INFO if r == role)

# <<< END OF FILE >>>
