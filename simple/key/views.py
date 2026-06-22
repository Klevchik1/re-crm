"""
REST-представления приложения ``key``.

Архитектура: ViewSet-ы для CRUD + отдельные APIView для аутентификации
и интеграции с DaData (подсказки адресов).
"""
from django.contrib.auth import get_user_model, login as auth_login
from django.db.models import Count, Sum, Q
from django.utils import timezone
from rest_framework import status, viewsets, filters
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken

from django.http import FileResponse, Http404, HttpResponseRedirect, HttpResponseForbidden

from . import business_rules, models, serializers
from .business_rules import WorkloadLimitExceeded
from .dadata import DadataClient
from .deals_service import create_deal_from_request
from .mailing import (
    resend as resend_email,
    enqueue_request_closed,
    enqueue_task_assigned,
)
from .permissions import (
    IsAdminOrManager,
    IsEmployee,
    IsEmployeeOrReadOnly,
    IsAdminOrManagerOrReadOnly,
    IsOwnClientProfileOrEmployee,
)

User = get_user_model()


# ====== Аутентификация =====================================================

class RegisterView(APIView):
    """
    Регистрация нового пользователя.

    Принимаются только ``username``, ``email``, ``phone`` и ``password``.
    Тип пользователя всегда ``client``, должность не назначается —
    это делает администратор или менеджер агентства через отдельный
    эндпоинт ``/users/{id}/assign_role/``.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = serializers.RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(serializers.UserSerializer(user).data,
                        status=status.HTTP_201_CREATED)


class LoginView(TokenObtainPairView):
    """Получение пары токенов ``access`` / ``refresh``."""
    permission_classes = [AllowAny]


class MeView(APIView):
    """Информация о текущем пользователе."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(serializers.UserSerializer(request.user).data)


# ====== Справочники =========================================================

class OperationTypeViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = models.OperationType.objects.all()
    serializer_class = serializers.OperationTypeSerializer
    permission_classes = [IsAuthenticated]


class PropertyStatusViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = models.PropertyStatus.objects.all()
    serializer_class = serializers.PropertyStatusSerializer
    permission_classes = [IsAuthenticated]


class RequestStatusViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = models.RequestStatus.objects.all()
    serializer_class = serializers.RequestStatusSerializer
    permission_classes = [IsAuthenticated]


class DealStatusViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = models.DealStatus.objects.all()
    serializer_class = serializers.DealStatusSerializer
    permission_classes = [IsAuthenticated]


class TaskStatusViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = models.TaskStatus.objects.all()
    serializer_class = serializers.TaskStatusSerializer
    permission_classes = [IsAuthenticated]


class UserRoleViewSet(viewsets.ModelViewSet):
    """
    Справочник должностей сотрудников.

    Чтение доступно любому авторизованному пользователю (нужен для
    выпадающих списков). Создание, редактирование и удаление — только
    администратору и менеджеру через админ-панель.
    """
    queryset = models.UserRole.objects.all()
    serializer_class = serializers.UserRoleSerializer
    permission_classes = [IsAdminOrManagerOrReadOnly]


# ====== Адресная иерархия ==================================================

class CityViewSet(viewsets.ModelViewSet):
    queryset = models.City.objects.all()
    serializer_class = serializers.CitySerializer
    permission_classes = [IsAdminOrManagerOrReadOnly]
    filter_backends = [filters.SearchFilter]
    search_fields = ['name', 'region']


class StreetViewSet(viewsets.ModelViewSet):
    queryset = models.Street.objects.select_related('city').all()
    serializer_class = serializers.StreetSerializer
    permission_classes = [IsAdminOrManagerOrReadOnly]
    filter_backends = [filters.SearchFilter]
    search_fields = ['name']

    def get_queryset(self):
        qs = super().get_queryset()
        city_id = self.request.query_params.get('city')
        if city_id:
            qs = qs.filter(city_id=city_id)
        return qs


class HouseViewSet(viewsets.ModelViewSet):
    queryset = models.House.objects.select_related('street').all()
    serializer_class = serializers.HouseSerializer
    permission_classes = [IsAdminOrManagerOrReadOnly]

    def get_queryset(self):
        qs = super().get_queryset()
        street_id = self.request.query_params.get('street')
        if street_id:
            qs = qs.filter(street_id=street_id)
        return qs


class AddressViewSet(viewsets.ModelViewSet):
    queryset = models.Address.objects.select_related(
        'house__street__city').all()
    serializer_class = serializers.AddressSerializer
    permission_classes = [IsEmployeeOrReadOnly]


# ====== Подсказки адресов (прокси к DaData) ================================

