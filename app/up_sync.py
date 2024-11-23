#!/usr/bin/env python3

import os
import sys
import datetime

import requests
from typing import Generator

sys.path.append(os.path.join(os.path.dirname(__file__), "../"))

from app.db import Accounts, Transactions, DB


VERSION = "v1"
URL = f"https://api.up.com.au/api/{VERSION}" if os.environ.get("env") == "prod" else os.environ.get("MOCKSERVER_URL")


class UpSync:
    def __init__(self, token):
        self.token = token
        self.headers = {"Authorization": f"Bearer {self.token}"}
        self.session = DB().session

    def _get_request(self, url: str, extras: dict = {}) -> Generator:
        page = 1
        while True:
            res = requests.get(url, headers=self.headers, **extras)
            res_json = res.json()
            try:
                res.raise_for_status()
            # TODO error handling
            except Exception as e:
                print(e)
                raise e
            print("Successfully fetched", url, "page", page, "extras", extras)
            print("Response-xxxxxx", res_json)
            yield res_json

            if (next_page := res_json.get("links", {}).get("next")):
                url = next_page
                page += 1
                print("Fetching next page", page)
                continue
            print("Finished pagination")
            break

    def _sync_transactions_for_account(self, account: Accounts):
        print("🤝🤝🤝🤝🤝🤝🤝🤝🤝🤝🤝🤝🤝🤝🤝🤝")
        print("Syncing transactions for account", account._mapping["display_name"])
        print("🤝🤝🤝🤝🤝🤝🤝🤝🤝🤝🤝🤝🤝🤝🤝🤝")
        count = 0
        account_id = account._mapping["id"]
        # find the latest transaction date to start pulling from
        since_param = Transactions.max_transaction_date_for_account(self.session, account_id)
        params = {"filter[since]": since_param}
        for record in self._get_request(f"{URL}/accounts/{account_id}/transactions", extras={"params": params}):
            for lst in record.get("data", []):
                transaction = Transactions.parse_transaction(lst, account_id)
                Transactions.insert(self.session, transaction)
                count += 1
        print(f"Successfully synced {count} transactions for account {account_id}")

    def sync_accounts(self):
        print("💳💳💳💳💳💳💳💳💳💳💳💳💳💳💳💳")
        print("Syncing Accounts")
        print("💳💳💳💳💳💳💳💳💳💳💳💳💳💳💳💳")
        count = 0
        for res in self._get_request(f"{URL}/accounts"):
            for lst in res.get("data", []):
                account = Accounts.parse_account(lst)
                Accounts.insert(self.session, account)
                count += 1
        print("💳💳💳💳💳💳💳💳💳💳💳💳💳💳💳💳")
        print(f"Successfully synced {count} accounts")
        print("💳💳💳💳💳💳💳💳💳💳💳💳💳💳💳💳")

    def sync_transactions(self):
        accounts = self.session.query(Accounts.id, Accounts.display_name).all()
        for account in accounts:
            self._sync_transactions_for_account(account)
        pass


    def sync(self):
        print("Starting Sync")
        self.sync_accounts()
        self.sync_transactions()
        print("Sync complete")

if __name__ == "__main__":
    up_sync = UpSync(os.environ["UP_TOKEN"])
    up_sync.sync()
