"""База знаний: размеченные кейсы, эмбеддинги, retrieval, фильтр утечки, шаблоны и фиксированные примеры.

Загружается один раз при старте сервиса (`load_knowledge_base`) и передаётся в функции этапов.
Если данные на стороне сервиса будут храниться иначе (хранилище, БД) — подменяется только эта загрузка:
она должна вернуть тот же `KnowledgeBase`.
"""
from __future__ import annotations

import difflib
import html
import logging
import re
import threading
import time
import unicodedata
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import load_workbook

from . import config
from .common import FIELD_COLS, format_context, normalize_text, strip_field_header

log = logging.getLogger(__name__)

# ---------------------------------------------------------------- шаблон сценария SCORE/JTBD
GENERATED_ROWS = {4, 40}          # строки шаблона, которые модель пишет целиком: фильтр-вопросы и портрет
TEMPLATE_NOTE = re.compile(r"\s*\(гипотеза работы \{Б1\}\)\s*")   # служебная пометка шаблона (строка 5)
SCENARIO_TEMPLATE_GLOB = "*SCORE*JTBD*.xlsx"                      # шаблон лежит в корне папки снапшота

# ---------------------------------------------------------------- раздел 1 дизайна
DESIGN_HEADINGS = {"problem_and_losses": "Проблема и потери",
                   "current_solutions": "Текущие способы решения",
                   "desired_outcome_and_effect": "Желаемый результат и измеримый эффект"}

# разрешённые домены для поля url рекомендаций по каналам — корневые домены из экспертных офферов базы
RE_DOMAIN = re.compile(r"\b((?:[a-z0-9-]+\.)+(?:com|ru|me|org|io|net|tv))\b", re.I)


def resolve_device(device: str = "auto") -> str:
    """auto -> cuda, затем mps, затем cpu."""
    if device != "auto":
        return device
    import torch
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _nfc(name: str) -> str:
    return unicodedata.normalize("NFC", name)


def _files(folder: Path, suffix: str, keyword: str) -> list[Path]:
    """Файлы папки (без вложенных) с расширением suffix, в имени которых есть keyword (сравнение в NFC)."""
    return [p for p in folder.glob(f"*{suffix}")
            if keyword in _nfc(p.name).lower() and not p.name.startswith("~$")]


def _one(files: list[Path], what: str) -> Path:
    if len(files) != 1:
        raise FileNotFoundError(f"{what}: найдено файлов {len(files)}: {[p.name for p in files]}")
    return files[0]


def _cell(ws, r, c):
    """Значение ячейки с учётом объединённых диапазонов."""
    v = ws.cell(r, c).value
    if v is None:
        for rng in ws.merged_cells.ranges:
            if rng.min_row <= r <= rng.max_row and rng.min_col <= c <= rng.max_col:
                return ws.cell(rng.min_row, rng.min_col).value
    return v


def _clean(v):
    return None if v is None else str(v).strip() or None


def read_scenario_sheet(ws) -> pd.DataFrame:
    """Строки 4–40 листа сценария: раздел, тема, вопрос, подсказка."""
    return pd.DataFrame([{"row_no": r, "section": _clean(_cell(ws, r, 1)), "topic": _clean(_cell(ws, r, 2)),
                          "question": _clean(ws.cell(r, 3).value), "hint": _clean(_cell(ws, r, 4))}
                         for r in range(4, 41)])


def load_example_scenario(raw_dir: Path, case_id: str) -> dict[str, pd.DataFrame]:
    """Эталонные сценарии кейса: {segment_id: DataFrame строк 4–40}; ID сегмента — в первой строке листа."""
    wb = load_workbook(_one(_files(raw_dir / case_id, ".xlsx", "ценари"), f"{case_id}: сценарий"))
    out = {}
    for ws in wb.worksheets:
        head = " ".join(str(c.value) for c in ws[1] if c.value)
        m = re.search(r"C\d{4}-SEG\d{2}", head)
        if not m:
            raise ValueError(f"{case_id}, лист {ws.title}: не найден ID сегмента в первой строке")
        out[m.group(0)] = read_scenario_sheet(ws)
    return out


