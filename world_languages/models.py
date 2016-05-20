import re
import regex
import unicodedata
import uuid
from urllib.parse import urlparse

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator, MinValueValidator, MaxValueValidator
from django.db import models
from django.forms.models import model_to_dict
from django.utils.encoding import force_text, python_2_unicode_compatible
from django.utils.functional import allow_lazy
from django.utils.safestring import SafeText, mark_safe
from django.utils.timezone import now
from django.utils.translation import ugettext as _

from model_utils import Choices
from polymorphic.models import PolymorphicModel
from six import text_type

from cities.models import Continent, Country

from .managers import AlternativeNameManager, InUseManager


# TODO: Move regexes and lists of words into their own module
cv_rgx = regex.compile(r'''
    (?(DEFINE)
      (?P<cv>[CV]+)
      (?P<modifiers>[i:/]+)
      (?P<cv_part>(?&cv)(?&modifiers)?(?&cv_paren)*)
      (?P<cv_paren>\((?&cv_part)\))
    )
    (?P<cvs>(?&cv_part)+)
    ''', regex.VERBOSE)
dash_und_rgx = re.compile(r'-+_')  # -> _
glid_rgx = re.compile(r'^[a-z]{4}\d{4}$|^[a-z]\d{2}[a-z]\d{4}$')
iso639_1_rgx = re.compile(r'^[a-z]{2}$')
iso639_3_rgx = re.compile(r'^[a-z]{3}$')
multi_dash_rgx = re.compile(r'-{2,}')
slugify_rgx = re.compile(r"""[^-\w$_.+!*'(),]""", re.UNICODE)
starting_chars_rgx = re.compile(r'^[-._]*')  # Characters not allowed at the beginning of a path
ending_chars_rgx = re.compile(r'[-._]+$')  # Characters not allowed at the end of a path
syllable_pattern_rgx = regex.compile(r'''
    (?(DEFINE)
      (?P<cv>[CV]+)
      (?P<modifiers>[i:/]+)
      (?P<cv_part>(?&cv_paren)*(?&cv)(?&modifiers)?(?&cv_paren)*)
      (?P<cv_paren>\((?&cv_part)\))
    )
    (?P<cvs>(?&cv_part)+)
    ''', regex.VERBOSE)
svo_rgx = regex.compile(r'\b[SVO]{2,3}\b')
to_und_rgx = re.compile(r"(?:[-_]'|'[-_])+")  # -> _
und_dash_rgx = re.compile(r'[-_]+-')  # -> -


# TODO: Tests for this function. It needs them.
def slugify(value):
    value = force_text(value)
    value = unicodedata.normalize('NFKC', value.strip().lower())
    value = re.sub(slugify_rgx, '-', value)
    value = re.sub(to_und_rgx, '_', value)
    value = re.sub(multi_dash_rgx, '-', value)
    value = re.sub(dash_und_rgx, '-', value)
    value = re.sub(und_dash_rgx, '_', value)
    value = re.sub(starting_chars_rgx, '', value)
    value = re.sub(ending_chars_rgx, '', value)
    return mark_safe(value)
slugify = allow_lazy(slugify, text_type, SafeText)


class Macroarea(models.Model):
    name = models.CharField(max_length=255)
    continents = models.ManyToManyField(Continent, related_name='macroarea')


