from django.contrib import admin
from .models import Questionnaire, QuestionSection, Question


class QuestionInline(admin.TabularInline):
    model = Question
    extra = 1
    fields = ['question_text', 'question_type', 'config', 'required', 'order']


class QuestionSectionInline(admin.StackedInline):
    model = QuestionSection
    extra = 1
    fields = ['title', 'description', 'order']


@admin.register(Questionnaire)
class QuestionnaireAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_default', 'is_active', 'created_at']
    list_filter = ['is_default', 'is_active', 'created_at']
    search_fields = ['name', 'description']
    inlines = [QuestionSectionInline]


@admin.register(QuestionSection)
class QuestionSectionAdmin(admin.ModelAdmin):
    list_display = ['title', 'questionnaire', 'order', 'created_at']
    list_filter = ['questionnaire', 'created_at']
    search_fields = ['title', 'description']
    list_select_related = ['questionnaire']
    inlines = [QuestionInline]


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ['question_text_short', 'section', 'question_type', 'required', 'order']
    list_filter = ['question_type', 'required', 'section__questionnaire']
    search_fields = ['question_text']
    list_select_related = ['section', 'section__questionnaire']

    def question_text_short(self, obj):
        return obj.question_text[:60] + '...' if len(obj.question_text) > 60 else obj.question_text
    question_text_short.short_description = 'Question'
