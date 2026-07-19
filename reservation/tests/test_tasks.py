import uuid
from unittest import mock

import pytest
from django.conf import settings
from django.utils import timezone

from reservation.models import BookingStatus, Reservation
from reservation.services import EventBookingService
from reservation.tasks import expire_reservation, trigger_expire_reservation

pytestmark = pytest.mark.django_db


def make_overdue(reservation):
    Reservation.objects.filter(pk=reservation.pk).update(
        created_at=timezone.now()
        - timezone.timedelta(seconds=settings.TASK_EXPIRE_RESERVATION_DELAY + 1)
    )


@pytest.fixture
def redis_lock():
    """Replace the Redis lock with a no-op context manager."""
    with mock.patch("reservation.tasks.RedisClient") as redis_client:
        yield redis_client.return_value.conn.lock


class TestExpireReservationTask:
    def test_expires_pending_reservation(self, user, event):
        reservation = EventBookingService.book_event(event.uuid, uuid.uuid4(), user)

        expire_reservation(reservation.uuid)

        reservation.refresh_from_db()
        assert reservation.status == BookingStatus.EXPIRED
        event.refresh_from_db()
        assert event.capacity == 5


class TestTriggerExpireReservation:
    def test_enqueues_only_overdue_pending_reservations(
        self, redis_lock, make_user, event
    ):
        overdue = EventBookingService.book_event(event.uuid, uuid.uuid4(), make_user())
        make_overdue(overdue)

        fresh = EventBookingService.book_event(event.uuid, uuid.uuid4(), make_user())

        confirmed = Reservation.objects.create(
            event=event,
            user=make_user(),
            status=BookingStatus.CONFIRMED,
            tracking_id=uuid.uuid4(),
        )
        make_overdue(confirmed)

        with mock.patch("reservation.tasks.expire_reservation.delay") as delay:
            trigger_expire_reservation()

        enqueued = {call.args[0] for call in delay.call_args_list}
        assert enqueued == {overdue.uuid}
        assert fresh.uuid not in enqueued

    def test_uses_redis_lock_to_avoid_duplicate_runs(self, redis_lock, db):
        with mock.patch("reservation.tasks.expire_reservation.delay"):
            trigger_expire_reservation()

        redis_lock.assert_called_once_with(
            name="trigger_expire_reservation",
            timeout=30,
            blocking=False,
        )
