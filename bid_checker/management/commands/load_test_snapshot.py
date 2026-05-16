"""
Recreate a BidSnapshot + MonthlyOverview in the database from
the test files captured by `capture_test_snapshot`.

Usage:
    python manage.py load_test_snapshot              # adds a new snapshot
    python manage.py load_test_snapshot --clear      # wipes existing snapshots first
    python manage.py load_test_snapshot --rerun      # re-runs the analyzer instead of loading cached JSON

Reads from bid_checker/test_data/:
    snapshot_ca.xls / snapshot_fo.xls / snapshot_barry.xls
    snapshot_meta.json
    overview_<YYYY-MM-DD>.xlsx + overview_meta.json

The new BidSnapshot's `created_at` will be NOW (auto_now_add),
not the original capture time — they're easy to confuse, so the
original time is preserved in report_data['captured_from'].
"""
import datetime
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from bid_checker.analyzer import analyze_bids
from bid_checker.models import BidSnapshot, MonthlyOverview


TEST_DATA_DIR = settings.BASE_DIR / 'bid_checker' / 'test_data'


class Command(BaseCommand):
    help = 'Load captured test data into the database. Useful for offline dev.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear', action='store_true',
            help='Delete all existing BidSnapshot and MonthlyOverview rows first.'
        )
        parser.add_argument(
            '--rerun', action='store_true',
            help='Re-run the analyzer against the captured XLS files instead of using cached report_data.'
        )

    def handle(self, *args, **options):
        if not TEST_DATA_DIR.exists():
            raise CommandError(
                f'No test data at {TEST_DATA_DIR}. '
                'Run `capture_test_snapshot` on production first.'
            )

        meta_path = TEST_DATA_DIR / 'snapshot_meta.json'
        if not meta_path.exists():
            raise CommandError(f'snapshot_meta.json missing from {TEST_DATA_DIR}.')

        meta = json.loads(meta_path.read_text())

        if options['clear']:
            n_snap = BidSnapshot.objects.count()
            n_mo   = MonthlyOverview.objects.count()
            BidSnapshot.objects.all().delete()
            MonthlyOverview.objects.all().delete()
            self.stdout.write(self.style.WARNING(
                f'Cleared {n_snap} BidSnapshot row(s) and {n_mo} MonthlyOverview row(s).'
            ))

        # ── XLS files ────────────────────────────────────────────────────────
        ca_xls    = (TEST_DATA_DIR / 'snapshot_ca.xls').read_bytes()
        fo_xls    = (TEST_DATA_DIR / 'snapshot_fo.xls').read_bytes()
        barry_xls = (TEST_DATA_DIR / 'snapshot_barry.xls').read_bytes()

        # ── MonthlyOverview (load first so the analyzer's overview lookup works) ─
        overview_meta_path = TEST_DATA_DIR / 'overview_meta.json'
        overview_bytes = None
        if overview_meta_path.exists():
            overview_meta = json.loads(overview_meta_path.read_text())
            month = datetime.date.fromisoformat(overview_meta['month'])
            overview_file = TEST_DATA_DIR / overview_meta['filename']
            if not overview_file.exists():
                raise CommandError(f'Overview file missing: {overview_file}')
            overview_bytes = overview_file.read_bytes()
            mo, created = MonthlyOverview.objects.update_or_create(
                month=month,
                defaults={'xlsx_data': overview_bytes},
            )
            self.stdout.write(
                f'{"Created" if created else "Updated"} MonthlyOverview for {month:%B %Y} '
                f'({len(overview_bytes):,} bytes)'
            )
        else:
            self.stdout.write(self.style.WARNING(
                'No overview_meta.json — falling back to static Overview.xlsx'
            ))

        # ── Build report_data ────────────────────────────────────────────────
        if options['rerun']:
            if not overview_bytes:
                from bid_checker.views import _get_overview_bytes
                overview_bytes = _get_overview_bytes()
            report_data = analyze_bids(
                ca_xls=ca_xls,
                fo_xls=fo_xls,
                overview_xlsx=overview_bytes,
                subject_name=getattr(settings, 'KALITTA_BARRY_NAME', 'Moore, Barry'),
                subject_class='FO',
                subject_xls=barry_xls,
            )
            self.stdout.write('Re-ran analyzer against captured XLS files.')
        else:
            report_data = meta.get('report_data', {})

        # Stash the original capture metadata for traceability
        report_data['captured_from'] = {
            'source_id':         meta.get('source_id'),
            'original_created':  meta.get('created_at'),
            'projected_award':   meta.get('projected_award'),
            'loaded_via':        'load_test_snapshot',
            'rerun_analyzer':    bool(options['rerun']),
        }

        # ── Create the snapshot ──────────────────────────────────────────────
        snap = BidSnapshot.objects.create(
            ca_xls=ca_xls,
            fo_xls=fo_xls,
            barry_xls=barry_xls,
            report_data=report_data,
            projected_award=report_data.get('projected_award', meta.get('projected_award', '???')),
            success=True,
        )

        self.stdout.write(self.style.SUCCESS(
            f'Created BidSnapshot id={snap.id} from captured data '
            f'(originally captured {meta.get("created_at")}).'
        ))
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Test data loaded. Hit /bids/ to verify.'))
