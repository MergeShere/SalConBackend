from django.shortcuts import render
from rest_framework_simplejwt.views import TokenObtainPairView

from userauths.models import User, Profile
from userauths.serializer import MyTokenObtainPairSerializer, RegistrationSerializer
# Create your views here.
