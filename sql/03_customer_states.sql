-- Delay rate, speed and cost by customer state (states with at least 300 orders)
SELECT customer_state,
       customer_region,
       COUNT(*)                        AS orders,
       ROUND(100.0 * AVG(is_late), 1)  AS delay_pct,
       ROUND(AVG(total_days), 1)       AS avg_processing_days,
       ROUND(AVG(transit_days), 1)     AS avg_transit_days,
       ROUND(AVG(freight), 2)          AS cost_per_order
FROM orders
WHERE analysed = 1
GROUP BY customer_state, customer_region
HAVING COUNT(*) >= 300
ORDER BY delay_pct DESC;
