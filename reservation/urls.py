from django.urls import include, path
from rest_framework.routers import DefaultRouter

from reservation.views import EventDetailAPIView, EventListAPIView, ReservationViewSet

app_name = "reservation"

router = DefaultRouter()
router.register("reservations", ReservationViewSet, basename="reservation")

urlpatterns = [
    path("events/", EventListAPIView.as_view(), name="event-list"),
    path("events/<uuid:uuid>/", EventDetailAPIView.as_view(), name="event-detail"),
    path("", include(router.urls)),
]
