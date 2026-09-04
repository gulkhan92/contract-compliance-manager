"""Seed a demo organization with sample contracts + a synthetic obligation
calendar, built from the CUAD v1 dataset's real (but historical) clause
annotations — so the compliance calendar and dashboard have a realistic,
multi-month, multi-status view to demo without waiting on live uploads.

See docs/CONTRACT_CLM_BUILD_PLAN.md §5.2. Never runs without --demo, and
refuses outright against ENVIRONMENT=production, so it can't accidentally
run against a real deployment.

Usage (from backend/, with the venv active and the DB migrated):
    python -m scripts.seed_demo_data --demo
    python -m scripts.seed_demo_data --demo --limit 50 --reset
    python -m scripts.seed_demo_data --demo --cuad-path ../data/cuad_v1/CUAD_v1/master_clauses.csv
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import random
import re
import sys
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from dateutil import parser as date_parser
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.enums import (
    ContractStatus,
    ContractType,
    ObligationCategory,
    ObligationStatus,
    RecurrenceType,
    UserRole,
)
from app.db.models import (
    Alert,
    Contract,
    ContractChunk,
    ExtractionJob,
    Obligation,
    Organization,
    User,
)
from app.db.session import AsyncSessionLocal

DEMO_ORG_NAME = "Demo Legal Ops"
DEFAULT_CUAD_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "cuad_v1" / "CUAD_v1" / "master_clauses.csv"
)

# A demo user's hashed_password is not a real bcrypt hash — real password
# hashing (passlib/bcrypt) is wired up in Phase 2. These accounts cannot
# actually log in until then; the value below is deliberately unusable.
UNUSABLE_SEED_PASSWORD_HASH = "!seed-data-no-real-login-until-phase-2-auth!"

CONTRACT_TYPE_KEYWORDS: list[tuple[str, ContractType]] = [
    ("non-disclosure", ContractType.NDA),
    ("nda", ContractType.NDA),
    ("master service", ContractType.MSA),
    ("lease", ContractType.LEASE),
    ("employment", ContractType.EMPLOYMENT),
    ("license", ContractType.LICENSE),
    ("vendor", ContractType.VENDOR),
    ("supply", ContractType.VENDOR),
    ("distribut", ContractType.VENDOR),
]


@dataclass(frozen=True)
class ObligationField:
    """One CUAD column this seeder can turn into an Obligation."""

    raw_col: str
    answer_col: str
    category: ObligationCategory

    def description_for(self, answer: str) -> str:
        return DESCRIPTION_TEMPLATES[self.category, self.raw_col](answer)


DESCRIPTION_TEMPLATES: dict[tuple[ObligationCategory, str], Callable[[str], str]] = {
    (ObligationCategory.RENEWAL, "Renewal Term"): lambda a: f"Contract auto-renews: {a}.",
    (ObligationCategory.TERMINATION_NOTICE, "Notice Period To Terminate Renewal"): (
        lambda a: f"Requires {a} written notice to prevent auto-renewal or terminate."
    ),
    (ObligationCategory.TERMINATION_NOTICE, "Termination For Convenience"): (
        lambda _a: "Either party may terminate this agreement for convenience."
    ),
    (ObligationCategory.GOVERNING_LAW, "Governing Law"): lambda a: f"Governed by the laws of {a}.",
    (ObligationCategory.NON_COMPETE, "Non-Compete"): (
        lambda _a: "Agreement contains a non-compete restriction."
    ),
    (ObligationCategory.AUDIT_RIGHTS, "Audit Rights"): (
        lambda _a: "Counterparty holds audit rights over records/compliance."
    ),
    (ObligationCategory.LIMITATION_OF_LIABILITY, "Cap On Liability"): (
        lambda _a: "Liability is capped per the agreement's limitation-of-liability terms."
    ),
    (ObligationCategory.LIMITATION_OF_LIABILITY, "Uncapped Liability"): (
        lambda _a: "Liability is uncapped for certain categories of breach."
    ),
    (ObligationCategory.PAYMENT_MILESTONE, "Revenue/Profit Sharing"): (
        lambda _a: "Revenue/profit-sharing payment obligation applies."
    ),
    (ObligationCategory.PAYMENT_MILESTONE, "Minimum Commitment"): (
        lambda _a: "A minimum purchase/spend commitment applies."
    ),
    (ObligationCategory.SLA_COMMITMENT, "Insurance"): (
        lambda _a: "Party must maintain minimum insurance coverage."
    ),
    (ObligationCategory.SLA_COMMITMENT, "Warranty Duration"): lambda a: f"Warranty period: {a}.",
}

OBLIGATION_FIELDS: list[ObligationField] = [
    ObligationField("Renewal Term", "Renewal Term-Answer", ObligationCategory.RENEWAL),
    ObligationField(
        "Notice Period To Terminate Renewal",
        "Notice Period To Terminate Renewal- Answer",
        ObligationCategory.TERMINATION_NOTICE,
    ),
    ObligationField(
        "Termination For Convenience",
        "Termination For Convenience-Answer",
        ObligationCategory.TERMINATION_NOTICE,
    ),
    ObligationField("Governing Law", "Governing Law-Answer", ObligationCategory.GOVERNING_LAW),
    ObligationField("Non-Compete", "Non-Compete-Answer", ObligationCategory.NON_COMPETE),
    ObligationField("Audit Rights", "Audit Rights-Answer", ObligationCategory.AUDIT_RIGHTS),
    ObligationField(
        "Cap On Liability", "Cap On Liability-Answer", ObligationCategory.LIMITATION_OF_LIABILITY
    ),
    ObligationField(
        "Uncapped Liability",
        "Uncapped Liability-Answer",
        ObligationCategory.LIMITATION_OF_LIABILITY,
    ),
    ObligationField(
        "Revenue/Profit Sharing",
        "Revenue/Profit Sharing-Answer",
        ObligationCategory.PAYMENT_MILESTONE,
    ),
    ObligationField(
        "Minimum Commitment", "Minimum Commitment-Answer", ObligationCategory.PAYMENT_MILESTONE
    ),
    ObligationField("Insurance", "Insurance-Answer", ObligationCategory.SLA_COMMITMENT),
    ObligationField(
        "Warranty Duration", "Warranty Duration-Answer", ObligationCategory.SLA_COMMITMENT
    ),
]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Required. Confirms you intend to write demo/synthetic data.",
    )
    parser.add_argument(
        "--cuad-path",
        type=Path,
        default=DEFAULT_CUAD_PATH,
        help="Path to CUAD_v1/master_clauses.csv (see data/README.md).",
    )
    parser.add_argument(
        "--limit", type=int, default=25, help="Number of CUAD contracts to seed (default: 25)."
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete any existing demo org's data first, then reseed.",
    )
    return parser.parse_args(argv)


def infer_contract_type(document_name: str) -> ContractType:
    lowered = document_name.lower()
    for keyword, contract_type in CONTRACT_TYPE_KEYWORDS:
        if keyword in lowered:
            return contract_type
    return ContractType.OTHER


def parse_cuad_date(raw: str) -> date | None:
    if not raw.strip():
        return None
    try:
        return date_parser.parse(raw, fuzzy=True, default=datetime(2020, 1, 1)).date()
    except (ValueError, OverflowError):
        return None


def parse_notice_period_days(raw: str) -> int | None:
    match = re.search(r"(\d+)\s*day", raw, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def clean_raw_span(raw: str) -> str | None:
    """CUAD's non-'-Answer' columns hold a Python-list-repr string of quoted
    spans (e.g. "['...text...', '...text...']"). Strip that down to plain
    text for `raw_source_text`."""
    stripped = raw.strip()
    if not stripped:
        return None
    stripped = stripped.strip("[]")
    parts = re.findall(r"'((?:[^'\\]|\\.)*)'", stripped) or re.findall(
        r'"((?:[^"\\]|\\.)*)"', stripped
    )
    text = " ... ".join(parts) if parts else stripped
    text = text.strip()
    return text[:2000] if text else None


def iter_cuad_rows(cuad_path: Path, limit: int) -> Iterator[dict[str, str]]:
    with cuad_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if i >= limit:
                return
            yield row


def build_obligations(
    contract_id: uuid.UUID, row: dict[str, str], today: date
) -> list[Obligation]:
    obligations: list[Obligation] = []

    for field in OBLIGATION_FIELDS:
        answer = row.get(field.answer_col, "").strip()
        if not answer or answer.lower() == "no":
            continue

        trigger_date = today + timedelta(days=random.randint(-60, 400))
        notice_period_days = (
            parse_notice_period_days(answer)
            if field.category == ObligationCategory.TERMINATION_NOTICE
            else None
        )
        if field.category in (ObligationCategory.RENEWAL, ObligationCategory.TERMINATION_NOTICE):
            notice_period_days = notice_period_days or random.choice([30, 60, 90])
        computed_alert_date = (
            trigger_date - timedelta(days=notice_period_days) if notice_period_days else None
        )

        status = _derive_status(trigger_date, computed_alert_date, today)
        confidence_score = round(random.uniform(0.55, 0.98), 2)
        is_high_stakes = field.category in (
            ObligationCategory.RENEWAL,
            ObligationCategory.TERMINATION_NOTICE,
        )
        is_human_reviewed = confidence_score >= 0.7 and not is_high_stakes

        monetary_amount = None
        currency = None
        if field.category == ObligationCategory.PAYMENT_MILESTONE:
            monetary_amount = round(random.uniform(1_000, 500_000), 2)
            currency = "USD"

        obligations.append(
            Obligation(
                contract_id=contract_id,
                category=field.category,
                description=field.description_for(answer),
                trigger_date=trigger_date,
                notice_period_days=notice_period_days,
                computed_alert_date=computed_alert_date,
                monetary_amount=monetary_amount,
                currency=currency,
                recurrence=(
                    RecurrenceType.ANNUALLY
                    if field.category == ObligationCategory.RENEWAL
                    else RecurrenceType.NONE
                ),
                status=status,
                confidence_score=confidence_score,
                is_human_reviewed=is_human_reviewed,
                raw_source_text=clean_raw_span(row.get(field.raw_col, "")),
            )
        )

    return obligations


def _derive_status(
    trigger_date: date, computed_alert_date: date | None, today: date
) -> ObligationStatus:
    if trigger_date < today:
        status = ObligationStatus.OVERDUE
    elif computed_alert_date and computed_alert_date <= today:
        status = ObligationStatus.AT_RISK
    else:
        status = ObligationStatus.UPCOMING

    # Sprinkle in resolved/waived so the calendar shows every status.
    roll = random.random()
    if status in (ObligationStatus.OVERDUE, ObligationStatus.AT_RISK) and roll < 0.3:
        return ObligationStatus.RESOLVED
    if status == ObligationStatus.UPCOMING and roll < 0.05:
        return ObligationStatus.WAIVED
    return status


async def wipe_existing_demo_org(session: AsyncSession, org_id: uuid.UUID) -> None:
    contract_ids = (
        await session.execute(select(Contract.id).where(Contract.org_id == org_id))
    ).scalars().all()
    obligation_ids = (
        await session.execute(select(Obligation.id).where(Obligation.contract_id.in_(contract_ids)))
    ).scalars().all()

    if obligation_ids:
        await session.execute(delete(Alert).where(Alert.obligation_id.in_(obligation_ids)))
        await session.execute(delete(Obligation).where(Obligation.id.in_(obligation_ids)))
    if contract_ids:
        await session.execute(
            delete(ContractChunk).where(ContractChunk.contract_id.in_(contract_ids))
        )
        await session.execute(
            delete(ExtractionJob).where(ExtractionJob.contract_id.in_(contract_ids))
        )
        await session.execute(delete(Contract).where(Contract.id.in_(contract_ids)))
    await session.execute(delete(User).where(User.org_id == org_id))
    await session.execute(delete(Organization).where(Organization.id == org_id))
    await session.flush()


async def seed(args: argparse.Namespace) -> None:
    if not args.cuad_path.exists():
        raise SystemExit(
            f"CUAD dataset not found at {args.cuad_path}. "
            "See data/README.md for how to fetch it, or pass --cuad-path."
        )

    today = date.today()

    async with AsyncSessionLocal() as session:
        existing = (
            await session.execute(select(Organization).where(Organization.name == DEMO_ORG_NAME))
        ).scalar_one_or_none()

        if existing is not None:
            if not args.reset:
                raise SystemExit(
                    f"Demo org {DEMO_ORG_NAME!r} already exists. Pass --reset to wipe and reseed."
                )
            print(f"Wiping existing demo org {existing.id} ...")
            await wipe_existing_demo_org(session, existing.id)

        org = Organization(name=DEMO_ORG_NAME)
        session.add(org)
        await session.flush()

        users = [
            User(
                org_id=org.id,
                email="admin@demo.oblitrack.test",
                hashed_password=UNUSABLE_SEED_PASSWORD_HASH,
                role=UserRole.ADMIN,
                full_name="Dana Admin",
            ),
            User(
                org_id=org.id,
                email="counsel@demo.oblitrack.test",
                hashed_password=UNUSABLE_SEED_PASSWORD_HASH,
                role=UserRole.LEGAL_OPS,
                full_name="Casey Counsel",
            ),
            User(
                org_id=org.id,
                email="viewer@demo.oblitrack.test",
                hashed_password=UNUSABLE_SEED_PASSWORD_HASH,
                role=UserRole.VIEWER,
                full_name="Val Viewer",
            ),
        ]
        session.add_all(users)
        await session.flush()
        assignable_users = [u for u in users if u.role != UserRole.VIEWER]

        contract_count = 0
        obligation_count = 0
        status_counts: dict[ObligationStatus, int] = {}

        for row in iter_cuad_rows(args.cuad_path, args.limit):
            filename = row.get("Filename", "").strip()
            document_name = row.get("Document Name-Answer", "").strip() or filename
            if not filename:
                continue

            parties_answer = row.get("Parties-Answer", "").strip()

            contract = Contract(
                org_id=org.id,
                uploaded_by=random.choice(assignable_users).id,
                title=document_name[:500],
                counterparty_name=parties_answer[:500] if parties_answer else None,
                contract_type=infer_contract_type(document_name),
                original_filename=filename,
                storage_path=f"demo/cuad/{filename}",
                file_hash=hashlib.sha256(f"{filename}:{contract_count}".encode()).hexdigest(),
                status=random.choices(
                    [
                        ContractStatus.ACTIVE,
                        ContractStatus.NEEDS_REVIEW,
                        ContractStatus.EXPIRED,
                    ],
                    weights=[0.6, 0.3, 0.1],
                )[0],
                effective_date=parse_cuad_date(row.get("Effective Date-Answer", "")),
                original_expiration_date=parse_cuad_date(row.get("Expiration Date-Answer", "")),
                governing_law=(row.get("Governing Law-Answer", "").strip() or None),
                extraction_confidence=round(random.uniform(0.6, 0.99), 2),
            )
            session.add(contract)
            await session.flush()
            contract_count += 1

            obligations = build_obligations(contract.id, row, today)
            for obligation in obligations:
                if obligation.category in (
                    ObligationCategory.RENEWAL,
                    ObligationCategory.TERMINATION_NOTICE,
                ) and random.random() < 0.7:
                    obligation.assigned_to = random.choice(assignable_users).id
                status_counts[obligation.status] = status_counts.get(obligation.status, 0) + 1
            session.add_all(obligations)
            obligation_count += len(obligations)

        await session.commit()

    print(f"Seeded org {DEMO_ORG_NAME!r} with {len(users)} users, {contract_count} contracts, "
          f"{obligation_count} obligations.")
    print("Obligation status breakdown:")
    for status, count in sorted(status_counts.items(), key=lambda kv: kv[0].value):
        print(f"  {status.value:10s} {count}")


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    if not args.demo:
        raise SystemExit("Refusing to run without --demo (this writes synthetic demo data).")
    if get_settings().environment == "production":
        raise SystemExit("Refusing to seed demo data into ENVIRONMENT=production.")
    asyncio.run(seed(args))


if __name__ == "__main__":
    main()
