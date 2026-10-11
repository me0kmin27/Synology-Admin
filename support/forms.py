from django import forms


class TicketForm(forms.Form):
    title = forms.CharField(max_length=160)
    body = forms.CharField(max_length=10000, widget=forms.Textarea)
