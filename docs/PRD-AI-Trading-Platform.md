# PRD: FlockTrade — AI-Powered Forex Trading Platform

**Version:** 1.0  
**Author:** ESiteHoster  
**Date:** March 18, 2026  
**Status:** Draft  

---

## 1. Executive Summary

FlockTrade is a self-hosted AI-powered forex trading platform that replaces the current MQL5 Expert Advisor with a full Python application. It connects to MetaTrader 5 via the mt5linux bridge running in Docker, uses multi-model AI (scout + confirmer) for trade decisions, and provides a web dashboard for monitoring. Deployed on Contabo Linux VPS via Dokploy.

### Why Move from MQL5 to Python?

- **MQL5 limitations:** No proper JSON parsing, no async HTTP, limited debugging, hard to test, WebRequest is synchronous and unreliable
- **Python advantages:** Native JSON, async HTTP, pandas for data analysis, any AI model via REST API, proper logging, backtesting, unit tests, web dashboard
- **Docker advantage:** Runs on Linux VPS 24/7, auto-restarts, no Windows needed

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Contabo Linux VPS                      │
│                    (Dokploy managed)                      │
│                                                           │
│  ┌─────────────┐    ┌──────────────────────────────────┐ │
│  │  MT5 Docker  │    │     FlockTrade App (Python)       │ │
│  │  (Wine+VNC)  │◄──►│                                  │ │
│  │  Port 3000   │    │  ┌────────┐  ┌───────────────┐  │ │
│  │  Port 8001   │    │  │ Scanner │  │   AI Engine    │  │ │
│  │  (RPyC)      │    │  │ (1/min) │  │ Scout + Confirm│  │ │
│  └─────────────┘    │  └────┬───┘  └───────┬───────┘  │ │
│                      │       │              │           │ │
│                      │  ┌────▼──────────────▼────────┐  │ │
│                      │  │     Strategy Engine          │  │ │
│                      │  │  S/R Detection + 13 Filters  │  │ │
│                      │  └────────────┬───────────────┘  │ │
│                      │               │                   │ │
│                      │  ┌────────────▼───────────────┐  │ │
│                      │  │    Trade Executor            │  │ │
│                      │  │  Open/Close/Manage via MT5   │  │ │
│                      │  └────────────┬───────────────┘  │ │
│                      │               │                   │ │
│                      │  ┌────────────▼───────────────┐  │ │
│                      │  │    PostgreSQL + Redis        │  │ │
│                      │  │  Trade logs, S/R cache, state│  │ │
│                      │  └────────────────────────────┘  │ │
│                      │                                   │ │
│                      │  ┌────────────────────────────┐  │ │
│                      │  │    Django + DRF + Channels    │  │ │
│                      │  │    Web UI + API + WebSocket    │  │ │
│                      │  │  Port 8080                   │  │ │
│                      │  └────────────────────────────┘  │ │
│                      └──────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

---

## 3. Tech Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| **Language** | Python 3.12+ | Best MT5 integration, AI libraries, pandas |
| **MT5 Bridge** | mt5linux + RPyC | Connects Python on Linux to MT5 via Docker |
| **MT5 Container** | gmag11/metatrader5_vnc:2.0 | MT5 + Wine + VNC + RPyC on Linux |
| **Web Framework** | Django 6.0.3 | Built-in auth, ORM, admin, tasks framework, CSP |
| **API Layer** | Django REST Framework 3.16+ | REST API + token auth for React frontend |
| **Auth** | Django Allauth + JWT (SimpleJWT) | Social login, 2FA, JWT tokens for SPA |
| **Frontend** | React 19 + Tailwind + shadcn/ui | Dashboard for monitoring trades |
| **Database** | PostgreSQL 18 | Trade logs, S/R history, performance analytics |
| **Cache** | Redis 7 | Session touches, level states, rate limiting |
| **AI Provider** | OpenRouter API | Multi-model access (Haiku, Sonnet, DeepSeek, Gemini) |
| **Task Queue** | Django Tasks (built-in) + Celery | 1-min scanner via Django 6.0 Tasks framework |
| **Channels** | Django Channels + Redis | WebSocket for real-time dashboard updates |
| **Deployment** | Docker Compose + Dokploy | Auto-restart, health checks, log aggregation |
| **Monitoring** | Prometheus + Grafana (optional) | P&L tracking, API cost tracking |

