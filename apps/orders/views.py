from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .models import Order
from .serializers import OrderSerializer, CreateOrderSerializer


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_order(request):
    user = request.user
    serializer = CreateOrderSerializer(data=request.data, context={'user': user, 'request': request})
    if serializer.is_valid():
        order = serializer.save()
        return Response(
            OrderSerializer(order, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
def order_detail(request, order_number):
    try:
        order = Order.objects.prefetch_related('items__product').get(order_number=order_number)
    except Order.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)
    return Response(OrderSerializer(order, context={'request': request}).data)
