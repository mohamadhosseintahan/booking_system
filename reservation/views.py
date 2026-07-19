from django.db.models import Count, Q
from rest_framework import generics, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from reservation.models import BookingStatus, Event, Reservation
from reservation.serializers import (
    EventDetailSerializer,
    EventSerializer,
    ReservationCreateSerializer,
    ReservationDetailSerializer,
)
from reservation.services import EventBookingService


class EventListAPIView(generics.ListAPIView):
    queryset = Event.objects.filter(active=True)
    serializer_class = EventSerializer
    lookup_field = "uuid"


class EventDetailAPIView(generics.RetrieveAPIView):
    serializer_class = EventDetailSerializer
    lookup_field = "uuid"

    def get_queryset(self):
        return Event.objects.filter(active=True).annotate(
            active_reservations=Count(
                "reservations",
                filter=Q(
                    reservations__status__in=[
                        BookingStatus.PENDING,
                        BookingStatus.CONFIRMED,
                    ]
                ),
            ),
            confirmed_reservations=Count(
                "reservations",
                filter=Q(reservations__status=BookingStatus.CONFIRMED),
            ),
        )


class ReservationViewSet(viewsets.ModelViewSet):
    serializer_class = ReservationDetailSerializer
    http_method_names = ["post", "get", "delete", "trace", "options", "head"]
    lookup_field = "uuid"

    def get_queryset(self):
        return Reservation.objects.filter(user=self.request.user).select_related(
            "event"
        )

    def get_serializer_class(self):
        if self.action == "create":
            return ReservationCreateSerializer
        return ReservationDetailSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        event_id = serializer.validated_data.get("event_id")
        tracking_id = serializer.validated_data.get("tracking_id")
        user = request.user

        reservation = EventBookingService.book_event(event_id, tracking_id, user)

        return Response(
            ReservationDetailSerializer(reservation).data,
            status=status.HTTP_201_CREATED,
        )

    def destroy(self, request, *args, **kwargs):
        reservation = self.get_object()
        EventBookingService.cancel_reservation(reservation.uuid)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(methods=["post"], detail=True)
    def confirm(self, request, *args, **kwargs):
        reservation = self.get_object()
        reservation = EventBookingService.confirm_reservation(reservation.uuid)
        if reservation.status == BookingStatus.EXPIRED:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"detail": "Reservation has expired"},
            )
        return Response(
            ReservationDetailSerializer(reservation).data,
            status=status.HTTP_200_OK,
        )