---

## 4. Core Modules

### 4.1 MT5 Connector (`mt5_connector.py`)

Handles all communication with MetaTrader 5.

**Functions:**
- `connect(host, port)` — Connect to MT5 via RPyC
- `get_candles(symbol, timeframe, count)` — Fetch OHLCV data
- `get_tick(symbol)` — Current bid/ask/spread
- `open_trade(symbol, type, lot, sl, tp, comment)` — Place order
- `close_trade(ticket)` — Close position
- `get_positions()` — List open trades
- `get_history(from_date, to_date)` — Trade history
- `get_account_info()` — Balance, equity, margin

**Key Design:**
- Auto-reconnect on connection loss
- Retry logic with exponential backoff
- Connection health check every 30 seconds

### 4.2 S/R Detection Engine (`sr_engine.py`)

Multi-timeframe Support/Resistance detection — ported from MQL5 V28.

**Levels detected:**
- M5 swing highs/lows (str: 1)
- M15 swing highs/lows (str: 2)
- M30 swing highs/lows (str: 3)
- H1 swing highs/lows (str: 4)
- Previous Day High/Low/Close (str: 5)
- Round numbers R20/R50/R100 (str: 1-4)

**Confluence scoring:**
- Multiple timeframes at same level = combined strength
- PD-H + M15 at same price = str: 7 (5+2)

**Output:**
```python
@dataclass
class SRLevel:
    price: float
    strength: int          # 1-10
    timeframes: list[str]  # ["H1", "M15"]
    touches: int           # session touch count
    last_touch: datetime
    direction: str         # "support" or "resistance"
```

### 4.3 Strategy Engine (`strategy.py`)

The brain — implements all 13 filters from V28.

