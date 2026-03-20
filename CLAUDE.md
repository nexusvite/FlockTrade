# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

FlockTrade is an AI-powered forex trading platform. Django backend serves a REST API, WebSocket live feed, and a pre-built React SPA. It connects to MetaTrader 5 via an RPyC bridge running in Docker, and uses dual-AI analysis (scout + confirmer) through OpenRouter.

## Development Commands

### Backend (from `bot/` directory)
```bash
# Run dev server (ASGI — handles both HTTP and WebSocket)
cd bot && python manage.py runserver       # Django dev server (HTTP only)
cd bot && daphne -b 0.0.0.0 -p 8080 flocktrade.asgi:application  # Full ASGI

# Database
cd bot && python manage.py migrate
cd bot && python manage.py makemigrations <app_name>

# Celery (requires Redis running)
cd bot && celery -A flocktrade worker --loglevel=info --concurrency=2
cd bot && celery -A flocktrade beat --loglevel=info

# Tests
cd bot && pytest                           # Run all tests
cd bot && pytest trading/tests/            # Run one app's tests
cd bot && pytest -k "test_name"            # Run single test by name

# Django management
cd bot && python manage.py create_admin    # Creates admin user from env vars
cd bot && python manage.py collectstatic --noinput
```

### Frontend (from `frontend/` directory)
```bash
cd frontend && npm install
cd frontend && npm run dev                 # Vite dev server (proxies /api and /ws to backend)
cd frontend && npm run build               # Build to bot/spa/ for Django serving
```

### Docker (full stack)
```bash
docker compose up -d                       # Start all services
docker compose up -d mt5 postgres redis    # Start infrastructure only
docker compose build bot                   # Rebuild backend image
```

## Architecture

### Request Flow
```
Browser → Traefik (prod) / Vite proxy (dev)
  ├── /api/*     → Django REST Framework views
  ├── /ws/live/  → Channels WebSocket consumer (JWT auth via query param)
  ├── /admin/    → Django admin
  └── /*         → SPA catch-all (serves React from bot/spa/)
```

### Trading Loop (runs every 60s via Celery beat)
```
run_scanner task
  → MT5Connector.get_candles() via RPyC
  → SREngine: detect support/resistance levels (multi-timeframe M5/M15/M30/H1)
  → StrategyEngine: 13-filter chain (ported from MQL5 V28)
  → AIEngine.scout(): fast analysis (Claude Haiku)
  → AIEngine.confirm(): deep analysis (Claude Sonnet, only if scout says BUY/SELL)
  → TradeManager.execute(): place trade via MT5

monitor_exits task (every 60s)
  → AIEngine.exit_check() on each open position
  → Close via MT5 if AI says CLOSE

health_check task (every 30s)
  → MT5 connectivity check → updates BotStatus singleton
```

### Key Design Patterns

**Singleton models** — `BotStatus` and `TradingConfig` use `pk=1` with `save()` override to enforce single instance. Always use `BotStatus.objects.first()` or `TradingConfig.objects.first()`.

**Immutable models** — `AuditLog` and `AIDecision` are append-only; `default_permissions = ("add", "view")`.

**Config hierarchy** — Settings resolve in order: SymbolConfig (per-symbol DB) → TradingConfig (global DB) → environment variables → `settings.py` defaults. The `config_service.py` module handles this with Redis caching (60s TTL).

**Real-time broadcasting** — Django signals on Trade/AIDecision post_save trigger `channel_layer.group_send()` to the "live_feed" WebSocket group. Uses `async_to_sync` wrapper.

### App Responsibilities

| App | Purpose |
|-----|---------|
| `trading` | MT5 connector, S/R engine, 13-filter strategy, indicators (RSI/EMA), trade execution, Celery tasks, config service |
| `ai` | OpenRouter integration, scout/confirmer/exit prompts, response parsing, cost tracking |
| `accounts` | JWT auth (SimpleJWT), user profiles with roles (Viewer/Trader/Admin), audit middleware |
| `dashboard` | WebSocket consumer (`/ws/live/`), Django signals for real-time broadcasting |
| `spa` | Static directory — pre-built React assets served by Django's catch-all route |
| `flocktrade` | Project config: settings, URLs, ASGI routing, Celery app |

### MT5 Bridge

The connector (`trading/mt5_connector.py`) uses RPyC to communicate with a MetaTrader 5 instance running inside `gmag11/metatrader5_vnc:2.0` Docker container. RPyC server listens on port 8001. The connector uses data classes (Candle, Tick, AccountInfo, etc.) to avoid passing RPyC netref objects across the boundary.

### AI Engine

Dual-model via OpenRouter (`ai/engine.py`):
- **Scout** (Claude Haiku): runs on every symbol every minute, cheap (~$0.0001/call)
- **Confirmer** (Claude Sonnet): only called when scout signals BUY/SELL (~$0.003/call)
- Uses async httpx, in-memory LRU cache (90s TTL), token-bucket rate limiting
- Response parser (`ai/parsers.py`) handles malformed JSON with layered fallbacks

### Frontend

React 19 + TypeScript + Tailwind CSS + Recharts. Key patterns:
- `useAuth()` hook manages JWT lifecycle (access + refresh token rotation)
- `useWebSocket()` hook connects to `/ws/live/?token=<JWT>` with auto-reconnect
- API client (`lib/api.ts`) uses axios with Bearer token injection and 401 refresh interceptor
- Built assets go to `bot/spa/` — Django serves them via a catch-all `re_path`

## Infrastructure Requirements

- **PostgreSQL 16** — primary database (psycopg3 driver)
- **Redis 7** — Channels layer, Celery broker/result backend, Django cache, config cache
- **MT5 container** — `gmag11/metatrader5_vnc:2.0` for RPyC bridge on port 8001

## Deployment Notes

- Production uses supervisord to run Daphne + Celery worker + Celery beat in a single container
- Deployed via Dokploy on Contabo VPS; frontend is built into `bot/spa/` and served by Django (separate frontend container is unused due to VPS OOM)
- Behind Traefik: uses `SECURE_PROXY_SSL_HEADER` (not `SECURE_SSL_REDIRECT`)
- Entrypoint runs migrations + `create_admin` on every deploy
- `package-lock.json` must be committed for `npm ci` in Docker builds

## Role-Based Access

- **Viewer**: read-only API access
- **Trader**: + bot control (pause/resume/stop/start via `POST /api/control/`)
- **Admin**: + config changes, user registration, audit log access
