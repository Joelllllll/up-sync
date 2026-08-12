import datetime
import os
import sys
from unittest.mock import patch

# makes it access the test db instead
os.environ["env"] = "dev"

sys.path.append(os.path.join(os.path.dirname(__file__), "../../"))

import pytest_asyncio
from sqlalchemy import select

from app.clients import Accounts, DBClient, Transactions, UpClient
from app.test.helpers import delete_all_from_tables, setup_test_db


class TestDB:
    @pytest_asyncio.fixture(scope="class", autouse=True)
    async def clean_tables(self):
        await delete_all_from_tables()
        yield
        await delete_all_from_tables()

    @pytest_asyncio.fixture(autouse=True)
    async def db_session(self):
        # a fresh session/engine per test, not shared across tests - each async test
        # runs in its own event loop, and an async engine's pooled connections are
        # tied to whichever loop first used them
        self.session = DBClient().session
        yield
        await self.session.close()

    def test_dev_db_string(self):
        assert DBClient.db_string() == "postgresql+asyncpg://postgres:postgres@postgres:5432/test"

    def test_prod_db_string(self):
        os.environ["env"] = "prod"
        assert DBClient.db_string() == "postgresql+asyncpg://postgres:postgres@postgres:5432/postgres"
        os.environ["env"] = "dev"

    async def test_insert_account(self):
        account = Accounts(
            id="123",
            display_name="display name",
            account_type="test",
            ownership_type="test",
            balance=1.0,
            currency="AUD",
            value_str="1.0",
            value_base=100,
            created_at=datetime.datetime.fromisoformat("2024-06-06T07:20:59+00:00"),
        )
        await Accounts.insert(self.session, account)
        result = await self.session.execute(select(Accounts).where(Accounts.id == "123"))
        q = result.scalar_one_or_none()

        assert q.id == account.id
        assert q.display_name == account.display_name
        assert q.account_type == account.account_type
        assert q.ownership_type == account.ownership_type
        assert q.balance == account.balance
        assert q.currency == account.currency
        assert q.value_str == account.value_str
        assert q.value_base == account.value_base
        assert q.created_at.__str__() == "2024-06-06 07:20:59+00:00"

    async def test_insert_transaction(self):
        transaction = Transactions(
            id="123",
            account_id="123",
            status="SETTLED",
            raw_text=None,
            description="test",
            message="test",
            categorizable=True,
            currency="AUD",
            value_str="1.0",
            value_base=100,
            card_purchase_suffix="12345",
            settled_at=datetime.datetime.fromisoformat("2024-06-06T07:20:59+00:00"),
            created_at=datetime.datetime.fromisoformat("2024-06-06T07:20:59+00:00"),
        )
        await Transactions.insert(self.session, transaction)
        result = await self.session.execute(select(Transactions).where(Transactions.id == "123"))
        q = result.scalar_one_or_none()

        assert q.id == transaction.id
        assert q.account_id == transaction.account_id
        assert q.status == transaction.status
        assert q.raw_text == transaction.raw_text
        assert q.description == transaction.description
        assert q.message == transaction.message
        assert q.categorizable == transaction.categorizable
        assert q.currency == transaction.currency
        assert q.value_str == transaction.value_str
        assert q.value_base == transaction.value_base
        assert q.card_purchase_suffix == transaction.card_purchase_suffix
        assert q.settled_at.__str__() == "2024-06-06 07:20:59+00:00"
        assert q.created_at.__str__() == "2024-06-06 07:20:59+00:00"


