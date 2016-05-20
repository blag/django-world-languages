import collections
import inspect
import io
import logging
import os
import re
import string
import time
import zipfile
from datetime import datetime, timedelta
from pprint import pprint
from urllib.parse import urlparse

import regex
import yaml
from optparse import make_option
from pyquery import PyQuery as pq
from tqdm import tqdm

import django
from django.core.management.base import BaseCommand
from django.db import transaction, IntegrityError
from django.db.models import Q
from django.db.utils import IntegrityError
from django.forms.models import model_to_dict

from cities.models import Country, AlternativeName as AlternativeCountryName

from ...conf import *
from ...models import (OKAY_LITERACY_TAG_NAMES, OKAY_TAG_NAMES,
                       cv_rgx, glid_rgx, iso639_1_rgx, iso639_3_rgx,
                       syllable_pattern_rgx, svo_rgx,
                       slugify,
                       Macroarea, Family, Language, AlternativeName,
                       LexicalSimilarity,
                       UsedIn,
                       Dialect, DialectNote,
                       Characteristic, AbsoluteWordTypeOrder,
                       RelativeWordTypeOrder, SpeechSoundCount,
                       SubjectVerbObjectOrder, SyllablePattern,
                       Script, ScriptStyle, ScriptUsage, ScriptUsageStyle,
                       AlternativeScriptName,
                       DevelopmentNote, DevelopmentNoteTag,
                       DevelopmentNoteBible, DevelopmentNoteLiteracy,
                       DevelopmentNoteLiteracyTag,
                       DevelopmentNoteLiteracyPercent)
from ...utils import urlopen_with_progress

# TODO: Remove backwards compatibility once django-cities requires Django 1.7
# or 1.8 LTS.
_transact = (transaction.commit_on_success if django.VERSION < (1, 6) else
             transaction.atomic)


def log(str):
    pass
# log = print


def plog(obj):
    pass
# plog = pprint

# # Setup the YAML interpreter to use OrderedDicts for mappings
# _mapping_tag = yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG


# def dict_representer(dumper, data):
#     return dumper.represent_dict(data.items())


# def dict_constructor(loader, node):
#     return collections.OrderedDict(loader.constructor_pairs(node))

# yaml.add_representer(collections.OrderedDict, dict_representer)
# yaml.add_constructor(_mapping_tag, dict_constructor)


if Country.objects.count() < 200:
    raise Exception("You must import continents and countries before importing "
                    "languages. To do this run:"
                    "\n"
                    "\n"
                    "    python manage.py cities --import=country"
                    "\n"
                    "\n"
                    "or:"
                    "\n"
                    "\n"
                    "    python manage.py cities --import=all"
                    "\n"
                    "\n"
                    "Refer to the django-cities package documentation for more "
                    "specific information:\n\ndjango-cities.rtfd.org")

MINOR_USAGE_PHRASES = ['experimental', 'limited usage', 'limited use', 'minor',
                       'never widely used', 'small-scale use',
                       'small collection']

# Used to parse script usages
SCRIPT_USAGE_BEGIN_PHRASES = [
    'dating to', 'dating from', 'developed in', 'development in',
    'established in', 'introduced in', 'invented in', 'since',
    'standardized in']

SCRIPT_USAGE_END_PHRASES = ['until', 'till']

# Used when characterizing word order
WORD_TYPES = [
    'adjective',
    'article',
    'attributive',
    'classifier',
    'demonstrative',
    'genitive',
    'modifier',
    'noun',
    'noun class',
    'noun head',
    'number',
    'number classifier construction',
    'number-classifier construction',
    'numeral',
    'personal pronoun',
    'possessive',
    'possessor',
    'possessor noun phrase',
    'postposition',
    'preposition',
    'proper noun',
    'q-word',
    'question word',
    'question words phrase',
    'relative',
    'relative clause',
    'verb',
    'verb phrase',
    'VP',
]

# Singular and pluralized word types
BOTH_WORD_TYPES = [x for pair in zip(WORD_TYPES, ['{}es'.format(el) if el.endswith('ss') else '{}s'.format(el) for el in WORD_TYPES]) for x in pair]


ABSOLUTE_POSITIONERS = [
    'final',
    'initial',
    'initial and final',
    'initial or final',
]

RELATIVE_POSITIONERS = [
    'after',
    'after or without',
    'before',
    'before and after',
    'before or after',
    'before and without',
    'before or without',
    'final with',
    'follow',
    'initial in',
    'precedes',
]

MODIFIERS = [
    'both',
    'generally',
    'in',
    'mostly',
    'normally',
    'not',
    'tend to',
    'usually',
    'with',
]

GRAMEMES = [
    'adjective',
    'article',
    'attributive',
    'classifier',
    'demonstrative',
    'genitive',
    'modifier',
    '(?:proper )?noun(?: class(?:es)?| clause| head)?',
    'number(?:[-\\s]classifier construction)?',
    'numeral',
    'possessive',
    'possessor(?: noun phrase)?',
    '(?:post|pre)position',
    '(?:personal )?pronoun',
    'q(?:-|uestion )word(?:s\s+phrase)?',
    'relative(?: clause)?',
    '(?:the )?verb(?: phrase)?',
    'VP',
]

POSITIONERS = [
    '(?:mostly )?after(?: (?:and|or) without)?',
    '(?:generally |normally |usually )?(?:all )?before(?: (?:and|or) (?:after|without))?',
    '(?:generally |normally |usually )?final(?: with)?',
    '(?:tend to )?follow',
    'followed by',
    '(?:both |not )?[Ii]nitial(?: in)?(?: (?:and|or) final)?',
    'precedes?'
]

UNITS = {
    'zero': 0,
    'one': 1,
    'two': 2,
    'three': 3,
    'four': 4,
    'five': 5,
    'six': 6,
    'seven': 7,
    'eight': 8,
    'nine': 9,
    'ten': 10,
    'eleven': 11,
    'twelve': 12,
    'thirteen': 13,
    'fourteen': 14,
    'fifteen': 15,
    'sixteen': 16,
    'seventeen': 17,
    'eighteen': 18,
    'nineteen': 19,
}

TENS = {
    'twenty': 20,
    'thirty': 30,
    'forty': 40,
    'fifty': 50,
    'sixty': 60,
    'seventy': 70,
    'eighty': 80,
    'ninety': 90,
}

SCALES = {
    'hundred': 100,
    'thousand': 1000,
    'million': 1000000,
    'billion': 1000000000,
    'trillion': 1000000000000,
}

NUMBERS = {}
NUMBERS.update(UNITS)
NUMBERS.update(TENS)
NUMBERS.update(SCALES)

aka_rgx = re.compile('^a\.?k\.?a\.?\s*')
alt_name_rgx = re.compile(r'\s*\(\w+\)\s*$', re.UNICODE)
as_of_rgx = re.compile(r'.*\((?P<year1>\d{4})|.*(?P<year2>\d{4})\)')
country_rgx = re.compile(r"^(?P<name>(?:[-\w',]+\s+)*[-\w',]+)\s+\[(?P<code>[A-Z]{2})\]$", re.UNICODE)
country_name_rgx = re.compile(r"(?P<name>(?:[-\w',]+\s+)*[-\w',]+)(?!\()", re.UNICODE)
country_name_and_code_rgx = re.compile(r"^(?P<name>(?:[-\w',]+\s+)*[-\w',]+)\s*(?:\[(?P<code>[A-Z]{2})\])?", re.UNICODE)
cv_num_repl_rgx = regex.compile(r'''
    (?(DEFINE)
        (?P<units>{units})
        (?P<tens>{tens})
        (?P<scales>{scales})
        (?P<numbers>
           \d+
           |(?:(?&units)|(?&tens)|(?&scales))
            (?:[\s-]+
               (?:(?&units)|(?&tens)|(?&scales))
            )*
        )
        (?P<modifiers>basic|long|short|simple)
        (?P<types>
           (?:consonants?
              |diph?thongs?
              |monoph?thongs?
              |qualit(?:y|ies)
              |vowels?
           )
           (?:\s+\([^)]+\))?
           (?:\s+phonemes?)?
           (?:\s+\([^)]+\))?
        )
        (?P<cv_phrase>
           (?&numbers)
           (?:\s+(?&modifiers))?
           \s+
           (?&types)
        )
    )
    (?:about\s+)?
    (?&cv_phrase)
    (?:(?:,|\s+and|)\s+(?:about\s+)?(?&cv_phrase)|)*
    (?:,\s+|$)
    '''.format(
    units='|'.join(UNITS.keys()),
    tens='|'.join(TENS.keys()),
    scales='|'.join(SCALES.keys()),
    ), regex.VERBOSE)
cv_num_rgx = regex.compile(r'''
    (?(DEFINE)
        (?P<units>{units})
        (?P<tens>{tens})
        (?P<scales>{scales})
        (?P<numbers>
           \d+
           |(?:(?&units)|(?&tens)|(?&scales))
            (?:[\s-]+
               (?:(?&units)|(?&tens)|(?&scales))
            )*
        )
        (?P<types>
           (?:consonants?
              |diph?thongs?
              |monoph?thongs?
              |qualit(?:y|ies)
              |vowels?
           )
           (?:\s+\([^)]+\))?
           (?:\s+phonemes?)?
           (?:\s+\([^)]+\))?
        )
        (?P<modifiers>basic|long|short|simple)
    )
    (?:about\s+)?
    (?P<number>(?&numbers))
    (?:\s+(?P<modifier>(?&modifiers)))?
    \s+
    (?P<type>(?&types))
    '''.format(
    units='|'.join(UNITS.keys()),
    tens='|'.join(TENS.keys()),
    scales='|'.join(SCALES.keys()),
    ), regex.VERBOSE)
dev_status_rgx = re.compile(r'^(?P<status>[^.]+)(?:\.\s*(?P<notes>.+))?\.?$')
dialect_notes_split_rgx = re.compile(r'\.\s*(?!:$)')
dialect_split_rgx = re.compile(r'(?:[^,(]|\([^)]*\))+')
family_name_rgx = re.compile(r'^(?P<glottolog_name>.*)\s+\[(?P<glottolog_id>[a-z]{4}\d{4}|[a-z]\d{2}[a-z]\d{4})\]\s*$')
find_country_rgx = regex.compile(r".*\s+in\s+(?:the\s+)?(?P<name>(?:\p{Lu}\p{Ll}+[-\s]+)*\p{Lu}\p{Ll}+).*")
full_dialect_rgx = re.compile(r'^(?P<dialect>[^()]+)(?:\s+\((?P<akas>.+)\))?\.?')
language_name_rgx = re.compile(r'^(?P<mother_language>(?:\w+\s+)*\w+),\s*(?P<language_prefix>\w+(?:\s+\w+)*)\s*(?:\[(?P<code>[a-z]{3})\])?$')
lex_sim_rgx = re.compile(r'(?P<name>(?:[-\w]+\s+)*[-\w]+)\s*(?:\[(?P<code>[a-z]{3})\])?\s*')
lit_tag_rgx = re.compile(r'^(?P<tag>{})$'.format('|'.join(OKAY_LITERACY_TAG_NAMES), re.I))
macrol_rgx = re.compile(r'^macrolanguage,?\s*')
overall_pop_rgx = re.compile(r'.*Population total[^\d]+(?P<total_population>[\d,]+).*')
percent_rgx = re.compile(r'^(?:\w+\s+)*(?P<low>\d+)%?(?:-(?P<high>\d+)%?)?')
pop_and_country_rgx = re.compile(r"^(?:(?P<pop>[\d,]+)|(?P<desc>\w+))\s+in\s+(?P<country>[\w',\s]+(?!:\s+\(|\s+\.|\s+and))(?:(?P<and>\s*and\s*)(?(and)(?P<other_country>(?:[\w',\s](?!:\s+\())+)))?", re.UNICODE)
pop_rgx = re.compile(r'^(?P<pop>[\d,]+)')
script_rgx = regex.compile(r'''
    ^
    (?(DEFINE)
        (?P<name_part>\(?(?:\p{Lu}\p{Ll}*(?:[-']?\p{Lu}?\p{Ll}*)*|ideograms|movement|notation|system)\)?)
        (?P<alternative_names>\((?&names)\))
        (?P<names>(?&name_part)(?&alternative_names)?(?:(?:\s+and|,)?\s+(?&name_part)(?&alternative_names)?)*)
    )
    (?P<script_name>(?&names))(?:\s+scripts?|\s+Notation|\s+Alphabet)?
    (?:,\s+(?P<style_names>(?&names))\s+styles?)?
    (?:,\s+(?P<variant_name>(&names))\s+variant)?
    (?:,\s+(?P<notes>.*))?
    $
    ''', regex.VERBOSE)
script_names_rgx = re.compile(r'''
    (?P<name>(?:[^()\s]+\s+)*[^()\s]+)
    (?:\s+
    \((?P<alt_names>[^)]+)\))?
    (?:\s+
      (?P<other_things>(?:[^()\s]+\s+)*[^()\s]+)+
    )?''', re.VERBOSE)
