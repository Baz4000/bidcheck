"""
Dump the current latest BidSnapshot and MonthlyOverview to disk
so we can develop and test offline (e.g. after the Kalitta bidding
window closes and the scraper has nothing to scrape).

Run on production *before* the bid window closes:
    docker-compose run --rm web python manage.py capture_test_snapshot

Writes to bid_checker/test_data/:
    snapshot_ca.xls          — raw CA AllBids XLS
    snapshot_fo.xls          — raw FO AllBids XLS
    snapshot_barry.xls       — Barry's personal bids XLS
    snapshot_meta.json       — projected_award + full report_data JSON
    overview_<YYYY-MM-DD>.xlsx — the bid-month Overview.xlsx
    overview_meta.json       — which month the overview is for

The captured files are designed to be committed to the repo so
anyone with the codebase can `load_test_snapshot` and have a
working dataset locally.
"""
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from bid_checker.models import BidSnapshot, MonthlyOverview


TEST_DATA_DIR = settings.BASE_DIR / 'bid_checker' / 'test_data'


class Command(BaseCommand):
    help = 'Capture the latest BidSnapshot + MonthlyOverview to disk for offline development.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--snapshot-id', type=int, default=None,
            help='Capture a specific BidSnapshot by id instead of the latest successful one.'
        )

    def handle(self, *args, **options):
        TEST_DATA_DIR.mkdir(parents=True, exist_ok=True)

        # ── BidSnapshot ──────────────────────────────────────────────────────
        if options['snapshot_id']:
            try:
                snap = BidSnapshot.objects.get(pk=options['snapshot_id'])
            except BidSnapshot.DoesNotExist:
                raise CommandError(f"No BidSnapshot with id={options['snapshot_id']}")
        else:
            snap = BidSnapshot.objects.filter(success=True).order_by('-created_at').first()
            if not snap:
                raise CommandError('No successful BidSnapshot to capture.')

        (TEST_DATA_DIR / 'snapshot_ca.xls').write_bytes(bytes(snap.ca_xls))
        (TEST_DATA_DIR / 'snapshot_fo.xls').write_bytes(bytes(snap.fo_xls))
        (TEST_DATA_DIR / 'snapshot_barry.xls').write_bytes(bytes(snap.barry_xls))

        snap_meta = {
            'source_id':       snap.id,
            'created_at':      snap.created_at.isoformat(),
            'projected_award': snap.projected_award,
            'success':         snap.success,
            'error_message':   snap.error_message,
            'report_data':     snap.report_data,
        }
        (TEST_DATA_DIR / 'snapshot_meta.json').write_text(
            json.dumps(snap_meta, indent=2, default=str)
        )

        self.stdout.write(self.style.SUCCESS(
            f'Captured BidSnapshot id={snap.id} from {snap.created_at:%Y-%m-%d %H:%M UTC} '
            f'(projected: {snap.projected_award})'
        ))

        # ── MonthlyOverview ──────────────────────────────────────────────────
        mo = MonthlyOverview.objects.order_by('-month').first()
        if mo:
            overview_name = f'overview_{mo.month.isoformat()}.xlsx'
            (TEST_DATA_DIR / overview_name).write_bytes(bytes(mo.xlsx_data))
            (TEST_DATA_DIR / 'overview_meta.json').write_text(json.dumps({
                'month':         mo.month.isoformat(),
                'downloaded_at': mo.downloaded_at.isoformat(),
                'filename':      overview_name,
                'byte_count':    len(bytes(mo.xlsx_data)),
            }, indent=2))
            self.stdout.write(self.style.SUCCESS(
                f'Captured MonthlyOverview for {mo.month:%B %Y} → {overview_name}'
            ))
        else:
            self.stdout.write(self.style.WARNING(
                'No MonthlyOverview found — overview was not captured. '
                'The system will fall back to the static Overview.xlsx when this snapshot is loaded.'
            ))

        # ── Summary ──────────────────────────────────────────────────────────
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'Test data written to: {TEST_DATA_DIR}'))
        self.stdout.write('To restore later: python manage.py load_test_snapshot')
        self.stdout.write('To commit so others can develop offline: git add bid_checker/test_data/ && git commit')
