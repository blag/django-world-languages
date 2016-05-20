**********************
Django World Languages
**********************

Django World Languages (DWL) provides you with language related models:

* ``Language``
* ``Family`` - Both ISO 639-5 and Glottolog language families
* ``Dialect`` - Slightly different dictions and pronunciations of languages
* ``LexicalSimilarity`` - Similarities between languages

and language metadata:

* ``UsedIn`` - Maps languages to countries they are spoken in
* ``Characteristic`` - Common characteristics of languages (word type orders, number of speech sounds, subject/verb/object order, syllable patterns)
* ``Script`` and ``ScriptStyle`` - Characters that are used in languages
* ``DevelopmentNote`` - Development statuses of languages (tags, Bible translations, literacy rates)

============
Installation
============

1.  Install it with pip:

    .. code-block:: bash

        pip install django-world-languages

2.  Add ``world_languages`` to the ``INSTALLED_APPS`` variable in your project's ``settings.py`` file:
    
    .. code-block:: python

        INSTALLED_APPS = [
            # ...
            'world_languages',
            # ...
        ]

3.  Create the database tables:
    
    .. code-block:: bash

        python manage.py migrate world_languages

=============
Configuration
=============

All configuration options should be specified in the ``LANGUAGE_SETTINGS``
variable in your project's ``settings.py`` file.

*   ``PLUGINS`` - You can specify your own functions to run before and after a language is created. This should be specified as a dictionary mapping signal names to your custom function in dotted-module notation.

    **Example**

    .. code-block:: python

        LANGUAGE_SETTINGS = {
            'PLUGINS': {
                'pre_language': 'custom_app.utils.function_name'
            },
            # ...
        }

*   ``FILES`` - You can also specify your own URLs where files are hosted.

    **Example**

    .. code-block:: python

        LANGUAGE_SETINGS = {
            # ...
            'FILES': {
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
        }

===========
Import Data
===========

Once you have created the models and adjusted the settings to your liking, you
will need to import data into your database with the provided
``world_languages`` management command:

.. code-block:: bash

    python manage.py world_languages --import=all

====
TODO
====

* Tests
* Add import signals for all models, not just ``Language``

==============
Reporting Bugs
==============

This package uses regexes to parse downloaded YAML, HTML, and text files from
Glottolog_, Wikipedia_, and Geonames_. If you find a bug, especially in the
import script, please open an issue on `Github <https://github.com/blag/django-world-languages/issues>`_.

.. _Glottolog: https://github.com/clld/glottolog-data/blob/master/languoids/languages.yaml
.. _Wikipedia: https://en.wikipedia.org/wiki/ISO_639
.. _Geonames: http://download.geonames.org/export/dump/iso-languagecodes.txt
