"""RCAEval offline benchmark + AMD ROCm optimisation benchmark."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from backend.evaluation.benchmarks.rcaeval_runner import rcaeval_evaluator
from backend.rocm.benchmarks.benchmark_engine import rocm_benchmark_suite

router = APIRouter(prefix="/benchmarks", tags=["benchmarks"])


@router.get("")
def benchmarks() -> dict[str, Any]:
    """RCAEval benchmark results across baselines and ablations."""
    return rcaeval_evaluator.evaluate_all()


@router.get("/rocm")
def rocm_benchmarks(concurrency: int = Query(4, ge=1, le=64)) -> dict[str, Any]:
    return rocm_benchmark_suite.run_benchmark(concurrency=concurrency)