**Filter chain (in order):**
1. Session filter (Asia/London/NY hours)
2. Spread filter (max spread check)
3. Startup guard (3-bar warmup)
4. S/R proximity (find nearest levels)
5. Strength filter (str >= 2 required)
6. Bounce distance (str-scaled max distance)
7. Direction enforcer (closer to R → SELL only)
8. Equal distance trap detector
9. Touch count rules (1st=TRADE, 2nd=SKIP, 3rd+=BREAKOUT)
10. Traded level tracker (no re-entry)
11. RSI extreme block (>80 blocks BUY, <20 blocks SELL)
12. M15 trend confirmation (EMA20 vs EMA50)
13. Smart SR_Block (weak levels can't block strong trades)

**Output:**
```python
@dataclass  
class TradeSignal:
    action: str          # "BUY", "SELL", "SKIP"
    symbol: str
    level: SRLevel
    confidence: int
    reasons: list[str]
    filters_passed: list[str]
    filters_failed: list[str]
```

### 4.4 AI Engine (`ai_engine.py`)

Dual AI system — Scout scans, Confirmer gates.

**Scout (runs every minute per symbol):**
- Model: `anthropic/claude-haiku-4.5` (default, configurable)
- Input: Last 15 M1 candles + S/R map + indicators
- Output: BUY/SELL/SKIP with confidence and reason
- Cost: ~$0.0001/call

**Confirmer (runs only on BUY/SELL signals):**
- Model: `anthropic/claude-sonnet-4-6` (default, configurable)
- Input: Full context + Scout's reasoning + candle data
- Output: CONFIRM/REJECT with confidence and reason
- Role: Only check candle patterns and M1 momentum (trusts hardcoded filters)
- Cost: ~$0.003/call, 3-5 calls/day

**Key Design:**
- Model names configurable via environment variables
- Proper JSON parsing with fallback handling
- Response caching to avoid duplicate calls
- Cost tracking per model per day
- Rate limiting (respect provider limits)

```python
class AIEngine:
    def __init__(self, scout_model, confirm_model, api_key):
        self.scout = scout_model
        self.confirmer = confirm_model
    
    async def scout_scan(self, context: TradeContext) -> ScoutResult:
        """Fast scan every minute"""
        
    async def confirm_trade(self, signal: TradeSignal, context: TradeContext) -> ConfirmResult:
        """Deep analysis before opening trade - only on BUY/SELL"""
```

### 4.5 Trade Manager (`trade_manager.py`)

Handles open position management.

**Exit logic:**
- AI-based exit (HOLD/CLOSE) every minute while in trade
- Profit protection at +1.2 pips
- Max hold: 20 bars
- Touch exit: Only for weak levels (str < 4)
- Strong levels (str >= 4): Trust the level, trust the SL
- Daily loss limit: 3 losses or -$100

**Position tracking:**
```python
@dataclass
class ActiveTrade:
    ticket: int
    symbol: str
    type: str              # "BUY" or "SELL"
    entry_price: float
    sl: float
    tp: float
    entry_level: SRLevel
    entry_time: datetime
    bars_open: int
    current_pnl: float
    ai_holds: int
```

### 4.6 Dashboard API (`api/`)

Django REST Framework-based API with JWT authentication and WebSocket via Django Channels.

**Authentication System:**
- JWT tokens via `djangorestframework-simplejwt`
- Login returns `access` (15 min) + `refresh` (7 days) tokens
- React frontend stores tokens in httpOnly cookies
- CSRF protection enabled for cookie-based auth
- Rate limiting on login endpoint (5 attempts/min)
- Optional 2FA via `django-allauth` TOTP

**REST Endpoints (all require JWT auth):**
- `POST /api/auth/login/` — Get JWT tokens (username + password)
- `POST /api/auth/refresh/` — Refresh access token
- `POST /api/auth/logout/` — Blacklist refresh token
- `POST /api/auth/register/` — Create account (disabled in production, admin-only)
- `GET  /api/auth/me/` — Current user profile
- `POST /api/auth/change-password/` — Change password
- `GET  /api/status/` — Bot status, account info
- `GET  /api/trades/` — Active and historical trades (paginated)
- `GET  /api/trades/{id}/` — Trade detail with AI reasoning
- `GET  /api/levels/` — Current S/R levels map
- `GET  /api/performance/` — Win rate, P&L, per-pair stats
- `GET  /api/ai/costs/` — API cost breakdown per model
- `GET  /api/ai/decisions/` — AI decision log (paginated)
- `POST /api/config/` — Update bot settings (pairs, models, sessions)
- `POST /api/control/pause/` — Pause trading
- `POST /api/control/resume/` — Resume trading

**WebSocket (Django Channels + Redis):**
- `WS /ws/live/` — Real-time trade signals, price updates, AI decisions
- Authenticated via JWT token in query string

**Django Admin:**
- Full admin interface at `/admin/` for managing trades, users, settings
- Built-in Django admin with custom dashboards

### 4.7 Authentication & Security (`accounts/`)

Secure multi-layer auth system using Django's built-in auth + extensions.

**Backend Stack:**
```
Django Auth (User model)
  └── djangorestframework-simplejwt (JWT tokens for SPA)
      └── django-allauth (optional: social login, 2FA)
          └── django-axes (brute-force protection)
```

**Security Features:**
- **Password hashing:** Argon2 (Django 6.0 default) with fallback to PBKDF2
- **JWT tokens:** Short-lived access (15 min), long-lived refresh (7 days)
- **CORS:** Restricted to dashboard origin only
- **CSRF:** Enabled for cookie-based auth
- **Rate limiting:** `django-axes` blocks after 5 failed logins
- **CSP headers:** Django 6.0 native Content Security Policy
- **HTTPS only:** Secure cookies, HSTS headers
- **Session security:** httpOnly + Secure + SameSite=Lax cookies
- **IP whitelist:** Optional — restrict dashboard to specific IPs

**User Roles:**
```python
class UserRole(models.TextChoices):
    ADMIN = "admin"      # Full access: config, trades, users
    TRADER = "trader"    # View trades, P&L, AI logs
    VIEWER = "viewer"    # Read-only dashboard access
```

**Django Settings (security):**
```python
# settings.py
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# JWT
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
}

# Security headers (Django 6.0)
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
CONTENT_SECURITY_POLICY = {
    "default-src": ["'self'"],
    "script-src": ["'self'"],
    "style-src": ["'self'", "'unsafe-inline'"],
    "connect-src": ["'self'", "wss:", "https://openrouter.ai"],
}

# Brute-force protection
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = timedelta(minutes=15)
AXES_LOCK_OUT_BY_IP_AND_USER_AGENT = True
```

### 4.8 Dashboard Frontend (`frontend/`)

React dashboard for monitoring the bot.

**Pages:**
- **Login** — Email/password login with JWT, remember me, forgot password
- **Dashboard** — Live P&L, active trades, recent signals (protected)
- **Trades** — Trade history with filters, AI reasoning for each
- **Levels** — Visual S/R map with touch counts
- **AI Log** — Scout/Confirmer decisions with reasoning
- **Settings** — Pairs, models, session hours, risk parameters (admin only)
- **Analytics** — Win rate by pair, session, level strength, AI accuracy
- **Profile** — Change password, 2FA setup, API key management

---

## 5. Data Models (PostgreSQL 18)

```sql
-- Extended user profile (extends Django's built-in User model)
CREATE TABLE user_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INT UNIQUE REFERENCES auth_user(id) ON DELETE CASCADE,
    role VARCHAR(10) DEFAULT 'viewer',     -- admin/trader/viewer
    telegram_chat_id VARCHAR(50),
    notification_enabled BOOLEAN DEFAULT TRUE,
    two_factor_enabled BOOLEAN DEFAULT FALSE,
    last_active TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- API keys for programmatic access
CREATE TABLE api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INT REFERENCES auth_user(id) ON DELETE CASCADE,
    key_hash VARCHAR(255) NOT NULL,        -- SHA256 hash of the key
    name VARCHAR(100),
    permissions VARCHAR(20) DEFAULT 'read', -- read/write/admin
    last_used TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Audit log for security events
CREATE TABLE audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INT REFERENCES auth_user(id),
    action VARCHAR(50) NOT NULL,           -- login/logout/config_change/trade_pause
    ip_address INET,
    user_agent TEXT,
    details JSONB,
    timestamp TIMESTAMPTZ DEFAULT NOW()
);

-- Trade history
CREATE TABLE trades (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol VARCHAR(20) NOT NULL,
    type VARCHAR(4) NOT NULL,              -- BUY/SELL
    entry_price DECIMAL(12,5),
    exit_price DECIMAL(12,5),
    sl DECIMAL(12,5),
    tp DECIMAL(12,5),
    lot_size DECIMAL(8,2),
    pnl DECIMAL(10,2),
    entry_time TIMESTAMPTZ,
    exit_time TIMESTAMPTZ,
    bars_held INT,
    level_price DECIMAL(12,5),
    level_strength INT,
    level_timeframes TEXT,
    scout_action VARCHAR(10),
    scout_confidence INT,
    scout_reason TEXT,
    confirmer_action VARCHAR(10),
    confirmer_confidence INT,
    confirmer_reason TEXT,
    exit_reason TEXT,
    filters_log JSONB
);

-- AI decision log  
CREATE TABLE ai_decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    symbol VARCHAR(20),
    role VARCHAR(10),                      -- scout/confirmer
    model VARCHAR(100),
    action VARCHAR(10),
    confidence INT,
    reason TEXT,
    input_context TEXT,
    raw_response TEXT,
    latency_ms INT,
    cost_usd DECIMAL(10,6)
);

-- S/R levels cache
CREATE TABLE sr_levels (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol VARCHAR(20),
    price DECIMAL(12,5),
    strength INT,
    timeframes TEXT[],
    session_touches INT DEFAULT 0,
    first_detected TIMESTAMPTZ,
    last_touched TIMESTAMPTZ,
    traded BOOLEAN DEFAULT FALSE
);

-- Daily performance
CREATE TABLE daily_stats (
    date DATE PRIMARY KEY,
    trades INT DEFAULT 0,
    wins INT DEFAULT 0,
    losses INT DEFAULT 0,
    scratches INT DEFAULT 0,
    pnl DECIMAL(10,2) DEFAULT 0,
    ai_cost DECIMAL(10,4) DEFAULT 0,
    best_trade DECIMAL(10,2),
    worst_trade DECIMAL(10,2)
);
```

---

## 6. Configuration

Environment variables (`.env` file):

```env
# MT5 Connection
MT5_HOST=mt5-trading          # Docker container name
MT5_PORT=8001                 # RPyC port
MT5_ACCOUNT=262463380
MT5_PASSWORD=your_password
MT5_SERVER=Exness-Mt5Trial7

# Trading
SYMBOLS=USDJPYm,EURUSDm
LOT_SIZE_FOREX=1.0
LOT_SIZE_GOLD=0.1
TP_PIPS_FOREX=2
SL_PIPS_FOREX=5
TP_PIPS_GOLD=20
SL_PIPS_GOLD=50
MAX_DAILY_LOSSES=3
MAX_DAILY_LOSS_USD=100

# Sessions (server time)
ASIA_START=1
ASIA_END=6
LONDON_START=8
LONDON_END=12
NY_START=13
NY_END=20

# AI Models
OPENROUTER_API_KEY=sk-or-v1-xxx
SCOUT_MODEL=anthropic/claude-haiku-4.5
CONFIRMER_MODEL=anthropic/claude-sonnet-4-6
AI_TIMEOUT=15

# Django
DJANGO_SECRET_KEY=your-very-long-random-secret-key-here
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=flocktrade.yourdomain.com,localhost
DJANGO_CORS_ORIGINS=https://flocktrade.yourdomain.com

# Auth
JWT_ACCESS_LIFETIME_MINUTES=15
JWT_REFRESH_LIFETIME_DAYS=7
ADMIN_USERNAME=admin
ADMIN_EMAIL=admin@yourdomain.com
ADMIN_PASSWORD=initial-secure-password

# Database
DATABASE_URL=postgresql://trader:pass@postgres:5432/flocktrade
REDIS_URL=redis://redis:6379

# Dashboard
DASHBOARD_PORT=8080
```

---

## 7. Docker Compose

```yaml
version: '3.8'
services:
  mt5:
    image: gmag11/metatrader5_vnc:2.0
    container_name: mt5-trading
    volumes:
      - mt5_config:/config
    ports:
      - "3000:3000"    # VNC web access
      - "8001:8001"    # RPyC Python bridge
    environment:
      - CUSTOM_USER=trader
      - PASSWORD=${MT5_VNC_PASSWORD}
    restart: unless-stopped

  bot:
    build: ./bot
    container_name: flocktrade-bot
    command: daphne -b 0.0.0.0 -p 8080 flocktrade.asgi:application
    depends_on:
      - mt5
      - postgres
      - redis
    env_file: .env
    ports:
      - "8080:8080"
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "manage.py", "check"]
      interval: 60s
      timeout: 10s
      retries: 3

  celery:
    build: ./bot
    container_name: flocktrade-worker
    command: celery -A flocktrade worker -l info -B
    depends_on:
      - bot
      - redis
    env_file: .env
    restart: unless-stopped

  dashboard:
    build: ./frontend
    container_name: flocktrade-dashboard
    ports:
      - "8080:80"
    depends_on:
      - bot
    restart: unless-stopped

  postgres:
    image: postgres:18-alpine
    container_name: flocktrade-db
    volumes:
      - pg_data:/var/lib/postgresql/data
    environment:
      POSTGRES_DB: flocktrade
      POSTGRES_USER: trader
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    container_name: flocktrade-redis
    restart: unless-stopped

volumes:
  mt5_config:
  pg_data:
```

---

## 8. Project Structure

```
flocktrade/
├── bot/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── manage.py
│   ├── flocktrade/                  # Django project settings
│   │   ├── __init__.py
│   │   ├── settings.py              # Django 6.0.3 config
│   │   ├── urls.py                  # Root URL routing
│   │   ├── asgi.py                  # ASGI for Channels WebSocket
│   │   ├── wsgi.py                  # WSGI for production
│   │   └── celery.py               # Celery config (if needed beyond Django Tasks)
│   ├── accounts/                    # Auth & user management
│   │   ├── __init__.py
│   │   ├── models.py               # UserProfile, APIKey, AuditLog
│   │   ├── serializers.py          # Login, Register, Profile serializers
│   │   ├── views.py                # JWT login/refresh/logout views
│   │   ├── permissions.py          # IsAdmin, IsTrader, IsViewer
│   │   ├── middleware.py           # JWT cookie middleware, audit logging
│   │   ├── urls.py
│   │   └── admin.py
│   ├── trading/                     # Core trading engine
│   │   ├── __init__.py
│   │   ├── models.py               # Trade, SRLevel, DailyStats
│   │   ├── mt5_connector.py        # MT5 RPyC bridge
│   │   ├── sr_engine.py            # S/R detection (multi-TF)
│   │   ├── strategy.py             # 13-filter chain
│   │   ├── trade_manager.py        # Position management
│   │   ├── instrument.py           # Auto-detect forex/gold/oil/crypto
│   │   ├── indicators.py           # RSI, EMA calculations
│   │   ├── tasks.py                # Django 6.0 Tasks: scanner, exit monitor
│   │   ├── serializers.py
│   │   ├── views.py                # Trade API endpoints
│   │   ├── urls.py
│   │   └── admin.py
│   ├── ai/                          # AI engine module
│   │   ├── __init__.py
│   │   ├── models.py               # AIDecision log model
│   │   ├── engine.py               # Scout + Confirmer logic
│   │   ├── prompts.py              # System/user prompts for each AI role
│   │   ├── parsers.py              # JSON response parsing with fallbacks
│   │   ├── serializers.py
│   │   ├── views.py                # AI decisions API
│   │   ├── urls.py
│   │   └── admin.py
│   ├── dashboard/                   # WebSocket + real-time
│   │   ├── __init__.py
│   │   ├── consumers.py            # Django Channels WebSocket consumers
│   │   ├── routing.py              # WebSocket URL routing
│   │   └── signals.py              # Django signals for live updates
│   └── tests/
│       ├── test_sr_engine.py
│       ├── test_strategy.py
│       ├── test_ai_engine.py
│       ├── test_trade_manager.py
│       └── test_auth.py
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   ├── src/
│   │   ├── App.tsx
│   │   ├── lib/
│   │   │   ├── api.ts               # Axios instance with JWT interceptor
│   │   │   ├── auth.ts              # Auth context, token management
│   │   │   └── websocket.ts         # WebSocket connection manager
│   │   ├── pages/
│   │   │   ├── Login.tsx            # Login form with validation
│   │   │   ├── Dashboard.tsx        # Protected: live P&L, trades
│   │   │   ├── Trades.tsx           # Protected: trade history
│   │   │   ├── Levels.tsx           # Protected: S/R map
│   │   │   ├── AILog.tsx            # Protected: AI decisions
│   │   │   ├── Settings.tsx         # Admin only: bot config
│   │   │   ├── Analytics.tsx        # Protected: performance charts
│   │   │   └── Profile.tsx          # Protected: password, 2FA
│   │   ├── components/
│   │   │   ├── ProtectedRoute.tsx   # Auth guard for routes
│   │   │   ├── AuthProvider.tsx     # JWT token context provider
│   │   │   ├── TradeCard.tsx
│   │   │   ├── SRMap.tsx
│   │   │   ├── PnLChart.tsx
│   │   │   └── LiveFeed.tsx
│   │   └── hooks/
│   │       ├── useAuth.ts           # Login, logout, refresh hooks
│   │       └── useWebSocket.ts      # Real-time data hook
│   └── tailwind.config.js
├── docker-compose.yml
├── .env.example
├── README.md
└── PRD.md
```

---

## 9. Migration Plan (MQL5 → Python)

### Phase 1: Django Setup + MT5 Connector (Week 1)
- Django 6.0.3 project scaffold with PostgreSQL 18
- MT5 connector via RPyC
- S/R detection engine (port from MQL5)
- Basic scanner loop using Django Tasks
- Console logging (match MQL5 log format)

### Phase 2: Auth + Strategy + AI (Week 2)
- User model with roles (admin/trader/viewer)
- JWT auth with SimpleJWT + login/logout/refresh
- Brute-force protection with django-axes
- Port all 13 filters from V28
- AI engine with Scout + Confirmer
- Trade executor (open/close via MT5 API)
- Position manager with exit logic

### Phase 3: API + Database (Week 3)
- Django REST Framework API endpoints
- Trade logging to PostgreSQL
- Redis for session state (touches, traded levels)
- AI decision logging with full context
- Audit log for security events
- Django Admin customization

### Phase 4: Dashboard Frontend (Week 4)
- React login page with JWT flow
- Protected routes with auth guards
- Live P&L display via Django Channels WebSocket
- Trade history with AI reasoning
- Settings management (admin only)
- Profile page (password change, 2FA)

### Phase 5: Deploy + Harden (Week 5)
- Docker Compose on Contabo via Dokploy
- HTTPS with Let's Encrypt (via Dokploy)
- CSP headers, CORS, HSTS configuration
- Health checks and auto-restart
- Backtesting with historical data
- Performance optimization

---

## 10. Advantages Over MQL5 EA

| Feature | MQL5 EA (Current) | Python Platform (FlockTrade) |
|---------|-------------------|------------------------------|
| JSON Parsing | Broken, manual string search | Native `json.loads()` |
| AI Models | WebRequest (sync, unreliable) | `httpx` async, retry, fallback |
| Auth | None | Django built-in auth + JWT + 2FA + RBAC |
| Logging | Print() to Experts tab | Structured logging + DB + audit trail |
| Debugging | No debugger | Python debugger, breakpoints |
| Admin Panel | None | Django Admin (free, built-in, powerful) |
| Background Tasks | None | Django 6.0 Tasks framework (built-in) |
| CSP Security | None | Django 6.0 native Content Security Policy |
| Backtesting | MT5 tester (limited) | pandas + custom backtester |
| Monitoring | Must open MT5 terminal | Web dashboard from phone |
| Deployment | Copy .mq5, compile, drag | `git push` → auto-deploy |
| Testing | None | pytest unit tests |
| Data Analysis | None | pandas, numpy, matplotlib |
| Multi-broker | One broker at a time | Multiple MT5 instances |
| Configuration | EA inputs (restart required) | Web UI (live reload) |
| Cost Tracking | None | Per-model API cost dashboard |
| Alerts | None | Telegram/WhatsApp notifications |

---

## 11. Future Enhancements (V2)

- **Telegram Bot** — Trade alerts and remote control
- **Backtesting Engine** — Test strategies on historical data
- **Multi-Account** — Run same strategy on multiple broker accounts
- **Strategy Marketplace** — Share/sell strategies (FlockHive integration)
- **RAG Knowledge Base** — Feed trading books/courses to AI for better decisions
- **Voice Alerts** — TTS notifications for trade events
- **Mobile App** — React Native companion app
- **ML Ensemble** — Combine multiple AI model votes for higher accuracy

---

## 12. Risk Management

- **Demo first** — All testing on Exness demo account
- **Daily limits** — Hard stop at 3 losses or -$100
- **Position sizing** — Fixed lot, no martingale
- **Circuit breaker** — Bot pauses after consecutive losses
- **Health monitoring** — Auto-restart on crash, alert on prolonged disconnect
- **Audit trail** — Every AI decision logged with full context

---

## 13. Cost Estimate

| Item | Monthly Cost |
|------|-------------|
| Contabo VPS (existing) | ~$5 |
| OpenRouter API (Haiku scout) | ~$7 |
| OpenRouter API (Sonnet confirmer) | ~$0.50 |
| PostgreSQL (self-hosted) | $0 |
| Redis (self-hosted) | $0 |
| Domain (optional) | ~$1 |
| **Total** | **~$13.50/month** |

With cheaper models (Gemini Flash-Lite scout): **~$6/month**

---

*This document serves as the technical blueprint for building FlockTrade. Each module can be developed and tested independently before integration.*
