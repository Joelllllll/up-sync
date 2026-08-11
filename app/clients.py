from __future__ import annotations

import asyncio
import datetime
import logging
import os
import time
from dataclasses import dataclass
from typing import Generator

import aiohttp
import requests
from sqlalchemy import Boolean, Column, ForeignKey, Integer, Numeric, String, create_engine, func
from sqlalchemy.orm import declarative_base, sessionmaker

logging.basicConfig(level=logging.INFO)
LOG = logging.getLogger(__name__)

TEST_DATABASE = "test"

VERSION = "v1"

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 1

def sanitize(record: dict):
    try:
        record.pop("_sa_instance_state")
    except AttributeError:
        pass
    return record

class DBClient:
    def __init__(self):
        db = create_engine(DBClient.db_string())
        self.session = sessionmaker(db)()

    @classmethod
    def db_string(cls):
        USERNAME = os.environ["POSTGRES_USER"]
        PASSWORD = os.environ["POSTGRES_PASSWORD"]
        HOST = os.environ["POSTGRES_HOST"]
        PORT = os.environ["POSTGRES_PORT"]
        DB_NAME = TEST_DATABASE if os.environ["env"] == "dev" else os.environ["POSTGRES_DB"]
        return f"postgresql://{USERNAME}:{PASSWORD}@{HOST}:{PORT}/{DB_NAME}"

class UpClient():
    class UpAuthError(Exception):
        pass

    def __init__(self, token: str, lookback: int = None):
        self.token = token
        self.headers = {"Authorization": f"Bearer {self.token}"}
        self.authenticate()
        self.lookback = lookback
        self.session = DBClient().session

    def authenticate(self):
        for _ in self._get_request(endpoint="/util/ping"):
            return LOG.info("Successfully authenticated")
        raise self.UpAuthError("Failed to authenticate")

    def base_url(self) -> str:
        if os.environ.get("env") == "prod":
            return f"https://api.up.com.au/api/{VERSION}"
        return os.environ.get("MOCKSERVER_URL")

    def join_endpoint(self, endpoint: str) -> str:
        return f"{self.base_url()}/{endpoint.lstrip('/')}"

    async def async_get_request(
        self, session: aiohttp.ClientSession, endpoint: str = None, url: str = None, extras: dict = None
    ) -> Generator:
        url = url or self.join_endpoint(endpoint)
        extras = extras or {}
        page = 1
        while True:
            res_json = await self._async_fetch_with_retries(session, url, extras)
            # url has the pagination cursor tacked on which is long and not worth printing
            LOG.info(f"Successfully fetched {url.split('?')[0]}, page {page}")
            yield res_json

            if (next_page := res_json.get("links", {}).get("next")):
                url = next_page
                page += 1
                LOG.info(f"Fetching next page {page}")
                continue
            LOG.info("Finished pagination")
            break

    async def _async_fetch_with_retries(self, session: aiohttp.ClientSession, url: str, extras: dict) -> dict:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                async with session.get(url, headers=self.headers, **extras) as res:
                    res_json = await res.json()
                    res.raise_for_status()
                    return res_json
            except aiohttp.ClientResponseError as e:
                if e.status == 401:
                    raise self.UpAuthError("Failed to authenticate")
                # 429 is Up's rate limit response, worth backing off and retrying same as a 5xx
                if (e.status < 500 and e.status != 429) or attempt == MAX_RETRIES:
                    raise
            except aiohttp.ClientError as e:
                if attempt == MAX_RETRIES:
                    raise
            LOG.warning(f"Request to {url} failed (attempt {attempt}/{MAX_RETRIES}), retrying")
            await asyncio.sleep(RETRY_BACKOFF_SECONDS * attempt)

    def _get_request(self, endpoint: str = None, url: str = None, extras: dict = None) -> Generator:
        url = url or self.join_endpoint(endpoint)
        extras = extras or {}
        page = 1
        while True:
            res_json = self._fetch_with_retries(url, extras)
            # url has the pagination cursor tacked on which is long and not worth printing
            LOG.info(f"Successfully fetched {url.split('?')[0]}, page {page}")
            yield res_json

            if (next_page := res_json.get("links", {}).get("next")):
                url = next_page
                page += 1
                LOG.info(f"Fetching next page {page}")
                continue
            LOG.info("Finished pagination")
            break

    def _fetch_with_retries(self, url: str, extras: dict) -> dict:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                res = requests.get(url, headers=self.headers, **extras)
                res.raise_for_status()
                return res.json()
            except requests.exceptions.HTTPError as e:
                status = e.response.status_code
                if status == 401:
                    raise self.UpAuthError("Failed to authenticate")
                # 429 is Up's rate limit response, worth backing off and retrying same as a 5xx
                if (status < 500 and status != 429) or attempt == MAX_RETRIES:
                    raise
            except requests.exceptions.RequestException as e:
                if attempt == MAX_RETRIES:
                    raise
            LOG.warning(f"Request to {url} failed (attempt {attempt}/{MAX_RETRIES}), retrying")
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)

