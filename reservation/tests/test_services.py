import uuid

import pytest
from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from reservation.models import BookingStatus, Reservation
from reservation.services import EventBookingService

pytestmark = pytest.mark.django_db


def make_overdue(reservation):
    """Push created_at back past the confirmation window."""
    Reservation.objects.filter(pk=reservation.pk).update(
        created_at=timezone.now()
        - timezone.timedelta(seconds=settings.TASK_EXPIRE_RESERVATION_DELAY + 1)
    )


class TestBookEvent:
    def test_creates_pending_reservation_and_decrements_capacity(self, user, event):
        tracking_id = uuid.uuid4()

        reservation = EventBookingService.book_event(event.uuid, tracking_id, user)

        assert reservation.status == BookingStatus.PENDING
        assert reservation.tracking_id == tracking_id
        assert reservation.user == user
        assert reservation.event == event

        event.refresh_from_db()
        assert event.capacity == 4

    def test_unknown_event_raises(self, user):
        with pytest.raises(ValidationError, match="not found"):
            EventBookingService.book_event(uuid.uuid4(), uuid.uuid4(), user)

    def test_sold_out_event_raises_and_capacity_stays_zero(self, user, make_event):
        event = make_event(capacity=0)

        with pytest.raises(ValidationError, match="sold out"):
            EventBookingService.book_event(event.uuid, uuid.uuid4(), user)

        event.refresh_from_db()
        assert event.capacity == 0
        assert Reservation.objects.filter(event=event).count() == 0

    def test_duplicate_tracking_id_raises(self, user, other_user, event):
        tracking_id = uuid.uuid4()
        EventBookingService.book_event(event.uuid, tracking_id, user)

        with pytest.raises(ValidationError, match="Tracking ID already exists"):
            EventBookingService.book_event(event.uuid, tracking_id, other_user)

        event.refresh_from_db()
        assert event.capacity == 4

    def test_same_user_cannot_book_same_event_twice(self, user, event):
        EventBookingService.book_event(event.uuid, uuid.uuid4(), user)

        with pytest.raises(ValidationError, match="already booked"):
            EventBookingService.book_event(event.uuid, uuid.uuid4(), user)

        event.refresh_from_db()
        assert event.capacity == 4

    def test_user_can_rebook_after_cancellation(self, user, event):
        first = EventBookingService.book_event(event.uuid, uuid.uuid4(), user)
        EventBookingService.cancel_reservation(first.uuid)

        second = EventBookingService.book_event(event.uuid, uuid.uuid4(), user)

        assert second.status == BookingStatus.PENDING
        event.refresh_from_db()
        assert event.capacity == 4


class TestConfirmReservation:
    def test_confirms_pending_reservation(self, user, event):
        reservation = EventBookingService.book_event(event.uuid, uuid.uuid4(), user)

        confirmed = EventBookingService.confirm_reservation(reservation.uuid)

        assert confirmed.status == BookingStatus.CONFIRMED
        assert confirmed.confirmed_at is not None
        event.refresh_from_db()
        assert event.capacity == 4

    def test_confirm_after_window_expires_and_releases_capacity(self, user, event):
        reservation = EventBookingService.book_event(event.uuid, uuid.uuid4(), user)
        make_overdue(reservation)

        result = EventBookingService.confirm_reservation(reservation.uuid)

        assert result.status == BookingStatus.EXPIRED
        assert result.expired_at is not None
        event.refresh_from_db()
        assert event.capacity == 5

    def test_confirm_twice_raises(self, user, event):
        reservation = EventBookingService.book_event(event.uuid, uuid.uuid4(), user)
        EventBookingService.confirm_reservation(reservation.uuid)

        with pytest.raises(ValidationError):
            EventBookingService.confirm_reservation(reservation.uuid)

    def test_confirm_unknown_reservation_raises(self):
        with pytest.raises(ValidationError):
            EventBookingService.confirm_reservation(uuid.uuid4())


class TestCancelReservation:
    def test_cancels_and_releases_capacity(self, user, event):
        reservation = EventBookingService.book_event(event.uuid, uuid.uuid4(), user)

        cancelled = EventBookingService.cancel_reservation(reservation.uuid)

        assert cancelled.status == BookingStatus.CANCELLED
        assert cancelled.cancelled_at is not None
        event.refresh_from_db()
        assert event.capacity == 5

    def test_cancels_confirmed_reservation_and_releases_capacity(self, user, event):
        reservation = EventBookingService.book_event(event.uuid, uuid.uuid4(), user)
        EventBookingService.confirm_reservation(reservation.uuid)

        cancelled = EventBookingService.cancel_reservation(reservation.uuid)

        assert cancelled.status == BookingStatus.CANCELLED
        assert cancelled.cancelled_at is not None
        event.refresh_from_db()
        assert event.capacity == 5

    def test_cancel_twice_raises(self, user, event):
        reservation = EventBookingService.book_event(event.uuid, uuid.uuid4(), user)
        EventBookingService.cancel_reservation(reservation.uuid)

        with pytest.raises(ValidationError):
            EventBookingService.cancel_reservation(reservation.uuid)

        event.refresh_from_db()
        assert event.capacity == 5

    def test_cancel_expired_reservation_raises(self, user, event):
        reservation = EventBookingService.book_event(event.uuid, uuid.uuid4(), user)
        EventBookingService.expire_reservation(reservation.uuid)

        with pytest.raises(ValidationError):
            EventBookingService.cancel_reservation(reservation.uuid)

        event.refresh_from_db()
        assert event.capacity == 5


class TestExpireReservation:
    def test_expires_and_releases_capacity(self, user, event):
        reservation = EventBookingService.book_event(event.uuid, uuid.uuid4(), user)

        expired = EventBookingService.expire_reservation(reservation.uuid)

        assert expired.status == BookingStatus.EXPIRED
        assert expired.expired_at is not None
        event.refresh_from_db()
        assert event.capacity == 5

    def test_expire_non_pending_reservation_raises(self, user, event):
        reservation = EventBookingService.book_event(event.uuid, uuid.uuid4(), user)
        EventBookingService.cancel_reservation(reservation.uuid)

        with pytest.raises(ValidationError):
            EventBookingService.expire_reservation(reservation.uuid)

        event.refresh_from_db()
        assert event.capacity == 5
