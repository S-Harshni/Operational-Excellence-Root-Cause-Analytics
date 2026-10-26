"""SQLite warehouse for the order table and the SQL analyses in sql/."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

DB_PATH = Path("data/operations.db")
COLUMNS = ["order_id", "order_status", "month", "order_purchase_timestamp", "customer_state", "customer_region",
           "seller_id", "seller_state", "route", "category", "items", "sellers", "price", "freight", "weight_kg",
           "volume_l", "distance_km", "approval_hours", "handling_days", "transit_days", "total_days",
           "promised_days", "days_late", "is_late", "seller_missed_handoff", "review_score", "analysed"]


def build(orders: pd.DataFrame, path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    t = orders.assign(analysed=(orders["stage_times_valid"] & orders["in_window"]).astype(int))[COLUMNS].copy()
    t["month"] = t["month"].dt.strftime("%Y-%m")
    t["order_purchase_timestamp"] = t["order_purchase_timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
    con = sqlite3.connect(path)
    t.to_sql("orders", con, index=False)
    con.execute("CREATE INDEX idx_orders_seller ON orders(seller_id)")
    con.commit()
    return con


def run_queries(con: sqlite3.Connection, sql_dir: Path = Path("sql")) -> dict[str, pd.DataFrame]:
    return {f.stem[3:]: pd.read_sql_query(f.read_text(), con) for f in sorted(sql_dir.glob("*.sql"))}
