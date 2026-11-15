"""Подготовка базы знаний из размеченных данных (бывший ноутбук Data_preparation).

Вход — папка снапшота `raw/<снапшот>`:
  - реестр «Дата сет для icust.xlsx», лист `wo_links` (анкеты, экспертные сегменты, гипотезы, офферы);
  - папки кейсов `C0001/ … C0010/` с файлами «Оценка гипотез сегментации.xlsx» и «Оценка гипотез продукта.xlsx».
Выход — папка `processed/<снапшот>`: cases / segments / hypotheses / evals / issues / notes (parquet),
manifest.json (хэши исходных файлов и число строк) и validation_report.xlsx (список правок для разметчика).

Запуск: python -m icust.prepare_data <raw_dir> <processed_dir>
"""
from __future__ import annotations

import difflib
import hashlib
import json
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

# Поля анкеты: метка -> колонка
INPUT_FIELDS = {
    "А":  "product",        # название продукта / фичи
    "Б":  "groups",         # первоначальные группы потребителей
    "Б1": "job",            # потребительская задача
    "Б2": "situation",      # ситуация и условия выполнения работы
    "В":  "problem",        # гипотеза проблемы
    "В1": "losses",         # предполагаемые измеримые потери
    "Г":  "mechanism",      # механизм / функция решения
    "Д":  "outcome",        # желаемый результат потребителя
    "Д1": "effect",         # проверяемый эффект (опционально)
    "Е":  "alternatives",   # текущие альтернативы и ограничения
    "Ж":  "decision",       # решение по результатам исследования
}
OPTIONAL_FIELDS = {"Д1"}

LAT2CYR = str.maketrans("ABEKMHOPCTXaeopcx", "АВЕКМНОРСТХаеорсх")   # латиница, похожая на кириллицу, в метках

RE_CASE_ID = re.compile(r"^C\d{4}$")
RE_SEG = re.compile(r"^(C\d{4}-SEG\d{2})\.\s*(.+)$", re.S)
RE_HYP = re.compile(r"^(C\d{4}-SEG\d{2})\s*\|\s*(C\d{4}-H\d{2})\.\s*(.+)$", re.S)
RE_LABEL = re.compile(r"^\s*\{([^}]{1,3})\}\s*", re.M)

EVAL_KINDS = {"сегментац": "seg", "продукт": "hyp"}         # ключевое слово в имени файла оценки -> тип
SKIP_KINDS = ("сценари", "дизайн", "шаблон")                # известные xlsx, которые здесь не разбираются
SET_LEVEL_CRITERIA = {"seg": {9}, "hyp": set()}             # критерии уровня набора (кейса)
POST_INTERVIEW_MARK = "после проведения интервью"
VERDICTS = {"да": True, "нет": False}
MINOR_EDIT = 0.90                    # порог похожести: выше — «правка формулировки»
SHORT_COMMENT = 25                   # короче — комментарий без пояснения

RE_CONDITIONAL = re.compile(r"(соответствует|выполнен\w*)\s*,?\s*(если|при условии)", re.I)
RE_NEGATIVE = re.compile(r"^\s*не\s+(соответствует|выполнен)", re.I)
RE_POSITIVE = re.compile(r"^\s*(соответствует|выполнен)", re.I)
RE_REVISED = re.compile(r"исправлен|правк\w*\s*\{", re.I)   # «исправленн…» или «правку {Б1}»


def clean(text) -> str:
    """NFC-нормализация, обрезка пробелов, снятие внешних кавычек «…»."""
    t = unicodedata.normalize("NFC", str(text)).strip()
    if t.startswith("«") and t.rstrip(".").endswith("»"):
        t = t[1:].rstrip(".").removesuffix("»").strip()
    return t


def split_items(cell) -> list[str]:
    """Деление ячейки со списком сущностей по пустым строкам."""
    if cell is None:
        return []
    return [x.strip() for x in re.split(r"\n\s*\n", str(cell).strip()) if x.strip()]


