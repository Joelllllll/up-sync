#!/usr/bin/env python3

import os
import sys
import asyncio
import logging

sys.path.append(os.path.join(os.path.dirname(__file__), "../"))

from app.clients import Accounts, Transactions
from app.clients import UpClient

logging.basicConfig(level=logging.INFO)
LOG = logging.getLogger(__name__)

class UpSync:
    def __init__(self, token):
        self.client = UpClient(token)

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

if __name__ == "__main__":
    up_sync = UpSync(os.environ["UP_TOKEN"])
    up_sync.sync()
