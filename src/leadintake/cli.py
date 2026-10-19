"""leadintake: serve | seed | report | status | reset"""

from __future__ import annotations

import argparse
import json
import sys
import time

from . import __version__


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("leadintake.api:app", host=args.host, port=args.port, reload=False)
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    from .config import get_settings
    from .seed import as_form_payload, generate, load, write

    s = get_settings()
    if args.generate:
        rows = generate(args.count)
        out = write(rows, args.out or s.seed_path)
        print(f"wrote {len(rows)} enquiries to {out}")
        return 0
    rows = load(args.out or s.seed_path)
    if not rows:
        rows = generate(args.count)
        write(rows, args.out or s.seed_path)
    rows = rows[: args.count] if args.count else rows

    if args.post:
        import httpx

        ok = 0
        with httpx.Client(timeout=30) as client:
            for i, row in enumerate(rows, 1):
                payload = as_form_payload(row)
                payload.pop("received_at", None)  # the webhook stamps its own time
                r = client.post(args.post, json=payload)
                ok += r.status_code < 300
                print(f"{i:4d} {r.status_code} {row['name']}")
                time.sleep(args.delay)
        print(f"posted {ok}/{len(rows)} to {args.post}")
        return 0 if ok == len(rows) else 1

    from .db import session_scope
    from .pipeline import decide, intake, mark_sent

    sent = 0
    with session_scope() as session:
        for i, row in enumerate(rows, 1):
            lead = intake(as_form_payload(row), session)
            if args.auto_approve:
                decide(session, lead.id, "approve", by="seed --auto-approve")
                mark_sent(session, lead.id)
                sent += 1
            print(
                f"{i:4d} {lead.qualification:4s} {lead.score:3d} "
                f"{'dup ' if lead.is_duplicate else '    '}{lead.name}"
            )
    print(
        f"processed {len(rows)} enquiries"
        + (f", {sent} auto-approved and marked sent" if sent else "")
    )
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from .db import session_scope
    from .report import build_report, to_markdown, write_markdown

    with session_scope() as session:
        r = build_report(session, args.seed)
    if args.json:
        print(json.dumps(r, indent=2))
    else:
        print(to_markdown(r))
    if args.markdown:
        write_markdown(r, args.markdown)
        print(f"written to {args.markdown}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    from sqlalchemy import func, select

    from .config import get_settings
    from .db import session_scope
    from .models import Contact, Incident, Lead

    s = get_settings()
    with session_scope() as session:
        leads = session.scalar(select(func.count()).select_from(Lead)) or 0
        contacts = session.scalar(select(func.count()).select_from(Contact)) or 0
        incidents = session.scalar(select(func.count()).select_from(Incident)) or 0
    print(
        f"leadintake {__version__}\n"
        f"database   {s.database_url}\n"
        f"crm        {s.crm_provider}\n"
        f"llm        {s.llm_provider} ({s.draft_model})\n"
        f"criteria   {s.criteria_path}\n"
        f"leads {leads} · fake-CRM contacts {contacts} · incidents {incidents}"
    )
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    if not args.yes:
        print("refusing without --yes", file=sys.stderr)
        return 2
    from .db import get_engine, reset_engine
    from .models import Base

    engine = get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    reset_engine()
    print("tables dropped and recreated")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="leadintake", description=__doc__)
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="run the API (uvicorn)")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(func=cmd_serve)

    s = sub.add_parser("seed", help="generate or replay the synthetic enquiries")
    s.add_argument("--count", type=int, default=200)
    s.add_argument("--out", help="seed file (default SEED_PATH)")
    s.add_argument("--generate", action="store_true", help="only write the seed file")
    s.add_argument("--post", metavar="URL", help="POST each enquiry to this webhook (n8n)")
    s.add_argument("--delay", type=float, default=0.2, help="seconds between posts")
    s.add_argument("--auto-approve", action="store_true", help="in-process: approve and mark sent")
    s.set_defaults(func=cmd_seed)

    s = sub.add_parser("report", help="the numbers, as Markdown or JSON")
    s.add_argument("--json", action="store_true")
    s.add_argument("--markdown", metavar="PATH", help="also write the Markdown report here")
    s.add_argument("--seed", help="seed file for the duplicate check (default SEED_PATH)")
    s.set_defaults(func=cmd_report)

    s = sub.add_parser("status", help="what is configured and how much is in the database")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("reset", help="drop and recreate every table")
    s.add_argument("--yes", action="store_true")
    s.set_defaults(func=cmd_reset)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
