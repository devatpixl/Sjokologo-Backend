import uuid
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models


class CustomUserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra):
        if not email:
            raise ValueError('Email required')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault('is_admin', True)
        extra.setdefault('is_staff', True)
        extra.setdefault('is_superuser', True)
        return self.create_user(email, password, **extra)


class CustomUser(AbstractBaseUser, PermissionsMixin):
    USER_TYPE_CHOICES = [
        ('registered', 'Registered'),
        ('guest', 'Guest'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=150)
    email = models.EmailField(unique=True)
    user_type = models.CharField(
        max_length=12,
        choices=USER_TYPE_CHOICES,
        default='registered',
        db_index=True,
    )
    is_admin = models.BooleanField(default=False)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    waitlist_batches = models.JSONField(default=list)
    custom_box_count = models.PositiveIntegerField(default=0)
    # Saved shipping/contact info — used for checkout autofill
    phone = models.CharField(max_length=30, blank=True, default='')
    address = models.CharField(max_length=255, blank=True, default='')
    postal_code = models.CharField(max_length=20, blank=True, default='')
    city = models.CharField(max_length=120, blank=True, default='')
    country = models.CharField(max_length=80, blank=True, default='Norge')
    created_at = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['name']

    objects = CustomUserManager()

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.email
