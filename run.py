"""Run the whole analysis: clean -> SQL -> KPIs -> bottlenecks -> root causes -> statistics -> exports."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
from opsrc import analysis as an, data, export, warehouse  # noqa: E402


def main() -> None:
    orders, quality = data.build_orders(data.load(data.download()))
    print("Quality:", quality)
    a = an.analysed(orders)

    con = warehouse.build(orders)
    sql = warehouse.run_queries(con)
    con.close()

    kpis = an.headline_kpis(a, orders)
    monthly = an.monthly_kpis(orders)
    stages = an.stage_breakdown(a)
    late = an.classify_root_causes(a)
    causes = an.pareto(late["root_cause"])
    concentration = {k: an.concentration(late, a, k) for k in ("seller_id", "route", "category", "customer_state")}
    sellers = an.seller_scorecard(a)
    regions = an.group_compare(a, "customer_region")
    states = an.group_compare(a, "customer_state")
    categories = an.group_compare(a, "category").sort_values("orders", ascending=False)
    tests = an.hypothesis_tests(a)
    corr = an.correlations(a)
    reg = an.regressions(a)

    print(kpis)
    print(causes)
    print({k: v["share_of_groups_pct"] for k, v in concentration.items()})
    for t in tests:
        print(t["hypothesis"], "|", t["result"], "| p =", f"{t['p_value']:.2g}")
    print(reg["cost_decomposition"])

    headline = export.write_all(orders=orders, a=a, quality=quality, kpis=kpis, monthly=monthly, stages=stages,
                                late=late, pareto_causes=causes, concentration=concentration, sellers=sellers,
                                regions=regions, states=states, categories=categories, routes=None, tests=tests,
                                corr=corr, reg=reg, sql=sql)
    print(json.dumps({k: headline[k] for k in ("share_of_extra_days", "top_two_causes_pct", "peak_delay_month")}, indent=1))


if __name__ == "__main__":
    main()
