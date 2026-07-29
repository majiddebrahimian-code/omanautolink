from django.core.management.base import BaseCommand

from accounts.services import ensure_default_role_groups


class Command(BaseCommand):
    help = "گروه‌ها و مجوزهای پایهٔ سیستم را همگام‌سازی می‌کند."

    def handle(self, *args, **options):
        role_groups = ensure_default_role_groups()

        group_names = ", ".join(sorted(role_groups.keys()))

        self.stdout.write(
            self.style.SUCCESS(
                "گروه‌های پایه با موفقیت همگام‌سازی شدند: " f"{group_names}"
            )
        )
