from django.core.mail import send_mail
from django.conf import settings

def send_normal_email(data):
    send_mail(
        data['email_subject'],
        data['email_body'],
        settings.EMAIL_HOST_USER,
        [data['to_email']],
        fail_silently=False,
    )
