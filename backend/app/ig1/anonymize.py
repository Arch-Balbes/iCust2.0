"""Шаг 2 — обезличивание перед LLM: локальный NER Natasha, заменяются ТОЛЬКО имена людей (решение 13.11.2026).

Организации, места и косвенные признаки не трогаем — они могут быть содержательными для исследования
(IG1_PIPELINE.md, шаг 2). LLM на этом шаге не используется.
"""
from functools import lru_cache

NAME_TAG = "[ИМЯ]"


@lru_cache(maxsize=1)
def _pipeline():  # type: ignore[no-untyped-def]
    from natasha import NewsEmbedding, NewsNERTagger, Segmenter

    return Segmenter(), NewsNERTagger(NewsEmbedding())


def anonymize_names(text: str) -> str:
    """Заменяет упоминания людей (NER-тип PER) на [ИМЯ]."""
    from natasha import Doc

    if not text.strip():
        return text
    segmenter, tagger = _pipeline()
    doc = Doc(text)
    doc.segment(segmenter)
    doc.tag_ner(tagger)
    out, pos = [], 0
    for span in doc.spans:
        if span.type != "PER":
            continue
        out.append(text[pos:span.start])
        out.append(NAME_TAG)
        pos = span.stop
    out.append(text[pos:])
    return "".join(out)
