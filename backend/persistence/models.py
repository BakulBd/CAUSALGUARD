"""ORM models for CausalGuard persistence."""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import JSON, Float, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class DossierRecord(Base):
    __tablename__ = "dossiers"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    risk_type: Mapped[str] = mapped_column(String(64), index=True)
    mode: Mapped[str] = mapped_column(String(32), index=True)
    severity: Mapped[str] = mapped_column(String(32), index=True)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    scenario: Mapped[str] = mapped_column(String(64), default="unknown", index=True)
    source_mode: Mapped[str] = mapped_column(String(32), default="simulated")
    verified: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(Float, default=time.time, index=True)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time)

    __table_args__ = (Index("ix_dossiers_risk_created", "risk_type", "created_at"),)


class ScenarioEventRecord(Base):
    __tablename__ = "scenario_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scenario: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(32))
    source_mode: Mapped[str] = mapped_column(String(32), default="simulated")
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[float] = mapped_column(Float, default=time.time, index=True)


class ObservationRecord(Base):
    __tablename__ = "observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    obs_key: Mapped[str] = mapped_column(String(128), index=True)
    dossier_id: Mapped[str] = mapped_column(String(128), index=True)
    category: Mapped[str] = mapped_column(String(32), index=True)
    source: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(128))
    current_value: Mapped[float] = mapped_column(Float, default=0.0)
    baseline_value: Mapped[float] = mapped_column(Float, default=0.0)
    trend: Mapped[str] = mapped_column(String(32), default="stable")
    z_score: Mapped[float] = mapped_column(Float, default=0.0)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[float] = mapped_column(Float, default=time.time, index=True)


class InterventionRecord(Base):
    __tablename__ = "interventions"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    dossier_id: Mapped[str] = mapped_column(String(128), index=True)
    action_name: Mapped[str] = mapped_column(String(128))
    environment: Mapped[str] = mapped_column(String(64), default="CONTROLLED_SANDBOX")
    verified: Mapped[int] = mapped_column(Integer, default=0)
    risk_reduction_pct: Mapped[float] = mapped_column(Float, default=0.0)
    notes: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[float] = mapped_column(Float, default=time.time, index=True)
