"""
AI prompt templates for FlockTrade's dual-AI trading engine.

Each prompt is designed to elicit a strict JSON response so the parser
can extract action / confidence / reason without relying on freeform text.

Design philosophy:
  - Scout: lightweight, fast, cheap — only look at momentum & structure.
  - Confirmer: thorough, expensive — only runs on BUY/SELL signals.
  - Exit: runs every bar while in a trade — minimise tokens.
"""
from string import Template

# ---------------------------------------------------------------------------
# SCOUT PROMPTS
# Scout model: anthropic/claude-haiku-4.5 (or equivalent fast/cheap model)
# Task: Scan last 15 M1 candles + S/R levels + indicators.
#       Return BUY / SELL / SKIP + confidence + one-line reason.
# ---------------------------------------------------------------------------

SCOUT_SYSTEM_PROMPT: str = """\
You are FlockTrade Scout — a professional forex analyst specialising in \
price-action momentum and support/resistance identification on M1 charts.

Your ONLY job is to decide whether there is a high-probability setup in the \
next few candles based on the data provided. You DO NOT manage open trades.

Rules:
1. Reply ONLY with a single JSON object — no markdown, no commentary.
2. The JSON MUST contain exactly these keys:
   - "action": one of "BUY", "SELL", or "SKIP"
   - "confidence": integer 0-100 (how confident are you in this action?)
   - "reason": a SINGLE sentence (max 30 words) explaining your decision
3. Only recommend BUY or SELL when confidence >= 60.
4. If no clear setup exists, reply SKIP with confidence <= 40.
5. Do NOT consider risk management, lot sizes, or account balance.
6. Base your decision purely on candle patterns, momentum, and proximity \
   to the S/R levels provided.

Response format (strict):
{"action": "BUY", "confidence": 72, "reason": "Price bounced off strong H1 support at 150.20 with 3 consecutive bullish M1 candles confirming momentum."}
"""

SCOUT_USER_TEMPLATE: Template = Template("""\
Symbol: $symbol
Current time: $current_time (UTC)
Session: $session
Spread: $spread pips

--- LAST 15 M1 CANDLES (newest last) ---
$candles_table

--- NEAREST S/R LEVELS ---
$sr_levels

--- INDICATORS ---
RSI(14): $rsi
EMA20(M15): $ema20_m15
EMA50(M15): $ema50_m15
M15 Trend: $m15_trend

Current price: $current_price
Nearest support: $nearest_support (strength $support_strength)
Nearest resistance: $nearest_resistance (strength $resistance_strength)

Scout — analyse and respond with JSON only.
""")

# ---------------------------------------------------------------------------
# CONFIRMER PROMPTS
# Confirmer model: anthropic/claude-sonnet-4-6 (or equivalent deep model)
# Task: Deep analysis to confirm or reject the scout's BUY/SELL signal.
#       The hardcoded 13-filter strategy has already passed. The confirmer
#       checks candle structure and M1 micro-momentum ONLY.
# ---------------------------------------------------------------------------

CONFIRMER_SYSTEM_PROMPT: str = """\
You are FlockTrade Confirmer — a senior forex analyst and risk gatekeeper.

A fast Scout AI has identified a potential trade. A rigorous 13-filter \
strategy engine has already validated: session, spread, S/R proximity, \
strength, direction, touch count, RSI extremes, and M15 trend alignment.

Your ONLY job is to perform a final deep-analysis check on:
1. Last 5 M1 candle structure and pattern (doji, engulfing, pin bar, etc.)
2. Whether price is currently showing real momentum TOWARD the trade direction
3. Whether any obvious reversal candles contradict the signal
4. Overall conviction given the scout reasoning + full context below

Rules:
1. Reply ONLY with a single JSON object — no markdown, no commentary.
2. The JSON MUST contain exactly these keys:
   - "action": one of "CONFIRM" or "REJECT"
   - "confidence": integer 0-100
   - "reason": a SINGLE sentence (max 40 words) explaining your decision
3. Default to CONFIRM when the scout has high confidence (>=70) and the \
   M1 candle structure is clean.
4. REJECT only if you see a clear contradiction: e.g. strong opposing candle \
   immediately before the signal, or price already moved 3+ pips away.
5. Do NOT second-guess the 13 strategy filters — trust they passed.
6. Do NOT consider account balance, lot size, or risk parameters.

Response format (strict):
{"action": "CONFIRM", "confidence": 85, "reason": "Clean pin-bar bounce at H1 support, momentum candles confirm, no conflicting pattern detected."}
"""

