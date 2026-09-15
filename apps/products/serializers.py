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

    def validate_price(self, value):
        """A visible product must be buyable.

        Nothing stopped a product being saved at 0 (or a negative price), and
        the shop only filters on in_stock — so it would appear for sale and
        then die at checkout on the "Ordresummen ble 0 kr" guard. Cheaper to
        refuse it here, while someone is looking at the form, than to let a
        customer discover it.
        """
        if value is None or value <= 0:
            raise serializers.ValidationError(
                'Prisen må være større enn 0. Et produkt med pris 0 vises i '
                'butikken, men kan ikke kjøpes.'
            )
        return value

    def validate(self, attrs):
        # Same reasoning for the optional range used by variant products.
        for field in ('price_min', 'price_max'):
            value = attrs.get(field)
            if value is not None and value <= 0:
                raise serializers.ValidationError(
                    {field: 'Må være større enn 0 hvis den er satt.'}
                )
        low, high = attrs.get('price_min'), attrs.get('price_max')
        if low is not None and high is not None and low > high:
            raise serializers.ValidationError(
                {'price_min': 'Kan ikke være høyere enn price_max.'}
            )
        return attrs

    def get_image_url(self, obj):
        request = self.context.get('request')
        if obj.image and request:
            return request.build_absolute_uri(obj.image.url)
        return None


class TruffleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Truffle
        fields = ['id', 'name', 'color', 'note', 'is_active']
