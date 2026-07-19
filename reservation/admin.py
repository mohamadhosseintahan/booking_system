import logging

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError
from django.db.models import F
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils.html import format_html

from .models import Event, Reservation

logger = logging.getLogger(__name__)


class CapacityUpdateForm(forms.Form):
    delta = forms.IntegerField(
        label="Capacity change",
        help_text="Positive to increase capacity, negative to decrease. "
        "Applied atomically in the database to avoid race conditions.",
    )


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "capacity",
        "event_date",
        "active",
        "created_at",
        "capacity_actions",
    )
    list_filter = ("active", "event_date")
    search_fields = ("title", "description", "uuid")
    ordering = ("-event_date",)
    readonly_fields = ("uuid", "created_at", "updated_at")

    def get_readonly_fields(self, request, obj=None):
        readonly = super().get_readonly_fields(request, obj)
        if obj is not None:
            readonly = (*readonly, "capacity")
        return readonly

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<path:object_id>/update-capacity/",
                self.admin_site.admin_view(self.update_capacity_view),
                name="reservation_event_update_capacity",
            ),
        ]
        return custom_urls + urls

    @admin.display(description="Capacity")
    def capacity_actions(self, obj):
        url = reverse("admin:reservation_event_update_capacity", args=[obj.pk])
        return format_html('<a class="button" href="{}">Update capacity</a>', url)

    def update_capacity_view(self, request, object_id):
        event = self.get_object(request, object_id)
        if event is None:
            return self._get_obj_does_not_exist_redirect(request, self.opts, object_id)
        if not self.has_change_permission(request, event):
            raise PermissionDenied

        form = CapacityUpdateForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            delta = form.cleaned_data["delta"]
            queryset = Event.objects.filter(pk=event.pk)

            try:
                updated = queryset.update(capacity=F("capacity") + delta)
            except IntegrityError as e:
                logger.error(f"IntegrityError: {e}")
                updated = 0

            if updated:
                event.refresh_from_db(fields=["capacity"])
                self.message_user(
                    request,
                    f"Capacity of “{event.title}” changed by {delta:+d} "
                    f"(now {event.capacity}).",
                    messages.SUCCESS,
                )
                return redirect("admin:reservation_event_change", object_id=event.pk)
            form.add_error(
                "delta",
                "This change would make the capacity negative. "
                "Refresh and try a smaller decrease.",
            )

        context = {
            **self.admin_site.each_context(request),
            "title": f"Update capacity: {event.title}",
            "form": form,
            "event": event,
            "opts": self.opts,
            "original": event,
        }
        return render(request, "admin/reservation/event/update_capacity.html", context)


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = ("user", "event", "status", "tracking_id", "created_at")
    list_filter = ("status", "created_at")
    search_fields = (
        "user__username",
        "event__title",
        "tracking_id",
        "uuid",
    )
    list_select_related = ("user", "event")
    autocomplete_fields = ("user", "event")
    readonly_fields = (
        "uuid",
        "tracking_id",
        "expired_at",
        "confirmed_at",
        "cancelled_at",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
