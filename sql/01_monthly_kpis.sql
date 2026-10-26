-- Monthly operational KPIs for delivered orders with valid stage times
SELECT month,
       COUNT(*)                                     AS orders_delivered,
       ROUND(AVG(total_days), 2)                    AS avg_processing_days,
       ROUND(100.0 * (1 - AVG(is_late)), 1)         AS on_time_pct,
       ROUND(100.0 * AVG(is_late), 2)               AS delay_pct,
       ROUND(AVG(freight), 2)                       AS cost_per_order,
       ROUND(100.0 * SUM(freight) / SUM(price), 1)  AS freight_share_pct,
       COUNT(DISTINCT seller_id)                    AS active_sellers
FROM orders
WHERE analysed = 1
GROUP BY month
ORDER BY month;