class DadataSuggestAddressView(APIView):
    """
    Прокси-эндпоинт подсказок адресов DaData.

    Ключ к DaData хранится только в настройках сервера и никогда не
    передаётся в браузер. Принимает ``GET ?q=...`` и возвращает массив
    нормализованных подсказок.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        query = request.query_params.get('q', '').strip()
        if not query or len(query) < 2:
            return Response({'results': []})
        try:
            count = int(request.query_params.get('count', 10))
        except ValueError:
            count = 10
        try:
            client = DadataClient()
            results = client.suggest_address(query, count=count)
        except Exception as exc:  # pragma: no cover
            return Response(
                {'detail': 'Сервис подсказок адресов временно недоступен.',
                 'error': str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response({'results': results})


# ====== Пользователи и профили ============================================

class UserViewSet(viewsets.ModelViewSet):
    """
    Управление пользователями.

    Просмотр списка доступен сотрудникам. Назначение роли/типа —
    только администратору и менеджеру.
    """
    queryset = User.objects.select_related('role').all()
    serializer_class = serializers.UserSerializer
    permission_classes = [IsEmployee]
    filter_backends = [filters.SearchFilter]
    search_fields = ['username', 'email', 'phone']

    def get_queryset(self):
        qs = super().get_queryset()
        user_type = self.request.query_params.get('user_type')
        if user_type:
            qs = qs.filter(user_type=user_type)
        role_code = self.request.query_params.get('role')
        if role_code:
            qs = qs.filter(role__code=role_code)
        return qs

    def get_permissions(self):
        if self.action in {'create', 'update', 'partial_update',
                           'destroy', 'assign_role'}:
            return [IsAdminOrManager()]
        return super().get_permissions()

    @action(detail=True, methods=['post'], url_path='assign_role')
    def assign_role(self, request, pk=None):
        """
        Назначить пользователю тип учётной записи и должность.

        Доступно только администратору или менеджеру. Принимает
        поля ``user_type``, ``role_id`` и/или ``is_active``.
        """
        target = self.get_object()
        serializer = serializers.UserRoleAssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if 'user_type' in data:
            target.user_type = data['user_type']
        if 'role' in data:
            target.role = data['role']
        if 'is_active' in data:
            target.is_active = data['is_active']
        target.save()
        return Response(serializers.UserSerializer(target).data)

    @action(detail=False, methods=['get'], url_path='me/workload',
            permission_classes=[IsAuthenticated])
    def my_workload(self, request):
        """
        Срез текущей загрузки сотрудника: сколько задач/заявок
        сейчас в работе и каковы лимиты. Используется виджетом в TopBar
        и формами назначения, чтобы заранее показывать «лимит исчерпан».
        """
        if not request.user.is_employee:
            return Response({
                'active_tasks': 0,
                'in_progress_tasks': 0,
                'active_requests': 0,
                'max_active_tasks': business_rules.MAX_ACTIVE_TASKS,
                'max_in_progress_tasks':
                    business_rules.MAX_IN_PROGRESS_TASKS,
                'max_active_requests':
                    business_rules.MAX_ACTIVE_REQUESTS,
                'can_take_request': False,
                'can_take_task': False,
                'can_start_task': False,
            })
        return Response(business_rules.snapshot_for(request.user).as_dict())

    @action(detail=True, methods=['get'], url_path='workload',
            permission_classes=[IsAdminOrManager])
    def user_workload(self, request, pk=None):
        """Нагрузка конкретного сотрудника — только для менеджеров/админов."""
        target = self.get_object()
        if not target.is_employee:
            return Response(
                {'detail': 'Учитывается только загрузка сотрудников.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(business_rules.snapshot_for(target).as_dict())


class EmployeeProfileViewSet(viewsets.ModelViewSet):
    queryset = models.EmployeeProfile.objects.select_related('user').all()
    serializer_class = serializers.EmployeeProfileSerializer
    permission_classes = [IsEmployee]


class ClientProfileViewSet(viewsets.ModelViewSet):
    queryset = models.ClientProfile.objects.select_related('user').all()
    serializer_class = serializers.ClientProfileSerializer
    # Клиент должен иметь возможность сам дозаполнить паспорт/адреса
    # перед подписанием договора, поэтому используем правило, которое
    # явно разрешает редактирование собственного профиля.
    permission_classes = [IsOwnClientProfileOrEmployee]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.is_authenticated and user.is_client:
            qs = qs.filter(user=user)
        return qs


# ====== Объекты недвижимости ==============================================

class PropertyViewSet(viewsets.ModelViewSet):
    queryset = models.Property.objects.select_related(
        'operation_type', 'status', 'address__house__street__city'
    ).prefetch_related('photos', 'feature_values__feature').all()
    serializer_class = serializers.PropertySerializer
    permission_classes = [IsEmployeeOrReadOnly]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['title', 'description']
    ordering_fields = ['price', 'created_at', 'area_total']

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params

        if params.get('operation_type'):
            qs = qs.filter(operation_type_id=params['operation_type'])
        if params.get('status'):
            qs = qs.filter(status_id=params['status'])
        if params.get('rooms'):
            qs = qs.filter(rooms_count=params['rooms'])
        if params.get('min_price'):
            qs = qs.filter(price__gte=params['min_price'])
        if params.get('max_price'):
            qs = qs.filter(price__lte=params['max_price'])

        return qs

    @action(detail=True, methods=['post'], url_path='change_status')
    def change_status(self, request, pk=None):
        """Смена статуса объекта с записью в историю."""
        property_obj = self.get_object()
        new_status_id = request.data.get('status_id')
        if not new_status_id:
            return Response({'detail': 'Не указан статус.'},
                            status=status.HTTP_400_BAD_REQUEST)
        property_obj.status_id = new_status_id
        property_obj.save()
        models.PropertyStatusHistory.objects.create(
            property=property_obj,
            status_id=new_status_id,
            changed_by=request.user,
        )
        return Response(serializers.PropertySerializer(
            property_obj, context={'request': request}).data)

    @action(detail=True, methods=['get'])
    def history(self, request, pk=None):
        """История смен статусов объекта."""
        property_obj = self.get_object()
        qs = property_obj.status_history.select_related('status', 'changed_by')
        return Response(
            serializers.PropertyStatusHistorySerializer(qs, many=True).data
        )

    @action(
        detail=True,
        methods=['post'],
        url_path='upload_photo',
        parser_classes=[MultiPartParser, FormParser, JSONParser],
        permission_classes=[IsEmployee],
    )
    def upload_photo(self, request, pk=None):
        """
        Загрузить фото объекта.

        Принимает либо файл в поле ``image`` (multipart/form-data),
        либо внешний URL в поле ``url`` (application/json).
        """
        property_obj = self.get_object()
        image = request.FILES.get('image')
        url = request.data.get('url')
        if not image and not url:
            return Response(
                {'detail': 'Нужно передать файл image или ссылку url.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Если это самое первое фото — сразу делаем его обложкой.
        is_first = not property_obj.photos.exists()
        photo = models.PropertyPhoto.objects.create(
            property=property_obj,
            image=image if image else None,
            url=url if not image else '',
            caption=request.data.get('caption', '') or '',
            is_cover=is_first,
            order=property_obj.photos.count(),
        )
        return Response(
            serializers.PropertyPhotoSerializer(
                photo, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )


class PropertyFeatureViewSet(viewsets.ModelViewSet):
    queryset = models.PropertyFeature.objects.all()
    serializer_class = serializers.PropertyFeatureSerializer
    permission_classes = [IsAdminOrManagerOrReadOnly]


class PropertyPhotoViewSet(viewsets.ModelViewSet):
    """
    Фото объекта. Поддерживает два формата загрузки:
      * multipart/form-data с полем ``image`` — файл;
      * application/json с полем ``url`` — внешняя ссылка.

    Для ручного управления альбомом добавлены действия:
      * ``set_cover``    — назначить обложкой;
      * ``toggle_hidden`` — скрыть/показать фото без удаления;
      * ``reorder``      — переставить порядок фото у объекта.
    """
    queryset = models.PropertyPhoto.objects.all()
    serializer_class = serializers.PropertyPhotoSerializer
    permission_classes = [IsEmployee]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        qs = super().get_queryset()
        prop = self.request.query_params.get('property')
        if prop:
            qs = qs.filter(property_id=prop)
        # По умолчанию клиентская часть может скрывать "скрытые" фото,
        # а сотрудники — видеть всё. Параметр show_hidden=0/1 управляется
        # фронтом и использует только значения 0/1.
        if self.request.query_params.get('show_hidden') == '0':
            qs = qs.filter(is_hidden=False)
        return qs

    @action(detail=True, methods=['post'], url_path='set_cover')
    def set_cover(self, request, pk=None):
        """Сделать выбранное фото обложкой объекта."""
        photo = self.get_object()
        # Снимаем флаг у всех остальных фото этого объекта
        # одним UPDATE и выставляем у выбранного.
        models.PropertyPhoto.objects.filter(
            property_id=photo.property_id
        ).exclude(pk=photo.pk).update(is_cover=False)
        photo.is_cover = True
        photo.is_hidden = False  # обложка не может быть скрытой
        photo.save(update_fields=['is_cover', 'is_hidden'])
        return Response(serializers.PropertyPhotoSerializer(
            photo, context={'request': request}).data)

    @action(detail=True, methods=['post'], url_path='toggle_hidden')
    def toggle_hidden(self, request, pk=None):
        """Скрыть/показать фото. Обложку скрыть нельзя."""
        photo = self.get_object()
        if photo.is_cover and not photo.is_hidden:
            return Response(
                {'detail': 'Нельзя скрыть фото-обложку. '
                           'Сначала назначьте обложкой другое фото.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        photo.is_hidden = not photo.is_hidden
        photo.save(update_fields=['is_hidden'])
        return Response(serializers.PropertyPhotoSerializer(
            photo, context={'request': request}).data)

    @action(detail=False, methods=['post'], url_path='reorder')
    def reorder(self, request):
        """
        Массовая перестановка порядка. Тело: ``{"order": [id1, id2, ...]}``.
        Все фото должны принадлежать одному объекту.
        """
        order = request.data.get('order') or []
        if not isinstance(order, list) or not order:
            return Response({'detail': 'Нужно поле order: [id,...]'},
                            status=status.HTTP_400_BAD_REQUEST)
        photos = list(models.PropertyPhoto.objects.filter(pk__in=order))
        if len({p.property_id for p in photos}) > 1:
            return Response({'detail': 'Фото разных объектов.'},
                            status=status.HTTP_400_BAD_REQUEST)
        by_id = {p.pk: p for p in photos}
        for idx, pid in enumerate(order):
            p = by_id.get(pid)
            if p is None:
                continue
            if p.order != idx:
                p.order = idx
                p.save(update_fields=['order'])
        return Response({'detail': 'Порядок обновлён.'})


class PropertyDocumentViewSet(viewsets.ModelViewSet):
    queryset = models.PropertyDocument.objects.select_related('verified_by').all()
    serializer_class = serializers.PropertyDocumentSerializer
    permission_classes = [IsEmployee]

    @action(detail=True, methods=['post'])
    def verify(self, request, pk=None):
        """Отметить документ как проверенный."""
        doc = self.get_object()
        doc.is_verified = True
        doc.verified_by = request.user
        doc.verified_at = timezone.now()
        doc.save()
        return Response(serializers.PropertyDocumentSerializer(doc).data)


# ====== Заявки, сделки, просмотры, задачи =================================

class RequestViewSet(viewsets.ModelViewSet):
    """
    Заявки клиентов.

    Правила доступа:
      * клиент видит и создаёт только свои заявки; закрыть может только
        свою и только в неоконечном статусе;
      * сотрудник видит все заявки. Может взять в работу неназначенную
        заявку (``POST /requests/{id}/take/``), прикрепить объект
        (``POST /requests/{id}/attach_property/``) и закрыть любую.
    """
    queryset = models.Request.objects.select_related(
        'client', 'agent', 'operation_type', 'status', 'property',
    ).prefetch_related('matches__property', 'matches__agent').all()
    serializer_class = serializers.RequestSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['created_at', 'updated_at']

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.is_authenticated and user.is_client:
            qs = qs.filter(client=user)

        params = self.request.query_params
        if params.get('status'):
            qs = qs.filter(status_id=params['status'])
        if params.get('status_code'):
            qs = qs.filter(status__code=params['status_code'])
        # «scope=unassigned» — заявки без агента (для вкладки сотрудника).
        scope = params.get('scope')
        if scope == 'unassigned' and user.is_employee:
            qs = qs.filter(agent__isnull=True)
        elif scope == 'mine' and user.is_employee:
            qs = qs.filter(agent=user)
        return qs

    def perform_create(self, serializer):
        """
        Автозаполнение при подаче заявки клиентом.

        Клиент не имеет права указывать ``client`` (подставляем его из
        запроса) и не может назначить себе агента.
        """
        user = self.request.user
        extra = {}
        if user.is_authenticated and user.is_client:
            extra['client'] = user
            extra['agent'] = None
        elif not serializer.validated_data.get('client'):
            raise ValidationError(
                {'client': 'Укажите клиента заявки.'}
            )
        serializer.save(**extra)

    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        """
        Закрыть заявку.

        Клиент может закрыть только свою заявку (отсечение происходит
        в ``get_queryset``). Повторное закрытие не допускается.

        Побочный эффект (сотрудник): если в заявке указан конкретный
        объект или в подборке есть подтверждённый вариант, автоматически
        создаётся сделка (см. :func:`key.deals_service.create_deal_from_request`)
        и генерируется PDF-договор со шрифтом DejaVuSans.
        """
        req = self.get_object()
        if req.status and req.status.code in {'closed', 'cancelled'}:
            return Response(
                {'detail': 'Заявка уже закрыта.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        closed = models.RequestStatus.objects.filter(code='closed').first()
        if closed:
            req.status = closed
        req.closed_at = timezone.now()
        req.save()

        # Автосоздание сделки и PDF-договора. Сам метод идемпотентен
        # (OneToOne на Deal.request — повторные вызовы не плодят дублей)
        # и бро��ает исключения только на ошибках БД, но не на «нет объекта».
        deal = create_deal_from_request(req, actor=request.user)
        enqueue_request_closed(request=req, actor=request.user, deal=deal)

        payload = serializers.RequestSerializer(req).data
        if deal is not None:
            payload['deal'] = serializers.DealSerializer(deal).data
        return Response(payload)

    @action(detail=True, methods=['post'])
    def take(self, request, pk=None):
        """
        Сотрудник берёт заявку в работу.

        Назначает себя агентом и переводит статус в «в обработке».
        Сигнал ``request_taken_create_task`` автоматически создаёт
        задачу «Связаться с клиентом».
        """
        if not request.user.is_employee:
            return Response(
                {'detail': 'Доступно только сотрудникам.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        req = self.get_object()
        if req.agent_id and req.agent_id != request.user.id:
            return Response(
                {'detail': 'Заявка уже взята другим сотрудником.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Лимит «один сотрудник — максимум 2 активные заявки».
        # Администраторы и менеджеры могут перераспределять нагрузку,
        # поэтому их не ограничиваем.
        if not request.user.is_admin_or_manager:
            try:
                business_rules.assert_can_take_request(
                    request.user, exclude_pk=req.pk,
                )
            except WorkloadLimitExceeded as exc:
                return Response(
                    {'detail': exc.detail, 'code': exc.code},
                    status=status.HTTP_409_CONFLICT,
                )
        req.agent = request.user
        processing = models.RequestStatus.objects.filter(
            code='processing').first()
        if processing:
            req.status = processing
        req.save()
        return Response(serializers.RequestSerializer(req).data)

    @action(detail=True, methods=['post'], url_path='attach_property')
    def attach_property(self, request, pk=None):
        """
        Добавить вариант объекта в подборку по заявке (только сотрудник).

        Ожидает ``property_id`` и опционально ``agent_note``.
        """
        if not request.user.is_employee:
            return Response(
                {'detail': 'Доступно только сотрудникам.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        req = self.get_object()
        property_id = request.data.get('property_id')
        if not property_id:
            return Response({'detail': 'Не указан объект.'},
                            status=status.HTTP_400_BAD_REQUEST)
        match, created = models.RequestPropertyMatch.objects.get_or_create(
            request=req, property_id=property_id,
            defaults={'agent': request.user,
                      'agent_note': request.data.get('agent_note', '')},
        )
        if not created:
            match.is_rejected = False
            match.is_offered = True
            if request.data.get('agent_note') is not None:
                match.agent_note = request.data['agent_note']
            match.save()
        return Response(
            serializers.RequestPropertyMatchSerializer(match).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @action(detail=True, methods=['post'], url_path='detach_property')
    def detach_property(self, request, pk=None):
        """Удалить вариант из подборки по заявке."""
        if not request.user.is_employee:
            return Response(
                {'detail': 'Доступно только сотрудникам.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        req = self.get_object()
        match_id = request.data.get('match_id')
        deleted, _ = req.matches.filter(pk=match_id).delete()
        if not deleted:
            return Response({'detail': 'Вариант не найден.'},
                            status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'], url_path='confirm_property')
    def confirm_property(self, request, pk=None):
        """
        Подтвердить вариант из подборки.

        Это действие:
        1. Помечает вариант как подтверждённый
        2. Автоматически закрывает задачи типа 'property_search' по заявке
        3. Создаёт исходящее письмо клиенту
        4. Записывает результат в статистику сотрудника
        """
        if not request.user.is_employee:
            return Response(
                {'detail': 'Доступно только сотрудникам.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        req = self.get_object()
        match_id = request.data.get('match_id')
        if not match_id:
            return Response({'detail': 'Не указан match_id.'},
                            status=status.HTTP_400_BAD_REQUEST)

        match = req.matches.filter(pk=match_id).first()
        if not match:
            return Response({'detail': 'Вариант не найден.'},
                            status=status.HTTP_404_NOT_FOUND)

        # Помечаем как предложенный/подтверждённый
        match.is_offered = True
        match.is_rejected = False
        match.save(update_fields=['is_offered', 'is_rejected'])

        # Отправляем сигнал для автозакрытия задач и со��дания письма
        from .signals import property_match_confirmed
        property_match_confirmed.send(
            sender=self.__class__,
            match=match,
            confirmed_by=request.user,
        )

        return Response({
            'detail': 'Вариант подтверждён. Задачи подбора закрыты, '
                      'письмо клиенту поставлено в очередь.',
            'match': serializers.RequestPropertyMatchSerializer(match).data,
        })

    @action(detail=True, methods=['post'], url_path='accept_match')
    def accept_match(self, request, pk=None):
        """
        Обратная совместимость для фронтенда.

        Старый клиент вызывает ``accept_match``, а бизнес-логика теперь
        живёт в ``confirm_property``. Держим алиас, чтобы убрать 404
        и не дублировать код.
        """
        return self.confirm_property(request, pk=pk)


class RequestPropertyMatchViewSet(viewsets.ReadOnlyModelViewSet):
    """Только чтение подборки; модификация — через действия RequestViewSet."""
    queryset = models.RequestPropertyMatch.objects.select_related(
        'property', 'agent', 'request'
    ).all()
    serializer_class = serializers.RequestPropertyMatchSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.is_authenticated and user.is_client:
            qs = qs.filter(request__client=user)
        request_id = self.request.query_params.get('request')
        if request_id:
            qs = qs.filter(request_id=request_id)
        return qs


class DealViewSet(viewsets.ModelViewSet):
    queryset = models.Deal.objects.select_related(
        'property', 'agent', 'client', 'operation_type', 'status'
    ).all()
    serializer_class = serializers.DealSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.is_authenticated and user.is_client:
            qs = qs.filter(client=user)
        return qs

    @action(detail=True, methods=['post'], url_path='change_status')
    def change_status(self, request, pk=None):
        """Смена статуса сделки (воронка продаж)."""
        deal = self.get_object()
        status_id = request.data.get('status_id')
        if not status_id:
            return Response({'detail': 'Не указан статус.'},
                            status=status.HTTP_400_BAD_REQUEST)
        deal.status_id = status_id
        deal.save()
        return Response(serializers.DealSerializer(deal).data)

    @action(detail=True, methods=['get'], url_path='contract')
    def contract(self, request, pk=None):
        """
        Скачать PDF-договор по сделке.

        Если файл ещё не сгенерирован (старые «ручные» сделки до
        внедрения автогенерации) — генерируем на лету и сохраняем.
        """
        deal = self.get_object()
        if not deal.contract_file:
            from .deals_service import _attach_contract
            _attach_contract(deal)
            deal.refresh_from_db()
        if not deal.contract_file:
            raise Http404('Договор не удалось сформировать.')
        return FileResponse(
            deal.contract_file.open('rb'),
            as_attachment=True,
            filename=f'contract-{deal.deal_number}.pdf',
            content_type='application/pdf',
        )

    @action(detail=True, methods=['post'], url_path='regenerate_contract')
    def regenerate_contract(self, request, pk=None):
        """Перегенерировать PDF-договор (например, после правок сделки)."""
        if not request.user.is_employee:
            return Response(
                {'detail': 'Доступно только сотрудникам.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        deal = self.get_object()
        from .deals_service import _attach_contract
        # Удаляем старый файл, чтобы не захламлять media/.
        if deal.contract_file:
            deal.contract_file.delete(save=False)
            deal.contract_file = None
        _attach_contract(deal)
        deal.refresh_from_db()
        return Response(serializers.DealSerializer(deal).data)


class PropertyViewingViewSet(viewsets.ModelViewSet):
    queryset = models.PropertyViewing.objects.select_related(
        'property', 'client', 'agent'
    ).all()
    serializer_class = serializers.PropertyViewingSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.is_authenticated and user.is_client:
            qs = qs.filter(client=user)
        return qs


class TaskViewSet(viewsets.ModelViewSet):
    """
    Задачи сотрудников агентства.

    Сотрудник видит свои задачи и задачи, где он исполнитель.
    Администратор/менеджер — все. Клиенты доступа не имеют.
    """
    queryset = models.Task.objects.select_related(
        'status', 'assignee', 'created_by', 'client', 'property',
        'request', 'deal',
    ).all()
    serializer_class = serializers.TaskSerializer
    permission_classes = [IsEmployee]
    filter_backends = [filters.OrderingFilter, filters.SearchFilter]
    ordering_fields = ['due_date', 'created_at', 'priority']
    search_fields = ['title', 'description']

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        params = self.request.query_params
        if user.is_authenticated and not user.is_admin_or_manager:
            qs = qs.filter(Q(assignee=user) | Q(created_by=user))
        if params.get('status'):
            qs = qs.filter(status_id=params['status'])
        # Фильтр по коду статуса — фронтенду удобнее, чем pk из справочника.
        # Принимает одиночный код или список через запятую:
        # ?status_code=done или ?status_code=done,cancelled.
        if params.get('status_code'):
            codes = [c.strip() for c in params['status_code'].split(',')
                     if c.strip()]
            qs = qs.filter(status__code__in=codes)
        if params.get('assignee'):
            value = params['assignee']
            # Алиас «me» — удобен для страницы «Моя история».
            if value == 'me':
                qs = qs.filter(assignee=user)
            else:
                qs = qs.filter(assignee_id=value)
        if params.get('task_type'):
            qs = qs.filter(task_type=params['task_type'])
        if params.get('request'):
            qs = qs.filter(request_id=params['request'])
        # Интервал по дате завершения — для вкладки «История».
        if params.get('completed_after'):
            qs = qs.filter(completed_at__gte=params['completed_after'])
        if params.get('completed_before'):
            qs = qs.filter(completed_at__lte=params['completed_before'])
        return qs

    def perform_create(self, serializer):
        # При создании задачи проверяем лимит активных задач у исполнителя.
        # Менеджер может «перегрузить» сотрудника только через отдельную
        # проверку is_admin_or_manager ниже — обычные сотрудники себя
        # лимитируют.
        assignee = serializer.validated_data.get('assignee')
        if assignee and not self.request.user.is_admin_or_manager:
            try:
                business_rules.assert_can_assign_task(assignee)
            except WorkloadLimitExceeded as exc:
                raise ValidationError({'assignee': [exc.detail]})
        task = serializer.save(created_by=self.request.user)
        enqueue_task_assigned(task=task)

    @action(detail=True, methods=['post'], url_path='change_status')
    def change_status(self, request, pk=None):
        """Смена статуса задачи."""
        task = self.get_object()
        status_id = request.data.get('status_id')
        if not status_id:
            return Response({'detail': 'Не указан статус.'},
                            status=status.HTTP_400_BAD_REQUEST)
        new_status = models.TaskStatus.objects.filter(pk=status_id).first()
        if not new_status:
            return Response({'detail': 'Неизвестный статус.'},
                            status=status.HTTP_400_BAD_REQUEST)
        # При переводе в ``in_progress`` — гарантируем,
        # что у исполнителя нет другой задачи в работе.
        if (new_status.code == 'in_progress'
                and task.assignee_id
                and not request.user.is_admin_or_manager):
            try:
                business_rules.assert_can_start_task(task.assignee, task)
            except WorkloadLimitExceeded as exc:
                return Response(
                    {'detail': exc.detail, 'code': exc.code},
                    status=status.HTTP_409_CONFLICT,
                )
        task.status = new_status
        # Если статус «выполнено» — проставим время завершения
        if new_status.code == 'done':
            task.completed_at = timezone.now()
        task.save()
        return Response(serializers.TaskSerializer(task).data)

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        """
        Перевести задачу в «В работе». Сотрудник может держать только
        одну активную задачу одновременно — соответствующий лимит
        проверяется бизнес-слоем.
        """
        task = self.get_object()
        if task.assignee_id != request.user.id \
                and not request.user.is_admin_or_manager:
            return Response(
                {'detail': 'Нельзя стартовать чужую задачу.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        in_progress = business_rules.status_by_code(
            models.TaskStatus, 'in_progress',
        )
        if not in_progress:
            return Response(
                {'detail': 'Справочник статусов не заполнен.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        try:
            business_rules.assert_can_start_task(task.assignee, task)
        except WorkloadLimitExceeded as exc:
            return Response(
                {'detail': exc.detail, 'code': exc.code},
                status=status.HTTP_409_CONFLICT,
            )
        task.status = in_progress
        task.save(update_fields=['status', 'updated_at'])
        return Response(serializers.TaskSerializer(task).data)

    @action(detail=True, methods=['post'])
    def pause(self, request, pk=None):
        """Поставить текущую задачу на паузу — перевод в «Ожидание»."""
        task = self.get_object()
        if task.assignee_id != request.user.id \
                and not request.user.is_admin_or_manager:
            return Response(
                {'detail': 'Нельзя приостанавливать чужую задачу.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        waiting = business_rules.status_by_code(
            models.TaskStatus, 'waiting',
        )
        if not waiting:
            return Response(
                {'detail': 'Справочник статусов не заполнен.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        task.status = waiting
        task.save(update_fields=['status', 'updated_at'])
        return Response(serializers.TaskSerializer(task).data)

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        """
        Отметка задачи как выполненной.

        Опционально принимает ``result`` — строку (текстовое резюме)
        или объект ``{summary, ...}`` (фронтенд TaskWorkflow шлёт dict
        с саммари и произвольной мета-информацией). Логика завершения
        вынесена в :mod:`key.task_actions` и идемпотентна — повторный
        клик не ломает статистику.
        """
        task = self.get_object()
        # Проверяем права: завершать может только сам исполнитель
        # или администрация агентства.
        if (task.assignee_id != request.user.id
                and not request.user.is_admin_or_manager):
            return Response(
                {'detail': 'Нельзя завершить чужую задачу.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        from . import task_actions
        task, changed = task_actions.complete_task(
            task,
            actor=request.user,
            result=request.data.get('result'),
        )
        if not changed:
            # Задача уже была в терминальном статусе — возвращаем
            # актуальный срез, но HTTP 200 (идемпотентность).
            return Response(serializers.TaskSerializer(task).data)
        return Response(serializers.TaskSerializer(task).data)

    @action(detail=True, methods=['post'], url_path='record_step')
    def record_step(self, request, pk=None):
        """
        Зафиксировать этап выполнения задачи (контакт, заявка, подбор).

        Вызывается из ``TaskWorkflow.vue`` после каждого нажатия
        «Позвонил» / «Написал» / «Не дозвонился» / «Подобрал объект»,
        а также при завершении этапа «Заявка» (создана или открыта).

        Тело запроса: ``{step: str, outcome?: str, note?: str}``.
        Список step'ов — см. docstring :func:`key.task_actions.record_step`.
        """
        task = self.get_object()
        if (task.assignee_id != request.user.id
                and not request.user.is_admin_or_manager):
            return Response(
                {'detail': 'Нельзя дописывать шаги чужой задачи.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        step = (request.data.get('step') or '').strip()
        if not step:
            return Response(
                {'detail': 'Поле step обязательно.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        from . import task_actions
        task = task_actions.record_step(
            task,
            step=step,
            outcome=request.data.get('outcome'),
            note=request.data.get('note'),
            actor=request.user,
        )
        return Response(serializers.TaskSerializer(task).data)

    @action(detail=False, methods=['get'])
    def current(self, request):
        """
        Текущая активная задача сотрудника (статус ``in_progress``).

        Возвращает либо одну задачу, либо ``null`` — чтобы виджет в TopBar
        мог отрендерить «у вас нет задачи в работе».
        """
        if not request.user.is_employee:
            return Response(None)
        task = models.Task.objects.select_related(
            'status', 'request', 'client', 'property',
        ).filter(
            assignee=request.user,
            status__code='in_progress',
        ).order_by('-updated_at').first()
        if task is None:
            return Response(None)
        return Response(serializers.TaskSerializer(task).data)


# ====== Исходящие письма ==================================================

class OutgoingEmailViewSet(viewsets.ModelViewSet):
    """
    Очередь исходящих писем.

    Только для сотрудник��в и администраторов. Позволяет просматривать
    очередь, повторно отправлять неудавшиеся письма.
    """
    queryset = models.OutgoingEmail.objects.select_related(
        'recipient', 'sender', 'task', 'request', 'property',
    ).all()
    serializer_class = serializers.OutgoingEmailSerializer
    permission_classes = [IsEmployee]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['created_at', 'sent_at']

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        if params.get('status'):
            qs = qs.filter(status=params['status'])
        if params.get('request'):
            qs = qs.filter(request_id=params['request'])
        return qs

    @action(detail=True, methods=['post'])
    def retry(self, request, pk=None):
        """Повторная попытка отправки неудавшегося письма."""
        email = self.get_object()
        if email.status != 'failed':
            return Response(
                {'detail': 'Можно повторить только неудавшиеся письма.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        resend_email(email)
        email.refresh_from_db()
        return Response(serializers.OutgoingEmailSerializer(email).data)


# ====== Авто-логин в Django Admin через JWT ================================

class AdminAutoLoginView(APIView):
    """
    Авторизация в Django Admin без повторного ввода пароля.

    Принимает GET-запрос с параметром ?token=<access_jwt>.
    Верифицирует токен, создаёт Django-сессию (session auth) для пользователя
    и перенаправляет на /admin/. Работает только если пользователь is_staff.
    Использование: фронтенд передаёт токен из localStorage и выполняет
    редирект на этот эндпоинт — Django сам выдаст session cookie.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        token_str = request.query_params.get('token', '').strip()
        if not token_str:
            return HttpResponseForbidden('Токен не передан.')
        try:
            token = AccessToken(token_str)
            user_id = token.get('user_id')
        except (TokenError, InvalidToken):
            return HttpResponseForbidden('Недействительный или просроченный токен.')

        try:
            user = get_user_model().objects.get(pk=user_id)
        except get_user_model().DoesNotExist:
            return HttpResponseForbidden('Пользователь не найден.')

        if not user.is_active:
            return HttpResponseForbidden('Аккаунт отключён.')

        # Доступ разрешён суперпользователям, is_staff и admin/manager-ролям.
        has_access = user.is_staff or user.is_superuser or user.is_admin_or_manager
        if not has_access:
            return HttpResponseForbidden(
                'Доступ в Django Admin разрешён только администраторам и менеджерам.'
            )

        # Django Admin требует is_staff=True. Если у пользователя с admin/manager
        # ролью этот флаг ещё не выставлен — выставляем автоматически.
        if not user.is_staff:
            user.is_staff = True
            user.save(update_fields=['is_staff'])

        # Логиним пользователя в Django-сессии — теперь браузер получит
        # session cookie и попадёт в /admin/ без формы входа.
        auth_login(request, user,
                   backend='django.contrib.auth.backends.ModelBackend')
        return HttpResponseRedirect('/admin/')


# ====== Сводка для главного экрана ========================================

class DashboardStatsView(APIView):
    """Агрегированные показатели учётной системы."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        data = {
            'properties_total': models.Property.objects.count(),
            'properties_active': models.Property.objects.filter(
                status__code='active').count(),
            'requests_open': models.Request.objects.filter(
                status__code='open').count(),
            'requests_total': models.Request.objects.count(),
            'deals_total': models.Deal.objects.count(),
            'deals_sum': models.Deal.objects.aggregate(
                total=Sum('price_final'))['total'] or 0,
            'clients_total': User.objects.filter(user_type='client').count(),
            'employees_total': User.objects.filter(user_type='employee').count(),
            'by_operation': list(
                models.Property.objects
                .values('operation_type__name')
                .annotate(total=Count('id'))
            ),
        }
        if user.is_authenticated and user.is_employee:
            open_tasks = models.Task.objects.exclude(
                status__code__in=['done', 'cancelled']
            )
            if not user.is_admin_or_manager:
                open_tasks = open_tasks.filter(assignee=user)
            data['tasks_open'] = open_tasks.count()
        return Response(data)
