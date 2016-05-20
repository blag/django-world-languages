from django.apps import AppConfig
from django.db.models.signals import post_save, pre_delete


def save_symmetric_lexical_similarity(sender, instance, created, raw, **kwargs):
    if raw:
        return

    if created:
        # Create the reflexive similarity, avoiding infinite recursion
        ls = sender(
            language_1=instance.language_2,
            language_2=instance.language_1,
            percent_low=instance.percent_low,
            percent_high=instance.percent_high,
            notes=instance.notes)
        if not getattr(instance, '_disable_signals', False):
            ls.save_without_signals(**kwargs)
    else:
        # Calling .update() on querysets doesn't send pre_save or post_save
        # signals, so we don't need to call ls.save_without_signals() here
        ls = sender.objects.filter(language_1=instance.language_2,
                                   language_2=instance.language_1).update(
            percent_low=instance.percent_low,
            percent_high=instance.percent_high,
            notes=instance.notes)


def delete_symmetric_lexical_similarity(sender, instance, **kwargs):
    # Delete the reflexive similarity, avoiding infinite recursion
    if not getattr(instance, '_disable_signals', False):
        try:
            sender.objects.get(
                language_1=instance.language_2,
                language_2=instance.language_1).delete_without_signals()
        except sender.DoesNotExist:
            pass


class WorldLanguagesConfig(AppConfig):
    name = 'world_languages'

    def ready(self):
        post_save.connect(
            save_symmetric_lexical_similarity,
            sender=self.get_model('LexicalSimilarity'),
            dispatch_uid='save_symmetric_lexical_similarity')
        pre_delete.connect(
            delete_symmetric_lexical_similarity,
            sender=self.get_model('LexicalSimilarity'),
            dispatch_uid='delete_symmetric_lexical_similarity')