def norm_cmp(text) -> str:
    """Нормализация только для сравнения: кавычки по краям, тире, пробелы, точка в конце."""
    t = re.sub(r"\s+", " ", clean(text)).strip()
    t = re.sub(r"[–—−]", "-", t)
    return t.lstrip("«").rstrip(" .").rstrip("»").rstrip(" .")


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def _find_row(ws, startswith: str):
    """Номер строки, где текст в колонке A начинается с заданного."""
    for r in range(1, ws.max_row + 1):
        v = ws.cell(r, 1).value
        if v and str(v).strip().lower().startswith(startswith.lower()):
            return r
    return None


def _block_columns(ws, row: int, col: int) -> list[int]:
    """Колонки, которые занимает объединённая ячейка (или одна колонка)."""
    for rng in ws.merged_cells.ranges:
        if rng.min_row <= row <= rng.max_row and rng.min_col <= col <= rng.max_col:
            return list(range(rng.min_col, rng.max_col + 1))
    return [col]


def _parse_input(case_id: str, text: str, issues: list) -> dict:
    """Разбор ячейки «Инпут» по меткам {А}, {Б}, {Б1}, …"""
    text = unicodedata.normalize("NFC", text)
    matches = list(RE_LABEL.finditer(text))
    fields = {}
    for i, m in enumerate(matches):
        label = m.group(1).translate(LAT2CYR)
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        value = text[m.end():end].strip()
        if label not in INPUT_FIELDS:
            issues.append((case_id, "input", f"неизвестная метка {{{m.group(1)}}}"))
            continue
        if label in fields:
            issues.append((case_id, "input", f"метка {{{label}}} повторяется"))
        fields[INPUT_FIELDS[label]] = value
    for label, col in INPUT_FIELDS.items():
        if not fields.get(col) and label not in OPTIONAL_FIELDS:
            issues.append((case_id, "input", f"пустое или отсутствует поле {{{label}}}"))
    return fields


def _parse_registry(registry_path: Path, issues: list):
    ws = load_workbook(registry_path)["wo_links"]
    header = [str(c.value).strip() if c.value else None for c in ws[1]]
    col = {name: i for i, name in enumerate(header) if name}
    c_id, c_input = col["ID"], col["Инпут"]
    c_seg, c_hyp, c_offer = col["Сегментация ЦА"], col["Гипотеза продукта"], col["Формулирование оффера"]

    cases, segments, hypotheses = [], [], []
    for row in ws.iter_rows(min_row=3, values_only=True):  # строка 2 — шаблоны формул
        raw_id = row[c_id]
        if raw_id is None:
            continue
        case_id = str(raw_id).strip()
        if not RE_CASE_ID.match(case_id):
            issues.append((case_id, "case", "ID не в формате C0000 (латиница, 4 цифры) - строка пропущена"))
            continue
        if not row[c_input]:
            issues.append((case_id, "case", "пустой input - строка пропущена"))
            continue
        cases.append({"case_id": case_id, **_parse_input(case_id, row[c_input], issues),
                      "offer_raw": clean(row[c_offer]) if row[c_offer] else None})
        for item in split_items(row[c_seg]):
            m = RE_SEG.match(item)
            if not m:
                issues.append((case_id, "segment", f"не распознан: {item[:60]!r}"))
                continue
            segments.append({"segment_id": m.group(1), "case_id": case_id, "text": clean(m.group(2))})
        for item in split_items(row[c_hyp]):
            m = RE_HYP.match(item)
            if not m:
                issues.append((case_id, "hypothesis", f"не распознана: {item[:60]!r}"))
                continue
            hypotheses.append({"hypothesis_id": m.group(2), "segment_id": m.group(1),
                               "case_id": case_id, "text": clean(m.group(3))})

    df_cases, df_segments, df_hypotheses = pd.DataFrame(cases), pd.DataFrame(segments), pd.DataFrame(hypotheses)
    # проверки связей
    for df, id_col in [(df_segments, "segment_id"), (df_hypotheses, "hypothesis_id")]:
        for _, r in df.iterrows():
            if not r[id_col].startswith(r["case_id"]):
                issues.append((r["case_id"], id_col, f"{r[id_col]} не относится к кейсу"))
        for dup in df.loc[df[id_col].duplicated(), id_col]:
            issues.append((dup[:5], id_col, f"дубль {dup}"))
    for _, r in df_hypotheses.iterrows():
        if r["segment_id"] not in set(df_segments["segment_id"]):
            issues.append((r["case_id"], "hypothesis", f"{r['hypothesis_id']} ссылается на несуществующий {r['segment_id']}"))
    return df_cases, df_segments, df_hypotheses


