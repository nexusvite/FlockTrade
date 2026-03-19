"""
MT5 Connector for FlockTrade.

Manages the RPyC connection to the MetaTrader 5 Docker container
(gmag11/metatrader5_vnc:2.0). Provides a clean Python interface over
the raw mt5linux RPyC bridge with auto-reconnect and health checks.

Configuration is read from django.conf.settings:
    MT5_HOST  - Docker service hostname (default: mt5-trading)
    MT5_PORT  - RPyC port (default: 8001)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from django.conf import settings

logger = logging.getLogger("trading.mt5_connector")

# ---------------------------------------------------------------------------
# Data transfer objects
# ---------------------------------------------------------------------------


@dataclass
class Candle:
    """Single OHLCV bar returned from MT5."""

    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    spread: int = 0


@dataclass
class Tick:
    """Current best bid/ask for a symbol."""

    symbol: str
    bid: float
    ask: float
    spread_points: float
    time: datetime


@dataclass
class AccountInfo:
    """Snapshot of the trading account."""

    balance: float
    equity: float
    margin: float
    free_margin: float
    margin_level: float
    currency: str
    login: int
    server: str


@dataclass
class Position:
    """Open MT5 position."""

    ticket: int
    symbol: str
    type: str          # "BUY" or "SELL"
    volume: float
    price_open: float
    sl: float
    tp: float
    profit: float
    comment: str
    time: datetime


@dataclass
class HistoryDeal:
    """Closed deal from MT5 history."""

    ticket: int
    order: int
    symbol: str
    type: str
    volume: float
    price: float
    profit: float
    comment: str
    time: datetime


@dataclass
class TradeResult:
    """Result of an open/close trade request."""

    success: bool
    ticket: int = 0
    price: float = 0.0
    error_code: int = 0
    error_message: str = ""


# ---------------------------------------------------------------------------
# MT5 Timeframe constants (mirroring mt5linux values)
# ---------------------------------------------------------------------------

TIMEFRAMES: dict[str, int] = {
    "M1": 1,
    "M5": 5,
    "M15": 15,
    "M30": 30,
    "H1": 16385,
    "H4": 16388,
    "D1": 16408,
}

ORDER_TYPE_BUY = 0
ORDER_TYPE_SELL = 1


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------


class MT5ConnectorError(Exception):
    """Raised when an MT5 operation fails permanently."""


class MT5Connector:
    """
    Thread-safe RPyC bridge to MetaTrader 5.

    Usage:
        connector = MT5Connector()
        connector.connect()
        candles = connector.get_candles("USDJPYm", "M5", 100)
        connector.disconnect()

    The connector reads MT5_HOST and MT5_PORT from Django settings so
    no environment parsing is needed at call sites.
    """

    # Reconnect policy
    MAX_RETRIES: int = 5
    BASE_BACKOFF: float = 1.0   # seconds
    MAX_BACKOFF: float = 60.0   # seconds

    def __init__(self) -> None:
        self._conn: Any = None          # rpyc connection
        self._mt5: Any = None           # remote mt5 module proxy
        from trading.config_service import get_global_config

        gc = get_global_config()
        self._host: str = gc.mt5_host if gc else getattr(settings, "MT5_HOST", "mt5-trading")
        self._port: int = gc.mt5_port if gc else getattr(settings, "MT5_PORT", 8001)
        self._connected: bool = False
        self._retry_count: int = 0
        self._last_error: str = ""

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """
        Establish RPyC connection to the MT5 Docker container.

        Attempts up to MAX_RETRIES times with exponential backoff.
        Returns True on success, False if all retries are exhausted.
        """
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                logger.info(
                    "MT5 connect attempt %d/%d to %s:%d",
                    attempt,
                    self.MAX_RETRIES,
                    self._host,
                    self._port,
                )
                self._conn, self._mt5 = self._open_rpyc_connection()
                self._connected = True
                self._retry_count = 0
                logger.info("MT5 connected successfully to %s:%d", self._host, self._port)
                return True

            except Exception as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                logger.warning("MT5 connect attempt %d failed: %s", attempt, self._last_error)
                self._connected = False
                if attempt < self.MAX_RETRIES:
                    backoff = min(
                        self.BASE_BACKOFF * (2 ** (attempt - 1)), self.MAX_BACKOFF
                    )
                    logger.info("Retrying MT5 connection in %.1f seconds…", backoff)
                    time.sleep(backoff)

        logger.error(
            "MT5 connection failed after %d attempts. Giving up.", self.MAX_RETRIES
        )
        return False

    def disconnect(self) -> None:
        """Close the RPyC connection gracefully."""
        if self._conn is not None:
            try:
                self._conn.close()
                logger.info("MT5 connection closed.")
            except Exception as exc:
                logger.warning("Error closing MT5 connection: %s", exc)
            finally:
                self._conn = None
                self._mt5 = None
                self._connected = False

    def is_connected(self) -> bool:
        """Return True if the connection is currently live."""
        if not self._connected or self._conn is None:
            return False
        try:
            # Lightweight probe: check if the remote object is reachable
            _ = self._mt5.version()
            return True
        except Exception:
            self._connected = False
            return False

    def ensure_connected(self) -> bool:
        """
        Ensure the connection is alive, reconnecting if necessary.

        Called before every API operation. Returns True if connected.
        """
        if self.is_connected():
            return True
        logger.warning("MT5 connection lost — attempting reconnect…")
        return self.connect()

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    def get_candles(
        self, symbol: str, timeframe: str, count: int = 100
    ) -> list[Candle]:
        """
        Fetch the most recent `count` OHLCV bars for the given symbol/timeframe.

        Args:
            symbol:    e.g. "USDJPYm"
            timeframe: one of M1, M5, M15, M30, H1, H4, D1
            count:     number of bars to fetch (most recent first)

        Returns:
            List of Candle objects, oldest bar first.

        Raises:
            MT5ConnectorError if MT5 returns no data.
        """
        self._require_connection()
        tf_const = self._resolve_timeframe(timeframe)

        try:
            rates = self._mt5.copy_rates_from_pos(symbol, tf_const, 0, count)
        except Exception as exc:
            raise MT5ConnectorError(f"get_candles({symbol},{timeframe}) failed: {exc}") from exc

        if rates is None or len(rates) == 0:
            raise MT5ConnectorError(
                f"MT5 returned no candles for {symbol} {timeframe}. "
                "Check symbol name and market hours."
            )

        candles = [
            Candle(
                time=datetime.utcfromtimestamp(int(r[0])),
                open=float(r[1]),
                high=float(r[2]),
                low=float(r[3]),
                close=float(r[4]),
                volume=int(r[5]),
                spread=int(r[6]) if len(r) > 6 else 0,
            )
            for r in rates
        ]
        return candles

    def get_tick(self, symbol: str) -> Tick:
        """
        Fetch the current best bid/ask tick for a symbol.

        Raises:
            MT5ConnectorError if no tick data is available.
        """
        self._require_connection()
        try:
            tick = self._mt5.symbol_info_tick(symbol)
        except Exception as exc:
            raise MT5ConnectorError(f"get_tick({symbol}) failed: {exc}") from exc

        if tick is None:
            raise MT5ConnectorError(
                f"No tick data for {symbol}. Symbol may be unavailable."
            )

        return Tick(
            symbol=symbol,
            bid=float(tick.bid),
            ask=float(tick.ask),
            spread_points=float(tick.ask - tick.bid),
            time=datetime.utcfromtimestamp(int(tick.time)),
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
        Send a market order to MT5.

        Args:
            symbol:     Trading symbol, e.g. "USDJPYm"
            trade_type: "BUY" or "SELL"
            lot:        Lot size
            sl:         Stop loss price (absolute price level)
            tp:         Take profit price (absolute price level)
            comment:    MT5 order comment (max 31 chars)

        Returns:
            TradeResult with ticket number on success.
        """
        self._require_connection()

        order_type = ORDER_TYPE_BUY if trade_type.upper() == "BUY" else ORDER_TYPE_SELL

        try:
            tick = self._mt5.symbol_info_tick(symbol)
            if tick is None:
                return TradeResult(
                    success=False,
                    error_message=f"Cannot get tick for {symbol}",
                )
            price = float(tick.ask) if order_type == ORDER_TYPE_BUY else float(tick.bid)

            request = {
                "action": self._mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": float(lot),
                "type": order_type,
                "price": price,
                "sl": float(sl),
                "tp": float(tp),
                "deviation": 20,
                "magic": 202600,   # FlockTrade magic number
                "comment": comment[:31],
                "type_time": self._mt5.ORDER_TIME_GTC,
                "type_filling": self._mt5.ORDER_FILLING_IOC,
            }

            result = self._mt5.order_send(request)
        except Exception as exc:
            raise MT5ConnectorError(f"open_trade({symbol},{trade_type}) failed: {exc}") from exc

        if result is None:
            last_error = self._mt5.last_error()
            return TradeResult(
                success=False,
                error_code=last_error[0] if last_error else -1,
                error_message=str(last_error),
            )

        if result.retcode == 10009:  # TRADE_RETCODE_DONE
            logger.info(
                "Trade opened: %s %s %.2f lots @ %.5f ticket=%d",
                symbol, trade_type, lot, result.price, result.order,
            )
            return TradeResult(
                success=True,
                ticket=int(result.order),
                price=float(result.price),
            )

        logger.error(
            "Trade rejected: %s %s retcode=%d comment=%s",
            symbol, trade_type, result.retcode, result.comment,
        )
        return TradeResult(
            success=False,
            error_code=int(result.retcode),
            error_message=result.comment,
        )

    def close_trade(self, ticket: int, comment: str = "FlockTrade-Exit") -> TradeResult:
        """
        Close an open position by ticket number.

        Args:
            ticket:  MT5 position ticket
            comment: Closing comment

        Returns:
            TradeResult indicating success or failure.
        """
        self._require_connection()

        try:
            position = self._mt5.positions_get(ticket=ticket)
        except Exception as exc:
            raise MT5ConnectorError(f"close_trade({ticket}) lookup failed: {exc}") from exc

        if not position:
            return TradeResult(
                success=False,
                ticket=ticket,
                error_message=f"Position {ticket} not found.",
            )

        pos = position[0]
        # Opposite order type to close
        close_type = ORDER_TYPE_SELL if pos.type == ORDER_TYPE_BUY else ORDER_TYPE_BUY

        try:
            tick = self._mt5.symbol_info_tick(pos.symbol)
            price = float(tick.bid) if close_type == ORDER_TYPE_SELL else float(tick.ask)

            request = {
                "action": self._mt5.TRADE_ACTION_DEAL,
                "symbol": pos.symbol,
                "volume": float(pos.volume),
                "type": close_type,
                "position": ticket,
                "price": price,
                "deviation": 20,
                "magic": 202600,
                "comment": comment[:31],
                "type_time": self._mt5.ORDER_TIME_GTC,
                "type_filling": self._mt5.ORDER_FILLING_IOC,
            }
            result = self._mt5.order_send(request)
        except Exception as exc:
            raise MT5ConnectorError(f"close_trade({ticket}) order_send failed: {exc}") from exc

        if result is None:
            return TradeResult(
                success=False,
                ticket=ticket,
                error_message="MT5 returned None for close order",
            )

        if result.retcode == 10009:
            logger.info("Trade closed: ticket=%d @ %.5f", ticket, result.price)
            return TradeResult(
                success=True,
                ticket=ticket,
                price=float(result.price),
            )

        logger.error(
            "Close rejected: ticket=%d retcode=%d comment=%s",
            ticket, result.retcode, result.comment,
        )
        return TradeResult(
            success=False,
            ticket=ticket,
            error_code=int(result.retcode),
            error_message=result.comment,
        )

    # ------------------------------------------------------------------
    # Account & position queries
    # ------------------------------------------------------------------

    def get_positions(self) -> list[Position]:
        """Return all currently open positions for the account."""
        self._require_connection()
        try:
            raw = self._mt5.positions_get()
        except Exception as exc:
            raise MT5ConnectorError(f"get_positions() failed: {exc}") from exc

        if raw is None:
            return []

        positions = []
        for p in raw:
            positions.append(
                Position(
                    ticket=int(p.ticket),
                    symbol=str(p.symbol),
                    type="BUY" if p.type == ORDER_TYPE_BUY else "SELL",
                    volume=float(p.volume),
                    price_open=float(p.price_open),
                    sl=float(p.sl),
                    tp=float(p.tp),
                    profit=float(p.profit),
                    comment=str(p.comment),
                    time=datetime.utcfromtimestamp(int(p.time)),
                )
            )
        return positions

    def get_history(
        self, from_date: datetime, to_date: datetime
    ) -> list[HistoryDeal]:
        """
        Fetch closed deal history between two UTC datetimes.

        Returns:
            List of HistoryDeal, ordered oldest first.
        """
        self._require_connection()
        try:
            deals = self._mt5.history_deals_get(from_date, to_date)
        except Exception as exc:
            raise MT5ConnectorError(f"get_history() failed: {exc}") from exc

        if deals is None:
            return []

        history = []
        for d in deals:
            history.append(
                HistoryDeal(
                    ticket=int(d.ticket),
                    order=int(d.order),
                    symbol=str(d.symbol),
                    type="BUY" if d.type == 0 else "SELL",
                    volume=float(d.volume),
                    price=float(d.price),
                    profit=float(d.profit),
                    comment=str(d.comment),
                    time=datetime.utcfromtimestamp(int(d.time)),
                )
            )
        return history

    def get_account_info(self) -> AccountInfo:
        """
        Fetch current account balance, equity, and margin data.

        Raises:
            MT5ConnectorError if account info is unavailable.
        """
        self._require_connection()
        try:
            info = self._mt5.account_info()
        except Exception as exc:
            raise MT5ConnectorError(f"get_account_info() failed: {exc}") from exc

        if info is None:
            raise MT5ConnectorError("MT5 returned None for account_info()")

        return AccountInfo(
            balance=float(info.balance),
            equity=float(info.equity),
            margin=float(info.margin),
            free_margin=float(info.margin_free),
            margin_level=float(info.margin_level),
            currency=str(info.currency),
            login=int(info.login),
            server=str(info.server),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_connection(self) -> None:
        """
        Raise MT5ConnectorError if not connected after an auto-reconnect attempt.
        """
        if not self.ensure_connected():
            raise MT5ConnectorError(
                "MT5 is not connected. Reconnect attempts exhausted."
            )

    @staticmethod
    def _resolve_timeframe(timeframe: str) -> int:
        """Map a human-readable timeframe string to the MT5 integer constant."""
        tf = TIMEFRAMES.get(timeframe.upper())
        if tf is None:
            raise ValueError(
                f"Unknown timeframe '{timeframe}'. "
                f"Valid values: {list(TIMEFRAMES.keys())}"
            )
        return tf

    def _open_rpyc_connection(self) -> tuple[Any, Any]:
        """
        Open the RPyC TCP connection and return (connection, mt5_module).

        The gmag11/metatrader5_vnc image runs an RPyC **classic** server
        via mt5linux. In classic mode the remote MetaTrader5 module is
        accessed through ``conn.modules.MetaTrader5``, not ``conn.root``.

        Isolated here so tests can mock it cleanly.
        """
        try:
            import rpyc  # type: ignore[import]
            import rpyc.utils.classic  # type: ignore[import]
        except ImportError as exc:
            raise MT5ConnectorError(
                "rpyc is not installed. Add 'rpyc' to requirements.txt."
            ) from exc

        conn = rpyc.classic.connect(
            self._host,
            self._port,
        )
        mt5 = conn.modules.MetaTrader5
        if not mt5.initialize():
            logger.warning("mt5.initialize() returned False — terminal may not be logged in")
        return conn, mt5


# ---------------------------------------------------------------------------
# Module-level singleton for use across the application
# ---------------------------------------------------------------------------

_connector: MT5Connector | None = None


def get_connector() -> MT5Connector:
    """
    Return the application-wide MT5Connector instance.

    Creates it on first call. The caller is responsible for calling
    connect() before use and disconnect() on shutdown.
    """
    global _connector
    if _connector is None:
        _connector = MT5Connector()
    return _connector
