from django.contrib import admin
from .models import BidSnapshot, AppSettings, GuestPilot


@admin.register(BidSnapshot)
class BidSnapshotAdmin(admin.ModelAdmin):
    list_display  = ('created_at', 'projected_award', 'success', 'error_message')
    list_filter   = ('success',)
    readonly_fields = ('created_at', 'report_data', 'projected_award',
                       'success', 'error_message')
    ordering = ('-created_at',)

    def has_add_permission(self, request):
        return False  # snapshots are created only by the scraper


@admin.register(AppSettings)
class AppSettingsAdmin(admin.ModelAdmin):
    list_display = ('key', 'value')
    search_fields = ('key',)


@admin.register(GuestPilot)
class GuestPilotAdmin(admin.ModelAdmin):
    list_display    = ('staff_number', 'name', 'seat_class', 'fleet',
                       'seniority_number', 'is_active', 'view_count',
                       'last_viewed_at')
    list_filter     = ('is_active', 'seat_class', 'fleet')
    list_editable   = ('is_active',)
    search_fields   = ('staff_number', 'name')
    ordering        = ('seniority_number',)
    readonly_fields = ('added_at', 'last_viewed_at', 'view_count')

    fieldsets = (
        ('Identity', {
            'fields': ('staff_number', 'name', 'seat_class', 'fleet', 'seniority_number')
        }),
        ('Access', {
            'fields': ('is_active', 'notes'),
            'description': 'Tick "is active" to allow this pilot to view their bids at /guest/.'
        }),
        ('Activity (read-only)', {
            'fields': ('added_at', 'last_viewed_at', 'view_count'),
            'classes': ('collapse',)
        }),
    )
