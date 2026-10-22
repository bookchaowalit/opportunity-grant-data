"""One explicit official source; all unsupported facts remain unknown."""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .cli import resource, timestamp, validate
from .observability import init_sentry, report_exit

MONTHS = {
    name: number
    for number, name in enumerate(
        (
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ),
        1,
    )
}


def uk_time_to_utc(day_month_year, clock, meridiem):
    """Convert a published "16 September 2026 11:00am UK time" cutoff to UTC.

    Month names and am/pm are matched explicitly, so the host locale (which drives
    ``strptime`` %B/%p) cannot change the result, and UK summer time comes from the
    Europe/London zone rather than the host clock.
    """
    day, month, year = day_month_year.split()
    hour, minute = (int(part) for part in clock.split(":"))
    if month.casefold() not in MONTHS or not 1 <= hour <= 12:
        raise ValueError("unsupported UK closing time")
    hour = hour % 12 + (12 if meridiem.casefold() == "pm" else 0)
    local = datetime(int(year), MONTHS[month.casefold()], int(day), hour, minute, tzinfo=ZoneInfo("Europe/London"))
    return local.astimezone(timezone.utc)


class Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "svg"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, value):
        if not self.hidden:
            self.parts.append(value)


def _normalize_generic(raw, source, checked_at):
    if source.get("access") == "govuk-api":
        body = json.loads(raw)
        if not isinstance(body, dict) or not isinstance(body.get("details"), dict):
            raise ValueError("unexpected GOV.UK document")
        text = " ".join(str(body.get(key, "")) for key in ("title", "description", "details"))
    else:
        parser = Text()
        parser.feed(raw.decode("utf-8"))
        text = " ".join(" ".join(parser.parts).split())
    folded = text.casefold()
    markers = source.get("required_markers") or [source["title"]]
    if not all(marker.casefold() in folded for marker in markers):
        raise ValueError("generic grant source drift or challenge page")
    schema = resource("schema-v2.json")
    terms: dict[str, Any] = {
        key: None for key in schema["properties"]["items"]["items"]["properties"]["terms"]["properties"]
    }
    terms.update(source.get("normalized_terms", {}))
    record_id = source["id"]
    item = {
        "id": record_id,
        "title": source["title"],
        "record_kind": source["record_kind"],
        "category": source["category"],
        "source_url": source["source_url"],
        "provider": source["provider"],
        "status": source.get("status", "unknown"),
        "deadline": {"kind": source.get("deadline_kind", "unknown"), "at": None},
        "eligible_countries": source.get("eligible_countries", ["GLOBAL"]),
        "eligibility_text": source["eligibility_text"],
        "value": {
            "kind": source.get("value_kind", "unknown"),
            "amount": source.get("value_amount"),
            "currency": source.get("value_currency"),
            "guaranteed": source.get("value_guaranteed"),
        },
        "cost": {"fee_amount": None, "currency": None, "auto_renewal": None, "notes": source["cost_notes"]},
        "terms": terms,
        "related_records": [],
        "provenance": {
            "evidence_kind": "captured",
            "source_id": source["id"],
            "source_record_id": record_id,
            "checked_at": checked_at,
            "raw_object_key": None,
            "bronze_manifest_key": None,
        },
    }
    return {
        "schema_version": source["schema_version"],
        "source": source["product"],
        "retrieved_at": checked_at,
        "data_status": "live",
        "items": [item],
    }


