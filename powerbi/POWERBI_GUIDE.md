# Power BI dashboard: build guide

`python run.py` writes the tables below to `powerbi/data/`. This guide builds the report in Power BI Desktop (about 30 minutes).

## 1. Load the data

**Get data → Text/CSV** for each file:

| Table | Grain | Used for |
| --- | --- | --- |
| `fact_orders` | one delivered order (94,819 rows) | every KPI, stage times, root cause, region, category, route |
| `dim_seller` | one seller | seller state, late rate, hand-off miss rate, excess late orders |
| `monthly_kpis` | one month | trend lines (already aggregated) |
| `root_cause_pareto` | one cause | Pareto chart |
| `hypothesis_tests` | one test | statistics page |
| `regression_coefficients` | one factor per model | statistics page |

Date table (**Modeling → New table**), marked as the date table:

```DAX
dim_date = ADDCOLUMNS ( CALENDAR ( DATE ( 2017, 1, 1 ), DATE ( 2018, 8, 31 ) ),
    "Year", YEAR ( [Date] ), "Month", FORMAT ( [Date], "MMM YYYY" ), "MonthStart", DATE ( YEAR ( [Date] ), MONTH ( [Date] ), 1 ),
    "IsBlackFriday", [Date] >= DATE ( 2017, 11, 20 ) && [Date] <= DATE ( 2017, 12, 3 ) )
```

**Stage table:** in Power Query, duplicate `fact_orders`, keep `order_key`, `is_late`, `approval_hours`, `handling_days`, `transit_days`, convert `approval_hours` to days, then **Unpivot columns** into `stage` / `days`. This gives the process-stage bottleneck visual.

## 2. Relationships

- `dim_seller[seller_key]` 1 → * `fact_orders[seller_key]`
- `dim_date[Date]` 1 → * `fact_orders[order_date]`
- `fact_stages[order_key]` * → 1 `fact_orders[order_key]` (single direction)

## 3. Measures

Create a `_Measures` table and paste [`measures.dax`](measures.dax).

## 4. Report pages

| Page | Visuals | KPI |
| --- | --- | --- |
| **Overview** | KPI cards; delay rate by month (column, red when above 10%); processing vs promised days (line) | Avg processing time, On-time completion rate, Cost per transaction, Delay rate |
| **Process bottlenecks** | stage days, late vs on time (clustered bar from `fact_stages`); stage days by month (line); processing time histogram (bins of 3 days) | Process-stage bottlenecks |
| **Root causes** | Pareto: `Late Orders by Cause` columns + `Cumulative Cause Share %` line; causes by month (stacked column); seller table sorted by `Excess Late Orders` | Root cause breakdown |
| **Comparisons** | delay rate by customer region and state (bar, map); categories and routes tables; slicers for region, category and seller state | Delay rate, Cost per transaction |
| **Cost** | cost per transaction by month (line); freight share of value; cost by region | Cost per transaction |
| **Statistics** | `hypothesis_tests` table; `regression_coefficients` table filtered by model; scatter of distance vs total days | |

Add drill-through from a seller row to an order-level page, and a **IsBlackFriday** slicer to compare the peak with normal weeks.

Save as `powerbi/Operations_Root_Cause.pbix`.