class TestTransactions:
    @pytest_asyncio.fixture(autouse=True)
    async def db_session(self):
        self.session = DBClient().session
        yield
        await self.session.close()

    async def test_max_transaction_date_for_account_no_transactions(self):
        "this should default to 30 days ago"
        fixed_now = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)  # match your freeze_time date

        class FixedDateTime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed_now if tz is None else fixed_now.astimezone(tz)

        with patch("datetime.datetime", FixedDateTime):
            for account_id in ("123", "321"):
                result = await Transactions.max_transaction_date_for_account(self.session, account_id)
                assert result == "2023-12-02T00:00:00+00:00"

    async def test_max_transaction_date_for_account(self):
        await setup_test_db()
        assert await Transactions.max_transaction_date_for_account(self.session, "123") == "2023-12-27T00:00:00+00:00"
        assert await Transactions.max_transaction_date_for_account(self.session, "321") == "2021-12-27T00:00:00+00:00"

    async def test_determine_account_filter_since_param(self):
        "Use days ago if present"
        await setup_test_db()
        lookback = 7
        client = UpClient(os.environ["UP_TOKEN"], lookback=lookback)
        date_result = await Transactions.determine_account_filter_since_param(client, "123", self.session)
        assert date_result.split("T")[0] == (datetime.datetime.today() - datetime.timedelta(days=lookback)).strftime(
            "%Y-%m-%d"
        )
        await client.session.close()

    async def test_determine_account_filter_since_param_no_lookback(self):
        "Use days ago if present, else check the earliest date for the account"
        await setup_test_db()
        client = UpClient(os.environ["UP_TOKEN"])
        date_result = await Transactions.determine_account_filter_since_param(client, "123", self.session)
        assert date_result == "2023-12-27T00:00:00+00:00"
        await client.session.close()

    async def test_determine_account_filter_since_param_start_date_takes_precedence(self):
        "start_date should win over lookback and over the account's last transaction date"
        await setup_test_db()
        start_date = datetime.datetime(2025, 12, 1)
        client = UpClient(os.environ["UP_TOKEN"], lookback=7, start_date=start_date)
        date_result = await Transactions.determine_account_filter_since_param(client, "123", self.session)
        assert date_result == "2025-12-01T00:00:00+00:00"
        await client.session.close()

    async def test_determine_account_filter_until_param_with_end_date(self):
        client = UpClient(os.environ["UP_TOKEN"], end_date=datetime.datetime(2026, 1, 1))
        assert Transactions.determine_account_filter_until_param(client) == "2026-01-01T00:00:00+00:00"
        await client.session.close()

    async def test_determine_account_filter_until_param_no_end_date(self):
        client = UpClient(os.environ["UP_TOKEN"])
        assert Transactions.determine_account_filter_until_param(client) is None
        await client.session.close()

    def test_day_windows_respects_until(self):
        "windows should stop at the given until instead of running to now"
        since = "2025-12-01T00:00:00+00:00"
        until = "2025-12-15T00:00:00+00:00"
        windows = Transactions._day_windows(since, window_days=7, until=until)
        assert windows == [
            ("2025-12-01T00:00:00+00:00", "2025-12-08T00:00:00+00:00"),
            ("2025-12-08T00:00:00+00:00", "2025-12-15T00:00:00+00:00"),
        ]

    def test_day_windows_defaults_to_now_without_until(self):
        fixed_now = datetime.datetime(2025, 12, 10)

        class FixedDateTime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed_now if tz is None else fixed_now.astimezone(tz)

        since = "2025-12-01T00:00:00+00:00"
        with patch("datetime.datetime", FixedDateTime):
            windows = Transactions._day_windows(since, window_days=7)
        assert windows == [
            ("2025-12-01T00:00:00+00:00", "2025-12-08T00:00:00+00:00"),
            ("2025-12-08T00:00:00+00:00", "2025-12-10T00:00:00+00:00"),
        ]


class TestUpClient:
    async def test_authenticate(self):
        client = UpClient(os.environ["UP_TOKEN"], lookback=7)
        client.authenticate()
        await client.session.close()

    def test_authenticate_fail(self):
        try:
            UpClient("bad_token", lookback=7).authenticate()
        except UpClient.UpAuthError:
            return
        assert False