def _parse_eval(path: Path, kind: str, issues: list):
    fname = unicodedata.normalize("NFC", path.name)
    prefix = fname[:5]
    case_id = prefix.translate(str.maketrans("С", "C"))
    if prefix != case_id:
        issues.append((case_id, path.name, "в имени файла кириллическая «С» — переименовать"))
    if not RE_CASE_ID.match(case_id):
        issues.append((prefix, path.name, "имя файла не начинается с ID кейса C0000"))
    if path.parent.name != case_id:
        issues.append((case_id, path.name, f"файл лежит в папке {path.parent.name}, а не {case_id}"))

    ws = load_workbook(path).worksheets[0]
    r_id, r_head = _find_row(ws, "Идентификатор"), _find_row(ws, "Критерий")
    if not r_id or not r_head:
        issues.append((case_id, path.name, "не найдены строки «Идентификатор» / «Критерий»"))
        return [], []
    r_text = r_id + 1

    # блоки сущностей: ID в строке «Идентификатор», колонки результата/вердикта по заголовкам
    blocks = []
    for c in range(3, ws.max_column + 1):
        ent_id = ws.cell(r_id, c).value
        if not ent_id:
            continue
        ent_id = str(ent_id).strip()
        pattern = rf"^{case_id}-SEG\d{{2}}$" if kind == "seg" else rf"^{case_id}-H\d{{2}}$"
        if not re.match(pattern, ent_id):
            issues.append((case_id, path.name, f"ID {ent_id!r} не в формате {case_id}-SEG00 / {case_id}-H00 (или чужой кейс)"))
        cols = _block_columns(ws, r_id, c)
        heads = {str(ws.cell(r_head, cc).value or "").strip().lower(): cc for cc in cols}
        c_res = next((cc for h, cc in heads.items() if h.startswith("результат")), None)
        c_ver = next((cc for h, cc in heads.items() if h.startswith("выполнен")), None)
        if not c_res or not c_ver:
            issues.append((case_id, path.name, f"{ent_id}: нет колонок результата/вердикта ({get_column_letter(c)})"))
            continue
        blocks.append({"id": ent_id, "text": ws.cell(r_text, c).value, "c_res": c_res, "c_ver": c_ver})

    # критерии
    criteria = []
    for r in range(r_head + 1, ws.max_row + 1):
        title = ws.cell(r, 1).value
        if not title:
            continue
        title = unicodedata.normalize("NFC", str(title)).strip()
        m = re.match(r"^(\d+)\.\s*(.+)$", title, re.S)
        if not m:
            issues.append((case_id, path.name, f"строка {r}: критерий без номера"))
            continue
        no = int(m.group(1))
        criteria.append({"row": r, "no": no, "title": m.group(2).strip(),
                         "check": str(ws.cell(r, 2).value or "").strip(),
                         "level": "set" if no in SET_LEVEL_CRITERIA[kind] else "item",
                         "post_interview": POST_INTERVIEW_MARK in title.lower()})

    # вердикты в длинном формате
    entities, evals = [], []
    for b in blocks:
        entities.append({"entity_id": b["id"], "case_id": case_id, "kind": kind, "text_eval": b["text"]})
        for cr in criteria:
            raw = ws.cell(cr["row"], b["c_ver"]).value
            raw_s = str(raw).strip().lower() if raw is not None else ""
            verdict = VERDICTS.get(raw_s)
            if raw_s and verdict is None:
                issues.append((case_id, path.name, f"{b['id']}, критерий {cr['no']}: недопустимый вердикт {raw!r}"))
            single_item = cr["level"] == "set" and len(blocks) == 1   # критерий набора неприменим к одному сегменту
            if not raw_s and not cr["post_interview"] and not single_item:
                issues.append((case_id, path.name, f"{b['id']}, критерий {cr['no']}: пустой вердикт"))
            if raw_s and cr["post_interview"]:
                issues.append((case_id, path.name, f"{b['id']}, критерий {cr['no']}: заполнен критерий «после интервью»"))
            evals.append({"entity_id": b["id"], "case_id": case_id, "kind": kind,
                          "criterion_no": cr["no"], "criterion": cr["title"], "check": cr["check"],
                          "level": cr["level"], "post_interview": cr["post_interview"],
                          "verdict": verdict,
                          "comment": str(ws.cell(cr["row"], b["c_res"]).value or "").strip() or None})
    return entities, evals


