-- =============================================================
-- BFA-Scout — Find ALL passport holders (bahraini + origin_country)
-- =============================================================
-- Run on PROD to confirm the players-list badge fix visually: every row this
-- returns should now show its "Eligible in Xy Ym" countdown (or "Eligible now"
-- if 5 years from residency-start has passed) on the players-list cards —
-- NOT the "Citizen" badge. (Juninho, Soufian Mahrouq, Vinícius Vargas, etc.)
--
-- A passport holder = nationality_status='bahraini' AND origin_country set.
-- Read-only.
-- =============================================================

SELECT id,
       full_name,
       nationality_status,
       nationality_code,
       origin_country,
       origin_country_code,
       bahrain_residency_start_date,
       eligible_from_date,
       -- expected display: NULL residency → "date not set"; else the 5y mark
       (bahrain_residency_start_date + INTERVAL '5 years')::date AS eligible_on_5y,
       CASE
         WHEN bahrain_residency_start_date IS NULL AND eligible_from_date IS NULL
           THEN 'pending — residency start not set'
         WHEN COALESCE(eligible_from_date,
                       bahrain_residency_start_date + INTERVAL '5 years') <= CURRENT_DATE
           THEN 'eligible now'
         ELSE 'counting down (Eligible in Xy Ym)'
       END AS expected_badge
FROM   players
WHERE  is_active = TRUE
  AND  nationality_status = 'bahraini'
  AND  origin_country IS NOT NULL
ORDER  BY full_name;
