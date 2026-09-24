"""HORECA portal — company accounts and the people inside them.

A HORECA customer is a *company* (a hotel, restaurant or caterer), not a person.
That is the whole reason this app exists: `apps.users.CustomUser` models one
private buyer with one flat address, and every consumer query in the project
assumes it.

Two rules worth stating once, because the rest of the app leans on them:

1. A company is **not** allowed to order until Sjoko Loco has approved it
   (K-5, K-6). Approval is a state on the company, never a flag on the user.
2. The role a person has comes from their membership, never from anything they
   choose in the interface (K-2).
"""
import uuid
from datetime import time, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone as djtz

from .storage import logo_upload_to, private_logo_storage


class Company(models.Model):
    """A HORECA customer. Registers itself, then waits for approval (K-5)."""

    class Status(models.TextChoices):
        PENDING = 'pending', 'Venter godkjenning'
        ACTIVE = 'active', 'Godkjent'
        REJECTED = 'rejected', 'Avvist'
        SUSPENDED = 'suspended', 'Sperret'

    # REJECTED and SUSPENDED are deliberately separate states. The sibling B2B
    # project collapses both onto "suspended", which makes "we never accepted
    # this signup" and "we cut off a customer we used to serve" indistinguishable
    # — and those want different wording in the e-mail and different handling.

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    org_number = models.CharField(max_length=32, unique=True, db_index=True)

    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    rejection_reason = models.TextField(blank=True)

    # Contact for the company as a whole. The people who actually log in live on
    # Membership; this is the switchboard number and the invoice inbox.
    phone = models.CharField(max_length=32, blank=True)
    email = models.EmailField(blank=True)

    invoice_street = models.CharField(max_length=255, blank=True)
    invoice_postal_code = models.CharField(max_length=16, blank=True)
    invoice_city = models.CharField(max_length=128, blank=True)
    # 'Norge', not 'NO': CustomUser.country and Order.ship_country both store
    # the display name. The order snapshot copies this field, so a divergence
    # here would be permanent in order history.
    invoice_country = models.CharField(max_length=80, blank=True, default='Norge')

    # Who let them in, and when. Worth storing rather than reconstructing from a
    # log: "why does this company have wholesale prices?" is a question that gets
    # asked months later.
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'companies'

    def __str__(self):
        return f'{self.name} ({self.org_number})'

    @property
    def can_order(self) -> bool:
        """K-6: an unapproved company may look, but may not send an order."""
        return self.status == self.Status.ACTIVE


class Membership(models.Model):
    """Links a person to a company, and says what they may do there (K-1..K-3)."""

    class Role(models.TextChoices):
        BESTILLER = 'bestiller', 'Bestiller'
        BEDRIFTSADMIN = 'bedriftsadmin', 'Bedriftsadmin'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='horeca_memberships',
    )
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='members',
    )

    # A ForeignKey pair, not a OneToOneField on the user. The sibling project
    # made it one-to-one and as a result a chef who caters for two hotels cannot
    # be represented at all. This costs nothing today and keeps that door open.
    role = models.CharField(
        max_length=16,
        choices=Role.choices,
        default=Role.BESTILLER,
    )

    # K-3: when someone leaves, the membership is deactivated rather than
    # deleted, so the company's order history stays intact and the orders they
    # placed keep pointing at a real person.
    is_active = models.BooleanField(default=True)

    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    invited_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'company'],
                name='uniq_membership_user_company',
            ),
        ]

    def __str__(self):
        return f'{self.user.email} @ {self.company.name} ({self.role})'


# ── Operational settings Terje controls ─────────────────────────────────────
#
# The split rule: limits OPS change (capacity, lead times, cut-off, tray
# geometry) live in the database and are editable in the admin panel. Limits
# DEVELOPERS own (max upload bytes, portal URL, e-mail recipients) stay in
# config/settings.py. K-41 is explicit that lead times must be settings in the
# portal, "ikke i koden".

def _default_delivery_weekdays():
    return [0, 1, 2, 3, 4]  # Mon–Fri; 5/6 are Sat/Sun in Python's weekday()


