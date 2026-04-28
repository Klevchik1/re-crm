"""URL-маршруты приложения ``key``."""
from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView

from . import views

router = DefaultRouter()

# Справочники
router.register('operation-types', views.OperationTypeViewSet)
router.register('property-statuses', views.PropertyStatusViewSet)
router.register('request-statuses', views.RequestStatusViewSet)
router.register('deal-statuses', views.DealStatusViewSet)
router.register('task-statuses', views.TaskStatusViewSet)
router.register('user-roles', views.UserRoleViewSet)

# Адреса
router.register('cities', views.CityViewSet)
router.register('streets', views.StreetViewSet)
router.register('houses', views.HouseViewSet)
router.register('addresses', views.AddressViewSet)

# Пользователи
router.register('users', views.UserViewSet)
router.register('employee-profiles', views.EmployeeProfileViewSet)
router.register('client-profiles', views.ClientProfileViewSet)

# Недвижимость
router.register('properties', views.PropertyViewSet)
router.register('property-features', views.PropertyFeatureViewSet)
router.register('property-photos', views.PropertyPhotoViewSet)
router.register('property-documents', views.PropertyDocumentViewSet)

# Бизнес-процессы
router.register('requests', views.RequestViewSet)
router.register('request-matches', views.RequestPropertyMatchViewSet,
                basename='request-matches')
router.register('deals', views.DealViewSet)
router.register('viewings', views.PropertyViewingViewSet)
router.register('tasks', views.TaskViewSet)
router.register('outgoing-emails', views.OutgoingEmailViewSet)

urlpatterns = [
    # Аутентификация (JWT)
    path('auth/register/', views.RegisterView.as_view(), name='register'),
    path('auth/login/', views.LoginView.as_view(), name='login'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('auth/verify/', TokenVerifyView.as_view(), name='token_verify'),
    path('auth/me/', views.MeView.as_view(), name='me'),

    # Подсказки адресов DaData
    path('dadata/suggest-address/',
         views.DadataSuggestAddressView.as_view(),
         name='dadata_suggest_address'),

    # Парсер realty.yandex.ru — автозаполнение карточки объекта.
    # Защищён правами IsEmployee (см. YandexRealtySearchView).
    path('yandex-realty/search/',
         views.YandexRealtySearchView.as_view(),
         name='yandex_realty_search'),
    path('yandex-realty/import/',
         views.YandexRealtyImportView.as_view(),
         name='yandex_realty_import'),

    # Сводка для дашборда
    path('dashboard/stats/', views.DashboardStatsView.as_view(),
         name='dashboard_stats'),

    path('', include(router.urls)),
]
