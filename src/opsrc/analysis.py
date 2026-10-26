"""Operational KPIs, stage bottlenecks, root-cause classification, Pareto, statistics and regression."""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy import stats

STAGES = {"approval": "approval_days", "seller handling": "handling_days", "carrier transit": "transit_days"}
BLACK_FRIDAY = (pd.Timestamp("2017-11-20"), pd.Timestamp("2017-12-03"))
CAUSE_ORDER = ["Payment approval delay", "Seller missed hand-off deadline", "Slow carrier transit",
               "Promise shorter than the route needs", "Other"]


def analysed(orders: pd.DataFrame) -> pd.DataFrame:
    a = orders[orders["stage_times_valid"] & orders["in_window"]].copy()
    a["approval_days"] = a["approval_hours"] / 24
    return a


# ---------------- KPIs ----------------
def monthly_kpis(orders: pd.DataFrame) -> pd.DataFrame:
    all_ = orders[orders["in_window"]]
    a = analysed(orders)
    g = a.groupby("month")
    k = pd.DataFrame({
        "orders_placed": all_.groupby("month").size(),
        "orders_delivered": g.size(),
        "avg_processing_days": g["total_days"].mean(),
        "median_processing_days": g["total_days"].median(),
        "on_time_rate": 1 - g["is_late"].mean(),
        "delay_rate": g["is_late"].mean(),
        "cost_per_order": g["freight"].mean(),
        "freight_share_of_price": g["freight"].sum() / g["price"].sum(),
        "avg_approval_days": g["approval_days"].mean(),
        "avg_handling_days": g["handling_days"].mean(),
        "avg_transit_days": g["transit_days"].mean(),
        "avg_promised_days": g["promised_days"].mean(),
        "seller_handoff_miss_rate": g["seller_missed_handoff"].mean(),
        "active_sellers": g["seller_id"].nunique(),
        "avg_review": g["review_score"].mean(),
    })
    k["orders_per_active_seller"] = k["orders_delivered"] / k["active_sellers"]
    weeks = k.index.days_in_month / 7
    k["throughput_per_week"] = k["orders_delivered"] / weeks
    k["cancel_rate"] = all_.groupby("month")["order_status"].apply(lambda s: s.isin(["canceled", "unavailable"]).mean())
    return k.round(4)


def headline_kpis(a: pd.DataFrame, orders: pd.DataFrame) -> dict:
    return {
        "orders_analysed": int(len(a)),
        "avg_processing_days": round(float(a["total_days"].mean()), 2),
        "median_processing_days": round(float(a["total_days"].median()), 2),
        "on_time_rate_pct": round(float(1 - a["is_late"].mean()) * 100, 1),
        "delay_rate_pct": round(float(a["is_late"].mean()) * 100, 2),
        "cost_per_order": round(float(a["freight"].mean()), 2),
        "freight_share_pct": round(float(a["freight"].sum() / a["price"].sum()) * 100, 1),
        "throughput_per_week": round(float(len(a) / ((a["order_purchase_timestamp"].max() - a["order_purchase_timestamp"].min()).days / 7)), 0),
        "sellers": int(a["seller_id"].nunique()),
        "late_orders": int(a["is_late"].sum()),
    }


# ---------------- Stage bottlenecks ----------------
def route_baselines(a: pd.DataFrame, min_orders: int = 30) -> pd.DataFrame:
    """Typical (median) time per stage for each seller-state -> customer-state route."""
    cols = ["handling_days", "transit_days", "total_days"]
    by_route = a.groupby("route")[cols].median()
    counts = a.groupby("route").size()
    by_state = a.groupby("customer_state")[cols].median()
    base = a[["route", "customer_state"]].drop_duplicates("route").set_index("route")
    out = by_state.reindex(base["customer_state"]).set_index(base.index)
    ok = counts[counts >= min_orders].index
    out.loc[ok] = by_route.loc[ok]
    return out.add_prefix("typical_")