def docx_paragraphs(path: Path) -> list[str]:
    """Непустые абзацы docx по порядку (без зависимости от python-docx)."""
    xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8")
    paras = ["".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p)) for p in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S)]
    return [html.unescape(p).strip() for p in paras if p.strip()]


def load_design_example(raw_dir: Path, case_id: str) -> dict[str, str]:
    """Раздел 1 экспертного дизайна: текст абзаца после каждого из трёх подзаголовков."""
    paras = docx_paragraphs(_one(_files(raw_dir / case_id, ".docx", "дизайн"), f"{case_id}: дизайн"))
    out = {}
    for field, head in DESIGN_HEADINGS.items():
        if head not in paras:
            raise ValueError(f"{case_id}: в дизайне нет подзаголовка «{head}»")
        out[field] = paras[paras.index(head) + 1]
    return out


class KnowledgeBase:
    """Таблицы базы, эмбеддинги, модели retrieval, шаблон сценария и фиксированные примеры."""

    def __init__(self, processed_dir: Path, raw_dir: Path, device: str = "auto"):
        from sentence_transformers import CrossEncoder, SentenceTransformer

        t0 = time.time()
        self.processed_dir, self.raw_dir = Path(processed_dir), Path(raw_dir)
        self.device = resolve_device(device)
        self.cache: dict = {}            # промпты этапов, собранные из критериев базы (заполняют модули этапов)

        # ---- таблицы (prepare_knowledge_base)
        self.cases = pd.read_parquet(self.processed_dir / "cases.parquet")
        self.segments = pd.read_parquet(self.processed_dir / "segments.parquet")
        self.hypotheses = pd.read_parquet(self.processed_dir / "hypotheses.parquet")
        self.evals = pd.read_parquet(self.processed_dir / "evals.parquet")

        # валидность экспертных сущностей: все критерии уровня элемента = Да
        def _valid(kind):
            it = self.evals[(self.evals["kind"] == kind) & (self.evals["level"] == "item") & (~self.evals["post_interview"])]
            return it.groupby("entity_id")["verdict"].agg(lambda v: bool(v.notna().all() and v.all()))
        self.seg_base = self.segments.assign(
            valid=self.segments["segment_id"].map(_valid("seg")).fillna(False).astype(bool))
        self.hyp_base = self.hypotheses.assign(
            valid=self.hypotheses["hypothesis_id"].map(_valid("hyp")).fillna(False).astype(bool))

        self.case_base = self.cases.assign(
            context_prompt=self.cases.apply(lambda r: format_context(r), axis=1),
            retrieval_key=self.cases.apply(lambda r: format_context(r, exclude=("product",)), axis=1))
        self.case_ids = self.case_base["case_id"].tolist()
        self.case_keys = self.case_base["retrieval_key"].tolist()
        self.ctx_by_case = dict(zip(self.case_ids, self.case_base["context_prompt"]))

        # ---- модели retrieval и эмбеддинги базы
        self._emb_lock = threading.Lock()
        self._emb_cache: dict[str, np.ndarray] = {}
        self.embedder = SentenceTransformer(config.EMB_MODEL_NAME, device=self.device)
        self.embedder.max_seq_length = 2048
        self.reranker = CrossEncoder(config.RERANK_MODEL_NAME, device=self.device, max_length=2048)
        self.case_emb = self.embed(self.case_keys)
        self.seg_emb = dict(zip(self.seg_base["segment_id"], self.embed(self.seg_base["text"].tolist())))

        # ---- шаблон сценария и фиксированные примеры этапов 3–5
        tpl = _one([p for p in self.raw_dir.glob(SCENARIO_TEMPLATE_GLOB) if not p.name.startswith("~$")],
                   f"{self.raw_dir}: шаблон {SCENARIO_TEMPLATE_GLOB}")
        self.scen_template = read_scenario_sheet(load_workbook(tpl).worksheets[0])
        self.scen_template["slots"] = self.scen_template["question"].fillna("").str.contains("<")
        self.scen_template["generated"] = self.scen_template["row_no"].isin(GENERATED_ROWS)
        self.rows_to_fill = self.scen_template.loc[self.scen_template["slots"] | self.scen_template["generated"],
                                                   "row_no"].tolist()
        self.scen_examples = {c: load_example_scenario(self.raw_dir, c) for c in config.SCENARIO_EXAMPLE.values()}
        self.design_examples = {c: load_design_example(self.raw_dir, c) for c in config.DESIGN_EXAMPLE.values()}
        self.allowed_domains = sorted({d.lower() for t in self.cases["offer_raw"].dropna() for d in RE_DOMAIN.findall(t)})
        for c in config.OFFER_EXAMPLE.values():
            offer_example_text(self, c)          # проверка: пример оффера есть и размечен заголовками
        log.info("База: кейсов %d, сегментов %d (валидных %d), гипотез %d (валидных %d) | %s | %.1f с",
                 len(self.case_ids), len(self.seg_base), int(self.seg_base["valid"].sum()),
                 len(self.hyp_base), int(self.hyp_base["valid"].sum()), self.device, time.time() - t0)

    def embed(self, texts: list[str]) -> np.ndarray:
        """Нормированные эмбеддинги bge-m3; кэш в памяти по тексту."""
        with self._emb_lock:
            missing = [t for t in dict.fromkeys(texts) if t not in self._emb_cache]
            if missing:
                vecs = self.embedder.encode(missing, batch_size=8, normalize_embeddings=True, show_progress_bar=False)
                for t, v in zip(missing, vecs):
                    self._emb_cache[t] = v.astype(np.float32)
            return np.vstack([self._emb_cache[t] for t in texts])


