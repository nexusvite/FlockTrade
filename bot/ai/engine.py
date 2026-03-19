"""
AIEngine — FlockTrade's async dual-AI trading decision engine.

Architecture:
  Scout  (fast, cheap)  → scans every symbol every minute
  Confirmer (deep, costly) → gates BUY/SELL signals before execution
  Exit Manager (fast)    → monitors open positions every minute

Key features:
  - Async httpx for non-blocking API calls
  - In-memory LRU response cache to avoid duplicate calls
  - Per-model token-bucket rate limiting
  - Daily cost accumulator (persisted via Django cache / Redis)
  - Automatic DB logging of every decision (AIDecision model)
  - Configurable via django.conf.settings
"""
import asyncio
import hashlib
import json
import logging
import time
from collections import defaultdict
from decimal import Decimal
from typing import Any

import httpx
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from .models import AIDecision, AIRole
from .parsers import estimate_cost, extract_usage_from_response, parse_ai_response
from .prompts import build_confirmer_messages, build_exit_messages, build_scout_messages

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OPENROUTER_URL: str = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_REFERER: str = "https://flocktrade.app"
OPENROUTER_TITLE: str = "FlockTrade"

# Cache key prefixes (stored in Redis via Django cache framework).
CACHE_PREFIX_RESPONSE: str = "ai:resp:"       # Deduplicated response cache
CACHE_PREFIX_DAILY_COST: str = "ai:cost:"     # Cost accumulator: cost:model:date
CACHE_PREFIX_DAILY_CALLS: str = "ai:calls:"   # Call counter: calls:model:date

# Response cache TTL — 90 seconds.  Same candle data won't change in 1 minute.
RESPONSE_CACHE_TTL: int = 90

# Daily cost cache TTL — 25 hours (survive day boundary + 1 hour buffer).
DAILY_CACHE_TTL: int = 25 * 3600

# Default temperature settings per role.
TEMPERATURE_SCOUT: float = 0.1      # Near-deterministic for speed
TEMPERATURE_CONFIRMER: float = 0.2  # Slightly more analytical
TEMPERATURE_EXIT: float = 0.1       # Deterministic exit decisions

# Max tokens per role (limit cost on runaway responses).
MAX_TOKENS_SCOUT: int = 200
MAX_TOKENS_CONFIRMER: int = 400
MAX_TOKENS_EXIT: int = 200


# ---------------------------------------------------------------------------
# Rate limiter — simple in-process token bucket
# ---------------------------------------------------------------------------

class _TokenBucket:
    """
    Async token-bucket rate limiter for a single model.

    Allows burst_size calls immediately, then refills at rate_per_second.
    Thread-safe via asyncio.Lock.
    """

    def __init__(self, rate_per_second: float = 2.0, burst_size: int = 5) -> None:
        self._rate = rate_per_second
        self._burst = burst_size
        self._tokens: float = burst_size
        self._last_refill: float = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Block until a token is available, then consume one."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(
                self._burst,
                self._tokens + elapsed * self._rate,
            )
            self._last_refill = now

            if self._tokens < 1.0:
                wait_time = (1.0 - self._tokens) / self._rate
                logger.debug("Rate limit: sleeping %.2fs for token.", wait_time)
                await asyncio.sleep(wait_time)
                self._tokens = 0.0
            else:
                self._tokens -= 1.0


# ---------------------------------------------------------------------------
# AIEngine
# ---------------------------------------------------------------------------

