from rest_framework import serializers
from .models import Order, OrderItem
from apps.products.serializers import ProductSerializer


class OrderItemSerializer(serializers.ModelSerializer):
    product = ProductSerializer(read_only=True)
    product_id = serializers.PrimaryKeyRelatedField(
        source='product', queryset=__import__('apps.products.models', fromlist=['Product']).Product.objects.all(),
        write_only=True,
    )

    class Meta:
        model = OrderItem
        fields = ['id', 'product', 'product_id', 'quantity', 'unit_price', 'variant', 'initials', 'custom_slots']
        read_only_fields = ['unit_price']


class ShippingAddressField(serializers.Serializer):
    firstName = serializers.CharField(source='ship_first_name')
    lastName = serializers.CharField(source='ship_last_name')
    email = serializers.EmailField(source='ship_email')
    phone = serializers.CharField(source='ship_phone')
    address = serializers.CharField(source='ship_address')
    postalCode = serializers.CharField(source='ship_postal_code')
    city = serializers.CharField(source='ship_city')
    country = serializers.CharField(source='ship_country', default='Norge')


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    shipping_address = serializers.SerializerMethodField()
    customer_name = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            'id', 'order_number', 'user', 'customer_name',
            'subtotal', 'shipping', 'total',
            'status', 'payment_method',
            'shipping_address', 'items',
            'created_at', 'updated_at',
        ]

    def get_shipping_address(self, obj):
        return {
            'firstName': obj.ship_first_name,
            'lastName': obj.ship_last_name,
            'email': obj.ship_email,
            'phone': obj.ship_phone,
            'address': obj.ship_address,
            'postalCode': obj.ship_postal_code,
            'city': obj.ship_city,
            'country': obj.ship_country,
        }

    def get_customer_name(self, obj):
        if obj.user:
            return obj.user.name
        return f'{obj.ship_first_name} {obj.ship_last_name}'


class CreateOrderSerializer(serializers.Serializer):
    items = serializers.ListField(child=serializers.DictField())
    shippingAddress = serializers.DictField()
    paymentMethod = serializers.ChoiceField(choices=['vipps', 'card', 'klarna', 'invoice'])
    # Optional — frontend now computes a real Profrakt freight cost client-side
    # and forwards it here. Older clients omit it; fall back to the legacy rule.
    shipping = serializers.FloatField(required=False, allow_null=True)

    def create(self, validated_data):
        from apps.products.models import Product

        addr = validated_data['shippingAddress']
        subtotal = sum(
            float(i.get('price', 0)) * int(i.get('quantity', 1))
            for i in validated_data['items']
        )
        client_shipping = validated_data.get('shipping')
        shipping = float(client_shipping) if client_shipping is not None else (0 if subtotal >= 500 else 79)

        order = Order.objects.create(
            user=self.context.get('user'),
            subtotal=subtotal,
            shipping=shipping,
            total=subtotal + shipping,
            payment_method=validated_data['paymentMethod'],
            ship_first_name=addr.get('firstName', ''),
            ship_last_name=addr.get('lastName', ''),
            ship_email=addr.get('email', ''),
            ship_phone=addr.get('phone', ''),
            ship_address=addr.get('address', ''),
            ship_postal_code=addr.get('postalCode', ''),
            ship_city=addr.get('city', ''),
            ship_country=addr.get('country', 'Norge'),
        )

        for item_data in validated_data['items']:
            try:
                product = Product.objects.get(slug=item_data.get('slug', ''))
                OrderItem.objects.create(
                    order=order,
                    product=product,
                    quantity=item_data.get('quantity', 1),
                    unit_price=product.price,
                    variant=item_data.get('variant', ''),
                    initials=item_data.get('initials', ''),
                    custom_slots=item_data.get('customSlots'),
                )
            except Product.DoesNotExist:
                pass

        return order


class OrderStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        fields = ['status']
