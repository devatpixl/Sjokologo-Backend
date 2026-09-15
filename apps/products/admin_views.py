from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from .models import Product, Truffle
from .serializers import ProductSerializer, TruffleSerializer
from apps.users.permissions import IsAdminUser
from .storefront import revalidate_storefront


@api_view(['GET', 'POST'])
@permission_classes([IsAdminUser])
def admin_product_list(request):
    if request.method == 'GET':
        category = request.query_params.get('category')
        stock = request.query_params.get('in_stock')
        # Sellable products first: ops asked for the green ones on top, so the
        # list opens on what can actually be sold rather than on sold-out rows.
        qs = Product.objects.all().order_by('-in_stock', 'category', 'name')
        if category:
            qs = qs.filter(category=category)
        if stock in ('true', 'false'):
            qs = qs.filter(in_stock=(stock == 'true'))
        return Response(ProductSerializer(qs, many=True, context={'request': request}).data)

    serializer = ProductSerializer(data=request.data, context={'request': request})
    if serializer.is_valid():
        product = serializer.save()
        revalidate_storefront(getattr(product, 'slug', None))
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
@permission_classes([IsAdminUser])
def admin_product_detail(request, pk):
    try:
        product = Product.objects.get(pk=pk)
    except Product.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)

    if request.method == 'GET':
        return Response(ProductSerializer(product, context={'request': request}).data)

    if request.method == 'DELETE':
        slug = product.slug
        product.delete()
        revalidate_storefront(slug)
        return Response(status=status.HTTP_204_NO_CONTENT)

    partial = request.method == 'PATCH'
    serializer = ProductSerializer(product, data=request.data, partial=partial, context={'request': request})
    if serializer.is_valid():
        product = serializer.save()
        # Drop the storefront's cached pages so "Utsolgt" / "Aktiv" show up on
        # the next refresh rather than up to a minute later.
        revalidate_storefront(getattr(product, 'slug', None))
        return Response(serializer.data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'POST'])
@permission_classes([IsAdminUser])
def admin_truffle_list(request):
    if request.method == 'GET':
        return Response(TruffleSerializer(Truffle.objects.all(), many=True).data)

    serializer = TruffleSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
@permission_classes([IsAdminUser])
def admin_truffle_detail(request, pk):
    try:
        truffle = Truffle.objects.get(pk=pk)
    except Truffle.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)

    if request.method == 'GET':
        return Response(TruffleSerializer(truffle).data)

    if request.method == 'DELETE':
        truffle.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    partial = request.method == 'PATCH'
    serializer = TruffleSerializer(truffle, data=request.data, partial=partial)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
