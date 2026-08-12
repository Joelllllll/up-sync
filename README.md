# Up Sync

Pulls accounts and transactions from the [Up Bank](https://up.com.au) API and writes them into Postgres, which [Metabase](https://www.metabase.com/) connects to for dashboards: net worth over time, spending by category, that kind of thing. It's a single-run sync script rather than a long-lived service: point it at a schedule (cron, CI, whatever) and it catches up incrementally each run rather than re-pulling everything.

## Architecture

- **`app/up_sync.py`** is the CLI entrypoint: authenticate, then sync accounts, then sync transactions.
- **`app/clients.py`** holds the rest: `UpClient` (talks to the Up API), `DBClient` (Postgres session), and the `Accounts`/`Transactions` SQLAlchemy models, each of which owns its own parse/insert logic rather than there being a separate service layer.
- **Pagination**: the Up API is cursor-based (`links.next` in the response body); both the sync and async clients loop until it's null.
- **Incremental sync**: there's no separate watermark table. Each account's `filter[since]` param is `--start-date` (if passed), else `--lookback` days ago (if passed), else the latest `created_at` already stored for that account, with a few days' buffer. Up transactions can sit as `HELD` and settle later without their `created_at` changing, so starting from the exact max would miss that settlement.
- **Transactions sync is concurrent**: one coroutine per account via `asyncio.gather`, sharing a single `aiohttp` connection. With `--async`, each account's range is further split into windows (`--window-days`, default 7) fetched concurrently (bounded by a semaphore) instead of one cursor-paginated request per account. Rows are batch-inserted and committed as each page arrives, not buffered until the end.
- **Upserts, not inserts**: both models use `session.merge()` keyed on `id`, so re-running the sync over overlapping data is idempotent.
- **Rate limit handling**: a 429 from Up is retried with its own escalating backoff (`RATE_LIMIT_BACKOFF_SECONDS` = 60s, 300s, 20 min, 1 hour) separate from the general retry/backoff used for other request failures. Up doesn't give how long until the rate limit resets so I've chosen this aggressive exponential backoff to prevent crashing

## Running

Build the image first:
```shell
docker compose build
```

### 1. Start everything (testing: app, postgres, metabase, mockserver)
```shell
docker compose --profile metabase --profile mockserver up -d
```
Then run the tests:
```shell
docker compose exec app pytest
```
Metabase UI: `http://localhost:3000`

### 2. Start just enough to pull in data (app + postgres)
```shell
docker compose run app bash
```
Inside the container:
```shell
export UP_TOKEN="xxxxxxxx"
./app/up_sync.py --lookback 100
```
The `lookback` config is in days and is optional (default 30). This syncs accounts + transactions into the `accounts`/`transactions` tables.

Add `--async` to split each account's transaction fetch into windows fetched concurrently instead of one cursor-paginated request per account. Window size defaults to 7 days, override with `--window-days`. Leave it at the default for typical low-volume accounts; drop it lower (e.g. 1) for an account with a lot of transactions to pull, so more windows are in flight at once instead of one big window paginating through sequentially.

Use `--start-date`/`--end-date` (`YYYY-MM-DD`, start inclusive, end exclusive) instead of `--lookback` to pull a specific date range rather than up to now, e.g. to get just December:
```shell
./app/up_sync.py --start-date 2025-12-01 --end-date 2026-01-01
```
`--start-date`/`--end-date` must be used together, and can't be combined with `--lookback`.


## Todo
- [ ] Config to change output format (postgres, csv dump, pyspark delta tables)
- [ ] Consume all transaction fields
- [ ] Consume all other streams
    - [ ] Categories
    - [ ] Tags
    - [ ] Attachments
- [ ] Sync individual streams
- [ ] implement UV package manager
- [ ] better error handling for requests
