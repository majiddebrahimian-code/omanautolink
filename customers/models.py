from django.db import models


class Customer(models.Model):
    full_name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20, blank=True)
    telegram_id = models.CharField(max_length=50, blank=True, null=True, unique=True)

    def __str__(self):
        return self.full_name




class SearchLog(models.Model):
    class Source(models.TextChoices):
        WEB = 'web', 'Website'
        BOT = 'bot', 'Telegram bot'

    car = models.ForeignKey(
        'cars.Car',
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='search_logs',
    )
    customer = models.ForeignKey(
        Customer,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='search_logs',
    )
    source = models.CharField(max_length=10, choices=Source.choices)
    user_agent = models.CharField(max_length=300, blank=True)
    searched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-searched_at']

    def __str__(self):
        return f'{self.source} search at {self.searched_at:%Y-%m-%d %H:%M}'