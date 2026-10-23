# Multilingual questionnaires and reports

Date: 2026-10-19
Status: planned, implementation starting (#24)

## Goal

A reviewer answers in their own language, and everyone reads a report in
their own language. The same report can be shown in English and in German
without being regenerated, and an answer given in German counts exactly like
the same answer given in English. The interface and the emails follow the same
language settings.

This document describes the data model and the migration approach. The
implementation follows the order in Part 6. Where it shows that part of the
plan does not work as described, we will change the plan and point out the
change in the PR concerned.

Out of scope: machine translation, translating free-text answers, right-to-left
languages, and the landing site (it has its own settings module and no
database).

## Fixed requirements

- **Every PR applies automatically on every existing install**, whatever state
  its database is in. No primary keys in fixtures or migrations. References are
  resolved when the migration or upgrade step runs.
- **Store IDs and numbers, not displayed text.** Weights, scale values and
  Dreyfus mappings are stored once, and only text is translated.
- **Anonymity does not change.** Reports never show which language an answer
  was given in, and no new field ties a language to a response.
- **Organization isolation does not change.** Every new tenant-scoped model
  hangs off an existing tenant-scoped parent and is reached through it.

## Why the current model cannot be translated

Today an option of a likert or choice question *is* its label:

- The feedback form posts the label (`value="{{ choice }}"`), and
  `Response.answer_data` stores it, e.g. `{"value": "Agree"}`.
- `generate_report` counts answers by label and finds weights with
  `choices.index(response_text)`. An answer whose label was reworded or
  translated silently drops out of the score.
- The likert sentiment in `_question_response.html` looks up the literal keys
  `"Strongly Agree"` and `"Agree"`.
- `report_data` freezes question text, section titles, the full `config` and
  English prose (trend labels, perception gaps, sentiment ratings, Dreyfus
  stage texts, development plan) at generation time.
- Section summaries, peer benchmarks and cycle-over-cycle trends are keyed by
  the section title.
- `edit_question` rebuilds `Question.config` from scratch on every save, so
  anything stored in it besides what the form posts is lost. Rating labels are
  set when a question is created and cannot be edited afterwards.

Translating the labels in place would therefore change the stored answers,
break scoring and split every distribution by language.

## Design decisions

| Decision | Choice |
|---|---|
| Answer options | Own model `AnswerOption` with a stable `value` (slug), `label` in the source language, `weight` and `order`. Responses store `value`. |
| Other text in `config` | Rating and scale labels move to `Question.labels`, in the source language. Action items get a stable key. `config` keeps numbers only. |
| Translation storage | One translation table per translated model, text fields only, unique per (parent, language). No copy of `config` per language. |
| Source language | `Questionnaire.source_language`. The existing text fields hold that language. |
| Language codes | `CharField(max_length=10)` without `choices`, validated against `settings.LANGUAGES` in forms and serializers, so the language list is never frozen into a migration. |
| Report data | Numbers, codes and references. Text is resolved at display time in the viewer's language. A source-language snapshot stays in `report_data` as a fallback for deleted questions. |
| Report wording after edits | A report shows the current wording of its questionnaire. Rewording a question changes old reports, as translating it does. The editor warns when a questionnaire already has reports. |
| Reviewer language | Browser language by default. An explicit language per reviewer, reviewee and organization overrides it, and is known before the first email is sent. |
| Missing translations | Each missing string falls back to the source language, in the form and in reports. The editor shows what is missing. |
| Reviewee's name | Question texts use a `{name}` placeholder instead of "This person". |
| Data conversion | Schema migrations only add tables and fields with defaults. Converting existing data runs as idempotent steps in `core/upgrade_steps.py`. |
| UI strings | Standard gettext (`{% trans %}`, `.po` files), independent of all of the above. |

## Part 1: Data model

### Answer options

```python
class AnswerOption(TimeStampedModel):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='options')
    order = models.PositiveIntegerField()
    value = models.SlugField(max_length=64)   # stable, unique per question
    label = models.CharField(max_length=255)  # source language
    weight = models.FloatField(null=True, blank=True)
    # unique (question, order) and (question, value)
```

- Used by `likert`, `single_choice` and `multiple_choice`. `rating` and
  `scale` keep storing numbers, which are already stable.
- `value` is derived once from the source label (`slugify`) and never changes
  afterwards, even when the label is reworded. Template questionnaires and
  their clones get the same values, so answers to questionnaires cloned from
  the same template stay comparable.
- `config['scale']`, `config['choices']` and `config['weights']` move into the
  options. `config` keeps the numeric settings only: `min`, `max`, `step`,
  `scoring_enabled`, `chart_weight`, `exclude_from_charts` and
  `dreyfus_mapping`.
- During the transition the editor keeps writing `config`, and a `post_save`
  signal derives the options from it. It matches options by label first, so a
  moved option keeps its value, and pairs the rest by position, so a reworded
  label keeps its value too. Once the editor writes options directly, the
  signal goes away.

### Labels and action items

- `Question.labels` (new `JSONField`) holds the rating and scale labels in the
  source language: `{"1": "…", "5": "…"}` for rating, `{"min": "…", "max": "…"}`
  for scale. They move there from `config['labels']`, `config['min_label']`
  and `config['max_label']`.
- Action items get a stable `key` inside `Question.action_items`, so a
  translation can refer to them.

### Translations

```python
class QuestionnaireTranslation(TimeStampedModel):   # name, description
class QuestionSectionTranslation(TimeStampedModel): # title, description
class QuestionTranslation(TimeStampedModel):        # question_text, labels, action_items
class AnswerOptionTranslation(TimeStampedModel):    # label
```

- Each has an FK to its parent (`related_name='translations'`), `language`
  and `source_checksum`, and is unique per (parent, language).
- `QuestionTranslation.labels` is keyed like `Question.labels`. Keys that the
  source does not have are rejected. `QuestionTranslation.action_items` maps
  action item key to text.
- `source_checksum` is a hash of the source text at the time of translation.
  When the source text changes, the translation counts as outdated: it is
  still shown, and the editor lists it as needing review.
- Cloning a questionnaire for a new organization copies its translations.

`Questionnaire.source_language` defaults to `settings.LANGUAGE_CODE`.
Installs whose questionnaires are written in another language change it once
in the editor; nothing is translated automatically.

### Languages of people

| Field | Purpose |
|---|---|
| `Organization.default_language` | Fallback for every email and form of the organization. Set in the settings page, or by `ORGANIZATION_LANGUAGE`, which then owns the field like the other entries in `ENV_MANAGED_FIELDS`. |
| `Reviewee.language` (blank) | Emails to the reviewee and their self-assessment. |
| `ReviewerToken.language` (blank) | Invitations and reminders to that reviewer, and the form. |
| `UserProfile.language` (blank) | Dashboard and team emails. Optional, the browser decides otherwise. |

A blank field means "use the next fallback". Forms preselect the effective
language, so an admin sees which language an email goes out in. Copying the
organization default into every row instead would keep the browser language
from ever applying.

None of these are shown in reports.

## Part 2: Reviewer flow and emails

**Language of the feedback form**, first match wins:

1. The reviewer's choice in the language switcher on the form. The maintainer
   asked for a small dropdown in a corner of the screen.
2. `ReviewerToken.language`.
3. The browser (`Accept-Language`, through `LocaleMiddleware`).
4. `Organization.default_language`.

Questionnaire text that is not translated into that language is shown in the
source language, string by string.

When the token has no language yet, the language the form was shown in is
stored on it, and the switcher updates it. Later reminders then go out in that
language. Admins can set it beforehand on the invitations page, next to the
reviewer's email.

**Emails** render under `translation.override(lang)`. Subjects go through
`gettext`, and templates use `{% trans %}`/`{% blocktrans %}` within the
existing table-based markup.

| Recipient | Emails | Language |
|---|---|---|
| Reviewer | invitation, reminder | `ReviewerToken.language`, then the organization default |
| Reviewee | self-assessment, invitation links, close check, report ready | `Reviewee.language`, then the organization default |
| Invited team member | invitation | The organization default (there is no profile yet) |
| Team member | welcome, password reset | `UserProfile.language`, then the organization default |

`send_individual_reminder` currently builds its email directly with
`EmailMultiAlternatives`; it moves to the shared reminder function, so there is
one place that picks the language.

**The reviewee's name.** Question texts refer to the reviewee as "This
person". The API replaces that phrase with the reviewee's first name, the form
shows it as is. In German the phrase changes with its grammatical case
(*diese Person*, *dieser Person*), so replacing a translated phrase does not
work. Question texts and their translations get a `{name}` placeholder
instead, which the form, the API and the report resolve to the reviewee's
first name.

## Part 3: Reports

`generate_report` stops writing text and writes references, numbers and codes:

- Sections and questions by id, with the source-language text as a fallback
  for questions that were deleted since (`Response.question` cascades, so
  their answers go with them, but older reports may still mention them).
- Distributions keyed by option value. The likert sentiment uses the top two
  options by order instead of the English labels.
- Insights as codes plus numbers, e.g. `{"trend": "improving", "delta": 0.4}`
  or `{"gap": "self_higher", "delta": 0.8}`. The templates turn them into
  sentences with gettext.
- Dreyfus and agency stages by key (`novice` … `expert`). The CSS selectors
  that currently match the English stage name move to the key.

Display resolves every reference in the viewer's language (`LANGUAGE_CODE` of
the request) and falls back to the source text per string. A switcher on the
report page shows the other available languages. The PDF/print view uses the
same path.

