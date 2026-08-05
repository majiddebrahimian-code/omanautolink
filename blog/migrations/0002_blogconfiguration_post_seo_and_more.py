# Generated manually for the Phase 10 public-blog architecture.

import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


def create_blog_configurations(apps, schema_editor):
    SiteConfiguration = apps.get_model("core", "SiteConfiguration")
    BlogConfiguration = apps.get_model("blog", "BlogConfiguration")

    for site_configuration in SiteConfiguration.objects.all().iterator():
        BlogConfiguration.objects.get_or_create(
            site_configuration_id=site_configuration.pk,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("blog", "0001_initial"),
        ("core", "0004_homequickaction"),
    ]

    operations = [
        migrations.CreateModel(
            name="BlogConfiguration",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "listing_eyebrow",
                    models.CharField(
                        default="راهنما و تجربه",
                        max_length=120,
                        verbose_name="تیتر کوتاه فهرست وبلاگ",
                    ),
                ),
                (
                    "listing_title",
                    models.CharField(
                        default="مجلهٔ واردات خودرو",
                        max_length=180,
                        verbose_name="عنوان فهرست وبلاگ",
                    ),
                ),
                (
                    "listing_description",
                    models.TextField(
                        default="محتوای کاربردی برای انتخاب خودرو و درک فرایند واردات و تحویل.",
                        verbose_name="توضیح فهرست وبلاگ",
                    ),
                ),
                (
                    "default_meta_title",
                    models.CharField(
                        blank=True,
                        max_length=160,
                        verbose_name="عنوان پیش‌فرض سئوی وبلاگ",
                    ),
                ),
                (
                    "default_meta_description",
                    models.CharField(
                        blank=True,
                        max_length=320,
                        verbose_name="توضیح پیش‌فرض سئوی وبلاگ",
                    ),
                ),
                (
                    "default_meta_keywords",
                    models.CharField(
                        blank=True,
                        max_length=500,
                        verbose_name="کلیدواژه‌های پیش‌فرض وبلاگ",
                    ),
                ),
                (
                    "default_og_image",
                    models.ImageField(
                        blank=True,
                        null=True,
                        upload_to="blog/seo/",
                        validators=[
                            django.core.validators.FileExtensionValidator(
                                ["png", "jpg", "jpeg", "webp"]
                            )
                        ],
                        verbose_name="تصویر پیش‌فرض اشتراک‌گذاری وبلاگ",
                    ),
                ),
                (
                    "articles_per_page",
                    models.PositiveSmallIntegerField(
                        default=12,
                        validators=[
                            django.core.validators.MinValueValidator(1),
                            django.core.validators.MaxValueValidator(48),
                        ],
                        verbose_name="تعداد مطلب در هر صفحه",
                    ),
                ),
                (
                    "site_configuration",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="blog_configuration",
                        to="core.siteconfiguration",
                        verbose_name="تنظیمات اصلی سایت",
                    ),
                ),
            ],
            options={
                "verbose_name": "تنظیمات وبلاگ",
                "verbose_name_plural": "تنظیمات وبلاگ",
            },
        ),
        migrations.AlterModelOptions(
            name="category",
            options={
                "verbose_name": "دسته‌بندی وبلاگ",
                "verbose_name_plural": "دسته‌بندی‌های وبلاگ",
            },
        ),
        migrations.AlterModelOptions(
            name="post",
            options={
                "ordering": ["-published_at", "-created_at"],
                "permissions": [
                    ("publish_post", "Can publish and unpublish blog posts"),
                ],
                "verbose_name": "مطلب وبلاگ",
                "verbose_name_plural": "مطالب وبلاگ",
            },
        ),
        migrations.AddField(
            model_name="post",
            name="cover_image_alt",
            field=models.CharField(
                blank=True,
                max_length=180,
                verbose_name="متن جایگزین تصویر کاور",
            ),
        ),
        migrations.AddField(
            model_name="post",
            name="excerpt",
            field=models.TextField(blank=True, verbose_name="خلاصهٔ مطلب"),
        ),
        migrations.AddField(
            model_name="post",
            name="meta_description",
            field=models.CharField(blank=True, max_length=320, verbose_name="توضیح سئو"),
        ),
        migrations.AddField(
            model_name="post",
            name="meta_keywords",
            field=models.CharField(blank=True, max_length=500, verbose_name="کلیدواژه‌های سئو"),
        ),
        migrations.AddField(
            model_name="post",
            name="og_image",
            field=models.ImageField(
                blank=True,
                null=True,
                upload_to="blog/seo/",
                validators=[
                    django.core.validators.FileExtensionValidator(
                        ["png", "jpg", "jpeg", "webp"]
                    )
                ],
                verbose_name="تصویر اشتراک‌گذاری",
            ),
        ),
        migrations.AddField(
            model_name="post",
            name="seo_title",
            field=models.CharField(blank=True, max_length=160, verbose_name="عنوان سئو"),
        ),
        migrations.AddField(
            model_name="post",
            name="updated_at",
            field=models.DateTimeField(
                auto_now=True,
                default=django.utils.timezone.now,
                verbose_name="آخرین ویرایش",
            ),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name="category",
            name="name",
            field=models.CharField(max_length=120, verbose_name="نام دسته‌بندی"),
        ),
        migrations.AlterField(
            model_name="category",
            name="slug",
            field=models.SlugField(
                allow_unicode=True,
                max_length=140,
                unique=True,
                verbose_name="نامک",
            ),
        ),
        migrations.AlterField(
            model_name="post",
            name="author",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="posts",
                to=settings.AUTH_USER_MODEL,
                verbose_name="نویسنده",
            ),
        ),
        migrations.AlterField(
            model_name="post",
            name="category",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="posts",
                to="blog.category",
                verbose_name="دسته‌بندی",
            ),
        ),
        migrations.AlterField(
            model_name="post",
            name="content",
            field=models.TextField(verbose_name="متن مطلب"),
        ),
        migrations.AlterField(
            model_name="post",
            name="cover_image",
            field=models.ImageField(
                blank=True,
                null=True,
                upload_to="blog/",
                validators=[
                    django.core.validators.FileExtensionValidator(
                        ["png", "jpg", "jpeg", "webp"]
                    )
                ],
                verbose_name="تصویر کاور",
            ),
        ),
        migrations.AlterField(
            model_name="post",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, verbose_name="زمان ایجاد"),
        ),
        migrations.AlterField(
            model_name="post",
            name="published_at",
            field=models.DateTimeField(
                blank=True,
                db_index=True,
                null=True,
                verbose_name="زمان انتشار",
            ),
        ),
        migrations.AlterField(
            model_name="post",
            name="slug",
            field=models.SlugField(
                allow_unicode=True,
                max_length=240,
                unique=True,
                verbose_name="نامک",
            ),
        ),
        migrations.AlterField(
            model_name="post",
            name="status",
            field=models.CharField(
                choices=[("draft", "پیش‌نویس"), ("published", "منتشرشده")],
                db_index=True,
                default="draft",
                max_length=10,
                verbose_name="وضعیت انتشار",
            ),
        ),
        migrations.AlterField(
            model_name="post",
            name="title",
            field=models.CharField(max_length=220, verbose_name="عنوان"),
        ),
        migrations.RunPython(create_blog_configurations, migrations.RunPython.noop),
    ]
