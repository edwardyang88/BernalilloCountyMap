"""
Bernalillo County Eviction Watch.

Run with:
    streamlit run eviction_watch.py
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import folium
import geopandas as gpd
import pandas as pd
import streamlit as st
from branca.colormap import linear
from streamlit_folium import st_folium

from ui import DATA_GPKG, DATA_LAYER, add_area_labels

EVLAB_DIR = "data/eviction_lab"
ALBUQUERQUE_WEEKLY = os.path.join(EVLAB_DIR, "albuquerque_weekly.csv")
NEW_MEXICO_WEEKLY = os.path.join(EVLAB_DIR, "new_mexico_weekly.csv")
RENTER_HOUSEHOLDS = os.path.join(EVLAB_DIR, "acs_2022_renter_households.csv")
OUTPUT_GPKG = os.path.join("outputs", "eviction_watch_tracts.gpkg")
OUTPUT_CSV = os.path.join("outputs", "eviction_watch_tracts.csv")


@dataclass(frozen=True)
class MetricConfig:
    key: str
    label: str
    column: str
    unit: str
    palette: str
    high_is_bad: bool = True


METRICS = {
    "rate12": MetricConfig(
        key="rate12",
        label="Last 12 months: filings per 1,000 renter households",
        column="filing_rate_12mo_per_1000",
        unit="rate",
        palette="YlOrRd_09",
    ),
    "rate90": MetricConfig(
        key="rate90",
        label="Last 90 days: filings per 1,000 renter households",
        column="filing_rate_90d_per_1000",
        unit="rate",
        palette="YlOrRd_09",
    ),
    "yoy": MetricConfig(
        key="yoy",
        label="Year-over-year change in filings",
        column="yoy_change_pct",
        unit="percent_change",
        palette="YlOrRd_09",
    ),
    "pressure": MetricConfig(
        key="pressure",
        label="Existing eviction pressure prior",
        column="eviction_pressure_prior_0_100",
        unit="score",
        palette="PuRd_09",
    ),
}

CATEGORY_COLORS = {
    "High filings + high pressure": "#991b1b",
    "High pressure + low filings": "#7c3aed",
    "Low pressure + high filings": "#d97706",
    "Spiking YoY": "#dc2626",
    "Mixed / monitor": "#64748b",
    "Lower current concern": "#0f766e",
}


@st.cache_data(show_spinner=True)
def load_eviction_watch_data() -> tuple[gpd.GeoDataFrame, dict]:
    base = add_area_labels(gpd.read_file(DATA_GPKG, layer=DATA_LAYER))
    weekly = pd.read_csv(ALBUQUERQUE_WEEKLY, dtype={"GEOID": str})
    renters = pd.read_csv(RENTER_HOUSEHOLDS, dtype={"GEOID": str})
    nm_weekly = pd.read_csv(NEW_MEXICO_WEEKLY, dtype={"GEOID": str}) if os.path.exists(NEW_MEXICO_WEEKLY) else None

    weekly = clean_weekly(weekly)
    nm_weekly = clean_weekly(nm_weekly) if nm_weekly is not None else None

    max_date = weekly["week_date"].max()
    last_update = weekly["last_updated"].dropna().astype(str).max() if weekly["last_updated"].notna().any() else None

    summary = summarize_filings(weekly, max_date)
    if nm_weekly is not None:
        nm_summary = summarize_totals(nm_weekly, max_date)
    else:
        nm_summary = {"nm_filings_12mo": pd.NA, "nm_filings_90d": pd.NA}

    gdf = base.merge(renters, on="GEOID", how="left").merge(summary, on="GEOID", how="left")
    for col in ["filings_12mo", "filings_prev_12mo", "filings_90d", "baseline_12mo"]:
        gdf[col] = pd.to_numeric(gdf[col], errors="coerce").fillna(0)

    gdf["renter_households"] = pd.to_numeric(gdf["renter_households"], errors="coerce")
    gdf["filing_rate_12mo_per_1000"] = safe_rate(gdf["filings_12mo"], gdf["renter_households"])
    gdf["filing_rate_90d_per_1000"] = safe_rate(gdf["filings_90d"], gdf["renter_households"])
    gdf["yoy_change_pct"] = pct_change(gdf["filings_12mo"], gdf["filings_prev_12mo"])
    gdf["baseline_gap_pct"] = pct_change(gdf["filings_12mo"], gdf["baseline_12mo"])
    gdf["eviction_pressure_prior_0_100"] = pd.to_numeric(gdf["eviction_risk_score"], errors="coerce") * 100
    gdf["watch_type"] = classify_tracts(gdf)
    gdf["epp_dollars"] = pd.NA
    gdf["top_filer"] = pd.NA

    try:
        os.makedirs("outputs", exist_ok=True)
        gdf.to_file(OUTPUT_GPKG, layer="tracts", driver="GPKG")
        non_geom_cols = [c for c in gdf.columns if c != "geometry"]
        gdf[non_geom_cols].to_csv(OUTPUT_CSV, index=False)
    except Exception as exc:
        print(f"Could not write eviction watch export files: {exc}")

    meta = {
        "max_week": max_date.date().isoformat(),
        "last_updated": last_update,
        "bern_filings_12mo": int(gdf["filings_12mo"].sum()),
        "bern_filings_90d": int(gdf["filings_90d"].sum()),
        "nm_filings_12mo": int(nm_summary["nm_filings_12mo"]) if pd.notna(nm_summary["nm_filings_12mo"]) else None,
        "nm_filings_90d": int(nm_summary["nm_filings_90d"]) if pd.notna(nm_summary["nm_filings_90d"]) else None,
    }
    return gdf, meta


def clean_weekly(df: pd.DataFrame) -> pd.DataFrame:
    clean = df.copy()
    clean = clean[clean["GEOID"].astype(str).str.fullmatch(r"\d+")].copy()
    clean["GEOID"] = clean["GEOID"].astype(str)
    clean["week_date"] = pd.to_datetime(clean["week_date"], errors="coerce")
    clean["filings_2020"] = pd.to_numeric(clean["filings_2020"], errors="coerce").fillna(0)
    clean["filings_avg"] = pd.to_numeric(clean["filings_avg"], errors="coerce")
    clean = clean.dropna(subset=["week_date"])
    return clean


def summarize_filings(weekly: pd.DataFrame, max_date: pd.Timestamp) -> pd.DataFrame:
    start_12 = max_date - pd.Timedelta(days=365)
    start_prev = start_12 - pd.Timedelta(days=365)
    start_90 = max_date - pd.Timedelta(days=90)

    last12 = period_sum(weekly, start_12, max_date, "filings_12mo")
    prev12 = period_sum(weekly, start_prev, start_12, "filings_prev_12mo")
    last90 = period_sum(weekly, start_90, max_date, "filings_90d")
    baseline = baseline_sum(weekly, start_12, max_date, "baseline_12mo")

    return last12.merge(prev12, on="GEOID", how="outer").merge(last90, on="GEOID", how="outer").merge(baseline, on="GEOID", how="outer")


def summarize_totals(weekly: pd.DataFrame, max_date: pd.Timestamp) -> dict:
    start_12 = max_date - pd.Timedelta(days=365)
    start_90 = max_date - pd.Timedelta(days=90)
    return {
        "nm_filings_12mo": weekly[(weekly["week_date"] > start_12) & (weekly["week_date"] <= max_date)]["filings_2020"].sum(),
        "nm_filings_90d": weekly[(weekly["week_date"] > start_90) & (weekly["week_date"] <= max_date)]["filings_2020"].sum(),
    }


def period_sum(weekly: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, out_col: str) -> pd.DataFrame:
    period = weekly[(weekly["week_date"] > start) & (weekly["week_date"] <= end)]
    return period.groupby("GEOID", as_index=False)["filings_2020"].sum().rename(columns={"filings_2020": out_col})


def baseline_sum(weekly: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, out_col: str) -> pd.DataFrame:
    period = weekly[(weekly["week_date"] > start) & (weekly["week_date"] <= end)]
    return period.groupby("GEOID", as_index=False)["filings_avg"].sum().rename(columns={"filings_avg": out_col})


def safe_rate(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    denominator = pd.to_numeric(denominator, errors="coerce")
    return pd.to_numeric(numerator, errors="coerce").div(denominator.where(denominator > 0)).mul(1000)


def pct_change(current: pd.Series, previous: pd.Series) -> pd.Series:
    current = pd.to_numeric(current, errors="coerce")
    previous = pd.to_numeric(previous, errors="coerce")
    return current.sub(previous).div(previous.where(previous > 0)).mul(100)


def classify_tracts(gdf: gpd.GeoDataFrame) -> pd.Series:
    rate = gdf["filing_rate_12mo_per_1000"]
    pressure = gdf["eviction_pressure_prior_0_100"]
    yoy = gdf["yoy_change_pct"]

    high_rate = rate >= rate.quantile(0.75)
    low_rate = rate <= rate.quantile(0.50)
    high_pressure = pressure >= pressure.quantile(0.75)
    low_pressure = pressure <= pressure.quantile(0.50)
    spiking = (yoy >= 25) & (gdf["filings_12mo"] >= 10)

    label = pd.Series("Mixed / monitor", index=gdf.index)
    label.loc[(low_rate) & (low_pressure)] = "Lower current concern"
    label.loc[(high_pressure) & (low_rate)] = "High pressure + low filings"
    label.loc[(low_pressure) & (high_rate)] = "Low pressure + high filings"
    label.loc[(high_pressure) & (high_rate)] = "High filings + high pressure"
    label.loc[spiking] = "Spiking YoY"
    return label


def fmt(value, unit: str) -> str:
    if pd.isna(value):
        return "n/a"
    value = float(value)
    if unit == "rate":
        return f"{value:.1f} / 1k"
    if unit == "percent_change":
        return f"{value:+.0f}%"
    if unit == "score":
        return f"{value:.0f}"
    if unit == "currency":
        return f"${value:,.0f}"
    return f"{value:,.0f}"


def make_numeric_map(gdf: gpd.GeoDataFrame, metric: MetricConfig) -> folium.Map:
    gdf = gdf.to_crs("EPSG:4326") if gdf.crs and gdf.crs.to_string() != "EPSG:4326" else gdf.copy()
    values = pd.to_numeric(gdf[metric.column], errors="coerce")
    clean = values.dropna()
    q_low = clean.quantile(0.05) if not clean.empty else 0
    q_high = clean.quantile(0.95) if not clean.empty else 1
    if q_low == q_high:
        q_high = q_low + 1
    colormap = getattr(linear, metric.palette).scale(q_low, q_high).to_step(7)
    colormap.caption = metric.label

    min_lon, min_lat, max_lon, max_lat = gdf.total_bounds
    m = folium.Map(location=[(min_lat + max_lat) / 2, (min_lon + max_lon) / 2], tiles="CartoDB positron", zoom_start=11, control_scale=True)
    m.fit_bounds([[min_lat, min_lon], [max_lat, max_lon]])

    def style(feature):
        value = feature["properties"].get(metric.column)
        if value is None or pd.isna(value):
            return {"fillColor": "#d1d5db", "color": "#334155", "weight": 0.55, "fillOpacity": 0.25}
        return {"fillColor": colormap(value), "color": "#334155", "weight": 0.55, "fillOpacity": 0.82}

    tooltip_fields = ["tract_label", "filings_12mo", "filing_rate_12mo_per_1000", "filings_90d", "yoy_change_pct", "watch_type"]
    tooltip_aliases = ["Area", "12-mo filings", "12-mo filings / 1k renters", "90-day filings", "YoY", "Watch type"]
    display = gdf.copy()
    display["filing_rate_12mo_per_1000"] = display["filing_rate_12mo_per_1000"].map(lambda x: fmt(x, "rate"))
    display["yoy_change_pct"] = display["yoy_change_pct"].map(lambda x: fmt(x, "percent_change"))
    folium.GeoJson(
        display.to_json(),
        style_function=style,
        highlight_function=lambda _: {"weight": 2, "color": "#111827", "fillOpacity": 0.9},
        tooltip=folium.features.GeoJsonTooltip(fields=tooltip_fields, aliases=tooltip_aliases, sticky=False),
    ).add_to(m)
    colormap.add_to(m)
    return m


def make_category_map(gdf: gpd.GeoDataFrame) -> folium.Map:
    gdf = gdf.to_crs("EPSG:4326") if gdf.crs and gdf.crs.to_string() != "EPSG:4326" else gdf.copy()
    min_lon, min_lat, max_lon, max_lat = gdf.total_bounds
    m = folium.Map(location=[(min_lat + max_lat) / 2, (min_lon + max_lon) / 2], tiles="CartoDB positron", zoom_start=11, control_scale=True)
    m.fit_bounds([[min_lat, min_lon], [max_lat, max_lon]])

    def style(feature):
        label = feature["properties"].get("watch_type") or "Mixed / monitor"
        return {"fillColor": CATEGORY_COLORS.get(label, "#64748b"), "color": "#334155", "weight": 0.55, "fillOpacity": 0.82}

    display = gdf.copy()
    display["filing_rate_12mo_per_1000"] = display["filing_rate_12mo_per_1000"].map(lambda x: fmt(x, "rate"))
    display["yoy_change_pct"] = display["yoy_change_pct"].map(lambda x: fmt(x, "percent_change"))
    folium.GeoJson(
        display.to_json(),
        style_function=style,
        highlight_function=lambda _: {"weight": 2, "color": "#111827", "fillOpacity": 0.9},
        tooltip=folium.features.GeoJsonTooltip(
            fields=["tract_label", "watch_type", "filings_12mo", "filing_rate_12mo_per_1000", "yoy_change_pct"],
            aliases=["Area", "Watch type", "12-mo filings", "12-mo rate", "YoY"],
            sticky=False,
        ),
    ).add_to(m)
    legend = "".join(f'<div><span style="display:inline-block;width:12px;height:12px;background:{color};margin-right:6px"></span>{label}</div>' for label, color in CATEGORY_COLORS.items())
    folium.Marker(
        [min_lat, min_lon],
        icon=folium.DivIcon(html=f'<div style="background:white;border:1px solid #cbd5e1;padding:8px;width:250px;font-size:12px"><b>Watch categories</b>{legend}</div>'),
    ).add_to(m)
    return m


def hotspots_table(gdf: gpd.GeoDataFrame, sort_column: str) -> pd.DataFrame:
    table = gdf[[
        "area_label",
        "NAME",
        "GEOID",
        "filings_12mo",
        "filing_rate_12mo_per_1000",
        "filings_90d",
        "yoy_change_pct",
        "eviction_pressure_prior_0_100",
        "watch_type",
        "epp_dollars",
        "top_filer",
    ]].copy()
    table = table.sort_values(sort_column, ascending=False).head(20)
    table.rename(columns={
        "area_label": "Area",
        "NAME": "Tract",
        "filings_12mo": "12-mo filings",
        "filing_rate_12mo_per_1000": "Filings / 1k renters",
        "filings_90d": "90-day filings",
        "yoy_change_pct": "YoY change",
        "eviction_pressure_prior_0_100": "Pressure prior",
        "watch_type": "Watch type",
        "epp_dollars": "EPP dollars",
        "top_filer": "Top filer",
    }, inplace=True)
    table["Filings / 1k renters"] = table["Filings / 1k renters"].map(lambda x: fmt(x, "rate"))
    table["YoY change"] = table["YoY change"].map(lambda x: fmt(x, "percent_change"))
    table["Pressure prior"] = table["Pressure prior"].map(lambda x: fmt(x, "score"))
    table["EPP dollars"] = "not loaded"
    table["Top filer"] = "needs docket data"
    return table


def inject_css():
    st.markdown(
        """
        <style>
        .block-container { padding-top: 1.4rem; padding-bottom: 2rem; }
        [data-testid="stMetric"] { background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:.75rem .9rem; }
        [data-testid="stMetricValue"] { font-size:1.35rem; }
        .watch-note { border-left:4px solid #b91c1c; background:#fff7ed; padding:.8rem 1rem; margin:.5rem 0 1rem 0; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main():
    st.set_page_config(page_title="Bernalillo County Eviction Watch", layout="wide")
    inject_css()
    st.title("Bernalillo County Eviction Watch")
    st.caption("Current tract-level eviction filing signal from Eviction Lab aggregate data, joined to local pressure indicators.")

    gdf, meta = load_eviction_watch_data()

    st.markdown(
        "<div class='watch-note'><strong>Use this as an intervention-targeting map, not tenant prediction.</strong> "
        "All outputs are tract-level. EPP dollars and top-filer columns are placeholders until those data sources are obtained.</div>",
        unsafe_allow_html=True,
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("12-mo filings", f"{meta['bern_filings_12mo']:,}")
    c2.metric("90-day filings", f"{meta['bern_filings_90d']:,}")
    if meta["nm_filings_12mo"]:
        share = meta["bern_filings_12mo"] / meta["nm_filings_12mo"] * 100
        c3.metric("BernCo share of NM", f"{share:.1f}%")
    else:
        c3.metric("BernCo share of NM", "n/a")
    c4.metric("Data current through", meta["max_week"])

    metric_key = st.sidebar.selectbox(
        "Map view",
        options=["rate12", "rate90", "yoy", "pressure", "category"],
        format_func=lambda key: "Pressure vs filings categories" if key == "category" else METRICS[key].label,
    )

    left, right = st.columns([2.2, 1], gap="large")
    with left:
        if metric_key == "category":
            m = make_category_map(gdf)
        else:
            m = make_numeric_map(gdf, METRICS[metric_key])
        st_folium(m, use_container_width=True, height=650, returned_objects=[])

    sort_column = "filing_rate_12mo_per_1000" if metric_key in {"rate12", "category"} else METRICS.get(metric_key, METRICS["rate12"]).column
    with right:
        st.subheader("Hotspots")
        st.dataframe(hotspots_table(gdf, sort_column), hide_index=True, use_container_width=True)
        st.caption("Top filer and EPP dollar fields require docket-level filings and program spending data; this public aggregate source does not include them.")

    with st.expander("Methods and source notes"):
        st.write(
            "Filings come from Eviction Lab's Eviction Tracking System Albuquerque weekly tract CSV. "
            "The file is current to May 2026 and uses 2020 census tract boundaries. Renter households come from ACS 2022 table B25003. "
            "The pressure prior is the existing local proxy: rent burden, poverty, SNAP reliance, and unemployment."
        )
        st.write(
            "Watch categories compare each tract's filing rate to its pressure prior. High-pressure/low-filing tracts may indicate under-service "
            "or informal displacement; low-pressure/high-filing tracts may indicate concentrated filing behavior. These are hypotheses for outreach, not findings about tenants."
        )
        st.write(f"Last Eviction Lab update field: {meta['last_updated'] or 'not reported'}")
        st.write(f"Saved joined data to `{OUTPUT_CSV}` and `{OUTPUT_GPKG}`.")


if __name__ == "__main__":
    main()
