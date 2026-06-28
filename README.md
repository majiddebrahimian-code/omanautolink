# OmanAutoLink

سیستم رهگیری واردات خودرو — وب‌سایت و ربات تلگرام

## پیش‌نیازها

- Docker Desktop (در حال اجرا)

## راه‌اندازی — مرحله به مرحله

### گام ۱: ساخت پروژه جنگو (فقط بار اول)

این دستور پروژه جنگو را داخل Docker می‌سازد بدون اینکه پایتون روی ویندوز نصب باشد:

```powershell
docker compose run --rm web django-admin startproject config .
```

### گام ۲: بالا آوردن همه سرویس‌ها

```powershell
docker compose up --build
```

پس از اجرا، در مرورگر باز کنید: http://localhost:8000

برای دیدن صفحه پیش‌فرض جنگو باید صفحه موشک (راکت) نمایش داده شود.

### گام ۳: توقف سرویس‌ها

در ترمینال `Ctrl + C` بزنید، سپس:

```powershell
docker compose down
```

## دستورهای پرکاربرد

| کار | دستور |
|------|--------|
| بالا آوردن سرویس‌ها | `docker compose up` |
| بالا آوردن در پس‌زمینه | `docker compose up -d` |
| توقف | `docker compose down` |
| دیدن لاگ‌ها | `docker compose logs -f web` |
| اجرای دستور جنگو | `docker compose run --rm web python manage.py <command>` |
| ساخت migration | `docker compose run --rm web python manage.py makemigrations` |
| اعمال migration | `docker compose run --rm web python manage.py migrate` |
| ساخت کاربر ادمین | `docker compose run --rm web python manage.py createsuperuser` |

## معماری

- **web**: Django + DRF (وب‌سایت و API)
- **db**: PostgreSQL (پایگاه‌داده)
- **redis**: واسطه صف پیام
- **worker**: Celery (کارهای پس‌زمینه)
