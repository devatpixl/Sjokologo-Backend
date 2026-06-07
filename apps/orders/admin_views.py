import logging

from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status

from apps.emails import (
    send_order_delivered_email,
    send_order_packing_email,
    send_order_shipped_email,
)
from apps.users.permissions import IsAdminUser

from .models import Order
from .serializers import OrderSerializer, OrderStatusSerializer

log = logging.getLogger(__name__)

# Map each fulfillment-status target to the email helper that should fire
# when the order transitions *into* that status. Only emits one email per
# real change; idempotent saves (PATCH same status) emit nothing.
_STATUS_EMAIL_HANDLERS = {
    'Pakkes': send_order_packing_email,
    'Sendt':  send_order_shipped_email,
    'Levert': send_order_delivered_email,
}


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

    previous_status = order.status
    serializer = OrderStatusSerializer(order, data=request.data, partial=True)
    if serializer.is_valid():
        serializer.save()
        new_status = order.status
        if new_status != previous_status:
            handler = _STATUS_EMAIL_HANDLERS.get(new_status)
            if handler is not None:
                try:
                    handler(order)
                except Exception:
                    log.exception(
                        '%s email crashed for %s', new_status, order.order_number
                    )
        return Response(OrderSerializer(order, context={'request': request}).data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
