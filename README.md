# Event Booking System

A Django + DRF backend for creating events with limited capacity and booking tickets for them, with a hard guarantee that **the number of active reservations never exceeds event capacity — even under concurrent requests**.

## Stack

- **Django / Django REST Framework** — API layer
- **PostgreSQL** — primary datastore and source of truth for all concurrency guarantees
- **Celery + Redis** — background reservation expiration (broker, result backend, and distributed lock)
- **Gunicorn (gevent workers)** — production application server
- **uv** — dependency management
- **pytest / locust** — tests and load testing

## How to Run

### With Docker (recommended)

```bash
cp .env.example .env   # adjust if needed
docker compose up --build
```

This starts Postgres, Redis, the API (migrations run automatically, then gunicorn on port 8000), a Celery worker, and Celery beat.

### Getting an auth token

All endpoints require token authentication. Events are managed through the Django admin; a helper command creates a regular user plus token for API testing:

```bash
docker compose exec app python manage.py createsuperuser        # for /admin/ (create events here)
docker compose exec app python manage.py create_test_user       # prints a DRF token
curl -H "Authorization: Token <token>" http://localhost:8000/api/events/
```

### Running tests

Tests talk to a real Postgres (required — the concurrency tests exercise actual parallel transactions):

```bash
docker compose up -d postgres
uv sync
uv run pytest
```

### Load testing

```bash
docker compose up -d
uv run locust -f locustfile.py --host http://localhost:8000
# or headless:
uv run locust -f locustfile.py --host http://localhost:8000 --headless --users 50 --spawn-rate 10 --run-time 1m
```

The locustfile seeds events, creates a dedicated Django user + token per simulated client, and treats expected business rejections under contention (sold out, already booked) as successes so only real failures are reported.

## API

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/events/` | List active events |
| GET | `/api/events/{uuid}/` | Event detail: total capacity, active (PENDING+CONFIRMED) count, confirmed count, remaining capacity |
| POST | `/api/reservations/` | Book a ticket (`event_id`, `tracking_id`) — creates a PENDING reservation |
| GET | `/api/reservations/` | List own reservations |
| GET | `/api/reservations/{uuid}/` | Retrieve own reservation |
| POST | `/api/reservations/{uuid}/confirm/` | Confirm a PENDING reservation (simulates payment) |
| DELETE | `/api/reservations/{uuid}/` | Cancel a PENDING or CONFIRMED reservation (frees capacity) |

Reservation lifecycle: `PENDING → CONFIRMED | CANCELLED | EXPIRED`, and `CONFIRMED → CANCELLED`. A PENDING reservation must be confirmed within 10 minutes or it expires automatically and its capacity is released.

## Architecture

```
reservation/
  views.py        thin HTTP layer: auth, serialization, status codes
  serializers.py  input validation and response shaping
  services.py     EventBookingService — all business logic and transactions
  models.py       Event, Reservation + DB constraints
  tasks.py        Celery tasks for reservation expiration
booking_system/
  settings.py     configuration (12-factor via env vars)
  celery.py       Celery app + beat schedule
utils/            shared helpers (base model, Redis client)
```

Views never touch business rules; every state transition (book / confirm / cancel / expire) lives in `EventBookingService`, each wrapped in a single database transaction. This keeps the domain logic testable in isolation and makes the transaction boundaries explicit.

## Concurrency & Locking Strategy

The overselling guarantee is enforced in **PostgreSQL**, not in Python — application-level checks alone can always race between the read and the write.

**1. Atomic conditional update for capacity (the core mechanism).**
`Event.capacity` is a live counter of *remaining* spots. Acquiring a spot is one atomic statement:

```sql
UPDATE event SET capacity = capacity - 1
WHERE uuid = %s AND capacity > 0;
```

Postgres row-locks the event row during the update, so concurrent bookings serialize on it; whoever finds `capacity > 0` wins, everyone else affects 0 rows and the booking is rejected. Capacity can never go negative, regardless of how many requests arrive simultaneously. The reservation INSERT and the capacity decrement share one transaction, so a failure of either rolls back both.

**2. Partial unique constraints for business invariants.**

- `unique_reservation_per_user_event` — unique `(event, user)` *where status is PENDING or CONFIRMED*: a user can hold at most one active reservation per event, but can re-book after cancelling or expiring. Two simultaneous bookings by the same user both pass any application check; the constraint makes exactly one of them fail, and the `IntegrityError` is translated into a clean validation error.
- `unique_tracking_id` — makes booking retry-safe: a client that retries with the same `tracking_id` (e.g. after a network timeout) cannot create a duplicate reservation.

**3. `SELECT ... FOR UPDATE` for status transitions.**
Confirm, cancel, and expire lock the reservation row and filter by the allowed source status. Racing transitions (confirm vs. cancel, double cancel, cancel vs. expire) serialize on the row lock, and the loser simply finds no matching row — so capacity is released **exactly once** and states never fork.


## Environment Variables

See `.env.example`. Key ones: `POSTGRES_*` (database), `CELERY_BROKER_URL` / `REDIS_*` (broker and locks), `DJANGO_DEBUG`, `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`.
