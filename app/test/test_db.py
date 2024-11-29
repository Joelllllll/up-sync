import sys
import os

from freezegun import freeze_time

# makes it access the test db instead
os.environ["env"] = "dev"

sys.path.append(os.path.join(os.path.dirname(__file__), "../../"))

from app.clients import DBClient, Accounts, Transactions
from sqlalchemy import MetaData, Table


def delete_all_from_tables():
    session = DBClient().session
    accounts = Table('accounts', MetaData())
    transactions = Table('transactions', MetaData())
    session.execute(transactions.delete())
    session.execute(accounts.delete())
    session.commit()



def insert_transactions():
    session = DBClient().session
    accounts = [
        Accounts(
            id="123"
        ),
        Accounts(
            id="321"
        )
    ]
    for account in accounts:
        Accounts.insert(session, account)
    assert len(Accounts.all(session)) == 2
    transactions = [
        {"id": "1", "account_id": "123", "created_at": "2020-01-01T00:00:00+00:00"},
        {"id": "2", "account_id": "123", "created_at": "2024-01-01T00:00:00+00:00"},
        {"id": "3", "account_id": "321", "created_at": "2020-01-01T00:00:00+00:00"},
        {"id": "4", "account_id": "321", "created_at": "2022-01-01T00:00:00+00:00"},
    ]

    for transaction in transactions:
        Transactions.insert(session, Transactions(**transaction))

    assert len(Transactions.all(session)) == 4


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

        assert q.id == "123"
        assert q.display_name == "display name"
        assert q.account_type == "test"
        assert q.ownership_type == "test"
        assert q.balance == 1.0
        assert q.currency == "AUD"
        assert q.value_str == "1.0"
        assert q.value_base == 100
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

        assert q.id == "123"
        assert q.account_id == "123"
        assert q.status == "SETTLED"
        assert q.raw_text == None
        assert q.description == "test"
        assert q.message == "test"
        assert q.categorizable == True
        assert q.currency == "AUD"
        assert q.value_str == "1.0"
        assert q.value_base == 100
        assert q.card_purchase_suffix == "12345"
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
        insert_transactions()
        assert Transactions.min_transaction_date_for_account(self.session, "123") == "2020-01-01T00:00:00+00:00"
        assert Transactions.min_transaction_date_for_account(self.session, "321") == "2020-01-01T00:00:00+00:00"

    def test_max_transaction_date_for_account(self):
        insert_transactions()
        assert Transactions.max_transaction_date_for_account(self.session, "123") == "2024-01-01T00:00:00+00:00"
        assert Transactions.max_transaction_date_for_account(self.session, "321") == "2022-01-01T00:00:00+00:00"

