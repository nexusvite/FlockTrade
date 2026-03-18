"""
AI response parsers for FlockTrade.

OpenRouter / LLM responses are not always clean JSON. This module provides
a layered parsing strategy:

  1. Direct JSON parse of the full response body.
  2. Extract JSON from a markdown code block (```json ... ```).
  3. Regex extraction of a bare JSON object anywhere in the text.
  4. Heuristic text scanning as a last-resort fallback.

All paths return a normalised dict with at least: action, confidence, reason.
Invalid or unparseable responses return an ERROR action with full raw text
preserved for debugging.
"""
import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Recognised valid actions per AI role.
SCOUT_ACTIONS: frozenset[str] = frozenset({"BUY", "SELL", "SKIP"})
CONFIRMER_ACTIONS: frozenset[str] = frozenset({"CONFIRM", "REJECT"})
EXIT_ACTIONS: frozenset[str] = frozenset({"HOLD", "CLOSE"})
ALL_VALID_ACTIONS: frozenset[str] = SCOUT_ACTIONS | CONFIRMER_ACTIONS | EXIT_ACTIONS

# Regex to find a JSON object anywhere in the text (non-greedy, balanced braces
# won't match nested braces, but AI responses are always single-level objects).
_JSON_OBJECT_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)

# Regex to extract JSON from markdown code fences.
_CODE_FENCE_RE = re.compile(
    r"```(?:json)?\s*(\{.*?\})\s*```",
    re.DOTALL | re.IGNORECASE,
)

# Action keyword patterns for heuristic fallback.
_ACTION_PATTERNS: dict[str, re.Pattern[str]] = {
    action: re.compile(rf"\b{action}\b", re.IGNORECASE)
    for action in ALL_VALID_ACTIONS
}

# Confidence patterns: "confidence: 72", "72%", "72/100".
_CONFIDENCE_RE = re.compile(
    r'(?:"confidence"\s*:\s*(\d+))|'
    r'(\d+)\s*%|'
    r'(\d+)\s*/\s*100',
    re.IGNORECASE,
)


class ParseError(ValueError):
    """Raised when the AI response cannot be parsed into a valid decision."""


def _parse_json_object(text: str) -> dict[str, Any] | None:
    """Attempt to parse text as a raw JSON object."""
    stripped = text.strip()
    if not stripped.startswith("{"):
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return None


def _extract_from_code_fence(text: str) -> dict[str, Any] | None:
    """Extract JSON from a markdown ```json ... ``` block."""
    match = _CODE_FENCE_RE.search(text)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def _extract_bare_json(text: str) -> dict[str, Any] | None:
    """
    Find the first JSON object literal anywhere in the text.

    This handles cases where the LLM wraps the JSON in prose:
      'Sure! Here is my answer: {"action": "BUY", ...}'
    """
    for match in _JSON_OBJECT_RE.finditer(text):
        try:
            candidate = json.loads(match.group())
            if isinstance(candidate, dict):
                return candidate
        except json.JSONDecodeError:
            continue
    return None


def _heuristic_parse(text: str) -> dict[str, Any]:
    """
    Last-resort heuristic extraction when JSON parsing fails completely.

    Scans the text for action keywords and confidence numbers.
    Returns a best-effort dict — never raises.
    """
    logger.warning("AI parser falling back to heuristic extraction.")

    action = "SKIP"
    confidence = 0
    reason = text[:200].strip()  # Use first 200 chars as reason.

    # Find any known action keyword.
    for candidate_action, pattern in _ACTION_PATTERNS.items():
        if pattern.search(text):
            action = candidate_action
            break

    # Find any confidence number.
    conf_match = _CONFIDENCE_RE.search(text)
    if conf_match:
        raw_conf = next(g for g in conf_match.groups() if g is not None)
        confidence = min(100, max(0, int(raw_conf)))

    return {"action": action, "confidence": confidence, "reason": reason}


def _validate_and_normalise(data: dict[str, Any], role: str = "") -> dict[str, Any]:
    """
    Validate required fields and normalise types.

    Raises ParseError if the action field is missing or completely unrecognised.
    Other fields fall back to safe defaults.
    """
    if not isinstance(data, dict):
        raise ParseError(f"Expected dict, got {type(data).__name__}")

    # --- action ---
    raw_action: str = str(data.get("action", "")).upper().strip()
    if not raw_action:
        raise ParseError("Missing 'action' field in AI response.")

    # Map partial matches (e.g. model said "CONFIRMED" → "CONFIRM").
    action = raw_action
    for valid in ALL_VALID_ACTIONS:
        if raw_action.startswith(valid):
            action = valid
            break
    else:
        # Still not matched.
        logger.warning("Unrecognised action '%s' in AI response — defaulting SKIP.", raw_action)
        action = "SKIP"

    # Role-based action validation (log warnings, don't hard-fail).
    if role == "scout" and action not in SCOUT_ACTIONS:
        logger.warning("Scout returned non-scout action '%s', remapping to SKIP.", action)
        action = "SKIP"
    elif role == "confirmer" and action not in CONFIRMER_ACTIONS:
        logger.warning("Confirmer returned '%s', remapping to REJECT.", action)
        action = "REJECT"
    elif role == "exit" and action not in EXIT_ACTIONS:
        logger.warning("Exit returned '%s', remapping to HOLD.", action)
        action = "HOLD"

    # --- confidence ---
    try:
        confidence = int(data.get("confidence", 0))
        confidence = min(100, max(0, confidence))
    except (TypeError, ValueError):
        logger.warning("Invalid confidence value '%s', defaulting to 0.", data.get("confidence"))
        confidence = 0

    # --- reason ---
    reason: str = str(data.get("reason", "")).strip()
    if not reason:
        reason = f"No reason provided by model. Action: {action}, Confidence: {confidence}"

    # Truncate extreme lengths (models occasionally dump walls of text).
    if len(reason) > 500:
        reason = reason[:497] + "..."

    return {
        "action": action,
        "confidence": confidence,
        "reason": reason,
    }


