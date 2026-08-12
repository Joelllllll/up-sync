import asyncio
import datetime
import os
import sys
from unittest.mock import patch

# makes it access the test db instead
os.environ["env"] = "dev"

sys.path.append(os.path.join(os.path.dirname(__file__), "../../"))
import pytest
from sqlalchemy import select

from app import up_sync
from app.clients import Accounts, DBClient, Transactions, UpClient
from app.test.helpers import delete_all_from_tables

ACTION_DATE = "2024-06-06T07:20:59+00:00"


class TestSync:
    def setup_method(self):
        # a fresh session/engine per test - see TestDB.setup_method for why
        self.session = DBClient().session
        # uses mockserver to get data
        asyncio.run(Accounts.sync_accounts(up_sync.UpSync(os.environ["UP_TOKEN"]).client))

    def teardown_method(self):
        asyncio.run(delete_all_from_tables())

    async def test_sync_accounts(self):
        up = up_sync.UpSync(os.environ["UP_TOKEN"])
        await Accounts.sync_accounts(up.client)
        account = await Accounts.from_id(self.session, "123")
        assert account["id"] == "123"
        await self.session.close()
        await up.client.session.close()

    async def test_transaction_sync_with_pagination(self):
        up = up_sync.UpSync(os.environ["UP_TOKEN"])
        await Transactions.sync_transactions(up.client)

        # assert that the values made it into the database
        account = await Accounts.from_id(self.session, "123")
        assert account["id"] == "123"
        account = await Accounts.from_id(self.session, "1234")
        assert account["id"] == "1234"
        transaction = (await self.session.execute(select(Transactions))).scalars().all()
        assert len(transaction) == 3
        await self.session.close()
        await up.client.session.close()

    async def test_transaction_sync_commits_per_page(self):
        "regression test: each page should be committed as it arrives, not batched into one commit for the whole sync"
        up = up_sync.UpSync(os.environ["UP_TOKEN"])
        commit_calls = []
        original_commit = up.client.session.commit

        async def spy_commit():
            commit_calls.append(1)
            return await original_commit()

        up.client.session.commit = spy_commit
        await Transactions.sync_transactions(up.client)

        result = (await self.session.execute(select(Transactions))).scalars().all()
        assert len(result) == 3
        # account 123: 1 page, account 1234: 2 pages (pagination) -> 3 commits
        assert len(commit_calls) == 3
        await self.session.close()
        await up.client.session.close()

    async def test_transaction_sync_with_no_accounts(self):
        "sync_transactions should handle zero accounts in the db without crashing"
        await delete_all_from_tables()
        up = up_sync.UpSync(os.environ["UP_TOKEN"])
        await Transactions.sync_transactions(up.client)
        assert (await self.session.execute(select(Transactions))).scalars().all() == []
        await self.session.close()
        await up.client.session.close()

    async def test_re_sync_is_idempotent(self):
        "regression test: re-syncing the same data twice should not create duplicate rows"
        up = up_sync.UpSync(os.environ["UP_TOKEN"])
        await Transactions.sync_transactions(up.client)
        first_count = len((await self.session.execute(select(Transactions))).scalars().all())

        await Transactions.sync_transactions(up.client)
        second_count = len((await self.session.execute(select(Transactions))).scalars().all())

        assert first_count == second_count == 3
        await self.session.close()
        await up.client.session.close()

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
        assert args.start_date == datetime.datetime(2025, 12, 1, tzinfo=datetime.timezone.utc)
        assert args.end_date == datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
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
