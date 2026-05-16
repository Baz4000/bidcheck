"""empire_os URL configuration."""
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path, include

from bid_checker import views as bid_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('login/', auth_views.LoginView.as_view(template_name='login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('bids/', include('bid_checker.urls', namespace='bid_checker')),

    # Public guest entry — no login required
    path('guest/',                   bid_views.guest_landing,     name='guest_landing'),
    path('guest/<str:staff_number>/', bid_views.guest_bid_status, name='guest_bid_status'),

    # Root redirect to bids
    path('', lambda req: __import__('django.shortcuts', fromlist=['redirect']).redirect('/bids/')),
]
