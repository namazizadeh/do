# -*- coding: utf-8 -*-
#
import time
from hashlib import md5
from threading import Thread
from collections import defaultdict
from itertools import chain

from django.db.models.signals import m2m_changed
from django.utils.translation import ugettext_lazy as _
from django.core.cache import cache
from django.http import JsonResponse
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.settings import api_settings
from common.exceptions import JMSException

from common.drf.filters import IDSpmFilter, CustomFilter, IDInFilter
from ..utils import lazyproperty

__all__ = [
    'JSONResponseMixin', 'CommonApiMixin', 'AsyncApiMixin', 'RelationMixin',
    'SerializerMixin2', 'QuerySetMixin', 'ExtraFilterFieldsMixin'
]


class JSONResponseMixin(object):
    """JSON mixin"""
    @staticmethod
    def render_json_response(context):
        return JsonResponse(context)


class GenericSerializerMixin:
    serializer_classes = None

    def get_serializer_class_by_view_action(self):
        if not hasattr(self, 'serializer_classes'):
            return None
        if not isinstance(self.serializer_classes, dict):
            return None
        draw = self.request.query_params.get('draw')
        serializer_class = None
        if draw and self.action in ['list', 'metadata']:
            serializer_class = self.serializer_classes.get('display')
        if serializer_class is None:
            serializer_class = self.serializer_classes.get(self.action)
        if serializer_class is None:
            serializer_class = self.serializer_classes.get('default')
        return serializer_class

    def get_serializer_class(self):
        serializer_class = self.get_serializer_class_by_view_action()
        if serializer_class is None:
            serializer_class = super().get_serializer_class()
        return serializer_class


class JSONFieldsModelSerializerMixin:
    """
    作用: 获取包含 JSONField 字段的序列类

    class TestSerializer(serializers.Serializer):
        pass

    json_fields_category_mapping = {
        'json_field_1': {
            'type': ('apply_asset', 'apply_application', 'login_confirm', ),
        },
        'json_field_2': {
            'type': ('chrome', 'mysql', 'oracle', 'k8s', ),
            'category': ('remote_app', 'db', 'cloud', ),
        },
    }
    json_fields_serializer_classes = {
        'json_field_1': {
            'type': {
                'apply_asset': {
                    'get': TestSerializer,
                    'post': TestSerializer,
                    'open':TestSerializer,
                    'approve': TestSerializer,
                },
                'apply_application': {
                    'get': TestSerializer,
                    'post': TestSerializer,
                    'put': TestSerializer,
                },
                'login_confirm': {
                    'get': TestSerializer,
                    'post': TestSerializer,
                    'put': TestSerializer,
                }
            },
            'category': {}
        },
        'json_field_2': {},
        'json_field_3': {}
    }
    """

    json_fields_category_mapping = {}
    json_fields_serializer_classes = None

    # 保存当前处理的JSONField名称
    __field = None
    serializer_class = None

    def get_json_field_query_category(self, category):
        query_category = self.request.query_params.get(category)
        category_choices = self.json_fields_category_mapping[self.__field][category]
        if query_category and query_category not in category_choices:
            error = _(
                'Please bring the query parameter `{}`, '
                'the value is selected from the following options: {}'
                ''.format(query_category, category_choices)
            )
            raise JMSException({'query_params_error': error})
        return query_category

    def get_json_field_action_serializer_classes_by_query_category(self):
        action_serializer_classes = None
        category_collection = self.json_fields_category_mapping[self.__field]
        for category in category_collection:
            category_value = self.get_json_field_query_category(category)
            if not category_value:
                continue
            category_serializer_classes = self.json_fields_serializer_classes[self.__field][category]
            action_serializer_classes = category_serializer_classes.get(category_value)
            if action_serializer_classes:
                break
        return action_serializer_classes

    def get_json_field_action_serializer_classes(self):
        category_collection = self.json_fields_category_mapping[self.__field]
        if category_collection:
            serializer_classes = self.get_json_field_action_serializer_classes_by_query_category()
        else:
            serializer_classes = self.json_fields_serializer_classes[self.__field]
        return serializer_classes

    def get_json_field_serializer_class_by_action(self, serializer_classes):
        if serializer_classes is None:
            return None
        if self.action in ['metadata']:
            action = self.request.query_params.get('action')
            if not action:
                raise JMSException('The `metadata` methods must carry query parameter `action`')
        else:
            action = self.action
        serializer_class = serializer_classes.get(action)
        return serializer_class

    @lazyproperty
    def default_json_field_serializer_class(self):
        readonly_json_field_serializer_class = type(
            'DefaultReadonlyJSONFieldSerializer', (serializers.JSONField,),
        )
        return readonly_json_field_serializer_class

    def get_json_field_serializer(self):
        serializer_classes = self.get_json_field_action_serializer_classes()
        serializer_class = self.get_json_field_serializer_class_by_action(serializer_classes)
        if serializer_class:
            serializer = serializer_class()
            return serializer
        serializer_class = serializer_classes.get('default')
        if serializer_class:
            serializer = serializer_class(**{'read_only': True})
            return serializer
        return self.default_json_field_serializer_class(**{'read_only': True})

    def get_json_fields_serializer_mapping(self):
        """
        return: {
            'json_field_1': serializer1(),
            'json_field_2': serializer2(),
        }
        """
        fields_serializer_mapping = {}
        fields = self.json_fields_serializer_classes.keys()
        for field in fields:
            self.__field = field
            serializer = self.get_json_field_serializer()
            fields_serializer_mapping[self.__field] = serializer
        return fields_serializer_mapping

    def build_include_json_fields_serializer_class(self, base, attrs):
        serializer_class_name = ''.join([
            field_serializer.__class__.__name__ for field_serializer in attrs.values()
        ])
        serializer_class = type(serializer_class_name, (base,), attrs)
        return serializer_class

    def get_serializer_class(self):
        serializer_class = super().get_serializer_class()
        if not isinstance(self.json_fields_serializer_classes, dict):
            return serializer_class
        fields_serializer_mapping = self.get_json_fields_serializer_mapping()
        if not fields_serializer_mapping:
            return serializer_class
        serializer_class = self.build_include_json_fields_serializer_class(
            base=serializer_class, attrs=fields_serializer_mapping
        )
        return serializer_class


