from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import Tenant


class SignupForm(UserCreationForm):
    tenant = forms.ModelChoiceField(queryset=Tenant.objects.filter(signup_enabled=True), label='고객사 그룹')
