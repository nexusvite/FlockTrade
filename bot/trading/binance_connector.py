"""
Binance Connector for FlockTrade.

Provides the same interface as MT5Connector but uses the Binance API
via the python-binance library. Supports both testnet (DEMO) and
mainnet (REAL) accounts via account_type parameter.

Configuration is read from django.conf.settings:
    BINANCE_API_KEY            - Mainnet API key
    BINANCE_API_SECRET         - Mainnet API secret
    BINANCE_TESTNET_API_KEY    - Testnet API key
    BINANCE_TESTNET_API_SECRET - Testnet API secret
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal, ROUND_DOWN
from typing import Any

from django.conf import settings

from trading.mt5_connector import (
    Candle,
    Tick,
    AccountInfo,
    Position,
    HistoryDeal,
    TradeResult,
)

logger = logging.getLogger("trading.binance_connector")

# ---------------------------------------------------------------------------
# Binance timeframe mapping (FlockTrade string -> Binance kline interval)
# ---------------------------------------------------------------------------

TIMEFRAMES: dict[str, str] = {
    "M1": "1m",
    "M5": "5m",
    "M15": "15m",
    "M30": "30m",
    "H1": "1h",
    "H4": "4h",
    "D1": "1d",
}

# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class ConnectorError(Exception):
    """Raised when a Binance operation fails permanently."""


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------


class BinanceConnector:
    """
    Thread-safe Binance API connector.

    Usage:
        connector = BinanceConnector(account_type="DEMO")
        connector.connect()
        candles = connector.get_candles("BTCUSDT", "M5", 100)
        connector.disconnect()

    The connector reads API keys from Django settings so no
    environment parsing is needed at call sites.
    """

    # Reconnect policy
    MAX_RETRIES: int = 3
    BASE_BACKOFF: float = 1.0
    MAX_BACKOFF: float = 30.0

    # Binance testnet base URLs
    TESTNET_API_URL = "https://testnet.binance.vision/api"
    TESTNET_STREAM_URL = "wss://testnet.binance.vision/ws"

    def __init__(self, account_type: str = "DEMO") -> None:
        self._account_type = account_type.upper()
        self._client: Any = None
        self._connected: bool = False
        self._last_error: str = ""
        self._exchange_info_cache: dict[str, dict] = {}

        # Select API keys based on account type
        if self._account_type == "REAL":
            self._api_key = getattr(settings, "BINANCE_API_KEY", "")
            self._api_secret = getattr(settings, "BINANCE_API_SECRET", "")
            self._testnet = False
        else:
            self._api_key = getattr(settings, "BINANCE_TESTNET_API_KEY", "")
            self._api_secret = getattr(settings, "BINANCE_TESTNET_API_SECRET", "")
            self._testnet = True

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """
        Establish connection to Binance API.

        Verifies credentials with get_account(). Returns True on success.
        """
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                logger.info(
                    "Binance connect attempt %d/%d [%s]",
                    attempt, self.MAX_RETRIES, self._account_type,
                )
                self._client = self._create_client()

                # Verify credentials
                self._client.get_account()
                self._connected = True
                logger.info(
                    "Binance connected successfully [%s, testnet=%s]",
                    self._account_type, self._testnet,
                )
                return True

            except Exception as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "Binance connect attempt %d failed: %s", attempt, self._last_error,
                )
                self._connected = False
                if attempt < self.MAX_RETRIES:
                    backoff = min(
                        self.BASE_BACKOFF * (2 ** (attempt - 1)), self.MAX_BACKOFF,
                    )
                    logger.info("Retrying Binance connection in %.1fs...", backoff)
                    time.sleep(backoff)

        logger.error(
            "Binance connection failed after %d attempts [%s].",
            self.MAX_RETRIES, self._account_type,
        )
        return False

    def disconnect(self) -> None:
        """Close the Binance client."""
        if self._client is not None:
            try:
                self._client.close_connection()
            except Exception as exc:
                logger.warning("Error closing Binance connection: %s", exc)
            finally:
                self._client = None
                self._connected = False
                logger.info("Binance connection closed [%s].", self._account_type)

    def is_connected(self) -> bool:
        """Return True if the client is currently live."""
        if not self._connected or self._client is None:
            return False
        try:
            self._client.ping()
            return True
        except Exception:
            self._connected = False
            return False

    def ensure_connected(self) -> bool:
        """Ensure connection is alive, reconnecting if necessary."""
        if self.is_connected():
            return True
        logger.warning("Binance connection lost [%s] - attempting reconnect...", self._account_type)
        return self.connect()

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    def get_candles(
        self, symbol: str, timeframe: str, count: int = 100,
    ) -> list[Candle]:
        """
        Fetch the most recent `count` OHLCV bars for the given symbol/timeframe.

        Args:
            symbol:    e.g. "BTCUSDT"
            timeframe: one of M1, M5, M15, M30, H1, H4, D1
            count:     number of bars (max 1000)

        Returns:
            List of Candle objects, oldest bar first.
        """
        self._require_connection()
        interval = self._resolve_timeframe(timeframe)

        try:
            klines = self._client.get_klines(
                symbol=symbol,
                interval=interval,
                limit=count,
            )
        except Exception as exc:
            raise ConnectorError(
                f"get_candles({symbol},{timeframe}) failed: {exc}"
            ) from exc

        if not klines:
            raise ConnectorError(
                f"Binance returned no candles for {symbol} {timeframe}. "
                "Check symbol name and market hours."
            )

        candles = []
        for k in klines:
            candles.append(
                Candle(
                    time=datetime.fromtimestamp(int(k[0]) / 1000, tz=dt_timezone.utc),
                    open=float(k[1]),
                    high=float(k[2]),
                    low=float(k[3]),
                    close=float(k[4]),
                    volume=int(float(k[5])),
                    spread=0,
                )
            )
        return candles

    def get_tick(self, symbol: str) -> Tick:
        """
        Fetch the current best bid/ask for a symbol.

        Uses the order book ticker for accurate bid/ask spread.
        """
        self._require_connection()

        try:
            ticker = self._client.get_orderbook_ticker(symbol=symbol)
        except Exception as exc:
            raise ConnectorError(f"get_tick({symbol}) failed: {exc}") from exc

        if not ticker:
            raise ConnectorError(
                f"No tick data for {symbol}. Symbol may be unavailable."
            )

        bid = float(ticker["bidPrice"])
        ask = float(ticker["askPrice"])

        return Tick(
            symbol=symbol,
            bid=bid,
            ask=ask,
            spread_points=ask - bid,
            time=datetime.now(tz=dt_timezone.utc),
        )

    # ------------------------------------------------------------------
    # Trade execution
    # ------------------------------------------------------------------

    def open_trade(
        self,
        symbol: str,
        trade_type: str,
        lot: float,
        sl: float,
        tp: float,
        comment: str = "FlockTrade",
    ) -> TradeResult:
        """
        Send a market order to Binance.

        Note: Binance spot does not support native SL/TP on market orders.
        SL/TP are managed by the bot's exit monitor. The lot parameter
        represents the quantity in the base asset.

        Args:
            symbol:     Trading symbol, e.g. "BTCUSDT"
            trade_type: "BUY" or "SELL"
            lot:        Quantity in base asset (e.g. 0.001 BTC)
            sl:         Stop loss price (managed by bot, not sent to Binance)
            tp:         Take profit price (managed by bot, not sent to Binance)
            comment:    Order comment (stored in newClientOrderId)

        Returns:
            TradeResult with order ID on success.
        """
        self._require_connection()

        side = trade_type.upper()
        if side not in ("BUY", "SELL"):
            return TradeResult(
                success=False,
                error_message=f"Invalid trade type: {trade_type}",
            )

        # Adjust quantity to Binance precision
        try:
            adjusted_qty = self._adjust_quantity(symbol, lot)
        except ConnectorError as exc:
            return TradeResult(success=False, error_message=str(exc))

        try:
            order = self._client.create_order(
                symbol=symbol,
                side=side,
                type="MARKET",
                quantity=adjusted_qty,
                newClientOrderId=f"FT_{comment[:20]}_{int(time.time())}",
            )
        except Exception as exc:
            logger.error(
                "Trade open failed: %s %s %s qty=%s: %s",
                symbol, side, lot, adjusted_qty, exc,
            )
            return TradeResult(
                success=False,
                error_message=str(exc),
            )

        if order.get("status") in ("FILLED", "PARTIALLY_FILLED"):
            # Calculate average fill price from fills
            fills = order.get("fills", [])
            if fills:
                total_qty = sum(float(f["qty"]) for f in fills)
                total_cost = sum(float(f["qty"]) * float(f["price"]) for f in fills)
                avg_price = total_cost / total_qty if total_qty > 0 else 0.0
            else:
                avg_price = float(order.get("price", 0))

            order_id = int(order["orderId"])
            logger.info(
                "Trade opened: %s %s %s qty=%s @ %.8f orderId=%d",
                symbol, side, lot, adjusted_qty, avg_price, order_id,
            )
            return TradeResult(
                success=True,
                ticket=order_id,
                price=avg_price,
            )

        logger.error(
            "Trade not filled: %s %s status=%s",
            symbol, side, order.get("status"),
        )
        return TradeResult(
            success=False,
            error_code=int(order.get("orderId", 0)),
            error_message=f"Order status: {order.get('status')}",
        )

    def close_trade(self, ticket: int, comment: str = "FlockTrade-Exit") -> TradeResult:
        """
        Close an open position by placing a reverse market order.

        On Binance spot, closing means selling what was bought (or buying
        back what was sold). The ticket is the original order ID; we look
        up the trade details from the DB.

        Args:
            ticket:  Original Binance order ID
            comment: Closing comment

        Returns:
            TradeResult indicating success or failure.
        """
        self._require_connection()

        # Look up the open trade in the DB to know symbol, side, quantity
        try:
            from trading.models import Trade
            db_trade = Trade.objects.filter(
                exit_time__isnull=True,
                binance_order_id=str(ticket),
            ).first()
        except Exception:
            db_trade = None

        if db_trade is None:
            return TradeResult(
                success=False,
                ticket=ticket,
                error_message=f"Cannot find open trade with order ID {ticket}",
            )

        # Determine close side (reverse of open)
        close_side = "SELL" if db_trade.type == "BUY" else "BUY"
        quantity = float(db_trade.lot_size)

        try:
            adjusted_qty = self._adjust_quantity(db_trade.symbol, quantity)
        except ConnectorError as exc:
            return TradeResult(success=False, ticket=ticket, error_message=str(exc))

        try:
            order = self._client.create_order(
                symbol=db_trade.symbol,
                side=close_side,
                type="MARKET",
                quantity=adjusted_qty,
                newClientOrderId=f"FT_{comment[:20]}_{int(time.time())}",
            )
        except Exception as exc:
            logger.error("Close trade failed for order %d: %s", ticket, exc)
            return TradeResult(
                success=False,
                ticket=ticket,
                error_message=str(exc),
            )

        if order.get("status") in ("FILLED", "PARTIALLY_FILLED"):
            fills = order.get("fills", [])
            if fills:
                total_qty = sum(float(f["qty"]) for f in fills)
                total_cost = sum(float(f["qty"]) * float(f["price"]) for f in fills)
                avg_price = total_cost / total_qty if total_qty > 0 else 0.0
            else:
                avg_price = float(order.get("price", 0))

            logger.info("Trade closed: orderId=%d @ %.8f", ticket, avg_price)
            return TradeResult(
                success=True,
                ticket=ticket,
                price=avg_price,
            )

        return TradeResult(
            success=False,
            ticket=ticket,
            error_message=f"Close order status: {order.get('status')}",
        )

    # ------------------------------------------------------------------
    # Account & position queries
    # ------------------------------------------------------------------

    def get_positions(self) -> list[Position]:
        """
        Return all currently open positions from the database.

        Binance spot doesn't have a native "positions" concept like MT5.
        We derive positions from DB open trades + current market prices.
        """
        self._require_connection()

        try:
            from trading.models import Trade
            open_trades = Trade.objects.filter(
                exit_time__isnull=True,
                account_type=self._account_type,
            )
        except Exception as exc:
            raise ConnectorError(f"get_positions() DB query failed: {exc}") from exc

        positions = []
        for trade in open_trades:
            # Fetch current price for P&L calculation
            try:
                tick = self.get_tick(trade.symbol)
                if trade.type == "BUY":
                    current_price = tick.bid
                    profit = (current_price - float(trade.entry_price)) * float(trade.lot_size)
                else:
                    current_price = tick.ask
                    profit = (float(trade.entry_price) - current_price) * float(trade.lot_size)
            except ConnectorError:
                profit = 0.0

            positions.append(
                Position(
                    ticket=int(trade.binance_order_id) if trade.binance_order_id else 0,
                    symbol=trade.symbol,
                    type=trade.type,
                    volume=float(trade.lot_size or 0),
                    price_open=float(trade.entry_price or 0),
                    sl=float(trade.sl or 0),
                    tp=float(trade.tp or 0),
                    profit=profit,
                    comment=f"FT_{trade.pk}",
                    time=trade.entry_time or datetime.now(tz=dt_timezone.utc),
                )
            )
        return positions

    def get_history(
        self, from_date: datetime, to_date: datetime,
    ) -> list[HistoryDeal]:
        """
        Fetch trade history between two UTC datetimes.

        Returns closed deals from the database since Binance spot
        doesn't distinguish position open/close like MT5.
        """
        self._require_connection()

        try:
            from trading.models import Trade
            closed_trades = Trade.objects.filter(
                exit_time__isnull=False,
                account_type=self._account_type,
                exit_time__gte=from_date,
                exit_time__lte=to_date,
            ).order_by("exit_time")
        except Exception as exc:
            raise ConnectorError(f"get_history() failed: {exc}") from exc

        history = []
        for trade in closed_trades:
            history.append(
                HistoryDeal(
                    ticket=int(trade.binance_order_id) if trade.binance_order_id else 0,
                    order=int(trade.binance_order_id) if trade.binance_order_id else 0,
                    symbol=trade.symbol,
                    type=trade.type,
                    volume=float(trade.lot_size or 0),
                    price=float(trade.exit_price or 0),
                    profit=float(trade.pnl or 0),
                    comment=trade.exit_reason or "",
                    time=trade.exit_time,
                )
            )
        return history

    def get_account_info(self) -> AccountInfo:
        """
        Fetch current account balance and equity from Binance.

        Reads the USDT balance as the primary account currency.
        """
        self._require_connection()

        try:
            account = self._client.get_account()
        except Exception as exc:
            raise ConnectorError(f"get_account_info() failed: {exc}") from exc

        if account is None:
            raise ConnectorError("Binance returned None for get_account()")

        # Find USDT balance
        balances = account.get("balances", [])
        usdt_balance = 0.0
        usdt_free = 0.0
        total_btc_value = 0.0

        for b in balances:
            asset_free = float(b.get("free", 0))
            asset_locked = float(b.get("locked", 0))
            if b["asset"] == "USDT":
                usdt_balance = asset_free + asset_locked
                usdt_free = asset_free

        # Approximate total equity from all non-zero balances would require
        # price lookups for each asset. For simplicity, use USDT balance
        # as both balance and equity.
        return AccountInfo(
            balance=usdt_balance,
            equity=usdt_balance,
            margin=usdt_balance - usdt_free,
            free_margin=usdt_free,
            margin_level=100.0 if usdt_balance > 0 else 0.0,
            currency="USDT",
            login=0,
            server="binance-testnet" if self._testnet else "binance",
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_connection(self) -> None:
        """Raise ConnectorError if not connected after auto-reconnect attempt."""
        if not self.ensure_connected():
            raise ConnectorError(
                "Binance is not connected. Reconnect attempts exhausted."
            )

    def _create_client(self) -> Any:
        """Create and return a Binance API client."""
        try:
            from binance.client import Client
        except ImportError as exc:
            raise ConnectorError(
                "python-binance is not installed. Add 'python-binance' to requirements.txt."
            ) from exc

        if self._testnet:
            client = Client(
                self._api_key,
                self._api_secret,
                testnet=True,
            )
            client.API_URL = self.TESTNET_API_URL
        else:
            client = Client(self._api_key, self._api_secret)

        return client

    @staticmethod
    def _resolve_timeframe(timeframe: str) -> str:
        """Map a FlockTrade timeframe string to Binance kline interval."""
        interval = TIMEFRAMES.get(timeframe.upper())
        if interval is None:
            raise ValueError(
                f"Unknown timeframe '{timeframe}'. "
                f"Valid values: {list(TIMEFRAMES.keys())}"
            )
        return interval

    def _get_symbol_info(self, symbol: str) -> dict:
        """
        Get exchange info for a symbol (cached per session).

        Returns the symbol filter dict including LOT_SIZE stepSize.
        """
        if symbol in self._exchange_info_cache:
            return self._exchange_info_cache[symbol]

        try:
            info = self._client.get_symbol_info(symbol)
        except Exception as exc:
            raise ConnectorError(
                f"Cannot get exchange info for {symbol}: {exc}"
            ) from exc

        if info is None:
            raise ConnectorError(f"Symbol {symbol} not found on Binance.")

        self._exchange_info_cache[symbol] = info
        return info

    def _adjust_quantity(self, symbol: str, quantity: float) -> str:
        """
        Adjust a quantity to comply with Binance LOT_SIZE filter.

        Returns the quantity as a string with proper precision.
        """
        info = self._get_symbol_info(symbol)
        filters = {f["filterType"]: f for f in info.get("filters", [])}

        lot_filter = filters.get("LOT_SIZE", {})
        step_size = lot_filter.get("stepSize", "0.00001000")
        min_qty = float(lot_filter.get("minQty", "0.00001"))

        # Calculate precision from step size
        step_dec = Decimal(str(step_size))
        qty_dec = Decimal(str(quantity))

        # Round down to step size
        adjusted = (qty_dec / step_dec).to_integral_value(rounding=ROUND_DOWN) * step_dec

        if float(adjusted) < min_qty:
            raise ConnectorError(
                f"Quantity {quantity} below minimum {min_qty} for {symbol}"
            )

        # Determine decimal places from step size
        step_str = str(step_dec.normalize())
        if "." in step_str:
            precision = len(step_str.split(".")[1])
        else:
            precision = 0

        return f"{adjusted:.{precision}f}"


# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------

_demo_connector: BinanceConnector | None = None
_real_connector: BinanceConnector | None = None


def get_connector(account_type: str = "DEMO") -> BinanceConnector:
    """
    Return the application-wide BinanceConnector instance for the given
    account type.

    Creates it on first call. The caller is responsible for calling
    connect() before use and disconnect() on shutdown.
    """
    global _demo_connector, _real_connector

    if account_type.upper() == "REAL":
        if _real_connector is None:
            _real_connector = BinanceConnector(account_type="REAL")
        return _real_connector
    else:
        if _demo_connector is None:
            _demo_connector = BinanceConnector(account_type="DEMO")
        return _demo_connector
