from decimal import Decimal
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
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
