"""Saved Zebra label templates, managed from the admin's Etiketter page."""

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.users.permissions import IsAdminUser

from .models import LabelTemplate


def _as_dict(t: LabelTemplate) -> dict:
    return {
        'id': t.id,
        'name': t.name,
        'data': t.data,
        'updated_at': t.updated_at.isoformat(),
    }


@api_view(['GET', 'POST'])
@permission_classes([IsAdminUser])
def admin_label_list(request):
    if request.method == 'GET':
        return Response([_as_dict(t) for t in LabelTemplate.objects.all()])

    name = (request.data.get('name') or '').strip()
    data = request.data.get('data')
    if not name:
        return Response({'detail': 'Gi etiketten et navn.'}, status=status.HTTP_400_BAD_REQUEST)
    if not isinstance(data, dict):
        return Response({'detail': 'Ugyldig etikettdata.'}, status=status.HTTP_400_BAD_REQUEST)

    # Saving under an existing name overwrites it, which is what "lagre" means
    # to someone correcting a typo in a label they use every week.
    template, _ = LabelTemplate.objects.update_or_create(name=name, defaults={'data': data})
    return Response(_as_dict(template), status=status.HTTP_201_CREATED)


@api_view(['DELETE'])
@permission_classes([IsAdminUser])
def admin_label_detail(request, pk):
    try:
        template = LabelTemplate.objects.get(pk=pk)
    except LabelTemplate.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
    template.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)
