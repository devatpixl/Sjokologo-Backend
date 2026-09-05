# Deploying the Sjoko Loco API

Server: `root@187.124.180.167`, code at `/srv/sjokoloko/api`, service
`sjokoloko-api` (gunicorn, port 8001, nginx fronts it as `api.sjokoloco.no`).
The whole stack lives on one box: `nextjs` (storefront) and `admin` are
sibling directories with their own services.

**Deploy the API before the storefront.** The storefront sends fields the old
API would reject, so the API must be updated first.

```bash
ssh root@187.124.180.167
cd /srv/sjokoloko/api

# 1. back up first — this is a live shop
ts=$(date +%Y%m%d-%H%M%S)
sudo -u postgres pg_dump sjokoloko_db > /root/sjokoloko_db-$ts.sql

# 2. pull, migrate, restart
git pull --ff-only origin main
venv/bin/python manage.py migrate
systemctl restart sjokoloko-api
systemctl is-active sjokoloko-api
```

## Required environment (`/srv/sjokoloko/api/.env`)

`.env` is not in git. Everything already set stays as it is, but **the
Profrakt block below must be added by hand** the first time this version is
deployed. The values already exist on the same server, in
`/srv/sjokoloko/nextjs/.env.local` — copy them across verbatim:

```
PROFRAKT_BASE=…
PROFRAKT_KEY=…
PROFRAKT_SENDER=…
PROFRAKT_TRANSPORT_AGREEMENT=…
PROFRAKT_POSTNORD_AGREEMENT=…
```

Without them the admin's "Lag fraktetikett" button returns
*"Profrakt er ikke konfigurert"*. Nothing else breaks.

Other flags worth knowing:

| Variable | Meaning |
|---|---|
| `ORDERING_PAUSED` | `True` refuses every new order with 503. The storefront has its own `NEXT_PUBLIC_ORDERING_PAUSED`; **both must be changed together**, and the storefront needs a rebuild. |
| `STOREFRONT_URL` | Base for password links in e-mails. Should be `https://sjokoloco.no`. |
| `EMAIL_TEST_OVERRIDE` | When set, every e-mail is rewritten to that one address. Leave **empty** in production or customers stop receiving mail. |

## Behaviour that changed in this version

- **Shipping labels are no longer created at checkout.** Ops presses "Lag
  fraktetikett og send" on the order in the admin, which calls Profrakt, stores
  the tracking number and e-mails the customer. Self-pickup orders get a
  "klar til henting" mail instead. A consignment **cannot be cancelled** once
  created — the button confirms first.
- **Order e-mails are sent when Vipps approves the payment**, not at checkout,
  so an abandoned order mails nobody.
- **Order creation is strict**: prices come from the database, quantities and
  stock are validated, and an order totalling 0 is refused. A stale cart
  containing an out-of-stock product now fails with a readable Norwegian error.
- Vipps accepts `payment_type: "CARD"` as well as the default wallet flow.

## After deploying

```bash
# no pending migrations, service healthy, no errors
venv/bin/python manage.py migrate --check
journalctl -u sjokoloko-api --since "-10min" --no-pager | grep -ci traceback
curl -s -o /dev/null -w "%{http_code}\n" https://api.sjokoloco.no/api/products/
```

The reconciler cron (`*/5 * * * * manage.py vipps_reconcile`) must keep
running; it converges any payment whose webhook was lost.