Benchmarks and trends keep matching sections by their source-language title,
as today, so comparisons across cycles and clones behave as before.

`report_data` gets a `"schema": 2` marker. Reports without it are rendered
exactly as today, in English. They are not regenerated automatically, because
regenerating a closed cycle would pick up questionnaire edits made since.

## Part 4: Questionnaire editor

- Options of likert and choice questions are edited as rows (label, weight)
  instead of a text area with one option per line, so each row keeps its value
  and its translations.
- Rating labels become editable.
- A "Translate into" selector on the questionnaire page switches to a
  side-by-side view: source text on the left, translation on the right, for
  every translatable string (name, description, sections, questions, options,
  rating/scale labels, action items).
- A counter per language shows how many strings are missing or outdated, both
  in the editor and in the questionnaire list.
- Translations are saved per string, so a half-finished translation can be
  stored. Strings that are still missing fall back to the source text.
- The preview is available in every language.
- Weights, scale values and Dreyfus mappings are edited in the source view
  only.

## Part 5: API, export and import

- `QuestionSerializer` gains `options` (`[{"value", "label"}]`) and `labels`.
  `config` keeps its current keys, derived from the options and labels in the
  source language, so existing clients keep working. `?lang=de` returns
  translated text.
- Submitting answers accepts option values. Labels in the source language are
  still accepted and mapped to their value, for clients written against the
  current API.
