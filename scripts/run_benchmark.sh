#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

echo "=========================================================="
echo "      CausalGuard RCAEval & Baseline Benchmark Runner     "
echo "=========================================================="

source .venv/bin/activate
PYTHONPATH=. .venv/bin/python -c "
from backend.evaluation.benchmarks.rcaeval_runner import rcaeval_evaluator
from rich.console import Console
from rich.table import Table

console = Console()
results = rcaeval_evaluator.evaluate_all()

table = Table(title='RCAEval Benchmark Comparison (735 Incident Cases)')
table.add_column('Method / Architecture', style='cyan', no_wrap=True)
table.add_column('Detection Acc %', style='magenta')
table.add_column('Lead Time (min)', style='green')
table.add_column('False Pos %', style='red')
table.add_column('Localization %', style='yellow')
table.add_column('Verification Prec %', style='bold blue')
table.add_column('Intervention %', style='bold green')

for name, m in results['baselines'].items():
    table.add_row(
        name,
        str(m['detection_accuracy']),
        str(m['lead_time_minutes']),
        str(m['false_positive_rate']),
        str(m['causal_localization_top1']),
        str(m['verification_precision']),
        str(m['intervention_success'])
    )

console.print(table)
console.print('\n[bold green]Key Takeaway:[/bold green]', results['summary_takeaway'])
"
