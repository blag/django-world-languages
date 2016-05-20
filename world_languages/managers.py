from django.db import models
from django.utils.timezone import now


class AlternativeNameManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().exclude(type='link')


class InUseManager(models.Manager):
    def in_use(self):
        return super().get_queryset().filter(start__lt=now(), end__gt=now()).exclude(in_use=False)
