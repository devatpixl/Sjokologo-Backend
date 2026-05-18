from rest_framework import serializers
from .models import BundleRule


class BundleRulePublicSerializer(serializers.ModelSerializer):
    """Storefront-facing view: just enough for the cart to render badges and
    re-compute totals. Hides internal fields like created_at."""
    class Meta:
        model = BundleRule
        fields = [
            'id', 'name', 'description',
            'variant_group', 'products',
            'required_quantity', 'bundle_price',
            'includes_free_shipping',
        ]


class BundleRuleAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = BundleRule
        fields = [
            'id', 'name', 'description',
            'variant_group', 'products',
            'required_quantity', 'bundle_price',
            'includes_free_shipping', 'is_active',
            'valid_from', 'valid_to',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']
