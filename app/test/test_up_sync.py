import os
import sys

import secrets
import requests
import json

# makes it access the test db instead
os.environ["env"] = "dev"

sys.path.append(os.path.join(os.path.dirname(__file__), "../../"))
from app import up_sync
from app.clients import DBClient, Accounts, Transactions
from app.test.test_db import delete_all_from_tables

ACTION_DATE = "2024-06-06T07:20:59+00:00"

## I don't use these anymore but I'll leave them here for now
BASE_TRANSACTION_ATTRIBUTES = {
    "status": "SETTLED",
    "rawText": None,
    "description": "David Taylor",
    "message": "Money for the pizzas last night.",
    "isCategorizable": True,
    "holdInfo": None,
    "roundUp": None,
    "cashback": None,
    "amount": {
        "currencyCode": "AUD",
        "value": "-59.98",
        "valueInBaseUnits": -5998
    },
    "foreignAmount": None,
    "cardPurchaseMethod": {
        "cardNumberSuffix": "1234"
    },
    "settledAt": ACTION_DATE,
    "createdAt": ACTION_DATE

}

def generate_single_transaction(kwargs: dict = {}) -> dict:
    return {
        "type": "transactions",
        "id": secrets.token_hex(4),
        "attributes": {
            **{**BASE_TRANSACTION_ATTRIBUTES, **kwargs}
        }

    }


def generate_transaction_response(transactions: list, account_id: str, paginate: bool = False) -> dict:
    links = {
            "prev": None,
            "next": None
        }
    if paginate:
        links["next"] = f"{up_sync.URL}/accounts/{account_id}/transactions?page=2"
    return {
        "data": transactions,
        "links": links
    }

class TestSync:
    session = DBClient().session
    def teardown_method(self):
        delete_all_from_tables()

    def setup_method(self):
        # uses mockserver to get data
        up_sync.UpSync("token").sync_accounts()


    def test_sync_accounts(self):
        up_sync.UpSync("token").sync_accounts()
        account = Accounts.from_id(self.session, "123")
        assert account.id == "123"

    def test_transaction_sync_with_pagination(self):
        up_sync.UpSync("token").sync_transactions()

        # assert that the values made it into the database
        account = Accounts.from_id(self.session, "123")
        assert account.id == "123"
        account = Accounts.from_id(self.session, "1234")
        assert account.id == "1234"
        transaction = self.session.query(Transactions).all()
        assert len(transaction) == 3

