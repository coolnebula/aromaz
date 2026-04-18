# Aromaz POS - Detailed Implementation Plan

## Objective
Build a production-ready web + tablet restaurant POS with offline-first behavior, strict order pipeline controls, menu management, end-of-day reporting, and a single-operator access gate on a low-cost stack:
- Frontend: React (Vite)
- Backend: FastAPI
- Database: MongoDB Atlas (M0 free tier for pilot)

## Phase 1 - Foundation (Completed in this iteration)
1. Create project structure for frontend and backend.
2. Scaffold FastAPI app with:
   - health endpoint
   - bootstrap endpoint
   - order creation and item addition endpoints
   - status transition endpoint
   - discount endpoint
   - sync batch endpoint
   - end-of-day report endpoint
3. Add MongoDB connection/config.
4. Scaffold React app with:
   - adaptive table/menu/order layout
   - API integration layer
   - IndexedDB queue utility for offline mutations
5. Add basic operational docs and environment templates.

## Phase 2 - Core Product Flows
1. Replace demo menu fallback with backend menu collection.
2. Add full item editing:
   - qty update
   - modifiers
   - notes
   - void reason
3. Add manager-authorized discount and complimentary workflow.
4. Add strict status transition UX controls and disable invalid actions.
5. Add day-wise order history screen fed by backend.

## Phase 3 - Offline-first Hardening
1. Implement deterministic offline mutation actions with replay mapping:
   - `CREATE_ORDER`
   - `ADD_ITEM`
   - `UPDATE_STATUS`
   - `VOID_ITEM`
   - `APPLY_DISCOUNT`
2. Add idempotency handling with mutation conflict reporting.
3. Add optimistic UI rollback strategy for rejected replay.
4. Persist critical UI cache in IndexedDB (orders/menu/tables snapshot).

## Phase 4 - Access Security (Single-Operator, No Login)
1. Implement authenticator-app (TOTP) access gate:
   - `POST /api/access/totp/setup` to generate TOTP secret and provisioning URI.
   - `POST /api/access/totp/verify` to validate current TOTP code and issue session.
   - `GET /api/access/session` for frontend session/auth gate checks.
2. TOTP policy:
   - 6-digit time-based code (30 second rotation).
   - valid window ±1 step for clock drift.
   - limit failed attempts and apply temporary lockout.
3. Session policy:
   - On successful OTP verification, issue 24-hour session token/cookie.
   - Use `HttpOnly`, `Secure`, `SameSite` cookie attributes.
   - Require valid session for all protected APIs.
4. Abuse protection and governance:
   - setup endpoint optionally protected by `TOTP_SETUP_KEY` in env.
   - temporary lockout after repeated invalid TOTP attempts.
   - extend audit logs with access events (`TOTP_SETUP_GENERATED`, `TOTP_VERIFIED`, `SESSION_ISSUED`, `TOTP_FAILED`, `TOTP_LOCKED`).

## Phase 5 - Authorization and Sensitive Action Controls
1. Keep manager-check requirement for discount/complimentary and destructive actions.
2. Implement step-up verification for sensitive actions (manager code/session check).
3. Extend audit logs with actor role and source device.
4. Add request validation hardening on all business endpoints.

## Phase 6 - Deploy (Free-tier Pilot)
1. Frontend on Vercel (free).
2. Backend on Render free web service (cold start accepted).
3. MongoDB Atlas M0.
4. Environment-driven config and CORS locking.
5. Basic smoke checks and runbook.

## Validation Checklist
- Order pipeline enforced: `Open -> SentToKitchen -> Served -> Billed -> Paid`
- Cannot edit billed/paid/cancelled order items.
- Cancel requires reason and appears in history.
- Offline actions queue and replay after reconnect.
- End-of-day report returns aggregate counts and totals.
- Access gate works as designed:
  - Authenticator code required only when session is absent/expired.
  - Authenticator app code verifies with drift tolerance and lockout controls.
  - Verified session allows app usage for 24 hours.
