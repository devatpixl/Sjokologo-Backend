from decimal import Decimal
from django.db import models
from django.utils import timezone


class BundleRule(models.Model):
    """Auto-applied quantity-bracket pricing.

    The rule fires when at least ``required_quantity`` matching items are in
    the cart. Matching is by ``variant_group`` (preferred) or by the M2M
    ``products`` list. When fired, the matched items' line subtotal is
    replaced with ``bundle_price`` (per bundle), and shipping is forced to 0
    if ``includes_free_shipping``.

    Client launch case: code = "VANLIG-16-3PACK", variant_group=`vanlig-16`,
    required_quantity=3, bundle_price=949, includes_free_shipping=True.
    """
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=240, blank=True, default='')
    variant_group = models.CharField(
        max_length=64, blank=True, default='',
        help_text='Match products by their variant_group. Leave blank to use the explicit product list.',
    )
    products = models.ManyToManyField(
        'products.Product', blank=True, related_name='bundle_rules',
        help_text='Explicit product list, used when variant_group is blank.',
    )
    required_quantity = models.PositiveIntegerField(default=3)
    bundle_price = models.DecimalField(max_digits=10, decimal_places=2)
    includes_free_shipping = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True, db_index=True)
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_to = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    def is_currently_active(self) -> bool:
        if not self.is_active:
            return False
        now = timezone.now()
        if self.valid_from and now < self.valid_from:
            return False
        if self.valid_to and now > self.valid_to:
            return False
        return True

    def matches_product(self, product) -> bool:
        if self.variant_group:
            return getattr(product, 'variant_group', '') == self.variant_group
        return self.products.filter(pk=product.pk).exists()
