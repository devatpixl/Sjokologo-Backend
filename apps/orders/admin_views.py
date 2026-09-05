import logging

from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status

from apps.emails import (
    send_order_delivered_email,
    send_order_packing_email,
    send_order_ready_for_pickup_email,
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


@api_view(['POST'])
@permission_classes([IsAdminUser])
def admin_order_create_label(request, order_number):
    """Buy the shipping label for an order and mark it sent.

    This is the moment the carrier first hears about the parcel. Until ops
    presses this, no consignment exists, so nobody is told "a package is on
    its way" for an order that is still in the kitchen — and an abandoned or
    unpaid checkout never costs a label.

    Refuses when: the order was not paid, a label already exists, or the
    delivery method is self-pickup (nothing to send). A consignment cannot be
    cancelled once created, so the admin UI confirms before calling this.
    """
    from django.utils import timezone as djtz

    from .profrakt import ProfraktError, create_consignment

    try:
        order = Order.objects.get(order_number=order_number)
    except Order.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)

    if order.consignment_number:
        return Response(
            {'detail': f'Fraktetikett finnes allerede ({order.consignment_number}).'},
            status=status.HTTP_409_CONFLICT,
        )
    if order.payment_status != 'CAPTURED':
        return Response(
            {'detail': 'Ordren er ikke betalt — kan ikke sendes.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if order.shipping_method == 'self-pickup':
        # Nothing to ship: tell the customer their box is ready to collect.
        if order.status == 'Sendt':
            return Response(
                {'detail': 'Kunden er allerede varslet om at ordren kan hentes.'},
                status=status.HTTP_409_CONFLICT,
            )
        order.status = 'Sendt'
        order.save(update_fields=['status', 'updated_at'])
        try:
            send_order_ready_for_pickup_email(order)
        except Exception:
            log.exception('pickup-ready email failed for %s', order.order_number)
        return Response(OrderSerializer(order, context={'request': request}).data)

    try:
        result = create_consignment(order)
    except ProfraktError as exc:
        log.exception('label creation failed for %s', order.order_number)
        return Response({'detail': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

    order.consignment_id = result['id']
    order.consignment_number = result['number']
    order.consignment_pdf_url = result['pdf'] or None
    order.tracking_url = result['tracking_url'] or None
    previous_status = order.status
    order.status = 'Sendt'
    order.save(update_fields=[
        'consignment_id', 'consignment_number', 'consignment_pdf_url',
        'tracking_url', 'status', 'updated_at',
    ])
    log.info('label created for %s: %s', order.order_number, order.consignment_number)

    # Same e-mail ops would have triggered by setting the status by hand.
    if previous_status != 'Sendt':
        try:
            send_order_shipped_email(order)
        except Exception:
            log.exception('shipped email failed for %s', order.order_number)

    return Response(OrderSerializer(order, context={'request': request}).data)
