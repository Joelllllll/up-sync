import sys
import os
from datetime import datetime, timedelta

from freezegun import freeze_time

# makes it access the test db instead
os.environ["env"] = "dev"

sys.path.append(os.path.join(os.path.dirname(__file__), "../../"))

from app.clients import DBClient, Accounts, Transactions, UpClient
from app.test.helpers import delete_all_from_tables, setup_test_db
from sqlalchemy import MetaData, Table


class TestDB:
    session = DBClient().session
    def teardown_class(cls):
        delete_all_from_tables()

    def setup_class(cls):
        delete_all_from_tables()

    def test_dev_db_string(self):
        assert DBClient.db_string() == "postgresql://postgres:postgres@postgres:5432/test"

    def test_prod_db_string(self):
        os.environ["env"] = "prod"
        assert DBClient.db_string() == "postgresql://postgres:postgres@postgres:5432/postgres"
        os.environ["env"] = "dev"


    def test_insert_account(self):
        account = Accounts(
            id="123",
            display_name="display name",
            account_type="test",
            ownership_type="test",
            balance=1.0,
            currency="AUD",
            value_str="1.0",
            value_base=100,
            created_at="2024-06-06T07:20:59+00:00"
        )
        Accounts.insert(self.session, account)
        q = self.session.query(Accounts).filter(Accounts.id == "123").first()

        assert q.id == account.id
        assert q.display_name == account.display_name
        assert q.account_type == account.account_type
        assert q.ownership_type == account.ownership_type
        assert q.balance == account.balance
        assert q.currency == account.currency
        assert q.value_str == account.value_str
        assert q.value_base == account.value_base
        assert q.created_at.__str__() == "2024-06-06 07:20:59"

    def test_insert_transaction(self):
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
            settled_at="2024-06-06T07:20:59+00:00",
            created_at="2024-06-06T07:20:59+00:00"
        )
        Transactions.insert(self.session, transaction)
        q = self.session.query(Transactions).filter(Transactions.id == "123").first()

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
        assert q.settled_at.__str__() == "2024-06-06 07:20:59"
        assert q.created_at.__str__() == "2024-06-06 07:20:59"


class TestTransactions:

    @freeze_time("2024-01-01")
    def test_max_transaction_date_for_account_no_transactions(self):
        "this should default to 30 days ago"
        assert Transactions.max_transaction_date_for_account(self.session, "123") == "2023-12-02T00:00:00+00:00"
        assert Transactions.max_transaction_date_for_account(self.session, "321") == "2023-12-02T00:00:00+00:00"

    session = DBClient().session
    def test_min_transaction_date_for_account(self):
        setup_test_db()
        assert Transactions.min_transaction_date_for_account(self.session, "123") == "2020-01-01T00:00:00+00:00"
        assert Transactions.min_transaction_date_for_account(self.session, "321") == "2020-01-01T00:00:00+00:00"

    def test_max_transaction_date_for_account(self):
        setup_test_db()
        assert Transactions.max_transaction_date_for_account(self.session, "123") == "2024-01-01T00:00:00+00:00"
        assert Transactions.max_transaction_date_for_account(self.session, "321") == "2022-01-01T00:00:00+00:00"

    def test_determine_account_filter_since_param(self):
        "Use days ago if present"
        setup_test_db()
        lookback = 7
        client = UpClient(os.environ["UP_TOKEN"], lookback=lookback)
        date_result = Transactions.determine_account_filter_since_param(client, "123", self.session)
        assert date_result.split("T")[0] == (datetime.today() - timedelta(days=lookback)).strftime("%Y-%m-%d")

    def test_determine_account_filter_since_param_no_lookback(self):
        "Use days ago if present, else check the earliest date for the account"
        setup_test_db()
        client = UpClient(os.environ["UP_TOKEN"])
        date_result = Transactions.determine_account_filter_since_param(client, "123", self.session)
        assert date_result == "2024-01-01T00:00:00+00:00"


class TestUpClient:

    def test_authenticate(self):
        UpClient(os.environ["UP_TOKEN"], lookback=7).authenticate()

    def test_authenticate_fail(self):
        try:
            UpClient("bad_token", lookback=7).authenticate()
        except UpClient.UpAuthError:
            return
        assert False
