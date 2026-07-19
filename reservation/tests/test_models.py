import uuid

import pytest
from django.db import IntegrityError

from reservation.models import BookingStatus, Reservation

pytestmark = pytest.mark.django_db


def create_reservation(event, user, status=BookingStatus.PENDING, tracking_id=None):
    return Reservation.objects.create(
        event=event,
        user=user,
        status=status,
        tracking_id=tracking_id or uuid.uuid4(),
    )


class TestUniqueReservationPerUserEvent:
    @pytest.mark.parametrize(
        "first_status,second_status",
        [
            (BookingStatus.PENDING, BookingStatus.PENDING),
            (BookingStatus.PENDING, BookingStatus.CONFIRMED),
            (BookingStatus.CONFIRMED, BookingStatus.CONFIRMED),
        ],
    )
    def test_active_duplicate_is_rejected(
        self, event, user, first_status, second_status
    ):
        create_reservation(event, user, status=first_status)

        with pytest.raises(IntegrityError, match="unique_reservation_per_user_event"):
            create_reservation(event, user, status=second_status)

    @pytest.mark.parametrize(
        "inactive_status", [BookingStatus.CANCELLED, BookingStatus.EXPIRED]
    )
    def test_inactive_reservation_does_not_block_rebooking(
        self, event, user, inactive_status
    ):
        create_reservation(event, user, status=inactive_status)

        reservation = create_reservation(event, user, status=BookingStatus.PENDING)

        assert reservation.pk is not None

    def test_different_users_can_book_same_event(self, event, user, other_user):
        create_reservation(event, user)
        reservation = create_reservation(event, other_user)

        assert reservation.pk is not None

    def test_same_user_can_book_different_events(self, make_event, user):
        create_reservation(make_event(), user)
        reservation = create_reservation(make_event(), user)

        assert reservation.pk is not None


class TestUniqueTrackingId:
    def test_duplicate_tracking_id_is_rejected(self, make_event, user, other_user):
        tracking_id = uuid.uuid4()
        create_reservation(make_event(), user, tracking_id=tracking_id)

        with pytest.raises(IntegrityError, match="unique_tracking_id"):
            create_reservation(make_event(), other_user, tracking_id=tracking_id)
