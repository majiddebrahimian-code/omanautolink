import hashlib

from django.conf import settings
from django.core.cache import cache


def _get_public_tracking_cache_key(request):
    """
    Creates a cache key without storing the visitor's raw IP address.
    """

    client_ip = request.META.get("REMOTE_ADDR", "") or "unknown"

    hashed_ip = hashlib.sha256(client_ip.encode("utf-8")).hexdigest()

    return f"public-tracking-lookup:{hashed_ip}"


def is_public_tracking_lookup_allowed(request):
    """
    Allows only a limited number of valid tracking-code submissions
    from one IP address during a configured time window.
    """

    attempt_limit = getattr(
        settings,
        "PUBLIC_TRACKING_RATE_LIMIT_ATTEMPTS",
        10,
    )
    window_seconds = getattr(
        settings,
        "PUBLIC_TRACKING_RATE_LIMIT_WINDOW_SECONDS",
        600,
    )

    # A non-positive configuration explicitly disables the limiter.
    if attempt_limit <= 0 or window_seconds <= 0:
        return True

    cache_key = _get_public_tracking_cache_key(request)

    if cache.add(
        cache_key,
        1,
        timeout=window_seconds,
    ):
        return True

    try:
        attempt_count = cache.incr(cache_key)
    except ValueError:
        # The cache key may expire between add() and incr().
        cache.set(
            cache_key,
            1,
            timeout=window_seconds,
        )
        return True

    return attempt_count <= attempt_limit
