from celery import shared_task
from celery.utils.log import get_task_logger
from django.conf import settings
from django.utils import timezone

from reservation.models import BookingStatus, Reservation
from reservation.services import EventBookingService
from utils.clients import RedisClient

logger = get_task_logger(__name__)


# we use celery task to expire reservations in background (Active Way)
@shared_task
def trigger_expire_reservation():
    redis_client = RedisClient()
    # for whenever worker is down, we can avoid duplicate execution
    logger.info("Triggering expire reservation")
    with redis_client.conn.lock(
        name="trigger_expire_reservation",
        timeout=30,
        blocking=False,
    ):
        # expired_at is null while pending; a reservation is overdue once its
        # creation time is older than the confirmation window
        reservations = Reservation.objects.filter(
            status=BookingStatus.PENDING,
            created_at__lt=timezone.now()
            - timezone.timedelta(seconds=settings.TASK_EXPIRE_RESERVATION_DELAY),
        )
        for reservation in reservations:
            expire_reservation.delay(reservation.uuid)


@shared_task
def expire_reservation(reservation_uuid):
    EventBookingService.expire_reservation(reservation_uuid)
