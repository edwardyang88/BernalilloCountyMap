"""
Bernalillo County Opportunity Index: enrichment step.

Runs after bern_uoi_pipeline.py and adds what the ACS indicators alone can't tell you:

1. Measured eviction filings (Eviction Lab, Eviction Tracking System), last 52 complete
   weeks, as a rate per 100 renter households, plus how that compares to the tract's
   pre-pandemic baseline.
2. Spatial clustering of the index (global Moran's I and Local Moran's I / LISA,
   queen contiguity, 999 conditional permutations) to separate real geographic
   clusters of low opportunity from one-off tracts.
3. County rank, percentile, and commission district for each tract.
4. A validation check: does the index (built only from ACS inputs) line up with an
   outcome it never saw, the eviction filing rate?

Writes:
    data/tracts.json                         (web app GeoJSON, new fields added)
    data/summary.json                        (headline numbers the site displays)
    data/bernalillo_opportunity_index.csv    (clean public download)

Needs only numpy + pandas. Run with:  python bern_enrich.py
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import date, timedelta

import numpy as np
import pandas as pd

DATA_DIR = "data"
TRACTS_PATH = os.path.join(DATA_DIR, "tracts.json")
DISTRICTS_PATH = os.path.join(DATA_DIR, "commission_districts.json")
EVLAB_WEEKLY = os.path.join(DATA_DIR, "eviction_lab", "albuquerque_weekly.csv")
RENTERS_CSV = os.path.join(DATA_DIR, "eviction_lab", "acs_2022_renter_households.csv")
SUMMARY_PATH = os.path.join(DATA_DIR, "summary.json")
DOWNLOAD_CSV = os.path.join(DATA_DIR, "bernalillo_opportunity_index.csv")

WINDOW_WEEKS = 52
MIN_RENTERS_FOR_RATE = 50       # below this a filing rate is too noisy to show
PERMUTATIONS = 999
ALPHA = 0.05
SEED = 20221


# ---------------------------------------------------------------------------
# Geometry helpers (pure python; TIGER tracts share exact vertices)
# ---------------------------------------------------------------------------

def rings(geom):
    if geom["type"] == "Polygon":
        return geom["coordinates"]
    if geom["type"] == "MultiPolygon":
        return [r for poly in geom["coordinates"] for r in poly]
    return []


def outer_rings(geom):
    if geom["type"] == "Polygon":
        return [geom["coordinates"][0]]
    return [poly[0] for poly in geom["coordinates"]]


def queen_neighbors(features, ndigits=6):
    """Tracts are neighbors if they share at least one boundary vertex."""
    vertex_owners = defaultdict(set)
    for i, f in enumerate(features):
        for ring in rings(f["geometry"]):
            for x, y in ring:
                vertex_owners[(round(x, ndigits), round(y, ndigits))].add(i)
    nbrs = [set() for _ in features]
    for owners in vertex_owners.values():
        if len(owners) > 1:
            for i in owners:
                nbrs[i] |= owners - {i}
    return [sorted(n) for n in nbrs]


def ring_area_centroid(ring):
    a = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(ring, ring[1:]):
        c = x0 * y1 - x1 * y0
        a += c
        cx += (x0 + x1) * c
        cy += (y0 + y1) * c
    a *= 0.5
    if a == 0:
        return 0.0, ring[0][0], ring[0][1]
    return a, cx / (6 * a), cy / (6 * a)


def point_in_ring(x, y, ring):
    inside = False
    for (x0, y0), (x1, y1) in zip(ring, ring[1:]):
        if (y0 > y) != (y1 > y):
            if x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
                inside = not inside
    return inside


def point_in_geom(x, y, geom):
    polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    for poly in polys:
        if point_in_ring(x, y, poly[0]) and not any(point_in_ring(x, y, h) for h in poly[1:]):
            return True
    return False


def interior_point(geom):
    """Centroid of the largest ring, nudged inside if the shape is concave."""
    ring = max(outer_rings(geom), key=lambda r: abs(ring_area_centroid(r)[0]))
    _, cx, cy = ring_area_centroid(ring)
    if point_in_geom(cx, cy, geom):
        return cx, cy
    # fall back: midpoint between the centroid and the nearest vertex, then the vertex average
    xs, ys = zip(*ring)
    for t in (0.5, 0.75, 0.9):
        for vx, vy in sorted(ring, key=lambda v: (v[0] - cx) ** 2 + (v[1] - cy) ** 2)[:20]:
            px, py = cx + (vx - cx) * t, cy + (vy - cy) * t
            if point_in_geom(px, py, geom):
                return px, py
    return sum(xs) / len(xs), sum(ys) / len(ys)


# ---------------------------------------------------------------------------
# Spatial statistics
# ---------------------------------------------------------------------------

def row_standardized(nbrs):
    return [np.full(len(n), 1.0 / len(n)) if n else np.array([]) for n in nbrs]


def global_morans_i(z, nbrs, weights, perms, rng):
    n = len(z)
    s0 = sum(w.sum() for w in weights)

    def stat(v):
        lag = np.array([(w * v[nb]).sum() if len(nb) else 0.0 for nb, w in zip(nbrs, weights)])
        return (n / s0) * (v * lag).sum() / (v * v).sum()

    observed = stat(z)
    sims = np.array([stat(rng.permutation(z)) for _ in range(perms)])
    larger = (np.abs(sims) >= abs(observed)).sum()
    return float(observed), float((larger + 1) / (perms + 1))


def local_morans(z, nbrs, weights, perms, rng):
    """Local Moran's I with conditional randomization (pysal/esda's approach)."""
    n = len(z)
    m2 = (z * z).sum() / n
    lag = np.array([(w * z[nb]).sum() if len(nb) else 0.0 for nb, w in zip(nbrs, weights)])
    Ii = z * lag / m2
    p = np.ones(n)
    idx = np.arange(n)
    for i in range(n):
        k = len(nbrs[i])
        if k == 0:
            continue
        others = np.delete(idx, i)
        draws = np.array([rng.choice(others, size=k, replace=False) for _ in range(perms)])
        sim_lag = (z[draws] * weights[i]).sum(axis=1)
        sim_I = z[i] * sim_lag / m2
        if Ii[i] >= 0:
            larger = (sim_I >= Ii[i]).sum()
        else:
            larger = (sim_I <= Ii[i]).sum()
        p[i] = (larger + 1) / (perms + 1)
    return Ii, lag, p


def spearman(a, b):
    a = pd.Series(a).rank().to_numpy()
    b = pd.Series(b).rank().to_numpy()
    return float(np.corrcoef(a, b)[0, 1])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def eviction_filings(geoids):
    w = pd.read_csv(EVLAB_WEEKLY, dtype={"GEOID": str}, low_memory=False)
    w["week_date"] = pd.to_datetime(w["week_date"])
    sealed = int(w.loc[w["GEOID"] == "sealed", "filings_2020"].sum())
    w = w[w["GEOID"] != "sealed"]

    # The most recent week in an ETS release is usually incomplete; drop it.
    weekly_totals = w.groupby("week_date")["filings_2020"].sum()
    last_week = weekly_totals.index.max()
    if weekly_totals[last_week] < 0.25 * weekly_totals.tail(9).head(8).median():
        last_week = last_week - pd.Timedelta(days=7)
    first_week = last_week - pd.Timedelta(days=7 * (WINDOW_WEEKS - 1))
    win = w[(w["week_date"] >= first_week) & (w["week_date"] <= last_week)]

    agg = win.groupby("GEOID").agg(
        filings_12mo=("filings_2020", "sum"),
        baseline_12mo=("filings_avg_prepandemic_baseline", "sum"),
    )
    renters = pd.read_csv(RENTERS_CSV, dtype={"GEOID": str}).set_index("GEOID")["renter_households"]
    out = pd.DataFrame(index=pd.Index(geoids, name="GEOID")).join(agg).join(renters)
    out["filings_12mo"] = out["filings_12mo"].fillna(0)
    ok = out["renter_households"] >= MIN_RENTERS_FOR_RATE
    out["eviction_filing_rate"] = np.where(ok, out["filings_12mo"] / out["renter_households"] * 100, np.nan)
    out["filings_vs_baseline"] = np.where(out["baseline_12mo"] > 5, out["filings_12mo"] / out["baseline_12mo"], np.nan)

    window = {
        "start": first_week.date().isoformat(),
        "end": (last_week + pd.Timedelta(days=6)).date().isoformat(),
        "weeks": WINDOW_WEEKS,
        "sealed_or_unlocated_filings_in_full_series": sealed,
        "county_filings_12mo": int(win["filings_2020"].sum()),
        "county_baseline_12mo": float(win.groupby("GEOID")["filings_avg_prepandemic_baseline"].sum().sum()),
    }
    return out, window


def enrich():
    with open(TRACTS_PATH) as f:
        tracts = json.load(f)
    with open(DISTRICTS_PATH) as f:
        districts = json.load(f)
    feats = tracts["features"]
    props = [f["properties"] for f in feats]
    geoids = [p["GEOID"] for p in props]
    rng = np.random.default_rng(SEED)

    # --- 1. Eviction filings ------------------------------------------------
    ev, window = eviction_filings(geoids)

    # --- 2. Rank / percentile ---------------------------------------------
    score = pd.Series([p.get("uoi_score") for p in props], dtype=float) * 100
    rank = score.rank(ascending=False, method="min")
    pct = score.rank(pct=True, method="average") * 100

    # --- 3. Clusters (LISA) -----------------------------------------------
    nbrs = queen_neighbors(feats)
    valid = score.notna().to_numpy()
    idx_valid = np.flatnonzero(valid)
    remap = {old: new for new, old in enumerate(idx_valid)}
    nbrs_v = [[remap[j] for j in nbrs[i] if j in remap] for i in idx_valid]
    weights_v = row_standardized(nbrs_v)
    x = score.to_numpy()[valid]
    z = (x - x.mean()) / x.std()
    moran_i, moran_p = global_morans_i(z, nbrs_v, weights_v, PERMUTATIONS, rng)
    Ii, lag, p_local = local_morans(z, nbrs_v, weights_v, PERMUTATIONS, rng)

    cluster = ["insufficient"] * len(feats)
    for k, i in enumerate(idx_valid):
        if not nbrs_v[k]:
            cluster[i] = "isolated"
        elif p_local[k] >= ALPHA:
            cluster[i] = "none"
        elif z[k] > 0 and lag[k] > 0:
            cluster[i] = "high_high"
        elif z[k] < 0 and lag[k] < 0:
            cluster[i] = "low_low"
        elif z[k] > 0:
            cluster[i] = "high_low"
        else:
            cluster[i] = "low_high"
    p_full = [None] * len(feats)
    for k, i in enumerate(idx_valid):
        p_full[i] = float(p_local[k])

    # --- 4. Commission district -------------------------------------------
    district_of = []
    for f in feats:
        px, py = interior_point(f["geometry"])
        hit = None
        for d in districts["features"]:
            if point_in_geom(px, py, d["geometry"]):
                hit = int(d["properties"]["District"])
                break
        district_of.append(hit)

    # --- 5. Write fields back ---------------------------------------------
    def clean(v, nd=4):
        if v is None:
            return None
        try:
            if pd.isna(v):
                return None
        except TypeError:
            pass
        return round(float(v), nd)

    for i, p in enumerate(props):
        e = ev.loc[p["GEOID"]]
        p["uoi_rank"] = None if pd.isna(rank[i]) else int(rank[i])
        p["uoi_percentile"] = clean(pct[i], 1)
        p["renter_households"] = None if pd.isna(e["renter_households"]) else int(e["renter_households"])
        p["eviction_filings_12mo"] = int(e["filings_12mo"])
        p["eviction_filing_rate"] = clean(e["eviction_filing_rate"], 2)
        p["eviction_vs_baseline"] = clean(e["filings_vs_baseline"], 2)
        p["lisa_cluster"] = cluster[i]
        p["lisa_p"] = clean(p_full[i], 3)
        p["commission_district"] = district_of[i]
        p["neighbor_count"] = len(nbrs[i])

    with open(TRACTS_PATH, "w") as f:
        json.dump(tracts, f, separators=(",", ":"))

    # --- 6. Summary + validation ------------------------------------------
    df = pd.DataFrame(props)
    df["score"] = df["uoi_score"] * 100
    both = df.dropna(subset=["score", "eviction_filing_rate"])
    rho = spearman(both["score"], both["eviction_filing_rate"])
    q = pd.qcut(both["score"], 4, labels=["q1", "q2", "q3", "q4"])
    by_q = both.groupby(q, observed=True).agg(
        tracts=("GEOID", "size"),
        filings=("eviction_filings_12mo", "sum"),
        renters=("renter_households", "sum"),
    )
    by_q["rate"] = by_q["filings"] / by_q["renters"] * 100
    low_q, high_q = by_q.loc["q1"], by_q.loc["q4"]

    # Same check for the old ACS-only eviction proxy, so the two can be compared.
    proxy_rho = spearman(both["eviction_risk_score"], both["eviction_filing_rate"]) if "eviction_risk_score" in both else None

    clusters = df["lisa_cluster"].value_counts().to_dict()
    low_low = df[df["lisa_cluster"] == "low_low"]
    low_low_areas = (
        low_low.groupby("area_label")["GEOID"].size().sort_values(ascending=False).head(5).index.tolist()
    )

    district_rows = []
    for dnum, g in df.dropna(subset=["commission_district"]).groupby("commission_district"):
        district_rows.append({
            "district": int(dnum),
            "tracts": int(len(g)),
            "mean_score": round(float(g["score"].mean()), 1),
            "bottom_quartile_tracts": int((g["uoi_percentile"] <= 25).sum()),
            "low_low_cluster_tracts": int((g["lisa_cluster"] == "low_low").sum()),
            "filings_12mo": int(g["eviction_filings_12mo"].sum()),
            "filing_rate": round(float(g["eviction_filings_12mo"].sum() / g["renter_households"].sum() * 100), 2),
        })

    total_filings = int(df["eviction_filings_12mo"].sum())
    bottom_q_share = float(df.loc[df["uoi_percentile"] <= 25, "eviction_filings_12mo"].sum() / total_filings)

    summary = {
        "generated": date.today().isoformat(),
        "tract_count": int(len(df)),
        "acs_vintage": "2018-2022 ACS 5-year",
        "score": {
            "min": round(float(df["score"].min()), 1),
            "median": round(float(df["score"].median()), 1),
            "max": round(float(df["score"].max()), 1),
        },
        "eviction": {
            **window,
            "county_rate_per_100_renters": round(float(df["eviction_filings_12mo"].sum() / df["renter_households"].sum() * 100), 2),
            "county_vs_baseline": round(window["county_filings_12mo"] / window["county_baseline_12mo"], 2) if window["county_baseline_12mo"] else None,
            "tracts_with_rate": int(both.shape[0]),
            "min_renters_for_rate": MIN_RENTERS_FOR_RATE,
        },
        "validation": {
            "spearman_index_vs_filing_rate": round(rho, 3),
            "spearman_acs_proxy_vs_filing_rate": round(proxy_rho, 3) if proxy_rho is not None else None,
            "bottom_quartile_rate": round(float(low_q["rate"]), 2),
            "top_quartile_rate": round(float(high_q["rate"]), 2),
            "bottom_vs_top_ratio": round(float(low_q["rate"] / high_q["rate"]), 1),
            "bottom_quartile_share_of_filings": round(bottom_q_share, 3),
        },
        "clusters": {
            "morans_i": round(moran_i, 3),
            "morans_p": round(moran_p, 3),
            "permutations": PERMUTATIONS,
            "alpha": ALPHA,
            "counts": {k: int(v) for k, v in clusters.items()},
            "low_low_top_areas": low_low_areas,
        },
        "districts": district_rows,
    }
    with open(SUMMARY_PATH, "w") as f:
        json.dump(summary, f, indent=2)

    # --- 7. Public download --------------------------------------------------
    cols = {
        "GEOID": "geoid", "NAME": "tract", "area_label": "area",
        "commission_district": "commission_district",
        "uoi_score": "opportunity_score", "uoi_rank": "rank", "uoi_percentile": "percentile",
        "lisa_cluster": "cluster", "lisa_p": "cluster_p_value",
        "eviction_filings_12mo": "eviction_filings_12mo", "renter_households": "renter_households",
        "eviction_filing_rate": "eviction_filings_per_100_renters", "eviction_vs_baseline": "eviction_filings_vs_prepandemic",
        "pct_broadband": "pct_home_internet", "pct_rent_burdened": "pct_rent_burdened",
        "pct_uninsured": "pct_uninsured", "pct_poverty": "pct_poverty",
        "median_hh_income": "median_household_income", "pct_disability": "pct_disability",
        "pct_hs_or_higher": "pct_hs_or_higher", "pct_snap": "pct_snap",
        "unemployment_rate": "unemployment_rate", "pct_no_vehicle": "pct_no_vehicle",
        "pct_lep": "pct_limited_english", "hospital_distance_mi": "miles_to_hospital",
    }
    out = df[[c for c in cols if c in df.columns]].rename(columns=cols)
    out["opportunity_score"] = (out["opportunity_score"] * 100).round(1)
    out = out.sort_values("rank")
    out.to_csv(DOWNLOAD_CSV, index=False, float_format="%.4g")

    print(f"Moran's I = {moran_i:.3f} (p = {moran_p:.3f})")
    print(f"LISA clusters: {clusters}")
    print(f"Spearman(index, filing rate) = {rho:.3f};  ACS proxy = {proxy_rho:.3f}")
    print(f"Bottom-quartile filing rate {low_q['rate']:.2f} vs top {high_q['rate']:.2f} per 100 renters")
    print(f"Wrote {TRACTS_PATH}, {SUMMARY_PATH}, {DOWNLOAD_CSV}")
    return summary


if __name__ == "__main__":
    enrich()
