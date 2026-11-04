"""
Content for the "How Blik works, start to finish" pages.

The HR page (how_it_works_hr.html) and the developers page
(how_it_works_developers.html) render this one list,
so the copy and the visibility rules stay the same while the layout differs.

Visibility rules come from the code, not from marketing:
- reviews.models.ReviewerToken: answers link to a random token, not a person.
  An invited email sits on the token; invite links have no email at all.
- reports.services.apply_display_anonymization: per-question detail and
  comments for peers and direct reports need at least
  Organization.min_responses_for_anonymity answers (default 3). The self and
  manager groups are exempt. Overall scores and charts use all answers.
- reports.views: org admins see every report; a reviewee sees only their own,
  and only after the round is complete.
- admin_dashboard/manage_invitations.html: admins see which invited email has
  finished, never what that person answered.

Media with "placeholder": True are screenshots not captured yet;
the template shows a labelled box with the expected filename.
Media with "device": "phone" or "desktop" are two versions of one screen;
the HR page shows one set at a time, with a switch.
"""

ROLES = [
    {"key": "admin", "name": "Admin", "desc": "The person who runs Blik. Often HR or the team manager."},
    {"key": "reviewee", "name": "Reviewee", "desc": "The person who gets feedback."},
    {"key": "reviewers", "name": "Reviewers", "desc": "Peers, the manager and direct reports who give feedback."},
]


def _see(sees, hidden):
    return {"sees": sees, "hidden": hidden}


