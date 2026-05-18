from decimal import Decimal
from django.db import models
from django.utils import timezone


class Coupon(models.Model):
    """A redeemable discount code.

    Three kinds:
      * ``percent`` — value is 0-100, applied to subtotal
      * ``fixed``   — value is NOK amount, subtracted from subtotal
      * ``free_shipping`` — value ignored, shipping forced to 0

    ``min_subtotal`` gates redemption. ``valid_from`` / ``valid_to`` bound the
    window (either may be null). ``max_uses`` is the global cap; ``times_used``
    is incremented atomically when an order applies the coupon.
    """
    KIND_PERCENT = 'percent'
    KIND_FIXED = 'fixed'
    KIND_FREE_SHIPPING = 'free_shipping'
    KIND_CHOICES = [
        (KIND_PERCENT, 'Prosent'),
        (KIND_FIXED, 'Fast beløp (NOK)'),
        (KIND_FREE_SHIPPING, 'Fri frakt'),
    ]

    code = models.CharField(max_length=40, unique=True, db_index=True)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    value = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal('0'),
        help_text='Percent (0-100) or NOK amount. Ignored for free_shipping.',
    )
    min_subtotal = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0'),
        help_text='Minimum cart subtotal (NOK) required to redeem.',
    )
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_to = models.DateTimeField(null=True, blank=True)
    max_uses = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='Total redemptions allowed; null = unlimited.',
    )
    times_used = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.code} ({self.get_kind_display()})'

    def is_currently_valid(self, *, subtotal: Decimal | None = None) -> tuple[bool, str]:
        """Return (ok, reason). Reason is empty when ok."""
        if not self.is_active:
            return False, 'Koden er ikke aktiv.'
        now = timezone.now()
        if self.valid_from and now < self.valid_from:
            return False, 'Koden er ikke gyldig ennå.'
        if self.valid_to and now > self.valid_to:
            return False, 'Koden er utløpt.'
        if self.max_uses is not None and self.times_used >= self.max_uses:
            return False, 'Koden er brukt opp.'
        if subtotal is not None and self.min_subtotal and subtotal < self.min_subtotal:
            return False, f'Krever delsum på minst kr {self.min_subtotal:.0f}.'
        return True, ''

    def compute_discount(self, subtotal: Decimal) -> Decimal:
        """NOK amount to subtract from subtotal. Rounded to whole NOK so the
        storefront's whole-NOK price displays don't introduce awkward sub-NOK
        decimals in the total (e.g. 10% of 949 → 95 NOK, not 94.90).
        Never exceeds subtotal.
        """
        if self.kind == self.KIND_PERCENT:
            raw = (subtotal * self.value / Decimal('100')).quantize(Decimal('1'))
        elif self.kind == self.KIND_FIXED:
            raw = self.value.quantize(Decimal('1'))
        else:
            raw = Decimal('0')
        return max(Decimal('0'), min(raw, subtotal))

    def gives_free_shipping(self) -> bool:
        return self.kind == self.KIND_FREE_SHIPPING
