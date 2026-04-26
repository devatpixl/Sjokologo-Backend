from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from .models import WaitlistEntry, ContactSubmission
from .serializers import WaitlistSerializer, ContactSerializer
from apps.users.permissions import IsAdminUser


@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_waitlist(request):
    batch = request.query_params.get('batch')
    qs = WaitlistEntry.objects.all()
    if batch:
        qs = qs.filter(batch=batch)
    return Response(WaitlistSerializer(qs, many=True).data)


@api_view(['DELETE'])
@permission_classes([IsAdminUser])
def admin_waitlist_detail(request, pk):
    try:
        entry = WaitlistEntry.objects.get(pk=pk)
    except WaitlistEntry.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)
    entry.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_contact_list(request):
    qs = ContactSubmission.objects.all()
    is_read = request.query_params.get('is_read')
    if is_read is not None:
        qs = qs.filter(is_read=is_read.lower() == 'true')
    return Response(ContactSerializer(qs, many=True).data)


@api_view(['PATCH', 'DELETE'])
@permission_classes([IsAdminUser])
def admin_contact_detail(request, pk):
    try:
        submission = ContactSubmission.objects.get(pk=pk)
    except ContactSubmission.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)

    if request.method == 'DELETE':
        submission.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    submission.is_read = True
    submission.save()
    return Response(ContactSerializer(submission).data)
