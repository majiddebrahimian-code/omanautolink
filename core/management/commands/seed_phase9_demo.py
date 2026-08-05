"""Seed clearly marked, development-only visual data for the Phase 9 homepage."""

from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from cars.models import Car, CarPhoto, CarSpinFrame
from cars.spin import assess_car_spin_frames
from core.models import HomePageConfiguration, SiteConfiguration
from core.public_site import clear_public_site_context_cache


DEMO_MARKER = "[phase9-demo]"
DEMO_SLUG_PREFIX = "demo-phase9-"
DEMO_SPIN_CAR_SLUG = "demo-phase9-blue-suv"
DEMO_ASSET_DIRECTORY = (
    Path(settings.BASE_DIR) / "core" / "demo_assets" / "phase9"
)


DEMO_VEHICLES = (
    {
        "slug": "demo-phase9-blue-suv",
        "title": "خودروی نمونهٔ آبی",
        "brand": "Demo Motors",
        "model": "Blue Crossover",
        "year": 2025,
        "color": "آبی",
        "mileage": 0,
        "price_amount": 0,
        "asset": "blue-suv.webp",
    },
    {
        "slug": "demo-phase9-black-sedan",
        "title": "سدان نمونهٔ مشکی",
        "brand": "Demo Motors",
        "model": "Black Sedan",
        "year": 2025,
        "color": "مشکی",
        "mileage": 0,
        "price_amount": 0,
        "asset": "black-sedan.webp",
    },
    {
        "slug": "demo-phase9-white-suv",
        "title": "شاسی‌بلند نمونهٔ سفید",
        "brand": "Demo Motors",
        "model": "White SUV",
        "year": 2025,
        "color": "سفید",
        "mileage": 0,
        "price_amount": 0,
        "asset": "white-suv.webp",
    },
    {
        "slug": "demo-phase9-silver-sedan",
        "title": "سدان نمونهٔ نقره‌ای",
        "brand": "Demo Motors",
        "model": "Silver Sedan",
        "year": 2025,
        "color": "نقره‌ای",
        "mileage": 0,
        "price_amount": 0,
        "asset": "silver-sedan.webp",
    },
    {
        "slug": "demo-phase9-graphite-suv",
        "title": "شاسی‌بلند نمونهٔ گرافیتی",
        "brand": "Demo Motors",
        "model": "Graphite SUV",
        "year": 2025,
        "color": "گرافیتی",
        "mileage": 0,
        "price_amount": 0,
        "asset": "graphite-suv.webp",
    },
)


HOME_TEXT_DEFAULTS = {
    "hero_eyebrow": "واردات خودرو از عمان",
    "hero_title": "خودروی منتخب خود را پیدا کنید",
    "hero_description": (
        "خودروهای موجود را بررسی کنید و پس از نهایی‌شدن فروش، "
        "وضعیت ارسال را با کد اختصاصی دنبال کنید."
    ),
    "hero_image_alt": "خودروی نمونه در نمای شبانهٔ عمان",
    "primary_cta_label": "خودروهای موجود",
    "primary_cta_destination": "/cars/",
    "secondary_cta_label": "درخواست خودرو",
    "secondary_cta_destination": "/requests/vehicle/",
    "featured_vehicles_heading": "خودروهای موجود",
    "route_title": "مسیر واردات",
    "route_origin_label": "عمان",
    "route_destination_label": "ایران",
    "route_transport_label": "حمل دریایی و زمینی",
    "route_duration_label": "بر اساس مرحلهٔ فعلی خودرو",
    "tracking_section_heading": "رهگیری خودرو",
    "tracking_section_description": (
        "پس از نهایی‌شدن فروش، تاریخچهٔ ارسال و زمان تقریبی باقی‌مانده "
        "با کد اختصاصی در دسترس است."
    ),
}


HOME_IMAGE_ASSETS = {
    "hero_background_image": (
        "hero-oman-night-empty.webp",
        "hero-oman-night-empty.webp",
    ),
    "hero_mobile_background_image": (
        "hero-mobile-oman-night-empty.webp",
        "hero-mobile-oman-night-empty.webp",
    ),
    "route_panel_image": ("oman-iran-route.webp", "oman-iran-route.webp"),
}

