"""
Ethereum Load Testing Tool with Prometheus Metrics
Configurable load testing tool for Ethereum networks
"""

import time
import random
import threading
import os
from web3 import Web3
from eth_account import Account
from prometheus_client import Counter, Gauge, Histogram, start_http_server
import logging
from dataclasses import dataclass
from typing import List

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Prometheus Metrics
tx_sent_total = Counter('eth_transactions_sent_total', 'Total transactions sent')
tx_success_total = Counter('eth_transactions_success_total', 'Total successful transactions')
tx_failed_total = Counter('eth_transactions_failed_total', 'Total failed transactions')
tx_pending = Gauge('eth_transactions_pending', 'Current pending transactions')
tx_duration = Histogram('eth_transaction_duration_seconds', 'Transaction confirmation time')
accounts_created = Gauge('eth_accounts_created_total', 'Total accounts created')
current_balance = Gauge('eth_account_balance_wei', 'Current account balance', ['address'])
gas_price_gwei = Gauge('eth_gas_price_gwei', 'Current gas price in Gwei')
block_number = Gauge('eth_block_number', 'Current block number')
connection_status = Gauge('eth_connection_status', 'Connection status (1=connected, 0=disconnected)')


@dataclass
class LoadTestConfig:
    rpc_url: str
    num_accounts: int
    txs_per_batch: int
    batch_interval: float
    tx_value_wei: int
    gas_limit: int
    continuous: bool
    total_batches: int
    metrics_port: int
    fund_amount_ether: float


