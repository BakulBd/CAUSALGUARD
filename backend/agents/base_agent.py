"""
Base Agent class for CausalGuard multi-agent pipeline.
Tracks execution duration, step history, and telemetry evidence.
"""

import time

from backend.models.schema import AgentTraceStep


class BaseAgent:
    def __init__(self, name: str, role: str):
        self.name = name
        self.role = role
        self.history: list[AgentTraceStep] = []

    def record_step(
        self,
        step_type: str,
        input_summary: str,
        output_summary: str,
        tool_calls: list[str],
        duration_ms: float,
    ) -> AgentTraceStep:
        step = AgentTraceStep(
            agent_name=self.name,
            step_type=step_type,
            input_summary=input_summary,
            output_summary=output_summary,
            tool_calls=tool_calls,
            duration_ms=round(duration_ms, 2),
            timestamp=time.time(),
        )
        self.history.append(step)
        return step