def _default_delivery_windows():
    return [
        {'code': '08-12', 'label': '08:00–12:00'},
        {'code': '12-16', 'label': '12:00–16:00'},
    ]


class HorecaSettings(models.Model):
    """Singleton row. Seeded by a data migration so a fresh database has a
    working calendar with no manual step."""

    singleton_id = models.PositiveSmallIntegerField(
        primary_key=True, default=1, editable=False,
    )

    # K-47 — the client's decision: one number, admin-editable.
    max_trays_per_day = models.PositiveIntegerField(default=40)

    # K-41
    lead_time_days_plain = models.PositiveSmallIntegerField(default=3)
    lead_time_days_logo = models.PositiveSmallIntegerField(default=7)
    lead_time_in_working_days = models.BooleanField(default=True)
    cutoff_time = models.TimeField(default=time(12, 0))
    order_horizon_days = models.PositiveSmallIntegerField(default=180)

    # K-40 / K-42
    delivery_weekdays = models.JSONField(default=_default_delivery_weekdays)
    delivery_windows = models.JSONField(default=_default_delivery_windows)

    # Tray geometry (K-12). Also on the product, which overrides this — these
    # are the defaults the calendar uses before a basket exists.
    pieces_per_tray_plain = models.PositiveSmallIntegerField(default=88)
    pieces_per_tray_logo = models.PositiveSmallIntegerField(default=81)

    min_trays_per_order = models.PositiveSmallIntegerField(default=1)
    # A sanity ceiling to catch a typo, NOT a business rule. Note the consumer
    # shop's MAX_LINE_QTY of 50 deliberately has no analogue here — fifty trays
    # is a normal HORECA order.
    max_trays_per_order = models.PositiveIntegerField(default=500)

    cancel_deadline_days = models.PositiveSmallIntegerField(default=2)  # K-45
    vat_rate = models.DecimalField(max_digits=5, decimal_places=2,
                                   default=Decimal('15.00'))

    # Deliberately NOT settings.ORDERING_PAUSED: pausing the consumer shop and
    # pausing B2B production are different events, and that one needs a
    # storefront rebuild to change.
    ordering_paused = models.BooleanField(default=False)
    paused_message = models.TextField(blank=True, default='')

    contact_phone = models.CharField(max_length=32, blank=True, default='')

    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+',
    )

    class Meta:
        verbose_name_plural = 'horeca settings'

    def __str__(self):
        return 'HORECA-innstillinger'

    def save(self, *args, **kwargs):
        self.singleton_id = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class BlackoutDate(models.Model):
    """K-42 — a day nobody delivers on. The reason is shown to the customer."""
    date = models.DateField(unique=True)
    reason = models.CharField(max_length=200, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['date']

    def __str__(self):
        return f'{self.date} — {self.reason or "stengt"}'


class CapacityOverride(models.Model):
    """A day that is not the usual size — an extra shift, or a half day."""
    date = models.DateField(unique=True)
    max_trays = models.PositiveIntegerField()
    note = models.CharField(max_length=200, blank=True, default='')

    class Meta:
        ordering = ['date']

    def __str__(self):
        return f'{self.date}: {self.max_trays} brett'


# ── Catalogue (K-11 … K-15) ─────────────────────────────────────────────────
#
# A separate model from products.Product, not a flag on it. apps/products/
# views.py filters only in_stock+is_active, so a HORECA row in that table would
# appear in the consumer shop the moment anyone forgets a third filter — a
# direct breach of "the consumer shop keeps working identically".

class HorecaProduct(models.Model):
    slug = models.SlugField(max_length=200, unique=True)
    name = models.CharField(max_length=200)
    short_description = models.CharField(max_length=300, blank=True, default='')
    description = models.TextField(blank=True, default='')

    # K-12: the logo sheet takes the place of seven chocolates. Per product,
    # because a future line may not be 88/81.
    pieces_per_tray_plain = models.PositiveSmallIntegerField(default=88)
    pieces_per_tray_logo = models.PositiveSmallIntegerField(default=81)
    logo_available = models.BooleanField(default=True)

    # Named wholesale_price, never `price`, so it can never be mistaken for the
    # consumer Product.price. Read only through pricing.resolve_unit_price().
    wholesale_price = models.DecimalField(max_digits=10, decimal_places=2)
    vat_rate = models.DecimalField(max_digits=5, decimal_places=2,
                                   default=Decimal('15.00'))

    # K-15 — the customer has a legal labelling duty, so this is not optional
    # decoration.
    ingredients_text = models.TextField(blank=True, default='')
    allergens = models.JSONField(default=list)
    traces_of = models.JSONField(default=list)
    net_weight_grams = models.PositiveIntegerField(null=True, blank=True)
    shelf_life_days = models.PositiveSmallIntegerField(null=True, blank=True)
    storage_text = models.CharField(max_length=300, blank=True, default='')

    image = models.ImageField(upload_to='horeca/products/', blank=True)
    # K-43 — a tray needing hand-decoration can carry a longer lead than the
    # default. Null means "use the setting".
    lead_time_days = models.PositiveSmallIntegerField(null=True, blank=True)

    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True, db_index=True)  # K-13
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', 'name']

    def __str__(self):
        return self.name

    def pieces_for(self, with_logo: bool) -> int:
        return self.pieces_per_tray_logo if with_logo else self.pieces_per_tray_plain


