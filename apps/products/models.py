from django.db import models


class Product(models.Model):
    CATEGORY_CHOICES = [
        ('liten-sjokoladeboks', 'Liten sjokoladeboks'),
        ('stor-sjokoladeboks', 'Stor sjokoladeboks'),
        ('sjokoladebarer', 'Sjokoladebarer'),
    ]

    slug = models.SlugField(max_length=200, unique=True)
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES)
    size = models.CharField(max_length=50)
    price = models.DecimalField(max_digits=8, decimal_places=2)
    price_min = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    price_max = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    image = models.ImageField(upload_to='products/', blank=True)
    flavors = models.JSONField(default=list)
    blurb = models.TextField()
    in_stock = models.BooleanField(default=True)
    # Two different ideas, deliberately separate:
    #   in_stock=False  -> "Utsolgt". Still a real page, still in Google; the
    #                      shop grid hides it but an existing link works.
    #   is_active=False -> deactivated. Gone from the site entirely: no shop
    #                      listing, product URL 404s, dropped from the sitemap.
    # Defaults True so existing products are unaffected.
    is_active = models.BooleanField(default=True)
    variant_group = models.CharField(max_length=64, blank=True, default='')
    variant_label = models.CharField(max_length=64, blank=True, default='')
    batch_number = models.CharField(max_length=10)
    batch_count = models.PositiveIntegerField(default=0)
    batch_total = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['category', 'name']

    def __str__(self):
        return f'{self.name} ({self.get_category_display()})'


class Truffle(models.Model):
    id = models.CharField(max_length=10, primary_key=True)
    name = models.CharField(max_length=100)
    color = models.CharField(max_length=7)
    note = models.CharField(max_length=200)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class LabelTemplate(models.Model):
    """A saved Zebra label layout.

    Ops prints ingredient labels per product, so the editor needs to hold more
    than one: the text, font sizes and nutrition table are stored here under a
    name and loaded back when that product is made again. Kept server-side
    rather than in the browser, since several people print labels and a
    cleared browser must not lose the client's product texts.

    ``data`` is the editor's own state object, stored verbatim so new fields in
    the editor need no migration here.
    """
    name = models.CharField(max_length=120, unique=True)
    data = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name
