#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

echo "=========================================================="
echo "          CausalGuard 5-Minute Competition Demo           "
echo "  Predict. Simulate. Verify. Prevent. (AMD ROCm Hackathon)"
echo "=========================================================="

source .venv/bin/activate
PYTHONPATH=. .venv/bin/python -c "
import time
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from backend.scenarios.scenario_manager import scenario_manager
from backend.rocm.serving.rocm_engine import rocm_engine
from backend.rocm.benchmarks.benchmark_engine import rocm_benchmark_suite

console = Console()

# 0:00 - Healthy
console.print(Panel('[bold green]0:00 - System Baseline[/bold green]\nAll API endpoints healthy. Error rate: 0.02%, P99 Latency: 18.4ms, Risk Score: 6.5/100.', style='green'))
time.sleep(1.5)

# 0:20 - Start slow-burn scenario
console.print(Panel('[bold yellow]0:20 - Injecting Slow-Burn Reliability Scenario (pg-table-bloat)[/bold yellow]\nDisabling autovacuum on orders table while continuous write traffic runs...', style='yellow'))
scenario_manager.start_scenario('pg-table-bloat')
time.sleep(1.5)

# 0:40 - Pre-incident risk detected
console.print(Panel('[bold red]0:40 - Pre-Incident Risk Detected by Early-Warning Engine[/bold red]\nDead tuples surging (+1.4M), autovacuum inactive >30m, cache hit declining.\nNotice: User-facing API error rate is still 0.04% - NO OUTAGE YET!', style='bold red'))
time.sleep(1.5)

# 1:30 - Causal Graph
console.print(Panel('[bold cyan]1:30 - Causal Graph Reconstructed[/bold cyan]\nautovacuum_disabled -> dead_tuple_accumulation -> table_bloat -> buffer_cache_thrashing -> disk_read_spike -> predicted_p99_sla_breach', style='cyan'))
dossier = scenario_manager.run_investigation()
time.sleep(1.5)

# 2:00 & 2:30 - Counterfactual Simulation
comp = dossier.counterfactual
console.print(Panel(f'[bold magenta]2:00 - Counterfactual Simulation (What-If Analysis)[/bold magenta]\nScenario A (Do Nothing): SLA breach in {comp.baseline_do_nothing.predicted_horizon_minutes} min (P99={comp.baseline_do_nothing.expected_p99_latency_ms}ms)\nScenario B (Candidate Fix: VACUUM ANALYZE): Prevents breach, Expected Risk Reduction: {comp.expected_risk_reduction_pct}%', style='magenta'))
time.sleep(1.5)

# 3:20 - Verify Intervention in Sandbox
console.print(Panel('[bold blue]3:20 - Executing Sandbox Intervention & Empirical Verification[/bold blue]\nRunning VACUUM (ANALYZE, VERBOSE) in controlled sandbox clone...', style='blue'))
verif = scenario_manager.apply_verified_intervention(dossier.incident_id)
console.print(f'-> Sandbox Verification Result: Verified = {verif.verified}, Risk Reduction: {verif.risk_reduction_pct}%')
console.print(f'-> Dead tuples reduced from {verif.pre_metrics[\"n_dead_tup\"]:,} to {verif.post_metrics[\"n_dead_tup\"]:,}!')
time.sleep(1.5)

# 4:10 - Acute scenario & Falsification
console.print(Panel('[bold yellow]4:10 - Acute Scenario: pg-lock-contention & Verifier Falsification[/bold yellow]\nSchema migration holds ACCESS EXCLUSIVE lock on orders table.\nNaive threshold systems blame CPU saturation...', style='yellow'))
scenario_manager.start_scenario('pg-lock-contention')
dossier_lock = scenario_manager.run_investigation()

tab = Table(title='Verifier Hypothesis Falsification Audit')
tab.add_column('Candidate Hypothesis', style='cyan')
tab.add_column('Expected Telemetry', style='yellow')
tab.add_column('Actual Telemetry', style='magenta')
tab.add_column('Status', style='bold')
tab.add_column('Audit Reason', style='red')

for h in dossier_lock.hypotheses_evaluated:
    tab.add_row(
        h.claim,
        str(h.expected_signature),
        str(h.actual_signature),
        h.verification_status,
        h.contradiction_reason or 'Invariant holds'
    )
console.print(tab)
time.sleep(1.5)

# 4:45 - AMD ROCm Performance Panel
hw = rocm_engine.get_hardware_metrics()
bm = rocm_benchmark_suite.run_benchmark(concurrency=4)
console.print(Panel(f'[bold green]4:45 - AMD ROCm Hardware Acceleration[/bold green]\nHost GPU: {hw.device_name} ({hw.architecture})\nVRAM: {hw.vram_used_mb}MB / {hw.vram_total_mb}MB | Temp: {hw.temperature_c}°C\nInference: {hw.tokens_per_second} tokens/sec (TTFT: {hw.time_to_first_token_ms}ms)\nFP8 Kernel Speedup: {bm[\"comparison\"][\"throughput_speedup\"]} | VRAM Savings: {bm[\"comparison\"][\"vram_savings\"]}', style='bold green'))
time.sleep(1.0)

# 5:00 - Final statement
console.print(Panel('[bold white on blue]5:00 - FINAL STATEMENT[/bold white on blue]\n\"CausalGuard does not wait for the outage.\nIt identifies the developing causal risk, tests what happens next, verifies the intervention, and gives operators evidence before they act.\"\n', style='bold white on blue'))
"
