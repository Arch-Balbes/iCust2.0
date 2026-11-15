"""Функции этапов модуля."""
from .design import build_design
from .hypotheses import generate_value_hypotheses
from .offers import generate_offers
from .scenarios import generate_scenarios
from .segments import generate_segments

__all__ = ["generate_segments", "generate_value_hypotheses", "generate_scenarios", "generate_offers", "build_design"]
