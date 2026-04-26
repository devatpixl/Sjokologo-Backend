from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import WaitlistEntry, ContactSubmission, Article
from .serializers import WaitlistSerializer, ContactSerializer, ArticleSerializer


@api_view(['POST'])
def join_waitlist(request):
    serializer = WaitlistSerializer(data=request.data)
    if serializer.is_valid():
        entry = serializer.save()
        return Response({'position': entry.position, 'batch': entry.batch}, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
def contact_form(request):
    serializer = ContactSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response({'success': True}, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
def article_list(request):
    articles = Article.objects.all()
    return Response(ArticleSerializer(articles, many=True, context={'request': request}).data)


@api_view(['GET'])
def article_detail(request, slug):
    try:
        article = Article.objects.get(slug=slug)
    except Article.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)
    return Response(ArticleSerializer(article, context={'request': request}).data)


@api_view(['GET'])
def article_slugs(request):
    return Response(list(Article.objects.values_list('slug', flat=True)))
