"""
Bid Checker — Views

Authenticated routes:
  GET  /bids/           → dashboard (latest snapshot)
  POST /bids/refresh/   → run scraper + analyzer, save snapshot, redirect
  GET  /bids/history/   → list of past snapshots
  GET  /bids/settings/  → view/update Kalitta credentials
  POST /bids/settings/  → save credentials to DB

Public guest routes (no login):
  GET  /guest/                  → staff-number entry form
  POST /guest/                  → resolves to /guest/<staff_number>/
  GET  /guest/<staff_number>/   → view that pilot's bid status (if approved)
"""
import logging
from datetime import datetime, timezone

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import F
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST, require_http_methods

from .models import BidSnapshot, AppSettings, GuestPilot
from .scraper import scrape_bids, ScraperError
from .analyzer import analyze_bids

logger = logging.getLogger('bid_checker')

OVERVIEW_PATH = settings.BASE_DIR / 'bid_checker' / 'data' / 'Overview.xlsx'


def _get_overview_bytes() -> bytes:
    if not OVERVIEW_PATH.exists():
        raise FileNotFoundError(
            f"Overview.xlsx not found at {OVERVIEW_PATH}. "
            "Copy it into empire-os/bid_checker/data/"
        )
    return OVERVIEW_PATH.read_bytes()


def _kalitta_credentials():
    """Read credentials from DB, falling back to env/.env values."""
    username    = AppSettings.get('kalitta_username')    or settings.KALITTA_USERNAME
    password    = AppSettings.get('kalitta_password')    or settings.KALITTA_PASSWORD
    employee_id = AppSettings.get('kalitta_employee_id') or getattr(settings, 'KALITTA_EMPLOYEE_ID', '71837')
    return username, password, employee_id


# ── Authenticated dashboard ──────────────────────────────────────────────────

@login_required
def dashboard(request):
    snapshot = BidSnapshot.objects.filter(success=True).order_by('-created_at').first()
    return render(request, 'bid_checker/dashboard.html', {
        'snapshot': snapshot,
        'page_title': 'Bid Status',
        'is_guest': False,
        'base_template': 'base.html',
    })


@login_required
@require_POST
def trigger_refresh(request):
    logger.info('Manual refresh triggered by %s', request.user)
    try:
        username, password, employee_id = _kalitta_credentials()

        raw = scrape_bids(
            username=username,
            password=password,
            barry_employee_id=employee_id,
        )

        result = analyze_bids(
            ca_xls=raw['ca'],
            fo_xls=raw['fo'],
            overview_xlsx=raw['overview'],
            subject_name=getattr(settings, 'KALITTA_BARRY_NAME', 'Moore, Barry'),
            subject_class='FO',
            subject_xls=raw['barry'],
        )

        BidSnapshot.objects.create(
            ca_xls=raw['ca'],
            fo_xls=raw['fo'],
            barry_xls=raw['barry'],
            report_data=result,
            projected_award=result.get('projected_award', '???'),
            success=True,
        )

        projected = result.get('projected_award', '???')
        messages.success(request, f"Bids refreshed — projected award: {projected}")
        logger.info('Refresh complete. Projected award: %s', projected)

    except ScraperError as e:
        logger.error('Scraper error: %s', e)
        BidSnapshot.objects.create(
            ca_xls=b'', fo_xls=b'', barry_xls=b'',
            report_data={}, projected_award='',
            success=False, error_message=str(e),
        )
        messages.error(request, f"Scraper failed: {e}")

    except FileNotFoundError as e:
        logger.error('Overview file missing: %s', e)
        messages.error(request, str(e))

    except Exception as e:
        logger.exception('Unexpected error during refresh')
        messages.error(request, f"Unexpected error: {e}")

    return redirect('bid_checker:dashboard')


@login_required
def history(request):
    snapshots = BidSnapshot.objects.all()[:50]
    return render(request, 'bid_checker/history.html', {
        'snapshots': snapshots,
        'page_title': 'Bid History',
    })


@login_required
def snapshot_detail(request, pk):
    snapshot = get_object_or_404(BidSnapshot, pk=pk)
    return render(request, 'bid_checker/dashboard.html', {
        'snapshot': snapshot,
        'page_title': f'Snapshot — {snapshot.created_at:%Y-%m-%d %H:%M UTC}',
        'is_historical': True,
        'is_guest': False,
        'base_template': 'base.html',
    })


