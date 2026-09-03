import time

import pytest

from backend.persistence.database import Database
from backend.persistence.repository import DossierRepository

pytestmark = pytest.mark.asyncio


def _dossier(i: int, risk="postgresql_table_bloat") -> dict:
    return {
        "incident_id": f"DOSSIER_TEST_{i}",
        "mode": "PROACTIVE",
        "risk_type": risk,
        "severity": "HIGH",
        "risk_score": 55.0 + i,
        "score_contributors": {"dead_tuple_growth": 20.0},
        "causal_graph": {"nodes": [], "edges": [], "root_causes": []},
        "evidence": [
            {
                "id": f"OBSK_TEST_{i}",
                "category": "metric",
                "source": "postgres",
                "name": "x",
                "current_value": 1.0,
                "baseline_value": 0.0,
                "trend": "increasing",
                "slope": 1.0,
                "z_score": 2.0,
                "timestamp": time.time(),
            }
        ],
        "hypotheses_evaluated": [],
        "rejected_hypotheses": [],
        "counterfactual": {
            "risk_id": "R",
            "baseline_do_nothing": {
                "scenario_id": "A",
                "risk_id": "R",
                "name": "A",
                "action_type": "DO_NOTHING",
            },
            "candidate_intervention": {
                "scenario_id": "B",
                "risk_id": "R",
                "name": "B",
                "action_type": "VACUUM_ANALYZE",
            },
            "recommendation": "do it",
            "expected_risk_reduction_pct": 88.0,
        },
        "amd_metrics": {},
        "final_recommendation": "vacuum",
        "generated_at": time.time() + i,
    }


@pytest.fixture
async def repo(tmp_path):
    from backend.config import DatabaseConfig

    db = Database(DatabaseConfig(url=f"sqlite+aiosqlite:///{tmp_path / 't.db'}"))
    await db.connect()
    yield DossierRepository(db, retention=3)
    await db.disconnect()


async def test_save_get_latest_and_list(repo):
    for i in range(2):
        await repo.save_dossier(_dossier(i), scenario="pg-table-bloat", source_mode="simulated")
    got = await repo.get_dossier("DOSSIER_TEST_1")
    assert got and got["risk_score"] == 56.0
    latest = await repo.latest_dossier()
    assert latest["incident_id"] == "DOSSIER_TEST_1"
    rows = await repo.list_dossiers(limit=10, offset=0, risk_type=None)
    assert len(rows) == 2
    assert await repo.count_dossiers() == 2


async def test_retention_prunes_old_dossiers(repo):
    for i in range(6):
        await repo.save_dossier(_dossier(i), scenario="s", source_mode="simulated")
    assert await repo.count_dossiers() == 3
    # newest kept
    assert await repo.get_dossier("DOSSIER_TEST_5") is not None
    assert await repo.get_dossier("DOSSIER_TEST_0") is None


async def test_update_verification(repo):
    await repo.save_dossier(_dossier(0), scenario="s", source_mode="simulated")
    await repo.update_dossier_verification(
        "DOSSIER_TEST_0",
        {
            "intervention_id": "INTV_1",
            "action_name": "VACUUM_ANALYZE",
            "environment": "CONTROLLED_SANDBOX",
            "verified": True,
            "risk_reduction_pct": 90.0,
            "audit_notes": ["ok"],
            "executed_at": time.time(),
        },
    )
    row = await repo.get_dossier("DOSSIER_TEST_0")
    assert row["verification"]["intervention_id"] == "INTV_1"


async def test_repository_noop_when_disabled():
    from backend.config import DatabaseConfig

    db = Database(DatabaseConfig(url="sqlite+aiosqlite:///:memory:"))
    repo = DossierRepository(db)
    assert repo.enabled is False
    assert await repo.latest_dossier() is None
    await repo.save_dossier(_dossier(0), scenario="s", source_mode="simulated")  # must not raise
