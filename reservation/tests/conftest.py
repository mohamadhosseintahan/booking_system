import uuid

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from reservation.models import Event

User = get_user_model()


@pytest.fixture
def make_user(db):
    def _make_user(username=None):
        return User.objects.create_user(
            username=username or f"user-{uuid.uuid4().hex[:8]}",
            password="test-pass-123",
        )

    return _make_user


@pytest.fixture
def user(make_user):
    return make_user("alice")


@pytest.fixture
def other_user(make_user):
    return make_user("bob")


@pytest.fixture
def make_event(db):
    def _make_event(capacity=5, active=True, title="Concert"):
        return Event.objects.create(
            title=title,
            description="",
            capacity=capacity,
            event_date=timezone.now() + timezone.timedelta(days=7),
            active=active,
        )

    return _make_event


@pytest.fixture
def event(make_event):
    return make_event(capacity=5)


@pytest.fixture
def api_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def anon_client():
    return APIClient()
