from decimal import Decimal
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from .models import Coupon
from .serializers import CouponValidateRequestSerializer


@api_view(['POST'])
@permission_classes([AllowAny])
def validate_coupon(request):
    """Public preview endpoint used by the storefront cart/checkout to show
    the discount before order creation. The order serializer re-validates
    server-side, so this endpoint is purely informational.
    """
    payload = CouponValidateRequestSerializer(data=request.data)
    payload.is_valid(raise_exception=True)
    code = payload.validated_data['code'].strip().upper()
    subtotal = payload.validated_data['subtotal']

    try:
        coupon = Coupon.objects.get(code=code)
    except Coupon.DoesNotExist:
        return Response({'ok': False, 'reason': 'Ukjent rabattkode.'}, status=status.HTTP_404_NOT_FOUND)

    ok, reason = coupon.is_currently_valid(subtotal=Decimal(subtotal))
    if not ok:
        return Response({'ok': False, 'reason': reason}, status=status.HTTP_400_BAD_REQUEST)

    discount = coupon.compute_discount(Decimal(subtotal))
    return Response({
        'ok': True,
        'code': coupon.code,
        'kind': coupon.kind,
        'discount': str(discount),
        'free_shipping': coupon.gives_free_shipping(),
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_coupons(request):
    """Discount codes advertised on the customer's account page.

    Only codes the admin has ticked "Vis i kundekonto" appear, and only while
    they are actually redeemable (active, inside their window, not used up).
    The min_subtotal gate is left to display — the card shows it as a
    condition rather than hiding the code.
    """
    from django.utils import timezone
    now = timezone.now()
    out = []
    for c in Coupon.objects.filter(show_in_account=True, is_active=True):
        if c.valid_from and now < c.valid_from:
            continue
        if c.valid_to and now > c.valid_to:
            continue
        if c.max_uses is not None and c.times_used >= c.max_uses:
            continue
        out.append({
            'code': c.code,
            'kind': c.kind,
            'value': str(c.value),
            'min_subtotal': str(c.min_subtotal),
            'valid_to': c.valid_to.isoformat() if c.valid_to else None,
        })
    return Response(out)