script_usage_end_century_rgx = re.compile(r'(?:used\s+)?(?:{})(?P<about>\s+about)?(?:\s+the)?(?:\s+(?P<early_or_late>early|late))?\s+(?:(?P<turn_of_the_other_century>turn of the )?(?P<other_century>\d+)(?:st|nd|rd|th)?\s+(?:to)(?:the\s+)?)?(?P<turn_of_the_century>turn of the )?(?P<century>\d+)(?:st|nd|rd|th)? century'.format('|'.join(SCRIPT_USAGE_BEGIN_PHRASES)))
script_usage_end_year_rgx = re.compile(r'(?:used\s+)?(?:{})(?P<about>\s+about)?(?:\s+the)?\s+(?P<year>\d{{4}})(?P<decade>s)?(?:\s+or\s+(?P<other_year>\d{{4}})(?P<other_decade>s)?)?'.format('|'.join(SCRIPT_USAGE_END_PHRASES)))
script_usage_start_century_rgx = re.compile(r'(?:used\s+)?(?:{})(?P<about>\s+about)?(?:\s+the)?(?:\s+(?P<early_or_late>early|late))?\s+(?:(?P<turn_of_the_other_century>turn of the )?(?P<other_century>\d+)(?:st|nd|rd|th)?\s+(?:to)(?:the\s+)?)?(?P<turn_of_the_century>turn of the )?(?P<century>\d+)(?:st|nd|rd|th)? century'.format('|'.join(SCRIPT_USAGE_BEGIN_PHRASES)))
script_usage_start_year_rgx = re.compile(r'(?:used\s+)?(?:{})(?P<about>\s+about)?(?:\s+the)?\s+(?P<year>\d{{4}})(?P<decade>s)?(?:\s+or\s+(?P<other_year>\d{{4}})(?P<other_decade>s)?)?'.format('|'.join(SCRIPT_USAGE_END_PHRASES)))
script_usage_in_rgx = regex.compile(r'(?(DEFINE)(?P<country_name>(?:\p{Lu}\p{Ll}+[-\s]+)*\p{Lu}\p{Ll}+)).*(?:us(?:e|ed|age)|official script) in(?:\s+the)? (?P<country_list>(?:(?&country_name),?\s*)?(?:(?&country_name),\s*)*(?:and\s+)?(?&country_name)).*')
tag_rgx = re.compile(r'^(?P<tag>{})$'.format('|'.join(OKAY_TAG_NAMES)), re.I)
usage_status_rgx = re.compile(r'^(?P<code>\d+)(?P<subcode>\w*|Unattested\.)\s+\((?P<status>[^)]+)\)(?:\.\s*(?P<notes>.+|\.?))?$')
wt_rgx = regex.compile(
    r'''
    (?(DEFINE)
        (?P<tbns>
            (?:
                (?:
                    (?:{things_before_nouns}),
                    \s+
                )*
                (?:
                    (?:{things_before_nouns})
                    \s+
                )?
                (?:and\s+)?
                (?:{things_before_nouns})
                \s+
                (?:{positioners})
                \s+
                (?:{things_before_nouns})
            )
            |(?:
                (?:
                    (?:{things_before_nouns}),
                    \s+
                )*
                (?:{things_before_nouns}),?
                \s+
                (?:{positioners})
            )
            |(?:
                (?:{positioners})
                \s+
                (?:{things_before_nouns})
            )
            |(?:
                (?:{things_before_nouns})
                \s+
                and
                \s+
                (?:{things_before_nouns})
                \s+
                (?:{positioners})
                \s+
                (?:{things_before_nouns})
            )|
            (?:
                (?:{things_before_nouns})
                \s+
                \(
                and
                \s+
                (?:{things_before_nouns})
                \)
                \s+
                (?:{positioners})
                \s+
                (?:{things_before_nouns})
            )
        )
    )
    (?:SVO,\s+)?
    (?P<tbnses>(?&tbns))
    '''.format(
    positioners='|'.join(POSITIONERS).replace(' ', r'\s+'),
    things_before_nouns='|'.join(['{}s?'.format(tbn) for tbn in GRAMEMES]).replace(' ', r'\s+')
    ), regex.VERBOSE | regex.IGNORECASE)
# Used to tokenize word type orders
wt_token_rgx = regex.compile(r'(?:{})'.format(
    '|'.join(
        list(r'\b{}(?:es)?\b'.format(tbn)
             if tbn.endswith('ss')
             else r'\b{}s?\b'.format(tbn)
             for tbn in reversed(WORD_TYPES)) +
        list(reversed(RELATIVE_POSITIONERS)) +
        list(reversed(ABSOLUTE_POSITIONERS)) +
        list(r'\b{}\b'.format(m) for m in MODIFIERS)
    ).replace(' ', r'\s+')))

cv_number_index = cv_num_rgx.groupindex['number']-1
cv_modifier_index = cv_num_rgx.groupindex['modifier']-1
cv_type_index = cv_num_rgx.groupindex['type']-1
cvs_index = syllable_pattern_rgx.groupindex['cvs']-1
wt_rgx_index = wt_rgx.groupindex['tbnses']-1


def add_alt_names(en, l, alt_names):
    for i, alt_name in enumerate(alt_names):
        try:
            aln = AlternativeName.objects.get(name=alt_name, in_language=en)
        except AlternativeName.DoesNotExist:
            aln = AlternativeName.objects.create(
                language=l,
                name=alt_name,
                type=AlternativeName.TYPE.name,
                in_language=en)


def add_dialects(used_in, dialect_soup):
    dialects, *notes = dialect_soup.split('. ')
    notes = [n for n in notes if n != '']

    for dn in notes:
        DialectNote.objects.get_or_create(used_in=used_in, note=dn)

    for dialect in dialect_split_rgx.findall(dialects):
        log('dialect: {}'.format(dialect))
        dialect, *dialect_notes = [dn for dn in re.split(r'\.\s*(?!:$)', dialect.strip().replace('e.g.', 'example')) if dn != '']
        log('dialect: {}'.format(dialect))
        log('dialect notes: {}'.format(dialect_notes))

        # Now we should have a standardized form:
        # dialect (aka1, aka2)
        m = full_dialect_rgx.match(dialect)

        # Only create the notes on the first one
        try:
            d = Dialect.objects.get(used_in=used_in, name=m.group('dialect'))
        except Dialect.DoesNotExist:
            dnotes = ' '.join(['{}.'.format(n) for n in dialect_notes])
            d = Dialect.objects.create(used_in=used_in, name=m.group('dialect'), notes=dnotes)

        # Create the rest of the dialects
        dakas = [d]
        if m.group('akas') is not None:
            for dialect in m.group('akas').split(', '):
                d, _ = Dialect.objects.get_or_create(used_in=used_in, name=dialect)
                dakas.append(d)

        # Link them together with also_known_as
        # Assumes also_known_as is symmetrical, and is O(N^2) time
        for i, d1 in enumerate(dakas[:-1]):
            for d2 in dakas[i+1:]:
                d1.also_known_as.add(d2)


def add_language(name, name_gl, iso639_1, iso639_2t, iso639_2b, iso639_3,
                 population, macroarea, family, iso_family,
                 development_status, development_status_notes, notes):
    try:
        l = Language.objects.get(Q(Q(iso639_1=iso639_1.strip()) |
                                   Q(iso639_3=iso639_3.strip())),
                                 name=name.strip())
    except Language.DoesNotExist:
        l = Language()
    finally:
        l.name = name
        l.name_gl = name_gl
        l.iso639_1 = iso639_1
        l.iso639_2t = iso639_2t
        l.iso639_2b = iso639_2b
        l.iso639_3 = iso639_3
        l.population = population
        l.macroarea = macroarea if macroarea else None
        l.family = family
        l.iso_family = iso_family
        l.development_status = development_status
        l.development_status_notes = development_status_notes
        l.notes = notes
    return l


def add_lexical_similarities(language, lexical_similarities, lex_sim_soup):
    p = None
    percent = None
    for ls in lex_sim_soup.split(', '):
        log('ls: {}'.format(ls))

        for t in ls.split(';'):
            log('t: {}'.format(t))

            t = t.strip()
            for thing in re.split(r'\s+with\s+|\s*and\s+', t):
                if not thing:
                    continue

                log('thing: {}'.format(thing))
                m1 = percent_rgx.match(thing)
                m2 = lex_sim_rgx.match(thing)

                if m1:
                    percent_low = m1.group('low')
                    percent_high = m1.group('high')
                elif thing.endswith('%'):
                    try:
                        percent_low = percent_high = int(thing.strip('%'))
                    except ValueError:
                        percent_low = percent_high = None
                elif thing == 'high' or thing == 'low':
                    p_high = None
                    p_low = None
                    continue
                elif m2:
                    log('name: {}, code: {}'.format(m2.group('name'), m2.group('code')))

                    if not m2.group('code') and 'dialect' in m2.group('name'):
                        log('skipping dialect {}'.format(m2.group('name')))
                        continue

                    if not m2.group('code') and 'the' in m2.group('name'):
                        log('skipping dialect {}'.format(m2.group('name')))
                        continue

                    try:
                        p_low = percent_low
                    except UnboundLocalError:
                        p_low = None

                    try:
                        p_high = percent_high
                    except UnboundLocalError:
                        p_high = None

                    if p_low or p_high:
                        lexical_similarities.setdefault(language, []).append({
                            'percent_low': p_low,
                            'percent_high': p_high,
                            'other_language': language,
                            'language': {
                                'name': m2.group('name'),
                                'iso639-3': m2.group('code'),
                                'note': lex_sim_soup,
                            }
                        })


def add_native_names(l, native_names):
    for i, native_name in enumerate(native_names):
        aln = None
        name = alt_name_rgx.sub('', native_name).strip()
        while aln is None:
            try:
                aln = l.alternative_names.get(
                    name=name,
                    in_language=l,
                    type=AlternativeName.TYPE.name)
            except AlternativeName.DoesNotExist:
                log('l: {}'.format(l))
                try:
                    log("AlternativeName (slug): {}".format(slugify('{}_({})'.format(name, l.iso639_3))))
                    aln = AlternativeName.objects.get(slug=slugify('{}_({})'.format(name, l.iso639_3)))
                except AlternativeName.DoesNotExist:
                    try:
                        log("AlternativeName:")
                        plog({
                            'language': l,
                            'name': name,
                            'in_language': l,
                            'type': AlternativeName.TYPE.name,
                            'preferred': True if i == 0 else False,
                            'colloquial': True
                        })
                        aln = AlternativeName.objects.get(
                            language=l,
                            name=name,
                            in_language=l,
                            type=AlternativeName.TYPE.name,
                            preferred=True if i == 0 else False,
                            colloquial=True)
                    except AlternativeName.DoesNotExist:
                        log("Creating AlternativeName:")
                        plog({
                            'language': l,
                            'name': name,
                            'in_language': l,
                            'type': AlternativeName.TYPE.name,
                            'preferred': True if i == 0 else False,
                            'colloquial': True
                        })
                        aln = AlternativeName.objects.create(
                            language=l,
                            name=name,
                            in_language=l,
                            type=AlternativeName.TYPE.name,
                            preferred=True if i == 0 else False,
                            colloquial=True)
                    except AlternativeName.MultipleObjectsReturned:
                        aln = AlternativeName.objects.get(
                            language=l,
                            name=name,
                            in_language=l,
                            type=AlternativeName.TYPE.name,
                            colloquial=True)
                    aln.preferred = True if i == 0 else False
                    aln.save()
            except IntegrityError:
                aln = None


def clean_word_orders(word_orders):
    word_types_dict = {
        'number classifier construction': 'num cls cnstr',
        'number-classifier construction': 'num cls cnstr',
        'possessor noun phrase': 'poss noun phrase',
        'question words phrase': 'q word phrase',
    }

    for char in word_orders.keys():
        for i, wo in enumerate(word_orders[char]):
            for j, word in enumerate(wo['words']):
                for wt, choice in word_types_dict.items():
                    if wt in word.lower():
                        word_orders[char][i]['words'][j] = choice

                word_orders[char][i]['words'][j] = word_orders[char][i]['words'][j][:-1] if word_orders[char][i]['words'][j].endswith('s') and not word_orders[char][i]['words'][j].endswith('ss') else word_orders[char][i]['words'][j]

                word_orders[char][i]['words'][j] = word_orders[char][i]['words'][j].replace(' ', '_')

            if 'related_word' in word_orders[char][i] and word_orders[char][i]['related_word']:
                for wt, choice in word_types_dict.items():
                    if wt in word_orders[char][i]['related_word']:
                        word_orders[char][i]['related_word'] = choice

                word_orders[char][i]['related_word'] = word_orders[char][i]['related_word'][:-1] if word_orders[char][i]['related_word'].endswith('s') and not word_orders[char][i]['related_word'].endswith('ss') else word_orders[char][i]['related_word']

                word_orders[char][i]['related_word'] = word_orders[char][i]['related_word'].replace(' ', '_')

            if 'modifier' in word_orders[char][i] and word_orders[char][i]['modifier']:
                word_orders[char][i]['modifier'] = word_orders[char][i]['modifier'].replace(' ', '_')


def create_language(cmd, data, en):
    family_name = data[1]
    name, *alt_names = data[2].split(', ')
    native_names = data[3].split(', ')
    iso639_1 = data[4]
    iso639_2t = data[5]
    iso639_2b = data[6]
    iso639_3 = data[7]
    notes = data[9]

    notes = macrol_rgx.sub('', notes)

    if aka_rgx.match(notes):
        aka_name = aka_rgx.sub('', notes)
        alt_names.append(aka_name)
        notes = aka_rgx.sub('', notes)

    try:
        lf = Family.objects.get(name=family_name)
    except Family.DoesNotExist:
        try:
            lf = Family.objects.get(slug=slugify(family_name))
        except Family.DoesNotExist:
            d = {
                'name': family_name,
                'slug': slugify(family_name),
            }

            if cmd.call_hook('languagefamily_pre', d):
                lf = Family.objects.create(name=family_name)
            cmd.call_hook('languagefamily_post', lf, d)

    try:
        l = Language.objects.get(iso639_3=iso639_3)
    except Language.DoesNotExist:
        try:
            Language.objects.get(iso639_1=iso639_1)
        except Language.DoesNotExist:
            l = Language()

    l.name = name
    l.name_gl = name
    l.iso639_1 = iso639_1
    l.iso639_2b = iso639_2b
    l.iso639_2t = iso639_2t
    l.iso639_3 = iso639_3
    l.family = lf
    l.notes = notes

    return l


def create_used_in(country, language, known_ases, population, status, usage_notes):
    m = as_of_rgx.match(usage_notes)
    if m is not None:
        as_of = '{}-6-30'.format(m.group('year1') or m.group('year2'))
    else:
        as_of = None

    try:
        ui = UsedIn.objects.get(country=country, language=language)
    except UsedIn.DoesNotExist:
        ui = UsedIn(country=country, language=language)

    if not population:
        pop = None
    elif type(population) == int:
        pop = population
    else:
        m = pop_and_country_rgx.match(population)
        if m:
            pop = int(m.group('pop').replace(',', ''))
        else:
            pop = None

    log('status: {}'.format(status))
    ldstatus = dev_status_rgx.match(status)

    ui.population = pop
    if as_of:
        ui.as_of = as_of
    if ldstatus:
        ui.development_status = [i for i in Language.DEVELOPMENT_STATUS if i[1] == ldstatus.group('status')][0][0]
        ui.development_status_notes = ldstatus.group('notes')
    else:
        ui.development_status = Language.DEVELOPMENT_STATUS.unattested
        ui.development_status_notes = None
    ui.usage_notes = usage_notes

    ui.save()

    ui.known_as.add(*list(set(known_ases) - set(ui.known_as.all())))

    return ui