CONFIRMER_USER_TEMPLATE: Template = Template("""\
=== SCOUT SIGNAL ===
Scout action: $scout_action
Scout confidence: $scout_confidence%
Scout reason: $scout_reason

=== INSTRUMENT ===
Symbol: $symbol
Direction: $trade_direction
Entry zone: $entry_zone
S/R level: $level_price (strength $level_strength, $level_timeframes)
Level touches: $level_touches (in this session)

=== LAST 5 M1 CANDLES (newest last, closest to entry) ===
$candles_last5

=== FULL 15-CANDLE CONTEXT ===
$candles_table

=== INDICATORS ===
RSI(14): $rsi
M15 Trend: $m15_trend (EMA20=$ema20_m15 vs EMA50=$ema50_m15)
Current spread: $spread pips

=== STRATEGY FILTERS (all passed) ===
$filters_passed

Confirmer — review the scout signal and respond with JSON only.
""")

# ---------------------------------------------------------------------------
# EXIT PROMPTS
# Exit model: same as scout (fast/cheap) — runs every minute per open trade.
# Task: Should we HOLD or CLOSE the current open position?
# ---------------------------------------------------------------------------

EXIT_SYSTEM_PROMPT: str = """\
You are FlockTrade Exit Manager — a professional forex trade manager \
specialising in knowing WHEN to exit a winning or losing trade.

You are managing a single open position. Your job is to decide every minute \
whether to HOLD the trade open or CLOSE it immediately.

Rules:
1. Reply ONLY with a single JSON object — no markdown, no commentary.
2. The JSON MUST contain exactly these keys:
   - "action": one of "HOLD" or "CLOSE"
   - "confidence": integer 0-100
   - "reason": a SINGLE sentence (max 30 words) explaining your decision
3. Recommend CLOSE if:
   - Price is reversing strongly against the trade direction
   - The S/R level has clearly broken (price closed through it on M1)
   - Current P&L is positive and momentum has exhausted
   - The trade has been open > 15 bars and made no progress
4. Recommend HOLD if:
   - Price is still moving in the correct direction
   - The S/R level is holding
   - Trade is progressing toward TP
5. Do NOT consider lot size or account balance.
6. Trust the original entry — only exit on clear momentum or structural change.

Response format (strict):
{"action": "HOLD", "confidence": 78, "reason": "Price still above support, bullish momentum intact, TP within 1.2 pips."}
"""

EXIT_USER_TEMPLATE: Template = Template("""\
=== OPEN TRADE ===
Symbol: $symbol
Direction: $trade_direction
Entry price: $entry_price
Current price: $current_price
Stop-loss: $sl
Take-profit: $tp
Current P&L: $current_pnl pips ($pnl_usd USD)
Bars open: $bars_open / 20 max
AI holds so far: $ai_holds

=== ORIGINAL ENTRY CONTEXT ===
Entry S/R level: $level_price (strength $level_strength)
Scout confidence at entry: $scout_confidence%
Confirmer confidence at entry: $confirmer_confidence%

=== LAST 5 M1 CANDLES (newest last) ===
$candles_last5

=== CURRENT MARKET STATE ===
RSI(14): $rsi
M15 Trend: $m15_trend
Spread: $spread pips
Session: $session

Exit Manager — review and respond with JSON only.
""")

# ---------------------------------------------------------------------------
# Helper: build a plain-text candle table for prompt injection.
# Called by AIEngine when constructing messages.
# ---------------------------------------------------------------------------

def format_candle_table(candles: list[dict]) -> str:
    """
    Convert a list of OHLCV dicts into a compact prompt-friendly table.

    Expected dict keys: time, open, high, low, close, volume
    Each candle becomes one line: TIME  O  H  L  C  V  [bull/bear]
    """
    if not candles:
        return "(no candle data)"

    lines: list[str] = ["Time(UTC)          Open      High      Low       Close     Vol   Dir"]
    lines.append("-" * 72)

    for c in candles:
        direction = "bull" if float(c["close"]) >= float(c["open"]) else "bear"
        lines.append(
            f"{c['time']!s:<19} "
            f"{float(c['open']):<10.5f}"
            f"{float(c['high']):<10.5f}"
            f"{float(c['low']):<10.5f}"
            f"{float(c['close']):<10.5f}"
            f"{int(c.get('volume', 0)):<6} "
            f"{direction}"
        )

    return "\n".join(lines)


def format_sr_levels(levels: list[dict]) -> str:
    """
    Convert a list of S/R level dicts into a compact prompt-friendly table.

    Expected dict keys: price, strength, direction, timeframes, touches
    """
    if not levels:
        return "(no S/R levels detected)"

    lines: list[str] = ["Price      Strength  Direction   Timeframes          Touches"]
    lines.append("-" * 62)

    for lv in levels:
        timeframes = ", ".join(lv.get("timeframes", []))
        lines.append(
            f"{float(lv['price']):<11.5f}"
            f"{int(lv['strength']):<10}"
            f"{lv.get('direction', '?'):<12}"
            f"{timeframes:<20}"
            f"{int(lv.get('touches', 0))}"
        )

    return "\n".join(lines)


