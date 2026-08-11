# Up Sync

## Running

Build the image first:
```shell
docker compose build
```

### 1. Start everything (testing — app, postgres, metabase, mockserver)
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
