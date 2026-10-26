-- Average time spent in each process stage, late vs on-time orders
SELECT CASE WHEN is_late = 1 THEN 'Late' ELSE 'On time' END AS delivery,
       COUNT(*)                          AS orders,
       ROUND(AVG(approval_hours) / 24, 2) AS approval_days,
       ROUND(AVG(handling_days), 2)      AS seller_handling_days,
       ROUND(AVG(transit_days), 2)       AS carrier_transit_days,
       ROUND(AVG(total_days), 2)         AS total_days
FROM orders
WHERE analysed = 1
GROUP BY delivery;
