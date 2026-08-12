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
