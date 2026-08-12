from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Generator

import aiohttp
import requests
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Numeric, String, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

logging.basicConfig(level=logging.INFO)
LOG = logging.getLogger(__name__)

TEST_DATABASE = "test"

VERSION = "v1"

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 1
RATE_LIMIT_BACKOFF_SECONDS = [60, 300, 1200, 3600]  # 1min, 5mins, 20mins, 60mins


def parse_iso(value: str | None) -> datetime.datetime | None:
    return datetime.datetime.fromisoformat(value) if value else None


def sanitize(record: dict):
    try:
        record.pop("_sa_instance_state")
    except KeyError:
        pass
    return record


class DBClient:
    def __init__(self):
        engine = create_async_engine(DBClient.db_string())
        self.session = async_sessionmaker(engine)()

    @classmethod
    def db_string(cls):
        USERNAME = os.environ["POSTGRES_USER"]
        PASSWORD = os.environ["POSTGRES_PASSWORD"]
        HOST = os.environ["POSTGRES_HOST"]
        PORT = os.environ["POSTGRES_PORT"]
        DB_NAME = TEST_DATABASE if os.environ["env"] == "dev" else os.environ["POSTGRES_DB"]
        return f"postgresql+asyncpg://{USERNAME}:{PASSWORD}@{HOST}:{PORT}/{DB_NAME}"


class UpClient:
    class UpAuthError(Exception):
        pass

    def __init__(
        self, token: str, lookback: int = None, start_date: datetime.datetime = None, end_date: datetime.datetime = None
    ):
        self.token = token
        self.headers = {"Authorization": f"Bearer {self.token}"}
        self.authenticate()
        self.lookback = lookback
        self.start_date = start_date
        self.end_date = end_date
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

            if next_page := res_json.get("links", {}).get("next"):
                url = next_page
                page += 1
                LOG.info(f"Fetching next page {page}")
                continue
            LOG.info("Finished pagination")
            break

    async def _async_fetch_with_retries(self, session: aiohttp.ClientSession, url: str, extras: dict) -> dict:
        attempt = 0
        rate_limit_attempt = 0
        while True:
            try:
                async with session.get(url, headers=self.headers, **extras) as res:
                    res.raise_for_status()
                    res_json = await res.json()
                    return res_json
            except aiohttp.ClientResponseError as e:
                if e.status == 401:
                    raise self.UpAuthError("Failed to authenticate")
                if e.status == 429:
                    if rate_limit_attempt >= len(RATE_LIMIT_BACKOFF_SECONDS):
                        raise
                    wait = RATE_LIMIT_BACKOFF_SECONDS[rate_limit_attempt]
                    rate_limit_attempt += 1
                    LOG.warning(
                        f"Rate limited, waiting {wait}s "
                        f"(attempt {rate_limit_attempt}/{len(RATE_LIMIT_BACKOFF_SECONDS)})"
                    )
                    await asyncio.sleep(wait)
                    continue
                if e.status < 500 or attempt == MAX_RETRIES - 1:
                    raise
            except (aiohttp.ClientError, json.JSONDecodeError):
                if attempt == MAX_RETRIES - 1:
                    raise
            attempt += 1
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

            if next_page := res_json.get("links", {}).get("next"):
                url = next_page
                page += 1
                LOG.info(f"Fetching next page {page}")
                continue
            LOG.info("Finished pagination")
            break

    def _fetch_with_retries(self, url: str, extras: dict) -> dict:
        attempt = 0
        rate_limit_attempt = 0
        while True:
            try:
                res = requests.get(url, headers=self.headers, **extras)
                res.raise_for_status()
                return res.json()
            except requests.exceptions.HTTPError as e:
                status = e.response.status_code
                if status == 401:
                    raise self.UpAuthError("Failed to authenticate")
                if status == 429:
                    if rate_limit_attempt >= len(RATE_LIMIT_BACKOFF_SECONDS):
                        raise
                    wait = RATE_LIMIT_BACKOFF_SECONDS[rate_limit_attempt]
                    rate_limit_attempt += 1
                    LOG.warning(f"Got 429 for {url}, headers: {dict(e.response.headers)}")
                    LOG.warning(
                        f"Rate limited, waiting {wait}s "
                        f"(attempt {rate_limit_attempt}/{len(RATE_LIMIT_BACKOFF_SECONDS)})"
                    )
                    time.sleep(wait)
                    continue
                if status < 500 or attempt == MAX_RETRIES - 1:
                    raise
            except requests.exceptions.RequestException:
                if attempt == MAX_RETRIES - 1:
                    raise
            attempt += 1
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
    created_at = Column(DateTime(timezone=True))

    @classmethod
    async def sync_accounts(cls, client: UpClient):
        LOG.info("\n💳💳💳💳💳💳💳💳💳💳💳💳💳💳💳💳")
        LOG.info("Syncing Accounts")
        LOG.info("💳💳💳💳💳💳💳💳💳💳💳💳💳💳💳💳")
        total = 0
        for res in client._get_request(endpoint="/accounts"):
            accounts = [Accounts.parse_account(lst) for lst in res.get("data", [])]
            await Accounts.insert_many(client.session, accounts)
            total += len(accounts)
        LOG.info("💳💳💳💳💳💳💳💳💳💳💳💳💳💳💳💳")
        LOG.info(f"Successfully synced {total} accounts")
        LOG.info("💳💳💳💳💳💳💳💳💳💳💳💳💳💳💳💳")

    @classmethod
    async def insert(cls, session: AsyncSession, row: Accounts):
        try:
            await session.merge(row)
            await session.commit()
        except Exception as e:
            await session.rollback()
            LOG.exception(e)
            raise

    @classmethod
    async def insert_many(cls, session: AsyncSession, rows: list[Accounts]):
        try:
            for row in rows:
                await session.merge(row)
            await session.commit()
        except Exception as e:
            await session.rollback()
            LOG.exception(e)
            raise

    @classmethod
    async def from_id(cls, session: AsyncSession, id: str) -> dict:
        result = await session.execute(select(Accounts).where(Accounts.id == id))
        account = result.scalar_one_or_none()
        return sanitize(account.__dict__) if account else None

    @classmethod
    async def all(cls, session: AsyncSession) -> list[Accounts]:
        result = await session.execute(select(Accounts))
        return [sanitize(account.__dict__) for account in result.scalars().all()]

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
            created_at=parse_iso(account.get("attributes", {}).get("createdAt")),
        )


