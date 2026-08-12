import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "../../"))

from sqlalchemy import MetaData, Table

from app.clients import Accounts, DBClient, Transactions, parse_iso


async def delete_all_from_tables():
    session = DBClient().session
    accounts = Table("accounts", MetaData())
    transactions = Table("transactions", MetaData())
    await session.execute(transactions.delete())
    await session.execute(accounts.delete())
    await session.commit()
    await session.close()


async def setup_test_db():
    session = DBClient().session
    accounts = [Accounts(id="123"), Accounts(id="321")]
    for account in accounts:
        await Accounts.insert(session, account)
    assert len(await Accounts.all(session)) == 2
    transactions = [
        {"id": "1", "account_id": "123", "created_at": "2020-01-01T00:00:00+00:00"},
        {"id": "2", "account_id": "123", "created_at": "2024-01-01T00:00:00+00:00"},
        {"id": "3", "account_id": "321", "created_at": "2020-01-01T00:00:00+00:00"},
        {"id": "4", "account_id": "321", "created_at": "2022-01-01T00:00:00+00:00"},
    ]

    for transaction in transactions:
        transaction = {**transaction, "created_at": parse_iso(transaction["created_at"])}
        await Transactions.insert(session, Transactions(**transaction))

    assert len(await Transactions.all(session)) == 4
    await session.close()
