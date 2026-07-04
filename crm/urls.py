from django.urls import path

from . import views

app_name = 'crm'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('client/<int:client_id>/json/', views.client_detail_json, name='client_json'),
    path('api/site/webhook/', views.site_webhook, name='site_webhook'),
    path('api/tg-qr-status/', views.tg_qr_status, name='tg_qr_status'),
]
