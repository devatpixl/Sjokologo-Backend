# Sjokoloko — Backend API

Django REST API powering the Sjokoloko website (Next.js storefront) and admin
dashboard. Built with Django 6 + Django REST Framework + simple-jwt + PostgreSQL.

---

## Stack

- **Python** 3.12
- **Django** 6.x
- **Django REST Framework** 3.17+
- **djangorestframework-simplejwt** — JWT auth
- **django-cors-headers** — CORS for the Next.js apps
- **Pillow** — image uploads
- **django-environ** — `.env` config
- **psycopg2-binary** — PostgreSQL driver

---

## Quick start

### 1. Clone and create a virtualenv

```bash
git clone https://github.com/devatpixl/Sjokologo-Backend.git
cd Sjokologo-Backend

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Set up PostgreSQL

```bash
sudo -u postgres psql -c "CREATE USER sjokoloko WITH PASSWORD 'sjokoloko_dev';"
sudo -u postgres psql -c "CREATE DATABASE sjokoloko_db OWNER sjokoloko;"
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env if you need different values (DB credentials, secret key, etc.)
```

### 4. Migrate and seed

```bash
python manage.py migrate
python manage.py seed
```

The `seed` command creates:
- 13 products
- 8 truffle flavors
- 4 articles
- Test user: `test@sjokoloko.no` / `test1234`
- Admin user: `admin@sjokoloko.no` / `admin1234`

### 5. Run

```bash
python manage.py runserver 8000
```

API is now live at `http://localhost:8000`.

---

## Project layout

```
sjokoloko-api/
├── manage.py
├── requirements.txt
├── .env.example          # template for local .env
├── config/               # Django project settings + URL routing
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── apps/
│   ├── users/            # CustomUser, JWT auth, profile, admin views
│   ├── products/         # Product + Truffle catalog
│   ├── orders/           # Orders + OrderItems with inline shipping
│   └── utils/            # Waitlist, Contact, Articles
└── media/                # Uploaded product/article images (gitignored)
```

---

## API endpoints

### Public
| Method | URL                          | Description                       |
|--------|------------------------------|-----------------------------------|
| POST   | `/api/auth/register/`        | Register a new user               |
| POST   | `/api/auth/token/`           | Login → returns JWT               |
| POST   | `/api/auth/token/refresh/`   | Refresh access token              |
| GET    | `/api/products/`             | All products; `?category=` filter |
| GET    | `/api/products/<slug>/`      | Single product                    |
| GET    | `/api/products/slugs/`       | Slug list (for SSG)               |
| GET    | `/api/truffles/`             | All truffle flavors               |
| POST   | `/api/orders/`               | Create order (guest or authed)    |
| GET    | `/api/orders/<order_number>/`| Order confirmation lookup         |
| GET    | `/api/articles/`             | Article list                      |
| GET    | `/api/articles/<slug>/`      | Single article                    |
| GET    | `/api/articles/slugs/`       | Slug list                         |
| POST   | `/api/waitlist/`             | Join waitlist                     |
| POST   | `/api/contact/`              | Submit contact form               |

### Authenticated (JWT required)
| Method        | URL                       | Description                      |
|---------------|---------------------------|----------------------------------|
| GET / PATCH   | `/api/users/me/`          | Current user profile             |
| GET           | `/api/users/me/orders/`   | Authenticated user's orders      |
| POST          | `/api/users/me/password/` | Change password                  |

### Admin (requires `is_admin=True`)
All under `/api/admin/`.

| Method                        | URL                             |
|-------------------------------|---------------------------------|
| GET                           | `/stats/`                       |
| GET / POST                    | `/products/`                    |
| GET / PUT / PATCH / DELETE    | `/products/<id>/`               |
| GET                           | `/orders/`                      |
| GET / PATCH / DELETE          | `/orders/<order_number>/`       |
| GET                           | `/users/`                       |
| GET / PATCH / DELETE          | `/users/<id>/`                  |
| GET                           | `/waitlist/`                    |
| DELETE                        | `/waitlist/<id>/`               |
| GET                           | `/contact/`                     |
| PATCH / DELETE                | `/contact/<id>/`                |

---

## Authentication

JWT (simple-jwt). Include the access token in the `Authorization` header:

```
Authorization: Bearer <access_token>
```

The token payload includes custom claims: `is_admin`, `name`. The login response
also returns the full user object so the frontend can populate the session
without an extra `/me` call.

---

## Companion repos

- **Storefront (Next.js):** customer-facing website on port 3000
- **Admin dashboard (Next.js):** Shopify-style admin on port 3001

Both expect this API on `http://localhost:8000` (configurable via
`NEXT_PUBLIC_API_URL`).

---

## Production notes

- Set `DEBUG=False`
- Generate a strong `SECRET_KEY`
- Use a managed Postgres instance, not the dev credentials
- Configure `ALLOWED_HOSTS` and `CORS_ALLOWED_ORIGINS` for the deployed
  frontend domain
- Serve `/media/` via the web server (nginx, S3, etc.) — Django's built-in
  static-media serving is for development only
- Run `python manage.py collectstatic` for static admin assets

---

## License

Private project.
