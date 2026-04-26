from django.conf import settings
from django.db import models


class Order(models.Model):
    STATUS_CHOICES = [
        ('Bekreftet', 'Bekreftet'),
        ('Pakkes', 'Pakkes'),
        ('Sendt', 'Sendt'),
        ('Levert', 'Levert'),
    ]
    PAYMENT_CHOICES = [
        ('vipps', 'Vipps'),
        ('card', 'Card'),
        ('klarna', 'Klarna'),
        ('invoice', 'Invoice'),
    ]

    order_number = models.CharField(max_length=20, unique=True, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='orders',
    )
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    shipping = models.DecimalField(max_digits=10, decimal_places=2)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Bekreftet')
    payment_method = models.CharField(max_length=20, choices=PAYMENT_CHOICES)

    # Shipping address — embedded directly
    ship_first_name = models.CharField(max_length=100)
    ship_last_name = models.CharField(max_length=100)
    ship_email = models.EmailField()
    ship_phone = models.CharField(max_length=30)
    ship_address = models.CharField(max_length=300)
    ship_postal_code = models.CharField(max_length=10)
    ship_city = models.CharField(max_length=100)
    ship_country = models.CharField(max_length=100, default='Norge')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.order_number:
            last = Order.objects.order_by('id').last()
            next_id = (last.id + 1) if last else 347
            self.order_number = f'SL-{next_id:05d}'
        super().save(*args, **kwargs)

    def __str__(self):
        return self.order_number


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey('products.Product', on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=8, decimal_places=2)
    variant = models.CharField(max_length=50, blank=True)
    initials = models.CharField(max_length=10, blank=True)
    custom_slots = models.JSONField(null=True, blank=True)

    def __str__(self):
        return f'{self.quantity}× {self.product.name} (#{self.order.order_number})'
