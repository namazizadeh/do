from rest_framework import serializers
from django.utils.translation import gettext_lazy as _

from common.drf.fields import ChoiceDisplayField
from common.drf.serializers import JMSWritableNestedModelSerializer
from ..models import Platform, PlatformProtocol
from ..const import Category, AllTypes

__all__ = ['PlatformSerializer']


class PlatformProtocolsSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformProtocol
        fields = ['id', 'name', 'port', 'setting']


class PlatformSerializer(JMSWritableNestedModelSerializer):
    type = ChoiceDisplayField(choices=AllTypes.choices, label=_("Type"))
    category = ChoiceDisplayField(choices=Category.choices, label=_("Category"))
    protocols = PlatformProtocolsSerializer(label=_('Protocols'), many=True, required=False)
    type_constraints = serializers.ReadOnlyField(required=False, read_only=True)

    class Meta:
        model = Platform
        fields_mini = ['id', 'name', 'internal']
        fields_small = fields_mini + [
            'category', 'type',
        ]
        fields = fields_small + [
            'domain_enabled', 'domain_default',
            'su_enabled', 'su_method',
            'protocols_enabled', 'protocols',
            'ping_enabled', 'ping_method',
            'verify_account_enabled', 'verify_account_method',
            'create_account_enabled', 'create_account_method',
            'change_password_enabled', 'change_password_method',
            'type_constraints',
            'comment', 'charset',
        ]
        read_only_fields = [
            'category_display', 'type_display',
        ]