class Family(models.Model):
    """
    Language families of the world
    """
    name = models.CharField(max_length=255, unique=True)
    slug = models.CharField(max_length=255, unique=True)
    glottolog_id = models.CharField(blank=True, max_length=8, null=True, unique=True, validators=[RegexValidator(glid_rgx, "Glottolog IDs must be unique and of the form 'xxxx####' (except for the 'x##x####' one)")])
    parent = models.ForeignKey('self', blank=True, null=True)

    class Meta:
        verbose_name_plural = 'families'

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Language(models.Model):
    """
    Languages of the world
    """
    SCOPE = Choices(
        ('individual',    _("Individual")),
        ('collective',    _("Collection (do not precisely represent an individual language)")),
        ('macrolanguage', _("Macrolanguage")),
        ('local',         _("Local (reserved for local use)")),
        ('special',       _("Special")),
    )
    TYPE = Choices(
        ('',            _("Collective")),
        ('living',      _("Living")),
        ('ancient',     _("Ancient (extinct since ancient times)")),
        ('extinct',     _("Extinct (extinct in recent times)")),
        ('historic',    _("Historic (distinct from their modern form)")),
        ('constructed', _("Constructed (non-natural languages)")),
    )
    DEVELOPMENT_STATUS = Choices(
        (0,  'unattested',           _("Unattested")),
        (1,  'national',             _("1 (National)")),
        (2,  'provincial',           _("2 (Provincial)")),
        (3,  'wider_communication',  _("3 (Wider communication)")),
        (4,  'educational',          _("4 (Educational)")),
        (5,  'developing',           _("5 (Developing)")),
        (6,  'vigorous',             _("6a (Vigorous)")),
        (7,  'threatened',           _("6b (Threatened)")),
        (8,  'shifting',             _("7 (Shifting)")),
        (9,  'moribund',             _("8a (Moribund)")),
        (10, 'nearly_extinct',       _("8b (Nearly extinct)")),
        (11, 'reintroduced',         _("8b (Reintroduced)")),
        (12, 'second_language_only', _("9 (Second language only)")),
        (13, 'dormant',              _("9 (Dormant)")),
        (14, 'extinct',              _("10 (Extinct)")),
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    name_gl = models.CharField(max_length=255)
    slug = models.CharField(max_length=255, unique=True)
    iso639_1 = models.CharField(blank=True, max_length=2, null=True, validators=[RegexValidator(iso639_1_rgx, "ISO 639-1 IDs must be unique and two lowercase letters")])
    iso639_2t = models.CharField(blank=True, max_length=3, null=True, validators=[RegexValidator(iso639_3_rgx, "ISO 639-2T IDs must be unique and three lowercase letters")])
    iso639_2b = models.CharField(blank=True, max_length=3, null=True, validators=[RegexValidator(iso639_3_rgx, "ISO 639-2B IDs must be unique and three lowercase letters")])
    iso639_3 = models.CharField(blank=True, max_length=3, null=True, validators=[RegexValidator(iso639_3_rgx, "ISO 639-3 IDs must be unique")])
    iso639_5 = models.CharField(blank=True, default=None, max_length=3, null=True, validators=[RegexValidator(re.compile(r'[a-z]{3}|'), "ISO 639-5 IDs must be unique and three lowercase letters")])
    iso639_2_type = models.CharField(choices=TYPE, default=TYPE.living, max_length=11, db_column='type')
    iso639_2_scope = models.CharField(choices=SCOPE, default=SCOPE.individual, max_length=13)
    glottolog_id = models.CharField(blank=True, max_length=8, null=True, unique=True, validators=[RegexValidator(glid_rgx, "Glottolog IDs must be unique and of the form 'xxxx####' (except for the 'x##x####' one)")])
    development_status = models.PositiveIntegerField(blank=True, null=True, choices=DEVELOPMENT_STATUS)
    development_status_notes = models.TextField(blank=True, default='', null=True)
    usage_notes = models.TextField(blank=True, default='', null=True)
    family = models.ForeignKey(Family, blank=True, default=None, null=True, related_name='child_languages')
    iso_family = models.ForeignKey('self', blank=True, null=True, related_name='collected_languages')
    macrolanguage = models.ForeignKey('self', blank=True, default=None, null=True, related_name='languages')
    similar_languages = models.ManyToManyField('self', through='LexicalSimilarity', symmetrical=False)
    population = models.PositiveIntegerField(blank=True, null=True)
    macroarea = models.ForeignKey(Macroarea, blank=True, null=True, related_name='languages')
    lexical_similarity_notes = models.TextField(blank=True, default='')
    notes = models.TextField(blank=True, default='')
    used_in = models.ManyToManyField(Country, through='UsedIn', related_name='languages')

    class Meta:
        unique_together = (('glottolog_id', 'family'),)

    def __str__(self):
        return self.name

    def get_abbreviation(self):
        return self.iso639_1

    def set_abbreviation(self, value):
        self.iso639_1 = value

    abbreviation = property(get_abbreviation, set_abbreviation)

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        self.name_gl = self.name_gl.strip()

        if self.iso639_3:
            name = '{} [{}]'.format(self.name, self.iso639_3)
        else:
            name = '{}'.format(self.name)
        if name.startswith("//"):
            name = name.replace("//", 'X{}'.format(name))

        self.slug = slugify(name)
        # print('({}, {}) --> {}'.format(self.name, self.iso639_3, self.slug))
        super().save(*args, **kwargs)


@python_2_unicode_compatible
class AlternativeName(models.Model):
    TYPE = Choices(
        ('name', _("Name")),
        ('abbr', _("Abbreviation")),
    )
    language = models.ForeignKey(Language, related_name='alternative_names')
    name = models.CharField(max_length=255)
    slug = models.CharField(max_length=255, unique=True, validators=[RegexValidator(r'^.+$', "AlternativeName.slug cannot be blank")])
    type = models.CharField(choices=TYPE, max_length=4)
    in_language = models.ForeignKey(Language, blank=True, null=True, related_name='+')
    preferred = models.BooleanField(default=False)
    colloquial = models.BooleanField(default=False)

    objects = AlternativeNameManager()
    all_objects = models.Manager()

    class Meta:
        unique_together = (('language', 'name', 'type', 'in_language'),)

    def __str__(self):
        if self.in_language.iso639_3 != 'und':
            return "{} ({})".format(force_text(self.name), force_text(self.in_language))
        else:
            return self.name

    def slugify(self, *args, **kwargs):
        if not self.in_language:
            self.slug = slugify('{}_(und)'.format(self.name))
        else:
            self.slug = slugify('{}_({})'.format(self.name, self.in_language.iso639_3))

    def save(self, *args, **kwargs):
        self.name = self.name.strip()

        self.slugify()

        super().save(*args, **kwargs)


class UsedIn(models.Model):
    DEVELOPMENT_STATUS = Choices(
        (0,  'unattested',           _("Unattested")),
        (1,  'national',             _("1 (National)")),
        (2,  'provincial',           _("2 (Provincial)")),
        (3,  'wider_communication',  _("3 (Wider communication)")),
        (4,  'educational',          _("4 (Educational)")),
        (5,  'developing',           _("5 (Developing)")),
        (6,  'dispersed',            _("5 (Dispersed)")),
        (7,  'vigorous',             _("6a (Vigorous)")),
        (8,  'threatened',           _("6b (Threatened)")),
        (9,  'shifting',             _("7 (Shifting)")),
        (10,  'moribund',            _("8a (Moribund)")),
        (11, 'nearly_extinct',       _("8b (Nearly extinct)")),
        (12, 'reintroduced',         _("8b (Reintroduced)")),
        (13, 'second_language_only', _("9 (Second language only)")),
        (14, 'dormant',              _("9 (Dormant)")),
        (15, 'extinct',              _("10 (Extinct)")),
    )
    country = models.ForeignKey(Country)
    language = models.ForeignKey(Language)
    known_as = models.ManyToManyField(AlternativeName, related_name='used_in')
    population = models.PositiveIntegerField(null=True)
    scripts = models.ManyToManyField('ScriptUsage', related_name='used_in')
    as_of = models.DateField(default=now)
    development_status = models.PositiveIntegerField(choices=DEVELOPMENT_STATUS)
    development_status_notes = models.TextField(blank=True, default='', null=True)
    usage_notes = models.TextField(blank=True, default='', null=True)

    class Meta:
        unique_together = (('country', 'language'),)


class Dialect(models.Model):
    used_in = models.ForeignKey(UsedIn, related_name='dialects')
    name = models.CharField(max_length=255)
    also_known_as = models.ManyToManyField('self')
    #mixed_with = models.ForeignKey(Language, default=None, null=True)
    notes = models.TextField()

    class Meta:
        unique_together = (('used_in', 'name'),)


class DialectNote(models.Model):
    used_in = models.ForeignKey(UsedIn, related_name='dialect_notes')
    language = models.ForeignKey(Language, blank=True, default=None, null=True, related_name='+')
    note = models.TextField()


class LexicalSimilarity(models.Model):
    language_1 = models.ForeignKey(Language)
    language_2 = models.ForeignKey(Language, related_name='+')
    percent_low = models.PositiveIntegerField(blank=True, null=True, validators=[MaxValueValidator(100), MinValueValidator(0)])
    percent_high = models.PositiveIntegerField(blank=True, null=True, validators=[MaxValueValidator(100), MinValueValidator(0)])
    notes = models.TextField(blank=True, default=None, null=True)

    def save(self, **kwargs):
        if self.percent_low and self.percent_high and self.percent_low > self.percent_high:
            self.percent_low, self.percent_high = self.percent_high, self.percent_low
        super().save(**kwargs)

    def save_without_signals(self, **kwargs):
        """
        Save the model without sending signals so we avoid infinite recursion
        when automatically creating the reflexive similarity relationship
        """
        self._disable_signals = True
        self.save(**{kw: kwargs[kw] for kw in kwargs if kw != 'signal'})
        self._disable_signals = False

    def delete_without_signals(self, **kwargs):
        """
        Delete the model without sending signals so we avoid infinite recursion
        when automatically deleting the reflexive similarity relationship
        """
        self._disable_signals = True
        self.delete(**{kw: kwargs[kw] for k in kwargs if kw != 'signal'})
        self._disable_signals = False


class Characteristic(PolymorphicModel):
    languages = models.ManyToManyField(Language, related_name='characteristics')
    notes = models.CharField(max_length=1023)

    def __str__(self):
        return self.notes


class AbstractWordTypeOrder(models.Model):
    WORD_TYPE = Choices(
        ('adjective',        _("adjective")),
        ('article',          _("article")),
        ('attributive',      _("attributive")),
        ('classifier',       _("classifier")),
        ('demonstrative',    _("demonstrative")),
        ('genitive',         _("genitive")),
        ('modifier',         _("modifier")),
        ('noun',             _("noun")),
        ('noun_class',       _("noun class")),
        ('noun_head',        _("noun head")),
        ('number',           _("number")),
        ('num_cls_cnstr',    _("number classifier construction")),
        ('numeral',          _("numeral")),
        ('personal_pronoun', _("personal pronoun")),
        ('possessive',       _("possessive")),
        ('possessor',        _("possessor")),
        ('poss_noun_phrase', _("possessor noun phrase")),
        ('postposition',     _("postposition")),
        ('preposition',      _("preposition")),
        ('proper_noun',      _("proper noun")),
        ('question_word',    _("question word")),
        ('q_word_phrase',    _("question words phrase")),
        ('relative',         _("relative")),
        ('relative_clause',  _("relative clause")),
    )
    MODIFIER = Choices(
        ('all',       _("all")),
        ('both',      _("both")),
        ('generally', _("generally")),
        ('mostly',    _("mostly")),
        ('normally',  _("normally")),
        ('not',       _("not")),
        ('tend_to',   _("tend to")),
        ('usually',   _("usually")),
    )
    word_type = models.CharField(choices=WORD_TYPE, max_length=16)
    modifier = models.CharField(blank=True, choices=MODIFIER, default=None, max_length=9, null=True)
    position = models.CharField(max_length=18)

    class Meta:
        abstract = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._meta.get_field('position').choices = getattr(self, 'POSITION')


class AbsoluteWordTypeOrder(AbstractWordTypeOrder, Characteristic):
    POSITION = Choices(
        ('final',              _("final")),
        ('initial',            _("initial")),
        ('initial_and_final',  _("initial and final")),
        ('initial_or_final',   _("initial or final")),
    )


class RelativeWordTypeOrder(AbstractWordTypeOrder, Characteristic):
    POSITION = Choices(
        ('after',              _("after")),
        ('after_or_without',   _("after or without")),
        ('before',             _("before")),
        ('before_and_after',   _("before and after")),
        ('before_or_after',    _("before or after")),
        ('before_and_without', _("before and without")),
        ('before_or_without',  _("before or without")),
        ('follow',             _("follow")),
        ('precedes',           _("precedes")),
    )
    related_word_type = models.CharField(choices=AbstractWordTypeOrder.WORD_TYPE, max_length=16)


class SpeechSoundCount(Characteristic):
    MODIFIER = Choices(
        ('basic',  _("Basic")),  # Basic vowel
        ('long',   _("Long")),  # Long vowel
        ('short',  _("Short")),  # Short vowel
        ('simple', _("Simple")),  # Simple vowel
        ('unique', _("Unique")),  # Unique consonant
    )
    TYPE = Choices(
        ('consonant',         _("Consonant")),
        ('consonant_phoneme', _("Consonant Phoneme")),
        ('diphthong',         _("Diphthong")),
        ('monophthong',       _("Monophthong")),
        ('quality',           _("Quality")),
        ('vowel',             _("Vowel")),
        ('vowel_phoneme',     _("Vowel Phoneme")),
    )
    number = models.IntegerField()
    modifier = models.CharField(choices=MODIFIER, max_length=6)
    type = models.CharField(choices=TYPE, max_length=17)


class SubjectVerbObjectOrder(Characteristic):
    ORDER = Choices(
        ('SV',  _("Subject-Verb")),
        ('VO',  _("Verb-Object")),
        ('VS',  _("Verb-Subject")),
        ('VV',  _("Verb-Verb")),
        ('OSV', _("Object-Subject-Verb")),
        ('OVS', _("Object-Verb-Subject")),
        ('SOV', _("Subject-Object-Verb")),
        ('SVO', _("Subject-Verb-Object")),
        ('VOS', _("Verb-Object-Subject")),
        ('VSO', _("Verb-Subject-Object")),
    )
    order = models.CharField(choices=ORDER, max_length=3)

    @property
    def regex(self):
        return regex.compile(r'\b{}\b'.format(self.order))

    def __str__(self):
        return self.order

    def save(self, *args, **kwargs):
        if not svo_rgx.fullmatch(self.order):
            raise ValidationError("Cannot save SubjectVerbOrder: '{}' is not a valid order".format(self.order))
        super().save(*args, **kwargs)


class SyllablePattern(Characteristic):
    pattern = models.CharField(max_length=31)

    @property
    def regex(self):
        return regex.compile(r'\b{}\b'.format(self.pattern.replace('(', '\\(').replace(')', '\\)')))

    def __str__(self):
        return self.pattern

    def save(self, *args, **kwargs):
        if not syllable_pattern_rgx.fullmatch(self.pattern):
            raise ValidationError("Cannot save SyllablePattern: '{}' is not a valid syllable pattern".format(self.pattern))
        super().save(*args, **kwargs)


class Script(models.Model):
    TYPE = Choices(
        ('abjad',           'Abjad'),  # Only consonants (not vowels) have graphemes
        ('abugida',         'Abugida'),  # Each grapheme is consonant with secondary vowel notation
        ('alphabet',        'Alphabet'),  # Consonants and vowels have graphemes
        ('featural',        'Featural'),  # Shapes of graphemes encode phonological features of the phonemes they represent (eg: "a" with a diacritic "accent" mark)
        ('semisyllabary',   'Semi-syllabary'),  # Between an alphabet and a syllabary; each grapheme represents either a syllable or a phoneme
        ('syllabary',       'Syllabary'),  # Each grapheme represents a syllable, graphemes cannot be split into separate consonants and vowels
        ('logographic',     'Logographic'),  # Each grapheme represents a word or phrase
        ('semantophonetic', 'Semanto-phonetic'),  # Each grapheme is a syllable or an ideogram
        ('pictographic',    'Pictographic'),  # Ideogram that conveys meaning due to resemblance to a physical object
        ('ideogram',        'Ideogram'),  # Each grapheme represents an idea or concept, and specific words or phrases (eg: "No" ideogram part of the "No smoking" sign)
        ('numeral',         'Numeral'),  # Express mathematical numbers
        ('other',           'Other'),  # Braille, Signal Flags, Morse, SignWriting
    )
    name = models.CharField(max_length=255)
    parent = models.ForeignKey('self', blank=True, default=None, null=True, related_name='variants')
    type = models.CharField(blank=True, choices=TYPE, default=None, max_length=15, null=True)

    def __str__(self):
        if self.parent_script:
            return '{}/{}'.format(self.parent_script, self.name)
        else:
            return self.name


class AlternativeScriptName(models.Model):
    TYPE = Choices(
        ('name', _("Name")),
        ('abbr', _("Abbreviation")),
        ('link', _("Link")),
    )
    script = models.ForeignKey(Script, related_name='alternative_names')
    name = models.CharField(max_length=255)
    type = models.CharField(choices=TYPE, default=TYPE.name, max_length=4)


class ScriptStyle(models.Model):
    script = models.ForeignKey(Script)
    name = models.CharField(max_length=255)

    def __str__(self):
        return '{} ({})'.format(self.script.name, self.name)


class ScriptUsage(models.Model):
    script = models.ForeignKey(Script, related_name='usages')
    script_styles = models.ManyToManyField(ScriptStyle, through='ScriptUsageStyle', related_name='usages')
    start = models.DateField(blank=True, default=None, null=True)
    start_accuracy = models.DateField(blank=True, default=None, null=True)
    end = models.DateField(blank=True, default=None, null=True)
    end_accuracy = models.DateField(blank=True, default=None, null=True)
    primary = models.BooleanField(default=False)
    minor = models.BooleanField(default=False)
    in_use = models.BooleanField(default=True)
    notes = models.TextField()

    objects = InUseManager()


class ScriptUsageStyle(models.Model):
    script_usage = models.ForeignKey(ScriptUsage)
    script_style = models.ForeignKey(ScriptStyle)
    notes = models.TextField(default='')


class DevelopmentNote(models.Model):
    language = models.ForeignKey(Language, related_name='development_notes')
    ordinal = models.IntegerField('L1, L2, L3, etc.', default=None, null=True)
    other_languages = models.ManyToManyField(Language, related_name='+')
    note = models.TextField()

    class Meta:
        unique_together = (('language', 'note'),)


OKAY_TAG_NAMES = (
    'Dictionary',
    'Films',
    'Grammar',
    'Increasing',
    'Magazines',
    'Newspapers',
    'New media',
    'Poetry',
    'Pre-school',
    'Radio programs',
    'TV',
    'Videos'
)


def validate_development_note_tag(value):
    if value.capitalize() not in OKAY_TAG_NAMES:
        raise ValidationError(_("%(value)s is not an allowed development tag"), params={'value': value})


class DevelopmentNoteTag(DevelopmentNote):
    name = models.CharField(max_length=255, validators=[validate_development_note_tag])


class DevelopmentNoteBible(DevelopmentNote):
    PART_TYPE = Choices(
        ('all',   _("Complete")),
        ('part',  _("Portions")),
        ('old',   _("Old Testament")),
        ('new',   _("New Testament")),
    )
    part = models.CharField(choices=PART_TYPE, default=PART_TYPE.all, max_length=4)
    start = models.DateField(null=True, default=None)
    end = models.DateField(null=True, default=None)


class DevelopmentNoteLiteracy(DevelopmentNote):
    LITERACY_TYPE = Choices(
        ('read',  _("Read")),
        ('write', _("Write")),
    )
    type = models.CharField(choices=LITERACY_TYPE, max_length=5)
    low = models.IntegerField()
    high = models.IntegerField()


OKAY_LITERACY_TAG_NAMES = (
    'High',
    'Medium',
    'Moderate',
    'Some',
    'Few',
    'Low',
    'Fairly low',
    'Very low',
    'Extremely low',
    'Almost none',
    'Virtually none',
    'None',
)


def validate_development_note_literacy_tag(value):
    if value.capitalize() not in OKAY_LITERACY_TAG_NAMES:
        raise ValidationError(_("%(value)s is not an allowed development literacy tag"), params={'value': value})


class DevelopmentNoteLiteracyTag(DevelopmentNote):
    name = models.CharField(max_length=255, validators=[validate_development_note_literacy_tag])


class DevelopmentNoteLiteracyPercent(DevelopmentNote):
    low = models.PositiveIntegerField(validators=[MinValueValidator(0), MaxValueValidator(100)])
    high = models.PositiveIntegerField(validators=[MinValueValidator(0), MaxValueValidator(100)])
