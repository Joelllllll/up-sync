#!/usr/bin/env python3


import argparse
import asyncio
import logging
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "../"))

from app.clients import Accounts, Transactions, UpClient

logging.basicConfig(level=logging.INFO)
LOG = logging.getLogger(__name__)

class UpSync:
    def __init__(self, token: str, lookback: int = None):
        self.client = UpClient(token, lookback)

    def authenticate(self):
        try:
            self.client.authenticate()
        except UpClient.UpAuthError as e:
            LOG.info(f"Failed to authenticate with Up: {e}")
            sys.exit(1)

    def sync_transactions(self, account_ids=None):
        asyncio.run(Transactions.sync_transactions(self.client, account_ids))

    def sync_accounts(self):
        Accounts.sync_accounts(self.client)

    def sync(self):
        LOG.info("Starting Sync")
        self.sync_accounts()
        self.sync_transactions()
        LOG.info("Sync Complete")

def parse_args():
    parser = argparse.ArgumentParser(description="Sync Up data")
    parser.add_argument(
        "--lookback",
        type=int,
        required=False,
        default=None,
        help="Number of days to look back for transactions"
    )
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_args()
    up_sync = UpSync(os.environ["UP_TOKEN"], args.lookback)
    up_sync.sync()

