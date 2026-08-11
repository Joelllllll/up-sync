import os
import secrets
import sys
from unittest.mock import patch

# makes it access the test db instead
os.environ["env"] = "dev"

sys.path.append(os.path.join(os.path.dirname(__file__), "../../"))
import aiohttp

from app import up_sync
from app.clients import Accounts, DBClient, Transactions, UpClient
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
    "amount": {"currencyCode": "AUD", "value": "-59.98", "valueInBaseUnits": -5998},
    "foreignAmount": None,
    "cardPurchaseMethod": {"cardNumberSuffix": "1234"},
    "settledAt": ACTION_DATE,
    "createdAt": ACTION_DATE,
}


def generate_single_transaction(kwargs: dict = {}) -> dict:
    return {
        "type": "transactions",
        "id": secrets.token_hex(4),
        "attributes": {**{**BASE_TRANSACTION_ATTRIBUTES, **kwargs}},
    }


def generate_transaction_response(transactions: list, account_id: str, paginate: bool = False) -> dict:
    links = {"prev": None, "next": None}
    if paginate:
        links["next"] = f"{up_sync.URL}/accounts/{account_id}/transactions?page=2"
    return {"data": transactions, "links": links}


class TestSync:
    session = DBClient().session

    def teardown_method(self):
        delete_all_from_tables()

    def setup_method(self):
        # uses mockserver to get data
        up_sync.UpSync(os.environ["UP_TOKEN"]).sync_accounts()

    def test_sync_accounts(self):
        up_sync.UpSync(os.environ["UP_TOKEN"]).sync_accounts()
        account = Accounts.from_id(self.session, "123")
        assert account.id == "123"

    def test_transaction_sync_with_pagination(self):
        up_sync.UpSync(os.environ["UP_TOKEN"]).sync_transactions()

        # assert that the values made it into the database
        account = Accounts.from_id(self.session, "123")
        assert account.id == "123"
        account = Accounts.from_id(self.session, "1234")
        assert account.id == "1234"
        transaction = self.session.query(Transactions).all()
        assert len(transaction) == 3

    def test_transaction_sync_reuses_a_single_http_session(self):
        "regression test: requests must share one connection instead of opening a new one per page/account"
        real_client_session = aiohttp.ClientSession
        created = []

        def spy(*args, **kwargs):
            session = real_client_session(*args, **kwargs)
            created.append(session)
            return session

        with patch("app.clients.aiohttp.ClientSession", side_effect=spy):
            up_sync.UpSync(os.environ["UP_TOKEN"]).sync_transactions()

        # 2 accounts, one of which paginates, should still only open a single session
        assert len(created) == 1

    def test_transaction_sync_batches_inserts_into_a_single_commit(self):
        "regression test: transactions should be committed in one batch, not one commit per row"
        up = up_sync.UpSync(os.environ["UP_TOKEN"])
        commit_calls = []
        original_commit = up.client.session.commit

        def spy_commit():
            commit_calls.append(1)
            return original_commit()

        up.client.session.commit = spy_commit
        up.sync_transactions()

        assert len(self.session.query(Transactions).all()) == 3
        assert len(commit_calls) == 1

    def test_transaction_sync_with_no_accounts(self):
        "sync_transactions should handle zero accounts in the db without crashing"
        delete_all_from_tables()
        up_sync.UpSync(os.environ["UP_TOKEN"]).sync_transactions()
        assert self.session.query(Transactions).all() == []

    def test_re_sync_is_idempotent(self):
        "regression test: re-syncing the same data twice should not create duplicate rows"
        up = up_sync.UpSync(os.environ["UP_TOKEN"])
        up.sync_transactions()
        first_count = len(self.session.query(Transactions).all())

        up.sync_transactions()
        second_count = len(self.session.query(Transactions).all())

        assert first_count == second_count == 3

    def test_ping(self):
        for res in UpClient(os.environ["UP_TOKEN"])._get_request("/util/ping"):
            assert res == {
                "meta": {
                    "id": "2a6e40c9-31ef-4b43-af2f-b71c60747993",
                    "statusEmoji": "⚡️",
                },
            }
