"""iCust: модуль генерации дизайна CustDev-исследования.

Порядок: load_knowledge_base() один раз при старте, затем этапы
generate_segments -> generate_value_hypotheses -> generate_scenarios -> generate_offers -> build_design.
"""
__version__ = "1.0.0"

from .knowledge_base import KnowledgeBase, case_as_input, load_knowledge_base  # noqa: E402
from .stages import (build_design, generate_offers, generate_scenarios, generate_segments,  # noqa: E402
                     generate_value_hypotheses)


def prepare_knowledge_base(raw_dir, processed_dir):
    """Подготовка базы знаний из размеченных данных — см. icust.prepare_data."""
    from .prepare_data import prepare_knowledge_base as _prepare
    return _prepare(raw_dir, processed_dir)


__all__ = ["KnowledgeBase", "load_knowledge_base", "case_as_input", "prepare_knowledge_base",
           "generate_segments", "generate_value_hypotheses", "generate_scenarios", "generate_offers", "build_design"]
