from django.contrib import admin

from .models import Order, OrderItem, OrderAuditLog


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    readonly_fields = ('product', 'quantity', 'unit_price', 'variant', 'initials', 'custom_slots')

    def has_add_permission(self, request, obj=None):
        return False


class OrderAuditLogInline(admin.TabularInline):
    model = OrderAuditLog
    extra = 0
    can_delete = False
    readonly_fields = ('timestamp', 'actor_user', 'action', 'source', 'from_value', 'to_value', 'note')
    ordering = ('-timestamp',)

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        'order_number',
        'created_at',
        'user',
        'payment_status',
        'shipping_method',
        'consignment_number',
        'total',
    )
    list_filter = ('shipping_method', 'payment_status', 'status', 'created_at')
    search_fields = (
        'order_number',
        'user__email',
        'consignment_number',
        'pickup_point_name',
        'ship_email',
        'vipps_reference',
    )
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)

    readonly_fields = (
        'order_number',
        'created_at',
        'updated_at',
        # Carrier / consignment data — written by Profrakt response, never edited by hand.
        'pickup_point_number',
        'pickup_point_name',
        'pickup_point_address1',
        'pickup_point_postcode',
        'pickup_point_city',
        'pickup_point_country',
        'pickup_point_customer_number',
        'consignment_id',
        'consignment_number',
        'consignment_pdf_url',
        'tracking_url',
        'shipping_working_days',
        'shipping_expected_delivery',
        # Vipps fields — owned by webhook + reconciler.
        'vipps_reference',
        'vipps_psp_reference',
        'vipps_redirect_url',
        'vipps_currency',
        'vipps_authorized_amount',
        'vipps_captured_amount',
        'vipps_refunded_amount',
        'vipps_cancelled_amount',
        'vipps_capture_idempotency_key',
        'vipps_cancel_idempotency_key',
        'authorized_at',
        'captured_at',
        'last_vipps_sync_at',
    )

    fieldsets = (
        ('Order', {
            'fields': ('order_number', 'status', 'subtotal', 'shipping', 'total'),
        }),
        ('Customer', {
            'fields': ('user',),
        }),
        ('Shipping address', {
            'fields': (
                ('ship_first_name', 'ship_last_name'),
                'ship_email',
                'ship_phone',
                'ship_address',
                ('ship_postal_code', 'ship_city', 'ship_country'),
            ),
        }),
        ('Shipping (carrier)', {
            'fields': (
                'shipping_method',
                'pickup_point_name',
                'pickup_point_address1',
                ('pickup_point_postcode', 'pickup_point_city', 'pickup_point_country'),
                ('pickup_point_number', 'pickup_point_customer_number'),
                ('shipping_working_days', 'shipping_expected_delivery'),
            ),
        }),
        ('Consignment & tracking', {
            'fields': (
                'consignment_id',
                'consignment_number',
                'tracking_url',
                'consignment_pdf_url',
            ),
        }),
        ('Payment', {
            'fields': (
                'payment_method',
                'payment_status',
                'vipps_reference',
                'vipps_psp_reference',
                'vipps_redirect_url',
                ('vipps_currency', 'vipps_authorized_amount', 'vipps_captured_amount'),
                ('vipps_refunded_amount', 'vipps_cancelled_amount'),
                ('vipps_capture_idempotency_key', 'vipps_cancel_idempotency_key'),
                ('authorized_at', 'captured_at', 'last_vipps_sync_at'),
            ),
            'classes': ('collapse',),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    inlines = (OrderItemInline, OrderAuditLogInline)


@admin.register(OrderAuditLog)
class OrderAuditLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'order', 'action', 'source', 'actor_user')
    list_filter = ('action', 'source', 'timestamp')
    search_fields = ('order__order_number', 'note')
    date_hierarchy = 'timestamp'
    readonly_fields = ('order', 'timestamp', 'actor_user', 'action', 'from_value', 'to_value', 'source', 'note')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