def load_knowledge_base(processed_dir: str | Path | None = None, raw_dir: str | Path | None = None,
                        device: str | None = None) -> KnowledgeBase:
    """Загрузка базы знаний. По умолчанию пути и устройство — из ICUST_PROCESSED_DIR, ICUST_RAW_DIR, ICUST_DEVICE."""
    processed_dir = processed_dir or config.PROCESSED_DIR
    raw_dir = raw_dir or config.RAW_DIR
    if not processed_dir or not raw_dir:
        raise ValueError("Укажите processed_dir и raw_dir или переменные ICUST_PROCESSED_DIR и ICUST_RAW_DIR")
    return KnowledgeBase(Path(processed_dir), Path(raw_dir), device or config.DEVICE)


def offer_example_text(kb: KnowledgeBase, case_id: str) -> str:
    """Экспертный оффер кейса из реестра (колонка «Формулирование оффера»), начиная с первого сегмента."""
    raw = kb.cases.set_index("case_id").loc[case_id, "offer_raw"]
    i = (raw or "").find("# Сегмент")
    if i < 0:
        raise ValueError(f"{case_id}: в оффере реестра нет заголовка «# Сегмент»")
    return raw[i:].strip()


# ---------------------------------------------------------------- фильтр утечки
def find_leak_case(row: dict, kb: KnowledgeBase, threshold: float = config.LEAK_THRESHOLD) -> str | None:
    """ID кейса базы, совпадающего с анкетой (полное совпадение после нормализации или близость ≥ порога), или None.

    Нужен для демонстрации на кейсах базы: совпавший кейс исключается из примеров, фиксированный пример
    заменяется резервным. Для новых анкет обычно возвращает None.
    """
    q_fields = [normalize_text(strip_field_header(row.get(c) or "")) for c in FIELD_COLS]
    q_text = " | ".join(q_fields)
    best_id, best_sim = None, 0.0
    for r in kb.case_base.itertuples():
        b_fields = [normalize_text(strip_field_header(getattr(r, c) or "")) for c in FIELD_COLS]
        if b_fields == q_fields:
            return r.case_id
        sm = difflib.SequenceMatcher(None, q_text, " | ".join(b_fields), autojunk=False)
        if sm.real_quick_ratio() < max(threshold, best_sim) or sm.quick_ratio() < max(threshold, best_sim):
            continue      # верхняя оценка близости ниже порога — точное сравнение не нужно
        sim = sm.ratio()
        if sim > best_sim:
            best_id, best_sim = r.case_id, sim
    return best_id if best_sim >= threshold else None


