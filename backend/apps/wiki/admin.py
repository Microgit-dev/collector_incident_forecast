from django import forms
from django.contrib import admin

from apps.accounts.roles import ROLES

from .models import WikiPage, WikiSection

MARKDOWN_HELP = (
    "Markdown: # Заголовок, ## Подзаголовок, **жирный**, *курсив*, - список, 1. нумерованный, "
    "[ссылка](/incidents), таблицы | a | b |, > примечание. HTML не выполняется."
)


class WikiPageForm(forms.ModelForm):
    roles = forms.MultipleChoiceField(
        label="Для ролей",
        choices=[(role.value, spec.title) for role, spec in ROLES.items()],
        widget=forms.CheckboxSelectMultiple,
        required=False,
        help_text="Ничего не отмечено — статья видна всем.",
    )

    class Meta:
        model = WikiPage
        fields = ("section", "title", "slug", "summary", "roles", "order", "is_published", "body")
        widgets = {
            "body": forms.Textarea(attrs={"rows": 32, "style": "width: 100%; font-family: monospace"}),
            "summary": forms.TextInput(attrs={"style": "width: 100%"}),
        }
        help_texts = {"body": MARKDOWN_HELP}


class WikiPageInline(admin.TabularInline):
    model = WikiPage
    fields = ("title", "slug", "order", "is_published")
    extra = 0
    show_change_link = True


@admin.register(WikiSection)
class WikiSectionAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "order")
    list_editable = ("order",)
    prepopulated_fields = {"slug": ("title",)}
    inlines = [WikiPageInline]


@admin.register(WikiPage)
class WikiPageAdmin(admin.ModelAdmin):
    form = WikiPageForm
    list_display = ("title", "section", "audience", "order", "is_published", "updated_at", "updated_by")
    list_editable = ("order", "is_published")
    list_filter = ("section", "is_published")
    search_fields = ("title", "summary", "body")
    prepopulated_fields = {"slug": ("title",)}
    readonly_fields = ("updated_at", "updated_by")

    @admin.display(description="для ролей")
    def audience(self, obj):
        return ", ".join(ROLES[r].title for r in obj.roles if r in ROLES) or "все"

    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)