def normalize(raw, source, checked_at):
    if source.get("generic_html"):
        return _normalize_generic(raw, source, checked_at)
    schema = resource("schema-v2.json")
    terms: dict[str, Any] = {
        key: None for key in schema["properties"]["items"]["items"]["properties"]["terms"]["properties"]
    }
    deadline: dict[str, Any] = {"kind": "unknown", "at": None}
    status = "unknown"
    countries: list[str] = []
    if source["access"] == "govuk-api":
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise ValueError("unexpected GOV.UK document")
        if body.get("base_path") != source["source_url"].removeprefix("https://www.gov.uk") or not isinstance(
            body.get("details"), dict
        ):
            raise ValueError("unexpected GOV.UK document")
        title = body.get("title")
        expected = {"grant": "Apply for innovation funding", "benefit": "Universal Credit"}[source["domain"]]
        if title != expected:
            raise ValueError("source title drift")
        eligibility = (
            "UK program; read current eligibility and residence or organization requirements at the official source."
        )
        if source["domain"] == "benefit":
            terms["jurisdiction"] = "United Kingdom"
    elif source["id"] == "depa-digital-startup-fund":
        parser = Text()
        parser.feed(raw.decode("utf-8"))
        text = " ".join(" ".join(parser.parts).split())
        if "Digital Startup Fund" not in text or "depa" not in text.lower() or "Idea Stage" not in text:
            raise ValueError("depa source drift or challenge page")
        title = "depa Digital Startup Fund (Thailand)"
        countries = ["TH"]
        eligibility = "Thailand digital startup funding directory; current round, applicant type, required documents and submission window must be verified at the official depa source."
        terms["funding_purpose"] = "Digital startup business promotion and support."
        terms["applicant_type"] = "either"
    elif source["id"] == "iuk-zevi2-alternative-fuels":
        parser = Text()
        parser.feed(raw.decode("utf-8"))
        text = " ".join(" ".join(parser.parts).split())
        lower = text.casefold()
        required = (
            "zero emission vessels and infrastructure two: alternative fuels" in lower
            and "closing date:" in lower
            and "funding type:" in lower
            and "grant" in lower
            and "uk registered" in lower
        )
        if not required:
            raise ValueError("Innovate UK ZEVI source drift or challenge page")
        closing = re.search(
            r"Closing date:\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})\s+(\d{1,2}:\d{2})\s*(am|pm)\s+UK time", text, re.I
        )
        if not closing:
            raise ValueError("Innovate UK ZEVI closing date missing or changed")
        title = "Zero Emission Vessels and Infrastructure 2: Alternative Fuels"
        countries = ["GB"]
        eligibility = "UK registered organisations can apply for a share of the published competition funding; project, collaboration and clean maritime eligibility terms must be verified at the official source."
        terms["funding_purpose"] = (
            "Develop, deploy and operate innovative clean maritime solutions in a real-world environment."
        )
        terms["applicant_type"] = "organization"
        terms["reporting_obligation"] = (
            "Project delivery, monitoring and competition-specific reporting terms apply; verify the official brief."
        )
        cutoff = uk_time_to_utc(closing[1], closing[2], closing[3])
        deadline = {"kind": "fixed", "at": cutoff.isoformat().replace("+00:00", "Z")}
        explicitly_closed = bool(re.search(r"Opportunity status:\s*Closed\b", text, re.I))
        status = "closed" if explicitly_closed or cutoff <= timestamp(checked_at) else "open"
    else:
        raise ValueError("unknown grant source")
    record_id = source["id"] + (":" + deadline["at"][:10] if deadline["kind"] == "fixed" else "")
    value_kind = (
        "access"
        if source["domain"] == "freebie"
        else ("cash" if source["id"] in {"depa-digital-startup-fund", "iuk-zevi2-alternative-fuels"} else "unknown")
    )
    value_currency = "GBP" if source["id"] == "iuk-zevi2-alternative-fuels" else None
    item = {
        "id": record_id,
        "title": title,
        "record_kind": source["record_kind"],
        "category": source["category"],
        "source_url": source["source_url"],
        "provider": source["provider"],
        "status": status,
        "deadline": deadline,
        "eligible_countries": countries,
        "eligibility_text": eligibility,
        "value": {
            "kind": value_kind,
            "amount": None,
            "currency": value_currency,
            "guaranteed": False if source["id"] == "iuk-zevi2-alternative-fuels" else None,
        },
        "cost": {
            "fee_amount": None,
            "currency": None,
            "auto_renewal": None,
            "notes": "Not extracted; review official terms before applying or claiming.",
        },
        "terms": terms,
        "related_records": [],
        "provenance": {
            "evidence_kind": "captured",
            "source_id": source["id"],
            "source_record_id": record_id,
            "checked_at": checked_at,
            "raw_object_key": None,
            "bronze_manifest_key": None,
        },
    }
    return {
        "schema_version": source["schema_version"],
        "source": source["product"],
        "retrieved_at": checked_at,
        "data_status": "live",
        "items": [item],
    }


def source_config(source_id=None):
    if source_id is None:
        return resource("source.json")
    if not re.fullmatch(r"[a-z0-9-]+", source_id):
        raise ValueError("invalid source id")
    base = resource("source.json")
    if base["id"] == source_id:
        return base
    try:
        return resource("source-" + source_id + ".json")
    except FileNotFoundError:
        raise ValueError("unknown source id") from None


def main(argv=None):
    selector = argparse.ArgumentParser(add_help=False)
    selector.add_argument("--source-id")
    selected, remaining = selector.parse_known_args(argv)
    root = os.environ.get("SOLO_DATA_LAKE_ROOT")
    if not root:
        print("Set SOLO_DATA_LAKE_ROOT to the local shared capture/lake runtime.", file=sys.stderr)
        return 2
    runtime = Path(root).resolve() / "infra/scripts"
    if not (runtime / "discovery/capture_runtime.py").is_file():
        print("Shared discovery runtime is unavailable.", file=sys.stderr)
        return 2
    sys.path.insert(0, str(runtime))
    from discovery.capture_runtime import VERSION, run

    if VERSION != 1:
        raise RuntimeError("unsupported shared capture runtime")
    source = source_config(selected.source_id)
    sentry = init_sentry(source["id"])
    return report_exit(sentry, source["id"], run(source, normalize, validate, remaining))


if __name__ == "__main__":
    raise SystemExit(main())
