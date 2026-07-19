import uuid

import pytest
from rest_framework.test import APIClient

from reservation.models import BookingStatus, Reservation
from reservation.services import EventBookingService

pytestmark = pytest.mark.django_db

EVENTS_URL = "/api/events/"
RESERVATIONS_URL = "/api/reservations/"


def book(event, user):
    return EventBookingService.book_event(event.uuid, uuid.uuid4(), user)


class TestAuthentication:
    def test_events_require_authentication(self, anon_client):
        assert anon_client.get(EVENTS_URL).status_code == 401

    def test_reservations_require_authentication(self, anon_client):
        assert anon_client.get(RESERVATIONS_URL).status_code == 401
        assert anon_client.post(RESERVATIONS_URL, {}).status_code == 401


class TestEventList:
    def test_lists_only_active_events(self, api_client, make_event):
        active = make_event(active=True, title="Active")
        make_event(active=False, title="Inactive")

        response = api_client.get(EVENTS_URL)

        assert response.status_code == 200
        uuids = [item["uuid"] for item in response.data["results"]]
        assert uuids == [str(active.uuid)]


class TestEventDetail:
    def test_returns_capacity_breakdown(self, api_client, make_user, make_event):
        event = make_event(capacity=5)
        book(event, make_user())  # stays PENDING
        confirmed = book(event, make_user())
        EventBookingService.confirm_reservation(confirmed.uuid)
        cancelled = book(event, make_user())
        EventBookingService.cancel_reservation(cancelled.uuid)

        response = api_client.get(f"{EVENTS_URL}{event.uuid}/")

        assert response.status_code == 200
        assert response.data["total_capacity"] == 5
        assert response.data["active_reservations"] == 2  # pending + confirmed
        assert response.data["confirmed_reservations"] == 1
        assert response.data["remaining_capacity"] == 3

    def test_inactive_event_returns_404(self, api_client, make_event):
        event = make_event(active=False)

        response = api_client.get(f"{EVENTS_URL}{event.uuid}/")

        assert response.status_code == 404


class TestCreateReservation:
    def test_creates_reservation(self, api_client, user, event):
        tracking_id = uuid.uuid4()

        response = api_client.post(
            RESERVATIONS_URL,
            {"event_id": str(event.uuid), "tracking_id": str(tracking_id)},
        )

        assert response.status_code == 201
        assert response.data["status"] == BookingStatus.PENDING
        assert response.data["tracking_id"] == str(tracking_id)
        assert Reservation.objects.filter(user=user, event=event).exists()

    def test_missing_fields_return_400(self, api_client):
        response = api_client.post(RESERVATIONS_URL, {})

        assert response.status_code == 400
        assert "event_id" in response.data
        assert "tracking_id" in response.data

    def test_invalid_uuid_returns_400(self, api_client):
        response = api_client.post(
            RESERVATIONS_URL,
            {"event_id": "not-a-uuid", "tracking_id": "also-not"},
        )

        assert response.status_code == 400

    def test_sold_out_event_returns_400(self, api_client, make_event):
        event = make_event(capacity=0)

        response = api_client.post(
            RESERVATIONS_URL,
            {"event_id": str(event.uuid), "tracking_id": str(uuid.uuid4())},
        )

        assert response.status_code == 400


class TestReservationOwnership:
    def test_user_cannot_see_others_reservations(
        self, api_client, user, other_user, event
    ):
        mine = book(event, user)
        theirs = book(event, other_user)

        response = api_client.get(RESERVATIONS_URL)

        assert response.status_code == 200
        uuids = [item["uuid"] for item in response.data["results"]]
        assert str(mine.uuid) in uuids
        assert str(theirs.uuid) not in uuids

    def test_user_cannot_cancel_others_reservation(self, other_user, user, event):
        reservation = book(event, user)

        client = APIClient()
        client.force_authenticate(user=other_user)
        response = client.delete(f"{RESERVATIONS_URL}{reservation.uuid}/")

        assert response.status_code == 404
        reservation.refresh_from_db()
        assert reservation.status == BookingStatus.PENDING

    def test_user_cannot_confirm_others_reservation(self, other_user, user, event):
        reservation = book(event, user)

        client = APIClient()
        client.force_authenticate(user=other_user)
        response = client.post(f"{RESERVATIONS_URL}{reservation.uuid}/confirm/")

        assert response.status_code == 404
        reservation.refresh_from_db()
        assert reservation.status == BookingStatus.PENDING


class TestCancelAndConfirm:
    def test_delete_cancels_reservation(self, api_client, user, event):
        reservation = book(event, user)

        response = api_client.delete(f"{RESERVATIONS_URL}{reservation.uuid}/")

        assert response.status_code == 204
        reservation.refresh_from_db()
        assert reservation.status == BookingStatus.CANCELLED
        event.refresh_from_db()
        assert event.capacity == 5

    def test_delete_cancels_confirmed_reservation(self, api_client, user, event):
        reservation = book(event, user)
        EventBookingService.confirm_reservation(reservation.uuid)

        response = api_client.delete(f"{RESERVATIONS_URL}{reservation.uuid}/")

        assert response.status_code == 204
        reservation.refresh_from_db()
        assert reservation.status == BookingStatus.CANCELLED
        event.refresh_from_db()
        assert event.capacity == 5

    def test_confirm_action(self, api_client, user, event):
        reservation = book(event, user)

        response = api_client.post(f"{RESERVATIONS_URL}{reservation.uuid}/confirm/")

        assert response.status_code == 200
        assert response.data["status"] == BookingStatus.CONFIRMED

    def test_confirm_overdue_reservation_returns_400(
        self, api_client, user, event, settings
    ):
        reservation = book(event, user)
        settings.TASK_EXPIRE_RESERVATION_DELAY = 0

        response = api_client.post(f"{RESERVATIONS_URL}{reservation.uuid}/confirm/")

        assert response.status_code == 400
        assert "expired" in response.data["detail"].lower()
        reservation.refresh_from_db()
        assert reservation.status == BookingStatus.EXPIRED
        event.refresh_from_db()
        assert event.capacity == 5
