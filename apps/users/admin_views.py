from django.utils import timezone as djtz
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


@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_loyalty_list(request):
    """Kundeklubb members captured by the /bli-medlem form.

    Search matches name, e-mail or phone. Ordering is newest first (the
    model's Meta default), which is what ops wants after a stand.
    """
    from .models import LoyaltyMember

    search = (request.query_params.get('search') or '').strip()
    qs = LoyaltyMember.objects.all()
    if search:
        qs = (
            qs.filter(email__icontains=search)
            | qs.filter(first_name__icontains=search)
            | qs.filter(phone__icontains=search)
        )
    return Response([
        {
            'id': str(m.id),
            'first_name': m.first_name,
            'email': m.email,
            'phone': m.phone,
            'birthday': m.birthday.isoformat() if m.birthday else None,
            'source': m.source,
            'created_at': m.created_at.isoformat(),
        }
        for m in qs
    ])


@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_loyalty_export(request):
    """The same list as a CSV download, for mailings and for keeping a copy
    off the server. Excel-friendly: semicolon separated with a BOM, so
    Norwegian characters survive a double-click on Windows.
    """
    import csv
    from io import StringIO

    from django.http import HttpResponse

    from .models import LoyaltyMember

    buf = StringIO()
    writer = csv.writer(buf, delimiter=';')
    writer.writerow(['Fornavn', 'E-post', 'Telefon', 'Bursdag', 'Kilde', 'Registrert'])
    for m in LoyaltyMember.objects.all():
        writer.writerow([
            m.first_name,
            m.email,
            m.phone,
            m.birthday.isoformat() if m.birthday else '',
            m.source,
            m.created_at.strftime('%Y-%m-%d %H:%M'),
        ])

    response = HttpResponse(
        '﻿' + buf.getvalue(), content_type='text/csv; charset=utf-8',
    )
    stamp = djtz.now().strftime('%Y%m%d')
    response['Content-Disposition'] = f'attachment; filename="kundeklubb-{stamp}.csv"'
    return response
