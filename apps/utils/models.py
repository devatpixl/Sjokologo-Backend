from django.db import models


class WaitlistEntry(models.Model):
    email = models.EmailField()
    batch = models.CharField(max_length=10, default='05')
    position = models.PositiveIntegerField(editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('email', 'batch')]
        ordering = ['position']

    def save(self, *args, **kwargs):
        if not self.pk:
            count = WaitlistEntry.objects.filter(batch=self.batch).count()
            self.position = count + 1
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.email} — Batch {self.batch} #{self.position}'


class ContactSubmission(models.Model):
    name = models.CharField(max_length=200)
    email = models.EmailField()
    subject = models.CharField(max_length=300)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} — {self.subject}'


class Article(models.Model):
    CATEGORY_CHOICES = [
        ('Opprinnelse', 'Opprinnelse'),
        ('Håndverk', 'Håndverk'),
        ('Smaksnoter', 'Smaksnoter'),
        ('Folk', 'Folk'),
    ]

    slug = models.SlugField(max_length=200, unique=True)
    number = models.CharField(max_length=5)
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES)
    title = models.CharField(max_length=300)
    blurb = models.TextField()
    read_time = models.CharField(max_length=20)
    published_at = models.CharField(max_length=50)
    image = models.ImageField(upload_to='articles/', blank=True)
    is_featured = models.BooleanField(default=False)
    content = models.JSONField(default=list)

    class Meta:
        ordering = ['-number']

    def __str__(self):
        return self.title
