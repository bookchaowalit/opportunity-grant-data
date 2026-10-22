# book-grant-data

Find non-equity project funding and its reporting obligations.

Status: **local source pilot**. Original v1 demo/validation remains available.
The live lane uses v2 to distinguish unknown domain terms from false and program
directories from actual awards. Seven reviewed official sources are enabled for
explicit manual acquisition; no scheduler, remote deployment or application submission.

## Users and boundary

For people and small teams discovering project grants.
Project funding calls; individual tuition goes to scholarship and cohort admission to startup-program.

Subcategories: research, innovation, arts-culture, community, small-business, climate.

Domain-specific terms: `funding_purpose`, `applicant_type`, `matching_funds_required`, `reporting_obligation`.
Each record represents one program/offer intake window. A repeat intake receives
a distinct source record ID. Cross-domain packages use `related_records` rather
than copying the same award into several products.

## Run locally

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
book-grant-data contract              # v1 (demo)
book-grant-data contract --version v2 # v2 (captured records)
book-grant-data demo --open-only
book-grant-data demo --query "research"
book-grant-data validate src/book_grant_data/demo.json
python -m unittest discover -s tests -v
python -m pip install -e ".[dev]"  # pytest + pinned ruff
ruff check . && python -m pytest -q
uv sync --frozen --all-extras && uv run mypy  # locked env (uv.lock) as CI installs it
```

CI (`.github/workflows/ci.yml`) runs `ruff check`, the offline test suite and a
CLI smoke test on Python 3.10 and 3.13. `tests/test_registry.py` keeps
`sources.json`, the packaged `source*.json` configs and the contract in sync.

With dependencies already available, use `PYTHONPATH=src python3 -m book_grant_data`.
`demo` uses the fixed synthetic clock 2026-09-07T00:00:00Z unless `--as-of` is
provided. `--open-only` excludes closed, unknown-deadline, expired, stale (72h
default), and future-checked records. This is an availability filter; it does
not assert personal eligibility, selection probability, or a guaranteed payout.

Contract: `src/book_grant_data/schema.json` (`grant.v1`).
Unknown amounts, currencies, eligibility and deadlines remain unknown. Cash,
credit, discount, in-kind benefits and access are different value kinds. Never
sum them as cash income. Queries and validation are read-only and do not persist
provided files. The `live` label requires captured lineage, but validation alone
does not verify that referenced lake objects exist or prove source truth.

## Data ownership and source policy

Owner: bookchaowalit. Public program metadata only; no applications, personal
screening answers, financial credentials, cookies, or private transcripts.
See `sources.json` and the source policy below. Select official API/export, then feed,
then bounded permitted scraping. Exact source permission and retention must be
reviewed before network ingestion. No spending, account creation or messaging.

Implemented capture flow: approved source pull → immutable landing bytes
and checksum → Bronze Parquet and manifest through the shared lake runtime →
versioned read-only contract → consumer pull. Each product owns its source
adapters and lake prefix. Producers never write into another app's database,
CRM, tasks, application tracker, or notification system.

## Remaining implementation gates

1. Keep the seven source adapters fresh and add a specific intake-window parser when a reviewed call publishes one.
2. Expand domain field extraction and live quality monitoring.
3. Package the local shared capture runtime for independent deployment.
   Current source capture and replay use the explicit data-lake runtime.
4. Add live source tests, retention/access controls and runtime monitoring.
5. Connect a read-only consumer. Personal eligibility, ranking, deadlines and
   application workflow belong to consumers with separate private storage.

No runtime port is reserved. The former `opportunity.v1` is archival; `job.v1` remains a separate job-data contract.
Breaking contract changes require a new version and a consumer migration.
There is no production deployment to roll back; discard demo output or restore
the previous contract version locally. Source permission, live availability,
real eligibility and production operations are **unverified**, not passing gates.

## Official source pilots

Sources: [GOV.UK / Innovate UK](https://www.gov.uk/apply-funding-innovation),
[depa Digital Startup Fund](https://www.depa.or.th/th/startup),
[Innovate UK ZEVI 2 Alternative Fuels](https://www.ukri.org/opportunity/zero-emission-vessels-and-infrastructure-two-alternative-fuels/),
[National Lottery Community Fund programmes](https://www.tnlcommunityfund.org.uk/funding/funding-programmes),
[Creative Europe culture calls](https://culture.ec.europa.eu/funding/calls),
[Grants.gov research search](https://grants.gov/search-grants.html), and
[SBA grants](https://www.sba.gov/loans/additional-funding-opportunities/grants/).
The exact source configurations live in `src/book_grant_data/source*.json`;
the enabled IDs and capture status are recorded in `sources.json`.
GOV.UK content attribution: Crown copyright, Open Government Licence v3.0.
Other providers' content remains subject to the terms recorded in each source's
`permission_evidence`. Only private source archival and bounded program metadata
extraction; no public mirror of the source body.

Run from this repo with the existing data-lake Python environment:

```bash
export SOLO_DATA_LAKE_ROOT=/path/to/solo-data-lake
PYTHONPATH=src "$SOLO_DATA_LAKE_ROOT/.venv/bin/python" -m book_grant_data.capture acquire --lake "$PWD/data/lake" --state-dir "$PWD/data/control"
PYTHONPATH=src "$SOLO_DATA_LAKE_ROOT/.venv/bin/python" -m book_grant_data.capture records --lake "$PWD/data/lake" --state-dir "$PWD/data/control"
# Select the Thailand NIA directory explicitly when needed:
PYTHONPATH=src "$SOLO_DATA_LAKE_ROOT/.venv/bin/python" -m book_grant_data.capture acquire --source-id depa-digital-startup-fund --lake "$PWD/data/lake" --state-dir "$PWD/data/control"
# Select the specific UKRI/Innovate UK competition explicitly when needed:
PYTHONPATH=src "$SOLO_DATA_LAKE_ROOT/.venv/bin/python" -m book_grant_data.capture acquire --source-id iuk-zevi2-alternative-fuels --lake "$PWD/data/lake" --state-dir "$PWD/data/control"
```

This lane depends on the explicit local shared `discovery.capture_runtime` v1
and existing `data_lake.product_adapter`. No parent-path auto-discovery, cloud
target, credentials or environment-selected lake is used. It is not a standalone
deployed ingestion package yet. The pure v1/v2 contract CLI remains standalone.

Capture preserves exact bytes, a Bronze document-metadata row and manifest before
domain parsing. Records are replayed from checksum-verified landing and Bronze
objects. The per-source control state records a fresh check even when unchanged
bytes reuse an existing immutable batch. Failed latest fetches fail closed;
parser failures leave a quarantined capture reference and no synthetic fallback.

There are at most two source GET attempts (15-second timeout each), a 2 MB
response cap and a six-hour cooldown under a local file lock. HTML sources
recheck robots.txt; API sources use their documented public API and license.
429/auth failures are not retried. Redirects need explicit policy review.
Sensitive session-token markers are refused before archive. The GOV.UK source is
read through the public GOV.UK Content API; adapters for unregistered source IDs
fail closed instead of falling back to a generic parser.

The grant pilot is a **funding directory**, not a claim of an open award. The
depa page remains a Thailand program directory; deadlines, co-funding, amounts
and reporting terms stay unknown there. The ZEVI 2 source is a specific UK
competition and parses its published fixed deadline as 2026-09-16T10:00:00Z
(11:00 UK local time), while applicant, project, collaboration and award terms
remain subject to the official brief. A reviewed NIA candidate remains disabled because its public HTML
exceeds the capture cap and contains a CSRF marker; see `sources.json`.
Missing deadlines, fees, selection guarantees and domain terms remain unknown.
`records` reports the captured check time; callers must apply their freshness
window. No personal eligibility decision is inferred from country or page title.
Retention is operational in a private local archive; cleanup is manual under the
repository data lifecycle policy. No automatic deletion or source republication.
