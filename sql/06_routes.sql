-- Seller-state to customer-state routes with the most late orders
SELECT route,
       COUNT(*)                        AS orders,
       SUM(is_late)                    AS late_orders,
       ROUND(100.0 * AVG(is_late), 1)  AS delay_pct,
       ROUND(AVG(transit_days), 1)     AS avg_transit_days,
       ROUND(AVG(distance_km), 0)      AS avg_distance_km
FROM orders
WHERE analysed = 1
GROUP BY route
ORDER BY late_orders DESC
LIMIT 20;
