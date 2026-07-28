from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render

from .forms import PublicCustomVehicleRequestForm
from .models import CustomVehicleRequest
from .services import create_custom_vehicle_request


def _add_service_validation_errors(form, error):
    """
    Maps shared-service validation errors to visible form errors.
    """

    if hasattr(error, "message_dict"):
        for field_name, messages in error.message_dict.items():
            target_field = field_name if field_name in form.fields else None

            for message in messages:
                form.add_error(target_field, message)

        return

    for message in error.messages:
        form.add_error(None, message)


def public_custom_vehicle_request_create(request):
    if request.method == "POST":
        form = PublicCustomVehicleRequestForm(request.POST)

        if form.is_valid():
            try:
                create_custom_vehicle_request(
                    full_name=form.cleaned_data["full_name"],
                    phone=form.cleaned_data["phone"],
                    telegram_id=form.cleaned_data["telegram_id"],
                    desired_vehicle_description=form.cleaned_data[
                        "desired_vehicle_description"
                    ],
                    preferred_brand=form.cleaned_data["preferred_brand"],
                    preferred_model=form.cleaned_data["preferred_model"],
                    preferred_year_from=form.cleaned_data["preferred_year_from"],
                    preferred_year_to=form.cleaned_data["preferred_year_to"],
                    budget_amount=form.cleaned_data["budget_amount"],
                    preferred_color=form.cleaned_data["preferred_color"],
                    notes=form.cleaned_data["notes"],
                    source=CustomVehicleRequest.Source.WEBSITE,
                )
            except ValidationError as error:
                _add_service_validation_errors(form, error)
            else:
                return redirect("customers:custom_vehicle_request_success")
    else:
        form = PublicCustomVehicleRequestForm()

    return render(
        request,
        "customers/custom_vehicle_request_form.html",
        {
            "form": form,
        },
    )


def public_custom_vehicle_request_success(request):
    return render(
        request,
        "customers/custom_vehicle_request_success.html",
    )