class Command(BaseCommand):
    logger = logging.getLogger("cities")
    force = False

    option_list = BaseCommand.option_list + (
        make_option(
            '--force',
            action='store_true',
            default=False,
            help='Import even if files are up-to-date.'),
        make_option(
            '--import',
            metavar="DATA_TYPES",
            default='all',
            help='Selectively import data. Comma separated list of data types: {}'.format(str(import_opts).replace("'", ''))),
        make_option(
            '--flush',
            metavar="DATA_TYPES",
            default='',
            help="Selectively flush data. Comma separated list of data types.")
    )

    @_transact
    def handle(self, *args, **options):
        self.options = options

        self.force = self.options['force']

        self.flushes = [e for e in self.options['flush'].split(',') if e]
        if 'all' in self.flushes:
            self.flushes = import_opts_all
        for flush in self.flushes:
            func = getattr(self, "flush_" + flush)
            func()

        self.imports = [e for e in self.options['import'].split(',') if e]
        if 'all' in self.imports:
            self.imports = import_opts_all
        if self.flushes:
            self.imports = []
        for import_ in self.imports:
            func = getattr(self, "import_" + import_)
            func()

    def call_hook(self, hook, *args, **kwargs):
        if hasattr(settings, 'plugins'):
            for plugin in settings.plugins[hook]:
                try:
                    func = getattr(plugin, hook)
                    func(self, *args, **kwargs)
                except HookException as e:
                    error = str(e)
                    if error:
                        self.logger.error(error)
                    return False
        return True

    def get_data(self, filekey, key_index=None):
        if key_index is None:
            filename = settings.files[filekey]['filename']
        else:
            filename = settings.files[filekey]['filenames'][key_index]

        urls = [e.format(filename=filename) for e in settings.files[filekey]['urls']]
        for url in urls:
            # TODO: Fix this logic - don't catch all exceptions here, it makes
            #       it more difficult to debug
            try:
                web_file = urlopen_with_progress(url)
                # if 'html' in web_file.headers['content-type']:
                #     raise Exception()
                break
            except:
                web_file = None
                continue
        else:
            self.logger.error("Web file not found: %s. Tried URLs:\n%s", filename, '\n'.join(urls))

        if 'filename' in settings.files[filekey]:
            filenames = [settings.files[filekey]['filename']]
        else:
            filenames = settings.files[filekey]['filenames']

        for filename in filenames:
            name, ext = filename.rsplit('.', 1)

            if ext == 'zip':
                zipfile = ZipFile(StringIO(web_file))
                zipfilename = ''
                for zipname in zipfile.nameslist():
                    if zipname.startswith(name):
                        zipfilename = zipname
                        break
                file_obj = zipfile.open(zipfilename).readlines()
            elif ext == 'yaml':
                data = yaml.safe_load(web_file)

                for key in sorted(data):
                    yield (key, data[key])

                file_obj = []
            else:
                file_obj = web_file.strip().split('\n')

            for row in file_obj:
                if not row.startswith('#'):
                    yield dict(list(zip(settings.files[filekey]['fields'], row.split("\t"))))

    def import_languages_from_wikipedia(self):
        try:
            und = Language.objects.get(
                family=None,
                name='Undetermined')
        except Language.DoesNotExist:
            und = Language.objects.create(
                name='Undetermined',
                name_gl='Undetermined',
                iso639_1='xx',
                iso639_2t='und',
                iso639_2b='und',
                iso639_3='und',
                glottolog_id=None,
                development_status=Language.DEVELOPMENT_STATUS.unattested,
                population=0)

        try:
            en = Language.objects.get(iso639_1='en')
        except Language.DoesNotExist:
            en = Language.objects.create(
                name='English',
                name_gl='Standard English',
                iso639_1='en',
                iso639_2t='eng',
                iso639_2b='eng',
                iso639_3='eng',
                glottolog_id='stan1293',
                development_status=None,
                population=0)

        doc = pq(url="https://en.wikipedia.org/wiki/List_of_ISO_639-1_codes",
                 opener=lambda url, **kwargs: urlopen_with_progress(url))

        for row in tqdm(doc("#Partial_ISO_639_table").parent().siblings('table.wikitable > tr')[1:],
                        desc="Importing languages from Wikipedia..."):
            data = [pq(el).text() for el in pq(row).children()]

            # Skip adding languages without any ISO639 codes
            if not any(data[4:7]):
                continue

            iso639_3_m = re.match(r'^(?P<iso639_3>[a-z]{3})(?:\s*\+\s*\d+)?$', data[7])

            if iso639_3_m:
                data[7] = iso639_3_m.group('iso639_3')

            item = {
                'family_name': data[1].strip(),
                'name': data[2].split(', ')[0].strip(),
                'alt_names': [an.strip() for an in re.split(r',\s*', data[2].strip())][1:],
                'native_names': [nn.strip() for nn in re.split(r',\s*', data[3])],
                'iso639_1': data[4].strip(),
                'iso639_2t': data[5].strip(),
                'iso639_2b': data[6].strip(),
                'iso639_3': data[7].strip(),
                # data[6] is the iso639-6 abbreviation, a proposed standard that
                # has since been withdrawn, so we skip it
                'notes': macrol_rgx.sub('', data[9].strip()),
            }

            if not self.call_hook('language_pre', item):
                continue

            l = create_language(self, data, en)

            if not self.call_hook('language_post', l, item):
                continue

            l.save()

            add_alt_names(en, l, item['alt_names'])

            add_native_names(l, item['native_names'])

    def import_macrolanguages_from_wikipedia(self):
        doc = pq(url="https://en.wikipedia.org/wiki/ISO_639_macrolanguage",
                 opener=lambda url, **kwargs: urlopen_with_progress(url))

        for row in tqdm(doc("#List_of_macrolanguages").parent().siblings('table.wikitable > tr')[1:],
                        desc="Importing macrolanguages from Wikipedia..."):
            item = [pq(el).text() for el in pq(row).children()]

            if not self.call_hook('macrolanguage_pre', item):
                continue

            if len(item) > 4:
                ml = create_macrolanguage(item)

            if not self.call_hook('macrolanguage_post', ml, item):
                continue

    def import_iso639_2_language_types_and_scopes_from_wikipedia(self):
        doc = pq(url="https://en.wikipedia.org/wiki/List_of_ISO_639-2_codes",
                 opener=lambda url, **kwargs: urlopen_with_progress(url))

        for row in tqdm(doc("table tr th:contains('Scope')").parent().parent().children()[1:],
                        desc="Importing ISO 639-2 types..."):

            item = [pq(el).text() for el in pq(row).children()]

            try:
                l = Language.objects.get(
                    Q(iso639_2b=item[0].strip()) |
                    Q(iso639_2t=item[0].strip()),
                    Q(iso639_5=item[0].strip()))
            except Language.DoesNotExist:
                continue

            if item[4] == 'Individual':
                l.iso639_2_scope = Language.SCOPE.individual
            elif item[4] == 'Collective':
                l.iso639_2_scope = Language.SCOPE.collective
            elif item[4] == 'Macrolanguage':
                l.iso639_2_scope = Language.SCOPE.macrolanguage
            elif item[4] == 'Local':
                l.iso639_2_scope = Language.SCOPE.local
            elif item[4] == 'Special':
                l.iso639_2_scope = Language.SCOPE.special

            if len(item) > 5:
                if item[5] == 'Ancient':
                    l.iso639_2_type = Language.TYPE.ancient
                elif item[5] == 'Constructed':
                    l.iso639_2_type = Language.TYPE.constructed
                elif item[5] == 'Extinct':
                    l.iso639_2_type = Language.TYPE.extinct
                elif item[5] == 'Historical':
                    l.iso639_2_type = Language.TYPE.historic
                elif item[5] == 'Living':
                    l.iso639_2_type = Language.TYPE.living

            l.save()

        # Tie each macrolanguage to its family
        doc = pq(url="https://en.wikipedia.org/wiki/ISO_639_macrolanguage",
                 opener=lambda url, **kwargs: urlopen_with_progress(url))

        for row in tqdm(doc("#List_of_macrolanguages_and_the_individual_languages").parent().nextAll('h4, ol'),
                        desc="Importing ISO macrolanguages from Wikipedia..."):

            if row.tag == 'h4':
                mlcode = pq(pq(row).children('span')[0]).text()
                try:
                    ml = Language.objects.get(iso639_3=mlcode.strip())
                except Language.DoesNotExist:
                    continue
            elif row.tag == 'ol':
                Language.objects.filter(iso639_3__in=[pq(clcode).text().strip() for clcode in pq(row).children('li > tt')]).update(macrolanguage=ml)

    def import_iso_language_families_from_wikipedia(self):
        try:
            und = Language.objects.get(
                family=None,
                name='Undetermined')
        except Language.DoesNotExist:
            und = Language.objects.create(
                name='Undetermined',
                name_gl='Undetermined',
                iso639_1='xx',
                iso639_2t='und',
                iso639_2b='und',
                iso639_3='und',
                glottolog_id=None,
                development_status=Language.DEVELOPMENT_STATUS.unattested,
                population=0)

        try:
            en = Language.objects.get(iso639_1='en')
        except Language.DoesNotExist:
            en = Language.objects.create(
                name='English',
                name_gl='Standard English',
                iso639_1='en',
                iso639_2t='eng',
                iso639_2b='eng',
                iso639_3='eng',
                glottolog_id='stan1293',
                development_status=None,
                population=0)

        # Import the actual languages first
        doc = pq(url="https://en.wikipedia.org/wiki/List_of_ISO_639-5_codes",
                 opener=lambda url, **kwargs: urlopen_with_progress(url))

        hierarchy = []

        for row in tqdm(doc("table tr th:contains('Hierarchy')").parent().parent().children()[1:],
                        desc="Importing ISO language families from Wikipedia..."):

            item = [pq(el).text() for el in pq(row).children()]

            if item[2].endswith(' languages'):
                item[2] = item[2].replace(' languages', '')

            if item[2].endswith(' (family)'):
                item[2] = item[2].replace(' (family)', '')

            if ', ' in item[2]:
                item[2] = ' '.join(reversed(item[2].split(', ')))

            try:
                l = Language.objects.get(iso639_5=item[1].strip())
            except Language.DoesNotExist:
                l = Language(iso639_2b=item[1].strip(),
                             iso639_2t=item[1].strip(),
                             iso639_5=item[1].strip())

            l.name = item[2]
            l.name_gl = item[2]
            l.iso639_1 = None
            l.iso639_3 = None
            if len(item) > 3:
                if not l.notes:
                    l.notes = item[3]
                elif item[3] not in l.notes:
                    l.notes = '{}, {}'.format(l.notes, item[3])
            l.glottolog_id = None
            l.development_status = None
            l.population = 0
            l.save()

            hierarchy.append(item[0])

        saved_hierarchy = {}

        # Create the hierarchy of ISO language families
        for h in hierarchy:
            ls = h.split(':')
            for i, lcode in enumerate(ls):
                if i == 0:
                    continue
                elif lcode not in saved_hierarchy:
                    iso_family = Language.objects.get(iso639_5=ls[i-1].strip())
                    l = Language.objects.get(iso639_5=ls[i].strip())
                    l.iso_family = iso_family
                    l.save()
                    saved_hierarchy[lcode] = iso_family

        # Tie each language to its family
        doc = pq(url="https://en.wikipedia.org/wiki/List_of_ISO_639-1_codes",
                 opener=lambda url, **kwargs: urlopen_with_progress(url))

        for row in tqdm(doc("table tr th:contains('Language family')").parent().parent().children()[1:],
                        desc="Tying languages to their ISO language families..."):
            item = [pq(el).text() for el in pq(row).children()]

            if item[1] == 'Northeast Caucasian' or item[1] == 'Northwest Caucasian':
                item[1] = 'North Caucasian'

            if ',' in item[2]:
                item[2], *alt_names = re.split(r'\s*,\s*', item[2])
            else:
                alt_names = []

            native_names = re.split(r',\s*', item[3])

            if len(item) > 8 and 'macrolanguage' in item[9]:
                item[9] = item[9].replace('macrolanguage,', '').replace('macrolanguage', '').strip()

            try:
                if len(item) > 6:
                    l = Language.objects.get(
                        Q(name_gl=item[2].strip()) |
                        Q(iso639_3=item[7].split('+')[0].strip()))
                else:
                    l = Language.objects.get(iso639_1=item[4].strip())
            except Language.DoesNotExist:
                l = Language(iso639_1=item[4].strip())

                l.name = item[2]
                l.name_gl = item[2]
                l.iso639_2t = item[5]
                l.iso639_2b = item[6]
                if len(item) > 6:
                    l.iso639_3 = item[7].split('+')[0].strip()
                l.glottolog_id = None
                l.development_status = None
                l.population = 0
            except Language.MultipleObjectsReturned as e:
                if len(item) > 6:
                    l = Language.objects.get(iso639_3=item[7].split('+')[0].strip())
                else:
                    log('looking for:')
                    plog(item)
                    log('options:')
                    plog(Language.objects.filter(
                        Q(name_gl=item[2].strip()) |
                        Q(iso639_3=item[7].split('+')[0].strip())))
                    raise e

            if len(item) > 8:
                if not l.notes:
                    l.notes = item[9]
                elif item[9] not in l.notes:
                    l.notes = '{}, {}'.format(l.notes, item[3])

            l.save()

            add_alt_names(en, l, alt_names)

            add_native_names(l, native_names)

    def import_language_families_from_wikipedia(self):
        doc = pq(url="https://en.wikipedia.org/wiki/List_of_language_families",
                 opener=lambda url, **kwargs: urlopen_with_progress(url))

        for row in tqdm(doc("#Language_families").parent().siblings('table.wikitable')[0].children('tbody').children('tr'),
                        desc="Importing language families from Wikipedia..."):
            item = [pq(el).text() for el in pq(row).children()]

            if not self.call_hook('languagefamily_pre', item):
                continue

            if item[0].endswith('(proposed)'):
                continue
            else:
                name = re.sub(r'\s+languages$', '', item[0]).replace('–', '-')
                lf, _ = Family.objects.get_or_create(name=item[0])

            if not self.call_hook('languagefamily_post', ml, item):
                continue

    def import_alternative_language_names(self):
        url = "https://en.wikipedia.org/wiki/ISO_639:{}"

        purl = urlparse(url)

        for letter in string.ascii_lowercase:
            doc = pq(url=url.format(letter),
                     opener=lambda url, **kwargs: urlopen_with_progress(url))

            header_row, *rows = doc('#mw-content-text').children('table.wikitable').children('tr')

            header_cols = [(i, pq(th).text()) for i, th in enumerate(pq(header_row).children('th')) if regex.match(r'^\p{Ll}{3}$', pq(th).text())]

            translated_languages = [(i[0], Language.objects.get(iso639_3=i[1])) for i in header_cols]

            for row in [pq(r) for r in rows]:
                lang_id = pq(row.children('th')[0])
                iso639_3 = lang_id.text().strip()

                if iso639_3.startswith('(') and iso639_3.endswith(')'):
                    continue

                try:
                    l = Language.objects.get(iso639_3=iso639_3)
                except Language.DoesNotExist:
                    continue

                cols = row.children('td')

                for i, lang in translated_languages:
                    try:
                        for alt_name in regex.split(r'\s*;\s+', pq(cols[i-1]).text()):
                            if alt_name:
                                alt_name = regex.sub(r'\s+\([^)]+\)$', '', alt_name).strip()

                                if ',' in alt_name:
                                    alt_name = ' '.join(reversed(regex.split(r',\s+', alt_name))).strip()

                                try:
                                    log('Alternative name (by slug):')
                                    plog({
                                        'slug': slugify('{}_({})'.format(alt_name, lang.iso639_3)),
                                        'language': l,
                                        'name': alt_name,
                                        'type': AlternativeName.TYPE.name,
                                        'in_language': lang,
                                    })
                                    an = AlternativeName.objects.get(
                                        type=AlternativeName.TYPE.name,
                                        slug=slugify('{}_({})'.format(alt_name, lang.iso639_3)))
                                except AlternativeName.DoesNotExist:
                                    log('Alternative name:')
                                    plog({
                                        'language': l,
                                        'name': alt_name,
                                        'type': AlternativeName.TYPE.name,
                                        'in_language': lang,
                                    })
                                    an, _ = AlternativeName.objects.get_or_create(
                                        language=l,
                                        name=alt_name,
                                        type=AlternativeName.TYPE.name,
                                        in_language=lang)

                    except IndexError as e:
                        log('header cols:')
                        plog(header_cols)
                        log('cols:')
                        plog([pq(col).text() for col in cols])
                        raise e

    def import_glottolog(self):
        self.build_iso_index()

        ldata = self.get_data('glottolog')

        try:
            und = Language.objects.get(
                family=None,
                name='Undetermined')
        except Language.DoesNotExist:
            und = Language.objects.create(
                name='Undetermined',
                name_gl='Undetermined',
                iso639_1='xx',
                iso639_2t='und',
                iso639_2b='und',
                iso639_3='und',
                glottolog_id=None,
                development_status=Language.DEVELOPMENT_STATUS.unattested,
                population=0)

        try:
            en = Language.objects.get(iso639_1='en')
        except Language.DoesNotExist:
            en = Language.objects.create(
                name='English',
                name_gl='Standard English',
                iso639_1='en',
                iso639_2t='eng',
                iso639_2b='eng',
                iso639_3='eng',
                glottolog_id='stan1293',
                development_status=None,
                population=0)

        lexical_similarities = {}
        note_lcodes = {}

        for lk, ld in tqdm(ldata, total=sum(1 for _ in self.get_data('glottolog')),
                           desc="Importing languages from Glottolog..."):
            if ld['iso_639-3'].startswith('NOCODE_'):
                # Skip over languages if they don't have ISO 639-3 codes,
                # because we require an ISO 639-3 code
                continue

            if ld['iso_639-3'] not in self.iso_index:
                # Glottolog has some languages that were retired from ISO 639-3
                continue

            log('[{}]'.format(lk))

            name = ld['name']
            m = language_name_rgx.match(name)
            log('name: {}'.format(name))
            if m:
                name = '{} {}{}'.format(m.group('language_prefix'), m.group('mother_language'), ' [{}]'.format(m.group('code')) if m.group('code') else '')
                log(" --> '{}'".format(name))

            if len(ld.get('country-gl', ld.get('country', []))) == 1:
                log('Extracting from single country from both lists: {}'.format(ld.get('country-gl', ld.get('country', []))))
                # Has to match:
                # United Kingdom
                # Democratic Republic of Congo, The [CD]
                # Virgin Islands, U.S. [VI]
                name_m = re.match(r"^(?P<name>(?:[-\w(),.']+\s+)*[-\w(),.']+)(?:\s+\[(?P<code>[A-Z]{2})\])?$", ld.get('country-gl', ld.get('country'))[0])

                if name_m:
                    home_country_name = name_m.group('name')
                    home_country_code = name_m.group('code')
                else:
                    home_country_name = ld.get('country-gl', ld.get('country', []))[0]
                    home_country_code = ''

                pop_m = re.match(r'^(?P<pop>[\d,]+)(?![\d,])', ld.get('population', ''))
                if pop_m:
                    home_country_pop = int(pop_m.group('pop').strip().replace(',', ''))
                else:
                    home_country_pop = None

            elif len(ld.get('country-gl', [])) == 1 or len(ld.get('country', [])) == 1:
                log('Extracting from single {}: {}'.format(
                    'country-gl' if ld.get('country-gl', []) else 'country',
                    ld.get('country-gl')[0] if ld.get('country-gl', []) else ld.get('country')[0]))
                if ld.get('country-gl', '0') == ld.get('country', '1'):
                    cm = country_rgx.match(ld.get('country-gl', l.get('country', '')))
                    home_country_name = cm.group('name')
                    home_country_code = cm.group('code')
                else:
                    for c in ld.get('country-gl', []) + ld.get('country', []):
                        cm = country_rgx.match(c)
                        if cm:
                            home_country_name = cm.group('name')
                            home_country_code = cm.group('code')
                            break
                    else:
                        raise Exception('Cannot figure out home country name and code: {}'.format(ld.get('country-gl', []) + ld.get('country', [])))

                popm = pop_rgx.match(ld.get('population', ''))
                if popm:
                    home_country_pop = int(popm.group('pop').replace(',', ''))
                else:
                    home_country_pop = None

            elif len(ld.get('country', ld.get('country-gl', []))) - len(ld.get('also_spoken_in', [])) == 1:
                log('Extracting from the relative complement of also-spoken-ins in countries:')
                possible_countries = set([country_name_rgx.match(c).group('name') for c in ld.get('country', []) + ld.get('country-gl', [])])
                asis = set(ld.get('also_spoken_in', []).keys())
                remaining_country = list(possible_countries - asis)[0]
                log('{} - {} -> {}'.format(
                    possible_countries,
                    asis,
                    possible_countries - asis))
                log('remaining_country: {}'.format(remaining_country))

                # Now find that country and its country code
                log('looking at: {}'.format([c for c in ld.get('country', []) + ld.get('country-gl', []) if c.startswith(remaining_country)][0]))

                for c in ld.get('country', []) + ld.get('country-gl', []):
                    m = country_rgx.match(c)

                    if m:
                        cname = m.group('name')

                        if ',' in cname:
                            cname = '{}{}'.format(*reversed(cname.split(', ')))
                        if cname.startswith('The '):
                            cname = cname[4:]

                        if cname == remaining_country:
                            home_country_name = m.group('name')
                            home_country_code = m.group('code')
                            home_country_pop = ld.get('population_numeric', 0)

            else:
                home_country_population = pop_and_country_rgx.match(ld.get('population', ''))
                if home_country_population:
                    log('Extracting country from population: {}'.format(ld.get('population', '')))
                    try:
                        home_country_pop = home_country_population.group('desc')
                    except AttributeError:
                        home_country_pop = int(home_country_population.group('pop').replace(',', ''))
                    else:
                        if 'population_numeric' in ld:
                            home_country_pop = int(ld.get('population_numeric', 0))
                        else:
                            home_country_pop = 0

                    if ' and ' in home_country_population.group('country'):
                        # South Sudan and Sudan [suda1236]
                        possible_countries = set(home_country_population.group('country').split(' and '))
                        asis = set(ld.get('also_spoken_in', {}).keys())

                        remaining_countries = list(possible_countries - asis)

                        if len(remaining_countries) == 1:
                            home_country_name = remaining_countries[0]

                            for c in ld.get('country-gl'):
                                cm = country_rgx.match(c)
                                if cm and cm.group('name') == home_country_name:
                                    home_country_code = cm.group('code')
                                    home_country_pop = ld.get('population_numeric')
                                    break
                            else:
                                raise Exception("Cannot find home country and population: {} (extracting from: '{}' -> {})".format(
                                    name,
                                    ld.get('population', ''),
                                    ld.get('country-gl')))
                        else:
                            log('country: {}'.format(home_country_population.group('country')))

                            for c in ld.get('country-gl', ld.get('country', [])):
                                cm = country_rgx.match(c)
                                log('c: {} == {} --> {}'.format(cm.group('name'), home_country_population.group('country').strip(), cm.group('name') == home_country_population.group('country').strip()))
                                if cm and cm.group('name') == home_country_population.group('country').strip():
                                    home_country_name = home_country_population.group('country').strip()
                                    home_country_code = cm.group('code')
                                    home_country_pop = home_country_population.group('pop')
                                    break
                            else:
                                raise Exception("Cannot figure out home country because there's multiple countries specified in the population field: {}".format(lk))
                    else:
                        home_country_name = home_country_population.group('country').strip()
                        log('home_country_name: {}'.format(home_country_name))
                        if home_country_name.endswith(', decreasing'):
                            home_country_name = home_country_name[:-12]
                        elif ', ' in home_country_name:
                            home_country_name = ' '.join(reversed(home_country_name.split(', ')))
                        home_country_code = ''

                elif (ld.get('name').endswith('i') and any(ld.get('name')[:-1] in c for c in ld.get('country-gl', ld.get('country', []))) or
                      ld.get('name').endswith('ian') and any(ld.get('name')[:-1] in c for c in ld.get('country-gl', ld.get('country', [])))):
                    # Nepali --> Nepal
                    # Estonian --> Estonia
                    cty = [c for c in ld.get('country-gl', ld.get('country', [])) if ld.get('name')[:-1] in c][0]
                    cm = country_name_and_code_rgx.match(cty)

                    home_country_name = cm.group('name')
                    home_country_code = cm.group('code')
                    home_country_pop = ld.get('population_numeric', 0)

                else:
                    # If we don't have a country code off the bat, try to guess
                    log('Attempting to guess country code...')
                    log('population [{}]: {}'.format(type(ld.get('population', '')), ld.get('population', '')))
                    cm = find_country_rgx.match(ld.get('population', ''))
                    if cm and any(cm.group('name') in c for c in ld.get('country', []) + ld.get('country-gl', [])):
                        log('cm name: {}'.format(cm.group('name')))
                        home_country_name = cm.group('name')
                        home_country_code = ''
                        home_country_pop = ld.get('population_numeric', 0)
                    elif ld.get('country', [''])[0].endswith(']'):
                        log("country ends in ']': {}".format(ld.get('country')[0]))
                        # Grab the country name
                        cname = country_name_rgx.match(ld.get('country')[0]).group('name')
                        log('country name: {}'.format(cname))

                        # Search for the country
                        for c in ld.get('country-gl', ld.get('country', [])):
                            cm = country_rgx.match(c)
                            if cm and cm.group('name') == cname:
                                home_country_name = cm.group('name')
                                home_country_code = cm.group('code')
                                home_country_pop = ld.get('population_numeric')
                                break
                        else:
                            raise Exception("Cannot find home country and population: {} (extracting from: '{}' -> {})".format(
                                name,
                                ld.get('population', ''),
                                ld.get('country-gl')))

                    elif "Also in " in ld.get('location', ''):
                        log("Guessing from locations: {}".format(ld.get('location', '')))
                        m = re.match(r'.*Also in (?P<also_ins>[^.]+)\.', ld.get('location', ''))
                        also_ins = m.group('also_ins').split(', ')
                        log('also_ins: {}'.format(also_ins))

                        country_name_and_codes = [
                            (country_name_and_code_rgx.match(c).group('name'),
                             country_name_and_code_rgx.match(c).group('code'))
                            for c in ld['country']]

                        home_country_name = list(set([c[0] for c in country_name_and_codes]) - set(also_ins))[0]
                        home_country_code = [c[1] for c in country_name_and_codes if c[0] == home_country_name][0]
                        home_country_pop = ld.get('population_numeric', 0)

                    elif ld.get('language_maps', '') and len(re.sub(r',\s+Map\s+\d+$', ld.get('language_maps', ''), '').split(', ')) == 1:
                        log("Guessing from maps: {}".format(ld.get('language_maps', '')))
                        country_name_and_codes = [
                            (country_name_and_code_rgx.match(c).group('name').replace(' the', ''),
                             country_name_and_code_rgx.match(c).group('code'))
                            for c in ld['country']]
                        log('country_name_and_codes: {}'.format(country_name_and_codes))

                        home_country_name = re.sub(r',\s+Map\s+\d+$', '', ld.get('language_maps', '')).split(', ')[0]
                        log('home_country_name: {}'.format(home_country_name))
                        for c in country_name_and_codes:
                            log('c: {} == {} --> {}'.format(c[0], home_country_name, c[0] == home_country_name))
                            if c[0] == home_country_name:
                                home_country_code = c[1]
                                break
                        else:
                            home_country_name = re.sub(r'^(?:Central|(?:North|East|South|West)(?:ern)?\s*)*', '', home_country_name)
                            for c in country_name_and_codes:
                                log('modified c: {} == {} --> {}'.format(c[0], home_country_name, c[0] == home_country_name))
                                if home_country_name in c[0]:
                                    home_country_code = c[1]
                                    break
                            else:
                                for c in country_name_and_codes:
                                    log('more modified c: {} in {} --> {}'.format(home_country_name, c[0], c[0] in home_country_name))
                                    if c[0] == home_country_name:
                                        home_country_code = c[1]
                                        break
                                else:
                                    if ' and ' in ld.get('language_maps', ''):
                                        home_country_name = re.sub(r',\s+Map\s+\d+$', '', ld.get('language_maps', '')).split(' and ')[0]
                                        log('home_country_name: {}'.format(home_country_name))
                                        for c in country_name_and_codes:
                                            log('c: {} == {} --> {}'.format(c[0], home_country_name, c[0] == home_country_name))
                                            if c[0] == home_country_name:
                                                home_country_code = c[1]
                                                break
                                        else:
                                            home_country_name = re.sub(r'^(?:Central|(?:North|East|South|West)(?:ern)?\s*)*', '', home_country_name)
                                            for c in country_name_and_codes:
                                                log('and modified c: {} == {} --> {}'.format(c[0], home_country_name, c[0] == home_country_name))
                                                if home_country_name in c[0]:
                                                    home_country_code = c[1]
                                                    break
                                            else:
                                                for c in country_name_and_codes:
                                                    log('and more modified c: {} in {} --> {}'.format(home_country_name, c[0], c[0] in home_country_name))
                                                    if c[0] == home_country_name:
                                                        home_country_code = c[1]
                                                        break
                                                else:
                                                    raise Exception("Map data inconclusive: {}".format(ld.get('language_maps', '')))
                                    else:
                                        raise Exception("Map data inconclusive: {}".format(ld.get('language_maps', '')))
                        home_country_pop = ld.get('population_numeric', 0)

                    else:
                        log('[{}]'.format(lk))
                        log('country: {}'.format(ld.get('country', '')))
                        log('country-gl: {}'.format(ld.get('country-gl', '')))
                        cm = country_rgx.match((ld.get('country-gl', []) + ld.get('country', []))[0])
                        if cm:
                            home_country_name = cm.group('name')
                            home_country_code = cm.group('code')
                            home_country_pop = int(ld.get('population_numeric', 0))
                        else:
                            raise Exception("Cannot find home country and population: {} (extracting from: '{}' -> {})".format(
                                name,
                                ld.get('population', ''),
                                home_country_population))

                    if ', ' in home_country_name:
                        home_country_name = '{}{}'.format(*reversed(home_country_name.split(', ')))

            overall_population = overall_pop_rgx.match(ld.get('population', ''))
            if overall_population is not None:
                overall_pop = int(overall_population.group('total_population').replace(',', ''))
            else:
                overall_pop = 0

            log('[{}] language status: {}'.format(lk, ld.get('language_status', '')))
            ldstatus = dev_status_rgx.match(ld.get('language_status', ''))
            log(ldstatus)

            # Add families
            families = []
            for i, fname in enumerate(ld.get('classification-gl', [])):
                f_m = family_name_rgx.match(fname)
                try:
                    log('family glottolog_id: {}, name: {}'.format(f_m.group('glottolog_id'), f_m.group('glottolog_name')))
                    family = Family.objects.get(
                        Q(glottolog_id=f_m.group('glottolog_id')) |
                        Q(name=f_m.group('glottolog_name')))
                except Family.DoesNotExist:
                    try:
                        log('family slug: {}'.format(slugify(f_m.group('glottolog_name'))))
                        family = Family.objects.get(slug=slugify(f_m.group('glottolog_name')))
                    except Family.DoesNotExist:
                        log('family name: {}, id: {}, parent: {}'.format(f_m.group('glottolog_name'), f_m.group('glottolog_id'), families[-1] if families else None))
                        family = Family.objects.create(
                            name=f_m.group('glottolog_name'),
                            glottolog_id=f_m.group('glottolog_id'),
                            parent=families[-1] if families else None)
                finally:
                    families.append(family)

            try:
                ma = Macroarea.objects.get(name=ld['macroarea-gl'])
            except KeyError:
                ma = None

            try:
                log('glottolog_id: {}'.format(lk))
                l = Language.objects.get(glottolog_id=lk)
            except Language.DoesNotExist:
                try:
                    log('iso639_3: {}'.format(ld['iso_639-3']))
                    l = Language.objects.get(iso639_3=ld['iso_639-3'])
                except Language.DoesNotExist:
                    try:
                        log('name_gl: {}'.format(ld.get('name-gl', name.strip())))
                        l = Language.objects.get(name_gl=ld.get('name-gl', name.strip()))
                    except Language.DoesNotExist:
                            log('Creating language: {}'.format(name.strip()))
                            l = Language()
                    except Language.MultipleObjectsReturned:
                        log('name_gl: {}, family: {}'.format(ld.get('name-gl', name.strip()), families[-1] if families else None))
                        l = Language.objects.get(name_gl=ld.get('name-gl', name.strip()), family=families[-1] if families else None)
            finally:
                l.name = name
                l.name_gl = ld.get('name-gl', name.strip())
                l.iso639_1 = self.iso_index[ld['iso_639-3']]['iso639-1']
                l.iso639_2t = self.iso_index[ld['iso_639-3']]['iso639-2t']
                # This will be fixed when we import languages from Wikipedia
                l.iso639_2b = self.iso_index[ld['iso_639-3']]['iso639-2b']
                l.iso639_3 = ld['iso_639-3']
                l.glottolog_id = lk
                if ldstatus:
                    l.development_status = [i for i in Language.DEVELOPMENT_STATUS if i[1] == ldstatus.group('status')][0][0]
                    l.development_status_notes = ldstatus.group('notes')
                else:
                    l.development_status = Language.DEVELOPMENT_STATUS.unattested
                    l.development_status_notes = None
                l.family = families[-1] if families else None
                l.population = overall_pop
                l.macroarea = ma if ma else None
                l.notes = ld.get('other_comments', '')
                l.save()

            self.iso_index[ld['iso_639-3']]['language'] = l

            # Add alternate names for languages
            for alt_name in ld.get('alternate_names', []):
                log('alt name: {}'.format(alt_name))
                try:
                    aln = AlternativeName.objects.get(
                        Q(name=alt_name,
                          language=l,
                          type=AlternativeName.TYPE.name,
                          in_language=en) |
                        Q(slug=slugify('{}_({})'.format(alt_name, en.iso639_3))))
                except AlternativeName.DoesNotExist:
                    aln = AlternativeName.objects.create(
                        name=alt_name,
                        language=l,
                        type=AlternativeName.TYPE.name,
                        in_language=en)

            # This is a little messy
            for note in re.split(r'(?<!c)\.\s+(?=[^)]*(?:\(|$))', ld.get('language_development', '').strip('.')):
                # ''.split('. ') == [''], so we have to manually skip that
                if note == '':
                    continue

                dnote = DevelopmentNote()

                note = note.strip('.').strip()
                log('note: {}'.format(note))

                m = re.match(r'^(?P<type>Bible(?:\s+portions)?|OT|NT):?(?:\s*(?:c\.?|circa))?\s*(?:(?P<start>\d+)(?:-(?P<end>\d+))?)?(?:[s\.]+)?$', note)
                if m:
                    log('Bible/OT/NT: {}'.format(note))
                    # DevelopmentNoteBible
                    if m.group('type') == 'Bible':
                        part = DevelopmentNoteBible.PART_TYPE.all
                    elif m.group('type') == 'Bible portions':
                        part = DevelopmentNoteBible.PART_TYPE.part
                    elif m.group('type') == 'OT':
                        part = DevelopmentNoteBible.PART_TYPE.old
                    elif m.group('type') == 'NT':
                        part = DevelopmentNoteBible.PART_TYPE.new
                    else:
                        part = None

                    try:
                        dnote = DevelopmentNoteBible.objects.get(language=l, note=note)
                    except DevelopmentNoteBible.DoesNotExist:
                        dnote = DevelopmentNoteBible(language=l, note=note)

                    dnote.part = part
                    if m.group('start'):
                        dnote.start = datetime(int(m.group('start')), 1, 1)
                    else:
                        dnote.start = None
                    if m.group('end'):
                        dnote.end = datetime(int(m.group('end')), 1, 1)
                    else:
                        dnote.end = None

                elif note.startswith('Literacy rate in '):
                    log('Literacy: {}'.format(note))
                    if '%' in note and re.match(r'^(?:\w+|\s+|\:)*(?P<low>\d+)%?(?:-(?P<high>\d+)%)?', note[21:]):
                        log('Literarcy percent: {}'.format(note))
                        # DevelopmentNoteLiteracyPercent
                        m = re.match(r'^(?:\w+|\s+|\:)*(?P<low>\d+)%?(?:-(?P<high>\d+)%)?', note[21:])
                        try:
                            dnote = DevelopmentNoteLiteracyPercent.objects.get(language=l, note=note)
                        except DevelopmentNoteLiteracyPercent.DoesNotExist:
                            dnote = DevelopmentNoteLiteracyPercent(
                                language=l,
                                note=note)

                        dnote.low = int(m.group('low'))
                        dnote.high = int(m.group('high') or m.group('low'))

                    elif lit_tag_rgx.match(note[21:]):
                        log('Literacy tag: {}'.format(note))
                        m = lit_tag_rgx.match(note[21:])
                        try:
                            dnote = DevelopmentNoteLiteracyTag.objects.get(language=l, note=note)
                        except DevelopmentNoteLiteracyTag.DoesNotExist:
                            dnote = DevelopmentNoteLiteracyTag(
                                language=l,
                                note=note)

                        dnote.name = m.group('tag')

                    elif re.match(r'.*(?:\d+,)*\d+ can read, (?:\d+,)*\d+ can write', note):
                        log('Literacy can read, can write: {}'.format(note))
                        try:
                            rd_dnote = DevelopmentNoteLiteracy.objects.get(
                                language=l,
                                type=DevelopmentNoteLiteracy.LITERACY_TYPE.read,
                                note=re.sub(r', (?:\d+,)*\d+ can write', '', note))
                        except DevelopmentNoteLiteracy.DoesNotExist:
                            rd_dnote = DevelopmentNoteLiteracy(
                                language=l,
                                type=DevelopmentNoteLiteracy.LITERACY_TYPE.read,
                                note=re.sub(r', (?:\d+,)*\d+ can write', '', note))

                        m = re.match(r'.*(?P<low>(?:\d+,)*\d+)(?:-(?P<high>(?:\d+,)*\d+))? can read, (?:\d+,)*\d+(?:-(?:\d+,)*\d+)? can write', note)

                        rd_dnote.low = int(m.group('low').replace(',', ''))
                        rd_dnote.high = int((m.group('high') or m.group('low')).replace(',', ''))
                        rd_dnote.language = l
                        lom = re.match(r'.*L(?P<ordinal>\d+).*', note)
                        if lom:
                            rd_dnote.ordinal = int(lom.group('ordinal'))
                        rd_dnote.note = re.sub(r', (?:\d+,)*\d+ can write', '', note)
                        rd_dnote.save()

                        for lcode in re.findall(r'\[[a-z]{3}\]', note):
                            if rd_dnote not in note_lcodes:
                                note_lcodes[rd_dnote] = [lcode]
                            else:
                                note_lcodes[rd_dnote].append(lcode)

                        try:
                            wr_dnote = DevelopmentNoteLiteracy.objects.get(
                                language=l,
                                type=DevelopmentNoteLiteracy.LITERACY_TYPE.write,
                                note=re.sub(r'(?:\d+,)*\d+ can read,\s*', '', note))
                        except DevelopmentNoteLiteracy.DoesNotExist:
                            wr_dnote = DevelopmentNoteLiteracy(
                                language=l,
                                type=DevelopmentNoteLiteracy.LITERACY_TYPE.write,
                                note=re.sub(r'(?:\d+,)*\d+ can read,\s*', '', note))

                        m = re.match(r'.*(?:\d+,)*\d+(?:-(?:\d+,)*\d+)? can read, (?P<low>(?:\d+,)*\d+)(?:-(?P<high>(?:\d+,)*\d+))? can write', note)

                        wr_dnote.low = int(m.group('low').replace(',', ''))
                        wr_dnote.high = int((m.group('high') or m.group('low')).replace(',', ''))
                        wr_dnote.language = l
                        lom = re.match(r'.*L(?P<ordinal>\d+).*', note)
                        if lom:
                            wr_dnote.ordinal = int(lom.group('ordinal'))
                        wr_dnote.note = re.sub(r'(?:\d+,)*\d+ can read,\s*', '', note)
                        wr_dnote.save()

                        for lcode in re.findall(r'\[[a-z]{3}\]', note):
                            if wr_dnote not in note_lcodes:
                                note_lcodes[wr_dnote] = [lcode]
                            else:
                                note_lcodes[wr_dnote].append(lcode)

                        continue

                    elif ' can read and write' in note:
                        log('Literacy can read and write: {}'.format(note))
                        try:
                            rd_dnote = DevelopmentNoteLiteracy.objects.get(
                                language=l,
                                type=DevelopmentNoteLiteracy.LITERACY_TYPE.read,
                                note=note.replace('can read and write', 'can read'))
                        except DevelopmentNoteLiteracy.DoesNotExist:
                            rd_dnote = DevelopmentNoteLiteracy(
                                language=l,
                                type=DevelopmentNoteLiteracy.LITERACY_TYPE.read,
                                note=note.replace('can read and write', 'can read'))

                        m = re.match(r'.*(?P<low>[\d,]+)(?:-(?P<high>[\d,]+))? can read and write', note)

                        rd_dnote.low = int(m.group('low').replace(',', ''))
                        rd_dnote.high = int((m.group('high') or m.group('low')).replace(',', ''))
                        rd_dnote.language = l
                        lom = re.match(r'.*L(?P<ordinal>\d+).*', note)
                        if lom:
                            rd_dnote.ordinal = int(lom.group('ordinal'))
                        rd_dnote.note = note.replace('can read and write', 'can read')
                        rd_dnote.save()

                        for lcode in re.findall(r'\[[a-z]{3}\]', note):
                            if rd_dnote not in note_lcodes:
                                note_lcodes[rd_dnote] = [lcode]
                            else:
                                note_lcodes[rd_dnote].append(lcode)

                        try:
                            wr_dnote = DevelopmentNoteLiteracy.objects.get(
                                language=l,
                                type=DevelopmentNoteLiteracy.LITERACY_TYPE.write,
                                note=note.replace('can read and write', 'can write'))
                        except DevelopmentNoteLiteracy.DoesNotExist:
                            wr_dnote = DevelopmentNoteLiteracy(
                                language=l,
                                type=DevelopmentNoteLiteracy.LITERACY_TYPE.write,
                                note=note.replace('can read and write', 'can write'))

                        m = re.match(r'.*(?P<low>[\d,]+)(?:-(?P<high>[\d,]+))?.*', note)

                        wr_dnote.low = int(m.group('low').replace(',', ''))
                        wr_dnote.high = int(m.group('high').replace(',', '')) if m.group('high') else wr_dnote.low
                        wr_dnote.language = l
                        lom = re.match(r'.*L(?P<ordinal>\d+).*', note)
                        if lom:
                            wr_dnote.ordinal = int(lom.group('ordinal'))
                        wr_dnote.note = note.replace('can read and write', 'can write')
                        wr_dnote.save()

                        for lcode in re.findall(r'\[[a-z]{3}\]', note):
                            if wr_dnote not in note_lcodes:
                                note_lcodes[wr_dnote] = [lcode]
                            else:
                                note_lcodes[wr_dnote].append(lcode)

                        continue

                    elif regex.match(r'(?P<subset>(?<!.*(?P<modifier>\w+)?\s*(?:[Mm]en|[Ww]omen)?\s*(?:over|under)\s*))(?(subset)|.*)\d+ can (?P<verb>read|write).*', note):
                        log('Literacy subset: {}'.format(note))
                        for note_piece in note.split(', '):
                            m = re.match(r'(?P<low>[\d,]+)(?:-(?P<high>[\d,]+))? can (?P<type>read|write)', note)

                            if m.group('type') == 'read':
                                type_ = DevelopmentNoteLiteracy.LITERACY_TYPE.read
                            elif m.group('type') == 'write':
                                type_ = DevelopmentNoteLiteracy.LITERACY_TYPE.write

                            try:
                                dnote = DevelopmentNoteLiteracy.objects.get(
                                    language=l,
                                    type=type_,
                                    note=note)
                            except DevelopmentNoteLiteracy.DoesNotExist:
                                dnote = DevelopmentNoteLiteracy(
                                    language=l,
                                    type=type_,
                                    note=note)

                            dnote.low = int(m.group('low').replace(',', ''))
                            dnote.high = int(m.group('high').replace(',', '')) or dnote.low

                            dnote.language = l
                            lom = re.match(r'.*L(?P<ordinal>\d+).*', note)
                            if lom:
                                dnote.ordinal = int(lom.group('ordinal'))
                            dnote.note = note
                            dnote.save()

                        for lcode in re.findall(r'\[[a-z]{3}\]', note):
                            if dnote not in note_lcodes:
                                note_lcodes[dnote] = [lcode]
                            else:
                                note_lcodes[dnote].append(lcode)

                        continue
                    else:
                        log('Literacy note: {}'.format(note))
                        dnote, _ = DevelopmentNote.objects.get_or_create(language=l, note=note)

                elif note.replace("'", '') != '' and ')' not in note:
                    log('Guessing...')
                    m = percent_rgx.match(note)
                    if m:
                        log('Literacy percent: {}'.format(note))
                        # DevelopmentNoteLiteracyPercent
                        try:
                            dnote = DevelopmentNoteLiteracyPercent.objects.get(language=l, note=note)
                        except DevelopmentNoteLiteracyPercent.DoesNotExist:
                            dnote = DevelopmentNoteLiteracyPercent(language=l, note=note)

                        dnote.low = int(m.group('low'))
                        dnote.high = int(m.group('high') or m.group('low'))

                    elif tag_rgx.match(note):
                        log('Tag: {}'.format(note))
                        try:
                            dnote = DevelopmentNoteTag.objects.get(language=l, note=note)
                        except DevelopmentNoteTag.DoesNotExist:
                            dnote = DevelopmentNoteTag(language=l, note=note)

                        # DevelopmentNoteTag
                        m = tag_rgx.match(note)
                        dnote.name = m.group('tag')

                    else:
                        # DevelopmentNote
                        log('Note: {}'.format(note))
                        dnote, _ = DevelopmentNote.objects.get_or_create(language=l, note=note)
                else:
                    log('Note: {}'.format(note))
                    dnote, _ = DevelopmentNote.objects.get_or_create(language=l, note=note)

                dnote.language = l
                m = re.match(r'.*L(?P<ordinal>\d+).*', note)
                if m:
                    dnote.ordinal = int(m.group('ordinal'))
                dnote.note = note
                dnote.save()

                for lcode in re.findall(r'\[[a-z]{3}\]', note):
                    if dnote not in note_lcodes:
                        note_lcodes[dnote] = [lcode]
                    else:
                        note_lcodes[dnote].append(lcode)

            country_names = {}

            if home_country_name.startswith('Timor-Leste'):
                home_country_name = 'East Timor'

            # Search for the country code by the country name
            if not home_country_code:
                for country in ld.get('country-gl', []) + ld.get('country', []):
                    if ', ' in country:
                        if country[-4] == '[' and country[-1] == ']':
                            home_country_code = country[-3:-1]
                            break
                        else:
                            country = '{}{}'.format(*reversed(country.split(', ')))
                    # Grab the country name
                    log('country: {} (matching to {})'.format(country, home_country_name))
                    cty = country_name_rgx.match(country).group('name')
                    log('country: {} (matching to {}) --> {}'.format(cty, home_country_name, cty == home_country_name))

                    if cty == home_country_name:

                        m = country_rgx.match(country)
                        if m:
                            cname = m.group('name')
                            ccode = m.group('code')

                            if ',' in cname:
                                cname = '{}{}'.format(*reversed(cname.split(', ')))
                            if cname.startswith('The '):
                                cname = cname[4:]

                            country_names[ccode] = cname

                            log('{} == {} -> {}'.format(cname, home_country_name, cname == home_country_name))
                            if cname == home_country_name:
                                home_country_code = ccode
                                break

            log('country code: {}'.format(home_country_code))
            log('country name: {}'.format(home_country_name))
            if home_country_code:
                home_country = Country.objects.get(code=home_country_code)
            else:
                if home_country_name == 'Congo (Kinshasa)':
                    home_country_name = 'Democratic Republic of the Congo'

                try:
                    home_country = Country.objects.get(name=home_country_name)
                except Country.DoesNotExist:
                    try:
                        home_country = Country.objects.get(name=home_country_name.replace(' ', '').capitalize())
                    except Country.DoesNotExist:
                        home_country = Country.objects.get(
                            alt_names__kind=AlternativeCountryName.TYPE.name,
                            alt_names__name=home_country_name)

            ui = create_used_in(
                home_country,
                l,
                [],  # known_ases
                home_country_pop,
                ld.get('language_status', ''),
                ld.get('language_use', ''))

            asi_data = ld.get('also_spoken_in', {})

            for ccode, ccname in country_names.items():
                if ccname in asi_data.keys():
                    cdata = asi_data[ccname]

                    country = Country.objects.get(code=ccode)

                    if 'Language name' in cdata:
                        name = cdata['Language name']
                        m = language_name_rgx.match(name)
                        if m:
                            name = '{} {}{}'.format(m.group('language_prefix'), m.group('mother_language'), ' [{}]'.format(m.group('code')) if m.group('code') else '')
                        try:
                            known_as = AlternativeName.objects.get(
                                language=l,
                                name=name)
                        except AlternativeName.DoesNotExist:
                            # If we're doing alternative names for English, they're in English
                            if lk == 'stan1293':
                                in_language = l
                                colloquial = True
                            elif len(re.sub(r'[- a-zA-Z0-9]', '', name)) > 0:
                                in_language = l
                                colloquial = True
                            else:
                                in_language = None
                                colloquial = False

                            known_as = AlternativeName.objects.create(
                                language=l,
                                name=name,
                                type=AlternativeName.TYPE.name,
                                in_language=in_language,
                                colloquial=colloquial)

                        known_ases = [known_as]

                        for an in [_ for _ in cdata.get('Alternate Names', '').split(', ') if _]:
                            ka, _ = AlternativeName.objects.get_or_create(
                                name=an.strip(),
                                language=l,
                                type=AlternativeName.TYPE.name,
                                in_language=l)
                            known_ases.append(ka)

                    else:
                        known_ases = []

                    create_used_in(
                        country,
                        l,
                        known_ases,
                        cdata.get('Population', ''),
                        cdata.get('Status', None),
                        cdata.get('Language Use', ''))

            dstr = ld.get('dialects', '')
            if dstr:
                log(dstr)
                dialect_soup = ', '.join(dstr)
                if 'Lexical similarity: ' in dialect_soup:
                    dialect_soup, *lex_sim_soup = dialect_soup.split('Lexical similarity: ')
                    lex_sim_soup = ', '.join([ls.strip().strip('.') for ls in lex_sim_soup])
                    if '. ' in lex_sim_soup:
                        lex_sim_soup, *lex_sim_notes = lex_sim_soup.split('. ')

                        l.lexical_similarity_notes = '{}.'.format('. '.join(lex_sim_notes))
                        l.save()

                    add_lexical_similarities(l, lexical_similarities, lex_sim_soup)

                add_dialects(ui, dialect_soup)

            chars = []
            for char in ld.get('typology', []):
                if syllable_pattern_rgx.match(char):
                    # Syllable Patterns
                    # Uniquify
                    for sp in list(set(clist[cvs_index] for clist in syllable_pattern_rgx.findall(char))):
                        try:
                            syllable_pattern = l.characteristics.instance_of(SyllablePattern).get(syllablepattern__pattern=sp)

                        except Characteristic.DoesNotExist:
                            syllable_pattern, _ = SyllablePattern.objects.get_or_create(
                                pattern=sp,
                                notes=char)

                            if _:
                                log('Created SyllablePattern:')
                                plog({
                                    'language': l,
                                    'pattern': sp,
                                    'notes': char,
                                })

                        if syllable_pattern not in l.characteristics.instance_of(SyllablePattern):
                            l.characteristics.add(syllable_pattern)

                        chars.append(syllable_pattern)
                        char = re.sub(r'\b{}(?:,\s+|\s+|$)'.format(sp.replace(' ', r'\s+').replace('(', r'\(').replace(')', r'\)')), '', char)

                # Subject-Verb-Object orders
                if svo_rgx.match(char):
                    for c in svo_rgx.findall(char):
                        try:
                            svo = l.characteristics.instance_of(SubjectVerbObjectOrder).get(subjectverbobjectorder__order=c)

                        except Characteristic.DoesNotExist:
                            svo, _ = SubjectVerbObjectOrder.objects.get_or_create(order=c, notes=char)

                            if _:
                                log('Created SubjectVerbObjectOrder:')
                                plog({
                                    'language': l,
                                    'order': c,
                                    'notes': char,
                                })

                        if svo not in l.characteristics.instance_of(SubjectVerbObjectOrder):
                            l.characteristics.add(svo)

                        chars.append(svo)
                        char = re.sub(r'\b{}\b(?:,\s+|\s+|:\s+|\)$|\s*$)'.format(c), '', char)

                # Word Type Orders
                word_orders = {}
                words = []
                modifier = None
                positioner = ''
                related_word = ''
                word_order_state = 'word_types'
                log("----")
                log('char: {}'.format(char))
                log('wt_rgx.findall: {}'.format([wtr[1] for wtr in wt_rgx.findall(char)]))
                log('wt_token_rgx.findall: {}'.format(wt_token_rgx.findall(char)))

                for c2 in [wtr[1] for wtr in wt_rgx.findall(char)]:
                    for cpart, cpart_next in zip(wt_token_rgx.findall(c2), wt_token_rgx.findall(c2)[1:] + ['']):
                        # Okay, at this point we have:
                        #
                        # ( (word types) (relative positioner) (word type) )*
                        # or
                        # ( (word types) (absolute positioner) )*
                        #
                        # so we can use a state machine to parse these sentences:
                        #
                        #     state                      possible next state
                        # -------------                 --------------------
                        # WORD_TYPES              ->    WORD_TYPES,
                        #                               MODIFIER,
                        #                               ABS_POS,
                        #                               REL_POS
                        #
                        # MODIFIER                ->    ABS_POS,
                        #                               REL_POS
                        #
                        # ABS_POS                 ->    WORD_TYPES,
                        #                               ABS_POS
                        #
                        # REL_POS                 ->    WORD_TYPES
                        #
                        if word_order_state == 'word_types':
                            if cpart in BOTH_WORD_TYPES:
                                log('word type: {}'.format(cpart))
                                words += [cpart]

                            elif cpart in MODIFIERS:
                                log('modifier: {}'.format(cpart))
                                modifier = cpart
                                word_order_state = 'modifier'

                            elif cpart in ABSOLUTE_POSITIONERS:
                                log('positioner: {}'.format(cpart))
                                positioner = cpart
                                word_order_state = 'abs_pos'

                            elif cpart in RELATIVE_POSITIONERS:
                                log('positioner: {}'.format(cpart))
                                positioner = cpart
                                word_order_state = 'rel_pos'

                            else:
                                raise Exception("Error: Unknown word in 'word types' state: {}".format(cpart))

                        elif word_order_state == 'modifier':
                            if cpart in ABSOLUTE_POSITIONERS:
                                log('positioner: {}'.format(cpart))
                                positioner = cpart
                                word_order_state = 'abs_pos'

                            elif cpart in RELATIVE_POSITIONERS:
                                log('positioner: {}'.format(cpart))
                                positioner = cpart
                                word_order_state = 'rel_pos'

                            else:
                                raise Exception("Error: Unknown word in 'modifier' state: {}".format(cpart))

                        elif word_order_state == 'abs_pos':
                            # final noun heads
                            if cpart in BOTH_WORD_TYPES and positioner and not words:
                                word_orders.setdefault(c2, []).append({
                                    'words': [cpart],
                                    'modifier': modifier,
                                    'positioner': positioner,
                                })
                                modifier = None
                                positioner = ''
                                word_order_state = 'word_types'

                            else:

                                word_orders.setdefault(c2, []).append({
                                    'words': words,
                                    'modifier': modifier,
                                    'positioner': positioner,
                                })

                                if cpart in BOTH_WORD_TYPES:
                                    words = [cpart]
                                    modifier = None
                                    positioner = ''
                                    related_word = ''
                                    word_order_state = 'word_types'

                                else:
                                    raise Exception("Error: Unknown word in 'abs pos' state: {}".format(cpart))

                        elif word_order_state == 'rel_pos':
                            if cpart in BOTH_WORD_TYPES:
                                log('related word: {}'.format(cpart))
                                word_orders.setdefault(c2, []).append({
                                    'words': words,
                                    'modifier': modifier,
                                    'positioner': positioner,
                                    'related_word': cpart,
                                })

                                if cpart_next in RELATIVE_POSITIONERS:
                                    word_order_state = 'rel_pos'
                                else:
                                    words = []
                                    word_order_state = 'word_types'

                                modifier = None
                                positioner = ''
                                related_word = ''

                            elif cpart in RELATIVE_POSITIONERS:
                                positioner = cpart
                                word_order_state = 'word_types'

                            else:
                                raise Exception("Error: Unknown word in 'rel pos' state: {}".format(cpart))

                        else:
                            raise Exception("Error: Unknown state '{}'".format(word_order_state))

                    char = re.sub(r'\b{}(?:,\s+|$)'.format(c2), '', char)

                log('word_orders:')
                plog(word_orders)

                clean_word_orders(word_orders)

                for k, wos in word_orders.items():
                    for d in wos:
                        log('d:')
                        plog(d)
                        if 'related_word' in d:
                            for word in d['words']:
                                try:
                                    wo = l.characteristics.instance_of(RelativeWordTypeOrder).get(
                                        relativewordtypeorder__word_type=c,
                                        relativewordtypeorder__modifier=d['modifier'],
                                        relativewordtypeorder__position=d['positioner'],
                                        relativewordtypeorder__related_word_type=d['related_word'])

                                except Characteristic.DoesNotExist:
                                    try:
                                        wo = RelativeWordTypeOrder.objects.get(
                                            notes=c,
                                            word_type=c,
                                            modifier=d['modifier'],
                                            position=d['positioner'],
                                            related_word_type=d['related_word'])

                                    except RelativeWordTypeOrder.DoesNotExist:
                                        wo, _ = RelativeWordTypeOrder.objects.get_or_create(
                                            notes=c,
                                            word_type=word,
                                            modifier=d['modifier'],
                                            position=d['positioner'],
                                            related_word_type=d['related_word'])

                                        if _:
                                            log('Created RelativeWordTypeOrder:')
                                            plog({
                                                'language': l,
                                                'word_type': word,
                                                'modifier': d['modifier'],
                                                'position': d['positioner'],
                                                'related_word_type': d['related_word'],
                                                'notes': c,
                                            })

                                if wo not in l.characteristics.instance_of(RelativeWordTypeOrder):
                                    l.characteristics.add(wo)

                                chars.append(wo)

                        else:
                            for word in d['words']:
                                try:
                                    wo = l.characteristics.instance_of(AbsoluteWordTypeOrder).get(
                                        absolutewordtypeorder__word_type=word,
                                        absolutewordtypeorder__modifier=d['modifier'],
                                        absolutewordtypeorder__position=d['positioner'])

                                except Characteristic.DoesNotExist:
                                    try:
                                        wo = AbsoluteWordTypeOrder.objects.get(
                                            notes=c,
                                            word_type=word,
                                            modifier=d['modifier'],
                                            position=d['positioner'])

                                    except AbsoluteWordTypeOrder.DoesNotExist:
                                        wo, _ = AbsoluteWordTypeOrder.objects.get_or_create(
                                            notes=c,
                                            word_type=word,
                                            modifier=d['modifier'],
                                            position=d['positioner'])

                                        if _:
                                            log('Created AbsoluteWordTypeOrder:')
                                            plog({
                                                'language': l,
                                                'word_type': word,
                                                'modifier': d['modifier'],
                                                'position': d['positioner'],
                                                'notes': c,
                                            })

                                if wo not in l.characteristics.instance_of(AbsoluteWordTypeOrder):
                                    l.characteristics.add(wo)

                                chars.append(wo)

                if cv_num_rgx.match(char):
                    for m in cv_num_rgx.findall(char):
                        if 'consonant phoneme' in m[cv_type_index]:
                            t = SpeechSoundCount.TYPE.consonant_phoneme
                        elif 'vowel phoneme' in m[cv_type_index]:
                            t = SpeechSoundCount.TYPE.vowel_phoneme
                        elif 'consonant' in m[cv_type_index]:
                            t = SpeechSoundCount.TYPE.consonant
                        elif 'vowel' in m[cv_type_index]:
                            t = SpeechSoundCount.TYPE.vowel
                        elif 'diphthong' in m[cv_type_index] or 'dipthong' in m[cv_type_index]:
                            t = SpeechSoundCount.TYPE.diphthong
                        elif 'monophthong' in m[cv_type_index] or 'monopthong' in m[cv_type_index]:
                            t = SpeechSoundCount.TYPE.monophthong
                        elif 'quality' in m[cv_type_index] or 'qualities' in m[cv_type_index]:
                            t = SpeechSoundCount.TYPE.quality
                        else:
                            raise Exception("Unknown SpeechSoundCount type: '{}'".format(m[cv_type_index]))

                        if m[cv_modifier_index]:
                            try:
                                ssc = l.characteristics.instance_of(SpeechSoundCount).get(
                                    # TODO: Need a better way to convert numbers words to numbers
                                    speechsoundcount__number=1 if m[cv_number_index] == 'one' else int(m[cv_number_index]),
                                    speechsoundcount__modifier=m[cv_modifier_index].lower(),
                                    speechsoundcount__type=t)

                            except Characteristic.DoesNotExist:
                                ssc, _ = SpeechSoundCount.objects.get_or_create(
                                    notes=char,
                                    # TODO: Need a better way to convert numbers words to numbers
                                    number=1 if m[cv_number_index] == 'one' else int(m[cv_number_index]),
                                    modifier=m[cv_modifier_index].lower(),
                                    type=t)

                                if _:
                                    log('Created SpeechSoundCount:')
                                    plog({
                                        'language': l,
                                        'number': m[cv_number_index],
                                        'modifier': m[cv_modifier_index].lower(),
                                        'type': t,
                                        'notes': char,
                                    })
                        else:
                            try:
                                ssc = l.characteristics.instance_of(SpeechSoundCount).get(
                                    # TODO: Need a better way to convert numbers words to numbers
                                    speechsoundcount__number=1 if m[cv_number_index] == 'one' else int(m[cv_number_index]),
                                    speechsoundcount__type=t)

                            except Characteristic.DoesNotExist:
                                ssc, _ = SpeechSoundCount.objects.get_or_create(
                                    notes=char,
                                    # TODO: Need a better way to convert numbers words to numbers
                                    number=1 if m[cv_number_index] == 'one' else int(m[cv_number_index]),
                                    type=t)

                                if _:
                                    log('Created SpeechSoundCount:')
                                    plog({
                                        'language': l,
                                        'number': m[cv_number_index],
                                        'type': t,
                                        'notes': char,
                                    })

                        if ssc not in l.characteristics.instance_of(SpeechSoundCount).all():
                            l.characteristics.add(ssc)

                        chars.append(ssc)

                        log('{} ->'.format(char))
                        char = cv_num_repl_rgx.sub('', char)
                        log(char)

                if char:
                        log('remaining char: {}'.format(char))
                        try:
                            log('char_obj: {}'.format(l.characteristics.not_instance_of(AbsoluteWordTypeOrder, RelativeWordTypeOrder, SpeechSoundCount, SubjectVerbObjectOrder, SyllablePattern).exclude(id__in=[ch.id for ch in chars]).filter(notes=char)))
                            char_obj = l.characteristics.not_instance_of(AbsoluteWordTypeOrder, RelativeWordTypeOrder, SpeechSoundCount, SubjectVerbObjectOrder, SyllablePattern).exclude(id__in=[ch.id for ch in chars]).get(notes=char)

                        except Characteristic.DoesNotExist:
                            log('language id: {}'.format(l.id))
                            log('language: {}'.format(model_to_dict(l)))
                            log('characteristics:')
                            plog(Characteristic.objects.not_instance_of(AbsoluteWordTypeOrder, RelativeWordTypeOrder, SpeechSoundCount, SubjectVerbObjectOrder, SyllablePattern).exclude(id__in=[ch.id for ch in chars]).filter(languages=l, notes=char))
                            log('characteristics dict:')
                            plog([model_to_dict(ch) for ch in Characteristic.objects.not_instance_of(AbsoluteWordTypeOrder, RelativeWordTypeOrder, SpeechSoundCount, SubjectVerbObjectOrder, SyllablePattern).exclude(id__in=[ch.id for ch in chars]).filter(languages=l, notes=char)])

                            try:
                                char_obj = Characteristic.objects.not_instance_of(AbsoluteWordTypeOrder, RelativeWordTypeOrder, SpeechSoundCount, SubjectVerbObjectOrder, SyllablePattern).exclude(id__in=[ch.id for ch in chars]).get(notes=char)

                            except Characteristic.DoesNotExist:
                                char_obj = Characteristic.objects.create(notes=char)

                                log('Created Characteristic:')
                                plog({
                                    'language': l,
                                    'notes': char
                                })

                            except Characteristic.MultipleObjectsReturned as e:
                                log('characteristics:')
                                plog(Characteristic.objects.not_instance_of(AbsoluteWordTypeOrder, RelativeWordTypeOrder, SpeechSoundCount, SubjectVerbObjectOrder, SyllablePattern).exclude(id__in=[ch.id for ch in chars]).filter(notes=char))
                                log('characteristics dict:')
                                plog([model_to_dict(ch) for ch in Characteristic.objects.not_instance_of(AbsoluteWordTypeOrder, RelativeWordTypeOrder, SpeechSoundCount, SubjectVerbObjectOrder, SyllablePattern).exclude(id__in=[ch.id for ch in chars]).filter(notes=char)])
                                char_ids = Characteristic.objects.not_instance_of(AbsoluteWordTypeOrder, RelativeWordTypeOrder, SpeechSoundCount, SubjectVerbObjectOrder, SyllablePattern).exclude(id__in=[ch.id for ch in chars]).filter(notes=char)
                                log('AbsoluteWordTypeOrders:')
                                plog(AbsoluteWordTypeOrder.objects.filter(id__in=char_ids))
                                log('RelativeWordTypeOrders:')
                                plog(RelativeWordTypeOrder.objects.filter(id__in=char_ids))
                                log('SpeechSoundCounts:')
                                plog(SpeechSoundCount.objects.filter(id__in=char_ids))
                                log('SubjectVerbObjectOrders:')
                                plog(SubjectVerbObjectOrder.objects.filter(id__in=char_ids))
                                log('SyllablePatterns:')
                                plog(SyllablePattern.objects.filter(id__in=char_ids))
                                raise e

                        except Characteristic.MultipleObjectsReturned as e:
                            log('language id: {}'.format(l.id))
                            log('language: {}'.format(model_to_dict(l)))
                            log('characteristics:')
                            plog(Characteristic.objects.not_instance_of(AbsoluteWordTypeOrder, RelativeWordTypeOrder, SpeechSoundCount, SubjectVerbObjectOrder, SyllablePattern).exclude(id__in=[ch.id for ch in chars]).filter(languages=l, notes=char))
                            log('characteristics dict:')
                            plog([model_to_dict(ch) for ch in Characteristic.objects.not_instance_of(AbsoluteWordTypeOrder, RelativeWordTypeOrder, SpeechSoundCount, SubjectVerbObjectOrder, SyllablePattern).exclude(id__in=[ch.id for ch in chars]).filter(languages=l, notes=char)])
                            plog(Characteristic.objects.not_instance_of(AbsoluteWordTypeOrder, RelativeWordTypeOrder, SpeechSoundCount, SubjectVerbObjectOrder, SyllablePattern).exclude(id__in=[ch.id for ch in chars]).filter(language=l, notes=char).values('polymorphic_ctype'))

                            char_ids = Characteristic.objects.not_instance_of(AbsoluteWordTypeOrder, RelativeWordTypeOrder, SpeechSoundCount, SubjectVerbObjectOrder, SyllablePattern).exclude(id__in=[ch.id for ch in chars]).filter(languages=l, notes=char)
                            log('AbsoluteWordTypeOrders:')
                            plog(AbsoluteWordTypeOrder.objects.filter(id__in=char_ids))
                            log('RelativeWordTypeOrders:')
                            plog(RelativeWordTypeOrder.objects.filter(id__in=char_ids))
                            log('SpeechSoundCounts:')
                            plog(SpeechSoundCount.objects.filter(id__in=char_ids))
                            log('SubjectVerbObjectOrders:')
                            plog(SubjectVerbObjectOrder.objects.filter(id__in=char_ids))
                            log('SyllablePatterns:')
                            plog(SyllablePattern.objects.filter(id__in=char_ids))

                            raise e

                        if char_obj not in l.characteristics.instance_of(Characteristic).exclude(id__in=[ch.id for ch in chars]):
                            l.characteristics.add(char_obj)

                        chars.append(char_obj)

            scripts = []
            # a0 = ld.get('writing', [])
            # a1 = '. '.join(a0)
            # a2 = a1.replace('e. g. ', 'eg')
            # script_soups = re.split(r'\.\s*(?=[^)]*(?:\(|$))', a2)
            for script_soup in '. '.join(ld.get('writing', [])).replace('e. g. ', 'eg:').split('. '):
                if not script_soup:
                    continue

                script_m = script_rgx.match(script_soup)

                if not script_m:
                    log('Unknown: {}'.format(script_soup))

                script_names_m = script_names_rgx.match(script_m.group('script_name'))
                script_name = script_names_m.group('name')
                script_alt_names = script_names_m.group('alt_names')

                if script_name == 'Lahnda':
                    script_name = 'Landa'
                    script_alt_names = ''
                elif script_name == 'Han':
                    script_alt_names = ''
                elif script_name == 'Han, Hiragana':
                    script_name = 'Hiragana'
                elif script_name == 'Naxi Dongba':
                    script_name = 'Dongba'

                if script_alt_names == 'Asomtavruli and Nuskhuri':
                    script_alt_names = 'Asomtavruli with Nuskhuri'

                script, _ = Script.objects.get_or_create(name=script_name)
                # TODO: Figure out types of scripts

                if script.name == 'Hiragana':
                    script.parent, _ = Script.objects.get_or_create(name='Han')
                    script.save()

                if script_names_m.group('name').startswith('Han ('):
                    scripts = []
                    han = script if script.name == 'Han' else Script.objects.get_or_create(name='Han')[0]
                    for sname in re.split(r'(?:,?\s+and|,)\s+', script_names_m.group('alt_names')):
                        scripts.append(Script.objects.get_or_create(parent=han, name=sname)[0])
                else:
                    scripts = [script]

                if script_alt_names:
                    for asname in re.split(r'(?:,?\s+and|,)\s+', script_alt_names):
                        AlternativeScriptName.objects.get_or_create(script=script, name=asname)

                if script_m.group('variant_name'):
                    script, _ = Script.objects.get_or_create(parent=script, name=script_m.group('variant_name'))

                log('styles: {}'.format(script_m.group('style_names')))
                if script_m.group('style_names'):
                    styles = []
                    for ssname in re.split(r'(?:,?\s+and|,)\s+', script_m.group('style_names')):
                        styles.append(ScriptStyle.objects.get_or_create(script=script, name=ssname)[0])
                else:
                    styles = []

                script_notes = script_m.group('notes') or ''

                end_century_m = script_usage_end_century_rgx.match(script_notes)
                end_year_m = script_usage_end_year_rgx.match(script_notes)
                start_year = None
                end_year = None
                if end_century_m:
                    end_year = 100*(int(end_century_m.group('century'))-1)

                    if end_century_m.group('other_century'):
                        if end_century_m.group('turn_of_the_other_century') and \
                           end_century_m.group('turn_of_the_century'):
                            # ~ xx90-xy10
                            end_accuracy_offset = 20
                        elif (end_century_m.group('turn_of_the_other_century') or
                              end_century_m.group('turn_of_the_century')):
                            # ~ 19th century-turn of the 21st century
                            # --> 1933-2010
                            end_accuracy_offset = 77
                        else:
                            # ~ 1933-2066
                            end_accuracy_offset = 67

                        end_accuracy = end_century_offset + 100*(int(end_century_m.group('century')) - int(end_century_m.group('other_century')))

                    elif end_century_m.group('turn_of_the_century'):
                        # ~ xx90-xy10
                        end_accuracy = 20

                    elif end_century_m.group('about'):
                        # about 19th century
                        end_accuracy = 150

                    else:
                        end_accuracy = None

                elif end_year_m:
                    if end_year_m.group('decade'):
                        end_year = int(end_year_m.group('year'))+5
                        end_accuracy = 10
                    elif end_year_m.group('about'):
                        end_year = int(end_year_m.group('year'))
                        end_accuracy = 5
                    else:
                        end_year = int(end_year_m.group('year'))
                        end_accuracy = None

                start_century_m = script_usage_start_century_rgx.match(script_notes)
                start_year_m = script_usage_start_year_rgx.match(script_notes)
                if start_century_m:
                    start_year = 100*(int(start_century_m.group('century'))-1)

                    if start_century_m.group('other_century'):
                        if start_century_m.group('turn_of_the_other_century') and \
                           start_century_m.group('turn_of_the_century'):
                            # ~ xx90-xy10
                            start_accuracy_offset = 20
                        elif (start_century_m.group('turn_of_the_other_century') or
                              start_century_m.group('turn_of_the_century')):
                            # ~ 19th century-turn of the 21st century
                            # --> 1933-2010
                            start_accuracy_offset = 77
                        else:
                            # ~ 1933-2066
                            start_accuracy_offset = 67

                        start_accuracy = start_century_offset + 100*(int(start_century_m.group('century')) - int(start_century_m.group('other_century')))

                    elif start_century_m.group('turn_of_the_century'):
                        # ~ xx90-xy10
                        start_accuracy = 20

                    elif start_century_m.group('about'):
                        # about 19th century
                        start_accuracy = 150

                    else:
                        start_accuracy = None

                elif start_year_m:
                    if start_year_m.group('decade'):
                        start_year = int(start_year_m.group('year'))+5
                        start_accuracy = 10
                    elif start_year_m.group('about'):
                        start_year = int(start_year_m.group('year'))
                        start_accuracy = 5
                    else:
                        start_year = int(start_year_m.group('year'))
                        start_accuracy = None

                used_ins = []

                usage_in_m = script_usage_in_rgx.match(script_notes)

                if usage_in_m:
                    log(re.split(r',\s*', usage_in_m.group('country_list').replace(', and', ',').replace(' and ', ', ')))
                    clist = [c.strip() for c in re.split(r',\s*', usage_in_m.group('country_list').replace(', and', ',').replace(' and ', ', '))]
                    log(clist)
                    used_ins = UsedIn.objects.filter(
                        Q(country__name__in=clist) |
                        Q(country__alt_names__name__in=clist),
                        language=l)

                if not usage_in_m or not used_ins:
                    used_ins = UsedIn.objects.filter(language=l)

                for ui in used_ins:
                    for script in scripts:
                        try:
                            su = ui.scripts.get(script=script)
                        except ScriptUsage.DoesNotExist:
                            su = ScriptUsage(script=script)

                        if end_year:
                            su.end = datetime(end_year, 1, 1)
                            if end_accuracy:
                                su.end_accuracy = datetime(end_accuracy, 12, 31)

                        if start_year:
                            su.start = datetime(start_year, 1, 1)
                            if start_accuracy:
                                su.start_accuracy = datetime(start_accuracy, 12, 31)

                        if 'primary usage' in script_notes:
                            su.primary = True

                        if any(minor_usage_note in script_notes for minor_usage_note in MINOR_USAGE_PHRASES):
                            su.minor = True

                        if 'no longer in use' in script_notes:
                            su.in_use = False

                        su.save()

                        for style in styles:
                            sus, _ = ScriptUsageStyle.objects.get_or_create(
                                script_usage=su,
                                script_style=style)
                            sus.notes = script_soup
                            sus.save()

                        try:
                            ui.scripts.get(id=su.id)
                        except ScriptUsage.DoesNotExist:
                            ui.scripts.add(su)

        for language, similars in tqdm(lexical_similarities.items(), total=len(lexical_similarities),
                                       desc="Importing lexical similarities from Glottolog..."):
            for sl in similars:
                log('searching for ')
                plog(sl['language'])
                if sl['language']['iso639-3']:
                    try:
                        similar_language = Language.objects.get(iso639_3=sl['language']['iso639-3'].strip())
                    except Language.DoesNotExist:
                        try:
                            similar_language = Language.objects.get(
                                Q(name=sl['language']['name'].strip()) |
                                Q(name_gl=sl['language']['name'].strip()) |
                                Q(iso639_3=sl['language']['iso639-3'].strip()))
                        except Language.DoesNotExist:
                            continue
                        except Language.MultipleObjectsReturned:
                            similar_language = Language.objects.get(
                                Q(name=sl['language']['name'].strip()) |
                                Q(name_gl=sl['language']['name'].strip()),
                                iso639_3=sl['language']['iso639-3'].strip())
                else:
                    try:
                        similar_language = Language.objects.get(
                            Q(name=sl['language']['name'].strip()) |
                            Q(name_gl=sl['language']['name'].strip()))
                    except Language.DoesNotExist:
                        continue
                    except Language.MultipleObjectsReturned:
                        log('Multiple languages found:')
                        plog([model_to_dict(l) for l in Language.objects.filter(
                            Q(name=sl['language']['name'].strip()) |
                            Q(name_gl=sl['language']['name'].strip()))])
                        try:
                            similar_language = Language.objects.get(
                                name=sl['language']['name'].strip())
                        except Language.DoesNotExist:
                            try:
                                similar_language = Language.objects.get(
                                    name_gl=sl['language']['name'].strip())
                            except Language.DoesNotExist:
                                log('Cannot find language:')
                                plog(sl['language'])
                                continue
                            except Language.MultipleObjectsReturned as e:
                                try:
                                    similar_language = Language.objects.get(
                                        name_gl=sl['language']['name'].strip(),
                                        macroarea=sl['other_language'].macroarea)
                                except Language.DoesNotExist:
                                    log('Cannot find language:')
                                    plog(sl['language'])
                                    continue
                                except Language.MultipleObjectsReturned:
                                    log('options:')
                                    plog([model_to_dict(l) for l in Language.objects.filter(
                                        name_gl=sl['language']['name'].strip(),
                                        macroarea=sl['other_language'].macroarea)])
                                    log('information:')
                                    plog(sl['language'])
                                    plog(model_to_dict(sl['other_language']))
                                    #raise e
                                    continue
                        except Language.MultipleObjectsReturned as e:
                            try:
                                similar_language = Language.objects.get(
                                    name=sl['language']['name'].strip(),
                                    macroarea=sl['other_language'].macroarea)
                            except Language.DoesNotExist:
                                log('Cannot find language:')
                                plog(sl['language'])
                                continue
                            except Language.MultipleObjectsReturned:
                                log('options:')
                                plog([model_to_dict(l) for l in Language.objects.filter(
                                    name=sl['language']['name'].strip(),
                                    macroarea=sl['other_language'].macroarea)])
                                log('information:')
                                plog(sl['language'])
                                plog(model_to_dict(sl['other_language']))
                                #raise e
                                continue

                if language == similar_language:
                    continue

                try:
                    # ls = LexicalSimilarity.objects.get(
                    #     Q(language_1=language) | Q(language_2=language),
                    #     Q(language_1=similar_language) | Q(language_2=similar_language))
                    ls = LexicalSimilarity.objects.get(
                        language_1=language,
                        language_2=similar_language)
                except LexicalSimilarity.DoesNotExist:
                    ls = LexicalSimilarity(
                        language_1=language,
                        language_2=similar_language)
                except LexicalSimilarity.MultipleObjectsReturned as e:
                    log('Multiple LexicalSimilarity objects found:')
                    plog([model_to_dict(l) for l in LexicalSimilarity.objects.filter(language_1=language, language_2=similar_language)])
                    raise e

                if sl['percent_low']:
                    ls.percent_low = int(sl['percent_low'])
                    ls.percent_high = int(sl['percent_high'] or sl['percent_low'])
                else:
                    ls.percent_low = None
                    ls.percent_high = None

                ls.save()

        for note, lcodes in note_lcodes.items():
            note.other_languages.add(*list(Language.objects.filter(iso639_3__in=[_.strip() for _ in lcodes])))

    def build_iso_index(self):
        self.logger.info("Building ISO language code index")

        if hasattr(self, 'iso_index') and self.iso_index:
            return

        data = self.get_data('language')

        self.iso_index = {}

        for item in tqdm(data, total=7767,
                         desc="Building index of ISO language codes..."):
            if item['iso639-3'] == "ISO 639-3":
                continue

            name, *alt_names = item['name'].strip().split('; ')

            self.iso_index[item['iso639-3']] = {
                'name': name,
                'iso639-1': item['iso639-1'],
                'iso639-2t': item['iso639-2'] if '/' not in item['iso639-2'] else item['iso639-2'].strip().strip('*').split(' / ')[0],
                'iso639-2b': item['iso639-2'] if '/' not in item['iso639-2'] else item['iso639-2'].strip().strip('*').split(' / ')[1],
                'alt_names': alt_names,
            }

    def import_additional_languages(self):
        en, und = self.create_undetermined_and_english_languages()

        self.build_iso_index()

        data = self.get_data('language')

        self.logger.info("Importing language data")
        for item in tqdm(data, total=len(self.iso_index),
                         desc="Importing additional languages..."):
            if item['iso639-3'] == "ISO 639-3":
                continue

            self.logger.info(item)
            if not self.call_hook('language_pre', item):
                continue

            name, *alt_names = item['name'].strip().split('; ')

            try:
                if item['iso639-3']:
                    l = Language.objects.get(iso639_3=item['iso639-3'].strip())
                else:
                    l = Language.objects.exclude(iso639_1=None).get(
                        Q(iso639_1=item['iso639-1'].strip()) |
                        Q(name=name.strip()))

                if not l.iso639_1 and l.iso639_3 == item['iso639-3']:
                    l.iso639_1 = item['iso639-1'] if item['iso639-1'] else None

                if not l.iso639_3 and l.iso639_1 == item['iso639-1']:
                    l.iso639_3 = item['iso639-3'] if item['iso639-3'] else None

            except Language.DoesNotExist:
                l = Language()
                l.name = name
                l.iso639_1 = item['iso639-1'] if item['iso639-1'] else None
                l.iso639_2t = item['iso639-2'] if item['iso639-2'] else None
                l.iso639_3 = item['iso639-3'] if item['iso639-3'] else None
            except Language.MultipleObjectsReturned as e:
                log('item:')
                plog(item)
                log('name:')
                plog(name)
                log('criteria:\n  (iso639-1: {} | name: {})\n  & iso639-3: {}'.format(
                    item['iso639-1'].strip(),
                    name.strip(),
                    item['iso639-3'].strip()))
                log('options:')
                plog([model_to_dict(l) for l in Language.objects.filter(
                    Q(iso639_1=item['iso639-1'].strip()) |
                    Q(Q(name=name.strip()) &
                      Q(iso639_3=item['iso639-3'].strip())))])
                raise e

            if not self.call_hook('language_post', l, item):
                continue
            l.save()

            for alt_name in alt_names:
                aln = AlternativeName.objects.get_or_create(
                    language=l,
                    name=alt_name,
                    type=AlternativeName.TYPE.name,
                    in_language=en)

    def create_undetermined_and_english_languages(self):
        und_ma, _ = Macroarea.objects.get_or_create(name='Undetermined')

        try:
            und = Language.objects.get(
                family=None,
                name='Undetermined')
        except Language.DoesNotExist:
            und = Language.objects.create(
                glottolog_id=None,
                name='Undetermined',
                name_gl='Undetermined',
                iso639_1='xx',
                iso639_2t='und',
                iso639_2b='und',
                iso639_3='und',
                population=0,
                macroarea=und_ma,
                family=None,
                iso_family=None,
                development_status=Language.DEVELOPMENT_STATUS.unattested,
                notes="Used in situations in which a language or languages must be "
                      "indicated but the language cannot be identified")

        try:
            lf = Family.objects.get(name='Indo-European')
        except Family.DoesNotExist:
            d = {
                'name': 'Indo-European',
                'slug': slugify('Indo-European'),
            }
            if self.call_hook('languagefamily_pre', d):
                lf = Family.objects.create(name=d['name'])
            self.call_hook('languagefamily_post', lf, d)

        en_data = {
            'name': 'English',
            'name_gl': 'Standard English',
            'iso639_1': 'en',
            'iso639_2t': 'eng',
            'iso639_2b': 'eng',
            'iso639_3': 'eng',
            'population': 334800758,
            'macroarea': Macroarea.objects.get(name='Eurasia'),
            'notes': '',
        }

        self.call_hook('language_pre', en_data)
        en = add_language(
            en_data['name'],
            en_data['name_gl'],
            en_data['iso639_1'],
            en_data['iso639_2t'],
            en_data['iso639_2b'],
            en_data['iso639_3'],
            en_data['population'],
            en_data['macroarea'],
            lf,
            None,  # iso_family
            Language.DEVELOPMENT_STATUS.national,
            'De facto national language',
            en_data['notes'])
        en.save()

        add_native_names(en, ['English'])

        return en, und

    def import_language(self):
        self.create_undetermined_and_english_languages()

        self.import_glottolog()

        self.import_iso_language_families_from_wikipedia()

        self.import_iso639_2_language_types_and_scopes_from_wikipedia()

        self.import_languages_from_wikipedia()

        self.import_alternative_language_names()

        self.import_additional_languages()

    def flush(self):
        self.logger.info("Flushing language data")
        for cls in inspect.getmembers(sys.modules['languages.models'],
                                      lambda c: (inspect.isclass(c)
                                                 and issubclass(c, models.Model)
                                                 and c.__modules__ == 'languages.models'
                                                 and not c._meta.abstract)):
            cls.objects.all().delete()
