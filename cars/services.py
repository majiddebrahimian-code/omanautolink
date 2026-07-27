import secrets
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Car, VehicleHold
from customers.models import Customer
from tracking.services import start_tracking_for_sold_car


def generate_tracking_code():
    """
    Generates a random public tracking code.

    The code is intentionally hard to guess because customers use it
    to view shipment progress without a customer login.
    """

    while True:
        code = f"OAL-{secrets.token_urlsafe(16)}"

        if not Car.objects.filter(tracking_code=code).exists():
            return code


@transaction.atomic
def mark_vehicle_as_sold(
    *,
    car_id,
    actor,
    full_name,
    phone,
    telegram_id,
    source="system",
):
    """
    Converts an active vehicle hold into a completed sale.

    A customer is created or found by Telegram ID.
    A unique tracking code is assigned to the vehicle.
    """

    if not full_name.strip():
        raise ValidationError("Customer full name is required.")

    if not phone.strip():
        raise ValidationError("Customer phone number is required.")

    if not telegram_id.strip():
        raise ValidationError("Customer Telegram ID is required.")

    car = Car.objects.select_for_update().get(pk=car_id)

    if car.status != Car.Status.ON_HOLD:
        raise ValidationError("Only a vehicle on hold can be marked as sold.")

    active_hold = (
        VehicleHold.objects.select_for_update().filter(car=car, is_active=True).first()
    )

    if active_hold is None:
        raise ValidationError("This vehicle does not have an active hold.")

    customer, _ = Customer.objects.get_or_create(
        telegram_id=telegram_id.strip(),
        defaults={
            "full_name": full_name.strip(),
            "phone": phone.strip(),
        },
    )

    car.customer = customer
    car.status = Car.Status.SOLD
    car.tracking_code = generate_tracking_code()
    car.save(
        update_fields=[
            "customer",
            "status",
            "tracking_code",
        ]
    )

    active_hold.is_active = False
    active_hold.released_at = timezone.now()
    active_hold.released_by = actor
    active_hold.release_note = "Converted to sold."
    active_hold.save(
        update_fields=[
            "is_active",
            "released_at",
            "released_by",
            "release_note",
        ]
    )

    start_tracking_for_sold_car(
        car=car,
        actor=actor,
        source=source,
    )

    car.refresh_from_db()

    return car


@transaction.atomic
def publish_vehicle_for_sale(*, car_id):
    """
    Publishes a draft vehicle and makes it available for sale.
    """

    car = Car.objects.select_for_update().get(pk=car_id)

    if car.is_deleted:
        raise ValidationError("A deleted vehicle cannot be published.")

    if car.status != Car.Status.DRAFT:
        raise ValidationError("Only a draft vehicle can be published for sale.")

    car.status = Car.Status.FOR_SALE
    car.save(update_fields=["status"])

    return car


@transaction.atomic
def place_vehicle_on_hold(
    *,
    car_id,
    actor,
    customer_name="",
    customer_phone="",
    expires_at=None,
):
    """
    Creates an active temporary hold for a vehicle.

    The vehicle must currently be available for sale.
    """

    car = Car.objects.select_for_update().get(pk=car_id)

    if car.status != Car.Status.FOR_SALE:
        raise ValidationError("Only a vehicle that is for sale can be placed on hold.")

    if VehicleHold.objects.filter(car=car, is_active=True).exists():
        raise ValidationError("This vehicle already has an active hold.")

    hold = VehicleHold.objects.create(
        car=car,
        customer_name=customer_name,
        customer_phone=customer_phone,
        created_by=actor,
        expires_at=expires_at,
    )

    car.status = Car.Status.ON_HOLD
    car.save(update_fields=["status"])

    return hold


@transaction.atomic
def release_vehicle_hold(*, hold_id, actor, release_note=""):
    """
    Releases an active vehicle hold and returns the vehicle to For Sale.
    """

    hold = VehicleHold.objects.select_for_update().get(pk=hold_id)
    car = Car.objects.select_for_update().get(pk=hold.car_id)

    if not hold.is_active:
        raise ValidationError("This vehicle hold has already been released.")

    hold.is_active = False
    hold.released_at = timezone.now()
    hold.released_by = actor
    hold.release_note = release_note
    hold.save(
        update_fields=[
            "is_active",
            "released_at",
            "released_by",
            "release_note",
        ]
    )

    car.status = Car.Status.FOR_SALE
    car.save(update_fields=["status"])

    return hold