# ---------------------------------------------------------------- retrieval: two-stage + per-case-2
def rank_cases(q_key: str, kb: KnowledgeBase, exclude=()) -> list[str]:
    """Кейсы базы по убыванию релевантности (bge-m3 -> bge-reranker-v2-m3 по top-6)."""
    cand = [i for i, c in enumerate(kb.case_ids) if c not in set(exclude)]
    dense = kb.case_emb[cand] @ kb.embed([q_key])[0]
    top = np.argsort(-dense)[:config.RERANK_TOP_N]
    rr = kb.reranker.predict([(q_key, kb.case_keys[cand[i]]) for i in top], show_progress_bar=False)
    scores = dense - dense.max() - 1.0
    scores[top] = rr - rr.min() + 1.0
    out = pd.DataFrame({"case_id": [kb.case_ids[i] for i in cand], "score": scores})
    return out.sort_values("score", ascending=False, ignore_index=True)["case_id"].tolist()


def _pool(q_key: str, case_ids: list[str], kb: KnowledgeBase) -> pd.DataFrame:
    q = kb.embed([q_key])[0]
    case_rel = dict(zip(case_ids, kb.case_emb[[kb.case_ids.index(c) for c in case_ids]] @ q))
    pool = kb.seg_base[kb.seg_base["case_id"].isin(case_ids) & kb.seg_base["valid"]].copy()
    pool["rel"] = pool["case_id"].map(case_rel)
    pool["text_rel"] = [float(kb.seg_emb[s] @ q) for s in pool["segment_id"]]
    return pool


def _mmr(pool: pd.DataFrame, k: int, kb: KnowledgeBase, lam: float = config.MMR_LAMBDA) -> list[str]:
    cand = pool.sort_values(["rel", "text_rel"], ascending=False)["segment_id"].tolist()
    rel = dict(zip(pool["segment_id"], pool["rel"]))
    chosen = []
    while cand and len(chosen) < k:
        def gain(s):
            sim = max((float(kb.seg_emb[s] @ kb.seg_emb[c]) for c in chosen), default=0.0)
            return lam * rel[s] - (1 - lam) * sim
        best = max(cand, key=gain)
        chosen.append(best)
        cand.remove(best)
    return chosen


def _select_per_case_2(q_key: str, ranked: list[str], kb: KnowledgeBase, k: int = config.K_EXAMPLES,
                       per_case: int = 2) -> list[str]:
    ids = []
    for c in ranked:
        if len(ids) >= k:
            break
        ids += _mmr(_pool(q_key, [c], kb), min(per_case, k - len(ids)), kb)
    return ids


def select_examples(q_key: str, kb: KnowledgeBase, exclude=()) -> list[str]:
    """ID экспертных сегментов-примеров: two-stage + per-case-2, K = 4, в порядке релевантности кейсов."""
    ranked = rank_cases(q_key, kb, exclude=exclude)
    ids = _select_per_case_2(q_key, ranked, kb)
    rank = {c: i for i, c in enumerate(ranked)}
    return sorted(ids, key=lambda s: (rank[s[:5]], s))


# ---------------------------------------------------------------- фильтр дублей (dedupe=True)
def is_duplicate(text: str, taken_texts: list[str], kb: KnowledgeBase,
                 threshold: float = config.DEDUPE_THRESHOLD) -> bool:
    """Дубль: совпадение после нормализации или косинус bge-m3 ≥ порога с уже взятым."""
    if not taken_texts:
        return False
    n = normalize_text(text)
    if any(n == normalize_text(t) for t in taken_texts):
        return True
    e = kb.embed([text] + list(taken_texts))
    return bool((e[1:] @ e[0]).max() >= threshold)


def case_as_input(case_id: str, kb: KnowledgeBase) -> dict:
    """Анкета кейса базы в формате запроса (для примеров и проверок; groups — одним элементом)."""
    r = kb.cases.set_index("case_id").loc[case_id]
    return {**{c: (None if pd.isna(r[c]) else r[c]) for c in FIELD_COLS if c != "groups"}, "groups": [r["groups"]]}
