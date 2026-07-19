"""
Load test for the booking API.

Usage:
    1. Start the stack (app + postgres + redis), e.g.:
         docker compose up -d
    2. Run locust from the project root (it needs DB access to create
       test users/tokens, same as manage.py):
         uv run locust -f locustfile.py --host http://localhost:8000
    3. Open http://localhost:8089 and start the swarm.

Headless example:
    uv run locust -f locustfile.py --host http://localhost:8000 \
        --headless --users 50 --spawn-rate 10 --run-time 1m

Each simulated user gets its own Django user + DRF token, so the
one-reservation-per-user-per-event constraint behaves like production.
Business rejections under contention (sold out, already booked) are
counted as successes; anything else is a real failure.
"""

import os
import random
import uuid

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "booking_system.settings")
django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.db import connection  # noqa: E402
from django.utils import timezone  # noqa: E402
from locust import HttpUser, between, events, task  # noqa: E402
from rest_framework.authtoken.models import Token  # noqa: E402

from reservation.models import Event  # noqa: E402

User = get_user_model()

EXPECTED_BOOKING_ERRORS = (
    "sold out",
    "already booked",
    "Tracking ID already exists",
)

# Odds of what a user does with a fresh reservation.
CONFIRM_WEIGHT = 0.6
CANCEL_WEIGHT = 0.3  # remaining 10%: leave it pending (expires later)

SEED_EVENT_COUNT = 5
SEED_EVENT_CAPACITY = 1000


@events.test_start.add_listener
def seed_events(environment, **kwargs):
    """Ensure there are open events to book before the swarm starts."""
    missing = (
        SEED_EVENT_COUNT - Event.objects.filter(active=True, capacity__gt=0).count()
    )
    for _ in range(max(missing, 0)):
        Event.objects.create(
            title=f"load-test-{uuid.uuid4().hex[:8]}",
            description="Seeded by locustfile",
            capacity=SEED_EVENT_CAPACITY,
            event_date=timezone.now() + timezone.timedelta(days=30),
        )
    connection.close()


class BookingUser(HttpUser):
    wait_time = between(0.5, 2)

    def on_start(self):
        """Create a dedicated Django user + token for this simulated user."""
        user = User.objects.create_user(
            username=f"locust-{uuid.uuid4().hex[:12]}",
            password="locust-pass-123",
        )
        token, _ = Token.objects.get_or_create(user=user)
        connection.close()

        self.client.headers["Authorization"] = f"Token {token.key}"
        self.event_uuids = []

    @task(3)
    def browse_events(self):
        response = self.client.get("/api/events/")
        if response.ok:
            self.event_uuids = [item["uuid"] for item in response.json()["results"]]

    @task(6)
    def book_event(self):
        if not self.event_uuids:
            self.browse_events()
            if not self.event_uuids:
                return

        payload = {
            "event_id": random.choice(self.event_uuids),
            "tracking_id": str(uuid.uuid4()),
        }
        with self.client.post(
            "/api/reservations/",
            json=payload,
            name="/api/reservations/ [book]",
            catch_response=True,
        ) as response:
            if response.status_code == 201:
                self._settle(response.json()["uuid"])
            elif response.status_code == 400 and any(
                message in response.text for message in EXPECTED_BOOKING_ERRORS
            ):
                # Losing the race for a spot is a correct outcome under load.
                response.success()

    @task(1)
    def my_reservations(self):
        self.client.get("/api/reservations/")

    def _settle(self, reservation_uuid):
        """Confirm, cancel, or abandon a freshly created reservation."""
        roll = random.random()
        if roll < CONFIRM_WEIGHT:
            self.client.post(
                f"/api/reservations/{reservation_uuid}/confirm/",
                name="/api/reservations/{uuid}/confirm/",
            )
        elif roll < CONFIRM_WEIGHT + CANCEL_WEIGHT:
            self.client.delete(
                f"/api/reservations/{reservation_uuid}/",
                name="/api/reservations/{uuid} [cancel]",
            )
        # otherwise leave it pending so the expiry flow gets exercised too
