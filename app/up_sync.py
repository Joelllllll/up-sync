#!/usr/bin/env python3


import argparse
import asyncio
import datetime
import logging
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "../"))

from app.clients import Accounts, Transactions, UpClient

logging.basicConfig(level=logging.INFO)
LOG = logging.getLogger(__name__)


class UpSync:
    def __init__(
        self, token: str, lookback: int = None, start_date: datetime.datetime = None, end_date: datetime.datetime = None
    ):
        self.client = UpClient(token, lookback, start_date, end_date)

    def authenticate(self):
        try:
            self.client.authenticate()
        except UpClient.UpAuthError as e:
            LOG.info(f"Failed to authenticate with Up: {e}")
            sys.exit(1)

    async def sync(self, windowed: bool = False, window_days: int = None):
        LOG.info("Starting Sync")
        # accounts + transactions run under one asyncio.run/event loop here - the async
        # engine's pooled connections are tied to the loop they were first used on, so
        # reusing the same client.session across two separate asyncio.run() calls would
        # hand the second one a connection bound to an already-closed loop
        await self._sync(windowed, window_days)
        LOG.info("Sync Complete")

    async def _sync(self, windowed: bool = False, window_days: int = None):
        try:
            await Accounts.sync_accounts(self.client)
            await Transactions.sync_transactions(self.client, windowed=windowed, window_days=window_days)
        finally:
            # close the session/engine while the loop that opened them is still running -
            # asyncio.run() tears the loop down right after this returns, and an asyncpg
            # connection finalized after that point blows up (can't spawn its cleanup greenlet)
            await self.client.session.close()
            await self.client.session.bind.dispose()


def valid_date(value: str) -> datetime.datetime:
    try:
        return datetime.datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid date '{value}', expected YYYY-MM-DD")


def parse_args():
    parser = argparse.ArgumentParser(description="Sync Up data")
    parser.add_argument(
        "--lookback", type=int, required=False, default=None, help="Number of days to look back for transactions"
    )
    parser.add_argument(
        "--start-date",
        type=valid_date,
        required=False,
        default=None,
        help="Start date (YYYY-MM-DD, inclusive) for transactions. Requires --end-date, cannot be used with --lookback",
    )
    parser.add_argument(
        "--end-date",
        type=valid_date,
        required=False,
        default=None,
        help="End date (YYYY-MM-DD, exclusive) for transactions. Requires --start-date, cannot be used with --lookback",
    )
    parser.add_argument(
        "--async",
        dest="windowed",
        action="store_true",
        help="Split each account's transaction fetch into day-sized windows and fetch them "
        "concurrently (bounded by a semaphore), instead of one cursor-paginated request per account",
    )
    parser.add_argument(
        "--window-days",
        type=int,
        required=False,
        default=None,
        help=f"Window size in days for --async transaction fetching (default {Transactions.WINDOW_SIZE_DAYS})",
    )
    args = parser.parse_args()
    if args.lookback and (args.start_date or args.end_date):
        parser.error("--lookback cannot be used with --start-date/--end-date")
    if bool(args.start_date) != bool(args.end_date):
        parser.error("--start-date and --end-date must be used together")
    if args.window_days and not args.windowed:
        parser.error("--window-days requires --async")
    return args


if __name__ == "__main__":
    args = parse_args()
    up_sync = UpSync(os.environ["UP_TOKEN"], args.lookback, args.start_date, args.end_date)
    # start the event loop
    asyncio.run(up_sync.sync(windowed=args.windowed, window_days=args.window_days))