# ── Delivery addresses (K-33 … K-38) ────────────────────────────────────────

class DeliveryAddress(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(Company, on_delete=models.CASCADE,
                               related_name='addresses')
    label = models.CharField(max_length=120)  # K-33 "Hovedkjøkken"
    recipient = models.CharField(max_length=150, blank=True, default='')
    contact_name = models.CharField(max_length=150, blank=True, default='')
    # K-36 — required, not optional. The driver needs somebody to ring.
    contact_phone = models.CharField(max_length=32)
    street = models.CharField(max_length=300)
    postal_code = models.CharField(max_length=10)
    city = models.CharField(max_length=120)
    country = models.CharField(max_length=80, default='Norge')
    instructions = models.TextField(blank=True, default='')  # K-37

    is_default = models.BooleanField(default=False)  # K-34
    # K-38: edited or removed addresses are archived, never deleted, so an
    # order's breadcrumb stays resolvable and history is never rewritten.
    is_archived = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_default', 'label']
        constraints = [
            models.UniqueConstraint(
                fields=['company'],
                condition=models.Q(is_default=True, is_archived=False),
                name='one_default_address_per_company',
            ),
        ]

    def __str__(self):
        return f'{self.label} — {self.street}, {self.city}'


# ── Logos (K-24 … K-32) ─────────────────────────────────────────────────────

class Logo(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Til godkjenning'
        APPROVED = 'approved', 'Godkjent'
        REJECTED = 'rejected', 'Avvist'

    class Kind(models.TextChoices):
        RASTER = 'raster', 'Bilde'
        VECTOR = 'vector', 'Vektor'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(Company, on_delete=models.CASCADE,
                                related_name='logos')  # K-30: several per company
    name = models.CharField(max_length=120)

    file = models.FileField(
        upload_to=logo_upload_to, storage=private_logo_storage, max_length=255,
    )
    original_filename = models.CharField(max_length=255)
    detected_format = models.CharField(max_length=8)
    kind = models.CharField(max_length=8, choices=Kind.choices)
    content_type = models.CharField(max_length=100, blank=True, default='')
    byte_size = models.PositiveIntegerField()
    checksum_sha256 = models.CharField(max_length=64, db_index=True)
    # Null for vector — K-27 exempts them from the pixel floor.
    width_px = models.PositiveIntegerField(null=True, blank=True)
    height_px = models.PositiveIntegerField(null=True, blank=True)

    status = models.CharField(max_length=16, choices=Status.choices,
                              default=Status.PENDING, db_index=True)
    rejection_reason = models.TextField(blank=True, default='')  # K-29
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name='+')
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name='+')
    is_archived = models.BooleanField(default=False)  # K-32

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['company', 'status'])]

    def __str__(self):
        return f'{self.name} ({self.company.name})'

    @property
    def is_usable(self) -> bool:
        return self.status == self.Status.APPROVED and not self.is_archived


