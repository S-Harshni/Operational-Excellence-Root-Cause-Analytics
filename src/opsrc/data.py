"""Load the Olist tables and build one clean row per order, with every process stage timed.

Order journey:  purchase ─► approval ─► seller hands parcel to carrier ─► carrier delivers
                          (payment)      (seller handling)                (carrier transit)
"""
from __future__ import annotations

import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

BASE_URL = "https://raw.githubusercontent.com/dujiaying/olist/master/data/"
RAW = Path("data/raw")
FILES = [
    "olist_orders_dataset", "olist_order_items_dataset", "olist_order_reviews_dataset",
    "olist_customers_dataset", "olist_sellers_dataset", "olist_products_dataset",
    "olist_order_payments_dataset", "product_category_name_translation", "olist_geolocation_dataset",
]
DATES = ["order_purchase_timestamp", "order_approved_at", "order_delivered_carrier_date",
         "order_delivered_customer_date", "order_estimated_delivery_date"]

REGION = {  # Brazilian macro-regions
    "SP": "Southeast", "RJ": "Southeast", "MG": "Southeast", "ES": "Southeast",
    "PR": "South", "SC": "South", "RS": "South",
    "DF": "Centre-West", "GO": "Centre-West", "MT": "Centre-West", "MS": "Centre-West",
    "BA": "Northeast", "PE": "Northeast", "CE": "Northeast", "MA": "Northeast", "PB": "Northeast",
    "RN": "Northeast", "AL": "Northeast", "PI": "Northeast", "SE": "Northeast",
    "PA": "North", "AM": "North", "RO": "North", "TO": "North", "AP": "North", "AC": "North", "RR": "North",
}


def download(raw: Path = RAW) -> Path:
    raw.mkdir(parents=True, exist_ok=True)
    for f in FILES:
        path = raw / f"{f}.csv"
        if not path.exists():
            print(f"Downloading {f}.csv ...")
            urllib.request.urlretrieve(BASE_URL + f + ".csv", path)
    return raw


def load(raw: Path = RAW) -> dict[str, pd.DataFrame]:
    return {f.replace("olist_", "").replace("_dataset", ""): pd.read_csv(raw / f"{f}.csv") for f in FILES}


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * np.arcsin(np.sqrt(a))


