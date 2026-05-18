from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from .models import BundleRule
from .serializers import BundleRulePublicSerializer


@api_view(['GET'])
@permission_classes([AllowAny])
def active_bundles(request):
    """Storefront fetches this once on mount to know which auto-bundles to
    render badges for and to compute the cart-side preview. The server-side
    order serializer re-applies the rule on submit, so the storefront
    response is purely informational.
    """
    qs = BundleRule.objects.filter(is_active=True)
    rules = [r for r in qs if r.is_currently_active()]
    return Response(BundleRulePublicSerializer(rules, many=True).data)
