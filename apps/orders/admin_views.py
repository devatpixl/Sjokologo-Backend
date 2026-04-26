from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from .models import Order
from .serializers import OrderSerializer, OrderStatusSerializer
from apps.users.permissions import IsAdminUser


@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_order_list(request):
    qs = Order.objects.prefetch_related('items__product').select_related('user')
    order_status = request.query_params.get('status')
    search = request.query_params.get('search', '')
    if order_status:
        qs = qs.filter(status=order_status)
    if search:
        qs = qs.filter(order_number__icontains=search) | qs.filter(ship_email__icontains=search) | qs.filter(ship_last_name__icontains=search)
    return Response(OrderSerializer(qs, many=True, context={'request': request}).data)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAdminUser])
def admin_order_detail(request, order_number):
    try:
        order = Order.objects.prefetch_related('items__product').select_related('user').get(order_number=order_number)
    except Order.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)

    if request.method == 'GET':
        return Response(OrderSerializer(order, context={'request': request}).data)

    if request.method == 'DELETE':
        order.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    serializer = OrderStatusSerializer(order, data=request.data, partial=True)
    if serializer.is_valid():
        serializer.save()
        return Response(OrderSerializer(order, context={'request': request}).data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