base = declarative_base()

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
    def sync_accounts(cls, client: UpClient):
        LOG.info("\n💳💳💳💳💳💳💳💳💳💳💳💳💳💳💳💳")
        LOG.info("Syncing Accounts")
        LOG.info("💳💳💳💳💳💳💳💳💳💳💳💳💳💳💳💳")
        #TODO move this to a method on  accounts class
        accounts = [
            Accounts.parse_account(lst)
            for res in client._get_request(endpoint="/accounts")
            for lst in res.get("data", [])
        ]
        Accounts.insert_many(client.session, accounts)
        LOG.info("💳💳💳💳💳💳💳💳💳💳💳💳💳💳💳💳")
        LOG.info(f"Successfully synced {len(accounts)} accounts")
        LOG.info("💳💳💳💳💳💳💳💳💳💳💳💳💳💳💳💳")

    @classmethod
    def insert(cls, session: DBClient.session, row: Accounts):
        try:
            session.merge(row)
            session.commit()
        except Exception as e:
            session.rollback()
            LOG.error(e)
            raise

    @classmethod
    def insert_many(cls, session: DBClient.session, rows: list[Accounts]):
        try:
            for row in rows:
                session.merge(row)
            session.commit()
        except Exception as e:
            session.rollback()
            LOG.error(e)
            raise


    @classmethod
    def from_id(cls, session: DBClient.session, id: str) -> Accounts:
        return sanitize(session.query(Accounts).filter(Accounts.id == id).first())

    @classmethod
    def all(cls, session: DBClient.session) -> list[Accounts]:
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
    DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S+00:00"
    SETTLEMENT_BUFFER_DAYS = 5
    PAGE_SIZE = 50

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
    def determine_account_filter_since_param(cls, client: UpClient, account_id: str, session: DBClient.session):
        # lookback takes precedence, if not given then look at the last date of transaction
        if client.lookback:
            return (datetime.datetime.now() - datetime.timedelta(days=client.lookback)).strftime(cls.DATETIME_FORMAT)
        return cls.max_transaction_date_for_account(session, account_id)

    @classmethod
    async def sync_transactions(cls, client: UpClient, account_ids=None):
        accounts = account_ids or client.session.query(Accounts.id, Accounts.display_name).all()

        # determine each account's `since` param up front, sequentially, before any
        # concurrent work starts touching the shared session
        since_by_account_id = {
            account._mapping["id"]: cls.determine_account_filter_since_param(
                client, account._mapping["id"], client.session
            )
            for account in accounts
        }

        # one connection, reused across every page of every account, instead of
        # opening a new TCP+TLS connection per request
        async with aiohttp.ClientSession() as http_session:
            cors = [
                cls._fetch_transactions_for_account(
                    client, http_session, account, since_by_account_id[account._mapping["id"]]
                )
                for account in accounts
            ]
            results = await asyncio.gather(*cors)

        # writes happen sequentially, after all fetching is done, so only one coroutine
        # ever touches the shared session at a time
        all_transactions = [transaction for _, transactions in results for transaction in transactions]
        Transactions.insert_many(client.session, all_transactions)
        for account_id, transactions in results:
            LOG.info(f"Successfully synced {len(transactions)} transactions for account {account_id}")

    @classmethod
    async def _fetch_transactions_for_account(
        cls, client: UpClient, http_session: aiohttp.ClientSession, account: Accounts, since: str
    ) -> tuple[str, list[Transactions]]:
        LOG.info("🤝🤝🤝🤝🤝🤝🤝🤝🤝🤝🤝🤝🤝🤝🤝🤝")
        LOG.info(f"Fetching transactions for account: {account._mapping['display_name']}")
        LOG.info("🤝🤝🤝🤝🤝🤝🤝🤝🤝🤝🤝🤝🤝🤝🤝🤝")
        account_id = account._mapping["id"]
        params = {"filter[since]": since, "page[size]": cls.PAGE_SIZE}
        transactions = []
        async for record in client.async_get_request(
            http_session,
            endpoint=f"accounts/{account_id}/transactions",
            extras={"params": params}
        ):
            page = [Transactions.parse_transaction(lst, account_id) for lst in record.get("data", [])]
            transactions.extend(page)
            # so you can actually tell how far through history it's got without decoding the cursor
            if page:
                dates = [t.created_at for t in page]
                LOG.info(
                    f"{account._mapping['display_name']}: got {len(page)} transactions, "
                    f"{min(dates)} to {max(dates)}"
                )
        return account_id, transactions

    @classmethod
    def insert(cls, session, row: Transactions):
        try:
            session.merge(row)
            session.commit()
        except Exception as e:
            session.rollback()
            LOG.error(e)
            raise

    @classmethod
    def insert_many(cls, session, rows: list[Transactions]):
        try:
            for row in rows:
                session.merge(row)
            session.commit()
        except Exception as e:
            session.rollback()
            LOG.error(e)
            raise

    @classmethod
    def all(cls, session: DBClient.session) -> list[Transactions]:
        return [sanitize(account.__dict__) for account in session.query(Transactions).all()]

    @classmethod
    def min_transaction_date_for_account(cls, session: DBClient.session, account_id: str):
        return session.query(func.min(Transactions.created_at)).\
            filter(Transactions.account_id == account_id).scalar().strftime(cls.DATETIME_FORMAT)

    @classmethod
    def max_transaction_date_for_account(cls, session: DBClient.session, account_id: str):
        res = session.query(func.max(Transactions.created_at)).\
            filter(Transactions.account_id == account_id).scalar()
        if res:
            # go back a few extra days rather than the exact max - transactions can sit as
            # HELD and settle later without their created_at changing, so if we started from
            # the exact max we'd never see that settlement
            return (res - datetime.timedelta(days=cls.SETTLEMENT_BUFFER_DAYS)).strftime(cls.DATETIME_FORMAT)
        return (datetime.datetime.now() - datetime.timedelta(days=cls.DEFAULT_LOOKBACK)).strftime(cls.DATETIME_FORMAT)

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
