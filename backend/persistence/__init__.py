"""Async persistence layer (SQLAlchemy 2.0)."""

from backend.persistence.database import Database, get_database
from backend.persistence.repository import DossierRepository

__all__ = ["Database", "DossierRepository", "get_database"]