def build_orders(t: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, dict]:
    q: dict = {}
    o = t["orders"].copy()
    q["orders_in_source"] = int(len(o))
    for c in DATES:
        o[c] = pd.to_datetime(o[c])

    # ---- items: one row per order ----
    it = t["order_items"].copy()
    it["shipping_limit_date"] = pd.to_datetime(it["shipping_limit_date"])
    pr = t["products"].copy()
    tr = t["product_category_name_translation"].set_index("product_category_name")["product_category_name_english"]
    pr["category"] = pr["product_category_name"].map(tr).fillna(pr["product_category_name"]).fillna("unknown")
    q["products_without_category"] = int(pr["product_category_name"].isna().sum())
    pr["volume_cm3"] = pr["product_length_cm"] * pr["product_height_cm"] * pr["product_width_cm"]
    it = it.merge(pr[["product_id", "category", "product_weight_g", "volume_cm3"]], on="product_id", how="left")
    q["items_without_weight"] = int(it["product_weight_g"].isna().sum())
    agg = it.groupby("order_id").agg(
        items=("order_item_id", "size"), sellers=("seller_id", "nunique"),
        price=("price", "sum"), freight=("freight_value", "sum"),
        weight_kg=("product_weight_g", lambda s: s.sum(min_count=1) / 1000),
        volume_l=("volume_cm3", lambda s: s.sum(min_count=1) / 1000),
        shipping_limit=("shipping_limit_date", "max"),
    )
    first = it.sort_values("order_item_id").groupby("order_id").first()[["seller_id", "category"]]
    o = o.merge(agg, on="order_id", how="left").merge(first, on="order_id", how="left")

    # ---- customers, sellers, distance ----
    cu = t["customers"][["customer_id", "customer_zip_code_prefix", "customer_state", "customer_city"]]
    se = t["sellers"][["seller_id", "seller_zip_code_prefix", "seller_state"]]
    o = o.merge(cu, on="customer_id", how="left").merge(se, on="seller_id", how="left")
    geo = t["geolocation"].groupby("geolocation_zip_code_prefix")[["geolocation_lat", "geolocation_lng"]].median()
    c_ll = geo.reindex(o["customer_zip_code_prefix"]).to_numpy()
    s_ll = geo.reindex(o["seller_zip_code_prefix"]).to_numpy()
    o["distance_km"] = haversine_km(s_ll[:, 0], s_ll[:, 1], c_ll[:, 0], c_ll[:, 1])
    # Brazil is about 4,400 km across; longer distances come from bad coordinates.
    q["impossible_distances_removed"] = int((o["distance_km"] > 4500).sum())
    o.loc[o["distance_km"] > 4500, "distance_km"] = np.nan
    q["orders_without_distance"] = int(o["distance_km"].isna().sum())
    o["customer_region"] = o["customer_state"].map(REGION)
    o["seller_region"] = o["seller_state"].map(REGION)
    o["route"] = o["seller_state"] + " -> " + o["customer_state"]

    # ---- reviews: keep the latest review per order ----
    rv = t["order_reviews"].copy()
    rv["review_answer_timestamp"] = pd.to_datetime(rv["review_answer_timestamp"])
    q["duplicate_reviews_removed"] = int(rv["order_id"].duplicated().sum())
    rv = rv.sort_values("review_answer_timestamp").drop_duplicates("order_id", keep="last")
    o = o.merge(rv[["order_id", "review_score"]], on="order_id", how="left")

    # ---- process stages ----
    hours = lambda a, b: (o[b] - o[a]).dt.total_seconds() / 3600  # noqa: E731
    o["approval_hours"] = hours("order_purchase_timestamp", "order_approved_at")
    o["handling_days"] = hours("order_approved_at", "order_delivered_carrier_date") / 24
    o["transit_days"] = hours("order_delivered_carrier_date", "order_delivered_customer_date") / 24
    o["total_days"] = hours("order_purchase_timestamp", "order_delivered_customer_date") / 24
    o["promised_days"] = hours("order_purchase_timestamp", "order_estimated_delivery_date") / 24
    o["days_late"] = (o["order_delivered_customer_date"].dt.normalize() - o["order_estimated_delivery_date"]).dt.days

    # ---- data quality ----
    q["orders_not_delivered"] = int((o["order_status"] != "delivered").sum())
    q["cancelled_or_unavailable"] = int(o["order_status"].isin(["canceled", "unavailable"]).sum())
    delivered = o["order_status"].eq("delivered")
    q["delivered_missing_a_date"] = int((delivered & o[["order_approved_at", "order_delivered_carrier_date",
                                                         "order_delivered_customer_date"]].isna().any(axis=1)).sum())
    neg_handling = o["handling_days"] < 0
    neg_transit = o["transit_days"] < 0
    q["carrier_date_before_approval"] = int((delivered & neg_handling).sum())
    q["delivered_before_carrier_pickup"] = int((delivered & neg_transit).sum())
    q["orders_without_items"] = int(o["items"].isna().sum())

    o["stage_times_valid"] = (delivered & o[["approval_hours", "handling_days", "transit_days"]].notna().all(axis=1)
                              & ~neg_handling & ~neg_transit)
    o["is_late"] = (o["days_late"] > 0).astype(int)
    o["seller_missed_handoff"] = (o["order_delivered_carrier_date"] > o["shipping_limit"]).astype(int)
    o["month"] = o["order_purchase_timestamp"].dt.to_period("M").dt.to_timestamp()
    o["freight_share"] = o["freight"] / o["price"]

    # The first months (Sep-Dec 2016) have almost no orders and the last weeks
    # (after Aug 2018) are incomplete, so analysis uses Jan 2017 - Aug 2018.
    o["in_window"] = o["month"].between("2017-01-01", "2018-08-01")
    q["orders_outside_jan2017_aug2018"] = int((~o["in_window"]).sum())
    q["delivered_orders_analysed"] = int((o["stage_times_valid"] & o["in_window"]).sum())
    return o, q
