from rest_framework import serializers
from .models import WaitlistEntry, ContactSubmission, Article


class WaitlistSerializer(serializers.ModelSerializer):
    class Meta:
        model = WaitlistEntry
        fields = ['id', 'email', 'batch', 'position', 'created_at']
        read_only_fields = ['id', 'position', 'created_at']

    def validate(self, data):
        if WaitlistEntry.objects.filter(email=data['email'], batch=data.get('batch', '05')).exists():
            raise serializers.ValidationError('Du er allerede på ventelisten for denne batchen.')
        return data


class ContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactSubmission
        fields = ['id', 'name', 'email', 'subject', 'message', 'is_read', 'created_at']
        read_only_fields = ['id', 'is_read', 'created_at']


class ArticleSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = Article
        fields = ['slug', 'number', 'category', 'title', 'blurb',
                  'read_time', 'published_at', 'image', 'image_url', 'is_featured', 'content']
        extra_kwargs = {'image': {'write_only': True, 'required': False}}

    def get_image_url(self, obj):
        request = self.context.get('request')
        if obj.image and request:
            return request.build_absolute_uri(obj.image.url)
        return None
