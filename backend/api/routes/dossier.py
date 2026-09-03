"""Incident dossier export (Markdown + JSON)."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse

from backend.api.deps import get_platform
from backend.models.schema import IncidentDossier
from backend.services.platform import PlatformService

router = APIRouter(prefix="/dossier", tags=["dossier"])


def render_markdown(d: IncidentDossier) -> str:
    md = f"""# CausalGuard Incident Prevention Dossier
**Dossier ID:** {d.incident_id}
**Timestamp:** {time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(d.generated_at))}
**Scenario:** {d.scenario}
**Telemetry Source:** {d.source_mode}
**Mode:** {d.mode}
**Risk Type:** {d.risk_type}
**Severity:** {d.severity}
**Risk Score:** {d.risk_score} / 100

## Score Attribution
"""
    for k, v in d.score_contributors.items():
        if v:
            md += f"- **{k.replace('_', ' ').title()}:** +{v} pts\n"

    md += """
## Hypotheses & Falsification Audit
| Hypothesis Claim | Target | Expected Signature | Actual Observation | Status | Falsification Reason |
|---|---|---|---|---|---|
"""
    for h in d.hypotheses_evaluated:
        md += (
            f"| {h.claim} | {h.target_entity} | {h.expected_signature} | "
            f"{h.actual_signature} | **{h.verification_status}** | "
            f"{h.contradiction_reason or 'None'} |\n"
        )

    cf = d.counterfactual
    md += f"""
## Counterfactual Comparison
- **Baseline (Do Nothing):** horizon={cf.baseline_do_nothing.predicted_horizon_minutes}m, SLA breach={cf.baseline_do_nothing.expected_sla_breach}
- **Candidate Intervention:** {cf.candidate_intervention.name}
- **Expected Risk Reduction:** {cf.expected_risk_reduction_pct}%

## AMD ROCm Runtime
- **Device:** {d.amd_metrics.device_name} ({d.amd_metrics.architecture})
- **Driver / KFD:** {d.amd_metrics.driver_version} (KFD Available: {d.amd_metrics.kfd_available})
- **Throughput:** {d.amd_metrics.tokens_per_second} tokens/sec (TTFT: {d.amd_metrics.time_to_first_token_ms}ms)
- **VRAM Footprint:** {d.amd_metrics.vram_used_mb}MB / {d.amd_metrics.vram_total_mb}MB
"""
    if d.verification:
        ver = d.verification
        md += f"""
## Empirical Verification ({ver.environment})
- **Action:** {ver.action_name}
- **Verified:** {ver.verified}
- **Risk Reduction:** {ver.risk_reduction_pct}%
"""
        for note in ver.audit_notes:
            md += f"- {note}\n"

    md += f"\n## Final Recommendation\n> **{d.final_recommendation}**\n"
    return md


async def _resolve(dossier_id: str, platform: PlatformService) -> IncidentDossier:
    if dossier_id in ("latest", "current"):
        return await platform.latest_dossier()
    try:
        return await platform.get_dossier(dossier_id)
    except Exception:
        return await platform.latest_dossier()


@router.get("/{dossier_id}/markdown", response_class=PlainTextResponse)
async def dossier_markdown(
    dossier_id: str, platform: PlatformService = Depends(get_platform)
) -> str:
    return render_markdown(await _resolve(dossier_id, platform))


@router.get("/{dossier_id}/json", response_model=IncidentDossier)
async def dossier_json(
    dossier_id: str, platform: PlatformService = Depends(get_platform)
) -> IncidentDossier:
    return await _resolve(dossier_id, platform)
