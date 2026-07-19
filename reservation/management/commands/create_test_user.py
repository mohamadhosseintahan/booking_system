from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from rest_framework.authtoken.models import Token

User = get_user_model()


class Command(BaseCommand):
    help = (
        "Create a test user and their auth token (for testing, no login flow needed)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--username",
            default="testuser",
            help="Username of the test user (default: testuser).",
        )
        parser.add_argument(
            "--password",
            default="testpass123",
            help="Password of the test user (default: testpass123).",
        )

    def handle(self, *args, **options):
        username = options["username"]
        password = options["password"]

        user, created = User.objects.get_or_create(username=username)
        if created:
            user.set_password(password)
            user.save()
            self.stdout.write(self.style.SUCCESS(f"Created user '{username}'."))
        else:
            self.stdout.write(f"User '{username}' already exists, reusing it.")

        token, _ = Token.objects.get_or_create(user=user)

        self.stdout.write(self.style.SUCCESS(f"Token: {token.key}"))
        self.stdout.write(
            f'Use it with: curl -H "Authorization: Token {token.key}" '
            "http://localhost:8000/api/events/"
        )
