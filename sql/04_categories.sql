-- Product categories ranked by number of late orders
SELECT category,
       COUNT(*)                          AS orders,
       SUM(is_late)                      AS late_orders,
       ROUND(100.0 * AVG(is_late), 1)    AS delay_pct,
       ROUND(AVG(handling_days), 2)      AS avg_handling_days,
       ROUND(AVG(freight), 2)            AS cost_per_order,
       ROUND(AVG(weight_kg), 2)          AS avg_weight_kg
FROM orders
WHERE analysed = 1
GROUP BY category
HAVING COUNT(*) >= 300
ORDER BY late_orders DESC;
