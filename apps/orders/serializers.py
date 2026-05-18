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
            'coupon_code', 'discount_amount', 'coupon_free_shipping',
            'bundles_applied',
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
        choices=['self-pickup', 'bring-pickup-point', 'postnord-locker'],
        required=False, allow_null=True,
    )
    pickupPoint = serializers.DictField(required=False, allow_null=True)
    consignment = serializers.DictField(required=False, allow_null=True)
    shippingWorkingDays = serializers.IntegerField(required=False, allow_null=True)
    shippingExpectedDelivery = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, max_length=20,
    )
    # Rabattkode entered by the customer. Re-validated server-side; an
    # invalid/expired code is dropped silently so the order still goes through.
    couponCode = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, max_length=40,
    )

    def create(self, validated_data):
        from decimal import Decimal
        from django.conf import settings as dj_settings
        from django.db.models import F
        from apps.products.models import Product
        from apps.coupons.models import Coupon
        from apps.bundles.models import BundleRule

        addr = validated_data['shippingAddress']

        # Build line entries up front: we need them for bundle matching and
        # OrderItem creation. Trust client prices for subtotal (matches the
        # storefront-displayed total); OrderItem.unit_price still uses the DB
        # value for downstream accounting.
        item_lines = []
        for i in validated_data['items']:
            try:
                product = Product.objects.get(slug=i.get('slug', ''))
            except Product.DoesNotExist:
                continue
            qty = int(i.get('quantity', 1))
            unit_price = Decimal(str(i.get('price', 0)))
            item_lines.append({'product': product, 'qty': qty, 'unit_price': unit_price, 'raw': i})

        subtotal = sum(
            (line['unit_price'] * line['qty'] for line in item_lines),
            Decimal('0'),
        )

        # 1. Auto-apply bundle rules. Each rule replaces N matching units'
        # line subtotal with bundle_price. The discount is the raw-vs-bundle
        # difference. Track per-rule for audit + free-shipping signal.
        bundles_applied = []
        bundle_discount = Decimal('0')
        bundle_free_shipping = False
        active_bundles = [r for r in BundleRule.objects.filter(is_active=True) if r.is_currently_active()]
        for rule in active_bundles:
            matching_qty = sum(line['qty'] for line in item_lines if rule.matches_product(line['product']))
            bundles_count = matching_qty // rule.required_quantity if rule.required_quantity else 0
            if bundles_count <= 0:
                continue
            # Sum the unit_prices of the matched-and-consumed units.
            consumed_remaining = bundles_count * rule.required_quantity
            matched_raw = Decimal('0')
            for line in item_lines:
                if not rule.matches_product(line['product']) or consumed_remaining <= 0:
                    continue
                take = min(line['qty'], consumed_remaining)
                matched_raw += line['unit_price'] * take
                consumed_remaining -= take
            bundle_subtotal = rule.bundle_price * bundles_count
            this_discount = matched_raw - bundle_subtotal
            if this_discount <= 0:
                continue
            bundle_discount += this_discount
            bundles_applied.append({
                'rule_id': rule.id,
                'name': rule.name,
                'qty_consumed': int(bundles_count * rule.required_quantity),
                'bundle_price': str(rule.bundle_price),
                'discount': str(this_discount),
            })
            if rule.includes_free_shipping:
                bundle_free_shipping = True

        # 2. Apply coupon (re-validated server-side, applied to post-bundle
        # subtotal so coupons stack with bundles cleanly).
        post_bundle_subtotal = subtotal - bundle_discount
        coupon_code = ''
        coupon_discount = Decimal('0')
        coupon_free_shipping = False
        submitted_code = (validated_data.get('couponCode') or '').strip().upper()
        if submitted_code:
            coupon = Coupon.objects.filter(code=submitted_code).first()
            if coupon:
                ok, _ = coupon.is_currently_valid(subtotal=post_bundle_subtotal)
                if ok:
                    coupon_discount = coupon.compute_discount(post_bundle_subtotal)
                    coupon_code = coupon.code
                    coupon_free_shipping = coupon.gives_free_shipping()
                    Coupon.objects.filter(pk=coupon.pk).update(times_used=F('times_used') + 1)

        total_discount = bundle_discount + coupon_discount

        # 3. Shipping resolution. Free if: cart subtotal (raw, pre-discount)
        # clears the threshold for any combination of products, OR coupon
        # kind=free_shipping, OR an applied bundle includes it. The threshold
        # is intentionally checked against the raw subtotal so a coupon that
        # drops the post-discount amount below the threshold doesn't strip
        # the customer of their free-shipping reward.
        shipping_supplied = validated_data.get('shipping')
        shipping = Decimal(str(shipping_supplied)) if shipping_supplied is not None else Decimal('0')
        free_shipping_threshold = Decimal(str(
            getattr(dj_settings, 'FREE_SHIPPING_THRESHOLD_NOK', 949)
        ))
        if (subtotal >= free_shipping_threshold
                or coupon_free_shipping
                or bundle_free_shipping):
            shipping = Decimal('0')

        total = subtotal - total_discount + shipping

        shipping_method = validated_data.get('shippingMethod') or None
        pickup = validated_data.get('pickupPoint') or {}
        consignment = validated_data.get('consignment') or {}

        user = self.context.get('user')
        order = Order.objects.create(
            user=user,
            subtotal=subtotal,
            shipping=shipping,
            total=total,
            coupon_code=coupon_code,
            discount_amount=total_discount,
            coupon_free_shipping=coupon_free_shipping,
            bundles_applied=bundles_applied,
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

        for line in item_lines:
            OrderItem.objects.create(
                order=order,
                product=line['product'],
                quantity=line['qty'],
                unit_price=line['product'].price,
                variant=line['raw'].get('variant', ''),
                initials=line['raw'].get('initials', ''),
                custom_slots=line['raw'].get('customSlots'),
            )

        record_order_event(
            order,
            action='order_created',
            source='storefront',
            actor_user=user,
            to_value={
                'order_number': order.order_number,
                'total': str(order.total),
                'subtotal': str(order.subtotal),
                'discount_amount': str(order.discount_amount),
                'coupon_code': order.coupon_code or None,
                'bundles_applied': order.bundles_applied,
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
