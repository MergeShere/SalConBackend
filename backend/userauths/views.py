from django.shortcuts import render
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework import generics

from userauths.models import User, Profile
from userauths.serializer import MyTokenObtainPairSerializer, RegistrationSerializer, PasswordResetSerializer, SetNewPasswordSerializer
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.encoding import smart_str, force_bytes, DjangoUnicodeDecodeError
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.contrib.sites.shortcuts import get_current_site
from django.urls import reverse
from .utils import send_normal_email
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.response import Response
from rest_framework import status

# Create your views here.

class MyTokenObtainPairView(TokenObtainPairView):
    serializer_class= MyTokenObtainPairSerializer

class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    permission_classes = (AllowAny, )
    serializer_class = RegistrationSerializer

class PasswordResetEmailView(generics.GenericAPIView):
    serializer_class = PasswordResetSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.data['email']
        user = User.objects.filter(email=email).first()
        if user:
            encoded_pk = urlsafe_base64_encode(force_bytes(user.pk))
            token = PasswordResetTokenGenerator().make_token(user)
            current_site = get_current_site(request).domain
            relative_link = reverse('reset-password', kwargs={'encoded_pk': encoded_pk, 'token': token})
            abs_url = f"http://{current_site}{relative_link}"
            email_body = f"Hi {user.full_name}, use the link below to reset your password: \n{abs_url}"
            data = {
                'email_body': email_body,
                'to_email': user.email,
                'email_subject': 'Reset Your Password'
            }
            send_normal_email(data)
            return Response({'message': 'Password reset email sent successfully.'}, status=status.HTTP_200_OK)
        return Response({'message': 'User with that email does not exist.'}, status=status.HTTP_404_NOT_FOUND)

class PasswordResetConfirmView(generics.GenericAPIView):
    serializer_class = SetNewPasswordSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response({'message': 'Password reset successful'}, status=status.HTTP_200_OK)

