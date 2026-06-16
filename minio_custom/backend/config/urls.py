from django.contrib import admin
from django.urls import include, path

from storage_api.views import (
    CookieTokenLogoutView,
    CookieTokenObtainPairView,
    CookieTokenRefreshView,
    RegisterView,
)


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/register/", RegisterView.as_view(), name="register"),
    path("api/auth/token/", CookieTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", CookieTokenRefreshView.as_view(), name="token_refresh"),
    path("api/auth/logout/", CookieTokenLogoutView.as_view(), name="token_logout"),
    path("api/", include("storage_api.urls")),
]
