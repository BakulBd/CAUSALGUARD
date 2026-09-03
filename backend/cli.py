"""``causalguard`` command line entrypoint.

causalguard serve   [--host --port --workers --reload]
causalguard config                # print redacted effective configuration
causalguard check                 # run readiness checks, exit non-zero if down
causalguard seed    [--scenario]  # drive a scenario + run one investigation
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys

from backend.config import get_settings


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    s = get_settings()
    uvicorn.run(
        "backend.api.main:app",
        host=args.host or s.server.host,
        port=args.port or s.server.port,
        workers=1 if args.reload else (args.workers or s.server.workers),
        reload=args.reload,
        log_config=None,  # our own structured logging owns stdout
        access_log=False,
    )
    return 0


def _cmd_config(_: argparse.Namespace) -> int:
    print(json.dumps(get_settings().redacted(), indent=2, default=str))
    return 0


def _cmd_check(_: argparse.Namespace) -> int:
    from backend.api.deps import build_platform_service
    from backend.persistence.database import get_database

    async def run() -> int:
        db = get_database()
        try:
            await db.connect()
        except Exception as exc:
            print(f"database: FAILED ({exc})")
        platform = build_platform_service()
        checks = await platform.readiness()
        worst_ok = True
        for c in checks:
            print(f"{c.name:16s} {c.status:9s} {c.detail}")
            if c.status == "down":
                worst_ok = False
        await platform.aclose()
        await db.disconnect()
        return 0 if worst_ok else 1

    return asyncio.run(run())


def _cmd_seed(args: argparse.Namespace) -> int:
    from backend.api.deps import build_platform_service
    from backend.persistence.database import get_database

    async def run() -> int:
        db = get_database()
        with contextlib.suppress(Exception):
            await db.connect()
        platform = build_platform_service()
        if args.scenario and args.scenario != "healthy":
            platform.start_scenario(args.scenario)
            # fast-forward the scenario clock so signals are fully ramped
            platform.context.started_at -= float(args.age)
        dossier = await platform.run_investigation()
        print(
            json.dumps(
                {
                    "incident_id": dossier.incident_id,
                    "risk_type": dossier.risk_type,
                    "severity": dossier.severity,
                    "risk_score": dossier.risk_score,
                    "recommendation": dossier.final_recommendation,
                },
                indent=2,
            )
        )
        await platform.aclose()
        await db.disconnect()
        return 0

    return asyncio.run(run())


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="causalguard", description="CausalGuard control CLI")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("serve", help="run the API server")
    sp.add_argument("--host")
    sp.add_argument("--port", type=int)
    sp.add_argument("--workers", type=int)
    sp.add_argument("--reload", action="store_true")
    sp.set_defaults(func=_cmd_serve)

    cp = sub.add_parser("config", help="print redacted effective configuration")
    cp.set_defaults(func=_cmd_config)

    kp = sub.add_parser("check", help="run readiness checks")
    kp.set_defaults(func=_cmd_check)

    dp = sub.add_parser("seed", help="drive a scenario and run one investigation")
    dp.add_argument("--scenario", default="pg-table-bloat")
    dp.add_argument(
        "--age", type=float, default=90.0, help="seconds to fast-forward the scenario clock"
    )
    dp.set_defaults(func=_cmd_seed)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
