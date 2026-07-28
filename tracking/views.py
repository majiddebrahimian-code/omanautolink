import logging

from django.core.exceptions import ValidationError
from django.shortcuts import render

from customers.models import SearchLog
from customers.services import record_successful_tracking_lookup

from .forms import PublicTrackingLookupForm
from .rate_limits import is_public_tracking_lookup_allowed
from .services import get_public_tracking_data

logger = logging.getLogger(__name__)


def public_tracking_lookup(request):
    tracking_data = None
    lookup_error = None

    if request.method == "POST":
        form = PublicTrackingLookupForm(request.POST)

        if form.is_valid():
            if not is_public_tracking_lookup_allowed(request):
                lookup_error = (
                    "تعداد تلاش‌های شما بیش از حد مجاز است. "
                    "لطفاً چند دقیقه دیگر دوباره تلاش کنید."
                )
            else:
                try:
                    tracking_data = get_public_tracking_data(
                        tracking_code=form.cleaned_data["tracking_code"],
                    )
                except ValidationError:
                    # Never expose internal service or database details publicly.
                    lookup_error = "اطلاعات رهگیری با این کد پیدا نشد."
                else:
                    try:
                        record_successful_tracking_lookup(
                            tracking_code=tracking_data["tracking_code"],
                            source=SearchLog.Source.WEB,
                            user_agent=request.META.get(
                                "HTTP_USER_AGENT",
                                "",
                            ),
                        )
                    except Exception:
                        # Tracking remains available even if audit logging fails.
                        # Do not log the sensitive tracking code.
                        logger.exception(
                            "Could not record a successful public tracking lookup."
                        )
    else:
        form = PublicTrackingLookupForm()

    return render(
        request,
        "tracking/public_lookup.html",
        {
            "form": form,
            "tracking_data": tracking_data,
            "lookup_error": lookup_error,
        },
    )
