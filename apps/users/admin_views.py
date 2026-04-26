from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from .models import CustomUser
from .serializers import UserSerializer
from .permissions import IsAdminUser
from apps.orders.models import Order
from apps.orders.serializers import OrderSerializer


@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_stats(request):
    from apps.utils.models import WaitlistEntry, ContactSubmission
    from django.db.models import Sum
    revenue = Order.objects.aggregate(total=Sum('total'))['total'] or 0
    return Response({
        'orders': Order.objects.count(),
        'users': CustomUser.objects.filter(is_admin=False).count(),
        'revenue': float(revenue),
        'waitlist': WaitlistEntry.objects.count(),
        'unread_contact': ContactSubmission.objects.filter(is_read=False).count(),
    })


@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_user_list(request):
    search = request.query_params.get('search', '')
    qs = CustomUser.objects.filter(is_admin=False)
    if search:
        qs = qs.filter(email__icontains=search) | qs.filter(name__icontains=search)
    return Response(UserSerializer(qs, many=True).data)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAdminUser])
def admin_user_detail(request, pk):
    try:
        user = CustomUser.objects.get(pk=pk)
    except CustomUser.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)

    if request.method == 'DELETE':
        if user == request.user:
            return Response({'detail': 'Du kan ikke slette deg selv.'}, status=400)
        user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    if request.method == 'PATCH':
        for f in ['name', 'email', 'is_admin']:
            if f in request.data:
                setattr(user, f, request.data[f])
        try:
            user.save()
        except Exception as e:
            return Response({'detail': str(e)}, status=400)
        return Response(UserSerializer(user).data)

    orders = Order.objects.filter(user=user).prefetch_related('items__product')
    return Response({
        'user': UserSerializer(user).data,
        'orders': OrderSerializer(orders, many=True, context={'request': request}).data,
    })