def stage_breakdown(a: pd.DataFrame) -> dict:
    """Where the time goes, and which stage the extra days of late orders come from."""
    share = {name: float(a[col].mean() / a[["approval_days", "handling_days", "transit_days"]].sum(axis=1).mean())
             for name, col in STAGES.items()}
    late, ontime = a[a["is_late"] == 1], a[a["is_late"] == 0]
    extra = {name: float(late[col].mean() - ontime[col].mean()) for name, col in STAGES.items()}
    total_extra = sum(max(v, 0) for v in extra.values())
    desc = {}
    for name, col in STAGES.items():
        s = a[col]
        desc[name] = {"mean": s.mean(), "median": s.median(), "p90": s.quantile(0.9), "std": s.std(),
                      "skew": stats.skew(s), "late_mean": late[col].mean(), "ontime_mean": ontime[col].mean()}
    desc["total"] = {"mean": a["total_days"].mean(), "median": a["total_days"].median(),
                     "p90": a["total_days"].quantile(0.9), "std": a["total_days"].std(), "skew": stats.skew(a["total_days"]),
                     "late_mean": late["total_days"].mean(), "ontime_mean": ontime["total_days"].mean()}
    return {
        "share_of_time": {k: round(v * 100, 1) for k, v in share.items()},
        "extra_days_late_vs_ontime": {k: round(v, 2) for k, v in extra.items()},
        "share_of_extra_days": {k: round(max(v, 0) / total_extra * 100, 1) for k, v in extra.items()},
        "descriptive": pd.DataFrame(desc).T.round(2),
    }


# ---------------- Root causes ----------------
def classify_root_causes(a: pd.DataFrame) -> pd.DataFrame:
    """Give every late order one primary cause, checked in process order."""
    base = route_baselines(a)
    b = a.join(base, on="route")
    late = b[b["is_late"] == 1].copy()
    slow_transit = (late["transit_days"] > 1.5 * late["typical_transit_days"]) & \
                   (late["transit_days"] - late["typical_transit_days"] > 3)
    tight = late["promised_days"] < late["typical_total_days"]
    late["root_cause"] = np.select(
        [late["approval_days"] > 2, late["seller_missed_handoff"] == 1, slow_transit, tight],
        CAUSE_ORDER[:4], default="Other")
    return late


def pareto(series: pd.Series, top: int | None = None) -> pd.DataFrame:
    """Counts sorted descending with cumulative share."""
    s = series.value_counts()
    df = pd.DataFrame({"late_orders": s, "share_pct": (s / s.sum() * 100).round(1)})
    df["cumulative_pct"] = df["share_pct"].cumsum().round(1)
    return df.head(top) if top else df


def concentration(late: pd.DataFrame, a: pd.DataFrame, key: str) -> dict:
    """How few groups (sellers, routes...) account for 80% of late orders."""
    s = late[key].value_counts()
    cum = s.cumsum() / s.sum()
    n80 = int((cum < 0.8).sum() + 1)
    total_groups = a[key].nunique()
    return {"groups": int(total_groups), "groups_with_late_orders": int(len(s)),
            "groups_for_80pct_of_late": n80, "share_of_groups_pct": round(n80 / total_groups * 100, 1)}


def seller_scorecard(a: pd.DataFrame, min_orders: int = 50) -> pd.DataFrame:
    g = a.groupby("seller_id")
    sc = pd.DataFrame({
        "orders": g.size(), "late_orders": g["is_late"].sum(), "late_rate": g["is_late"].mean(),
        "handoff_miss_rate": g["seller_missed_handoff"].mean(), "avg_handling_days": g["handling_days"].mean(),
        "avg_review": g["review_score"].mean(), "seller_state": g["seller_state"].first(),
    })
    sc = sc[sc["orders"] >= min_orders]
    overall = a["is_late"].mean()
    # Late orders above what an average seller would have had with the same volume.
    sc["excess_late_orders"] = (sc["late_orders"] - sc["orders"] * overall).round(1)
    return sc.sort_values("excess_late_orders", ascending=False).round(3)


