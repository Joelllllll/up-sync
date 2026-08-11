# Up Sync

Pulls accounts and transactions from the [Up Bank](https://up.com.au) API and writes them into Postgres, which [Metabase](https://www.metabase.com/) connects to for dashboards: net worth over time, spending by category, that kind of thing. It's a single-run sync script rather than a long-lived service: point it at a schedule (cron, CI, whatever) and it catches up incrementally each run rather than re-pulling everything.

## Architecture

- **`app/up_sync.py`** is the CLI entrypoint: authenticate, then sync accounts, then sync transactions.
- **`app/clients.py`** holds the rest: `UpClient` (talks to the Up API), `DBClient` (Postgres session), and the `Accounts`/`Transactions` SQLAlchemy models, each of which owns its own parse/insert logic rather than there being a separate service layer.
- **Pagination**: the Up API is cursor-based (`links.next` in the response body); both the sync and async clients loop until it's null.
- **Incremental sync**: there's no separate watermark table. Each account's `filter[since]` param is either `--lookback` days ago (if passed), or the latest `created_at` already stored for that account, with a few days' buffer. Up transactions can sit as `HELD` and settle later without their `created_at` changing, so starting from the exact max would miss that settlement.
- **Transactions sync is concurrent**: one coroutine per account via `asyncio.gather`, sharing a single `aiohttp` connection, with all the resulting rows written in one batched commit rather than per-page.
- **Upserts, not inserts**: both models use `session.merge()` keyed on `id`, so re-running the sync over overlapping data is idempotent.

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
