import math
import time
from functools import wraps

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.core.cache import cache
from django.core.exceptions import PermissionDenied


def portal_permissions_required(*perms):
    """Require an authenticated user with all listed permissions."""
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if request.user.is_superuser or request.user.has_perms(perms):
                return view_func(request, *args, **kwargs)
            raise PermissionDenied("You do not have permission to access this portal.")

        return _wrapped_view

    return decorator


def get_client_ip(request):
    forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded_for:
        return forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', 'unknown')


def _login_cache_keys(request, username):
    normalized_username = (username or '').strip().lower() or '__blank__'
    client_ip = get_client_ip(request)
    base_key = f'login-rate-limit:{client_ip}:{normalized_username}'
    return f'{base_key}:failures', f'{base_key}:blocked_until'


def get_login_lockout_remaining(request, username):
    _, blocked_key = _login_cache_keys(request, username)
    blocked_until = cache.get(blocked_key)
    if not blocked_until:
        return 0

    remaining = blocked_until - time.time()
    if remaining <= 0:
        cache.delete(blocked_key)
        return 0
    return math.ceil(remaining)


def register_failed_login(request, username):
    failures_key, blocked_key = _login_cache_keys(request, username)
    attempts = cache.get(failures_key, 0) + 1
    cache.set(failures_key, attempts, timeout=settings.LOGIN_FAILURE_WINDOW)

    if attempts >= settings.LOGIN_FAILURE_LIMIT:
        blocked_until = time.time() + settings.LOGIN_LOCKOUT_SECONDS
        cache.set(blocked_key, blocked_until, timeout=settings.LOGIN_LOCKOUT_SECONDS)
        cache.delete(failures_key)
        return settings.LOGIN_LOCKOUT_SECONDS

    return 0


def clear_failed_logins(request, username):
    failures_key, blocked_key = _login_cache_keys(request, username)
    cache.delete_many([failures_key, blocked_key])
