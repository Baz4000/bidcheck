"""
Seed the GuestPilot table from the parsed 777 seniority list.

Usage:
    python manage.py seed_777_fleet
    python manage.py seed_777_fleet --activate-all   # opt: mark every pilot active
    python manage.py seed_777_fleet --path /path/to/roster.json

Defaults:
    * Reads bid_checker/data/777_fleet_roster.json
    * Creates rows with is_active=False (Barry approves manually via admin)
    * Idempotent — existing rows are updated, not duplicated
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

from bid_checker.models import GuestPilot


DEFAULT_ROSTER_PATH = settings.BASE_DIR / 'bid_checker' / 'data' / '777_fleet_roster.json'


class Command(BaseCommand):
    help = 'Seed the GuestPilot table from the parsed 777 fleet roster JSON.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--path',
            default=str(DEFAULT_ROSTER_PATH),
            help='Path to the roster JSON file.',
        )
        parser.add_argument(
            '--activate-all',
            action='store_true',
            help='Mark every newly-created row is_active=True. By default new rows are inactive.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would happen without writing to the DB.',
        )

    def handle(self, *args, **options):
        roster_path = Path(options['path'])
        if not roster_path.exists():
            raise CommandError(f'Roster file not found: {roster_path}')

        try:
            roster = json.loads(roster_path.read_text())
        except Exception as e:
            raise CommandError(f'Failed to parse {roster_path}: {e}')

        if not isinstance(roster, list):
            raise CommandError('Expected JSON array at top level.')

        activate_all = options['activate_all']
        dry_run      = options['dry_run']

        created = updated = skipped = 0

        for row in roster:
            staff_number = str(row.get('emp_no', '')).strip()
            name         = str(row.get('name', '')).strip()
            seat_class   = str(row.get('class', '')).strip().upper()
            fleet        = str(row.get('type', '')).strip()
            sen_no       = row.get('sen_no')

            if not staff_number or not name or seat_class not in ('CA', 'FO'):
                skipped += 1
                continue

            defaults = {
                'name':             name,
                'seat_class':       seat_class,
                'fleet':            fleet or '777',
                'seniority_number': sen_no,
            }

            if dry_run:
                exists = GuestPilot.objects.filter(staff_number=staff_number).exists()
                action = 'UPDATE' if exists else 'CREATE'
                self.stdout.write(f'  [{action}] {staff_number}  {name}  ({seat_class}, sen #{sen_no})')
                if action == 'CREATE': created += 1
                else: updated += 1
                continue

            obj, was_created = GuestPilot.objects.update_or_create(
                staff_number=staff_number,
                defaults=defaults,
            )
            if was_created:
                # Set is_active only on newly-created rows; don't trample Barry's
                # manual approvals when this is re-run.
                obj.is_active = activate_all
                obj.save(update_fields=['is_active'])
                created += 1
            else:
                updated += 1

        msg = f'Seed complete. created={created}, updated={updated}, skipped={skipped}'
        if dry_run:
            msg = '[DRY RUN] ' + msg
        self.stdout.write(self.style.SUCCESS(msg))

        if not activate_all and created > 0 and not dry_run:
            self.stdout.write(self.style.WARNING(
                f'  {created} newly-created rows are is_active=False. '
                'Approve individual pilots via /admin/bid_checker/guestpilot/.'
            ))
