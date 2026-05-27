"""
Bernalillo County Urban Opportunity Index (tract level)

Pipeline:
1. Download ACS data for broadband, housing burden, insurance, poverty, income, disability, education, SNAP, and unemployment.
2. Download TIGER tract shapefile for NM and filter to Bernalillo County.
3. (Optional) Read HRSA/FQHC sites CSV and compute distance to nearest clinic.
4. Clean Census missing-value sentinels, compute indicators, and normalize them.
5. Export GeoPackage + CSV for mapping.
"""

import os
import requests
import pandas as pd
import geopandas as gpd

# =========================
# CONFIG
# =========================

# ACS 5-year vintage (2018–2022 = 2022)
ACS_YEAR = 2022

# New Mexico / Bernalillo County FIPS
STATE_FIPS = "35"
COUNTY_FIPS = "001"

# Optional Census API key. Public ACS calls usually work without one, but setting
# CENSUS_API_KEY can help avoid throttling during repeated rebuilds.
CENSUS_API_KEY = os.getenv("CENSUS_API_KEY")

# Output directory
OUTPUT_DIR = "outputs"

# Optional: local CSV with HRSA/FQHC sites (lat/long in WGS84)
HRSA_CSV_PATH = "data/hrsa_health_centers_nm.csv"  # set to None to skip distance calc

# Tract-level nearest-hospital distances. Expected columns: GEOID, year, dist1, hosp_id1.
HOSPITAL_DISTANCE_CSV_PATH = os.getenv("HOSPITAL_DISTANCE_CSV_PATH", "data/hospital_distances.csv")

# CRS for geometry
GEOG_CRS = "EPSG:4326"
METRIC_CRS = "EPSG:26913"  # UTM zone 13N (good for NM distances in meters)

# TIGER tract shapefile URL for NM (state FIPS 35)
TIGER_TRACT_URL = f"https://www2.census.gov/geo/tiger/TIGER2022/TRACT/tl_2022_{STATE_FIPS}_tract.zip"


# =========================
# HELPERS
# =========================

def ensure_output_dir():
    os.makedirs(OUTPUT_DIR, exist_ok=True)


def clean_acs_numeric(series: pd.Series) -> pd.Series:
    """Convert Census estimates to numbers and drop ACS special missing codes."""
    numeric = pd.to_numeric(series, errors="coerce")
    return numeric.mask(numeric <= -100_000_000)


