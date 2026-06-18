import logging
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from apps.core.models import PageVisit

logger = logging.getLogger('apps.dashboard')


@login_required
def index(request):
    context = {
        'total_users': User.objects.count(),
        'total_visits': PageVisit.objects.count(),
        'recent_visits': PageVisit.objects.select_related()[:10],
    }
    logger.debug('Dashboard geladen von %s', request.user.username)
    return render(request, 'dashboard/index.html', context)