def prepare_knowledge_base(raw_dir: str | Path, processed_dir: str | Path) -> dict:
    """Разбор размеченных данных снапшота в таблицы базы знаний. Возвращает манифест (число строк по таблицам).

    Ошибки разметки не прерывают разбор: они попадают в issues.parquet и validation_report.xlsx (лист «Ошибки»),
    замечания по содержанию — в notes.parquet и лист «Предупреждения».
    """
    raw_dir, processed_dir = Path(raw_dir), Path(processed_dir)
    issues: list = []   # (case_id, объект, проблема)
    notes: list = []    # (case_id, entity_id, criterion_no, предупреждение)

    files = sorted(p for p in raw_dir.rglob("*.xlsx") if not p.name.startswith("~$"))
    registry_path = next((p for p in files if "дата сет" in unicodedata.normalize("NFC", p.name).lower()), None)
    if registry_path is None:
        raise FileNotFoundError(f"{raw_dir}: не найден реестр «Дата сет …xlsx»")
    df_cases, df_segments, df_hypotheses = _parse_registry(registry_path, issues)

    # --- файлы оценок
    all_entities, all_evals = [], []
    for p in files:
        name = unicodedata.normalize("NFC", p.name).lower()
        kind = next((k for key, k in EVAL_KINDS.items() if key in name and "оценка" in name), None)
        if kind:
            ents, evs = _parse_eval(p, kind, issues)
            all_entities += ents
            all_evals += evs
        elif p != registry_path and not any(k in name for k in SKIP_KINDS):
            issues.append(("—", p.name, "файл не распознан (не реестр и не файл оценки) — пропущен"))
    df_eval_entities = pd.DataFrame(all_entities)
    df_eval = pd.DataFrame(all_evals)

    # --- сверка текстов в оценках с реестром
    registry = {"seg": df_segments.set_index("segment_id")["text"],
                "hyp": df_hypotheses.set_index("hypothesis_id")["text"]}
    registry_norm = {k: v.map(norm_cmp) for k, v in registry.items()}
    for _, e in df_eval_entities.iterrows():
        reg = registry_norm[e["kind"]]
        ent_id = e["entity_id"]
        if ent_id not in reg.index:
            issues.append((e["case_id"], e["kind"], f"{ent_id} есть в оценке, но нет в реестре"))
            continue
        a = norm_cmp(e["text_eval"])
        if a == reg[ent_id]:
            continue
        own = similarity(a, reg[ent_id])
        best_id, best = max(((i, similarity(a, t)) for i, t in reg.items()), key=lambda x: x[1])
        if best_id != ent_id and best > own:
            issues.append((e["case_id"], e["kind"],
                           f"{ent_id}: текст в оценке похож на {best_id} ({best:.0%}), а не на свой ({own:.0%}) — скопирован не тот текст?"))
        elif own >= MINOR_EDIT:
            issues.append((e["case_id"], e["kind"], f"{ent_id}: текст отличается от реестра незначительно ({own:.0%}) — правка формулировки"))
        else:
            issues.append((e["case_id"], e["kind"], f"{ent_id}: текст существенно отличается от реестра ({own:.0%})"))
    for kind, reg in registry.items():
        evaluated_cases = set(df_eval_entities.loc[df_eval_entities["kind"] == kind, "case_id"])
        evaluated_ids = set(df_eval_entities.loc[df_eval_entities["kind"] == kind, "entity_id"])
        for ent_id in reg.index:
            if ent_id[:5] in evaluated_cases and ent_id not in evaluated_ids:
                issues.append((ent_id[:5], kind, f"{ent_id} есть в реестре, но нет в оценке"))
        for case_id in sorted({i[:5] for i in reg.index} - evaluated_cases):
            issues.append((case_id, kind, "нет файла оценки"))

    # --- критерий уровня набора: одинаковый вердикт во всех блоках кейса
    for (case_id, no), g in df_eval[df_eval["level"] == "set"].groupby(["case_id", "criterion_no"]):
        if g["verdict"].nunique(dropna=False) > 1:
            issues.append((case_id, "seg", f"критерий {no} (уровень набора): разные вердикты в блоках"))
    # --- одинаковый состав критериев во всех файлах одного типа
    for kind, g in df_eval.groupby("kind"):
        sets = {c: tuple(sorted(set(zip(x["criterion_no"], x["criterion"])))) for c, x in g.groupby("case_id")}
        first_case, first = next(iter(sets.items()))
        for case_id, s in sets.items():
            if s != first:
                issues.append((case_id, kind, f"состав критериев отличается от {first_case}"))
    # --- содержание комментариев
    for _, r in df_eval[df_eval["verdict"].notna()].iterrows():
        c = r["comment"] or ""
        key = (r["case_id"], r["entity_id"], r["criterion_no"])
        if r["verdict"] and RE_NEGATIVE.match(c):
            issues.append((r["case_id"], r["entity_id"], f"критерий {r['criterion_no']}: вердикт «Да», а комментарий «Не соответствует»"))
        elif not r["verdict"] and RE_POSITIVE.match(c):
            issues.append((r["case_id"], r["entity_id"], f"критерий {r['criterion_no']}: вердикт «Нет», а комментарий «Соответствует»"))
        if r["verdict"] and RE_CONDITIONAL.search(c):
            notes.append((*key, "условный вердикт «Да» (…если…)"))
        if RE_REVISED.search(c):
            notes.append((*key, "комментарий ссылается на исправленную версию"))
        if len(c) < SHORT_COMMENT:
            notes.append((*key, f"комментарий без пояснения: {c!r}"))

    df_issues = pd.DataFrame(issues, columns=["case_id", "object", "issue"]).drop_duplicates()
    df_notes = pd.DataFrame(notes, columns=["case_id", "entity_id", "criterion_no", "note"]).drop_duplicates()

    # --- выгрузка
    processed_dir.mkdir(parents=True, exist_ok=True)
    tables = {"cases": df_cases, "segments": df_segments, "hypotheses": df_hypotheses,
              "evals": df_eval, "issues": df_issues, "notes": df_notes}
    for name, df in tables.items():
        df.to_parquet(processed_dir / f"{name}.parquet", index=False)
    manifest = {
        "snapshot": raw_dir.name,
        "parsed_at": datetime.now().isoformat(timespec="seconds"),
        "source_files": {str(p.relative_to(raw_dir)): hashlib.sha256(p.read_bytes()).hexdigest()[:16] for p in files},
        "counts": {name: len(df) for name, df in tables.items()},
    }
    (processed_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    with pd.ExcelWriter(processed_dir / "validation_report.xlsx") as xw:
        df_issues.to_excel(xw, sheet_name="Ошибки", index=False)
        df_notes.to_excel(xw, sheet_name="Предупреждения", index=False)
    return manifest


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("Использование: python -m icust.prepare_data <raw_dir> <processed_dir>")
    m = prepare_knowledge_base(sys.argv[1], sys.argv[2])
    print(json.dumps(m["counts"], ensure_ascii=False))
    if m["counts"]["issues"]:
        print(f"Ошибок разметки: {m['counts']['issues']} — см. validation_report.xlsx")