def build_scout_messages(context: dict) -> list[dict]:
    """
    Build the OpenRouter messages list for a Scout call.

    Args:
        context: Dict produced by the trading engine containing candles,
                 indicators, S/R levels, symbol, etc.

    Returns:
        List of message dicts: [{"role": "system", "content": ...}, ...]
    """
    candles_table = format_candle_table(context.get("candles", []))
    sr_levels = format_sr_levels(context.get("sr_levels", []))
    indicators = context.get("indicators", {})

    user_text = SCOUT_USER_TEMPLATE.substitute(
        symbol=context.get("symbol", "UNKNOWN"),
        current_time=context.get("current_time", ""),
        session=context.get("session", "UNKNOWN"),
        spread=context.get("spread", "?"),
        candles_table=candles_table,
        sr_levels=sr_levels,
        rsi=indicators.get("rsi", "?"),
        ema20_m15=indicators.get("ema20_m15", "?"),
        ema50_m15=indicators.get("ema50_m15", "?"),
        m15_trend=indicators.get("m15_trend", "?"),
        current_price=context.get("current_price", "?"),
        nearest_support=context.get("nearest_support", "?"),
        support_strength=context.get("support_strength", "?"),
        nearest_resistance=context.get("nearest_resistance", "?"),
        resistance_strength=context.get("resistance_strength", "?"),
    )

    return [
        {"role": "system", "content": SCOUT_SYSTEM_PROMPT},
        {"role": "user", "content": user_text},
    ]


def build_confirmer_messages(signal: dict, context: dict) -> list[dict]:
    """
    Build the OpenRouter messages list for a Confirmer call.

    Args:
        signal: Scout result dict (action, confidence, reason).
        context: Full trading context with candles, S/R, indicators.

    Returns:
        List of message dicts.
    """
    candles = context.get("candles", [])
    candles_last5 = format_candle_table(candles[-5:] if len(candles) >= 5 else candles)
    candles_table = format_candle_table(candles)
    sr_levels = context.get("sr_levels", [])
    nearest_level = sr_levels[0] if sr_levels else {}
    indicators = context.get("indicators", {})
    filters_passed = "\n".join(
        f"  - {f}" for f in context.get("filters_passed", [])
    ) or "  (none logged)"

    user_text = CONFIRMER_USER_TEMPLATE.substitute(
        scout_action=signal.get("action", "?"),
        scout_confidence=signal.get("confidence", 0),
        scout_reason=signal.get("reason", ""),
        symbol=context.get("symbol", "UNKNOWN"),
        trade_direction=signal.get("action", "?"),
        entry_zone=context.get("current_price", "?"),
        level_price=nearest_level.get("price", "?"),
        level_strength=nearest_level.get("strength", "?"),
        level_timeframes=", ".join(nearest_level.get("timeframes", [])),
        level_touches=nearest_level.get("touches", "?"),
        candles_last5=candles_last5,
        candles_table=candles_table,
        rsi=indicators.get("rsi", "?"),
        m15_trend=indicators.get("m15_trend", "?"),
        ema20_m15=indicators.get("ema20_m15", "?"),
        ema50_m15=indicators.get("ema50_m15", "?"),
        spread=context.get("spread", "?"),
        filters_passed=filters_passed,
    )

    return [
        {"role": "system", "content": CONFIRMER_SYSTEM_PROMPT},
        {"role": "user", "content": user_text},
    ]


def build_exit_messages(trade: dict, context: dict) -> list[dict]:
    """
    Build the OpenRouter messages list for an Exit Manager call.

    Args:
        trade: ActiveTrade-like dict with open position data.
        context: Current market context with candles and indicators.

    Returns:
        List of message dicts.
    """
    candles = context.get("candles", [])
    candles_last5 = format_candle_table(candles[-5:] if len(candles) >= 5 else candles)
    indicators = context.get("indicators", {})

    user_text = EXIT_USER_TEMPLATE.substitute(
        symbol=trade.get("symbol", "?"),
        trade_direction=trade.get("type", "?"),
        entry_price=trade.get("entry_price", "?"),
        current_price=context.get("current_price", "?"),
        sl=trade.get("sl", "?"),
        tp=trade.get("tp", "?"),
        current_pnl=trade.get("current_pnl_pips", "?"),
        pnl_usd=trade.get("current_pnl_usd", "?"),
        bars_open=trade.get("bars_open", 0),
        ai_holds=trade.get("ai_holds", 0),
        level_price=trade.get("entry_level_price", "?"),
        level_strength=trade.get("entry_level_strength", "?"),
        scout_confidence=trade.get("scout_confidence", "?"),
        confirmer_confidence=trade.get("confirmer_confidence", "?"),
        candles_last5=candles_last5,
        rsi=indicators.get("rsi", "?"),
        m15_trend=indicators.get("m15_trend", "?"),
        spread=context.get("spread", "?"),
        session=context.get("session", "?"),
    )

    return [
        {"role": "system", "content": EXIT_SYSTEM_PROMPT},
        {"role": "user", "content": user_text},
    ]
