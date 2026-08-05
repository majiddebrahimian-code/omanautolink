from django.db import migrations


def add_blog_header_navigation(apps, schema_editor):
    """Expose the existing public blog in the editable default header menu.

    The record is deliberately seeded only when a `/blog/` destination is not
    already present.  Administrators remain free to rename, reorder, disable,
    or remove this item from the AdminLTE/Django administration interface.
    """

    HeaderNavigationItem = apps.get_model("core", "HeaderNavigationItem")

    if not HeaderNavigationItem.objects.filter(destination="/blog/").exists():
        HeaderNavigationItem.objects.create(
            label="مجله",
            destination="/blog/",
            aria_label="مشاهدهٔ مقالات و راهنمای خودرو",
            sort_order=55,
            is_enabled=True,
            open_in_new_tab=False,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0004_homequickaction"),
    ]

    operations = [
        migrations.RunPython(add_blog_header_navigation, migrations.RunPython.noop),
    ]
