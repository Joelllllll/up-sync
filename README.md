# Up Sync

## Running
Build the docker image
```shell
docker-compose build
```
Bring up the docker containers,
This will start the `app` and `postgres` containers.

```shell
docker-compose run app bash
```

If you wish to bring up the `metabase` (for UI) or the `mockserver` (for testing) containers, you'll need to use `--profile` with compose up

to run the tests
```shell
docker-compose up --profile mockserver
```

You'll need to export your UP token as a ENV variable

```shell
export UP_TOKEN="xxxxxxxx"
```

```shell
./up_sync.py --lookback 100
```

This will sync all accounts and their transactions into an `accounts` and `transactions` table in the database \
The `lookback` config is in days and is optional. The default lookback period is 30 days

You can access the metabase dashboard at `http://localhost:3000` to view the data


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
