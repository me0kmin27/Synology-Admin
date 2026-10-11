from django import forms


class MessageForm(forms.Form):
    body = forms.CharField(max_length=2000, widget=forms.Textarea)
    nonce = forms.UUIDField()