def group_compare(a: pd.DataFrame, key: str, min_orders: int = 300) -> pd.DataFrame:
    g = a.groupby(key)
    t = pd.DataFrame({"orders": g.size(), "delay_rate_pct": g["is_late"].mean() * 100,
                      "avg_processing_days": g["total_days"].mean(), "avg_handling_days": g["handling_days"].mean(),
                      "avg_transit_days": g["transit_days"].mean(), "cost_per_order": g["freight"].mean(),
                      "avg_review": g["review_score"].mean()})
    return t[t["orders"] >= min_orders].sort_values("delay_rate_pct", ascending=False).round(2)


# ---------------- Statistics ----------------
def hypothesis_tests(a: pd.DataFrame) -> list[dict]:
    out = []
    late = a.loc[a["is_late"] == 1, "review_score"].dropna()
    ontime = a.loc[a["is_late"] == 0, "review_score"].dropna()
    u = stats.mannwhitneyu(late, ontime, alternative="less")
    out.append({"hypothesis": "Late orders get lower review scores", "test": "Mann-Whitney U (one-sided)",
                "result": f"mean {late.mean():.2f} late vs {ontime.mean():.2f} on time", "p_value": float(u.pvalue),
                "conclusion": "Supported" if u.pvalue < 0.05 else "Not supported"})

    ct = pd.crosstab(a["seller_missed_handoff"], a["is_late"])
    chi = stats.chi2_contingency(ct)
    r1 = a.loc[a["seller_missed_handoff"] == 1, "is_late"].mean()
    r0 = a.loc[a["seller_missed_handoff"] == 0, "is_late"].mean()
    out.append({"hypothesis": "Orders handed to the carrier after the seller deadline are more often late",
                "test": "Chi-square test of independence",
                "result": f"{r1 * 100:.1f}% late vs {r0 * 100:.1f}% ({r1 / r0:.1f}x)", "p_value": float(chi.pvalue),
                "conclusion": "Supported" if chi.pvalue < 0.05 else "Not supported"})

    bf = a["order_purchase_timestamp"].between(*BLACK_FRIDAY)
    q4 = a["order_purchase_timestamp"].between("2017-10-01", "2017-12-31")
    sub = a[q4]
    ct2 = pd.crosstab(bf[q4], sub["is_late"])
    chi2 = stats.chi2_contingency(ct2)
    rb, rr = sub.loc[bf[q4], "is_late"].mean(), sub.loc[~bf[q4], "is_late"].mean()
    out.append({"hypothesis": "The Black Friday peak (20 Nov - 3 Dec 2017) caused more delays than the rest of Q4",
                "test": "Chi-square test of independence",
                "result": f"{rb * 100:.1f}% late vs {rr * 100:.1f}% in the rest of Q4 2017", "p_value": float(chi2.pvalue),
                "conclusion": "Supported" if chi2.pvalue < 0.05 else "Not supported"})

    groups = [g["total_days"].to_numpy() for _, g in a.groupby("customer_region")]
    kw = stats.kruskal(*groups)
    med = a.groupby("customer_region")["total_days"].median().sort_values()
    out.append({"hypothesis": "Delivery time differs between customer regions", "test": "Kruskal-Wallis H",
                "result": f"median {med.iloc[0]:.1f} days ({med.index[0]}) to {med.iloc[-1]:.1f} days ({med.index[-1]})",
                "p_value": float(kw.pvalue), "conclusion": "Supported" if kw.pvalue < 0.05 else "Not supported"})

    rho = stats.spearmanr(a["handling_days"], a["days_late"].clip(lower=0))
    out.append({"hypothesis": "Longer seller handling goes with more days late", "test": "Spearman rank correlation",
                "result": f"rho = {rho.statistic:.2f}", "p_value": float(rho.pvalue),
                "conclusion": "Supported" if rho.pvalue < 0.05 and rho.statistic > 0 else "Not supported"})
    return out


