import uuid

from django.db import models


class BaseModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    uuid = models.UUIDField(default=uuid.uuid4)

    class Meta:
        abstract = True
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["uuid"],
                name="%(app_label)s_%(class)s_uuid_unique",
            ),
        ]
