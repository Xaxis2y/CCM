======================================================================
 MCE Cross Country Mobility Tool (CCM) V2
======================================================================

1. Overview
The MCE CCM V2 toolbox (.pyt) is a custom Python-based geoprocessing 
suite for ArcGIS Pro, designed to analyze and evaluate off-road 
vehicle mobility (Cross Country Mobility) based on terrain, soil, 
and vegetation data.

2. System Requirements
- Software: ArcGIS Pro 3.x
- Environment: Python 3.11 (Default ArcGIS Pro environment)
- Dependencies: This toolbox must be located in the same folder as 
  its supporting scripts (e.g., ccm_step1_setup.py, ccm_isochrone.py, 
  ccm_coords.py, etc.) to function correctly.

3. Installation & Usage
1) Launch ArcGIS Pro.
2) In the [Catalog] pane, right-click [Toolboxes] and select [Add Toolbox].
3) Navigate to and select "MCE_CCM_V2.pyt".
4) Expand the toolbox to access the 3-step workflow and specialized tools.

4. Core 3-Step Workflow
For new analyses, follow these steps in order:
- Step 1 Setup    : Pre-processing and terrain data preparation.
- Step 2 Mobility : Core mobility modeling and surface generation.
- Step 3 Advanced : Isochrone (time-distance) and high-level analysis.

5. Included Tools
- Reason Map Tool      : Identifies and maps the specific causes of 
                         slowdowns (Slope, Veg, etc.).
- Isochrone Tool       : Generates reachable areas based on time intervals.
- Vehicle Compare Tool : Compares mobility between two different 
                         vehicle types (Vehicle A vs B).
- Obstacle Detect Tool : Automates detection and integration of obstacles.
- Waypoints Tool       : Analyzes optimal paths and mobility between 
                         user-defined points.

6. Version Info
- Current Version: v2.40
- Key Updates: Multi-format coordinate support (MGRS, DD, DMS, DDM, UTM), 
  improved isochrone interval logic, and enhanced obstacle detection.