- Export and import include options and translations. Answer values are slugs,
  not ids, so they stay valid on another install.
- Webhooks carry no question or answer text and are unaffected.

## Part 6: Migration approach

The implementation is split into six PRs so each one can be reviewed on its
own. They belong together and are meant to land as a whole. Each one applies
automatically on boot, so an install is never broken between two steps.

| PR | Schema migration | Upgrade step (idempotent) | Visible change |
|---|---|---|---|
| 1. UI localisation | none | none | Dashboard, form and emails in English or German via gettext, with a language switcher. Builds the `.mo` files in the image (`compilemessages`). |
| 2. Languages of people | four language fields | none | The form remembers the reviewer's language, emails go out in the recipient's language, `ORGANIZATION_LANGUAGE`. |
| 3. Answer options and labels | `AnswerOption` table, `Question.labels` | Derive options from `config` for every question. Rewrite `answer_data` from label to value in one transaction. Answers that match no option are kept under `unmapped` and counted in the report instead of being dropped. Likert answers stored as 1-based numbers (demo data, API clients) map by position. Move rating and scale labels to `Question.labels`. Backfill action item keys. | None for users, apart from the likert sentiment no longer depending on English labels. |
| 4. Report data | none | none. Old reports keep `schema` 1 and render as before. | Insights and stage texts translatable. |
| 5. Translations and editor | translation tables, `source_language` | none | Option rows, editable rating labels, side-by-side editor and counter, `{name}` placeholder. |
| 6. Shipped translations | `Questionnaire.template_key` | Set `template_key` on templates and their clones (by template name, once). Replace "This person" with `{name}` in questions whose text still matches the template. Add the shipped German translations to every questionnaire with that key, matching questions by their source text. Questions whose text was edited are skipped, so they never get a wrong translation. | Built-in questionnaires available in German. |

Shipped translations live in files keyed by template key and English source
text, never by primary key. The current fixtures reuse primary keys across
files (`professional_skills` and `simple` both use questionnaire pk 1), so
nothing new should depend on them.

Each PR is tested by creating an install on the current `master` through the
setup pages, filling it with demo data and upgrading it to the branch, on
SQLite and PostgreSQL.

## Relation to #23

#23 and the `interface-localisation` branch take a different approach, so this
design does not build on them:

- #23 stores the translated label as the answer and keeps a full copy of
  `config` per language. That makes weights and Dreyfus mappings per-language
  and splits distributions. Here, options carry stable values and
  translations carry text only.
- #23 overlays live translations on the text stored in `report_data`. Here,
  `report_data` holds no text to overlay.
- The `interface-localisation` branch identifies options by source text and
  list position, and freezes reports in one language.

Some ideas coincide: #23 also puts a language on the reviewer token (here it
is known before the first email and backed by an organization default), and
the `interface-localisation` branch also has a source language, a side-by-side
translation workspace and a completeness counter.

The `.po` catalogues in #23 (de, es, fr, it, ja, pt, zh_Hans) could be reused
to add more languages once PR 1 has marked the interface strings.

## Open questions

1. What should `{name}` show in the self-assessment, where the reviewee reads
   their own name?
2. PR 1 ships English and German. Should further languages be listed in
   `LANGUAGES` only once their catalogue covers every string?
3. Should `config['choices']`/`config['scale']` stay in API responses for good,
   or be deprecated once clients use `options`?
