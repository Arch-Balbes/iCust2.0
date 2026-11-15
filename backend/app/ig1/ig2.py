"""ИГ2 — статус компонентов и гипотез по меткам пар (IG1_PIPELINE.md, «Что получает ИГ2»; решения 05.11,
10.11, 12.11.2026). Перенесено из iCust/scripts/evaluate_ig2_rules.py с атрибутом subject из шага 4.

Вердикт респондент × компонент:
 1) личный опыт важнее чужого: при личных S/C чужой опыт у этого респондента не учитывается; только чужой —
    засчитывается с весом 0,5 (не больше 0,5 на респондента); subject=unknown голоса не даёт;
 2) только S → supports, только C → contradicts;
 3) S и C в разных репликах → побеждает последняя по turn_index;
 4) S и C в последней реплике одновременно → mixed: поддержка при quantifier=occurrence, иначе не учитывается.
Статус: confirmed при k ≥ 3c и k ≥ 5; refuted при c ≥ 3k и c ≥ 5; insufficient — тему затронули (S/C/RI);
not_tested — не затронул никто. X % = confirmed / (компоненты − not_tested); все not_tested → None.
"""
from dataclasses import dataclass, field
from typing import Literal

THIRD_PARTY_WEIGHT = 0.5
MIN_VOTES = 5
RATIO = 3

Verdict = Literal["supports", "contradicts", "mixed", "no_evidence", "not_tested"]


@dataclass(frozen=True)
class Evidence:
    """Одна пара S/C/RI: утверждение респондента о компоненте."""
    respondent: str
    label: str  # S | C | RI
    subject: str  # personal | third_party | unknown
    turn_index: int
    claim_id: str = ""
    quote: str = ""


@dataclass
class ComponentResult:
    status: str
    n: int
    m: int
    k: float
    c: float
    mixed: int
    third_party_only: int
    ri_only: int
    verdicts: dict[str, tuple[Verdict, float]] = field(default_factory=dict)


def respondent_verdict(evidence: list[Evidence]) -> tuple[Verdict, float]:
    decisive = [e for e in evidence if e.label in ("S", "C")]
    votes, weight = [e for e in decisive if e.subject == "personal"], 1.0
    if not votes:
        votes, weight = [e for e in decisive if e.subject == "third_party"], THIRD_PARTY_WEIGHT
    if not votes:
        return ("no_evidence" if any(e.label == "RI" for e in evidence) else "not_tested"), 0.0
    labels = {e.label for e in votes}
    if len(labels) == 1:
        return ("supports" if labels.pop() == "S" else "contradicts"), weight
    last_turn = max(e.turn_index for e in votes)
    last = {e.label for e in votes if e.turn_index == last_turn}
    if len(last) == 2:
        return "mixed", weight
    return ("supports" if last.pop() == "S" else "contradicts"), weight


def component_status(by_respondent: dict[str, list[Evidence]], respondents: list[str], quantifier: str) -> ComponentResult:
    verdicts = {r: respondent_verdict(by_respondent.get(r, [])) for r in respondents}
    mixed_counts = quantifier == "occurrence"
    vw = list(verdicts.values())
    k = sum(w for v, w in vw if v == "supports" or (v == "mixed" and mixed_counts))
    c = sum(w for v, w in vw if v == "contradicts")
    m = sum(v in ("supports", "contradicts", "mixed") for v, _ in vw)
    ri = sum(v == "no_evidence" for v, _ in vw)
    if k >= RATIO * c and k >= MIN_VOTES:
        status = "confirmed"
    elif c >= RATIO * k and c >= MIN_VOTES:
        status = "refuted"
    elif m > 0 or ri > 0:
        status = "insufficient"
    else:
        status = "not_tested"
    return ComponentResult(
        status=status, n=len(respondents), m=m, k=k, c=c, mixed=sum(v == "mixed" for v, _ in vw),
        third_party_only=sum(v in ("supports", "contradicts", "mixed") and w < 1 for v, w in vw),
        ri_only=ri, verdicts=verdicts,
    )


def hypothesis_percent(statuses: list[str], n_interviews: int) -> tuple[str, float | None]:
    if n_interviews == 0:
        return "no_interviews_in_segment", None
    tested = [s for s in statuses if s != "not_tested"]
    if not tested:
        return "nothing_tested", None
    return "evaluated", round(100 * sum(s == "confirmed" for s in tested) / len(tested), 1)