@dataclass
class Transactions(base):
    __tablename__ = "transactions"
    DEFAULT_LOOKBACK = 30
    SETTLEMENT_BUFFER_DAYS = 5
    PAGE_SIZE = 50
    WINDOW_SIZE_DAYS = 7
    MAX_CONCURRENT_REQUESTS = 5

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
    settled_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True))

    @classmethod
    async def determine_account_filter_since_param(cls, client: UpClient, account_id: str, session: AsyncSession):
        # start_date/lookback take precedence, if neither given then look at the last date of transaction
        if client.start_date:
            return client.start_date.isoformat()
        if client.lookback:
            return (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=client.lookback)).isoformat()
        return await cls.max_transaction_date_for_account(session, account_id)

    @classmethod
    def determine_account_filter_until_param(cls, client: UpClient):
        if client.end_date:
            return client.end_date.isoformat()
        return None

    @classmethod
    async def sync_transactions(
        cls, client: UpClient, account_ids=None, windowed: bool = False, window_days: int = None
    ):
        accounts = account_ids or (await client.session.execute(select(Accounts.id, Accounts.display_name))).all()

        # determine each account's `since` param up front, sequentially, before any
        # concurrent work starts touching the shared session
        since_by_account_id = {}
        for account in accounts:
            since_by_account_id[account._mapping["id"]] = await cls.determine_account_filter_since_param(
                client, account._mapping["id"], client.session
            )

        until = cls.determine_account_filter_until_param(client)

        # windowed splits each account's range into day-sized chunks fetched concurrently;
        # otherwise each account is a single (since, until) window, paginated via cursor as before
        windows_for = (
            (lambda since: cls._day_windows(since, window_days, until))
            if windowed
            else (lambda since: [(since, until)])
        )

        # one connection, reused across every request, instead of opening a new
        # TCP+TLS connection per request
        # one semaphore shared across every account so at most MAX_CONCURRENT_REQUESTS
        # windows are in flight at once, not MAX_CONCURRENT_REQUESTS per account
        semaphore = asyncio.Semaphore(cls.MAX_CONCURRENT_REQUESTS)
        # every window writes through the one Session on `client`, so this enforces that only
        # one window is ever mid-write at a time - currently true by luck (insert_many has no
        # await in it, so nothing yields control mid-transaction), but that's fragile and this
        # makes it a guarantee instead
        write_lock = asyncio.Lock()
        async with aiohttp.ClientSession() as http_session:
            windows = [
                (account, since, until)
                for account in accounts
                for since, until in windows_for(since_by_account_id[account._mapping["id"]])
            ]
            cors = [
                cls._fetch_transactions_for_window(client, http_session, semaphore, write_lock, account, since, until)
                for account, since, until in windows
            ]
            # return_exceptions=True: one window/account failing (bad row, exhausted retries,
            # whatever) must not tear down the shared http_session out from under every other
            # still-running window, which would truncate unrelated accounts' syncs too
            results = await asyncio.gather(*cors, return_exceptions=True)

        counts_by_account_id: dict[str, int] = {}
        failed_account_ids: set[str] = set()
        for (account, since, until), result in zip(windows, results):
            account_id = account._mapping["id"]
            if isinstance(result, Exception):
                failed_account_ids.add(account_id)
                LOG.error(f"{account._mapping['display_name']}: failed syncing {since} to {until or 'now'}: {result}")
                continue
            _, count = result
            counts_by_account_id[account_id] = counts_by_account_id.get(account_id, 0) + count

        for account_id, count in counts_by_account_id.items():
            LOG.info(f"Successfully synced {count} transactions for account {account_id}")

        if failed_account_ids:
            raise RuntimeError(f"Failed to sync transactions for accounts: {', '.join(sorted(failed_account_ids))}")

    @classmethod
    def _day_windows(cls, since: str, window_days: int = None, until: str = None) -> list[tuple[str, str]]:
        "carve [since, until or now] into window_days-wide (since, until) pairs to fetch concurrently"
        window_days = window_days or cls.WINDOW_SIZE_DAYS
        window_start = datetime.datetime.fromisoformat(since)
        end = datetime.datetime.fromisoformat(until) if until else datetime.datetime.now(datetime.timezone.utc)
        windows = []
        while window_start < end:
            window_end = min(window_start + datetime.timedelta(days=window_days), end)
            windows.append((window_start.isoformat(), window_end.isoformat()))
            window_start = window_end
        return windows or [(since, end.isoformat())]

    @classmethod
    async def _fetch_transactions_for_window(
        cls,
        client: UpClient,
        http_session: aiohttp.ClientSession,
        semaphore: asyncio.Semaphore,
        write_lock: asyncio.Lock,
        account: Accounts,
        since: str,
        until: str | None,
    ) -> tuple[str, int]:
        account_id = account._mapping["id"]
        params = {"filter[since]": since, "page[size]": cls.PAGE_SIZE}
        if until:
            params["filter[until]"] = until
        count = 0
        async with semaphore:
            async for record in client.async_get_request(
                http_session, endpoint=f"accounts/{account_id}/transactions", extras={"params": params}
            ):
                # write each page as it arrives instead of buffering the whole window in memory,
                # so a crash partway through only loses the page in flight, not the whole sync
                page = [Transactions.parse_transaction(lst, account_id) for lst in record.get("data", [])]
                if page:
                    async with write_lock:
                        await Transactions.insert_many(client.session, page)
                    count += len(page)
        if count:
            LOG.info(f"{account._mapping['display_name']}: got {count} transactions, {since} to {until or 'now'}")
        return account_id, count

    @classmethod
    async def insert(cls, session: AsyncSession, row: Transactions):
        try:
            await session.merge(row)
            await session.commit()
        except Exception as e:
            await session.rollback()
            LOG.exception(e)
            raise

    @classmethod
    async def insert_many(cls, session: AsyncSession, rows: list[Transactions]):
        try:
            for row in rows:
                await session.merge(row)
            await session.commit()
        except Exception as e:
            await session.rollback()
            LOG.exception(e)
            raise

    @classmethod
    async def all(cls, session: AsyncSession) -> list[Transactions]:
        result = await session.execute(select(Transactions))
        return [sanitize(account.__dict__) for account in result.scalars().all()]

    @classmethod
    async def max_transaction_date_for_account(cls, session: AsyncSession, account_id: str):
        result = await session.execute(
            select(func.max(Transactions.created_at)).where(Transactions.account_id == account_id)
        )
        res = result.scalar()
        if res:
            # go back a few extra days rather than the exact max - transactions can sit as
            # HELD and settle later without their created_at changing, so if we started from
            # the exact max we'd never see that settlement
            return (res - datetime.timedelta(days=cls.SETTLEMENT_BUFFER_DAYS)).isoformat()
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=cls.DEFAULT_LOOKBACK)
        return cutoff.isoformat()

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
            settled_at=parse_iso(transaction.get("attributes", {}).get("settledAt")),
            created_at=parse_iso(transaction.get("attributes", {}).get("createdAt")),
        )
