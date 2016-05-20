from importlib import import_module
from collections import defaultdict
from django.conf import settings as django_settings
from django.core.exceptions import ImproperlyConfigured

__all__ = [
    'HookException', 'settings', 'import_opts', 'import_opts_all',
]

url_bases = {
    'geonames': {
        # GeoNames has certificate problems when we try to use https :-/
        'dump': 'http://download.geonames.org/export/dump/',
        'zip': 'http://download.geonames.org/export/zip/',
    },
    'glottolog': {
        'languoids': 'https://raw.githubusercontent.com/clld/glottolog-data/master/languoids/'
    }
}

files = {
    'language': {
        'filename': 'iso-languagecodes.txt',
        'urls': [url_bases['geonames']['dump'] + '{filename}'],
        'fields': [
            'iso639-3',
            'iso639-2',
            'iso639-1',
            'name',
        ]
    },
    'glottolog': {
        'filename': 'languages.yaml',
        'urls': [url_bases['glottolog']['languoids'] + '{filename}'],
    }
}

# Command-line import options
import_opts = [
    'all',
    'language',
    # 'glottolog',
]

import_opts_all = [
    'language',
    # 'glottolog',
]


# Raise inside a hook (with an error message) to skip the current line of data.
class HookException(Exception):
    pass

# Hook functions that a plugin class may define
plugin_hooks = [
    'language_pre',       'language_post',
]


LANGUAGE_SETTINGS = getattr(django_settings, 'LANGUAGE_SETTINGS', {})


def create_settings():
    res = type('', (), {})

    res.files = files.copy()
    if "FILES" in LANGUAGE_SETTINGS:
        for key in LANGUAGE_SETTINGS['FILES'].keys():
            if 'filenames' in LANGUAGE_SETTINGS['FILES'][key] and 'filename' in LANGUAGES['FILES'][key]:
                raise ImproperlyConfigured(
                    "Only one key should be specified for '{}': 'filename' of 'filenames'. Both specified instead".format(key)
                )
            res.files[key].update(LANGUAGE_SETTINGS['FILES'][key])
            if 'filenames' in LANGUAGE_SETTINGS['FILES'][key]:
                del res.files[key]['filename']

    if 'LOCALES' in LANGUAGE_SETTINGS:
        locales = LANGUAGE_SETTINGS['LOCALES'][:]
    else:
        locales = ['en', 'und']

    try:
        locales.remove('LANGUAGES')
        locales += [e[0] for e in django_settings.LANGUAGES]
    except:
        pass
    res.locales = set([e.lower() for e in locales])

    return res


def create_plugins():
    settings.plugins = defaultdict(list)
    if 'PLUGINS' in LANGUAGE_SETTINGS:
        for plugin in LANGUAGE_SETTINGS['PLUGINS']:
            module_path, classname = plugin.rsplit('.', 1)
            module = import_module(module_path)
            class_ = getattr(module, classname)
            obj = class_()
            [settings.plugins[hook].append(obj) for hook in plugin_hooks if hasattr(obj, hook)]

settings = create_settings()
create_plugins()
