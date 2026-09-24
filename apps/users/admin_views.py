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
        # Excludes HORECA accounts only — they are counted in their own
        # dashboard, and mixing them in overstates the shop's reach.
        # Deliberately an exclude() rather than user_type='registered': that
        # would ALSO drop guest-checkout rows, which have always been counted
        # here. Moving that number is a separate decision, not a side effect
        # of adding a B2B portal.
        'users': CustomUser.objects.filter(is_admin=False)
                                   .exclude(user_type='horeca').count(),
        'revenue': float(revenue),
        'waitlist': WaitlistEntry.objects.count(),
        'unread_contact': ContactSubmission.objects.filter(is_read=False).count(),
        'new_customers': CustomUser.objects.filter(
            is_admin=False, user_type='registered', is_seen=False
        ).count(),
        # B2B work queues, for the sidebar badges. Imported here rather than at
        # module scope so this view keeps working if the horeca app is ever
        # removed — the consumer dashboard should not die with it.
        **_horeca_queue_counts(),
    })


def _horeca_queue_counts():
    try:
        from apps.horeca.models import Company, Logo
        return {
            'horeca_pending_companies': Company.objects.filter(
                status=Company.Status.PENDING).count(),
            'horeca_pending_logos': Logo.objects.filter(
                status=Logo.Status.PENDING, is_archived=False).count(),
        }
    except Exception:
        return {'horeca_pending_companies': 0, 'horeca_pending_logos': 0}


@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_user_list(request):
    search = request.query_params.get('search', '')
    qs = CustomUser.objects.filter(is_admin=False)
    if search:
        qs = qs.filter(email__icontains=search) | qs.filter(name__icontains=search)
    return Response(UserSerializer(qs, many=True).data)


@api_view(['POST'])
@permission_classes([IsAdminUser])
def admin_users_mark_seen(request):
    """Dismiss the new-customer badge.

    Opening the customer list deliberately does not clear it — ops asked for a
    notification that survives a glance — so this is the only thing that does.
    Marks every registered customer seen; ``ids`` narrows it to a subset if a
    per-row dismiss is ever added to the UI.
    """
    qs = CustomUser.objects.filter(is_admin=False, user_type='registered', is_seen=False)
    ids = request.data.get('ids')
    if ids:
        qs = qs.filter(pk__in=ids)
    cleared = qs.update(is_seen=True)
    return Response({'cleared': cleared})


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