def safe_pct(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """Return numerator / denominator * 100, preserving NA for zero or missing denominators."""
    numerator = clean_acs_numeric(numerator)
    denominator = clean_acs_numeric(denominator)
    return numerator.div(denominator.where(denominator > 0)).mul(100.0)


def fetch_acs_json(year: int, dataset: str, variables, state_fips: str, county_fips: str) -> pd.DataFrame:
    """
    Generic helper for Census API.

    dataset:
        - "acs/acs5" for detailed B tables (e.g., B28002)
        - "acs/acs5/subject" for S tables (e.g., S2503, S2701, S1701)
    variables: list of variable names (e.g., ["B28002_001E", "B28002_004E"])
    """
    base_url = f"https://api.census.gov/data/{year}/{dataset}"
    get_vars = ["NAME"] + variables
    params = {
        "get": ",".join(get_vars),
        "for": "tract:*",
        "in": f"state:{state_fips} county:{county_fips}",
    }
    if CENSUS_API_KEY:
        params["key"] = CENSUS_API_KEY

    print(f"Requesting {dataset} variables: {variables}")
    r = requests.get(base_url, params=params, timeout=30)
    try:
        r.raise_for_status()
        data = r.json()
    except ValueError as exc:
        preview = r.text[:500].replace("\n", " ")
        raise RuntimeError(
            f"Census API returned non-JSON for {dataset} variables {variables}: {preview}"
        ) from exc

    cols = data[0]
    rows = data[1:]
    df = pd.DataFrame(rows, columns=cols)

    # Convert Census numeric estimates and replace ACS sentinel values with NA.
    for v in variables:
        df[v] = clean_acs_numeric(df[v])

    df["GEOID"] = df["state"] + df["county"] + df["tract"]
    return df[["GEOID"] + variables]


def download_tract_shapefile() -> gpd.GeoDataFrame:
    """
    Download NM tract shapefile (if not already) and return Bernalillo County tracts as GeoDataFrame.
    """
    ensure_output_dir()
    local_zip = os.path.join(OUTPUT_DIR, os.path.basename(TIGER_TRACT_URL))

    if not os.path.exists(local_zip):
        print(f"Downloading TIGER tracts from {TIGER_TRACT_URL} ...")
        resp = requests.get(TIGER_TRACT_URL)
        resp.raise_for_status()
        with open(local_zip, "wb") as f:
            f.write(resp.content)
        print("  Saved:", local_zip)
    else:
        print("TIGER tracts zip already present:", local_zip)

    print("Reading tract shapefile and filtering to Bernalillo County...")
    tracts = gpd.read_file(f"zip://{local_zip}")

    # Filter to Bernalillo (county FIPS 001)
    tracts = tracts[tracts["COUNTYFP"] == COUNTY_FIPS].copy()
    tracts["GEOID"] = tracts["GEOID"].astype(str)
    tracts = tracts.to_crs(GEOG_CRS)
    print(f"  ✓ Loaded {len(tracts)} tracts for Bernalillo County")
    return tracts



def load_hospital_distances(csv_path: str) -> pd.DataFrame | None:
    """
    Load tract-level nearest hospital distance data.

    The current source is a precomputed CSV with one row per tract/year:
        GEOID, year, dist1, hosp_id1
    dist1 is treated as miles. The latest available year is used.
    """
    if csv_path is None:
        print("HOSPITAL_DISTANCE_CSV_PATH is None - skipping hospital distance.")
        return None

    if not os.path.exists(csv_path):
        print(f"Hospital distance CSV not found at {csv_path}. Skipping hospital distance.")
        return None

    print(f"Loading hospital distances from {csv_path} ...")
    df = pd.read_csv(csv_path)
    required = {"GEOID", "year", "dist1"}
    missing = required - set(df.columns)
    if missing:
        print(f"Hospital distance CSV is missing required columns: {sorted(missing)}")
        return None

    df = df.copy()
    df["GEOID"] = df["GEOID"].astype(str)
    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    df["hospital_distance_mi"] = pd.to_numeric(df["dist1"], errors="coerce")
    if "hosp_id1" in df.columns:
        df["nearest_hospital_id"] = df["hosp_id1"].astype("string")
    else:
        df["nearest_hospital_id"] = pd.NA

    df = df.dropna(subset=["GEOID", "year", "hospital_distance_mi"])
    if df.empty:
        print("Hospital distance CSV has no usable rows.")
        return None

    latest_year = int(df["year"].max())
    latest = df[df["year"] == latest_year].copy()
    latest = latest.sort_values("hospital_distance_mi").drop_duplicates("GEOID", keep="first")
    latest["hospital_distance_year"] = latest_year
    print(f"  Loaded hospital distance for {len(latest)} tracts from year {latest_year}")
    return latest[["GEOID", "hospital_distance_mi", "nearest_hospital_id", "hospital_distance_year"]]


def load_hrsa_sites(csv_path: str) -> gpd.GeoDataFrame | None:
    """
    Load health center sites CSV with columns Latitude, Longitude.
    Returns GeoDataFrame or None if file missing.
    """
    if csv_path is None:
        print("HRSA_CSV_PATH is None - skipping clinic distance calculation.")
        return None

    if not os.path.exists(csv_path):
        print(f"HRSA CSV not found at {csv_path}. Skipping clinic distances.")
        return None

    print(f"Loading HRSA/FQHC sites from {csv_path} ...")
    df = pd.read_csv(csv_path)

    # Try to find lat/long columns (you can tweak this if your file uses different names)
    lat_col_candidates = ["Latitude", "LATITUDE", "lat", "Y"]
    lon_col_candidates = ["Longitude", "LONGITUDE", "lon", "X"]

    lat_col = next((c for c in lat_col_candidates if c in df.columns), None)
    lon_col = next((c for c in lon_col_candidates if c in df.columns), None)

    if lat_col is None or lon_col is None:
        print("Could not identify Latitude/Longitude columns in HRSA CSV. Columns present:")
        print(df.columns)
        print("   Skipping clinic distance calculation.")
        return None

    df = df.dropna(subset=[lat_col, lon_col]).copy()
    gdf = gpd.GeoDataFrame(
        df,
        geometry=gpd.points_from_xy(df[lon_col], df[lat_col]),
        crs=GEOG_CRS
    )
    print(f"  Loaded {len(gdf)} clinic points")
    return gdf


def compute_nearest_distance_km(tracts: gpd.GeoDataFrame, clinics: gpd.GeoDataFrame) -> pd.Series:
    """
    Compute distance from each tract centroid to nearest clinic (km).
    Uses a projected CRS for accuracy.
    """
    tracts_metric = tracts.to_crs(METRIC_CRS).copy()
    clinics_metric = clinics.to_crs(METRIC_CRS).copy()

    # Unary union is an efficient multi-point object
    clinic_union = clinics_metric.geometry.unary_union

    print("Computing distance to nearest clinic for each tract centroid...")
    centroids = tracts_metric.geometry.centroid
    dists_m = centroids.apply(lambda geom: geom.distance(clinic_union))

    return dists_m / 1000.0  # km


def minmax(series: pd.Series) -> pd.Series:
    """Return (x - min) / (max - min), preserving missing values."""
    series = clean_acs_numeric(series)
    mn = series.min(skipna=True)
    mx = series.max(skipna=True)
    if pd.isna(mn) or pd.isna(mx) or mx == mn:
        return pd.Series(pd.NA, index=series.index, dtype="Float64")
    return (series - mn) / (mx - mn)


# =========================
# MAIN BUILDER
# =========================

def build_bern_uoi(refresh: bool = True) -> gpd.GeoDataFrame:
    """
    Build Bernalillo County UOI dataset.

    - If refresh=True: hit the Census API and regenerate everything.
    - Always saves:
        outputs/bern_uoi_tracts.gpkg
        outputs/bern_uoi_tracts.csv
    - Returns a GeoDataFrame with all indicators + geometry.
    """
    ensure_output_dir()

    # ---------- 1. Download ACS data ----------

    # A. Broadband: B28002 (Detailed ACS table)
    # B28002_001E = Total households
    # B28002_004E = Households with broadband Internet subscription of any type
    broadband_vars = ["B28002_001E", "B28002_004E"]
    df_broadband = fetch_acs_json(
        ACS_YEAR,
        "acs/acs5",
        broadband_vars,
        STATE_FIPS,
        COUNTY_FIPS
    )

    # B. Housing cost burden: S2503 (Subject table, financial characteristics)
    # Following SVI-style construction:
    # E_HBURD = S2503_C01_028E + 032E + 036E + 040E
    # EP_HBURD = E_HBURD / S2503_C01_001E * 100
    rent_vars = [
        "S2503_C01_001E",  # total occupied housing units
        "S2503_C01_028E",
        "S2503_C01_032E",
        "S2503_C01_036E",
        "S2503_C01_040E",
    ]
    df_rent = fetch_acs_json(
        ACS_YEAR,
        "acs/acs5/subject",
        rent_vars,
        STATE_FIPS,
        COUNTY_FIPS
    )

    # C. Uninsured: S2701 (Subject table, health insurance)
    # E_UNINSUR = S2701_C04_001E (uninsured count)
    # Total = S2701_C01_001E; percent uninsured = E_UNINSUR / Total * 100
    health_vars = [
        "S2701_C01_001E",  # total civilian noninstitutionalized pop
        "S2701_C04_001E",  # uninsured count
    ]
    df_health = fetch_acs_json(
        ACS_YEAR,
        "acs/acs5/subject",
        health_vars,
        STATE_FIPS,
        COUNTY_FIPS
    )

    # D. Poverty: S1701 (Subject table, poverty status)
    # pct_poverty = percent of people below poverty level
    poverty_vars = [
        "S1701_C03_001E",  # percent below poverty level (all people for whom poverty status is determined)
    ]
    df_poverty = fetch_acs_json(
        ACS_YEAR,
        "acs/acs5/subject",
        poverty_vars,
        STATE_FIPS,
        COUNTY_FIPS
    )

    # E. Income: S1901 (Subject table, income)
    # median_hh_income = median household income (dollars)
    income_vars = [
        "S1901_C01_012E",  # median household income in dollars
    ]
    df_income = fetch_acs_json(
        ACS_YEAR,
        "acs/acs5/subject",
        income_vars,
        STATE_FIPS,
        COUNTY_FIPS
    )


    # G. Disability: S1810 (Subject table, disability characteristics)
    # pct_disability = percent of civilian noninstitutionalized population with a disability
    disability_vars = [
        "S1810_C03_001E",
    ]
    df_disability = fetch_acs_json(
        ACS_YEAR,
        "acs/acs5/subject",
        disability_vars,
        STATE_FIPS,
        COUNTY_FIPS
    )

    # H. Education: S1501 (Subject table, educational attainment)
    # pct_hs_or_higher = percent of adults 25+ with high school graduate or higher
    edu_vars = [
        "S1501_C02_014E",  # percent high school graduate or higher, population 25 years and over
    ]
    df_edu = fetch_acs_json(
        ACS_YEAR,
        "acs/acs5/subject",
        edu_vars,
        STATE_FIPS,
        COUNTY_FIPS
    )

    # I. SNAP/food assistance: S2201 (Subject table, Food Stamps/SNAP)
    # pct_snap = percent of households receiving SNAP benefits
    snap_vars = [
        "S2201_C04_001E",
    ]
    df_snap = fetch_acs_json(
        ACS_YEAR,
        "acs/acs5/subject",
        snap_vars,
        STATE_FIPS,
        COUNTY_FIPS
    )

    # J. Employment: S2301 (Subject table, employment status)
    # unemployment_rate = unemployment rate for population 16 years and over
    emp_vars = [
        "S2301_C04_001E",  # unemployment rate (percent), population 16 years and over
    ]
    df_emp = fetch_acs_json(
        ACS_YEAR,
        "acs/acs5/subject",
        emp_vars,
        STATE_FIPS,
        COUNTY_FIPS
    )

    # K. Vehicle access: B08201 (Detailed table, household vehicles available)
    # pct_no_vehicle = households with no vehicle / total households
    vehicle_vars = [
        "B08201_001E",  # total households
        "B08201_002E",  # no vehicle available
    ]
    df_vehicle = fetch_acs_json(
        ACS_YEAR,
        "acs/acs5",
        vehicle_vars,
        STATE_FIPS,
        COUNTY_FIPS
    )

    # L. Language isolation: C16002 (Detailed table, household limited English speaking status)
    # pct_lep = households that are "limited English speaking" / total households
    # Mirrors CDC SVI methodology.
    lang_vars = [
        "C16002_001E",  # total households
        "C16002_004E",  # Spanish - limited English speaking household
        "C16002_007E",  # Other Indo-European - limited English speaking household
        "C16002_010E",  # Asian and Pacific Islander - limited English speaking household
        "C16002_013E",  # Other - limited English speaking household
    ]
    df_lang = fetch_acs_json(
        ACS_YEAR,
        "acs/acs5",
        lang_vars,
        STATE_FIPS,
        COUNTY_FIPS
    )

    # ---------- 2. Compute tract-level indicators (tabular) ----------

    print("Computing indicators...")

    # Broadband: percent of households with broadband subscription
    df_broadband["pct_broadband"] = safe_pct(
        df_broadband["B28002_004E"], df_broadband["B28002_001E"]
    )

    # Rent burden: following SVI method (E_HBURD / total occupied units)
    df_rent["E_HBURD"] = (
        df_rent["S2503_C01_028E"]
        + df_rent["S2503_C01_032E"]
        + df_rent["S2503_C01_036E"]
        + df_rent["S2503_C01_040E"]
    )
    df_rent["pct_rent_burdened"] = safe_pct(
        df_rent["E_HBURD"], df_rent["S2503_C01_001E"]
    )

    # Health insurance: percent uninsured
    df_health["pct_uninsured"] = safe_pct(
        df_health["S2701_C04_001E"], df_health["S2701_C01_001E"]
    )

    # Poverty: percent below poverty level (already a percent in S1701_C03_001E)
    df_poverty["pct_poverty"] = df_poverty["S1701_C03_001E"]

    # Income: median household income (dollars)
    df_income["median_hh_income"] = df_income["S1901_C01_012E"]


    # Disability: percent of people with a disability (already a percent)
    df_disability["pct_disability"] = df_disability["S1810_C03_001E"]

    # Education: percent of adults 25+ with high school graduate or higher (already a percent)
    df_edu["pct_hs_or_higher"] = df_edu["S1501_C02_014E"]

    # SNAP: percent of households receiving SNAP (already a percent)
    df_snap["pct_snap"] = df_snap["S2201_C04_001E"]

    # Employment: unemployment rate (already a percent)
    df_emp["unemployment_rate"] = df_emp["S2301_C04_001E"]

    # Vehicle access: percent of households with no vehicle
    df_vehicle["pct_no_vehicle"] = safe_pct(
        df_vehicle["B08201_002E"], df_vehicle["B08201_001E"]
    )

    # Language isolation: percent of households that are limited English speaking
    df_lang["pct_lep"] = safe_pct(
        df_lang["C16002_004E"] + df_lang["C16002_007E"]
        + df_lang["C16002_010E"] + df_lang["C16002_013E"],
        df_lang["C16002_001E"]
    )

    # Merge all indicators on GEOID
    df_indicators = (
        df_broadband[["GEOID", "pct_broadband"]]
        .merge(df_rent[["GEOID", "pct_rent_burdened"]], on="GEOID", how="left")
        .merge(df_health[["GEOID", "pct_uninsured"]], on="GEOID", how="left")
        .merge(df_poverty[["GEOID", "pct_poverty"]], on="GEOID", how="left")
        .merge(df_income[["GEOID", "median_hh_income"]], on="GEOID", how="left")
        .merge(df_disability[["GEOID", "pct_disability"]], on="GEOID", how="left")
        .merge(df_edu[["GEOID", "pct_hs_or_higher"]], on="GEOID", how="left")
        .merge(df_snap[["GEOID", "pct_snap"]], on="GEOID", how="left")
        .merge(df_emp[["GEOID", "unemployment_rate"]], on="GEOID", how="left")
        .merge(df_vehicle[["GEOID", "pct_no_vehicle"]], on="GEOID", how="left")
        .merge(df_lang[["GEOID", "pct_lep"]], on="GEOID", how="left")
    )

    print("  Indicator table shape:", df_indicators.shape)

    # ---------- 3. Download & prepare tract geometries ----------

    tracts = download_tract_shapefile()

    # Join indicators to tracts
    gdf = tracts.merge(df_indicators, on="GEOID", how="left")

    # ---------- 4. Health access distances ----------

    hospital_distances = load_hospital_distances(HOSPITAL_DISTANCE_CSV_PATH)
    if hospital_distances is not None:
        gdf = gdf.merge(hospital_distances, on="GEOID", how="left")
        print("  Added hospital_distance_mi column")
    else:
        gdf["hospital_distance_mi"] = pd.NA
        gdf["nearest_hospital_id"] = pd.NA
        gdf["hospital_distance_year"] = pd.NA

    # ---------- 4b. (Optional) Clinic distances ----------

    clinic_gdf = load_hrsa_sites(HRSA_CSV_PATH)
    if clinic_gdf is not None:
        gdf["dist_clinic_km"] = compute_nearest_distance_km(gdf, clinic_gdf)
        print("  Added dist_clinic_km column")
    else:
        gdf["dist_clinic_km"] = pd.NA

    # ---------- 5. Normalize and build Urban Opportunity Index ----------

    indicator_cols = [
        "pct_broadband",
        "pct_rent_burdened",
        "pct_uninsured",
        "pct_poverty",
        "median_hh_income",
        "pct_disability",
        "pct_hs_or_higher",
        "pct_snap",
        "unemployment_rate",
        "hospital_distance_mi",
    ]
    missing_counts = gdf[indicator_cols].isna().sum()
    if missing_counts.any():
        print("Missing indicator counts after ACS cleanup:")
        print(missing_counts[missing_counts > 0].to_string())

    print("Normalizing indicators and computing Urban Opportunity Index...")

    # Direction:
    # - pct_broadband: higher = better -> keep
    # - pct_uninsured: higher = worse -> invert
    # - pct_rent_burdened: higher = worse -> invert
    # - dist_clinic_km: higher = worse -> invert

    gdf["norm_broadband"] = minmax(gdf["pct_broadband"])
    gdf["norm_uninsured"] = 1 - minmax(gdf["pct_uninsured"])
    gdf["norm_rent_burdened"] = 1 - minmax(gdf["pct_rent_burdened"])

    # Poverty: lower poverty = better
    gdf["norm_poverty"] = 1 - minmax(gdf["pct_poverty"])

    # Income: higher income = better
    gdf["norm_income"] = minmax(gdf["median_hh_income"])


    # Disability: fewer people with a disability = better (barrier-focused lens)
    gdf["norm_disability"] = 1 - minmax(gdf["pct_disability"])

    # Education: more adults with high school or higher = better
    gdf["norm_hs_or_higher"] = minmax(gdf["pct_hs_or_higher"])

    # SNAP: fewer households relying on SNAP = higher opportunity
    gdf["norm_snap"] = 1 - minmax(gdf["pct_snap"])

    # Employment: lower unemployment rate = higher opportunity
    gdf["norm_unemployment"] = 1 - minmax(gdf["unemployment_rate"])

    # Vehicle access: fewer households without a car = higher opportunity
    gdf["norm_vehicle_access"] = 1 - minmax(gdf["pct_no_vehicle"])

    # Language isolation: fewer limited-English households = fewer service barriers
    gdf["norm_language_access"] = 1 - minmax(gdf["pct_lep"])

    # Eviction risk: combines rent burden, poverty, SNAP reliance, and unemployment
    # Higher eviction_risk_score = more at risk; higher eviction_resilience_score = more stable
    risk_components = [
        minmax(gdf["pct_rent_burdened"]),
        minmax(gdf["pct_poverty"]),
        minmax(gdf["pct_snap"]),
        minmax(gdf["unemployment_rate"]),
    ]
    gdf["eviction_risk_score"] = pd.concat(risk_components, axis=1).mean(axis=1)
    gdf["eviction_resilience_score"] = 1 - gdf["eviction_risk_score"]

    if gdf["hospital_distance_mi"].notna().any():
        gdf["norm_hospital_access"] = 1 - minmax(gdf["hospital_distance_mi"])
    else:
        gdf["norm_hospital_access"] = pd.NA

    if gdf["dist_clinic_km"].notna().any():
        gdf["norm_clinic_access"] = 1 - minmax(gdf["dist_clinic_km"])
    else:
        gdf["norm_clinic_access"] = pd.NA

    # Choose which components to include in the overall index
    uoi_components = [
        "norm_broadband",
        "norm_uninsured",
        "norm_rent_burdened",
        "norm_poverty",
        "norm_income",
        "norm_disability",
        "norm_hs_or_higher",
        "norm_snap",
        "norm_unemployment",
        "norm_vehicle_access",
    ]
    if gdf["norm_hospital_access"].notna().any():
        uoi_components.append("norm_hospital_access")
    if gdf["norm_clinic_access"].notna().any():
        uoi_components.append("norm_clinic_access")

    gdf["uoi_score"] = gdf[uoi_components].mean(axis=1)

    # ---------- 6. Export for mapping ----------

    gpkg_path = os.path.join(OUTPUT_DIR, "bern_uoi_tracts.gpkg")
    csv_path = os.path.join(OUTPUT_DIR, "bern_uoi_tracts.csv")

    print(f"Saving GeoPackage to {gpkg_path} ...")
    gdf.to_file(gpkg_path, layer="tracts", driver="GPKG")

    # Also export a non-spatial table for other tools
    non_geom_cols = [c for c in gdf.columns if c != "geometry"]
    gdf[non_geom_cols].to_csv(csv_path, index=False)
    print(f"Saving CSV to {csv_path} ...")

    # Preserve custom area_label / tract_label from existing GeoJSON (hand-curated names)
    existing_geojson = os.path.join("data", "tracts.json")
    if os.path.exists(existing_geojson):
        import json as _json
        with open(existing_geojson) as _f:
            _old = _json.load(_f)
        _label_map = {
            feat["properties"]["GEOID"]: {
                "area_label": feat["properties"].get("area_label"),
                "tract_label": feat["properties"].get("tract_label"),
            }
            for feat in _old["features"]
            if feat["properties"].get("area_label") is not None
        }
        if _label_map:
            gdf["area_label"] = gdf["GEOID"].map(lambda g: _label_map.get(g, {}).get("area_label"))
            gdf["tract_label"] = gdf["GEOID"].map(lambda g: _label_map.get(g, {}).get("tract_label"))
            print(f"  Preserved area_label / tract_label for {len(_label_map)} tracts")

    # Export GeoJSON for the web app
    geojson_path = os.path.join("data", "tracts.json")
    web_cols = [
        "GEOID", "NAME", "area_label", "tract_label", "NAMELSAD",
        "uoi_score",
        "pct_broadband", "norm_broadband",
        "pct_rent_burdened", "norm_rent_burdened",
        "pct_uninsured", "norm_uninsured",
        "hospital_distance_mi", "norm_hospital_access",
        "pct_poverty", "norm_poverty",
        "median_hh_income", "norm_income",
        "pct_disability", "norm_disability",
        "pct_hs_or_higher", "norm_hs_or_higher",
        "pct_snap", "norm_snap",
        "unemployment_rate", "norm_unemployment",
        "pct_no_vehicle", "norm_vehicle_access",
        "pct_lep", "norm_language_access",
        "eviction_risk_score", "eviction_resilience_score",
        "geometry",
    ]
    # Only keep columns that actually exist (handles optional fields gracefully)
    web_cols = [c for c in web_cols if c in gdf.columns]
    gdf_web = gdf[web_cols].to_crs("EPSG:4326")
    gdf_web.to_file(geojson_path, driver="GeoJSON")
    print(f"Saving GeoJSON to {geojson_path} ...")

    print("\nDone")
    print("Columns you’ll likely map first:")
    print("  - pct_broadband")
    print("  - pct_uninsured")
    print("  - pct_rent_burdened")
    print("  - pct_poverty")
    print("  - median_hh_income")
    print("  - pct_disability")
    print("  - pct_hs_or_higher")
    print("  - pct_snap")
    print("  - unemployment_rate")
    print("  - hospital_distance_mi")
    print("  - dist_clinic_km (if available)")
    print("  - uoi_score (overall Urban Opportunity Index)")
    print("  - eviction_resilience_score (higher = more stability against eviction)")

    return gdf


def main():
    build_bern_uoi(refresh=True)


if __name__ == "__main__":
    main()