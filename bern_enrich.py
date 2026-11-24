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
4. A validation check: does the index line up with an outcome it never saw (eviction
   filings), and does it tell you anything that median income alone doesn't?
5. Expected vs. actual evictions: a quasi-Poisson model predicts each tract's filings
   from its income and housing cost burden, then flags tracts filing far more (or far
   fewer) cases than those two things explain.

Special-use census tracts (codes 9800-9899: Kirtland Air Force Base, parks, open space)
have few or no residents. They are flagged, left unscored and kept out of every ranking
and statistic, and the score is rescaled over residential tracts only.

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
EXCESS_Z = 2.0                  # quasi-Poisson z beyond which a tract is "far" from expected

# Census reserves tract codes 9800-9899 for special land use (bases, parks, airports).
SPECIAL_USE_LABELS = {"35001980000": "Kirtland Air Force Base"}

# Same inputs and directions as bern_uoi_pipeline.py: (raw column, normalized column, higher_is_better)
SCORE_INPUTS = [
    ("pct_broadband", "norm_broadband", True),
    ("pct_uninsured", "norm_uninsured", False),
    ("pct_rent_burdened", "norm_rent_burdened", False),
    ("pct_poverty", "norm_poverty", False),
    ("median_hh_income", "norm_income", True),
    ("pct_disability", "norm_disability", False),
    ("pct_hs_or_higher", "norm_hs_or_higher", True),
    ("pct_snap", "norm_snap", False),
    ("unemployment_rate", "norm_unemployment", False),
    ("pct_no_vehicle", "norm_vehicle_access", False),
    ("hospital_distance_mi", "norm_hospital_access", False),
]
REFERENCE_INPUTS = [("pct_lep", "norm_language_access", False)]


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


def is_special_use(props):
    try:
        return 9800 <= float(props["NAME"]) < 9900
    except (TypeError, ValueError):
        return False


def minmax(s):
    lo, hi = s.min(), s.max()
    return (s - lo) / (hi - lo) if hi > lo else s * 0 + 0.5


def rescore(df, residential):
    """Rebuild normalized inputs and the score over residential tracts only."""
    out = {}
    for raw, norm, better in SCORE_INPUTS + REFERENCE_INPUTS:
        v = pd.to_numeric(df[raw], errors="coerce").where(residential)
        n = minmax(v)
        out[norm] = n if better else 1 - n
    out = pd.DataFrame(out, index=df.index)
    out["uoi_score"] = out[[n for _, n, _ in SCORE_INPUTS]].mean(axis=1)
    risk = pd.concat([minmax(pd.to_numeric(df[c], errors="coerce").where(residential))
                      for c in ["pct_rent_burdened", "pct_poverty", "pct_snap", "unemployment_rate"]], axis=1).mean(axis=1)
    out["eviction_risk_score"] = risk
    out["eviction_resilience_score"] = 1 - risk
    return out.where(residential)


