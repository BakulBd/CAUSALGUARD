#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

echo "=========================================================="
echo "          AMD ROCm GPU Benchmark & Telemetry              "
echo "=========================================================="

source .venv/bin/activate
PYTHONPATH=. .venv/bin/python -c "
from backend.rocm.serving.rocm_engine import rocm_engine
from backend.rocm.benchmarks.benchmark_engine import rocm_benchmark_suite
from rich.console import Console
from rich.table import Table

console = Console()
hw = rocm_engine.get_hardware_metrics()

console.print(f'[bold cyan]Discovered Device:[/bold cyan] {hw.device_name}')
console.print(f'[bold cyan]Architecture:[/bold cyan] {hw.architecture}')
console.print(f'[bold cyan]KFD Active:[/bold cyan] {hw.kfd_available}')
console.print(f'[bold cyan]VRAM Used:[/bold cyan] {hw.vram_used_mb} MB / {hw.vram_total_mb} MB')
console.print(f'[bold cyan]GPU Temperature:[/bold cyan] {hw.temperature_c} °C\n')

bm = rocm_benchmark_suite.run_benchmark(concurrency=4)

table = Table(title='AMD ROCm Optimization Comparison')
table.add_column('Runtime Configuration', style='cyan')
table.add_column('Precision', style='magenta')
table.add_column('Tokens / Sec', style='green')
table.add_column('TTFT (ms)', style='yellow')
table.add_column('VRAM (MB)', style='red')
table.add_column('Queries / Sec', style='bold blue')
table.add_column('Diagnostic Acc %', style='bold green')

for r in bm['results']:
    table.add_row(
        r['config_name'],
        r['precision'],
        str(r['tokens_per_second']),
        str(r['time_to_first_token_ms']),
        str(r['vram_used_mb']),
        str(r['throughput_queries_per_sec']),
        str(r['diagnostic_accuracy_pct'])
    )

console.print(table)
console.print(f'\n[bold green]Throughput Speedup:[/bold green] {bm[\"comparison\"][\"throughput_speedup\"]}')
console.print(f'[bold green]TTFT Latency Reduction:[/bold green] {bm[\"comparison\"][\"ttft_reduction_pct\"]}')
console.print(f'[bold green]VRAM Memory Savings:[/bold green] {bm[\"comparison\"][\"vram_savings\"]}')
"
