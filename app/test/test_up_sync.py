import datetime
import os
import secrets
import sys
from unittest.mock import patch

# makes it access the test db instead
os.environ["env"] = "dev"

sys.path.append(os.path.join(os.path.dirname(__file__), "../../"))
import aiohttp
import pytest

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

    def test_transaction_sync_commits_per_page(self):
        "regression test: each page should be committed as it arrives, not batched into one commit for the whole sync"
        up = up_sync.UpSync(os.environ["UP_TOKEN"])
        commit_calls = []
        original_commit = up.client.session.commit

        def spy_commit():
            commit_calls.append(1)
            return original_commit()

        up.client.session.commit = spy_commit
        up.sync_transactions()

        assert len(self.session.query(Transactions).all()) == 3
        # account 123: 1 page, account 1234: 2 pages (pagination) -> 3 commits
        assert len(commit_calls) == 3

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


class TestParseArgs:
    def test_start_and_end_date_parsed(self):
        with patch("sys.argv", ["up_sync.py", "--start-date", "2025-12-01", "--end-date", "2026-01-01"]):
            args = up_sync.parse_args()
        assert args.start_date == datetime.datetime(2025, 12, 1)
        assert args.end_date == datetime.datetime(2026, 1, 1)
        assert args.lookback is None

    def test_lookback_alone_still_works(self):
        with patch("sys.argv", ["up_sync.py", "--lookback", "30"]):
            args = up_sync.parse_args()
        assert args.lookback == 30
        assert args.start_date is None
        assert args.end_date is None

    def test_no_args_still_works(self):
        with patch("sys.argv", ["up_sync.py"]):
            args = up_sync.parse_args()
        assert args.lookback is None
        assert args.start_date is None
        assert args.end_date is None

    def test_lookback_and_start_date_rejected(self):
        argv = ["up_sync.py", "--lookback", "30", "--start-date", "2025-12-01", "--end-date", "2026-01-01"]
        with patch("sys.argv", argv), pytest.raises(SystemExit):
            up_sync.parse_args()

    def test_lookback_and_end_date_rejected(self):
        argv = ["up_sync.py", "--lookback", "30", "--end-date", "2026-01-01"]
        with patch("sys.argv", argv), pytest.raises(SystemExit):
            up_sync.parse_args()

    def test_start_date_without_end_date_rejected(self):
        with patch("sys.argv", ["up_sync.py", "--start-date", "2025-12-01"]), pytest.raises(SystemExit):
            up_sync.parse_args()

    def test_end_date_without_start_date_rejected(self):
        with patch("sys.argv", ["up_sync.py", "--end-date", "2026-01-01"]), pytest.raises(SystemExit):
            up_sync.parse_args()

    def test_invalid_date_format_rejected(self):
        argv = ["up_sync.py", "--start-date", "01-12-2025", "--end-date", "2026-01-01"]
        with patch("sys.argv", argv), pytest.raises(SystemExit):
            up_sync.parse_args()
