from decimal import Decimal
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from .member import get_active_member_coupon, member_coupon_payload
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


@api_view(['GET'])
@permission_classes([AllowAny])
def member_coupon(request):
    """The discount the checkout applies automatically for a signed-in customer.

    Anyone may ask *whether* there is an offer and how big it is, because the
    checkout has to advertise "log in and get 20%" to someone who is not signed
    in yet, and that claim must come from the live coupon rather than a hardcoded
    string. The redeemable **code** is only returned to a signed-in customer:
    it is worth 20% with no usage limit, so it is not handed to anonymous
    callers.

    204 means there is no live offer, which is how the storefront knows to stop
    promising one.
    """
    coupon = get_active_member_coupon()
    if coupon is None:
        return Response(status=status.HTTP_204_NO_CONTENT)
    payload = member_coupon_payload(coupon)
    if not request.user.is_authenticated:
        payload.pop('code', None)
    return Response(payload)