@login_required
@require_http_methods(['GET', 'POST'])
def credential_settings(request):
    username, _, employee_id = _kalitta_credentials()

    if request.method == 'POST':
        new_username    = request.POST.get('kalitta_username', '').strip()
        new_password    = request.POST.get('kalitta_password', '').strip()
        new_employee_id = request.POST.get('kalitta_employee_id', '').strip()

        updated = []
        if new_username:
            AppSettings.set('kalitta_username', new_username)
            updated.append('username')
        if new_password:
            AppSettings.set('kalitta_password', new_password)
            updated.append('password')
        if new_employee_id:
            AppSettings.set('kalitta_employee_id', new_employee_id)
            updated.append('employee ID')

        if updated:
            messages.success(request, f"Updated: {', '.join(updated)}.")
        else:
            messages.warning(request, 'No changes — all fields were blank.')

        return redirect('bid_checker:settings')

    return render(request, 'bid_checker/settings.html', {
        'kalitta_username':    username,
        'kalitta_employee_id': employee_id,
        'page_title': 'Bid Site Credentials',
    })


# ── Public guest routes (no login) ───────────────────────────────────────────

@require_http_methods(['GET', 'POST'])
def guest_landing(request):
    """Staff-number entry page. Anyone can hit this; the next page checks approval."""
    if request.method == 'POST':
        staff_number = (request.POST.get('staff_number') or '').strip()
        if staff_number.isdigit():
            return redirect('guest_bid_status', staff_number=staff_number)
        return render(request, 'bid_checker/guest_landing.html', {
            'error': 'Please enter a numeric staff number.',
            'submitted': staff_number,
        })
    return render(request, 'bid_checker/guest_landing.html', {})


def guest_bid_status(request, staff_number):
    """Render the bid analysis from a guest pilot's perspective.

    Gracefully handles three not-allowed states:
      - pilot not in GuestPilot table          → "ask Barry for access"
      - pilot exists but is_active=False       → "your account is pending"
      - pilot is approved but no current bids  → "no current bid data"
    """
    # 1. Look up the guest
    try:
        guest = GuestPilot.objects.get(staff_number=staff_number)
    except GuestPilot.DoesNotExist:
        return render(request, 'bid_checker/guest_denied.html', {
            'reason': 'not_found',
            'staff_number': staff_number,
        }, status=404)

    if not guest.is_active:
        return render(request, 'bid_checker/guest_denied.html', {
            'reason': 'inactive',
            'staff_number': staff_number,
            'guest': guest,
        }, status=403)

    # 2. Pull the latest snapshot
    snapshot = BidSnapshot.objects.filter(success=True).order_by('-created_at').first()
    if not snapshot:
        return render(request, 'bid_checker/guest_denied.html', {
            'reason': 'no_snapshot',
            'guest': guest,
        }, status=503)

    # 3. Re-run the analyzer from the guest's perspective.
    #    Cheap — sub-second. No precomputation needed.
    try:
        overview_bytes = _get_overview_bytes()
        report_data = analyze_bids(
            ca_xls=bytes(snapshot.ca_xls),
            fo_xls=bytes(snapshot.fo_xls),
            overview_xlsx=overview_bytes,
            subject_name=guest.name,
            subject_class=guest.seat_class,
            subject_xls=None,  # extract from all-bids file
        )
    except Exception as e:
        logger.exception('Guest analyzer failed for %s', staff_number)
        return render(request, 'bid_checker/guest_denied.html', {
            'reason': 'analysis_failed',
            'guest': guest,
            'detail': str(e),
        }, status=500)

    if not report_data.get('lines'):
        return render(request, 'bid_checker/guest_denied.html', {
            'reason': 'no_bids',
            'guest': guest,
        }, status=200)

    # 4. Record the view (atomic increment to avoid races)
    GuestPilot.objects.filter(pk=guest.pk).update(
        view_count=F('view_count') + 1,
        last_viewed_at=datetime.now(timezone.utc),
    )

    # 5. Synthesize a snapshot-like object for the template
    class _GuestSnapshot:
        def __init__(self, report_data, created_at):
            self.report_data = report_data
            self.created_at = created_at
            self.projected_award = report_data.get('projected_award', '???')

    guest_snapshot = _GuestSnapshot(report_data, snapshot.created_at)

    return render(request, 'bid_checker/dashboard.html', {
        'snapshot':       guest_snapshot,
        'page_title':     f'Bid Status — {guest.name}',
        'is_guest':       True,
        'guest':          guest,
        'base_template':  'base_guest.html',
    })
