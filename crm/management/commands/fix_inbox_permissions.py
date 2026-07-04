from django.core.management.base import BaseCommand

from crm.models import EmployeeProfile, RolePermission

TARGETS = [
    (EmployeeProfile.Role.BACK, RolePermission.Resource.INBOX),
    (EmployeeProfile.Role.BACK, RolePermission.Resource.MESSAGES),
    (EmployeeProfile.Role.LOCOMOTIVE, RolePermission.Resource.INBOX),
]


class Command(BaseCommand):
    help = (
        'One-off fix: BACK/LOCOMOTIVE RolePermission rows for inbox/messages were '
        'created before these roles had access, so _ensure_role_permissions() never '
        'updates them. Sets can_read/can_write=True on the specific existing rows.'
    )

    def handle(self, *args, **options):
        updated = 0
        for role, resource in TARGETS:
            count = RolePermission.objects.filter(role=role, resource=resource).update(
                can_read=True, can_write=True,
            )
            updated += count
            self.stdout.write(f'{role}/{resource}: updated {count} row(s)')
        self.stdout.write(self.style.SUCCESS(f'Done — {updated} row(s) updated.'))
