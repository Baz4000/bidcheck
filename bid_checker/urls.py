from django.urls import path
from . import views

app_name = 'bid_checker'

urlpatterns = [
    path('',                  views.dashboard,          name='dashboard'),
    path('refresh/',          views.trigger_refresh,    name='refresh'),
    path('upload-overview/',  views.upload_overview,    name='upload_overview'),
    path('history/',          views.history,            name='history'),
    path('history/<int:pk>/', views.snapshot_detail,    name='snapshot_detail'),
    path('roster/',           views.master_roster,      name='master_roster'),
    path('settings/',         views.credential_settings, name='settings'),
]