def quasi_poisson(y, X, offset):
    """Poisson regression by IRLS with a log link and offset; returns coefficients, fitted means,
    dispersion (Pearson chi2 / df) and deviance pseudo-R2."""
    X = np.column_stack([np.ones(len(y)), X])
    b = np.zeros(X.shape[1])
    b[0] = np.log(y.sum() / np.exp(offset).sum())
    for _ in range(100):
        eta = X @ b + offset
        mu = np.exp(eta)
        z = eta - offset + (y - mu) / mu
        b_new = np.linalg.solve(X.T @ (mu[:, None] * X), X.T @ (mu * z))
        if np.max(np.abs(b_new - b)) < 1e-10:
            b = b_new
            break
        b = b_new
    mu = np.exp(X @ b + offset)
    phi = float(np.sum((y - mu) ** 2 / mu) / (len(y) - X.shape[1]))

    def deviance(m):
        with np.errstate(divide="ignore", invalid="ignore"):
            return 2 * np.sum(np.where(y > 0, y * np.log(y / m), 0.0) - (y - m))

    null_mu = np.exp(offset) * y.sum() / np.exp(offset).sum()
    pseudo_r2 = 1 - deviance(mu) / deviance(null_mu)
    return b, mu, phi, float(pseudo_r2)


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

    # --- 1a. Expected vs. actual filings ---------------------------------
    evm = ev.copy()
    evm["income"] = [p.get("median_hh_income") for p in props]
    evm["burden"] = [p.get("pct_rent_burdened") for p in props]
    evm["special"] = [is_special_use(p) for p in props]
    m = evm[(~evm["special"]) & (evm["renter_households"] >= MIN_RENTERS_FOR_RATE)
            & evm["income"].notna() & evm["burden"].notna() & (evm["income"] > 0)]
    y = m["filings_12mo"].to_numpy(float)
    Xm = np.column_stack([np.log(m["income"].to_numpy(float)), m["burden"].to_numpy(float)])
    beta, mu, phi, pseudo_r2 = quasi_poisson(y, Xm, np.log(m["renter_households"].to_numpy(float)))
    _, _, _, pseudo_r2_income = quasi_poisson(y, Xm[:, :1], np.log(m["renter_households"].to_numpy(float)))
    evm["expected"] = np.nan
    evm.loc[m.index, "expected"] = mu
    evm["excess"] = evm["filings_12mo"] - evm["expected"]
    evm["excess_ratio"] = evm["filings_12mo"] / evm["expected"]
    evm["excess_z"] = evm["excess"] / np.sqrt(phi * evm["expected"])
    def excess_class(z):
        if pd.isna(z):
            return None
        return "far_above" if z >= EXCESS_Z else "far_below" if z <= -EXCESS_Z else "as_expected"
    evm["excess_class"] = evm["excess_z"].map(excess_class)

    # --- 1b. Special-use tracts and rescoring ------------------------------
    special = pd.Series([is_special_use(p) for p in props])
    raw = pd.DataFrame(props)
    scored = rescore(raw, ~special)
    for i, p in enumerate(props):
        p["special_use"] = bool(special[i])
        if special[i]:
            g = p["GEOID"]
            label = p.get("area_label") or f"Tract {p['NAME']}"
            if g in SPECIAL_USE_LABELS:
                label = SPECIAL_USE_LABELS[g]
            elif not label.startswith("Special-use area"):
                label = f"Special-use area near {label}"
            p["area_label"] = label
            p["tract_label"] = f"{label} (Tract {p['NAME']})"
        for col in scored.columns:
            v = scored.at[i, col]
            p[col] = None if pd.isna(v) else float(v)

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
        x = evm.loc[p["GEOID"]]
        p["eviction_expected"] = clean(x["expected"], 1)
        p["eviction_excess"] = clean(x["excess"], 1)
        p["eviction_excess_ratio"] = clean(x["excess_ratio"], 2)
        p["eviction_excess_z"] = clean(x["excess_z"], 2)
        p["eviction_excess_class"] = x["excess_class"]
        if p["special_use"]:
            p["eviction_filing_rate"] = None
            p["eviction_vs_baseline"] = None

    with open(TRACTS_PATH, "w") as f:
        json.dump(tracts, f, separators=(",", ":"))

    # --- 6. Summary + validation ------------------------------------------
    df_all = pd.DataFrame(props)
    df = df_all[~df_all["special_use"]].copy()
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

    # Is the score just income? Compare it with median household income alone.
    inc = df.dropna(subset=["score", "median_hh_income"])
    rho_score_income = spearman(inc["score"], inc["median_hh_income"])
    both_inc = both.dropna(subset=["median_hh_income"])
    rho_income_filings = spearman(both_inc["median_hh_income"], both_inc["eviction_filing_rate"])
    qi = pd.qcut(both_inc["median_hh_income"], 4, labels=["q1", "q2", "q3", "q4"])
    by_qi = both_inc.groupby(qi, observed=True).agg(filings=("eviction_filings_12mo", "sum"), renters=("renter_households", "sum"))
    by_qi["rate"] = by_qi["filings"] / by_qi["renters"] * 100
    # Rank regression: does the score add anything once income is known?
    yr = both_inc["eviction_filing_rate"].rank().to_numpy()
    X1 = np.column_stack([np.ones(len(yr)), both_inc["median_hh_income"].rank()])
    X2 = np.column_stack([X1, both_inc["score"].rank()])
    def r2(X):
        b = np.linalg.lstsq(X, yr, rcond=None)[0]
        return 1 - ((yr - X @ b) ** 2).sum() / ((yr - yr.mean()) ** 2).sum()
    r2_income, r2_income_score = r2(X1), r2(X2)

    ex = df.dropna(subset=["eviction_excess_class"])
    far_above = ex[ex["eviction_excess_class"] == "far_above"].sort_values("eviction_excess", ascending=False)
    far_below = ex[ex["eviction_excess_class"] == "far_below"].sort_values("eviction_excess")

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
        "tract_count_all": int(len(df_all)),
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
            "spearman_score_vs_income": round(rho_score_income, 3),
            "spearman_income_vs_filing_rate": round(rho_income_filings, 3),
            "income_bottom_vs_top_ratio": round(float(by_qi.loc["q1", "rate"] / by_qi.loc["q4", "rate"]), 1),
            "r2_ranks_income_only": round(float(r2_income), 3),
            "r2_ranks_income_plus_score": round(float(r2_income_score), 3),
        },
        "expected_evictions": {
            "model": "quasi-Poisson: filings ~ log(median household income) + % cost-burdened households, offset log(renter households)",
            "tracts_modeled": int(len(ex)),
            "coef_log_income": round(float(beta[1]), 3),
            "coef_cost_burden_per_point": round(float(beta[2]), 4),
            "dispersion": round(phi, 1),
            "pseudo_r2": round(pseudo_r2, 3),
            "pseudo_r2_income_only": round(pseudo_r2_income, 3),
            "z_threshold": EXCESS_Z,
            "far_above_count": int(len(far_above)),
            "far_below_count": int(len(far_below)),
            "far_above_filings": int(far_above["eviction_filings_12mo"].sum()),
            "far_above_expected": round(float(far_above["eviction_expected"].sum()), 1),
            "far_above_share_of_renters": round(float(far_above["renter_households"].sum() / df["renter_households"].sum()), 3),
            "far_above_share_of_filings": round(float(far_above["eviction_filings_12mo"].sum() / df["eviction_filings_12mo"].sum()), 3),
            "far_above_top": [
                {"area": r.area_label, "tract": r.NAME, "filings": int(r.eviction_filings_12mo), "expected": round(float(r.eviction_expected), 0)}
                for r in far_above.head(5).itertuples()
            ],
            "far_below_top": [
                {"area": r.area_label, "tract": r.NAME, "filings": int(r.eviction_filings_12mo), "expected": round(float(r.eviction_expected), 0)}
                for r in far_below.head(3).itertuples()
            ],
        },
        "special_use_tracts": [
            {"geoid": r.GEOID, "tract": r.NAME, "label": r.area_label}
            for r in df_all[df_all["special_use"]].itertuples()
        ],
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
    cols.update({"special_use": "special_use", "eviction_expected": "eviction_filings_expected",
                 "eviction_excess_ratio": "eviction_actual_vs_expected", "eviction_excess_class": "eviction_vs_expected"})
    out = df_all[[c for c in cols if c in df_all.columns]].rename(columns=cols)
    out["opportunity_score"] = (out["opportunity_score"] * 100).round(1)
    out = out.sort_values(["special_use", "rank"])
    out.to_csv(DOWNLOAD_CSV, index=False, float_format="%.4g")

    print(f"Moran's I = {moran_i:.3f} (p = {moran_p:.3f})")
    print(f"LISA clusters: {clusters}")
    print(f"Spearman(index, filing rate) = {rho:.3f};  ACS proxy = {proxy_rho:.3f}")
    print(f"Bottom-quartile filing rate {low_q['rate']:.2f} vs top {high_q['rate']:.2f} per 100 renters")
    print(f"Score vs income rho = {rho_score_income:.3f}; income vs filings rho = {rho_income_filings:.3f}; rank R2 income {r2_income:.3f} -> +score {r2_income_score:.3f}")
    print(f"Expected-evictions model: pseudo-R2 {pseudo_r2:.3f} (income only {pseudo_r2_income:.3f}), dispersion {phi:.1f}; "
          f"{len(far_above)} tracts far above expected, {len(far_below)} far below")
    print(f"Wrote {TRACTS_PATH}, {SUMMARY_PATH}, {DOWNLOAD_CSV}")
    return summary


if __name__ == "__main__":
    enrich()
