from __future__ import annotations
import os
import datetime
from dataclasses import dataclass


from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, String, Integer, Boolean, Numeric, ForeignKey


base = declarative_base()

TEST_DATABASE = "test"

def sanitize(record: dict):
    try:
        record.pop("_sa_instance_state")
    except AttributeError:
        pass
    return record

class DB:
    def __init__(self):
        db = create_engine(DB.db_string())
        self.session = sessionmaker(db)()

    @classmethod
    def db_string(cls):
        USERNAME = os.environ["POSTGRES_USER"]
        PASSWORD = os.environ["POSTGRES_PASSWORD"]
        HOST = os.environ["POSTGRES_HOST"]
        PORT = os.environ["POSTGRES_PORT"]
        DB_NAME = TEST_DATABASE if os.environ["env"] == "dev" else os.environ["POSTGRES_DB"]
        return f"postgresql://{USERNAME}:{PASSWORD}@{HOST}:{PORT}/{DB_NAME}"


@dataclass
class Accounts(base):
    __tablename__ = "accounts"

    id = Column(String, primary_key=True)
    type = Column(String)
    display_name = Column(String)
    account_type = Column(String)
    ownership_type = Column(String)
    balance = Column(Numeric)
    currency = Column(String)
    value_str = Column(String)
    value_base = Column(Integer)
    created_at = Column(String)

    @classmethod
    def insert(cls, session: DB.session, row: Accounts):
        try:
            session.merge(row)
            session.commit()
        except Exception as e:
            session.rollback()
            print(e)


    @classmethod
    def from_id(cls, session: DB.session, id: str) -> Accounts:
        return sanitize(session.query(Accounts).filter(Accounts.id == id).first())

    @classmethod
    def all(cls, session: DB.session) -> list[Accounts]:
        return [sanitize(account.__dict__) for account in session.query(Accounts).all()]

    @classmethod
    def parse_account(self, account: dict) -> Accounts:
        return Accounts(
            id=account.get("id"),
            type=account.get("type"),
            display_name=account.get("attributes", {}).get("displayName"),
            account_type=account.get("attributes", {}).get("accountType"),
            ownership_type=account.get("attributes", {}).get("ownershipType"),
            balance=float(account.get("attributes", {}).get("balance", {}).get("value")),
            currency=account.get("attributes", {}).get("balance", {}).get("currencyCode"),
            value_str=account.get("attributes", {}).get("balance", {}).get("value"),
            value_base=account.get("attributes", {}).get("balance", {}).get("valueInBaseUnits"),
            created_at=account.get("attributes", {}).get("createdAt")
        )


@dataclass
class Transactions(base):
    __tablename__ = "transactions"
    DEFAULT_LOOKBACK = 30

    id = Column(String, primary_key=True)
    account_id = Column(String, ForeignKey("accounts.id"))
    status = Column(String)
    raw_text = Column(String)
    description = Column(String)
    message = Column(String)
    categorizable = Column(Boolean)
    currency = Column(String)
    value_str = Column(String)
    value_base = Column(Integer)
    card_purchase_suffix = Column(String)
    settled_at = Column(String)
    created_at = Column(String)

    @classmethod
    def insert(cls, session, row: Transactions):
        try:
            session.merge(row)
            session.commit()
        except Exception as e:
            session.rollback()
            print(e)

    @classmethod
    def all(cls, session: DB.session) -> list[Transactions]:
        return [sanitize(account.__dict__) for account in session.query(Transactions).all()]

    @classmethod
    def min_transaction_date_for_account(cls, session: DB.session, account_id: str):
        return session.query(func.min(Transactions.created_at)).\
            filter(Transactions.account_id == account_id).scalar().strftime('%Y-%m-%dT%H:%M:%S+00:00')

    @classmethod
    def max_transaction_date_for_account(cls, session: DB.session, account_id: str):
        res = session.query(func.max(Transactions.created_at)).\
            filter(Transactions.account_id == account_id).scalar()
        if res:
            return res.strftime('%Y-%m-%dT%H:%M:%S+00:00')
        return (datetime.datetime.now() - datetime.timedelta(days=cls.DEFAULT_LOOKBACK)).strftime('%Y-%m-%dT%H:%M:%S+00:00')

    @classmethod
    def parse_transaction(cls, transaction: dict, account_id: str) -> Transactions:
        purchase_method = transaction.get("attributes", {}).get("cardPurchaseMethod", {})
        return Transactions(
            id=transaction.get("id"),
            account_id=account_id,
            status=transaction.get("attributes", {}).get("status"),
            raw_text=transaction.get("attributes", {}).get("rawText"),
            description=transaction.get("attributes", {}).get("description"),
            message=transaction.get("attributes", {}).get("message"),
            categorizable=transaction.get("attributes", {}).get("isCategorizable"),
            currency=transaction.get("attributes", {}).get("amount", {}).get("currencyCode"),
            value_str=transaction.get("attributes", {}).get("amount", {}).get("value"),
            value_base=transaction.get("attributes", {}).get("amount", {}).get("valueInBaseUnits"),
            card_purchase_suffix=purchase_method.get("cardNumberSuffix") if purchase_method else None,
            settled_at=transaction.get("attributes", {}).get("settledAt"),
            created_at=transaction.get("attributes", {}).get("createdAt"),
        )