import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from opsrc import analysis as an, data, warehouse  # noqa: E402


def fake_tables(n: int = 400, seed: int = 0) -> dict[str, pd.DataFrame]:
    """Olist-shaped tables with known delays: sellers 's1' miss their hand-off deadline."""
    rng = np.random.default_rng(seed)
    start = pd.Timestamp("2017-02-01")
    orders, items, reviews, customers = [], [], [], []
    for k in range(n):
        oid, cid = f"o{k}", f"c{k}"
        seller = "s1" if k % 4 == 0 else "s2"
        buy = start + pd.Timedelta(hours=int(rng.integers(0, 24 * 300)))
        approve = buy + pd.Timedelta(hours=float(rng.uniform(0.1, 5)))
        limit = approve + pd.Timedelta(days=2)
        carrier = limit + pd.Timedelta(days=3) if seller == "s1" else approve + pd.Timedelta(days=1)
        deliver = carrier + pd.Timedelta(days=float(rng.uniform(3, 8)))
        est = (buy + pd.Timedelta(days=10)).normalize()
        status = "delivered" if k != 1 else "canceled"
        orders.append({"order_id": oid, "customer_id": cid, "order_status": status, "order_purchase_timestamp": buy,
                       "order_approved_at": approve, "order_delivered_carrier_date": carrier if status == "delivered" else None,
                       "order_delivered_customer_date": deliver if status == "delivered" else None,
                       "order_estimated_delivery_date": est})
        items.append({"order_id": oid, "order_item_id": 1, "product_id": "p1", "seller_id": seller,
                      "shipping_limit_date": limit, "price": 100.0, "freight_value": 10.0 + (k % 3)})
        late = deliver.normalize() > est
        reviews.append({"review_id": f"r{k}", "order_id": oid, "review_score": 2 if late else 5,
                        "review_answer_timestamp": deliver + pd.Timedelta(days=1)})
        customers.append({"customer_id": cid, "customer_zip_code_prefix": 2000 + (k % 2),
                          "customer_state": "SP" if k % 2 else "BA", "customer_city": "x"})
    # one duplicate review for order o0 (older), which must be dropped
    reviews.append({"review_id": "dup", "order_id": "o0", "review_score": 1, "review_answer_timestamp": start})
    # one order whose carrier date is before approval
    orders[2]["order_delivered_carrier_date"] = orders[2]["order_approved_at"] - pd.Timedelta(days=1)
    str_dates = lambda df: df.assign(**{c: df[c].astype(str) for c in df.columns if "date" in c or "_at" in c or "timestamp" in c})  # noqa: E731
    return {
        "orders": str_dates(pd.DataFrame(orders)),
        "order_items": str_dates(pd.DataFrame(items)),
        "order_reviews": str_dates(pd.DataFrame(reviews)),
        "customers": pd.DataFrame(customers),
        "sellers": pd.DataFrame({"seller_id": ["s1", "s2"], "seller_zip_code_prefix": [1000, 1001], "seller_state": ["SP", "SP"]}),
        "products": pd.DataFrame({"product_id": ["p1"], "product_category_name": ["cama_mesa_banho"], "product_weight_g": [500],
                                  "product_length_cm": [10], "product_height_cm": [10], "product_width_cm": [10]}),
        "product_category_name_translation": pd.DataFrame({"product_category_name": ["cama_mesa_banho"],
                                                           "product_category_name_english": ["bed_bath_table"]}),
        "geolocation": pd.DataFrame({"geolocation_zip_code_prefix": [1000, 1001, 2000, 2001],
                                     "geolocation_lat": [-23.5, -23.6, -12.9, -23.5], "geolocation_lng": [-46.6, -46.7, -38.5, -46.6]}),
    }


@pytest.fixture(scope="module")
def built():
    return data.build_orders(fake_tables())


def test_quality_counts(built):
    o, q = built
    assert q["duplicate_reviews_removed"] == 1
    assert q["carrier_date_before_approval"] == 1
    assert q["cancelled_or_unavailable"] == 1
    assert o.loc[o["order_id"] == "o0", "review_score"].iloc[0] != 1   # latest review kept


def test_stages_add_up(built):
    o, _ = built
    a = an.analysed(o)
    total = a["approval_days"] + a["handling_days"] + a["transit_days"]
    assert np.allclose(total, a["total_days"])
    assert (a[["approval_days", "handling_days", "transit_days"]] >= 0).all().all()


def test_invalid_orders_excluded(built):
    o, _ = built
    a = an.analysed(o)
    assert "o1" not in set(a["order_id"]) and "o2" not in set(a["order_id"])


def test_distance(built):
    o, _ = built
    d = data.haversine_km(-23.5505, -46.6333, -22.9068, -43.1729)   # Sao Paulo to Rio
    assert 340 < d < 370
    assert (o["distance_km"].dropna() >= 0).all()


def test_seller_handoff_flag_and_root_cause(built):
    o, _ = built
    a = an.analysed(o)
    assert a.loc[a["seller_id"] == "s1", "seller_missed_handoff"].all()
    assert not a.loc[a["seller_id"] == "s2", "seller_missed_handoff"].any()
    late = an.classify_root_causes(a)
    s1_late = late[late["seller_id"] == "s1"]
    assert len(s1_late) > 0
    assert (s1_late["root_cause"] == "Seller missed hand-off deadline").all()


def test_pareto_is_sorted_and_cumulative():
    p = an.pareto(pd.Series(["a"] * 5 + ["b"] * 3 + ["c"] * 2))
    assert list(p.index) == ["a", "b", "c"]
    assert p["cumulative_pct"].iloc[-1] == pytest.approx(100.0)
    assert p["share_pct"].is_monotonic_decreasing


def test_concentration():
    late = pd.DataFrame({"k": ["a"] * 8 + ["b"] * 1 + ["c"] * 1})
    allg = pd.DataFrame({"k": list("abcdefghij")})
    c = an.concentration(late, allg, "k")
    assert c["groups_for_80pct_of_late"] == 1 and c["share_of_groups_pct"] == 10.0


def test_kpis_consistent(built):
    o, _ = built
    a = an.analysed(o)
    k = an.headline_kpis(a, o)
    assert k["on_time_rate_pct"] + k["delay_rate_pct"] == pytest.approx(100, abs=0.1)
    assert k["cost_per_order"] == pytest.approx(a["freight"].mean(), abs=0.01)


def test_sql_queries_run(built, tmp_path):
    o, _ = built
    con = warehouse.build(o, tmp_path / "t.db")
    out = warehouse.run_queries(con, ROOT / "sql")
    assert {"monthly_kpis", "stage_times", "routes"} <= set(out)
    assert out["monthly_kpis"]["orders_delivered"].sum() == len(an.analysed(o))
