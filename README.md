# Stock Analyzer

A personal swing-trading analyzer for NSE equities. It pulls market data from Zerodha Kite Connect, researches news with a low-cost LLM and ranks buy and sell candidates. Everything is stored in SQL Server, so data is fetched once and analyzed many times. Orders run in paper mode first. Later, approve mode places a Kite order only after you click Approve.

| Part | Stack |
|---|---|
| `backend/` | FastAPI, Python 3.12 (uv), SQLAlchemy 2 + pyodbc, Alembic, APScheduler |
| `frontend/` | Next.js 16 (App Router), Tailwind v4, TanStack Query |
| Database | Existing SQL Server, schemas `mkt`, `res`, `trd`, `app` |

## Setup

1. Create `.env` from the example and fill in the SQL Server and Kite values:

   ```bash
   cp .env.example .env
   ```

2. Generate a value for `TOKEN_ENCRYPTION_KEY` and paste it into `.env`:

   ```bash
   cd backend && uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

3. Create the database `stocks` on your SQL Server, then apply the schema:

   ```bash
   cd backend && uv run alembic upgrade head
   ```

4. Start the backend:

   ```bash
   cd backend && python main.py
   ```

   `main.py` switches into `backend/.venv` on its own, so any Python works. `HOST` and `PORT` env vars override `127.0.0.1:8000`, and `--no-reload` turns off auto-reload.

5. Start the frontend. Copy `frontend/.env.example` to `frontend/.env.local` and set the same `BACKEND_API_KEY` first:

   ```bash
   cd frontend && npm install && npm run dev
   ```

## Checks

```bash
cd backend && uv run pytest && uv run ruff check .
cd frontend && npm run lint && npm run build
```

## Daily routine

1. Start Docker Desktop (SQL Server runs in `sql_server_container`), then the backend and frontend.
2. Before 09:15 IST, open Settings and click **Log in with Kite**. The token expires every day at 06:00.
3. The scheduler does the rest on NSE trading days (IST):
   - Hourly 07:05–22:05: collect news and score its sentiment with the LLM.
   - 09:16, 09:25, 09:40: fill pending paper orders at live prices.
   - Every 2 minutes from 09:15 to 15:30: check stops and targets.
   - 15:50: download candles, recompute indicators and signals, write AI research, run paper end-of-day, plan the next day's orders.
   - Sunday 10:00: refresh holidays and the NIFTY 500 list, then run a walk-forward backtest.

The backend must stay running for the scheduler to work. Anything missed while it was down is caught up at the next end-of-day run.

## Live trading (approve mode)

Real orders are off by default. To use them:

1. In Settings → Trading mode, choose **Approve real orders**. Leave **Dry run** on at first.
2. At 15:50 on trading days the app turns the paper plan into approval requests. Quantities are scaled by live capital ÷ paper capital and capped by the max order value. Requests expire at 09:30 the next session.
3. On the Approvals page, check each request and approve it. A dry run logs the exact Kite payload and sends nothing.
4. When the payloads look right, turn dry run off (you have to type `LIVE`). Approving then sends a CNC LIMIT order: an after-market order outside market hours, a regular order during them.
5. Once the order fills, the app places a GTT OCO stop-loss and target. Every 2 minutes it syncs orders and GTTs, trails the stop at the close, and asks your approval for signal and time exits.

Safety rails:
- Orders need approve mode, an unexpired request, the kill switch off and a live Kite login.
- Approval is refused if the price has moved more than 2% above the limit, if the order exceeds the per-order value cap, or if funds are short.
- Each request can only be placed once.
- The kill switch cancels pending requests and open entry orders.

Notes:
- Zerodha may require a registered static IP for order APIs under SEBI's retail algo rules. If so, the Kite rejection is shown in the order log.
- Exits use LIMIT orders, because Kite's API requires market protection for MARKET orders.

## Roadmap

1. Scaffold, DB schema, health checks (done)
2. Kite login, instruments, incremental candles, stock chart (done)
3. News collectors and LLM sentiment (done)
4. Indicators, regime and signal scoring (done)
5. Walk-forward backtester (done)
6. Paper broker, risk manager, scheduler, portfolio (done)
7. Approve mode with Kite orders and GTT stop/target (done)
