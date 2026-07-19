from django.contrib.auth import get_user_model
from django.db import models

# Create your models here.
from utils.base_model import BaseModel

User = get_user_model()


class Event(BaseModel):
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    capacity = models.PositiveIntegerField()
    event_date = models.DateTimeField()
    active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.title} - {self.uuid}"


class BookingStatus(models.TextChoices):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class Reservation(BaseModel):
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name="reservations",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="reservations",
    )
    status = models.CharField(
        max_length=31,
        choices=BookingStatus.choices,
        default=BookingStatus.PENDING,
    )
    tracking_id = models.UUIDField()
    expired_at = models.DateTimeField(null=True)
    confirmed_at = models.DateTimeField(null=True)
    cancelled_at = models.DateTimeField(null=True)

    def __str__(self):
        return f"{self.user.username} - {self.event.title} - {self.uuid}"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=(
                    "event",
                    "user",
                ),
                name="unique_reservation_per_user_event",
                condition=models.Q(
                    status__in=[
                        BookingStatus.PENDING,
                        BookingStatus.CONFIRMED,
                    ]
                ),
            ),
            models.UniqueConstraint(
                fields=("tracking_id",),
                name="unique_tracking_id",
            ),
        ]
