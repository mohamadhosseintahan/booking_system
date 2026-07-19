import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "booking_system.settings")

app = Celery("booking_system")

# Read config from Django settings, using the CELERY_ namespace.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-discover tasks.py modules in installed apps.
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f"Request: {self.request!r}")


app.conf.beat_schedule = {
    "trigger-expire-reservation": {
        "task": "reservation.tasks.trigger_expire_reservation",
        "schedule": 60,  # 1 minute
    },
}