DEMO_SPIN_FRAME_ASSETS = tuple(
    f"spin-blue-suv-{sequence:02d}.webp" for sequence in range(1, 17)
)


class Command(BaseCommand):
    help = (
        "Create clearly marked Phase 9 demo cars and homepage media for a "
        "development environment. It never creates customers, sales, or tracking data."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Describe the changes without writing database records or media files.",
        )
        parser.add_argument(
            "--reset-demo",
            action="store_true",
            help=(
                "Explicitly restore all Phase 9 demo car and homepage values, "
                "including nonblank homepage fields."
            ),
        )
        parser.add_argument(
            "--refresh-demo-media",
            action="store_true",
            help=(
                "Replace only existing controlled Phase 9 demo media with the "
                "current optimized source assets; it never changes homepage text."
            ),
        )
        parser.add_argument(
            "--allow-non-debug",
            action="store_true",
            help=(
                "Explicitly allow execution when DEBUG is False. Use only in a "
                "disposable environment."
            ),
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        reset_demo = options["reset_demo"]
        refresh_demo_media = options["refresh_demo_media"]

        if not settings.DEBUG and not options["allow_non_debug"]:
            raise CommandError(
                "This command is development-only and refuses to run while DEBUG=False. "
                "Use --allow-non-debug only for a disposable environment."
            )

        self._validate_source_assets()

        if dry_run:
            self._report_dry_run(
                reset_demo=reset_demo,
                refresh_demo_media=refresh_demo_media,
            )
            return

        with transaction.atomic():
            created_cars = self._seed_demo_vehicles(
                reset_demo=reset_demo,
                refresh_demo_media=refresh_demo_media,
            )
            home_updated = self._seed_homepage(
                reset_demo=reset_demo,
                refresh_demo_media=refresh_demo_media,
            )

        clear_public_site_context_cache()

        self.stdout.write(
            self.style.SUCCESS(
                "Phase 9 demo seed completed: "
                f"{created_cars} vehicle(s) created; "
                f"homepage {'updated' if home_updated else 'left unchanged'}."
            )
        )
        self.stdout.write(
            "Only cars with the reserved 'demo-phase9-' slug prefix were considered. "
            "No customer, sale, hold, stage, tracking, or event data was created."
        )

    def _validate_source_assets(self):
        expected_assets = {
            *(vehicle["asset"] for vehicle in DEMO_VEHICLES),
            *(source_asset for source_asset, _ in HOME_IMAGE_ASSETS.values()),
            *DEMO_SPIN_FRAME_ASSETS,
        }
        missing_assets = sorted(
            asset_name
            for asset_name in expected_assets
            if not (DEMO_ASSET_DIRECTORY / asset_name).is_file()
        )
        if missing_assets:
            raise CommandError(
                "The Phase 9 demo assets are missing: " + ", ".join(missing_assets)
            )

    def _report_dry_run(self, *, reset_demo, refresh_demo_media):
        existing_demo_cars = Car.objects.filter(
            slug__startswith=DEMO_SLUG_PREFIX
        ).count()
        site_configuration = SiteConfiguration.objects.filter(singleton_key=1).first()
        home_page = None
        if site_configuration is not None:
            home_page = HomePageConfiguration.objects.filter(
                site_configuration=site_configuration
            ).first()

        self.stdout.write("Dry run: no database records or media files were changed.")
        self.stdout.write(
            f"Would ensure {len(DEMO_VEHICLES)} reserved demo vehicles "
            f"(currently {existing_demo_cars} with the reserved prefix)."
        )
        if site_configuration is None:
            self.stdout.write(
                "Would stop: SiteConfiguration is missing, so the public-site "
                "migrations must be applied first."
            )
            return

        if home_page is None:
            self.stdout.write("Would create homepage configuration and attach Phase 9 media.")
            return

        blank_fields = [
            field_name
            for field_name in (*HOME_TEXT_DEFAULTS, *HOME_IMAGE_ASSETS, "hero_featured_car")
            if not getattr(home_page, field_name)
        ]
        if reset_demo:
            self.stdout.write(
                "Would explicitly reset homepage text, media, and selected demo vehicle."
            )
        elif refresh_demo_media:
            self.stdout.write(
                "Would replace only controlled Phase 9 demo media with current source assets."
            )
        elif blank_fields:
            self.stdout.write(
                "Would fill only blank homepage fields: " + ", ".join(blank_fields)
            )
        else:
            self.stdout.write("Would leave all nonblank homepage fields unchanged.")

    def _seed_demo_vehicles(self, *, reset_demo, refresh_demo_media):
        created_cars = 0

        for vehicle in DEMO_VEHICLES:
            car = Car.objects.filter(slug=vehicle["slug"]).first()
            if car is not None and DEMO_MARKER not in car.description:
                raise CommandError(
                    "Refusing to alter the reserved demo slug "
                    f"'{vehicle['slug']}' because it is not marked as Phase 9 demo data."
                )

            if car is None:
                car = Car.objects.create(
                    slug=vehicle["slug"],
                    title=vehicle["title"],
                    brand=vehicle["brand"],
                    model=vehicle["model"],
                    year=vehicle["year"],
                    color=vehicle["color"],
                    mileage=vehicle["mileage"],
                    price_amount=vehicle["price_amount"],
                    description=(
                        f"{DEMO_MARKER} این خودرو فقط برای پیش‌نمایش بصری "
                        "صفحهٔ اول در محیط توسعه ایجاد شده است."
                    ),
                    seo_title=vehicle["title"],
                    seo_description="خودروی نمونهٔ نمایشی برای محیط توسعه.",
                    seo_keywords="خودروی نمونه, پیش‌نمایش توسعه",
                    status=Car.Status.FOR_SALE,
                    is_featured=True,
                    is_deleted=False,
                )
                created_cars += 1
            elif reset_demo:
                self._reset_demo_car(car=car, vehicle=vehicle)

            self._ensure_demo_photo(
                car=car,
                vehicle=vehicle,
                refresh_demo_media=reset_demo or refresh_demo_media,
            )

            if car.slug == DEMO_SPIN_CAR_SLUG:
                self._ensure_demo_spin_frames(
                    car=car,
                    refresh_demo_media=reset_demo or refresh_demo_media,
                )

        return created_cars

    def _reset_demo_car(self, *, car, vehicle):
        car.title = vehicle["title"]
        car.brand = vehicle["brand"]
        car.model = vehicle["model"]
        car.year = vehicle["year"]
        car.color = vehicle["color"]
        car.mileage = vehicle["mileage"]
        car.price_amount = vehicle["price_amount"]
        car.description = (
            f"{DEMO_MARKER} این خودرو فقط برای پیش‌نمایش بصری "
            "صفحهٔ اول در محیط توسعه ایجاد شده است."
        )
        car.seo_title = vehicle["title"]
        car.seo_description = "خودروی نمونهٔ نمایشی برای محیط توسعه."
        car.seo_keywords = "خودروی نمونه, پیش‌نمایش توسعه"
        car.status = Car.Status.FOR_SALE
        car.is_featured = True
        car.is_deleted = False
        car.save()

    def _ensure_demo_photo(self, *, car, vehicle, refresh_demo_media):
        alt_text = f"تصویر {vehicle['title']}"
        photo = CarPhoto.objects.filter(car=car, alt_text=alt_text).first()

        if photo is None:
            photo = CarPhoto(
                car=car,
                alt_text=alt_text,
                is_cover=True,
                sort_order=0,
            )
            self._copy_asset_to_field(
                instance=photo,
                field_name="image",
                source_asset=vehicle["asset"],
                destination_name=f"phase9-demo/{vehicle['asset']}",
            )
            photo.save()
            return

        if refresh_demo_media:
            photo.is_cover = True
            photo.sort_order = 0
            self._copy_asset_to_field(
                instance=photo,
                field_name="image",
                source_asset=vehicle["asset"],
                destination_name=f"phase9-demo/{vehicle['asset']}",
            )
            photo.save()
        elif not photo.image:
            self._copy_asset_to_field(
                instance=photo,
                field_name="image",
                source_asset=vehicle["asset"],
                destination_name=f"phase9-demo/{vehicle['asset']}",
            )
            photo.save(update_fields=["image"])

    def _ensure_demo_spin_frames(self, *, car, refresh_demo_media):
        for sequence, asset_name in enumerate(DEMO_SPIN_FRAME_ASSETS, start=1):
            frame = CarSpinFrame.objects.filter(car=car, sequence=sequence).first()
            if frame is None:
                frame = CarSpinFrame(car=car, sequence=sequence)
                self._copy_asset_to_field(
                    instance=frame,
                    field_name="image",
                    source_asset=asset_name,
                    destination_name=(
                        f"phase9-demo/blue-suv/frame-{sequence:02d}.webp"
                    ),
                )
                frame.save()
            elif refresh_demo_media or not frame.image:
                self._copy_asset_to_field(
                    instance=frame,
                    field_name="image",
                    source_asset=asset_name,
                    destination_name=(
                        f"phase9-demo/blue-suv/frame-{sequence:02d}.webp"
                    ),
                )
                frame.save()

        readiness = assess_car_spin_frames(car)
        if readiness.is_ready and not car.spin_360_enabled:
            car.spin_360_enabled = True
            car.save(update_fields=["spin_360_enabled", "updated_at"])
        elif not readiness.is_ready and car.spin_360_enabled:
            car.spin_360_enabled = False
            car.save(update_fields=["spin_360_enabled", "updated_at"])

    def _seed_homepage(self, *, reset_demo, refresh_demo_media):
        site_configuration = SiteConfiguration.objects.filter(singleton_key=1).first()
        if site_configuration is None:
            raise CommandError(
                "SiteConfiguration is missing. Apply the public-site migrations before "
                "seeding Phase 9 demo media."
            )
        home_page, _ = HomePageConfiguration.objects.get_or_create(
            site_configuration=site_configuration,
        )
        selected_car = Car.objects.get(slug="demo-phase9-blue-suv")
        changed_fields = []

        for field_name, default_value in HOME_TEXT_DEFAULTS.items():
            if reset_demo or not getattr(home_page, field_name):
                setattr(home_page, field_name, default_value)
                changed_fields.append(field_name)

        if reset_demo or not home_page.hero_featured_car_id:
            home_page.hero_featured_car = selected_car
            changed_fields.append("hero_featured_car")

        for field_name, (source_asset, destination_asset) in HOME_IMAGE_ASSETS.items():
            field = getattr(home_page, field_name)
            can_refresh_existing_demo_media = (
                refresh_demo_media
                and field
                and self._is_controlled_demo_media(field.name)
            )
            if reset_demo or not field or can_refresh_existing_demo_media:
                self._copy_asset_to_field(
                    instance=home_page,
                    field_name=field_name,
                    source_asset=source_asset,
                    destination_name=f"phase9-demo/{destination_asset}",
                )
                changed_fields.append(field_name)

        if changed_fields:
            home_page.save()
            return True
        return False

    def _copy_asset_to_field(
        self,
        *,
        instance,
        field_name,
        source_asset,
        destination_name,
    ):
        source_path = DEMO_ASSET_DIRECTORY / source_asset
        field = getattr(instance, field_name)
        target_name = instance._meta.get_field(field_name).generate_filename(
            instance,
            destination_name,
        )
        if field and field.name and self._is_controlled_demo_media(
            field.name,
            target_name=target_name,
        ):
            # FileSystemStorage otherwise appends a random suffix on every
            # reset.  We only delete a path under our own controlled demo
            # prefix; real administrator-uploaded media is never removed.
            field.storage.delete(field.name)
        with source_path.open("rb") as source_file:
            field.save(
                destination_name,
                File(source_file),
                save=False,
            )

    @staticmethod
    def _is_controlled_demo_media(file_name, *, target_name=None):
        controlled_prefixes = ("cars/phase9-demo/", "site/home/phase9-demo/")
        if target_name:
            controlled_prefixes = (
                str(Path(target_name).parent).replace("\\", "/") + "/",
            )
        return str(file_name).replace("\\", "/").startswith(controlled_prefixes)
