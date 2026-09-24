from dataclasses import asdict

from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from ..domain.engine import Profile, normalize
from ..models import SensorProfile, StateRule
from ..selectors import compiled_registry


class StateRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = StateRule
        fields = ("id", "profile", "pattern", "is_regex", "state", "facet", "guarded", "priority")


class SensorProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = SensorProfile
        fields = (
            "id",
            "code",
            "name",
            "value_kind",
            "unit",
            "valid_min",
            "valid_max",
            "warn_threshold",
            "alarm_threshold",
            "direction",
            "sentinels",
            "expected_interval_s",
            "silence_factor",
            "description",
        )


class PreviewSerializer(serializers.Serializer):
    profile = serializers.CharField(required=False, allow_blank=True)
    value = serializers.CharField(allow_blank=True)


class SensorProfileViewSet(viewsets.ModelViewSet):
    queryset = SensorProfile.objects.all()
    serializer_class = SensorProfileSerializer
    search_fields = ("name", "code")

    @action(detail=False, methods=["post"], serializer_class=PreviewSerializer)
    def preview(self, request):
        """Проверить, как движок интерпретирует значение — для настройки профилей в админке."""
        data = PreviewSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        registry = compiled_registry()
        profile = registry.profiles.get(data.validated_data.get("profile") or "", Profile(code="default"))
        result = normalize(data.validated_data["value"], profile, registry.global_rules)
        return Response({**asdict(result), "is_alarming": result.is_alarming})


class StateRuleViewSet(viewsets.ModelViewSet):
    queryset = StateRule.objects.select_related("profile")
    serializer_class = StateRuleSerializer
    filterset_fields = ("profile", "state", "facet")
    search_fields = ("pattern",)
