from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .models import Coupon
from .serializers import CouponAdminSerializer


def _require_staff(request):
    return request.user.is_authenticated and request.user.is_staff


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def admin_coupon_list(request):
    if not _require_staff(request):
        return Response({'detail': 'Forbidden'}, status=status.HTTP_403_FORBIDDEN)

    if request.method == 'GET':
        qs = Coupon.objects.all()
        return Response(CouponAdminSerializer(qs, many=True).data)

    serializer = CouponAdminSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(serializer.data, status=status.HTTP_201_CREATED)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def admin_coupon_detail(request, pk):
    if not _require_staff(request):
        return Response({'detail': 'Forbidden'}, status=status.HTTP_403_FORBIDDEN)

    try:
        coupon = Coupon.objects.get(pk=pk)
    except Coupon.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        return Response(CouponAdminSerializer(coupon).data)

    if request.method == 'PATCH':
        serializer = CouponAdminSerializer(coupon, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    coupon.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)
