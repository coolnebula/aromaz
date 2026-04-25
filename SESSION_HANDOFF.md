# Session Handoff - Aromaz POS

## Current state snapshot

### Product decisions locked
- Domain: single-store restaurant POS with tablet + desktop web UI.
- Offline-first behavior with mutation queue and later replay.
- Access model: single-operator TOTP gate (no full user login system).
- Lifecycle finalized by stakeholder:
  - `Open -> Served -> Billed -> Paid`
  - Alternate terminal state: `Cancelled` (mandatory reason).

### Major implementation completed
- Backend stack: FastAPI + Motor + MongoDB Atlas.
- Frontend stack: React + Vite.
- TOTP setup/verify/session/logout implemented.
- Menu moved to DB-backed model and CRUD routes added.
- Order APIs now include:
  - create order
  - add item
  - update item
  - void item (reason required)
  - status update (cancel reason enforced)
  - discount apply
- Reports APIs:
  - end-of-day summary
  - day-wise order history
- Offline replay supports:
  - `CREATE_ORDER`
  - `ADD_ITEM`
  - `UPDATE_ITEM`
  - `STATUS_UPDATE`
  - `VOID_ITEM`
  - `APPLY_DISCOUNT`
- UI polished to a premium/minimal responsive layout and includes:
  - table status visibility
  - item edit/void actions
  - discount flow
  - cancel order action
  - report/history sections
  - sync pending indicator

### Reliability hardening completed
- Lifecycle updated across backend and frontend to remove `SentToKitchen`.
- Backward compatibility added for legacy `SentToKitchen` records.
- Online failures no longer silently fall back to offline mutation queue.
- Offline totals clamp discount to avoid negative totals.
- Build/compile/lint checks repeatedly passed in-session.
- API smoke validations run for critical flows and lifecycle transitions.

## Deployment readiness
- Target deployment remains:
  - Frontend: Vercel (free)
  - Backend: Render (free web service)
  - DB: MongoDB Atlas M0
- Added deployment assets:
  - `render.yaml` (backend service definition)
  - `frontend/vercel.json` (SPA routing support)
- Updated docs and env templates:
  - `README.md` deployment runbook expanded
  - `backend/.env.example` cleaned and TOTP issuer quoting fixed

## Critical gaps still open vs implementation plan
- Step-up manager verification is still placeholder (string pattern check).
- Complimentary flow is not implemented as a distinct workflow.
- Optimistic rollback for rejected replay is not fully implemented.
- Critical snapshot persistence is still in `localStorage`, not IndexedDB.
- Plan doc checklist still references old lifecycle (`SentToKitchen`) and should be updated.
- History endpoint currently does not include explicit cancel reason field.

## Suggested immediate next sequence
1. Implement real manager step-up verification for discount/destructive actions.
2. Add cancel reason to history payload and UI presentation.
3. Implement replay rejection rollback + move full snapshot cache to IndexedDB.
4. Update `IMPLEMENTATION_PLAN.md` validation checklist to final lifecycle.
5. Initialize git repo and deploy via GitHub -> Render/Vercel.

## Latest VM sync and verification (Apr 9, 2026)
- Synced latest local changes to VM (`129.159.16.45`) for:
  - `backend/app/routers/access.py`
  - `backend/app/routers/bootstrap.py`
  - `backend/app/routers/reports.py`
  - `frontend/src/App.jsx`
  - `frontend/src/api.js`
  - `frontend/src/styles.css`
- Rebuilt and restarted VM stack with Docker Compose; both services healthy:
  - `myspace-backend-1` up
  - `myspace-nginx-1` up on port `80`
- Executed VM smoke checks against live stack:
  - frontend root served successfully
  - session endpoint responded
  - authenticated lifecycle flow validated (`Open -> Served -> Billed -> Paid`)
  - table re-open behavior after `Paid` validated via bootstrap active-order checks
  - report range endpoints validated (`/api/reports/end-of-day` and `/api/reports/history`)

## Latest data hygiene actions on VM (Apr 9, 2026)
- Removed smoke-test artifacts created during deployment verification.
- Purged remaining historical order records on request:
  - cleared `orders`
  - removed order-related `audit_logs` entries (`payload.order_id` based)
  - cleared `sync_mutations`
  - reset all `tables.active_order_id` to `None`
  - removed temporary smoke sessions (`user_id = vm-smoke`)
- Preserved non-order baseline data intentionally:
  - `menu_items` kept
  - `access_totp` kept

## Current operational baseline
- VM is on latest code and running healthy.
- DB is clean for fresh order testing.
- All tables are open and ready for new orders.

## SSH + VM quick-connect memory (Apr 16, 2026)
- VM public IP: `129.159.16.45`
- SSH username: `ubuntu` (using `opc` is rejected by host policy)
- Private key path: `key/ssh-key-2026-04-09.key`
- Public key path: `key/ssh-key-2026-04-09.key.pub`
- Key permissions expected: `600` on private key

### Known-good commands
- SSH login:
  - `ssh -i "/Users/angan.sen/Documents/myspace/key/ssh-key-2026-04-09.key" ubuntu@129.159.16.45`
- Restart backend container:
  - `ssh -i "/Users/angan.sen/Documents/myspace/key/ssh-key-2026-04-09.key" ubuntu@129.159.16.45 "docker restart myspace-backend-1"`
- Check backend/session API from VM:
  - `ssh -i "/Users/angan.sen/Documents/myspace/key/ssh-key-2026-04-09.key" ubuntu@129.159.16.45 "curl -sS -D - http://127.0.0.1/api/access/session -o /tmp/session.out && head -c 300 /tmp/session.out"`

### Recent incident memory (Apr 16, 2026)
- Frontend "Backend unavailable" root cause was backend DB connectivity failure, not frontend/nginx crash.
- Backend logs showed MongoDB Atlas TLS handshake errors and `ServerSelectionTimeoutError`.
- Fix applied: Atlas IP Access List updated to include VM egress IP `129.159.16.45/32`.
- Post-fix verification: `/api/access/session` returned `200` with JSON payload.
- Separate local-only issue: current corporate network may redirect `https://pos.aromaz.co.in/` via Cloudflare Gateway (303), while VM-side checks still show app healthy.

## Git push fallback memory (Apr 18, 2026)
- Context: `git push origin ...` may fail on this laptop with:
  - `fatal: could not read Password for 'https://coolnebula@github.com': Device not configured`
- Known-good non-destructive fallback push command:
  - `git -c http.https://github.com/.extraheader="AUTHORIZATION: basic $(printf 'coolnebula:%s' "$(gh auth token)" | base64)" push https://github.com/coolnebula/aromaz.git HEAD:myspace-current-code`
- Notes:
  - Requires `gh auth status` to show `coolnebula` as active account.
  - Uses current GitHub CLI token and avoids storing new git credentials.
