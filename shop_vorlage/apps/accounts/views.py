import logging
from django.shortcuts import render, redirect
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils.http import url_has_allowed_host_and_scheme
from .forms import LoginForm, ProfileForm

logger = logging.getLogger('apps.accounts')


def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard:index')

    form = LoginForm(request, data=request.POST or None)
    if request.method == 'POST':
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            logger.info('Login: %s', user.username)
            next_url = request.GET.get('next', '')
            if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
                return redirect(next_url)
            return redirect('dashboard:index')
        else:
            logger.warning('Login fehlgeschlagen für: %s', request.POST.get('username'))
            messages.error(request, 'Benutzername oder Passwort falsch.')

    return render(request, 'accounts/login.html', {'form': form})


def logout_view(request):
    if request.method == 'POST':
        username = request.user.username if request.user.is_authenticated else 'anon'
        logout(request)
        logger.info('Logout: %s', username)
        messages.success(request, 'Erfolgreich abgemeldet.')
    return redirect('core:home')


@login_required
def profile_view(request):
    profile = request.user.profile
    form = ProfileForm(request.POST or None, request.FILES or None, instance=profile)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Profil aktualisiert.')
        return redirect('accounts:profile')
    return render(request, 'accounts/profile.html', {'form': form})
