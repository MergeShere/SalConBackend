from django.urls import path
from userauths import views

urlpatterns = [
    path("token/", views.MyTokenObtainPairView.as_view()),
    path("register/", views.RegisterView.as_view()),
    path('password-reset/', views.PasswordResetEmailView.as_view(), name='password-reset'),
    path('reset-password/<str:encoded_pk>/<str:token>/', views.PasswordResetConfirmView.as_view(), name='reset-password'),
]
