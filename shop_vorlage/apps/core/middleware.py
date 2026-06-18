import logging
from .models import PageVisit

logger = logging.getLogger('apps.core')

_SKIP_PREFIXES = ('/static/', '/media/', '/favicon.ico')


def _anonymize_ip(ip):
    if not ip:
        return None
    if ':' in ip:
        return ip.rsplit(':', 1)[0] + ':0'
    parts = ip.split('.')
    if len(parts) == 4:
        return '.'.join(parts[:3]) + '.0'
    return None


class RequestLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        skip = any(path.startswith(p) for p in _SKIP_PREFIXES)

        if not skip:
            user = getattr(request, 'user', None)
            uid = user.pk if (user and user.is_authenticated) else 'anon'
            logger.debug('%s %s [user=%s]', request.method, path, uid)

        response = self.get_response(request)

        if not skip and request.method == 'GET' and response.status_code == 200:
            try:
                PageVisit.objects.create(
                    path=path[:512],
                    ip_address=_anonymize_ip(request.META.get('REMOTE_ADDR')),
                    user_agent=request.META.get('HTTP_USER_AGENT', '')[:512],
                )
            except Exception as e:
                logger.warning('PageVisit konnte nicht gespeichert werden: %s', e)

        return response
