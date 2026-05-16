"""
Bid Checker models.

BidSnapshot stores the raw XLS files and the fully-analysed result from each
refresh run.  Keeping the raw XLS bytes means we can re-run the analysis
offline without hitting the Kalitta server again.
"""
from django.db import models


class BidSnapshot(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)

    # Raw XLS bytes as downloaded from crewbids.kalittaair.com
    ca_xls   = models.BinaryField()
    fo_xls   = models.BinaryField()
    barry_xls = models.BinaryField()

    # Fully-analysed result serialised as JSON.
    # Schema mirrors the dict returned by analyzer.analyze_bids().
    report_data = models.JSONField()

    # Convenience field so we can query/display the projected award quickly.
    projected_award = models.CharField(max_length=20, blank=True)

    # Was this snapshot collected successfully end-to-end?
    success = models.BooleanField(default=True)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        status = self.projected_award if self.success else 'ERROR'
        return f"{self.created_at:%Y-%m-%d %H:%M UTC}  →  {status}"


class AppSettings(models.Model):
    """Key/value store for runtime-configurable settings (credentials etc)."""
    key   = models.CharField(max_length=100, unique=True)
    value = models.TextField(blank=True)

    class Meta:
        verbose_name = 'App setting'
        verbose_name_plural = 'App settings'

    def __str__(self):
        return f"{self.key}"

    @classmethod
    def get(cls, key, default=None):
        try:
            return cls.objects.get(key=key).value or default
        except cls.DoesNotExist:
            return default

    @classmethod
    def set(cls, key, value):
        cls.objects.update_or_create(key=key, defaults={'value': value})


class MonthlyOverview(models.Model):
    """Stores the monthly bid Overview.xlsx downloaded from Documents.aspx.
    Keyed by the first day of the bid month (e.g. 2026-05-01 for May bids).
    Avoids re-downloading the file on every scrape run.
    """
    month        = models.DateField(unique=True)
    xlsx_data    = models.BinaryField()
    downloaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-month']

    def __str__(self):
        return f"Overview {self.month.strftime('%B %Y')}"


class GuestPilot(models.Model):
    """A pilot approved to view their own bid status as a guest (no Django account).

    Guests reach /guest/, enter their staff number, and — if their row is here
    and `is_active=True` — see the current bid analysis from their perspective.

    Seeded from the company seniority list via:
        python manage.py seed_777_fleet
    """

    SEAT_CHOICES = [('CA', 'Captain'), ('FO', 'First Officer')]

    staff_number     = models.CharField(max_length=20, primary_key=True,
                                        help_text="Kalitta employee number (Emp. No.)")
    name             = models.CharField(max_length=100,
                                        help_text='Lastname, Firstname — must match the all-bids XLS exactly')
    seat_class       = models.CharField(max_length=2, choices=SEAT_CHOICES, default='FO')
    fleet            = models.CharField(max_length=10, default='777')
    seniority_number = models.IntegerField(null=True, blank=True,
                                           help_text='Company-wide seniority number from the roster')
    is_active        = models.BooleanField(default=False,
                                           help_text='Must be ticked for this pilot to view their bids')
    notes            = models.TextField(blank=True)

    added_at         = models.DateTimeField(auto_now_add=True)
    last_viewed_at   = models.DateTimeField(null=True, blank=True)
    view_count       = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['seniority_number']
        verbose_name = 'Approved guest pilot'
        verbose_name_plural = 'Approved guest pilots'

    def __str__(self):
        return f"{self.name} (#{self.staff_number})"
