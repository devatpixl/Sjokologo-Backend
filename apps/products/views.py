from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import Product, Truffle
from .serializers import ProductSerializer, TruffleSerializer


@api_view(['GET'])
def product_list(request):
    qs = Product.objects.filter(in_stock=True)
    category = request.query_params.get('category')
    if category:
        qs = qs.filter(category=category)
    return Response(ProductSerializer(qs, many=True, context={'request': request}).data)


@api_view(['GET'])
def product_detail(request, slug):
    try:
        product = Product.objects.get(slug=slug)
    except Product.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)
    return Response(ProductSerializer(product, context={'request': request}).data)


@api_view(['GET'])
def product_slugs(request):
    return Response(list(Product.objects.values_list('slug', flat=True)))


@api_view(['GET'])
def truffle_list(request):
    return Response(TruffleSerializer(Truffle.objects.filter(is_active=True), many=True).data)
