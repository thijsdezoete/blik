"""
Facts about 360 feedback tools for /compare/ and /compare/<slug>/.

The tool data is in compare_tools.json, researched from the vendors' public pages
(pricing, security, help centre). Update CHECKED and CHECKED_ISO when you re-check it.
"""

import json
from pathlib import Path

from .context_processors import PRICING

CHECKED = "6 November 2026"
CHECKED_ISO = "2026-11-06"

GROUPS = [
    ("specialist", "360 specialists", "Tools where 360 feedback is the product."),
    ("performance", "Performance platforms", "Suites with 360 inside a reviews module, next to goals and 1:1s."),
    ("goals", "Goal and review tools", "Performance tools, some with a 360 product of their own."),
    ("hr", "HR suites", "HR systems where 360 is part of a bigger plan."),
    ("survey", "Enterprise and survey platforms", "Employee-experience and survey tools with a 360 module or template."),
    ("learning", "Learning and regional suites", "Learning platforms and regional performance suites."),
]

VENDORS = json.loads(Path(__file__).with_name("compare_tools.json").read_text(encoding="utf-8"))
BY_SLUG = {v["slug"]: v for v in VENDORS}

_PACKS = -(-50 // int(PRICING["plan_single_max"]))  # Single Round packs for 50 people
_SINGLE_50 = _PACKS * int(PRICING["plan_single_price"])
_SAAS_YEAR = int(PRICING["plan_saas_annual"])

# Blik is one row in the tables, with the same fields as the other tools.
BLIK = {
    "slug": None, "name": "Blik", "group": "specialist",
    "sold_as": "Standalone, 360 only. Open source (AGPL).",
    "entry": f"Free self-hosted. €{PRICING['plan_single_price']} per {PRICING['plan_single_max']} people for one round. "
             f"€{PRICING['plan_saas_price']}/month up to {PRICING['plan_saas_max']}.",
    "eu": "Yes, Hetzner Germany, or your own server", "ai": "No", "certs": "None",
    "flags": {"published_price": True, "standalone_360": True, "eu_hosting": "default",
              "ai_on_feedback": "no", "certified": "no"},
}

# Annual licence cost for 50 reviewed people and one round a year, cheapest first.
# "sort" is an approximate euro value, only for the order; the shown cost keeps the vendor's currency.
# Quote-only tools are left out. "page" is the URL name of the Blik page for that row.
SCENARIO = sorted([
    {"name": "Blik self-hosted", "page": "open_source", "cost": "€0 licence", "sort": 0,
     "basis": "Free AGPL software plus your own server (about €10–50/month)."},
    {"name": "Blik Single Round", "page": "one_time_360_review", "cost": f"€{_SINGLE_50}", "sort": _SINGLE_50,
     "basis": f"{_PACKS} packs of €{PRICING['plan_single_price']} for {PRICING['plan_single_max']} people. One round, no subscription."},
    {"name": "Blik EU SaaS", "page": "pricing", "cost": f"€{_SAAS_YEAR}", "sort": _SAAS_YEAR,
     "basis": f"€{PRICING['plan_saas_price']}/month for up to {PRICING['plan_saas_max']} people, all rounds included."},
] + [
    {"slug": v["slug"], "name": v["name"], "cost": v["pricing"]["cost"]["50"]["cost"],
     "basis": v["pricing"]["cost"]["50"]["basis"], "sort": v["pricing"]["sort_eur_50"]}
    for v in VENDORS if v["pricing"]["sort_eur_50"] is not None
], key=lambda row: row["sort"])
