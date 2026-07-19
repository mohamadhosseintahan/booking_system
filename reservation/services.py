import logging

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from reservation.models import BookingStatus, Event, Reservation

logger = logging.getLogger(__name__)


class EventBookingService:
    @classmethod
    def book_event(cls, event_uuid, tracking_id, user) -> Reservation:
        with transaction.atomic():
            try:
                event = Event.objects.get(uuid=event_uuid)
            except Event.DoesNotExist:
                raise ValidationError(f"Event with UUID {event_uuid} not found")

            if event.capacity <= 0:
                raise ValidationError("Event is sold out")
            try:
                reservation = Reservation.objects.create(
                    event=event,
                    tracking_id=tracking_id,
                    user=user,
                )
            except IntegrityError as e:
                logger.info(f"IntegrityError: {e}")
                if "unique_tracking_id" in str(e):
                    raise ValidationError("Tracking ID already exists")
                if "unique_reservation_per_user_event" in str(e):
                    raise ValidationError("You have already booked this event")
                raise ValidationError("Failed to create reservation")

            cls._acquire_event_capacity(event_uuid)

            return reservation

    @classmethod
    def confirm_reservation(cls, reservation_uuid) -> Reservation:
        with transaction.atomic():
            try:
                reservation = Reservation.objects.select_for_update().get(
                    uuid=reservation_uuid,
                    status=BookingStatus.PENDING,
                )
            except Reservation.DoesNotExist:
                raise ValidationError(
                    f"Reservation with UUID {reservation_uuid} not found or already confirmed"
                )
            # if time of confirmation has passed, we need to expire the reservation(Passive Way)
            if (
                reservation.created_at
                + timezone.timedelta(seconds=settings.TASK_EXPIRE_RESERVATION_DELAY)
                < timezone.now()
            ):
                reservation.expired_at = timezone.now()
                reservation.status = BookingStatus.EXPIRED
                reservation.save(update_fields=["expired_at", "status"])
                cls._release_event_capacity(reservation.event.uuid)
                return reservation

            reservation.confirmed_at = timezone.now()
            reservation.status = BookingStatus.CONFIRMED
            reservation.save(update_fields=["confirmed_at", "status"])
            return reservation

    @classmethod
    def cancel_reservation(cls, reservation_uuid):
        with transaction.atomic():
            try:
                reservation = Reservation.objects.select_for_update().get(
                    uuid=reservation_uuid,
                    status__in=[BookingStatus.PENDING, BookingStatus.CONFIRMED],
                )
            except Reservation.DoesNotExist:
                raise ValidationError(
                    f"Reservation with UUID {reservation_uuid} not found or not cancellable"
                )
            reservation.cancelled_at = timezone.now()
            reservation.status = BookingStatus.CANCELLED
            reservation.save(update_fields=["cancelled_at", "status"])
            cls._release_event_capacity(reservation.event.uuid)
            return reservation

    @classmethod
    def expire_reservation(cls, reservation_uuid):
        with transaction.atomic():
            try:
                reservation = Reservation.objects.select_for_update().get(
                    uuid=reservation_uuid,
                    status=BookingStatus.PENDING,
                )
            except Reservation.DoesNotExist:
                raise ValidationError(
                    f"Reservation with UUID {reservation_uuid} not found or already expired"
                )
            reservation.expired_at = timezone.now()
            reservation.status = BookingStatus.EXPIRED
            reservation.save(update_fields=["expired_at", "status"])
            cls._release_event_capacity(reservation.event.uuid)
            return reservation

    # this method should be called in an atomic block
    @staticmethod
    def _release_event_capacity(event_uuid):
        count = (
            Event.objects.select_for_update()
            .filter(uuid=event_uuid)
            .update(capacity=F("capacity") + 1)
        )
        if count == 0:
            raise ValidationError("Failed to release event capacity")
        return count

    # this method should be called in an atomic block
    @staticmethod
    def _acquire_event_capacity(event_uuid):
        count = (
            Event.objects.select_for_update()
            .filter(
                uuid=event_uuid,
                capacity__gt=0,
            )
            .update(capacity=F("capacity") - 1)
        )
        if count == 0:
            raise ValidationError("Event is sold out")
        return count
