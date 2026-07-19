from rest_framework import serializers

from reservation.models import Event, Reservation


class EventSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = [
            "uuid",
            "title",
            "description",
            "capacity",
            "event_date",
        ]


class EventDetailSerializer(serializers.ModelSerializer):
    # Event.capacity is a live counter of remaining spots; the original total
    # is reconstructed as remaining + active (each active reservation holds one spot).
    total_capacity = serializers.SerializerMethodField()
    remaining_capacity = serializers.IntegerField(source="capacity")
    active_reservations = serializers.IntegerField()
    confirmed_reservations = serializers.IntegerField()

    class Meta:
        model = Event
        fields = [
            "uuid",
            "title",
            "description",
            "event_date",
            "total_capacity",
            "active_reservations",
            "confirmed_reservations",
            "remaining_capacity",
        ]

    def get_total_capacity(self, obj) -> int:
        return obj.capacity + obj.active_reservations


class ReservationCreateSerializer(serializers.Serializer):
    event_id = serializers.UUIDField()
    tracking_id = serializers.UUIDField()


class ReservationDetailSerializer(serializers.ModelSerializer):
    event = EventSerializer()

    class Meta:
        model = Reservation
        fields = [
            "uuid",
            "status",
            "event",
            "tracking_id",
            "expired_at",
            "confirmed_at",
            "cancelled_at",
        ]
