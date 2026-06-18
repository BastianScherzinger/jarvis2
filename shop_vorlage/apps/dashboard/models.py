from django.db import models


class DashboardWidget(models.Model):
    title = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Widget'
        verbose_name_plural = 'Widgets'

    def __str__(self):
        return self.title
