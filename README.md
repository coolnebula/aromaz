# Aromaz POS (Implementation Scaffold)

## Stack
- Frontend: React + Vite (`frontend/`)
- Backend: FastAPI + Motor (`backend/`)
- Database: MongoDB Atlas

## Run Locally

### 1) Backend
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# optional for local overrides:
cp .env.local.example .env.local
uvicorn app.main:app --reload
```

### 2) Frontend
```bash
cd frontend
npm install
npm run dev
```

Frontend uses `/api` by default and Vite proxies to `http://localhost:8001` in local dev.
If needed, you can still override:
```bash
VITE_API_BASE_URL=http://localhost:8001/api
```

## Local vs VM config pattern
- `backend/.env` is the base config (VM/deploy can keep production values).
- `backend/.env.local` is optional local-only override, auto-loaded by backend settings.
- Recommended local overrides in `.env.local`:
  - `ENVIRONMENT=development`
  - `CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173`
  - valid local `MONGO_URI` (local Mongo or Atlas creds with your local IP allowed)

## Key API Endpoints
- `GET /health`
- `GET /api/access/session`
- `POST /api/access/totp/setup`
- `POST /api/access/totp/verify`
- `POST /api/access/logout`
- `GET /api/bootstrap`
- `GET /api/menu`
- `POST /api/menu/items`
- `PATCH /api/menu/items/{item_id}`
- `DELETE /api/menu/items/{item_id}`
- `POST /api/orders`
- `POST /api/orders/{order_id}/items`
- `PATCH /api/orders/{order_id}/items/{item_index}`
- `POST /api/orders/{order_id}/items/{item_index}/void`
- `POST /api/orders/{order_id}/status`
- `POST /api/orders/{order_id}/discount`
- `POST /api/ebill/sms/{order_id}`
- `POST /api/ebill/email/{order_id}`
- `GET /ebill/{token}` (public signed e-bill link)
- `POST /api/sync/batch`
- `GET /api/reports/end-of-day?date=YYYY-MM-DD` (single day)
- `GET /api/reports/end-of-day?from_date=YYYY-MM-DD&to_date=YYYY-MM-DD` (range)
- `GET /api/reports/history?date=YYYY-MM-DD` (single day)
- `GET /api/reports/history?from_date=YYYY-MM-DD&to_date=YYYY-MM-DD` (range)

## Access Gate Behavior
- App requires valid 24-hour session cookie for protected APIs.
- Setup endpoint generates authenticator-app provisioning URI (TOTP) and QR image data.
- Verification endpoint accepts current authenticator code and issues session.
- Repeated invalid codes trigger temporary lockout (`OTP_MAX_ATTEMPTS`, `OTP_LOCKOUT_MINUTES`).

## Free-tier Deployment Target
- Frontend: Vercel free
- Backend: Render free web service
- DB: MongoDB Atlas M0

## Deploy Now (Vercel + Render)

### 1) Backend on Render
1. Push this project to GitHub.
2. In Render: **New +** -> **Blueprint** -> select the repo.
3. Render will detect `render.yaml` and create `aromaz-pos-backend`.
4. Set required environment variables in Render service settings:
   - `MONGO_URI` = your MongoDB Atlas URI
   - `SESSION_SECRET` = long random secret
   - `CORS_ORIGINS` = your Vercel app URL (for example `https://your-app.vercel.app`)
   - `MSG91_AUTH_KEY` = MSG91 API auth key
   - `MSG91_SENDER_ID` = approved MSG91 sender id
   - `RESEND_API_KEY` = Resend API key for email delivery
   - `RESEND_FROM_EMAIL` = verified sender email/domain in Resend
   - `EBILL_PUBLIC_BASE_URL` = public app base URL (for example `https://your-app.vercel.app`)
   - Optional: `TOTP_SETUP_KEY`, `TOTP_ISSUER`, `TOTP_ACCOUNT_NAME`
5. Deploy and confirm health at `https://<render-service>.onrender.com/health`.

### 2) Frontend on Vercel
1. In Vercel: **Add New Project** -> import same GitHub repo.
2. Set **Root Directory** to `frontend`.
3. Add environment variable:
   - `VITE_API_BASE_URL` = `https://<render-service>.onrender.com/api`
4. Deploy and open the Vercel URL.

### 3) Post-deploy checks
- Load app and complete TOTP setup/verify.
- Create order -> move lifecycle `Open -> Served -> Billed -> Paid` or cancel.
- Test offline queue (simulate offline, then reconnect).
