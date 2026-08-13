-- Reference queries for Metabase dashboards.
-- Paste each block into Metabase: New Question -> SQL query (native query editor).
-- Not run anywhere automatically -- just a saved copy of what's pasted into the UI.


-- === Account Overview ===

-- Current balance per account
SELECT display_name, account_type, ownership_type, balance
FROM accounts
ORDER BY balance DESC;

-- Running balance over time per account (no daily snapshots exist, so this
-- derives it from the cumulative sum of settled transaction amounts)
SELECT
    a.display_name,
    t.settled_at,
    SUM(t.value_base) OVER (
        PARTITION BY t.account_id ORDER BY t.settled_at
    ) / 100.0 AS running_balance
FROM transactions t
JOIN accounts a ON a.id = t.account_id
WHERE t.status = 'SETTLED'
ORDER BY t.account_id, t.settled_at;

-- Daily balance per account, one row per account per calendar day (line chart)
-- The query above only has a point per transaction, so the chart looks jagged
-- and skips days with no activity. This builds a full daily date spine and
-- forward-fills each account's last known running balance onto it, so the
-- line is continuous even on days nothing happened.
WITH running AS (
    SELECT
        t.account_id,
        t.settled_at,
        SUM(t.value_base) OVER (
            PARTITION BY t.account_id ORDER BY t.settled_at
        ) / 100.0 AS running_balance
    FROM transactions t
    WHERE t.status = 'SETTLED'
),
daily_last AS (
    -- last balance change per account per day
    SELECT DISTINCT ON (account_id, settled_at::date)
        account_id,
        settled_at::date AS day,
        running_balance
    FROM running
    ORDER BY account_id, settled_at::date, settled_at DESC
),
date_spine AS (
    SELECT generate_series(
        (SELECT MIN(settled_at)::date FROM transactions WHERE status = 'SETTLED'),
        CURRENT_DATE,
        '1 day'
    )::date AS day
)
SELECT
    a.display_name,
    ds.day,
    (
        SELECT dl.running_balance
        FROM daily_last dl
        WHERE dl.account_id = a.id AND dl.day <= ds.day
        ORDER BY dl.day DESC
        LIMIT 1
    ) AS balance
FROM accounts a
CROSS JOIN date_spine ds
ORDER BY a.display_name, ds.day;

-- Daily spend per account, one row per account per calendar day (bar chart)
-- Companion to the daily balance query above: zero-fills days with no spend
-- so the chart doesn't just skip quiet days.
WITH daily_spend AS (
    SELECT
        account_id,
        settled_at::date AS day,
        -SUM(value_base) / 100.0 AS spend
    FROM transactions
    WHERE status = 'SETTLED' AND value_base < 0
    GROUP BY 1, 2
),
date_spine AS (
    SELECT generate_series(
        (SELECT MIN(settled_at)::date FROM transactions WHERE status = 'SETTLED'),
        CURRENT_DATE,
        '1 day'
    )::date AS day
)
SELECT
    a.display_name,
    ds.day,
    COALESCE(dsp.spend, 0) AS spend
FROM accounts a
CROSS JOIN date_spine ds
LEFT JOIN daily_spend dsp ON dsp.account_id = a.id AND dsp.day = ds.day
ORDER BY a.display_name, ds.day;

-- Daily net worth, all accounts combined (line or area chart)
-- Same gap-filling as above, summed across accounts per day.
WITH running AS (
    SELECT
        t.account_id,
        t.settled_at,
        SUM(t.value_base) OVER (
            PARTITION BY t.account_id ORDER BY t.settled_at
        ) / 100.0 AS running_balance
    FROM transactions t
    WHERE t.status = 'SETTLED'
),
daily_last AS (
    SELECT DISTINCT ON (account_id, settled_at::date)
        account_id,
        settled_at::date AS day,
        running_balance
    FROM running
    ORDER BY account_id, settled_at::date, settled_at DESC
),
date_spine AS (
    SELECT generate_series(
        (SELECT MIN(settled_at)::date FROM transactions WHERE status = 'SETTLED'),
        CURRENT_DATE,
        '1 day'
    )::date AS day
)
SELECT
    ds.day,
    SUM((
        SELECT dl.running_balance
        FROM daily_last dl
        WHERE dl.account_id = a.id AND dl.day <= ds.day
        ORDER BY dl.day DESC
        LIMIT 1
    )) AS net_worth
FROM accounts a
CROSS JOIN date_spine ds
GROUP BY ds.day
ORDER BY ds.day;

-- Balance split by ownership type (joint vs individual)
SELECT ownership_type, SUM(balance) AS total_balance
FROM accounts
GROUP BY ownership_type;


-- === Cash Flow ===

-- Income vs spend by month
SELECT
    date_trunc('month', settled_at) AS month,
    SUM(value_base) FILTER (WHERE value_base > 0) / 100.0 AS income,
    SUM(value_base) FILTER (WHERE value_base < 0) / 100.0 AS spend
FROM transactions
WHERE status = 'SETTLED'
GROUP BY 1
ORDER BY 1;

-- Net flow trend by month, all accounts combined
SELECT
    date_trunc('month', settled_at) AS month,
    SUM(value_base) / 100.0 AS net_flow