def correlations(a: pd.DataFrame) -> pd.DataFrame:
    cols = ["total_days", "handling_days", "transit_days", "approval_days", "distance_km", "weight_kg",
            "freight", "items", "promised_days", "review_score"]
    return a[cols].corr(method="spearman").round(2)


def _coef_table(model, names: dict) -> pd.DataFrame:
    ci = model.conf_int()
    t = pd.DataFrame({"coef": model.params, "ci_low": ci[0], "ci_high": ci[1], "p_value": model.pvalues})
    t = t.drop(index="Intercept")
    t.index = [names.get(i, i.replace("C(customer_region)[T.", "Customer region: ").replace("]", "")) for i in t.index]
    return t.round(4)


def regressions(a: pd.DataFrame) -> dict:
    d = a.dropna(subset=["distance_km", "weight_kg", "volume_l", "review_score"]).copy()
    d["distance_1000km"] = d["distance_km"] / 1000
    d["black_friday"] = d["order_purchase_timestamp"].between(*BLACK_FRIDAY).astype(int)
    d["q1_2018"] = d["order_purchase_timestamp"].between("2018-02-01", "2018-03-31").astype(int)

    names = {"distance_1000km": "Distance (per 1,000 km)", "weight_kg": "Weight (per kg)", "items": "Items in the order",
             "handling_days": "Seller handling (per day)", "black_friday": "Black Friday weeks",
             "q1_2018": "Feb-Mar 2018", "volume_l": "Volume (per litre)", "sellers": "Sellers in the order"}
    time_model = smf.ols("total_days ~ distance_1000km + weight_kg + items + handling_days + black_friday + q1_2018"
                         " + C(customer_region, Treatment('Southeast'))", data=d).fit(cov_type="HC3")
    cost_model = smf.ols("freight ~ distance_1000km + weight_kg + volume_l + items + sellers"
                         " + C(customer_region, Treatment('Southeast'))", data=d).fit(cov_type="HC3")

    def tidy(m):
        t = _coef_table(m, names)
        t.index = [i.replace("C(customer_region, Treatment('Southeast'))[T.", "Customer region: ") for i in t.index]
        return t

    # Why did cost per order rise? Fit costs on 2017 and apply that price list to the 2018 mix.
    early = d[d["month"].between("2017-01-01", "2017-06-01")]
    recent = d[d["month"].between("2018-03-01", "2018-08-01")]
    m17 = smf.ols("freight ~ distance_1000km + weight_kg + volume_l + items + sellers", data=early).fit()
    pred_recent = m17.predict(recent).mean()
    decomposition = {
        "cost_per_order_jan_jun_2017": round(float(early["freight"].mean()), 2),
        "cost_per_order_mar_aug_2018": round(float(recent["freight"].mean()), 2),
        "change_pct": round(float(recent["freight"].mean() / early["freight"].mean() - 1) * 100, 1),
        "explained_by_order_mix": round(float(pred_recent - early["freight"].mean()), 2),
        "unexplained_rate_change": round(float(recent["freight"].mean() - pred_recent), 2),
        "avg_weight_kg": [round(float(early["weight_kg"].mean()), 2), round(float(recent["weight_kg"].mean()), 2)],
        "avg_distance_km": [round(float(early["distance_km"].mean()), 0), round(float(recent["distance_km"].mean()), 0)],
        "avg_items": [round(float(early["items"].mean()), 3), round(float(recent["items"].mean()), 3)],
    }
    return {
        "time": tidy(time_model), "time_r2": round(float(time_model.rsquared), 3), "time_n": int(time_model.nobs),
        "cost": tidy(cost_model), "cost_r2": round(float(cost_model.rsquared), 3), "cost_n": int(cost_model.nobs),
        "cost_decomposition": decomposition,
    }
