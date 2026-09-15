from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import Product, Truffle
from .serializers import ProductSerializer, TruffleSerializer


@api_view(['GET'])
def product_list(request):
    qs = Product.objects.filter(in_stock=True, is_active=True)
    category = request.query_params.get('category')
    if category:
        qs = qs.filter(category=category)
    return Response(ProductSerializer(qs, many=True, context={'request': request}).data)


@api_view(['GET'])
def product_detail(request, slug):
    try:
        # Deactivated products 404 on purpose — that is what makes the
        # "deactivate" switch remove them from the site entirely, rather than
        # just from the shop grid the way "Utsolgt" does.
        product = Product.objects.get(slug=slug, is_active=True)
    except Product.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)
    return Response(ProductSerializer(product, context={'request': request}).data)


@api_view(['GET'])
def product_slugs(request):
    return Response(list(Product.objects.filter(is_active=True).values_list('slug', flat=True)))


@api_view(['GET'])
def truffle_list(request):
    return Response(TruffleSerializer(Truffle.objects.filter(is_active=True), many=True).data)
