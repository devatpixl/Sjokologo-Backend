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

    def __str__(self):
        return self.name
