import os
import sys

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

def setup_test_db():
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
