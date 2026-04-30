# Vipps MobilePay ePayment

This app implements the customer-facing payment flow with Vipps MobilePay,
using their ePayment API. Money flows from the customer's Vipps account to the
merchant's account through three stages: **CREATE → AUTHORIZE → CAPTURE**.

## Business decision: capture-on-authorize

We capture immediately on `AUTHORIZED`, not on shipment. The merchant accepts
legal responsibility for this. The capture call is triggered by the
`AUTHORIZED` webhook, with the reconciliation cron as a fallback. There is no
"mark as shipped → capture" flow.

## Architecture in one paragraph

The Next.js checkout page (`app/kasse/page.tsx`) creates a local order, then
posts to `/api/checkout/vipps/create` (Next.js proxy → Django). Django creates
a Vipps payment and returns a `redirectUrl`. The browser does a top-level
navigation to that URL; Vipps app-switches the customer onto the Vipps app.
After approval Vipps fires webhooks (CREATED, AUTHORIZED, CAPTURED) at
`/api/webhooks/vipps/`. The AUTHORIZED handler immediately calls Vipps capture
using a persistent idempotency key. The user is also redirected back to
`/kasse/retur`, which polls `/api/checkout/vipps/status/` and shows the
outcome. A `vipps_reconcile` management command runs every 5 minutes to fix
any orders that got stuck.

## Environment configuration

Add the variables from `.env.example` to your environment. You'll need
credentials from the [Vipps developer portal](https://portal.vipps.no/):

  * `VIPPS_CLIENT_ID`, `VIPPS_CLIENT_SECRET`
  * `VIPPS_SUBSCRIPTION_KEY`
  * `VIPPS_MERCHANT_SERIAL_NUMBER`

Set `VIPPS_BASE_URL` to `https://apitest.vipps.no` for the test environment or
`https://api.vipps.no` for production.

`VIPPS_WEBHOOK_URL` must be a public HTTPS URL pointing at our
`/api/webhooks/vipps/` endpoint. In development, use ngrok or cloudflared.

## One-time deployment steps (per environment)

1. Apply migrations:

   ```bash
   python manage.py migrate
   ```

2. (One-shot) Backfill existing pre-Vipps orders so the reconciler doesn't
   touch them. Run **once** after migrating an existing database:

   ```sql
   UPDATE orders_order
      SET payment_status = 'CAPTURED'
    WHERE payment_status = 'PENDING';
   ```

3. Register the webhook with Vipps. This stores the signing secret in the
   database — re-run to rotate.

   ```bash
   python manage.py vipps_register_webhooks
   ```

4. Install the reconciliation cron line in deploy. **Required** for resilience
   — without it, failed captures are not retried automatically.

   ```cron
   */5 * * * * cd /srv/sjokoloko-api && /srv/sjokoloko-api/venv/bin/python manage.py vipps_reconcile >> /var/log/vipps_reconcile.log 2>&1
   ```

## Running tests

```bash
python -m pytest apps/payments_vipps/tests/
```

Tests use SQLite in-memory (configured in `pytest.ini` / `config/test_settings.py`)
so they don't require a Postgres CREATE DATABASE permission.

## Manual smoke test (test environment, with the Vipps test app)

You'll need the Vipps test app on a phone, signed in with a test account, and
your storefront pointing at the test backend.

### Happy path
1. Add an item to the cart, go through checkout, choose **Vipps**.
2. Click **Fullfør bestilling**.
3. Browser navigates to `landing.vipps.no` → Vipps test app receives the push.
4. Approve in the test app.
5. Phone redirects back to `/kasse/retur`.
6. Page shows "Bekrefter…" → "Betaling mottatt!" → redirects to `/takk?order=...`.
7. In `psql`:
   ```sql
   SELECT order_number, payment_status, vipps_authorized_amount, vipps_captured_amount
     FROM orders_order ORDER BY id DESC LIMIT 1;
   ```
   Should be `CAPTURED` with authorized = captured = total*100.
8. Webhook events:
   ```sql
   SELECT event_name, processed_at FROM payments_vipps_vippswebhookevent ORDER BY received_at DESC LIMIT 3;
   ```
   Should show `CREATED`, `AUTHORIZED`, `CAPTURED`.

### Failure modes
- **Decline** in Vipps test app → `payment_status='ABORTED'`, return page shows
  "Betalingen ble ikke fullført."
- **Abandon** (don't open the app, wait it out) → eventually `EXPIRED`.
- **Block the webhook endpoint via firewall, then approve** → reconciler fixes
  the order to `CAPTURED` within 5–10 minutes.
- **Replay an AUTHORIZED webhook twice** with curl using the same body and
  signature → only one `VippsWebhookEvent` row, capture called once. (The
  `tests/test_webhook_view.py::test_duplicate_delivery_is_a_noop` covers this
  end-to-end against SQLite.)
- **Bad signature** → 401, no DB writes (covered by tests).
- **Run `vipps_register_webhooks` twice** → second run deletes the previous
  registration first and creates a fresh one (idempotent).

## Where to look when something goes wrong

- Application logs: filter to `apps.payments_vipps`. Every Vipps API call
  emits `vipps.request.*` log lines with the URL, method, status, attempt
  count, and Vipps' request id (when present). No tokens or signatures are
  ever logged.
- `payments_vipps_vippswebhookevent` table — every inbound webhook is
  recorded with the raw payload, processed_at, and any processing_error.
- `orders_order.last_vipps_sync_at` — last time the reconciler or webhook
  touched this row. Stale = the order is stuck.

## What was intentionally NOT built in this round

- **Refunds.** No `VippsRefund` model, no admin "Refunder" button, no refund
  endpoint. We _do_ accept incoming `epayments.payment.refunded.v1` webhooks
  defensively — if ops issues a refund through the Vipps merchant portal, the
  order's `vipps_refunded_amount` and `payment_status` will track it.
- **Capture-on-shipment.** Captured immediately on AUTHORIZED, by design.
- **Multi-currency.** Hardcoded to NOK.
