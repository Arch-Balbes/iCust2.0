"""Общие функции: поля анкеты, контекст для промпта, нормализация текста, блок повторной генерации."""
from __future__ import annotations

import re
import unicodedata

FIELDS = [   # колонка -> (метка, название) в порядке анкеты
    ("product",      "А",  "Название продукта / фичи"),
    ("groups",       "Б",  "Первоначальные группы потенциальных потребителей"),
    ("job",          "Б1", "Потребительская задача"),
    ("situation",    "Б2", "Ситуация и условия выполнения работы"),
    ("problem",      "В",  "Гипотеза проблемы"),
    ("losses",       "В1", "Предполагаемые измеримые потери"),
    ("mechanism",    "Г",  "Механизм / функция предлагаемого решения"),
    ("outcome",      "Д",  "Желаемый результат потребителя"),
    ("effect",       "Д1", "Проверяемый эффект продуктового решения"),
    ("alternatives", "Е",  "Текущие альтернативы и ограничения"),
    ("decision",     "Ж",  "Решение по результатам исследования"),
]
FIELD_COLS = [c for c, _, _ in FIELDS]

_FIELD_HEADERS = {t.lower() for _, _, t in FIELDS} | {
    "ситуация и условия выполнения задачи", "механизм / функция решения", "проверяемый эффект"}


def strip_field_header(value) -> str:
    """Убирает первую строку значения, если это повтор заголовка поля."""
    lines = str(value).strip().split("\n")
    first = lines[0].lower().replace("(опционально)", "").strip(" :\t")
    if len(lines) > 1 and first in _FIELD_HEADERS:
        lines = lines[1:]
    return "\n".join(lines).strip()


def format_context(case_row, exclude=()) -> str:
    """Анкета в виде строк «{метка} Название: значение» (контекст для промпта и ключ retrieval)."""
    lines = []
    for col, label, title in FIELDS:
        if col in exclude:
            continue
        value = case_row.get(col)
        if value is not None and str(value).strip():
            lines.append(f"{{{label}}} {title}: {strip_field_header(value)}")
    return "\n".join(lines)


def product_to_row(product: dict) -> dict:
    """Анкета запроса (groups — список) -> строка в формате кейса базы: группы по одной на строку."""
    row = {c: product.get(c) for c in FIELD_COLS}
    groups = product.get("groups") or []
    row["groups"] = "\n".join(str(g).strip() for g in groups if str(g).strip())
    return row


def normalize_text(text) -> str:
    t = unicodedata.normalize("NFC", str(text or "")).lower().replace("ё", "е")
    t = re.sub(r"[«»\"“”„']", "", t)
    t = re.sub(r"[–—−]", "-", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip(" .")


def clean_segment(s) -> str:
    """Чистка предложения из ответа модели: маркеры списка, номер, кавычки по краям."""
    s = re.sub(r"^[>\s]+", "", str(s).strip())
    s = re.sub(r"^\d+[.)]\s*", "", s)
    return s.strip().strip('"«»').strip()


def add_interview_block(user_text: str, initial_generation: bool, interview_summary: dict | None) -> str:
    """Блок результатов анализа интервью — только для повторной генерации (initial_generation=False)."""
    if initial_generation:
        return user_text
    if not interview_summary:
        raise ValueError("initial_generation=False требует interview_summary")
    lines = "\n".join(f"{k}: {v}" for k, v in interview_summary.items())
    return (f"{user_text}\n\n---\n\nРезультаты анализа проведённых интервью:\n{lines}\n\n"
            "Учитывай их при генерации: уточняй формулировки по подтверждённым данным и не противоречь им.")


def yes_no(v) -> str:
    return "Да" if v else "Нет"


def crit_block(rows) -> str:
    """Критерии оценщика: номер, название, «Что проверяем»."""
    return "\n\n".join(f"Критерий {r.criterion_no}. {r.criterion}\nЧто проверяем:\n{r.check}" for r in rows.itertuples())


def verdict_obj() -> dict:
    return {"type": "object",
            "properties": {"criterion_no": {"type": "integer"},
                           "reason": {"type": "string"},
                           "verdict": {"type": "boolean"}},
            "required": ["criterion_no", "reason", "verdict"],
            "additionalProperties": False}