FROM transactions
WHERE status = 'SETTLED'
GROUP BY 1
ORDER BY 1;

-- 7-day rolling average of net daily flow, all accounts combined (line chart)
-- Smooths day-to-day noise so a spending/income trend actually reads on a chart.
WITH daily_net AS (
    SELECT
        settled_at::date AS day,
        SUM(value_base) / 100.0 AS net_flow
    FROM transactions
    WHERE status = 'SETTLED'
    GROUP BY 1
)
SELECT
    day,
    net_flow,
    AVG(net_flow) OVER (
        ORDER BY day
        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ) AS rolling_7day_avg
FROM daily_net
ORDER BY day;

-- Top spend by description (rough proxy for "category" until that field is synced)
SELECT
    description,
    SUM(value_base) / 100.0 AS total_spend,
    COUNT(*) AS transaction_count
FROM transactions
WHERE status = 'SETTLED' AND value_base < 0
GROUP BY description
ORDER BY total_spend ASC
LIMIT 20;


-- === Transaction Activity ===

-- Transaction count by status (sync sanity check)
SELECT status, COUNT(*) AS transaction_count
FROM transactions
GROUP BY status;

-- Transactions per day, all accounts combined (bar or line chart)
SELECT
    settled_at::date AS day,
    COUNT(*) AS transaction_count
FROM transactions
WHERE status = 'SETTLED'
GROUP BY 1
ORDER BY 1;

-- Transactions per account per week
SELECT
    a.display_name,
    date_trunc('week', t.settled_at) AS week,
    COUNT(*) AS transaction_count
FROM transactions t
JOIN accounts a ON a.id = t.account_id
GROUP BY 1, 2
ORDER BY 2, 1;

-- Recent large transactions (threshold in cents; 10000 = $100)
SELECT
    a.display_name,
    t.description,
    t.value_str,
    t.settled_at
FROM transactions t
JOIN accounts a ON a.id = t.account_id
WHERE ABS(t.value_base) > 10000
ORDER BY t.settled_at DESC;


-- === Deeper Insights ===

-- Spend heatmap: day of week x hour of day (Metabase pivot table)
-- Answers "when does the money actually go out", not just how much per day.
-- Sorts Mon->Sun via ISODOW without selecting it, so total_spend is the only
-- numeric column in the output and there's no ambiguity over which field a
-- chart should size/color by.
SELECT
    TO_CHAR(settled_at, 'Dy') AS day_of_week,
    EXTRACT(HOUR FROM settled_at) AS hour_of_day,
    SUM(value_base) / -100.0 AS total_spend
FROM transactions
WHERE status = 'SETTLED' AND value_base < 0
GROUP BY day_of_week, EXTRACT(ISODOW FROM settled_at), hour_of_day
ORDER BY EXTRACT(ISODOW FROM settled_at), hour_of_day;

-- Recurring subscriptions: same description charging the same amount in 3+
-- distinct months (bar chart of monthly cost -- effectively auto-detects
-- what's on autopay without any category field synced from Up)
WITH monthly_charges AS (
    SELECT
        description,
        value_base,
        date_trunc('month', settled_at) AS month
    FROM transactions
    WHERE status = 'SETTLED' AND value_base < 0
    GROUP BY 1, 2, 3
)
SELECT
    description,
    value_base / -100.0 AS charge_amount,
    COUNT(DISTINCT month) AS months_charged
FROM monthly_charges
GROUP BY description, value_base
HAVING COUNT(DISTINCT month) >= 3
ORDER BY months_charged DESC, charge_amount DESC;

-- Outlier transactions: >= 2 standard deviations from that account's average
-- transaction size (scatter chart: x = settled_at, y = z_score)
WITH stats AS (
    SELECT
        account_id,
        AVG(value_base) AS avg_value,
        STDDEV(value_base) AS stddev_value
    FROM transactions
    WHERE status = 'SETTLED'
    GROUP BY account_id
)
SELECT
    a.display_name,
    t.settled_at,
    t.description,
    t.value_str,
    (t.value_base - s.avg_value) / NULLIF(s.stddev_value, 0) AS z_score
FROM transactions t
JOIN stats s ON s.account_id = t.account_id
JOIN accounts a ON a.id = t.account_id
WHERE t.status = 'SETTLED'
  AND ABS((t.value_base - s.avg_value) / NULLIF(s.stddev_value, 0)) >= 2
ORDER BY ABS((t.value_base - s.avg_value) / NULLIF(s.stddev_value, 0)) DESC;

-- Savings rate per month, % of income kept after spend (line chart)
SELECT
    date_trunc('month', settled_at) AS month,
    SUM(value_base) FILTER (WHERE value_base > 0) / 100.0 AS income,
    -SUM(value_base) FILTER (WHERE value_base < 0) / 100.0 AS spend,
    ROUND(
        100.0 * (
            SUM(value_base) FILTER (WHERE value_base > 0)
            + SUM(value_base) FILTER (WHERE value_base < 0)
        ) / NULLIF(SUM(value_base) FILTER (WHERE value_base > 0), 0),
        1
    ) AS savings_rate_pct
FROM transactions
WHERE status = 'SETTLED'
GROUP BY 1
ORDER BY 1;
