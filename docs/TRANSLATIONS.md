# Translations

Blik's interface is translated with Django's gettext tools. This guide covers where the
translations live, how to update the catalogues, how to mark texts, and the conventions for German.

## What is translated where

| Texts | Translations |
|---|---|
| Templates, Python code, emails | `locale/<locale>/LC_MESSAGES/django.po` |
| JavaScript in `static/js/` | `locale/<locale>/LC_MESSAGES/djangojs.po` |
| The questionnaires Blik ships | `locale/<locale>/LC_MESSAGES/questionnaires.po`, taken from `questionnaires/fixtures/` (see `questionnaires/shipped.py`) |
| Questionnaires an organization writes or edits | Translation tables in the database, edited with *Translate* in the questionnaire editor |

Reports store codes and numbers. `reports/report_texts.py` adds the texts in the reader's
language when a report is shown. Emails are rendered in the recipient's language
(`core/languages.py`). The landing site is not (yet) translated.

## Updating the catalogues

1. Mark the texts in code and templates (see below).
2. Update the catalogues:

   ```bash
   docker compose exec web python manage.py update_translations
   ```

   This runs `makemessages` for every domain and every language in `LANGUAGES` except English,
   the source language. It writes no source locations, obsolete entries or line wrapping, so the
   diff shows only the texts that changed.
3. Translate the new empty entries. Check entries marked `#, fuzzy`: gettext guessed them from a
   similar text and ignores them until the mark is gone. Correct the text and remove the mark, or
   empty the entry.
4. Compile. The container compiles the catalogues on every start. To see a change without a
   restart, or before running the tests, run
   `docker compose exec web python manage.py compilemessages`. The test container has no gettext
   and uses the `.mo` files in the checkout.

Don't add entries to a catalogue by hand. Hand-written entries easily miss texts, keep texts the
code no longer uses, and lack flags such as `python-format`. The next `update_translations` run
also moves them, so branches that touched the same catalogue conflict.

## Marking texts

### Templates

```django
{% load i18n %}
<h1>{% trans 'Review Cycles' %}</h1>
{% blocktrans trimmed with name=cycle.reviewee.name %}
    Feedback for <strong>{{ name }}</strong>
{% endblocktrans %}
```

- Always use `blocktrans trimmed`, and keep each sentence in one text instead of joining pieces
  in the template.
- Markup stays inside the text (`<a>`, `<strong>`). Only values such as names, URLs and ids become
  variables (`with url=…`). Never pass markup fragments in as variables.
- Easy to miss: `{% block title %}`, attributes (`placeholder`, `title`, `alt`, `aria-label`) and
  `confirm('…')`.

### Python

- `gettext` in views and services, `gettext_lazy` for texts defined at import time (models, forms,
  choices). `_` is always the gettext alias, so don't use it as a throwaway variable.
- Use named placeholders, so that a translation can reorder them:
  `_('Feedback for %(name)s') % {'name': name}`. Counts need `ngettext`.
- Values that are not text (code examples, JSON) stay out of the message. Insert them into lazy
  texts with `format_lazy`.
- Use `pgettext` or a `# Translators:` comment when an English word is ambiguous.

### JavaScript

- Files in `static/js/` use `gettext()`, `ngettext()` and `interpolate()` from the JavaScript
  catalogue (`/i18n/js/`, domain `djangojs`).
- Inline scripts in templates take their texts from the template:
  `{% blocktrans trimmed asvar message with url='%(url)s' %}…{% endblocktrans %}`, then
  `'{{ message|escapejs }}'.replace('%(url)s', url)` in the script.

## German: Sie and du

`de` addresses the reader with *Sie*, `de-informal` with *du*. The catalogue of the variant,
`locale/de_Informal/`, only holds the texts that address the reader. For every other text it falls
back to `de` (`core/languages.py`).

- In the interface, where space is short, write without addressing the reader, in the infinitive
  or passive: "Alle Pflichtfragen beantworten", "Feedback absenden". Such a text needs no entry in
  `de_Informal`.
- Emails speak to one person, so they address the reader. Subjects, headings and running text say
  *Sie* or *du*: "Ihr Bericht ist fertig", "Bitte ändern Sie dieses Passwort nach Ihrer ersten
  Anmeldung." Only buttons and the steps of a checklist stay short and impersonal: "Bericht
  öffnen". Keep a sentence impersonal where *Sie* could also mean "they": "Jeder Link lässt sich
  mit mehreren Personen teilen. Feedbackgebende bleiben anonym."
- A text that addresses the reader gets both forms:

  | `de` | `de_Informal` |
  |---|---|
  | Ihr Bericht ist fertig. | Dein Bericht ist fertig. |
  | Bitte beantworten Sie alle Pflichtfragen, bevor Sie fortfahren. | Bitte beantworte alle Pflichtfragen, bevor du fortfährst. |

- One exception: Django's own catalogue for `de` comes before ours, so a text that Django
  translates as well ("Email", "Created") shows Django's wording in `de-informal`. Copy such texts
  unchanged from `de` into `de_Informal`. `core/test_languages.py` fails and names them.
- `update_translations` may add guesses marked `#, fuzzy` to `de_Informal`. Empty them unless the
  text addresses the reader.

## German terms

German texts are gender-neutral. A form without a gender sign comes first, in labels too ("Die
eingeladene Person erhält …", "Feedbacknehmende Person hinzufügen"). Where there is none, use a
colon: "Benutzer:innen", "Kolleg:innen".

Use the same term throughout:

| English | German | Notes |
|---|---|---|
| Review cycle, cycle | Feedbackrunde | |
| Test cycle (on yourself) | Proberunde | not "Testrunde", which reads like part of the trial |
| Trial | Testphase | |
| Review (what a reviewer gives) | Feedback | neuter, plural Feedbacks |
| Reviewee | feedbacknehmende Person | plural Feedbacknehmende |
| Reviewer | feedbackgebende Person | plural Feedbackgebende |
| Department | Bereich | |
| Questionnaire | Fragebogen | |
| Report | Bericht | |
| Self-assessment, self | Selbsteinschätzung, Selbst | |
| Peer | Kolleg:in | plural Kolleg:innen |
| Manager | Führungskraft | |
| Direct report | direkte Mitarbeitende | plural only; as a label "Direkte Mitarbeitende" |
| Others' average | Durchschnitt der anderen | |
| User | Benutzer:in | |
| Team member | Teammitglied | |
| Organization | Organisation | |
| Admin, organization admin | Admin, Organisations-Admin | |
| Invitation, invite link | Einladung, Einladungslink | |
| Access token | Zugangstoken | |
| Perception gap | Wahrnehmungslücke | |
| Blind spot | Blinder Fleck | |
| Strengths, development areas | Stärken, Entwicklungsfelder | |
| Skill level | Kompetenzstufe | |
| Agency | Eigeninitiative | the second Dreyfus dimension next to skill |
| Dreyfus stages | Neuling, Fortgeschrittene:r Anfänger:in, Kompetent, Gewandt, Expert:in | Novice, Advanced Beginner, Competent, Proficient, Expert |
| Anonymity threshold | Mindestanzahl für Anonymität | |
| GDPR | DSGVO | |
| Settings | Einstellungen | |
| Dashboard | Dashboard | |

## Adding a language

Add the language to `LANGUAGES` in `blik/settings.py` and run `update_translations`, which creates
its catalogues. Then translate `django.po` and `djangojs.po`, and `questionnaires.po` for the
shipped questionnaires.
