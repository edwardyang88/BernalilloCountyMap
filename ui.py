"""
Streamlit UI for the Bernalillo County Urban Opportunity Index.

Run with:
    streamlit run ui.py
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

import folium
import geopandas as gpd
import pandas as pd
import streamlit as st
from branca.colormap import linear
from streamlit_folium import st_folium

from bern_uoi_pipeline import ACS_YEAR, OUTPUT_DIR, build_bern_uoi

DATA_GPKG = os.path.join(OUTPUT_DIR, "bern_uoi_tracts.gpkg")
DATA_LAYER = "tracts"
NEIGHBORHOODS_GEOJSON = os.path.join(OUTPUT_DIR, "abq_neighborhood_associations.geojson")
COMMISSION_DISTRICTS_GEOJSON = os.path.join(OUTPUT_DIR, "bernco_commission_districts.geojson")
METRIC_CRS = "EPSG:26913"
SCORE_SUFFIX = "_display"


@dataclass(frozen=True)
class LayerConfig:
    key: str
    label: str
    short_label: str
    score_col: str
    raw_col: str
    raw_label: str
    raw_unit: str
    raw_direction: str
    why_it_matters: str
    score_meaning: str
    palette_score: str = "YlGnBu_09"
    palette_raw: str = "YlOrRd_09"


@dataclass(frozen=True)
class IntersectionMetric:
    key: str
    label: str
    column: str
    unit: str
    help_text: str


LAYERS: dict[str, LayerConfig] = {
    "overall": LayerConfig(
        key="overall",
        label="Overall opportunity",
        short_label="Overall",
        score_col="uoi_score",
        raw_col="uoi_score",
        raw_label="Overall opportunity score",
        raw_unit="score",
        raw_direction="higher_better",
        why_it_matters="A combined view of access, stability, income, education, and hardship signals.",
        score_meaning="Higher scores mean stronger overall access and fewer measured barriers.",
    ),
    "internet": LayerConfig(
        key="internet",
        label="Internet access",
        short_label="Internet",
        score_col="norm_broadband",
        raw_col="pct_broadband",
        raw_label="Households with home internet",
        raw_unit="percent",
        raw_direction="higher_better",
        why_it_matters="Home internet affects job search, benefits access, school work, telehealth, and legal self-help.",
        score_meaning="Higher scores mean more households have home internet.",
        palette_raw="YlGnBu_09",
    ),
    "housing": LayerConfig(
        key="housing",
        label="Housing cost pressure",
        short_label="Housing",
        score_col="norm_rent_burdened",
        raw_col="pct_rent_burdened",
        raw_label="Households with high housing costs",
        raw_unit="percent",
        raw_direction="higher_worse",
        why_it_matters="High housing costs leave less money for food, transportation, utilities, and emergency expenses.",
        score_meaning="Higher scores mean fewer households are cost burdened.",
    ),
    "health": LayerConfig(
        key="health",
        label="Health insurance coverage",
        short_label="Insurance",
        score_col="norm_uninsured",
        raw_col="pct_uninsured",
        raw_label="People without health insurance",
        raw_unit="percent",
        raw_direction="higher_worse",
        why_it_matters="Uninsured residents are more exposed to medical debt and delayed care.",
        score_meaning="Higher scores mean fewer people are uninsured.",
    ),
    "hospital": LayerConfig(
        key="hospital",
        label="Hospital access",
        short_label="Hospital",
        score_col="norm_hospital_access",
        raw_col="hospital_distance_mi",
        raw_label="Miles to nearest hospital",
        raw_unit="miles",
        raw_direction="higher_worse",
        why_it_matters="Longer distance to a hospital can make emergency care and follow-up care harder to reach.",
        score_meaning="Higher scores mean the tract is closer to a hospital.",
    ),
    "poverty": LayerConfig(
        key="poverty",
        label="Poverty",
        short_label="Poverty",
        score_col="norm_poverty",
        raw_col="pct_poverty",
        raw_label="People below the poverty line",
        raw_unit="percent",
        raw_direction="higher_worse",
        why_it_matters="Poverty is a direct signal of economic stress and eligibility pressure for support services.",
        score_meaning="Higher scores mean lower poverty rates.",
    ),
    "income": LayerConfig(
        key="income",
        label="Household income",
        short_label="Income",
        score_col="norm_income",
        raw_col="median_hh_income",
        raw_label="Median household income",
        raw_unit="currency",
        raw_direction="higher_better",
        why_it_matters="Income helps identify where households have more or less room to absorb financial shocks.",
        score_meaning="Higher scores mean higher median household incomes.",
        palette_raw="YlGnBu_09",
    ),
    "disability": LayerConfig(
        key="disability",
        label="Disability-related barriers",
        short_label="Disability",
        score_col="norm_disability",
        raw_col="pct_disability",
        raw_label="People living with a disability",
        raw_unit="percent",
        raw_direction="higher_worse",
        why_it_matters="Disability can increase the need for accessible services, transportation support, and benefits navigation.",
        score_meaning="Higher scores mean a lower measured disability-related barrier rate.",
    ),
    "education": LayerConfig(
        key="education",
        label="Education",
        short_label="Education",
        score_col="norm_hs_or_higher",
        raw_col="pct_hs_or_higher",
        raw_label="Adults with high school or higher",
        raw_unit="percent",
        raw_direction="higher_better",
        why_it_matters="Educational attainment is connected to employment options, income, and navigation of institutions.",
        score_meaning="Higher scores mean more adults have at least a high school credential.",
        palette_raw="YlGnBu_09",
    ),
    "snap": LayerConfig(
        key="snap",
        label="SNAP reliance",
        short_label="SNAP",
        score_col="norm_snap",
        raw_col="pct_snap",
        raw_label="Households receiving SNAP",
        raw_unit="percent",
        raw_direction="higher_worse",
        why_it_matters="SNAP use can point to food insecurity and household income stress.",
        score_meaning="Higher scores mean lower SNAP reliance.",
    ),
    "unemployment": LayerConfig(
        key="unemployment",
        label="Unemployment",
        short_label="Jobs",
        score_col="norm_unemployment",
        raw_col="unemployment_rate",
        raw_label="Unemployment rate",
        raw_unit="percent",
        raw_direction="higher_worse",
        why_it_matters="Unemployment is a strong signal of near-term financial instability.",
        score_meaning="Higher scores mean lower unemployment.",
    ),
    "eviction": LayerConfig(
        key="eviction",
        label="Eviction pressure",
        short_label="Eviction",
        score_col="eviction_resilience_score",
        raw_col="eviction_risk_score",
        raw_label="Eviction pressure score",
        raw_unit="score",
        raw_direction="higher_worse",
        why_it_matters="This proxy combines rent burden, poverty, SNAP reliance, and unemployment to flag instability.",
        score_meaning="Higher scores mean stronger resilience against eviction pressure.",
    ),
}

INTERSECTION_METRICS: dict[str, IntersectionMetric] = {
    "income": IntersectionMetric(
        key="income",
        label="Household income",
        column="median_hh_income",
        unit="currency",
        help_text="Median household income.",
    ),
    "hospital": IntersectionMetric(
        key="hospital",
        label="Hospital distance",
        column="hospital_distance_mi",
        unit="miles",
        help_text="Miles from the tract to the nearest hospital.",
    ),
    "poverty": IntersectionMetric(
        key="poverty",
        label="Poverty",
        column="pct_poverty",
        unit="percent",
        help_text="Share of people below the federal poverty line.",
    ),
    "housing": IntersectionMetric(
        key="housing",
        label="Housing cost pressure",
        column="pct_rent_burdened",
        unit="percent",
        help_text="Share of households paying high housing costs.",
    ),
    "uninsured": IntersectionMetric(
        key="uninsured",
        label="Uninsured rate",
        column="pct_uninsured",
        unit="percent",
        help_text="Share of people without health insurance.",
    ),
    "internet": IntersectionMetric(
        key="internet",
        label="Home internet access",
        column="pct_broadband",
        unit="percent",
        help_text="Share of households with home internet.",
    ),
    "disability": IntersectionMetric(
        key="disability",
        label="Disability",
        column="pct_disability",
        unit="percent",
        help_text="Share of people living with a disability.",
    ),
    "education": IntersectionMetric(
        key="education",
        label="High school or higher",
        column="pct_hs_or_higher",
        unit="percent",
        help_text="Share of adults 25+ with a high school credential or higher.",
    ),
    "snap": IntersectionMetric(
        key="snap",
        label="SNAP reliance",
        column="pct_snap",
        unit="percent",
        help_text="Share of households receiving SNAP.",
    ),
    "unemployment": IntersectionMetric(
        key="unemployment",
        label="Unemployment",
        column="unemployment_rate",
        unit="percent",
        help_text="Unemployment rate for people 16 and older.",
    ),
    "eviction": IntersectionMetric(
        key="eviction",
        label="Eviction pressure",
        column="eviction_risk_score",
        unit="score",
        help_text="Proxy score from rent burden, poverty, SNAP reliance, and unemployment.",
    ),
    "overall": IntersectionMetric(
        key="overall",
        label="Overall opportunity score",
        column="uoi_score",
        unit="score",
        help_text="Composite opportunity score.",
    ),
}

METHOD_COMPONENTS = [
    ("Internet access", "Households with broadband or other home internet subscription", "Higher is better"),
    ("Housing costs", "Households spending 30% or more of income on housing", "Lower is better"),
    ("Health insurance", "People without health insurance", "Lower is better"),
    ("Hospital access", "Distance from tract to nearest hospital", "Lower is better"),
    ("Poverty", "People below the federal poverty line", "Lower is better"),
    ("Income", "Median household income", "Higher is better"),
    ("Disability", "People living with a disability", "Lower barrier rate scores higher"),
    ("Education", "Adults 25+ with high school diploma, GED, or higher", "Higher is better"),
    ("SNAP reliance", "Households receiving SNAP benefits", "Lower is better"),
    ("Unemployment", "Unemployment rate for people 16+", "Lower is better"),
]


@st.cache_data(show_spinner=True)
def load_data() -> gpd.GeoDataFrame:
    if os.path.exists(DATA_GPKG):
        gdf = gpd.read_file(DATA_GPKG, layer=DATA_LAYER)
        if "eviction_resilience_score" not in gdf.columns:
            gdf = build_bern_uoi(refresh=True)
    else:
        gdf = build_bern_uoi(refresh=True)
    return add_area_labels(gdf)


@st.cache_data(show_spinner=False)
def load_commission_districts() -> gpd.GeoDataFrame | None:
    if not os.path.exists(COMMISSION_DISTRICTS_GEOJSON):
        return None
    districts = gpd.read_file(COMMISSION_DISTRICTS_GEOJSON)
    if districts.crs is not None and districts.crs.to_string() != "EPSG:4326":
        districts = districts.to_crs("EPSG:4326")
    return districts


def clean_area_name(name: str) -> str:
    name = str(name or "").strip()
    name = re.sub(r"\s+NA(?:\s+Incorporated)?$", "", name)
    name = re.sub(r"\s+Neighborhood Association(?:\s+Incorporated)?$", "", name)
    name = re.sub(r"\s+Community Association$", " Community", name)
    name = re.sub(r"\s+Association$", "", name)
    name = re.sub(r"\s+Incorporated$", "", name)
    return name.strip() or "Albuquerque area"


def regional_area_label(row: pd.Series) -> str:
    lat = float(row.get("INTPTLAT") or row.geometry.centroid.y)
    lon = float(row.get("INTPTLON") or row.geometry.centroid.x)
    if lon > -106.45:
        return "East Mountains / Tijeras area"
    if lon < -106.82:
        return "West Mesa / To'hajiilee area"
    if lat >= 35.18 and lon < -106.60:
        return "North Valley / Alameda area"
    if lat <= 35.02 and lon < -106.60:
        return "South Valley area"
    if lon < -106.70:
        return "Southwest Mesa area"
    if lat >= 35.14:
        return "Far Northeast Heights area"
    if lat <= 35.03:
        return "South Albuquerque area"
    return "Central Albuquerque area"


def add_area_labels(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if {"area_label", "tract_label"}.issubset(gdf.columns):
        return gdf

    labeled = gdf.copy()
    labeled["area_label"] = labeled.apply(regional_area_label, axis=1)
    labeled["area_source"] = "regional label"

    if os.path.exists(NEIGHBORHOODS_GEOJSON):
        neighborhoods = gpd.read_file(NEIGHBORHOODS_GEOJSON)
        neighborhoods = neighborhoods.dropna(subset=["AssociationName"]).copy()
        neighborhoods["area_label"] = neighborhoods["AssociationName"].map(clean_area_name)

        tract_geom = labeled[["GEOID", "geometry"]].to_crs(METRIC_CRS)
        neighborhood_geom = neighborhoods[["area_label", "geometry"]].to_crs(METRIC_CRS)
        intersections = gpd.overlay(tract_geom, neighborhood_geom, how="intersection")
        if not intersections.empty:
            intersections["overlap_area"] = intersections.area
            best = intersections.sort_values("overlap_area").groupby("GEOID", as_index=False).tail(1)
            best_labels = best.set_index("GEOID")["area_label"]
            matched = labeled["GEOID"].isin(best_labels.index)
            labeled.loc[matched, "area_label"] = labeled.loc[matched, "GEOID"].map(best_labels)
            labeled.loc[matched, "area_source"] = "Albuquerque neighborhood association"

    labeled["tract_label"] = labeled["area_label"] + " (Tract " + labeled["NAME"].astype(str) + ")"
    return labeled


def is_score_column(column_name: str) -> bool:
    return column_name.startswith("norm_") or column_name.endswith("_score")


def add_display_column(gdf: gpd.GeoDataFrame, color_col: str) -> tuple[gpd.GeoDataFrame, str]:
    if not is_score_column(color_col):
        return gdf, color_col

    display_col = f"{color_col}{SCORE_SUFFIX}"
    gdf_display = gdf.copy()
    gdf_display[display_col] = pd.to_numeric(gdf_display[color_col], errors="coerce") * 100
    return gdf_display, display_col


def selected_column(layer: LayerConfig, value_mode: str) -> tuple[str, str, str]:
    if value_mode == "score":
        return layer.score_col, f"{layer.short_label} score", "score"
    return layer.raw_col, layer.raw_label, layer.raw_unit


def format_value(value, unit: str) -> str:
    if pd.isna(value):
        return "No data"
    value = float(value)
    if unit == "currency":
        return f"${value:,.0f}"
    if unit == "percent":
        return f"{value:.1f}%"
    if unit == "score":
        return f"{value:.1f}"
    if unit == "miles":
        return f"{value:.1f} mi"
    return f"{value:,.1f}"


def format_delta(layer: LayerConfig, value_mode: str) -> str:
    if value_mode == "score":
        return layer.score_meaning
    if layer.raw_direction == "higher_worse":
        return "Higher raw values indicate more pressure."
    if layer.raw_direction == "higher_better":
        return "Higher raw values indicate stronger access."
    return "Interpret alongside local context."


def format_intersection_value(value, metric: IntersectionMetric) -> str:
    if pd.isna(value):
        return "No data"
    value = float(value)
    if metric.unit == "score":
        return f"{value * 100:.1f}"
    return format_value(value, metric.unit)


def get_color_map(palette_name: str, values: pd.Series, caption: str):
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        colormap = linear.Greys_09.scale(0, 1).to_step(6)
        colormap.caption = caption
        return colormap

    q_low = clean.quantile(0.05)
    q_high = clean.quantile(0.95)
    if q_low == q_high:
        q_low = clean.min()
        q_high = clean.max() if clean.max() != clean.min() else clean.min() + 1

    palette = getattr(linear, palette_name)
    colormap = palette.scale(q_low, q_high).to_step(7)
    colormap.caption = caption
    return colormap


def add_commission_district_overlay(m: folium.Map) -> None:
    districts = load_commission_districts()
    if districts is None or districts.empty:
        return

    folium.GeoJson(
        districts.to_json(),
        name="Bernalillo County Commission districts",
        style_function=lambda _feature: {
            "fillOpacity": 0,
            "color": "#111827",
            "weight": 2.2,
            "dashArray": "6 4",
        },
        tooltip=folium.features.GeoJsonTooltip(
            fields=["DistrictName"],
            aliases=["Commission district"],
            sticky=False,
        ),
    ).add_to(m)
    folium.LayerControl(collapsed=True).add_to(m)


def build_map(
    gdf: gpd.GeoDataFrame,
    color_col: str,
    legend_name: str,
    palette_name: str,
    show_commission_districts: bool = False,
) -> folium.Map:
    if gdf.crs is not None and gdf.crs.to_string() != "EPSG:4326":
        gdf = gdf.to_crs("EPSG:4326")

    gdf_plot = gdf.copy()
    values = pd.to_numeric(gdf_plot[color_col], errors="coerce")
    gdf_plot["_map_value"] = values

    min_lon, min_lat, max_lon, max_lat = gdf_plot.total_bounds
    center_lat = (min_lat + max_lat) / 2
    center_lon = (min_lon + max_lon) / 2
    colormap = get_color_map(palette_name, values, legend_name)

    def style_feature(feature):
        value = feature["properties"].get("_map_value")
        if value is None or pd.isna(value):
            fill = "#d9d9d9"
            opacity = 0.25
        else:
            fill = colormap(value)
            opacity = 0.82
        return {
            "fillColor": fill,
            "color": "#334155",
            "weight": 0.55,
            "fillOpacity": opacity,
        }

    def highlight_feature(_feature):
        return {"weight": 2.0, "color": "#111827", "fillOpacity": 0.92}

    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=11,
        tiles="CartoDB positron",
        control_scale=True,
    )
    m.fit_bounds([[min_lat, min_lon], [max_lat, max_lon]])

    if "tract_label" not in gdf_plot.columns:
        gdf_plot["tract_label"] = "Tract " + gdf_plot["NAME"].astype(str)

    tooltip_fields = ["tract_label", "_display_value"]
    tooltip_aliases = ["Area", legend_name]
    folium.GeoJson(
        gdf_plot.to_json(),
        name=legend_name,
        style_function=style_feature,
        highlight_function=highlight_feature,
        tooltip=folium.features.GeoJsonTooltip(
            fields=tooltip_fields,
            aliases=tooltip_aliases,
            localize=True,
            sticky=False,
            labels=True,
        ),
    ).add_to(m)
    colormap.add_to(m)
    if show_commission_districts:
        add_commission_district_overlay(m)
    return m


def prepare_layer_data(gdf: gpd.GeoDataFrame, layer: LayerConfig, value_mode: str):
    source_col, legend_name, unit = selected_column(layer, value_mode)
    if source_col not in gdf.columns:
        return None, source_col, legend_name, unit

    plot_gdf = gdf[~gdf[source_col].isna()].copy()
    plot_gdf, map_col = add_display_column(plot_gdf, source_col)
    plot_gdf["_display_value"] = plot_gdf[map_col].apply(lambda value: format_value(value, unit))
    return plot_gdf, map_col, legend_name, unit


def metric_summary(plot_gdf: gpd.GeoDataFrame, map_col: str, unit: str, layer: LayerConfig, value_mode: str):
    values = pd.to_numeric(plot_gdf[map_col], errors="coerce")
    average = values.mean()
    low_row = plot_gdf.loc[values.idxmin()]
    high_row = plot_gdf.loc[values.idxmax()]

    low_label = low_row.get("tract_label", f"Tract {low_row['NAME']}")
    high_label = high_row.get("tract_label", f"Tract {high_row['NAME']}")

    c1, c2, c3 = st.columns(3)
    c1.metric("County average", format_value(average, unit), help=format_delta(layer, value_mode))
    c2.metric("Lowest value", format_value(low_row[map_col], unit), low_label)
    c3.metric("Highest value", format_value(high_row[map_col], unit), high_label)


def ranking_table(plot_gdf: gpd.GeoDataFrame, map_col: str, label: str, unit: str, sort_mode: str) -> pd.DataFrame:
    ascending = sort_mode == "lowest"
    label_cols = ["area_label", "NAME", "GEOID", map_col]
    for required in ["area_label", "NAME"]:
        if required not in plot_gdf.columns:
            plot_gdf[required] = plot_gdf.get("NAME", "")
    ranked = plot_gdf[label_cols].copy()
    ranked = ranked.sort_values(map_col, ascending=ascending).reset_index(drop=True)
    ranked.insert(0, "Rank", ranked.index + 1)
    ranked.rename(columns={"area_label": "Area", "NAME": "Census tract", map_col: label}, inplace=True)

    if unit == "currency":
        ranked[label] = ranked[label].map(lambda value: format_value(value, unit))
    elif unit in {"percent", "score", "miles"}:
        ranked[label] = ranked[label].map(lambda value: format_value(value, unit))
    return ranked


def quartile_mask(gdf: gpd.GeoDataFrame, metric: IntersectionMetric, condition: str) -> tuple[pd.Series, float]:
    values = pd.to_numeric(gdf[metric.column], errors="coerce")
    if condition == "bottom":
        threshold = values.quantile(0.25)
        return values <= threshold, threshold

    threshold = values.quantile(0.75)
    return values >= threshold, threshold


def condition_label(metric: IntersectionMetric, condition: str, threshold: float) -> str:
    side = "bottom quartile" if condition == "bottom" else "top quartile"
    comparator = "<=" if condition == "bottom" else ">="
    return f"{metric.label}: {side} ({comparator} {format_intersection_value(threshold, metric)})"


def intersection_priority_score(
    gdf: gpd.GeoDataFrame,
    metric_a: IntersectionMetric,
    condition_a: str,
    metric_b: IntersectionMetric,
    condition_b: str,
) -> pd.Series:
    a_rank = pd.to_numeric(gdf[metric_a.column], errors="coerce").rank(pct=True)
    b_rank = pd.to_numeric(gdf[metric_b.column], errors="coerce").rank(pct=True)
    if condition_a == "bottom":
        a_rank = 1 - a_rank
    if condition_b == "bottom":
        b_rank = 1 - b_rank
    return a_rank.add(b_rank).div(2).mul(100)


def build_intersection_map(
    gdf: gpd.GeoDataFrame,
    metric_a: IntersectionMetric,
    condition_a: str,
    metric_b: IntersectionMetric,
    condition_b: str,
    show_commission_districts: bool = False,
) -> folium.Map:
    plot_gdf = gdf.to_crs("EPSG:4326") if gdf.crs and gdf.crs.to_string() != "EPSG:4326" else gdf.copy()
    mask_a, threshold_a = quartile_mask(plot_gdf, metric_a, condition_a)
    mask_b, threshold_b = quartile_mask(plot_gdf, metric_b, condition_b)
    both = mask_a & mask_b

    plot_gdf["_intersection_group"] = "Neither condition"
    plot_gdf.loc[mask_a, "_intersection_group"] = f"{metric_a.label} only"
    plot_gdf.loc[mask_b, "_intersection_group"] = f"{metric_b.label} only"
    plot_gdf.loc[both, "_intersection_group"] = "Both conditions"
    plot_gdf["_a_value"] = plot_gdf[metric_a.column].apply(lambda value: format_intersection_value(value, metric_a))
    plot_gdf["_b_value"] = plot_gdf[metric_b.column].apply(lambda value: format_intersection_value(value, metric_b))

    colors = {
        "Both conditions": "#be123c",
        f"{metric_a.label} only": "#2563eb",
        f"{metric_b.label} only": "#f59e0b",
        "Neither condition": "#e5e7eb",
    }

    min_lon, min_lat, max_lon, max_lat = plot_gdf.total_bounds
    m = folium.Map(
        location=[(min_lat + max_lat) / 2, (min_lon + max_lon) / 2],
        zoom_start=11,
        tiles="CartoDB positron",
        control_scale=True,
    )
    m.fit_bounds([[min_lat, min_lon], [max_lat, max_lon]])

    def style_feature(feature):
        group = feature["properties"].get("_intersection_group", "Neither condition")
        return {
            "fillColor": colors[group],
            "color": "#334155",
            "weight": 0.55,
            "fillOpacity": 0.88 if group == "Both conditions" else 0.5,
        }

    folium.GeoJson(
        plot_gdf.to_json(),
        name="Intersection",
        style_function=style_feature,
        highlight_function=lambda _feature: {"weight": 2, "color": "#111827", "fillOpacity": 0.95},
        tooltip=folium.features.GeoJsonTooltip(
            fields=["tract_label", "_intersection_group", "_a_value", "_b_value"],
            aliases=["Area", "Match", metric_a.label, metric_b.label],
            sticky=False,
        ),
    ).add_to(m)

    legend_html = f"""
    <div style="background:white;border:1px solid #cbd5e1;border-radius:6px;padding:10px;width:310px;font-size:12px;">
      <strong>Intersection View</strong>
      <div style="margin-top:6px;"><span style="display:inline-block;width:12px;height:12px;background:{colors['Both conditions']};margin-right:6px;"></span>Both conditions</div>
      <div><span style="display:inline-block;width:12px;height:12px;background:{colors[f'{metric_a.label} only']};margin-right:6px;"></span>{metric_a.label} only</div>
      <div><span style="display:inline-block;width:12px;height:12px;background:{colors[f'{metric_b.label} only']};margin-right:6px;"></span>{metric_b.label} only</div>
      <div><span style="display:inline-block;width:12px;height:12px;background:{colors['Neither condition']};margin-right:6px;"></span>Neither condition</div>
      <hr style="border:none;border-top:1px solid #e5e7eb;margin:8px 0;">
      <div>{condition_label(metric_a, condition_a, threshold_a)}</div>
      <div>{condition_label(metric_b, condition_b, threshold_b)}</div>
    </div>
    """
    folium.Marker([min_lat, min_lon], icon=folium.DivIcon(html=legend_html)).add_to(m)
    if show_commission_districts:
        add_commission_district_overlay(m)
    return m


def intersection_table(
    gdf: gpd.GeoDataFrame,
    metric_a: IntersectionMetric,
    condition_a: str,
    metric_b: IntersectionMetric,
    condition_b: str,
) -> pd.DataFrame:
    mask_a, _threshold_a = quartile_mask(gdf, metric_a, condition_a)
    mask_b, _threshold_b = quartile_mask(gdf, metric_b, condition_b)
    priority_scores = intersection_priority_score(gdf, metric_a, condition_a, metric_b, condition_b)
    matches = gdf[mask_a & mask_b].copy()
    if matches.empty:
        return pd.DataFrame(columns=["Rank", "Area", "Census tract", "GEOID", metric_a.label, metric_b.label, "Priority score"])

    matches["Priority score"] = priority_scores.loc[matches.index]
    matches = matches.sort_values("Priority score", ascending=False).reset_index(drop=True)
    matches.insert(0, "Rank", matches.index + 1)
    table = matches[["Rank", "area_label", "NAME", "GEOID", metric_a.column, metric_b.column, "Priority score"]].copy()
    table.rename(
        columns={
            "area_label": "Area",
            "NAME": "Census tract",
            metric_a.column: metric_a.label,
            metric_b.column: metric_b.label,
        },
        inplace=True,
    )
    table[metric_a.label] = table[metric_a.label].map(lambda value: format_intersection_value(value, metric_a))
    table[metric_b.label] = table[metric_b.label].map(lambda value: format_intersection_value(value, metric_b))
    table["Priority score"] = table["Priority score"].map(lambda value: f"{value:.1f}")
    return table


def inject_css() -> None:
    st.markdown(
        """
        <style>
        .block-container { padding-top: 1.4rem; padding-bottom: 2rem; }
        [data-testid="stMetric"] {
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 0.75rem 0.9rem;
        }
        [data-testid="stMetricValue"] { font-size: 1.35rem; }
        .layer-note {
            border-left: 4px solid #2563eb;
            background: #f8fafc;
            padding: 0.8rem 1rem;
            margin: 0.4rem 0 1rem 0;
        }
        .small-muted { color: #64748b; font-size: 0.92rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_explore(gdf: gpd.GeoDataFrame) -> None:
    st.sidebar.header("Map Controls")
    show_commission_districts = st.sidebar.checkbox("Show County Commission districts", value=False)
    layer_key = st.sidebar.selectbox(
        "Layer",
        options=list(LAYERS.keys()),
        format_func=lambda key: LAYERS[key].label,
    )
    layer = LAYERS[layer_key]

    if layer.key == "overall":
        value_mode = "score"
        st.sidebar.caption("Overall opportunity is already a composite score.")
    else:
        value_mode = st.sidebar.radio(
            "Values",
            options=["score", "raw"],
            format_func=lambda value: "Comparable score (0-100)" if value == "score" else "Original measure",
        )

    plot_gdf, map_col, legend_name, unit = prepare_layer_data(gdf, layer, value_mode)
    if plot_gdf is None or plot_gdf.empty:
        st.warning(f"No usable data are available for {layer.label}.")
        return

    palette = layer.palette_score if value_mode == "score" else layer.palette_raw
    if value_mode == "raw" and layer.raw_direction == "higher_better":
        palette = "YlGnBu_09"

    st.subheader(layer.label)
    st.markdown(
        f"<div class='layer-note'><strong>{layer.score_meaning if value_mode == 'score' else layer.raw_label}</strong><br>"
        f"<span class='small-muted'>{layer.why_it_matters} {format_delta(layer, value_mode)}</span></div>",
        unsafe_allow_html=True,
    )

    metric_summary(plot_gdf, map_col, unit, layer, value_mode)

    left, right = st.columns([2.25, 1], gap="large")
    with left:
        m = build_map(plot_gdf, map_col, legend_name, palette, show_commission_districts)
        st_folium(m, use_container_width=True, height=650, returned_objects=[])

    with right:
        st.markdown("**Priority Tracts**")
        if value_mode == "score":
            sort_mode = "lowest"
            caption = "Lowest scores may need the most attention."
        elif layer.raw_direction == "higher_worse":
            sort_mode = "highest"
            caption = "Highest raw values may indicate more pressure."
        else:
            sort_mode = "lowest"
            caption = "Lowest raw values may indicate less access."

        top = ranking_table(plot_gdf, map_col, legend_name, unit, sort_mode).head(12)
        st.dataframe(top, hide_index=True, use_container_width=True)
        st.caption(caption)

        st.markdown("**Layer Details**")
        st.write(layer.why_it_matters)
        st.write(format_delta(layer, value_mode))


def render_priorities(gdf: gpd.GeoDataFrame) -> None:
    st.subheader("Priority List")
    st.write("Use this view to find tracts that rank lowest on the overall score or highest on a specific pressure measure.")

    list_mode = st.radio(
        "Rank by",
        options=["Overall score", "Eviction pressure", "Housing cost pressure", "Poverty", "Uninsured rate", "Hospital distance"],
        horizontal=True,
    )
    mode_map = {
        "Overall score": ("uoi_score", "Overall score", "score", "lowest"),
        "Eviction pressure": ("eviction_risk_score", "Eviction pressure", "score", "highest"),
        "Housing cost pressure": ("pct_rent_burdened", "High housing costs", "percent", "highest"),
        "Poverty": ("pct_poverty", "Poverty", "percent", "highest"),
        "Uninsured rate": ("pct_uninsured", "Uninsured", "percent", "highest"),
        "Hospital distance": ("hospital_distance_mi", "Miles to nearest hospital", "miles", "highest"),
    }
    source_col, label, unit, sort_mode = mode_map[list_mode]
    plot_gdf = gdf[~gdf[source_col].isna()].copy()
    plot_gdf, map_col = add_display_column(plot_gdf, source_col)
    table = ranking_table(plot_gdf, map_col, label, unit, sort_mode)
    st.dataframe(table.head(35), hide_index=True, use_container_width=True)


def render_intersection(gdf: gpd.GeoDataFrame) -> None:
    st.subheader("Intersection View")
    st.write(
        "Find tracts that meet two conditions at once, such as low income and long hospital distance. "
        "This is meant for intervention targeting, not just describing one variable at a time."
    )

    metric_keys = list(INTERSECTION_METRICS.keys())
    condition_options = {
        "bottom": "Bottom quartile",
        "top": "Top quartile",
    }

    c1, c2, c3, c4 = st.columns([1.35, 1, 1.35, 1])
    with c1:
        metric_a_key = st.selectbox(
            "First indicator",
            options=metric_keys,
            index=metric_keys.index("income"),
            format_func=lambda key: INTERSECTION_METRICS[key].label,
        )
    with c2:
        condition_a = st.selectbox(
            "First condition",
            options=list(condition_options.keys()),
            index=0,
            format_func=lambda key: condition_options[key],
        )
    with c3:
        metric_b_key = st.selectbox(
            "Second indicator",
            options=metric_keys,
            index=metric_keys.index("hospital"),
            format_func=lambda key: INTERSECTION_METRICS[key].label,
        )
    with c4:
        condition_b = st.selectbox(
            "Second condition",
            options=list(condition_options.keys()),
            index=1,
            format_func=lambda key: condition_options[key],
        )

    if metric_a_key == metric_b_key:
        st.warning("Pick two different indicators for an intersection view.")
        return

    show_commission_districts = st.checkbox("Show County Commission districts", value=False)

    metric_a = INTERSECTION_METRICS[metric_a_key]
    metric_b = INTERSECTION_METRICS[metric_b_key]
    missing_cols = [metric.column for metric in (metric_a, metric_b) if metric.column not in gdf.columns]
    if missing_cols:
        st.warning(f"Missing required column(s): {', '.join(missing_cols)}")
        return

    mask_a, threshold_a = quartile_mask(gdf, metric_a, condition_a)
    mask_b, threshold_b = quartile_mask(gdf, metric_b, condition_b)
    both = mask_a & mask_b
    valid_count = gdf[[metric_a.column, metric_b.column]].dropna().shape[0]

    st.markdown(
        f"<div class='layer-note'><strong>{condition_label(metric_a, condition_a, threshold_a)}</strong><br>"
        f"<strong>{condition_label(metric_b, condition_b, threshold_b)}</strong><br>"
        f"<span class='small-muted'>Highlighted tracts meet both conditions. Blue/orange tracts meet only one.</span></div>",
        unsafe_allow_html=True,
    )

    m1, m2, m3 = st.columns(3)
    m1.metric("Matched tracts", f"{int(both.sum())}")
    m2.metric("Share of valid tracts", f"{(both.sum() / valid_count * 100 if valid_count else 0):.1f}%")
    m3.metric("Valid tracts compared", f"{valid_count}")

    left, right = st.columns([2.1, 1], gap="large")
    with left:
        m = build_intersection_map(gdf, metric_a, condition_a, metric_b, condition_b, show_commission_districts)
        st_folium(m, use_container_width=True, height=650, returned_objects=[])

    with right:
        st.markdown("**Tracts Meeting Both Conditions**")
        table = intersection_table(gdf, metric_a, condition_a, metric_b, condition_b)
        if table.empty:
            st.info("No tracts match both selected conditions.")
        else:
            st.dataframe(table.head(25), hide_index=True, use_container_width=True)
        st.caption(
            "Priority score combines how extreme each tract is on the two selected indicators. "
            "It is a sorting aid, not a separate index."
        )


def render_methods(gdf: gpd.GeoDataFrame) -> None:
    st.subheader("Methods")
    st.write(
        f"This app uses tract-level public data from the U.S. Census Bureau ACS {ACS_YEAR} 5-year release "
        "and Census TIGER tract geometry for Bernalillo County."
    )

    components = pd.DataFrame(METHOD_COMPONENTS, columns=["Factor", "Measure", "Scoring direction"])
    st.dataframe(components, hide_index=True, use_container_width=True)

    st.markdown("**Overall score**")
    st.write(
        "Each factor is normalized across Bernalillo County tracts. Positive-access measures keep their direction; "
        "hardship and distance measures are inverted. The overall score averages the available normalized factors. Scores shown "
        "in the app are multiplied by 100 for readability."
    )

    st.markdown("**Eviction pressure proxy**")
    st.write("Eviction pressure averages normalized rent burden, poverty, SNAP reliance, and unemployment.")

    st.markdown("**Hospital distance**")
    st.write(
        "Hospital access uses the latest year available in data/hospital_distances.csv. The raw value is miles "
        "from each tract to the nearest hospital; the score reverses that distance so closer tracts score higher. "
        "Thanks to Luke Hudgins of UT Austin for the hospital distance data!"
    )

    st.markdown("**Intersection view**")
    st.write(
        "The intersection view uses raw indicator values and county quartiles. For example, bottom-quartile income "
        "and top-quartile hospital distance highlights tracts that are simultaneously lower-income and farther from hospitals."
    )

    st.markdown("**Area labels**")
    st.write(
        "Area names use the official City of Albuquerque neighborhood association boundary with the largest "
        "overlap for each tract. Tracts outside that layer receive a broader regional Bernalillo County label."
    )

    st.markdown("**County Commission districts**")
    st.write(
        "The optional commission district overlay comes from the Bernalillo County Commission Districts GIS layer "
        "and is drawn as dashed boundary lines over the tract map."
    )

    missing = gdf[[layer.raw_col for layer in LAYERS.values() if layer.raw_col in gdf.columns]].isna().sum()
    missing = missing[missing > 0].rename("Missing tracts").reset_index().rename(columns={"index": "Column"})
    if not missing.empty:
        st.markdown("**Missing data**")
        st.dataframe(missing, hide_index=True, use_container_width=True)


def main() -> None:
    st.set_page_config(page_title="Bernalillo County Opportunity Map", layout="wide")
    inject_css()

    st.title("Bernalillo County Opportunity Map")
    st.caption("A tract-level view of access, hardship, and stability indicators for service planning.")

    gdf = load_data()

    tabs = st.tabs(["Explore Map", "Intersection View", "Priority List", "Methods"])
    with tabs[0]:
        render_explore(gdf)
    with tabs[1]:
        render_intersection(gdf)
    with tabs[2]:
        render_priorities(gdf)
    with tabs[3]:
        render_methods(gdf)


if __name__ == "__main__":
    main()