class SerializerMixin(JSONFieldsModelSerializerMixin, GenericSerializerMixin):
    pass


class ExtraFilterFieldsMixin:
    """
    额外的 api filter
    """
    default_added_filters = [CustomFilter, IDSpmFilter, IDInFilter]
    filter_backends = api_settings.DEFAULT_FILTER_BACKENDS
    extra_filter_fields = []
    extra_filter_backends = []

    def get_filter_backends(self):
        if self.filter_backends != self.__class__.filter_backends:
            return self.filter_backends
        backends = list(chain(
            self.filter_backends,
            self.default_added_filters,
            self.extra_filter_backends))
        return backends

    def filter_queryset(self, queryset):
        for backend in self.get_filter_backends():
            queryset = backend().filter_queryset(self.request, queryset, self)
        return queryset


class PaginatedResponseMixin:
    def get_paginated_response_with_query_set(self, queryset):
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


class CommonApiMixin(SerializerMixin, ExtraFilterFieldsMixin):
    pass


class InterceptMixin:
    """
    Hack默认的dispatch, 让用户可以实现 self.do
    """
    def dispatch(self, request, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        request = self.initialize_request(request, *args, **kwargs)
        self.request = request
        self.headers = self.default_response_headers  # deprecate?

        try:
            self.initial(request, *args, **kwargs)

            # Get the appropriate handler method
            if request.method.lower() in self.http_method_names:
                handler = getattr(self, request.method.lower(),
                                  self.http_method_not_allowed)
            else:
                handler = self.http_method_not_allowed

            response = self.do(handler, request, *args, **kwargs)

        except Exception as exc:
            response = self.handle_exception(exc)

        self.response = self.finalize_response(request, response, *args, **kwargs)
        return self.response


class AsyncApiMixin(InterceptMixin):
    def get_request_user_id(self):
        user = self.request.user
        if hasattr(user, 'id'):
            return str(user.id)
        return ''

    @lazyproperty
    def async_cache_key(self):
        method = self.request.method
        path = self.get_request_md5()
        user = self.get_request_user_id()
        key = '{}_{}_{}'.format(method, path, user)
        return key

    def get_request_md5(self):
        path = self.request.path
        query = {k: v for k, v in self.request.GET.items()}
        query.pop("_", None)
        query.pop('refresh', None)
        query = "&".join(["{}={}".format(k, v) for k, v in query.items()])
        full_path = "{}?{}".format(path, query)
        return md5(full_path.encode()).hexdigest()

    @lazyproperty
    def initial_data(self):
        data = {
            "status": "running",
            "start_time": time.time(),
            "key": self.async_cache_key,
        }
        return data

    def get_cache_data(self):
        key = self.async_cache_key
        if self.is_need_refresh():
            cache.delete(key)
            return None
        data = cache.get(key)
        return data

    def do(self, handler, *args, **kwargs):
        if not self.is_need_async():
            return handler(*args, **kwargs)
        resp = self.do_async(handler, *args, **kwargs)
        return resp

    def is_need_refresh(self):
        if self.request.GET.get("refresh"):
            return True
        return False

    def is_need_async(self):
        return False

    def do_async(self, handler, *args, **kwargs):
        data = self.get_cache_data()
        if not data:
            t = Thread(
                target=self.do_in_thread,
                args=(handler, *args),
                kwargs=kwargs
            )
            t.start()
            resp = Response(self.initial_data)
            return resp
        status = data.get("status")
        resp = data.get("resp")
        if status == "ok" and resp:
            resp = Response(**resp)
        else:
            resp = Response(data)
        return resp

    def do_in_thread(self, handler, *args, **kwargs):
        key = self.async_cache_key
        data = self.initial_data
        cache.set(key, data, 600)
        try:
            response = handler(*args, **kwargs)
            data["status"] = "ok"
            data["resp"] = {
                "data": response.data,
                "status": response.status_code
            }
            cache.set(key, data, 600)
        except Exception as e:
            data["error"] = str(e)
            data["status"] = "error"
            cache.set(key, data, 600)


class RelationMixin:
    m2m_field = None
    from_field = None
    to_field = None
    to_model = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        assert self.m2m_field is not None, '''
        `m2m_field` should not be `None`
        '''

        self.from_field = self.m2m_field.m2m_field_name()
        self.to_field = self.m2m_field.m2m_reverse_field_name()
        self.to_model = self.m2m_field.related_model
        self.through = getattr(self.m2m_field.model, self.m2m_field.attname).through

    def get_queryset(self):
        # 注意，此处拦截了 `get_queryset` 没有 `super`
        queryset = self.through.objects.all()
        return queryset

    def send_m2m_changed_signal(self, instances, action):
        if not isinstance(instances, list):
            instances = [instances]

        from_to_mapper = defaultdict(list)

        for i in instances:
            to_id = getattr(i, self.to_field).id
            # TODO 优化，不应该每次都查询数据库
            from_obj = getattr(i, self.from_field)
            from_to_mapper[from_obj].append(to_id)

        for from_obj, to_ids in from_to_mapper.items():
            m2m_changed.send(
                sender=self.through, instance=from_obj, action=action,
                reverse=False, model=self.to_model, pk_set=to_ids
            )

    def perform_create(self, serializer):
        instance = serializer.save()
        self.send_m2m_changed_signal(instance, 'post_add')

    def perform_destroy(self, instance):
        instance.delete()
        self.send_m2m_changed_signal(instance, 'post_remove')


class SerializerMixin2:
    serializer_classes = {}

    def get_serializer_class(self):
        if self.serializer_classes:
            serializer_class = self.serializer_classes.get(
                self.action, self.serializer_classes.get('default')
            )

            if isinstance(serializer_class, dict):
                serializer_class = serializer_class.get(
                    self.request.method.lower, serializer_class.get('default')
                )

            assert serializer_class, '`serializer_classes` config error'
            return serializer_class
        return super().get_serializer_class()


class QuerySetMixin:
    def get_queryset(self):
        queryset = super().get_queryset()
        serializer_class = self.get_serializer_class()
        if serializer_class and hasattr(serializer_class, 'setup_eager_loading'):
            queryset = serializer_class.setup_eager_loading(queryset)

        return queryset


class AllowBulkDestoryMixin:
    def allow_bulk_destroy(self, qs, filtered):
        """
        我们规定，批量删除的情况必须用 `id` 指定要删除的数据。
        """
        query = str(filtered.query)
        return '`id` IN (' in query or '`id` =' in query