class EthereumLoadTester:
    def __init__(self, config: LoadTestConfig):
        self.config = config
        # Add timeout to HTTP provider
        self.w3 = Web3(Web3.HTTPProvider(
            config.rpc_url,
            request_kwargs={'timeout': 10}  # 10 second timeout
        ))
        self.accounts: List[Account] = []
        self.running = False
        self.pending_txs = set()

        # Wait for connection with retries
        self._wait_for_connection()

        logger.info(f"Connected to Ethereum node at {config.rpc_url}")
        logger.info(f"Chain ID: {self.w3.eth.chain_id}")

    def _wait_for_connection(self, max_retries=30, retry_delay=2):
        """Wait for Ethereum node to be ready"""
        logger.info(f"Connecting to {self.config.rpc_url}...")

        for attempt in range(max_retries):
            try:
                if self.w3.is_connected():
                    # Additional check: try to get chain_id
                    chain_id = self.w3.eth.chain_id
                    logger.info(f"Connection successful on attempt {attempt + 1}")
                    return
            except Exception as e:
                logger.debug(f"Connection attempt {attempt + 1} failed: {e}")

            if attempt < max_retries - 1:
                logger.info(f"Waiting for node... ({attempt + 1}/{max_retries})")
                time.sleep(retry_delay)

        raise Exception(f"Cannot connect to {self.config.rpc_url} after {max_retries} attempts")

    def _check_connection(self):
        """Check if connection is alive with timeout"""
        try:
            # Quick connection check with timeout
            self.w3.eth.block_number
            connection_status.set(1)  # Connected
            return True
        except Exception as e:
            logger.warning(f"Connection check failed: {e}")
            connection_status.set(0)  # Disconnected
            return False

    def create_accounts(self):
        """Create test accounts"""
        logger.info(f"Creating {self.config.num_accounts} accounts...")

        for i in range(self.config.num_accounts):
            account = Account.create()
            self.accounts.append(account)
            logger.info(f"Created account {i + 1}/{self.config.num_accounts}: {account.address}")

        accounts_created.set(len(self.accounts))

    def fund_accounts(self):
        """Fund accounts from the dev account"""
        logger.info("Funding accounts...")

        # Get dev account (unlocked in dev mode)
        dev_account = self.w3.eth.accounts[0]

        for i, account in enumerate(self.accounts):
            try:
                # Send funds to account
                tx_hash = self.w3.eth.send_transaction({
                    'from': dev_account,
                    'to': account.address,
                    'value': self.w3.to_wei(self.config.fund_amount_ether, 'ether'),
                    'gas': 21000,
                })

                # Wait for transaction
                receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)

                if receipt['status'] == 1:
                    balance = self.w3.eth.get_balance(account.address)
                    logger.info(f"Funded account {i + 1}: {account.address} with {self.w3.from_wei(balance, 'ether')} ETH")
                    current_balance.labels(address=account.address).set(balance)
                else:
                    logger.error(f"Failed to fund account {account.address}")

            except Exception as e:
                logger.error(f"Error funding account {account.address}: {e}")

    def send_transaction(self, from_account: Account, to_address: str):
        """Send a single transaction"""
        try:
            # Check if connection is still alive (with timeout)
            if not self._check_connection():
                logger.warning("Web3 connection lost")
                raise ConnectionError("Not connected to Ethereum node")

            # Get nonce with timeout protection (including pending)
            nonce = self.w3.eth.get_transaction_count(from_account.address, 'pending')

            # Build transaction
            gas_price = self.w3.eth.gas_price

            tx = {
                'nonce': nonce,
                'to': to_address,
                'value': self.config.tx_value_wei,
                'gas': self.config.gas_limit,
                'gasPrice': gas_price,
                'chainId': self.w3.eth.chain_id,
            }

            # Sign transaction
            signed_tx = from_account.sign_transaction(tx)

            # Send transaction - handle both old and new attribute names
            start_time = time.time()
            raw_tx = getattr(signed_tx, 'rawTransaction', None) or getattr(signed_tx, 'raw_transaction', None)

            if raw_tx is None:
                raise AttributeError("Could not find raw transaction data in signed transaction")

            tx_hash = self.w3.eth.send_raw_transaction(raw_tx)

            tx_sent_total.inc()
            self.pending_txs.add(tx_hash.hex())
            tx_pending.set(len(self.pending_txs))

            logger.debug(f"Sent tx: {tx_hash.hex()}")

            # Wait for receipt in background
            threading.Thread(
                target=self._wait_for_receipt,
                args=(tx_hash, start_time),
                daemon=True
            ).start()

            return tx_hash

        except Exception as e:
            error_msg = str(e)

            # Handle specific error cases
            if 'replacement transaction underpriced' in error_msg:
                logger.warning(f"Nonce collision for {from_account.address}, skipping")
            else:
                logger.error(f"Error sending transaction from {from_account.address}: {e}")

            tx_sent_total.inc()  # Count as sent attempt
            tx_failed_total.inc()  # Also count as failed
            return None

    def _wait_for_receipt(self, tx_hash, start_time):
        """Wait for transaction receipt"""
        try:
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            duration = time.time() - start_time

            if receipt['status'] == 1:
                tx_success_total.inc()
                tx_duration.observe(duration)
                logger.debug(f"Tx confirmed: {tx_hash.hex()} in {duration:.2f}s")
            else:
                tx_failed_total.inc()
                logger.error(f"Tx failed: {tx_hash.hex()}")

            # Remove from pending
            if tx_hash.hex() in self.pending_txs:
                self.pending_txs.remove(tx_hash.hex())
                tx_pending.set(len(self.pending_txs))

        except Exception as e:
            logger.error(f"Error waiting for receipt {tx_hash.hex()}: {e}")
            tx_failed_total.inc()

    def send_batch(self):
        """Send a batch of transactions"""
        logger.info(f"Sending batch of {self.config.txs_per_batch} transactions...")

        successful = 0
        failed = 0
        account_last_used = {}  # Track when each account was last used

        for i in range(self.config.txs_per_batch):
            # Random sender and receiver
            from_account = random.choice(self.accounts)
            to_account = random.choice(self.accounts)

            # Don't send to self
            while to_account.address == from_account.address:
                to_account = random.choice(self.accounts)

            # Add small delay if same account used recently (prevent nonce collisions)
            if from_account.address in account_last_used:
                time_since_last = time.time() - account_last_used[from_account.address]
                if time_since_last < 0.1:  # If used within last 100ms
                    time.sleep(0.1 - time_since_last)

            tx_hash = self.send_transaction(from_account, to_account.address)

            # Track when this account was used
            account_last_used[from_account.address] = time.time()

            if tx_hash:
                successful += 1
            else:
                failed += 1

            # Small delay between transactions in batch
            time.sleep(0.01)

        logger.info(f"Batch complete: {successful} successful, {failed} failed")

        # Don't stop on failures - keep running to maintain metrics

    def update_metrics(self):
        """Update general metrics"""
        try:
            # Check connection first with timeout
            if not self._check_connection():
                logger.warning("Cannot update metrics - Web3 not connected")
                return

            # Update gas price
            gas_price_wei = self.w3.eth.gas_price
            gas_price_gwei.set(self.w3.from_wei(gas_price_wei, 'gwei'))

            # Update block number
            block_num = self.w3.eth.block_number
            block_number.set(block_num)

            # Update account balances
            for account in self.accounts:
                balance = self.w3.eth.get_balance(account.address)
                current_balance.labels(address=account.address).set(balance)

        except Exception as e:
            logger.error(f"Error updating metrics: {e}")

    def run(self):
        """Run the load test"""
        self.running = True

        # Create and fund accounts
        self.create_accounts()
        self.fund_accounts()

        logger.info("Starting load test...")

        batch_count = 0

        try:
            while self.running:
                # Send batch
                self.send_batch()
                batch_count += 1

                # Update metrics
                self.update_metrics()

                logger.info(f"Batch {batch_count} completed. Waiting {self.config.batch_interval}s...")

                # Check if we should stop
                if not self.config.continuous and batch_count >= self.config.total_batches:
                    logger.info(f"Completed {batch_count} batches. Stopping...")
                    break

                # Wait for next batch
                time.sleep(self.config.batch_interval)

        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        finally:
            self.running = False
            logger.info("Load test completed")


