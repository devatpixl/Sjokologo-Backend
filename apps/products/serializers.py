import json

from rest_framework import serializers
from .models import Product, Truffle


class FlavorLinesField(serializers.JSONField):
    """The smaksnoter lines shown on a product page.

    The admin product form is multipart because it carries the image, so a
    list of lines reaches DRF as the *string* ``'["A", "B"]'``. A plain
    JSONField accepts that string and stores it as a string, after which the
    storefront iterates it character by character and renders one chip per
    letter. Decode it here, and insist on a list of non-empty text lines so a
    malformed payload is a 400 rather than a broken product page.
    """

    def to_internal_value(self, data):
        if isinstance(data, str):
            text = data.strip()
            if not text:
                return []
            try:
                data = json.loads(text)
            except ValueError:
                raise serializers.ValidationError('Smaksnoter må være en gyldig JSON-liste.')

        if not isinstance(data, list):
            raise serializers.ValidationError('Smaksnoter må være en liste med linjer.')

        lines = []
        for item in data:
            if not isinstance(item, str):
                raise serializers.ValidationError('Hver smaksnote må være tekst.')
            item = item.strip()
            if item:
                lines.append(item)
        return lines


class ProductSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    flavors = FlavorLinesField(required=False)

    class Meta:
        model = Product
        fields = [
            'id', 'slug', 'name', 'category', 'size',
            'price', 'price_min', 'price_max',
            'image', 'image_url', 'flavors', 'blurb',
            'in_stock', 'is_active', 'variant_group', 'variant_label',
            'batch_number', 'batch_count', 'batch_total',
        ]
        extra_kwargs = {'image': {'write_only': True, 'required': False}}

    def get_image_url(self, obj):
        request = self.context.get('request')
        if obj.image and request:
            return request.build_absolute_uri(obj.image.url)
        return None


class TruffleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Truffle
        fields = ['id', 'name', 'color', 'note', 'is_active']
