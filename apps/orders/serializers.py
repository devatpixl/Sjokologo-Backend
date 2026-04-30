from rest_framework import serializers
from .models import Order, OrderItem
from .audit import record_order_event
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


class OrderUserMiniSerializer(serializers.Serializer):
    """Compact view of the user that owns an order — enough for the thank-you
    page to decide whether to render the guest-to-registered upsell card."""
    id = serializers.UUIDField()
    name = serializers.CharField()
    email = serializers.EmailField()
    user_type = serializers.CharField()


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    shipping_address = serializers.SerializerMethodField()
    customer_name = serializers.SerializerMethodField()
    user = OrderUserMiniSerializer(read_only=True)

    class Meta:
        model = Order
        fields = [
            'id', 'order_number', 'user', 'customer_name',
            'subtotal', 'shipping', 'total',
            'status', 'payment_method', 'payment_status',
            'shipping_address', 'items',
            # Shipping method + Profrakt consignment (visible to client so /takk
            # can render the tracking number, partner name, ETA without depending
            # on sessionStorage). consignment_id and pickup_point_customer_number
            # stay internal — not exposed.
            'shipping_method',
            'pickup_point_name', 'pickup_point_address1',
            'pickup_point_postcode', 'pickup_point_city',
            'consignment_number', 'consignment_pdf_url', 'tracking_url',
            'shipping_expected_delivery', 'shipping_working_days',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['payment_status']

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
    paymentMethod = serializers.ChoiceField(choices=['vipps'], default='vipps')

    # Shipping cost the storefront quoted to the customer. Trusted: backend
    # doesn't have a Profrakt client (yet), and the audit log captures the
    # exact value so any tampering is auditable.
    shipping = serializers.FloatField(required=False, allow_null=True)

    # Bring vs. self-pickup. When 'bring-pickup-point', pickupPoint and
    # consignment are expected to be present. Self-pickup leaves them null.
    shippingMethod = serializers.ChoiceField(
        choices=['self-pickup', 'bring-pickup-point'],
        required=False, allow_null=True,
    )
    pickupPoint = serializers.DictField(required=False, allow_null=True)
    consignment = serializers.DictField(required=False, allow_null=True)
    shippingWorkingDays = serializers.IntegerField(required=False, allow_null=True)
    shippingExpectedDelivery = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, max_length=20,
    )

    def create(self, validated_data):
        from apps.products.models import Product

        addr = validated_data['shippingAddress']
        subtotal = sum(
            float(i.get('price', 0)) * int(i.get('quantity', 1))
            for i in validated_data['items']
        )
        # Trust storefront's shipping value when supplied (it came from Profrakt).
        # Fall back to the legacy 0/79 rule for callers that don't send shipping.
        shipping_supplied = validated_data.get('shipping')
        if shipping_supplied is None:
            shipping = 0 if subtotal >= 500 else 79
        else:
            shipping = float(shipping_supplied)

        shipping_method = validated_data.get('shippingMethod') or None
        pickup = validated_data.get('pickupPoint') or {}
        consignment = validated_data.get('consignment') or {}

        user = self.context.get('user')
        order = Order.objects.create(
            user=user,
            subtotal=subtotal,
            shipping=shipping,
            total=subtotal + shipping,
            payment_method=validated_data.get('paymentMethod', 'vipps'),
            ship_first_name=addr.get('firstName', ''),
            ship_last_name=addr.get('lastName', ''),
            ship_email=addr.get('email', ''),
            ship_phone=addr.get('phone', ''),
            ship_address=addr.get('address', ''),
            ship_postal_code=addr.get('postalCode', ''),
            ship_city=addr.get('city', ''),
            ship_country=addr.get('country', 'Norge'),
            shipping_method=shipping_method,
            pickup_point_number=pickup.get('number') or None,
            pickup_point_name=pickup.get('name') or None,
            pickup_point_address1=pickup.get('address1') or None,
            pickup_point_postcode=pickup.get('postcode') or None,
            pickup_point_city=pickup.get('city') or None,
            pickup_point_country=pickup.get('country') or None,
            pickup_point_customer_number=pickup.get('customerNumber') or None,
            consignment_id=consignment.get('id') or None,
            consignment_number=consignment.get('number') or None,
            consignment_pdf_url=consignment.get('consignmentPdf') or None,
            tracking_url=consignment.get('trackingUrl') or None,
            shipping_working_days=validated_data.get('shippingWorkingDays'),
            shipping_expected_delivery=validated_data.get('shippingExpectedDelivery') or None,
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

        record_order_event(
            order,
            action='order_created',
            source='storefront',
            actor_user=user,
            to_value={
                'order_number': order.order_number,
                'total': str(order.total),
                'payment_method': order.payment_method,
                'user_type': user.user_type if user else None,
                'shipping_method': order.shipping_method,
                'shipping_amount': str(order.shipping),
                'pickup_point_name': order.pickup_point_name,
                'consignment_number': order.consignment_number,
                'shipping_expected_delivery': order.shipping_expected_delivery,
                'shipping_working_days': order.shipping_working_days,
            },
        )

        return order


class OrderStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        fields = ['status']
