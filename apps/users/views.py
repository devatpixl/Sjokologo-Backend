from datetime import timedelta

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import AccessToken
from .models import CustomUser
from .serializers import RegisterSerializer, AuthResponseSerializer, UserSerializer, UserUpdateSerializer, PasswordChangeSerializer


class SjokolokoTokenSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        data['user'] = UserSerializer(self.user).data
        return data

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['is_admin'] = user.is_admin
        token['name'] = user.name
        return token


class LoginView(TokenObtainPairView):
    serializer_class = SjokolokoTokenSerializer


@api_view(['POST'])
def register_view(request):
    serializer = RegisterSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.save()
        return Response(AuthResponseSerializer.for_user(user), status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def me_view(request):
    user = request.user
    if request.method == 'GET':
        return Response(UserSerializer(user).data)
    serializer = UserUpdateSerializer(user, data=request.data, partial=True)
    if serializer.is_valid():
        serializer.save()
        return Response(UserSerializer(user).data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_orders_view(request):
    from apps.orders.models import Order
    from apps.orders.serializers import OrderSerializer
    orders = Order.objects.filter(user=request.user).prefetch_related('items__product')
    return Response(OrderSerializer(orders, many=True, context={'request': request}).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def change_password_view(request):
    serializer = PasswordChangeSerializer(data=request.data, context={'request': request})
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    user = request.user
    user.set_password(serializer.validated_data['new_password'])
    user.save()
    return Response({'detail': 'Passord oppdatert.'})


GUEST_TOKEN_LIFETIME = timedelta(minutes=30)


def _issue_guest_access_token(user: CustomUser) -> str:
    """Mint a short-lived access-only JWT for a guest user.

    Guests have an unusable password and never get a refresh token —
    when the 30-minute window closes they have to re-establish via
    the guest_checkout endpoint.
    """
    token = AccessToken.for_user(user)
    token.set_exp(lifetime=GUEST_TOKEN_LIFETIME)
    token['is_admin'] = False
    token['name'] = user.name
    token['user_type'] = 'guest'
    return str(token)


@api_view(['POST'])
def guest_checkout_view(request):
    """Create or reuse a guest user for checkout.

    Body: {email, name, phone?}
    Responses:
      200 {access, user}                 — guest created or reused
      409 {code: 'EMAIL_TAKEN', detail}  — email belongs to a registered user
      400                                — validation error
    """
    email = (request.data.get('email') or '').strip().lower()
    name = (request.data.get('name') or '').strip()
    phone = (request.data.get('phone') or '').strip()

    if not email or '@' not in email:
        return Response({'detail': 'En gyldig e-post er påkrevd.'}, status=400)
    if not name:
        return Response({'detail': 'Navn er påkrevd.'}, status=400)

    existing = CustomUser.objects.filter(email__iexact=email).first()
    if existing and existing.user_type == 'registered':
        return Response(
            {'code': 'EMAIL_TAKEN',
             'detail': 'Denne e-posten har allerede en konto. Logg inn for å fortsette.'},
            status=409,
        )

    if existing and existing.user_type == 'guest':
        # Reuse the row — refresh the latest contact info so the order has it.
        existing.name = name or existing.name
        if phone:
            existing.phone = phone
        existing.save(update_fields=['name', 'phone'])
        user = existing
    else:
        user = CustomUser.objects.create(
            email=email,
            name=name,
            phone=phone,
            user_type='guest',
        )
        user.set_unusable_password()
        user.save(update_fields=['password'])

    return Response(
        {'access': _issue_guest_access_token(user), 'user': UserSerializer(user).data},
        status=200,
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def promote_view(request):
    """Convert a guest account into a registered one by setting a password.

    Refuses if the caller is already registered (idempotent). Returns the
    full registered AuthResponse so the frontend can swap its short-lived
    guest token for a normal access+refresh pair.
    """
    user = request.user
    if user.user_type != 'guest':
        return Response(
            {'detail': 'Kontoen er allerede registrert.'},
            status=409,
        )
    password = (request.data.get('password') or '')
    if len(password) < 6:
        return Response(
            {'detail': 'Passordet må være minst 6 tegn.'},
            status=400,
        )
    user.set_password(password)
    user.user_type = 'registered'
    user.save(update_fields=['password', 'user_type'])
    return Response(AuthResponseSerializer.for_user(user), status=200)
