# Up Sync

## Running
Build the docker image
```shell
 main ~/up-sync 🍆💦 docker-compose build
```
Bring up the docker containers,
This will start the `app`, `postgres` and `metabase` containers (as well as `mockserver` used only for testing), credentials are in the `variables.env` file in `app/`

```shell
 main ~/up-sync 🍆💦 docker-compose up
```

You can shell into the app container and run the sync

```shell
 main ~/up-sync 🍆💦 docker-compose exec app bash
```

```shell
 root@f4b4b4b4b4b4:/app#  ./up_sync.py --lookback 100
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
