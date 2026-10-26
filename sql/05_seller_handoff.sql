-- Sellers that hand parcels to the carrier after their deadline most often (50+ orders)
SELECT seller_id,
       seller_state,
       COUNT(*)                                       AS orders,
       ROUND(100.0 * AVG(seller_missed_handoff), 1)   AS handoff_miss_pct,
       ROUND(100.0 * AVG(is_late), 1)                 AS delay_pct,
       ROUND(AVG(handling_days), 2)                   AS avg_handling_days
FROM orders
WHERE analysed = 1
GROUP BY seller_id, seller_state
HAVING COUNT(*) >= 50
ORDER BY handoff_miss_pct DESC
LIMIT 25;
