"""Dashboard JSON and the Power BI star schema."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

DOCS, RESULTS, POWERBI = Path("docs"), Path("results"), Path("powerbi/data")


def _rec(df: pd.DataFrame, index: bool = True) -> list[dict]:
    d = df.reset_index() if index else df.copy()
    for c in d.columns:
        if pd.api.types.is_datetime64_any_dtype(d[c]):
            d[c] = d[c].dt.strftime("%Y-%m-%d")
    return json.loads(d.to_json(orient="records"))


def short(seller_id: str) -> str:
    return "S-" + seller_id[:6]


def write_all(*, orders, a, quality, kpis, monthly, stages, late, pareto_causes, concentration, sellers,
              regions, states, categories, routes, tests, corr, reg, sql) -> dict:
    for p in (DOCS, RESULTS, POWERBI):
        p.mkdir(parents=True, exist_ok=True)

    # Seller Pareto curve: cumulative share of late orders vs share of sellers.
    s = late["seller_id"].value_counts()
    n_sellers = a["seller_id"].nunique()
    cum = (s.cumsum() / s.sum() * 100).to_numpy()
    xs = np.arange(1, len(s) + 1) / n_sellers * 100
    pick = np.unique(np.r_[np.linspace(0, len(s) - 1, 60).astype(int)])
    seller_curve = [{"sellers_pct": round(float(xs[i]), 2), "late_pct": round(float(cum[i]), 2)} for i in pick]

    cause_month = pd.crosstab(late["month"], late["root_cause"]).reindex(columns=pareto_causes.index, fill_value=0)

    bins = list(range(0, 61, 3))
    hist = {}
    for name, g in a.groupby("is_late"):
        h, _ = np.histogram(g["total_days"].clip(upper=60), bins=bins)
        hist["Late" if name else "On time"] = (h / h.sum() * 100).round(2).tolist()

    top_sellers = sellers.head(15).copy()
    top_sellers.index = [short(i) for i in top_sellers.index]

    headline = {**kpis,
                "share_of_time": stages["share_of_time"],
                "share_of_extra_days": stages["share_of_extra_days"],
                "extra_days": stages["extra_days_late_vs_ontime"],
                "top_cause": pareto_causes.index[0], "top_cause_pct": float(pareto_causes["share_pct"].iloc[0]),
                "second_cause": pareto_causes.index[1], "second_cause_pct": float(pareto_causes["share_pct"].iloc[1]),
                "top_two_causes_pct": float(pareto_causes["cumulative_pct"].iloc[1]),
                "concentration": concentration,
                "time_r2": reg["time_r2"], "cost_r2": reg["cost_r2"],
                "cost_decomposition": reg["cost_decomposition"],
                "worst_region": regions.index[0], "worst_region_delay_pct": float(regions["delay_rate_pct"].iloc[0]),
                "best_region": regions.index[-1], "best_region_delay_pct": float(regions["delay_rate_pct"].iloc[-1]),
                "peak_delay_month": str(monthly["delay_rate"].idxmax().date()),
                "peak_delay_rate_pct": round(float(monthly["delay_rate"].max() * 100), 1),
                "review_late": float(a.loc[a["is_late"] == 1, "review_score"].mean().round(2)),
                "review_ontime": float(a.loc[a["is_late"] == 0, "review_score"].mean().round(2)),
                }

    dash = {
        "headline": headline, "quality": quality,
        "monthly": _rec(monthly.rename_axis("month")),
        "stage_descriptive": _rec(stages["descriptive"].rename_axis("stage")),
        "root_causes": _rec(pareto_causes.rename_axis("cause")),
        "cause_by_month": {"months": [d.strftime("%Y-%m") for d in cause_month.index],
                           "series": {c: cause_month[c].tolist() for c in cause_month.columns}},
        "seller_curve": seller_curve,
        "top_sellers": _rec(top_sellers.rename_axis("seller")),
        "regions": _rec(regions.rename_axis("region")),
        "states": _rec(states.rename_axis("state")),
        "categories": _rec(categories.head(12).rename_axis("category")),
        "routes": _rec(sql["routes"].head(10), index=False),
        "tests": tests,
        "regression_time": _rec(reg["time"].rename_axis("factor")),
        "regression_cost": _rec(reg["cost"].rename_axis("factor")),
        "histogram": {"bins": [f"{b}-{b + 3}" for b in bins[:-1]], **hist},
        "correlations": {"cols": list(corr.columns), "values": corr.to_numpy().tolist()},
    }
    (DOCS / "data.json").write_text(json.dumps(dash, indent=1, default=str))
    (RESULTS / "summary.json").write_text(json.dumps({"headline": headline, "quality": quality, "tests": tests,
                                                       "root_causes": _rec(pareto_causes.rename_axis("cause"))},
                                                      indent=2, default=str))
    reg["time"].to_csv(RESULTS / "regression_delivery_time.csv")
    reg["cost"].to_csv(RESULTS / "regression_freight_cost.csv")
    stages["descriptive"].to_csv(RESULTS / "stage_descriptive_statistics.csv")

    # ---------- Power BI ----------
    fact = a[["order_id", "month", "order_purchase_timestamp", "seller_id", "customer_state", "customer_region",
              "seller_state", "route", "category", "items", "price", "freight", "weight_kg", "distance_km",
              "approval_hours", "handling_days", "transit_days", "total_days", "promised_days", "days_late",
              "is_late", "seller_missed_handoff", "review_score"]].copy()
    fact = fact.merge(late[["order_id", "root_cause"]], on="order_id", how="left")
    fact["root_cause"] = fact["root_cause"].fillna("On time")
    fact["order_date"] = fact["order_purchase_timestamp"].dt.date
    fact = fact.drop(columns="order_purchase_timestamp")
    # Integer keys keep the file small; dim_seller maps seller_key back to the seller.
    seller_keys = {sid: i + 1 for i, sid in enumerate(sorted(a["seller_id"].unique()))}
    fact.insert(0, "order_key", range(1, len(fact) + 1))
    fact["seller_key"] = fact["seller_id"].map(seller_keys)
    fact = fact.drop(columns=["order_id", "seller_id"])
    fact.to_csv(POWERBI / "fact_orders.csv", index=False, float_format="%.2f")

    dim_seller = sellers.reset_index()[["seller_id", "seller_state", "orders", "late_rate", "handoff_miss_rate",
                                        "avg_handling_days", "excess_late_orders"]]
    all_s = a.groupby("seller_id").agg(seller_state=("seller_state", "first"), orders=("order_id", "size")).reset_index()
    dim_seller = all_s.merge(dim_seller.drop(columns=["seller_state", "orders"]), on="seller_id", how="left")
    dim_seller["seller_label"] = dim_seller["seller_id"].map(short)
    dim_seller.insert(0, "seller_key", dim_seller["seller_id"].map(seller_keys))
    dim_seller = dim_seller.drop(columns="seller_id")
    dim_seller.to_csv(POWERBI / "dim_seller.csv", index=False, float_format="%.4f")

    monthly.rename_axis("month").to_csv(POWERBI / "monthly_kpis.csv", float_format="%.4f")
    pareto_causes.rename_axis("root_cause").to_csv(POWERBI / "root_cause_pareto.csv")
    pd.DataFrame(tests).to_csv(POWERBI / "hypothesis_tests.csv", index=False)
    pd.concat([reg["time"].assign(model="Delivery days"), reg["cost"].assign(model="Freight cost")]) \
        .rename_axis("factor").to_csv(POWERBI / "regression_coefficients.csv")
    return headline