def parse_ai_response(raw_text: str, role: str = "") -> dict[str, Any]:
    """
    Parse a raw OpenRouter/LLM response into a normalised decision dict.

    Tries multiple strategies in order of reliability:
      1. Direct JSON parse.
      2. Markdown code-fence extraction.
      3. Bare JSON object scan.
      4. Heuristic text fallback.

    Args:
        raw_text: The raw string content from the LLM response.
        role: Optional role hint ("scout", "confirmer", "exit") used for
              action validation. Pass empty string to skip role checks.

    Returns:
        Dict with keys: action (str), confidence (int), reason (str).
        Never raises — errors are captured in the action="ERROR" path.
    """
    if not raw_text or not raw_text.strip():
        logger.error("Empty AI response received.")
        return {
            "action": "ERROR",
            "confidence": 0,
            "reason": "Empty response from AI model.",
        }

    # Attempt each strategy.
    data: dict[str, Any] | None = None

    for strategy_name, strategy_fn in [
        ("direct_json", lambda t: _parse_json_object(t)),
        ("code_fence", lambda t: _extract_from_code_fence(t)),
        ("bare_json", lambda t: _extract_bare_json(t)),
    ]:
        data = strategy_fn(raw_text)
        if data is not None:
            logger.debug("AI response parsed via strategy: %s", strategy_name)
            break

    # Heuristic fallback.
    if data is None:
        data = _heuristic_parse(raw_text)

    # Validate and normalise.
    try:
        return _validate_and_normalise(data, role=role)
    except ParseError as exc:
        logger.error("AI response parse validation failed: %s | raw=%s", exc, raw_text[:200])
        return {
            "action": "ERROR",
            "confidence": 0,
            "reason": f"Parse error: {exc}",
        }


def extract_usage_from_response(api_response: dict[str, Any]) -> dict[str, int]:
    """
    Extract token usage from an OpenRouter API response envelope.

    OpenRouter wraps the LLM response in an OpenAI-compatible envelope:
      {"choices": [...], "usage": {"prompt_tokens": N, "completion_tokens": N}}

    Args:
        api_response: Full JSON dict from the OpenRouter HTTP response.

    Returns:
        Dict with: prompt_tokens, completion_tokens, total_tokens.
    """
    usage = api_response.get("usage") or {}
    return {
        "prompt_tokens": int(usage.get("prompt_tokens", 0)),
        "completion_tokens": int(usage.get("completion_tokens", 0)),
        "total_tokens": int(usage.get("total_tokens", 0)),
    }


def estimate_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> float:
    """
    Estimate USD cost for a single API call based on known model pricing.

    Prices are per-million-tokens as of March 2026. Update this table when
    model pricing changes. Falls back to a conservative estimate if the model
    is not in the table.

    Args:
        model: Full OpenRouter model identifier (e.g. "anthropic/claude-haiku-4.5").
        prompt_tokens: Number of input tokens consumed.
        completion_tokens: Number of output tokens generated.

    Returns:
        Estimated cost in USD as a float (e.g. 0.000125).
    """
    # Prices per million tokens: (prompt_price, completion_price)
    PRICING: dict[str, tuple[float, float]] = {
        # Anthropic
        "anthropic/claude-haiku-4.5": (0.80, 4.00),
        "anthropic/claude-haiku-3": (0.25, 1.25),
        "anthropic/claude-sonnet-4-6": (3.00, 15.00),
        "anthropic/claude-sonnet-3-5": (3.00, 15.00),
        "anthropic/claude-opus-4-6": (15.00, 75.00),
        # Google
        "google/gemini-flash-1.5": (0.075, 0.30),
        "google/gemini-flash-2.0": (0.10, 0.40),
        "google/gemini-pro-1.5": (1.25, 5.00),
        # DeepSeek
        "deepseek/deepseek-chat": (0.14, 0.28),
        "deepseek/deepseek-r1": (0.55, 2.19),
        # Mistral
        "mistralai/mistral-7b-instruct": (0.07, 0.07),
        "mistralai/mixtral-8x7b-instruct": (0.24, 0.24),
        # Meta
        "meta-llama/llama-3.1-8b-instruct": (0.06, 0.06),
        "meta-llama/llama-3.3-70b-instruct": (0.12, 0.40),
    }

    # Normalise model name for lookup (strip provider prefix variants).
    lookup_key = model.lower().strip()
    prompt_price, completion_price = PRICING.get(lookup_key, (1.00, 3.00))

    cost = (
        (prompt_tokens / 1_000_000) * prompt_price
        + (completion_tokens / 1_000_000) * completion_price
    )
    return round(cost, 8)
