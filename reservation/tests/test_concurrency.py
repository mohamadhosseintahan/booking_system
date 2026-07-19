"""
Concurrency tests run real parallel transactions against Postgres, so they
use transaction=True (no test-wide wrapping transaction) and each thread
closes its own DB connection when done.
"""

import threading
import uuid

import pytest
from django.db import connection
from rest_framework.exceptions import ValidationError

from reservation.models import BookingStatus, Event, Reservation
from reservation.services import EventBookingService

pytestmark = pytest.mark.django_db(transaction=True)


def run_concurrently(fn, args_list):
    """Run fn once per args tuple, all threads released at the same time.

    Returns (results, errors).
    """
    results = []
    errors = []
    barrier = threading.Barrier(len(args_list))

    def worker(args):
        try:
            barrier.wait()
            results.append(fn(*args))
        except Exception as exc:  # noqa: BLE001 - collected for assertions
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker, args=(args,)) for args in args_list]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    return results, errors


class TestConcurrentBooking:
    def test_single_spot_goes_to_exactly_one_user(self, make_user, make_event):
        event = make_event(capacity=1)
        users = [make_user() for _ in range(5)]

        results, errors = run_concurrently(
            EventBookingService.book_event,
            [(event.uuid, uuid.uuid4(), user) for user in users],
        )

        assert len(results) == 1
        assert len(errors) == 4
        assert all(isinstance(e, ValidationError) for e in errors)

        event.refresh_from_db()
        assert event.capacity == 0
        assert Reservation.objects.filter(event=event).count() == 1

    def test_capacity_never_goes_negative(self, make_user, make_event):
        event = make_event(capacity=3)
        users = [make_user() for _ in range(10)]

        results, errors = run_concurrently(
            EventBookingService.book_event,
            [(event.uuid, uuid.uuid4(), user) for user in users],
        )

        assert len(results) == 3
        assert len(errors) == 7

        event.refresh_from_db()
        assert event.capacity == 0
        assert Reservation.objects.filter(event=event).count() == 3

    def test_same_tracking_id_creates_exactly_one_reservation(
        self, make_user, make_event
    ):
        event = make_event(capacity=10)
        tracking_id = uuid.uuid4()
        users = [make_user() for _ in range(4)]

        results, errors = run_concurrently(
            EventBookingService.book_event,
            [(event.uuid, tracking_id, user) for user in users],
        )

        assert len(results) == 1
        assert len(errors) == 3

        event.refresh_from_db()
        assert event.capacity == 9
        assert Reservation.objects.filter(tracking_id=tracking_id).count() == 1

    def test_same_user_cannot_double_book_concurrently(self, user, make_event):
        event = make_event(capacity=10)

        results, errors = run_concurrently(
            EventBookingService.book_event,
            [(event.uuid, uuid.uuid4(), user) for _ in range(4)],
        )

        assert len(results) == 1
        assert len(errors) == 3

        event.refresh_from_db()
        assert event.capacity == 9
        assert Reservation.objects.filter(event=event, user=user).count() == 1


class TestConcurrentStatusTransitions:
    def test_double_cancel_releases_capacity_only_once(self, user, make_event):
        event = make_event(capacity=5)
        reservation = EventBookingService.book_event(event.uuid, uuid.uuid4(), user)
        assert Event.objects.get(pk=event.pk).capacity == 4

        results, errors = run_concurrently(
            EventBookingService.cancel_reservation,
            [(reservation.uuid,) for _ in range(2)],
        )

        assert len(results) == 1
        assert len(errors) == 1

        event.refresh_from_db()
        assert event.capacity == 5

    def test_concurrent_confirm_and_cancel_ends_cancelled(self, user, make_event):
        """Cancel always wins: a CONFIRMED reservation is still cancellable,
        so whichever order the row lock serializes them in, the final state
        is CANCELLED with capacity fully released exactly once."""
        event = make_event(capacity=5)
        reservation = EventBookingService.book_event(event.uuid, uuid.uuid4(), user)

        confirm_results, confirm_errors = [], []
        cancel_results, cancel_errors = [], []
        barrier = threading.Barrier(2)

        def confirm():
            try:
                barrier.wait()
                confirm_results.append(
                    EventBookingService.confirm_reservation(reservation.uuid)
                )
            except ValidationError as exc:
                confirm_errors.append(exc)
            finally:
                connection.close()

        def cancel():
            try:
                barrier.wait()
                cancel_results.append(
                    EventBookingService.cancel_reservation(reservation.uuid)
                )
            except ValidationError as exc:
                cancel_errors.append(exc)
            finally:
                connection.close()

        threads = [
            threading.Thread(target=confirm),
            threading.Thread(target=cancel),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        # Cancel always succeeds (PENDING or CONFIRMED are both cancellable).
        # Confirm succeeds only if it grabbed the row lock first.
        assert len(cancel_results) == 1
        assert len(cancel_errors) == 0
        assert len(confirm_results) + len(confirm_errors) == 1

        reservation.refresh_from_db()
        assert reservation.status == BookingStatus.CANCELLED

        # Capacity must be released exactly once, never twice.
        event.refresh_from_db()
        assert event.capacity == 5