# ── Orders (K-16 … K-23, K-39 … K-51) ───────────────────────────────────────

class HorecaOrder(models.Model):
    """A B2B order. Deliberately NOT apps.orders.Order — see the module docstring
    and the plan: that model is ~12 Vipps columns deep, caps a line at 50 units,
    has no company dimension, and only ever e-mails from a Vipps webhook."""

    class Status(models.TextChoices):
        # The SRS flowchart, exactly.
        UTKAST = 'utkast', 'Utkast'
        SENDT = 'sendt', 'Sendt'
        BEKREFTET = 'bekreftet', 'Bekreftet'
        PRODUKSJON = 'produksjon', 'I produksjon'
        KLAR = 'klar', 'Klar til levering'
        LEVERT = 'levert', 'Levert'
        AVBESTILT = 'avbestilt', 'Avbestilt'

    # K-48: the customer may cancel up to the deadline, and never once the
    # kitchen has started. Held here so the rule has exactly one home.
    CANCELLABLE_FROM = (Status.UTKAST, Status.SENDT, Status.BEKREFTET)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # NULL until the draft is sent. Nullable-and-unique rather than
    # blank-and-unique because Postgres treats every NULL as distinct but '' as
    # one value — so a second draft would collide with the first on the empty
    # string. This is the one place a CharField should be null=True.
    order_number = models.CharField(
        max_length=20, unique=True, null=True, blank=True, editable=False,
    )
    company = models.ForeignKey(Company, on_delete=models.PROTECT,
                                related_name='orders')
    placed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                  on_delete=models.SET_NULL,
                                  related_name='horeca_orders')
    # Snapshots, so the order still reads correctly after SET_NULL or a rename.
    placed_by_name = models.CharField(max_length=150, blank=True, default='')
    placed_by_email = models.EmailField(blank=True, default='')

    status = models.CharField(max_length=16, choices=Status.choices,
                              default=Status.UTKAST, db_index=True)
    # K-20: a draft is not an order. Kept as its own flag as well as a status so
    # every "real orders only" query reads the same way.
    is_draft = models.BooleanField(default=True)

    # K-39, K-40
    delivery_date = models.DateField(null=True, blank=True, db_index=True)
    delivery_window = models.CharField(max_length=16, blank=True, default='')
    delivery_window_label = models.CharField(max_length=40, blank=True, default='')

    company_name = models.CharField(max_length=255, blank=True, default='')
    org_number = models.CharField(max_length=32, blank=True, default='')

    # K-38 — the address on an order is a COPY, never a pointer. Editing a saved
    # address must not rewrite an order that already shipped.
    delivery_label = models.CharField(max_length=120, blank=True, default='')
    delivery_recipient = models.CharField(max_length=150, blank=True, default='')
    delivery_contact_name = models.CharField(max_length=150, blank=True, default='')
    delivery_contact_phone = models.CharField(max_length=32, blank=True, default='')
    delivery_street = models.CharField(max_length=300, blank=True, default='')
    delivery_postal_code = models.CharField(max_length=10, blank=True, default='')
    delivery_city = models.CharField(max_length=120, blank=True, default='')
    delivery_country = models.CharField(max_length=80, blank=True, default='Norge')
    delivery_instructions = models.TextField(blank=True, default='')
    # A breadcrumb only — "which saved address did they pick?". NEVER read this
    # for display; that is what the flat columns above are for.
    delivery_address_source = models.ForeignKey(
        DeliveryAddress, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+',
    )

    production_note = models.TextField(blank=True, default='')  # K-22
    internal_note = models.TextField(blank=True, default='')    # admin-only

    # K-18 — ex mva. No payment in the portal; invoiced as today.
    subtotal_ex_vat = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    vat_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_inc_vat = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # Denormalised so the capacity question is one indexed Sum with no join.
    # MUST be recomputed by every path that touches lines — services.recalculate
    # is the single place that does it.
    tray_count = models.PositiveIntegerField(default=0)

    sent_at = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name='+')
    cancellation_reason = models.TextField(blank=True, default='')
    # Doubles as the send-once idempotency claim, as apps/orders does it.
    confirmation_emails_sent_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['delivery_date', 'status']),  # the capacity query
            models.Index(fields=['company', '-created_at']),   # the customer's list
            models.Index(fields=['status', 'delivery_date']),  # the admin ops list
        ]

    def __str__(self):
        return self.order_number or f'(utkast {self.pk})'

    @property
    def piece_count(self) -> int:
        return sum(line.piece_count for line in self.lines.all())

    def can_be_cancelled_by_customer(self) -> bool:
        """K-45/K-48 — the deadline AND the production state both apply."""
        if self.status not in self.CANCELLABLE_FROM:
            return False
        if not self.delivery_date:
            return True
        cfg = HorecaSettings.load()
        deadline = self.delivery_date - timedelta(days=cfg.cancel_deadline_days)
        return djtz.localdate() <= deadline


