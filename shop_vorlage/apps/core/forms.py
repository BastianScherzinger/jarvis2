from django import forms
from .models import Anfrage


class AnfrageForm(forms.ModelForm):
    class Meta:
        model = Anfrage
        fields = ['leistung', 'zusatz_info', 'name', 'email', 'telefon', 'adresse']
        widgets = {
            'zusatz_info': forms.Textarea(attrs={
                'placeholder': 'Beschreiben Sie kurz Ihr Sanierungsprojekt – Umfang, Zeitraum, besondere Anforderungen ...',
                'rows': 4,
            }),
            'name': forms.TextInput(attrs={'placeholder': 'Vor- und Nachname'}),
            'email': forms.EmailInput(attrs={'placeholder': 'ihre@email.de'}),
            'telefon': forms.TextInput(attrs={'placeholder': '+49 ...'}),
            'adresse': forms.TextInput(attrs={'placeholder': 'Objektadresse (Straße, PLZ, Ort)'}),
        }