STEPS = [
    {
        "slug": "sign-up",
        "act": "setup",
        "title": "Sign up",
        "lead": "Pick a plan and pay with Stripe. You get an admin account and a welcome email.",
        "points": [
            "€19 buys 10 credits. One credit is one round for one reviewee.",
            "Reviewers are free. There is no limit on reviewers.",
            "A subscription covers up to 50 reviewees and starts with a 14-day free trial. For more people, ask Thijs.",
            "Or self-host the open source version for free.",
        ],
        "media": [
            {"kind": "browser", "shot": "signup_desktop",
             "alt": "The Blik sign-up page with the plan choice"},
        ],
        "visibility": {
            "admin": _see("Your own account. Nothing else exists yet.", ""),
            "reviewee": _see("", "Nothing. Blik sends no email to your team at this step."),
            "reviewers": _see("", "Nothing."),
        },
    },
    {
        "slug": "configure",
        "act": "setup",
        "title": "Set up your account and questionnaires",
        "lead": "Name your company and choose how Blik sends email. Then pick a questionnaire.",
        "points": [
            "Four questionnaires come with Blik. Use them as they are, or edit them.",
            "Write your own with rating scales, multiple choice and free text.",
            "Set the anonymity minimum. The default is 3 answers per group.",
            "Choose if Blik sends the report to the reviewee when the round ends.",
        ],
        "media": [
            {"kind": "browser", "shot": "questionnaire_edit_desktop",
             "alt": "Editing a questionnaire in Blik"},
        ],
        "visibility": {
            "admin": _see("All settings and all questionnaires.", ""),
            "reviewee": _see("", "Nothing yet. Your own questionnaires stay private to your organisation."),
            "reviewers": _see("", "Nothing yet."),
        },
    },
    {
        "slug": "people",
        "act": "setup",
        "title": "Add your people",
        "lead": "Add each reviewee with a name, an email and a department. Invite colleagues who help run Blik.",
        "points": [
            "An organisation admin sees all reviewees and all reports.",
            "A member can only start a round for themselves.",
            "Reviewers do not need an account. They never appear in this list.",
        ],
        "media": [
            {"kind": "browser", "shot": "reviewees_desktop", "focus": "15%",
             "alt": "The reviewees page: each person with their questionnaire and rounds"},
        ],
        "visibility": {
            "admin": _see("The list of reviewees and colleagues.", ""),
            "reviewee": _see("", "Nothing. Adding a person sends no email."),
            "reviewers": _see("", "Nothing."),
        },
    },
    {
        "slug": "round",
        "act": "setup",
        "title": "Start a review round",
        "lead": "Pick a reviewee and a questionnaire. Then add reviewers by email, per group.",
        "points": [
            "The groups are self, manager, peers and direct reports.",
            "Start rounds for many reviewees at once with the same questionnaire.",
            "Or skip the emails. Share one link per group, and each person who opens it gets a private link.",
            "Send the invitations now or later. Send reminders from the round page.",
        ],
        "media": [
            {"kind": "browser", "shot": "cycle_create_desktop",
             "alt": "Creating a review round: reviewee, questionnaire and reviewer emails"},
            {"kind": "browser", "shot": "cycle_detail_desktop", "focus": "15%",
             "alt": "A running round: how many reviewers finished, and the invitation links"},
        ],
        "visibility": {
            "admin": _see("Which invited emails have finished, and how many are open.",
                          "What any reviewer answered. With share links, not even who answered."),
            "reviewee": _see("An email that the round has started.", "Who you invited, unless you tell them."),
            "reviewers": _see("An email with their private link.", "Who else got an invitation."),
        },
    },
    {
        "slug": "reviewee",
        "act": "round",
        "title": "The reviewee gets an email",
        "lead": "The reviewee gets a link to their self-assessment. They answer the same questions as everyone else.",
        "points": [
            "No account and no password. The link is enough.",
            "Progress saves. They can stop and come back.",
            "After one week, Blik emails them how many reviews are done.",
        ],
        "email": {
            "subject": "Your self-assessment: Professional Skills 360 Review",
            "lines": [
                "Hi Emma,",
                "A new 360-degree feedback cycle has been created for you!",
                "Please complete your self-assessment by clicking the link below.",
            ],
            "button": "Complete Self-Assessment",
        },
        "media": [
            {"kind": "phone", "device": "phone", "shot": "email_reviewee_self_assessment_mobile",
             "alt": "The self-assessment email on a phone"},
            {"kind": "phone", "device": "phone", "shot": "self_assessment_mobile",
             "alt": "The self-assessment questionnaire on a phone"},
            {"kind": "browser", "device": "desktop", "shot": "email_reviewee_self_assessment_desktop",
             "alt": "The self-assessment email on a computer"},
            {"kind": "browser", "device": "desktop", "shot": "self_assessment_desktop",
             "alt": "The self-assessment questionnaire on a computer"},
        ],
        "visibility": {
            "admin": _see("If the self-assessment is done.", "The self-assessment answers, until the report."),
            "reviewee": _see("Their own questions and answers. A count of finished reviews.",
                             "Any answer from a reviewer. Who has answered."),
            "reviewers": _see("", "The self-assessment."),
        },
    },
    {
        "slug": "reviewers",
        "act": "round",
        "title": "Reviewers answer on a computer or a phone",
        "lead": "Each reviewer gets an email with a private link. The questionnaire works on any computer or phone.",
        "points": [
            "No app to install and no account to make.",
            "One section per screen. The answer buttons are large.",
            "Progress saves. A field worker can finish in two breaks.",
            "Answers are stored against the random link, not against a name.",
        ],
        "email": {
            "subject": "Your feedback for Emma Davis",
            "lines": [
                "Hello,",
                "You have been invited to provide peer feedback for Emma Davis.",
                "Your feedback is anonymous and will help Emma Davis grow professionally.",
            ],
            "button": "Start Your Review",
        },
        "media": [
            {"kind": "phone", "device": "phone", "shot": "email_reviewer_invitation_mobile",
             "alt": "The reviewer invitation email on a phone"},
            {"kind": "phone", "device": "phone", "shot": "feedback_mobile",
             "alt": "A reviewer answering questions on a phone"},
            {"kind": "browser", "device": "desktop", "shot": "email_reviewer_invitation_desktop",
             "alt": "The reviewer invitation email on a computer"},
            {"kind": "browser", "device": "desktop", "shot": "feedback_desktop",
             "alt": "A reviewer answering questions on a computer"},
        ],
        "visibility": {
            "admin": _see("That an invited email has finished.", "What that person answered."),
            "reviewee": _see("", "Who answered, and what one person answered."),
            "reviewers": _see("Only their own answers.", "Other answers and the report."),
        },
    },
    {
        "slug": "language",
        "act": "round",
        "title": "Each reviewer reads it in their own language",
        "lead": "When a questionnaire is fully translated, each reviewer sees it in their own language. Blik takes the language from their browser. Nobody has to choose.",
        "points": [
            "The four questionnaires that come with Blik are fully translated into German, formal and informal.",
            "Translate your own questionnaires next to the original. Blik shows which texts are missing or out of date.",
            "The self-assessment uses the language set for the reviewee.",
            "A reviewer can change the language on the form. Reminders then go out in that language.",
            "A text without a translation shows in the original language.",
        ],
        "media": [
            {"kind": "phone", "device": "phone", "shot": "feedback_translated_mobile",
             "alt": "A reviewer with a German browser sees the questionnaire in German"},
            {"kind": "browser", "device": "desktop", "shot": "feedback_translated_desktop",
             "alt": "A reviewer with a German browser sees the questionnaire in German"},
            {"kind": "browser", "shot": "questionnaire_translate_desktop",
             "alt": "Translating a questionnaire into German, next to the English original"},
        ],
        "visibility": {
            "admin": _see("How far each questionnaire is translated, per language.", ""),
            "reviewee": _see("Their self-assessment in their own language.", ""),
            "reviewers": _see("The questionnaire in their own language.", ""),
        },
    },
    {
        "slug": "report",
        "act": "result",
        "title": "The report",
        "lead": "The round closes when every invited reviewer has answered, or when you close it. Blik then makes the report.",
        "points": [
            "A radar chart compares self, manager, peers and direct reports.",
            "The biggest gaps between self and others come first.",
            "A skill level on the Dreyfus model and an initiative level on the five levels of agency.",
            "Strengths, development areas and written comments.",
        ],
        "media": [
            {"kind": "browser", "shot": "report_charts_desktop",
             "alt": "A radar chart comparing self, peer, manager and direct report ratings"},
            {"kind": "browser", "shot": "report_professional_skills_overview",
             "alt": "Report overview: overall score, self-assessment gap and skill level"},
        ],
        "visibility": {
            "admin": _see("The full report, grouped the same way.", "Which person gave which answer."),
            "reviewee": _see("Their own report, through a private link. Answers are grouped: self, manager, peers, direct reports.",
                             "Peer or direct-report detail and comments, if fewer than 3 people in that group answered."),
            "reviewers": _see("", "The report."),
        },
        "note": "The manager group is not pooled with others. If one manager answers, the reviewee knows those answers are from their manager. Overall scores and charts use all answers.",
    },
    {
        "slug": "manager",
        "act": "result",
        "title": "The manager view",
        "lead": "Admins open every report from one place. The reviewees page shows where each person differs most from how others see them.",
        "points": [
            "One row per reviewee, with the gap between self and others.",
            "The largest gaps come first, so you know who to talk to first.",
            "Open a row to go to that person's report.",
        ],
        "media": [
            {"kind": "browser", "shot": "reviewees_gap_desktop",
             "alt": "Overview of all reviewees, sorted by the gap between self-assessment and others"},
        ],
        "visibility": {
            "admin": _see("All reports in the organisation, and the gap per person.", "Any single reviewer's answers."),
            "reviewee": _see("Only their own report.", "Other people's reports and the overview."),
            "reviewers": _see("", "The overview and the reports."),
        },
    },
]

ACTS = [
    {"key": "setup", "name": "You set it up", "who": "Admin"},
    {"key": "round", "name": "The round runs", "who": "Reviewee and reviewers"},
    {"key": "result", "name": "You read the result", "who": "Reviewee and admin"},
]


def context():
    steps = [dict(step, number=i, has_devices=any("device" in m for m in step["media"]))
             for i, step in enumerate(STEPS, start=1)]
    acts = [dict(act, steps=[s for s in steps if s["act"] == act["key"]]) for act in ACTS]
    return {"roles": ROLES, "steps": steps, "acts": acts}
