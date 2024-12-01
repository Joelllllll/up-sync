# Up Sync


Build the docker image
```shell
 main ~/up-sync 🍆💦 docker-compose build
```

Run the image
This will bring up the app, database and metabase containers
```shell
 main ~/up-sync 🍆💦 docker-compose up
```

You can shell into the app container and run the sync

```shell
 main ~/up-sync 🍆💦 docker-compose exec app bash
```

```shell
 root@f4b4b4b4b4b4:/app#  ./up_sync.py
```

This will sync all accounts and their transactions into an `accounts` and `transactions` table in the database
The default lookback period is 30 days

You can access the metabase dashboard at `http://localhost:3000` to view the data