class HorecaOrderLine(models.Model):
    order = models.ForeignKey(HorecaOrder, on_delete=models.CASCADE,
                              related_name='lines')
    product = models.ForeignKey(HorecaProduct, on_delete=models.PROTECT,
                                related_name='+')
    # Snapshots — K-14, the price that applied when the order was sent stays on
    # the order, and the packing list must reproduce what was true then.
    product_name = models.CharField(max_length=200)
    product_slug = models.CharField(max_length=200, blank=True, default='')

    # K-16 — whole trays only; loose pieces are not sold.
    tray_count = models.PositiveIntegerField()
    # Per line, not per order: two trays plain and three with a logo is one
    # order with two lines and two different piece counts.
    with_logo = models.BooleanField(default=False)
    logo = models.ForeignKey(Logo, null=True, blank=True,
                             on_delete=models.PROTECT, related_name='order_lines')
    logo_name = models.CharField(max_length=120, blank=True, default='')

    pieces_per_tray = models.PositiveSmallIntegerField()
    piece_count = models.PositiveIntegerField()

    unit_price_ex_vat = models.DecimalField(max_digits=10, decimal_places=2)
    # The field that makes per-customer pricing a later change rather than a
    # rewrite: historical lines already say how their price was decided.
    price_source = models.CharField(max_length=24, default='list')
    vat_rate = models.DecimalField(max_digits=5, decimal_places=2,
                                   default=Decimal('15.00'))
    line_total_ex_vat = models.DecimalField(max_digits=12, decimal_places=2)

    allergens_snapshot = models.JSONField(default=list)
    ingredients_snapshot = models.TextField(blank=True, default='')
    line_note = models.CharField(max_length=300, blank=True, default='')

    class Meta:
        ordering = ['id']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(tray_count__gte=1),
                name='horeca_line_min_one_tray',
            ),
            # K-17: a logo tray without a logo is not orderable, and a plain
            # tray must not carry one. Enforced in the database, not just in a
            # serializer that someone might bypass.
            models.CheckConstraint(
                condition=(
                    models.Q(with_logo=False, logo__isnull=True)
                    | models.Q(with_logo=True, logo__isnull=False)
                ),
                name='horeca_line_logo_consistency',
            ),
        ]

    def __str__(self):
        return f'{self.tray_count} × {self.product_name}'


class HorecaOrderEvent(models.Model):
    """K-50 — the timeline the customer sees: who, what, and when."""

    class Source(models.TextChoices):
        PORTAL = 'portal', 'Portal'
        ADMIN = 'admin', 'Admin'
        SYSTEM = 'system', 'System'

    order = models.ForeignKey(HorecaOrder, on_delete=models.CASCADE,
                              related_name='events')
    from_status = models.CharField(max_length=16, blank=True, default='')
    to_status = models.CharField(max_length=16, blank=True, default='')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                              on_delete=models.SET_NULL, related_name='+')
    actor_name = models.CharField(max_length=150, blank=True, default='')
    source = models.CharField(max_length=16, choices=Source.choices,
                              default=Source.SYSTEM)
    note = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['created_at']
        indexes = [models.Index(fields=['order', 'created_at'])]

    def __str__(self):
        return f'{self.order_id}: {self.from_status} → {self.to_status}'
