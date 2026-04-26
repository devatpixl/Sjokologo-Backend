from rest_framework import serializers
from .models import Product, Truffle


class ProductSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'id', 'slug', 'name', 'category', 'size',
            'price', 'price_min', 'price_max',
            'image', 'image_url', 'flavors', 'blurb',
            'in_stock', 'batch_number', 'batch_count', 'batch_total',
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
        fields = ['id', 'name', 'color', 'note']