def load_config_from_env() -> LoadTestConfig:
    """Load configuration from environment variables"""
    return LoadTestConfig(
        rpc_url=os.getenv('RPC_URL', 'http://localhost:8545'),
        num_accounts=int(os.getenv('NUM_ACCOUNTS', '10')),
        txs_per_batch=int(os.getenv('TXS_PER_BATCH', '50')),
        batch_interval=float(os.getenv('BATCH_INTERVAL', '10.0')),
        tx_value_wei=int(os.getenv('TX_VALUE_WEI', '1000000000000000')),
        gas_limit=int(os.getenv('GAS_LIMIT', '21000')),
        continuous=os.getenv('CONTINUOUS', 'true').lower() == 'true',
        total_batches=int(os.getenv('TOTAL_BATCHES', '100')),
        metrics_port=int(os.getenv('METRICS_PORT', '8000')),
        fund_amount_ether=float(os.getenv('FUND_AMOUNT_ETHER', '1.0'))
    )


def main():
    # Load config from environment variables
    config = load_config_from_env()

    logger.info("Configuration loaded:")
    logger.info(f"  RPC URL: {config.rpc_url}")
    logger.info(f"  Num Accounts: {config.num_accounts}")
    logger.info(f"  TXs per Batch: {config.txs_per_batch}")
    logger.info(f"  Batch Interval: {config.batch_interval}s")
    logger.info(f"  TX Value: {config.tx_value_wei} wei")
    logger.info(f"  Gas Limit: {config.gas_limit}")
    logger.info(f"  Continuous: {config.continuous}")
    logger.info(f"  Total Batches: {config.total_batches}")
    logger.info(f"  Metrics Port: {config.metrics_port}")
    logger.info(f"  Fund Amount: {config.fund_amount_ether} ETH")

    # Start metrics server
    logger.info(f"Starting metrics server on port {config.metrics_port}")
    start_http_server(config.metrics_port)

    # Create and run load tester
    tester = EthereumLoadTester(config)
    tester.run()


if __name__ == '__main__':
    main()