class AIEngine:
    """
    Async AI engine coordinating Scout and Confirmer LLM calls.

    Usage (inside an async context):
        engine = AIEngine.from_settings()
        scout_result  = await engine.scout_scan(context)
        confirm_result = await engine.confirm_trade(scout_result, context)
        exit_result   = await engine.evaluate_exit(trade, context)

    All three methods return a normalised dict:
        {"action": str, "confidence": int, "reason": str}

    Every call is logged to the AIDecision table regardless of outcome.
    """

    def __init__(
        self,
        scout_model: str,
        confirm_model: str,
        api_key: str,
        timeout: int = 15,
    ) -> None:
        self.scout_model = scout_model
        self.confirm_model = confirm_model
        self.api_key = api_key
        self.timeout = timeout

        # Per-model rate limiters (2 req/s burst 5 — well within OpenRouter limits).
        self._rate_limiters: dict[str, _TokenBucket] = defaultdict(
            lambda: _TokenBucket(rate_per_second=2.0, burst_size=5)
        )

        # Shared async httpx client (connection-pooled, reused across calls).
        self._http_client: httpx.AsyncClient | None = None
        self._client_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_settings(cls) -> "AIEngine":
        """Instantiate AIEngine from DB config, falling back to Django settings."""
        from trading.config_service import get_global_config

        gc = get_global_config()
        return cls(
            scout_model=gc.scout_model if gc else getattr(settings, "SCOUT_MODEL", "anthropic/claude-haiku-4.5"),
            confirm_model=gc.confirmer_model if gc else getattr(settings, "CONFIRMER_MODEL", "anthropic/claude-sonnet-4-6"),
            api_key=gc.openrouter_api_key if gc else getattr(settings, "OPENROUTER_API_KEY", ""),
            timeout=gc.ai_timeout if gc else getattr(settings, "AI_TIMEOUT", 15),
        )

    # ------------------------------------------------------------------
    # HTTP client lifecycle
    # ------------------------------------------------------------------

    async def _get_client(self) -> httpx.AsyncClient:
        """Return the shared httpx client, creating it if necessary."""
        async with self._client_lock:
            if self._http_client is None or self._http_client.is_closed:
                self._http_client = httpx.AsyncClient(
                    timeout=httpx.Timeout(
                        connect=5.0,
                        read=float(self.timeout),
                        write=5.0,
                        pool=2.0,
                    ),
                    limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
                )
            return self._http_client

    async def close(self) -> None:
        """Gracefully close the underlying HTTP connection pool."""
        async with self._client_lock:
            if self._http_client and not self._http_client.is_closed:
                await self._http_client.aclose()
                self._http_client = None

    async def __aenter__(self) -> "AIEngine":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def scout_scan(self, context: dict) -> dict:
        """
        Run the Scout model against current market context.

        Args:
            context: Trading context dict with candles, indicators, S/R levels.
                     Must contain at minimum: symbol, current_price, candles.

        Returns:
            Normalised dict: {action: BUY|SELL|SKIP, confidence: int, reason: str}
        """
        symbol: str = context.get("symbol", "UNKNOWN")
        messages = build_scout_messages(context)

        result, latency_ms, cost_usd, raw_response = await self._call_openrouter(
            model=self.scout_model,
            messages=messages,
            temperature=TEMPERATURE_SCOUT,
            max_tokens=MAX_TOKENS_SCOUT,
            context_key=self._cache_key(self.scout_model, messages),
        )

        # Validate / coerce result for scout role.
        parsed = parse_ai_response(raw_response, role="scout")
        if result and result != parsed:
            # result came from cache — still re-validate.
            parsed = result

        await self._log_decision(
            symbol=symbol,
            role=AIRole.SCOUT,
            model=self.scout_model,
            parsed=parsed,
            input_context=json.dumps(context, default=str),
            raw_response=raw_response,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
        )

        logger.info(
            "[Scout] %s → %s (%s%%) | %dms | $%.6f",
            symbol, parsed["action"], parsed["confidence"], latency_ms, cost_usd,
        )
        return parsed

    async def confirm_trade(self, signal: dict, context: dict) -> dict:
        """
        Run the Confirmer model against a scout BUY/SELL signal.

        Should only be called when scout returns BUY or SELL.

        Args:
            signal: Scout result dict {action, confidence, reason}.
            context: Full trading context dict.

        Returns:
            Normalised dict: {action: CONFIRM|REJECT, confidence: int, reason: str}
        """
        symbol: str = context.get("symbol", "UNKNOWN")
        messages = build_confirmer_messages(signal, context)

        result, latency_ms, cost_usd, raw_response = await self._call_openrouter(
            model=self.confirm_model,
            messages=messages,
            temperature=TEMPERATURE_CONFIRMER,
            max_tokens=MAX_TOKENS_CONFIRMER,
            context_key=self._cache_key(self.confirm_model, messages),
        )

        parsed = parse_ai_response(raw_response, role="confirmer")
        if result and result != parsed:
            parsed = result

        await self._log_decision(
            symbol=symbol,
            role=AIRole.CONFIRMER,
            model=self.confirm_model,
            parsed=parsed,
            input_context=json.dumps(
                {"signal": signal, "context": context}, default=str
            ),
            raw_response=raw_response,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
        )

        logger.info(
            "[Confirmer] %s → %s (%s%%) | %dms | $%.6f",
            symbol, parsed["action"], parsed["confidence"], latency_ms, cost_usd,
        )
        return parsed

    async def evaluate_exit(self, trade: dict, context: dict) -> dict:
        """
        Run the Exit Manager model for an open position.

        Uses the same scout model (fast/cheap) since exit decisions need
        low latency and run every minute per open trade.

        Args:
            trade: Active trade dict with ticket, entry, PnL, bars open, etc.
            context: Current market context.

        Returns:
            Normalised dict: {action: HOLD|CLOSE, confidence: int, reason: str}
        """
        symbol: str = trade.get("symbol", "UNKNOWN")
        messages = build_exit_messages(trade, context)

        result, latency_ms, cost_usd, raw_response = await self._call_openrouter(
            model=self.scout_model,  # Use fast model for exits
            messages=messages,
            temperature=TEMPERATURE_EXIT,
            max_tokens=MAX_TOKENS_EXIT,
            context_key=self._cache_key(self.scout_model, messages),
        )

        parsed = parse_ai_response(raw_response, role="exit")
        if result and result != parsed:
            parsed = result

        await self._log_decision(
            symbol=symbol,
            role=AIRole.EXIT,
            model=self.scout_model,
            parsed=parsed,
            input_context=json.dumps(
                {"trade": trade, "context": context}, default=str
            ),
            raw_response=raw_response,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
        )

        logger.debug(
            "[Exit] %s → %s (%s%%) | %dms",
            symbol, parsed["action"], parsed["confidence"], latency_ms,
        )
        return parsed

    # ------------------------------------------------------------------
    # Core HTTP call
    # ------------------------------------------------------------------

    async def _call_openrouter(
        self,
        model: str,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        context_key: str,
    ) -> tuple[dict | None, int, float, str]:
        """
        Make an async HTTP POST to the OpenRouter Chat Completions endpoint.

        Implements:
          - Response caching (keyed on model + message hash)
          - Per-model token-bucket rate limiting
          - Structured error handling with safe fallback

        Args:
            model: Full OpenRouter model identifier.
            messages: OpenAI-format messages list.
            temperature: Sampling temperature.
            max_tokens: Max completion tokens.
            context_key: Cache key for deduplication.

        Returns:
            Tuple of (parsed_result_or_None, latency_ms, cost_usd, raw_response_text).
            On error returns (None, latency_ms, 0.0, error_message_string).
        """
        if not self.api_key:
            logger.error("OPENROUTER_API_KEY is not configured.")
            return None, 0, 0.0, '{"action": "ERROR", "confidence": 0, "reason": "API key not configured."}'

        # --- Cache check ---
        cached = cache.get(context_key)
        if cached is not None:
            logger.debug("AI response cache HIT: %s", context_key[:32])
            cached_data = json.loads(cached)
            return (
                cached_data["parsed"],
                0,       # Zero latency for cached responses
                0.0,     # Zero cost for cached responses
                cached_data["raw"],
            )

        # --- Rate limit ---
        await self._rate_limiters[model].acquire()

        # --- Build request payload ---
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        headers: dict[str, str] = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": OPENROUTER_REFERER,
            "X-Title": OPENROUTER_TITLE,
            "Content-Type": "application/json",
        }

        start_ns = time.perf_counter_ns()
        raw_response_text = ""

        try:
            client = await self._get_client()
            response = await client.post(
                OPENROUTER_URL,
                headers=headers,
                json=payload,
            )
            latency_ms = (time.perf_counter_ns() - start_ns) // 1_000_000

            response.raise_for_status()
            api_data: dict = response.json()

            # Extract text from OpenAI-compatible envelope.
            choices = api_data.get("choices", [])
            if not choices:
                raise ValueError("OpenRouter returned empty choices list.")

            raw_response_text = choices[0].get("message", {}).get("content", "")

            # Calculate cost from token usage.
            usage = extract_usage_from_response(api_data)
            cost_usd = estimate_cost(
                model=model,
                prompt_tokens=usage["prompt_tokens"],
                completion_tokens=usage["completion_tokens"],
            )

            # Parse the response.
            role_hint = self._role_hint_from_model(model)
            parsed = parse_ai_response(raw_response_text, role=role_hint)

            # Update cost trackers in Redis cache.
            await self._track_cost(model, cost_usd)

            # Store in response cache to avoid duplicate calls within TTL.
            cache.set(
                context_key,
                json.dumps({"parsed": parsed, "raw": raw_response_text}),
                timeout=RESPONSE_CACHE_TTL,
            )

            return parsed, latency_ms, cost_usd, raw_response_text

        except httpx.TimeoutException:
            latency_ms = (time.perf_counter_ns() - start_ns) // 1_000_000
            logger.error("OpenRouter timeout after %dms for model %s.", latency_ms, model)
            raw_response_text = '{"action": "ERROR", "confidence": 0, "reason": "API timeout."}'
            return None, latency_ms, 0.0, raw_response_text

        except httpx.HTTPStatusError as exc:
            latency_ms = (time.perf_counter_ns() - start_ns) // 1_000_000
            status = exc.response.status_code
            logger.error("OpenRouter HTTP %d for model %s: %s", status, model, exc.response.text[:200])
            raw_response_text = (
                f'{{"action": "ERROR", "confidence": 0, "reason": "HTTP {status} from OpenRouter."}}'
            )
            return None, latency_ms, 0.0, raw_response_text

        except httpx.RequestError as exc:
            latency_ms = (time.perf_counter_ns() - start_ns) // 1_000_000
            logger.error("OpenRouter request error for model %s: %s", model, exc)
            raw_response_text = (
                f'{{"action": "ERROR", "confidence": 0, "reason": "Network error: {type(exc).__name__}."}}'
            )
            return None, latency_ms, 0.0, raw_response_text

        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            latency_ms = (time.perf_counter_ns() - start_ns) // 1_000_000
            logger.error("OpenRouter response parse error for model %s: %s", model, exc)
            raw_response_text = raw_response_text or f"Parse error: {exc}"
            return None, latency_ms, 0.0, raw_response_text

    # ------------------------------------------------------------------
    # Cost tracking
    # ------------------------------------------------------------------

    async def _track_cost(self, model: str, cost_usd: float) -> None:
        """
        Accumulate cost and call count in Redis for the current day.

        Keys are namespaced by model and date so the AICostView can
        produce per-model-per-day breakdowns without hitting the database.
        """
        today = timezone.now().date().isoformat()
        cost_key = f"{CACHE_PREFIX_DAILY_COST}{model}:{today}"
        calls_key = f"{CACHE_PREFIX_DAILY_CALLS}{model}:{today}"

        try:
            # Atomic increment — Django's cache.incr is atomic for Redis backends.
            try:
                cache.incr(calls_key)
            except ValueError:
                cache.set(calls_key, 1, timeout=DAILY_CACHE_TTL)

            # Cost accumulation (Redis doesn't support float incr natively via
            # Django cache, so we use get-add-set with a small race condition
            # tolerance — sub-cent precision is sufficient for cost tracking).
            existing_cost: float = float(cache.get(cost_key) or 0.0)
            cache.set(cost_key, existing_cost + cost_usd, timeout=DAILY_CACHE_TTL)

        except Exception as exc:  # noqa: BLE001
            # Never let cost tracking failure kill a trade decision.
            logger.warning("Failed to update AI cost tracker: %s", exc)

    def get_daily_cost_summary(self) -> list[dict]:
        """
        Return cost and call count for all tracked models today.

        Reads from Redis cache — no database query needed.

        Returns:
            List of dicts: [{model, date, total_cost, total_calls}, ...]
        """
        today = timezone.now().date().isoformat()
        models = [self.scout_model, self.confirm_model]
        summary: list[dict] = []

        for model in models:
            cost_key = f"{CACHE_PREFIX_DAILY_COST}{model}:{today}"
            calls_key = f"{CACHE_PREFIX_DAILY_CALLS}{model}:{today}"

            total_cost = float(cache.get(cost_key) or 0.0)
            total_calls = int(cache.get(calls_key) or 0)

            summary.append(
                {
                    "model": model,
                    "date": today,
                    "total_cost_usd": round(total_cost, 6),
                    "total_calls": total_calls,
                    "avg_cost_per_call": (
                        round(total_cost / total_calls, 8) if total_calls > 0 else 0.0
                    ),
                }
            )

        return summary

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _cache_key(model: str, messages: list[dict]) -> str:
        """
        Generate a deterministic cache key from model + message content.

        Uses SHA-256 of the serialised messages to detect identical context
        (same candle bar, same S/R levels) and avoid redundant API calls.
        """
        content = model + json.dumps(messages, sort_keys=True)
        digest = hashlib.sha256(content.encode()).hexdigest()[:32]
        return f"{CACHE_PREFIX_RESPONSE}{digest}"

    def _role_hint_from_model(self, model: str) -> str:
        """Infer role hint from which model is being called."""
        if model == self.confirm_model:
            return "confirmer"
        return "scout"

    @staticmethod
    async def _log_decision(
        symbol: str,
        role: str,
        model: str,
        parsed: dict,
        input_context: str,
        raw_response: str,
        latency_ms: int,
        cost_usd: float,
    ) -> None:
        """
        Persist an AIDecision record to the database asynchronously.

        Uses Django's async ORM (acreate) available in Django 4.1+.
        Failures are logged but never propagated — trade execution must not
        be blocked by a DB write failure.
        """
        try:
            await AIDecision.objects.acreate(
                symbol=symbol,
                role=role,
                model=model,
                action=parsed.get("action", "ERROR"),
                confidence=parsed.get("confidence", 0),
                reason=parsed.get("reason", ""),
                input_context=input_context,
                raw_response=raw_response,
                latency_ms=latency_ms,
                cost_usd=Decimal(str(cost_usd)),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to log AIDecision to database: %s", exc)


# ---------------------------------------------------------------------------
# Module-level singleton accessor
# ---------------------------------------------------------------------------

_engine_instance: AIEngine | None = None
_engine_lock = asyncio.Lock()


async def get_ai_engine() -> AIEngine:
    """
    Return the module-level AIEngine singleton.

    Creates the engine on first call using Django settings.
    Safe to call from multiple async tasks — uses a lock to prevent
    double-initialisation.
    """
    global _engine_instance  # noqa: PLW0603

    if _engine_instance is not None:
        return _engine_instance

    async with _engine_lock:
        if _engine_instance is None:
            _engine_instance = AIEngine.from_settings()
            logger.info(
                "AIEngine initialised | scout=%s | confirmer=%s",
                _engine_instance.scout_model,
                _engine_instance.confirm_model,
            )

    return _engine_instance
