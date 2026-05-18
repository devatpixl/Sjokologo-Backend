from rest_framework import serializers
from .models import Coupon


class CouponAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Coupon
        fields = [
            'id', 'code', 'kind', 'value', 'min_subtotal',
            'valid_from', 'valid_to', 'max_uses', 'times_used',
            'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = ['times_used', 'created_at', 'updated_at']

    def validate_code(self, value):
        return value.strip().upper()

    def validate(self, attrs):
        kind = attrs.get('kind') or getattr(self.instance, 'kind', None)
        value = attrs.get('value')
        if kind == Coupon.KIND_PERCENT and value is not None and not (0 <= value <= 100):
            raise serializers.ValidationError({'value': 'Prosent må være mellom 0 og 100.'})
        if kind == Coupon.KIND_FIXED and value is not None and value < 0:
            raise serializers.ValidationError({'value': 'Beløp kan ikke være negativt.'})
        return attrs


class CouponValidateRequestSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=40)
    subtotal = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0)
