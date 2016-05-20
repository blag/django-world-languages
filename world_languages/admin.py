from django.contrib import admin

from .models import (Family, Language, AlternativeName, UsedIn, Dialect,
                     LexicalSimilarity, Macroarea, Characteristic,
                     ScriptUsage, Script)


class FamilyAdmin(admin.ModelAdmin):
    pass


class LanguageAdmin(admin.ModelAdmin):
    pass


class AlternativeNameAdmin(admin.ModelAdmin):
    ordering = ['name']
    list_display = ['name', 'language', 'preferred']
    list_filter = ['preferred', 'language']
    search_fields = ['name']


class MacroareaAdmin(admin.ModelAdmin):
    pass


class UsedInAdmin(admin.ModelAdmin):
    pass


class DialectAdmin(admin.ModelAdmin):
    pass


class LexicalSimilarityAdmin(admin.ModelAdmin):
    pass


class ScriptUsageAdmin(admin.ModelAdmin):
    pass


class ScriptAdmin(admin.ModelAdmin):
    pass


admin.site.register(Family, FamilyAdmin)
admin.site.register(Language, LanguageAdmin)
admin.site.register(AlternativeName, AlternativeNameAdmin)
admin.site.register(Macroarea, MacroareaAdmin)
admin.site.register(UsedIn, UsedInAdmin)
admin.site.register(Dialect, DialectAdmin)
admin.site.register(LexicalSimilarity, LexicalSimilarityAdmin)
admin.site.register(ScriptUsage, ScriptUsageAdmin)
admin.site.register(Script, ScriptAdmin)
