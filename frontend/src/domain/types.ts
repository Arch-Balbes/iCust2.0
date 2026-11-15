// Доменная модель фронтенда. Совпадает по смыслу с MVP_PLAN.md: слоты А–Ж, гипотезы с вариантами,
// компоненты = слоты гипотез, интервью → реплики → утверждения, инсайты, результаты ИГ2.
// Форму ProjectView отдаёт бэкенд: GET /api/projects/{id}/view (backend/app/api/projects.py).

/** Слоты гипотез (подписи как в макете). Код — стабильный ключ для API. */
export type SlotCode =
  | "product" | "role" | "situation" | "job" | "outcome"
  | "problem" | "losses" | "function" | "effect";

export const SLOT_LABEL: Record<SlotCode, string> = {
  product: "Продукт",
  role: "Роль",
  situation: "Ситуация",
  job: "Задача",
  outcome: "Результат",
  problem: "Проблема",
  losses: "Потери",
  function: "Функция",
  effect: "Эффект",
};

/** Строка гипотезы: слот + связка (серым в макете, «которые», «стремятся») + текст слота. */
export type SlotLine = { slot: SlotCode; lead?: string | null; text: string };

/** Результат проверки варианта оценщиком модуля коллеги. */
export type QualityCheck = { passed: boolean; reasons: string[] };

export type HypothesisKind = "segment" | "value";

export type Hypothesis = {
  id: string;            // SEG01 / SEG01-H01
  kind: HypothesisKind;
  segmentId: string;     // к какому сегменту относится (для гипотезы сегмента — свой id)
  variantNo: number;
  text?: string;         // гипотеза одним предложением (как вернул модуль)
  lines: SlotLine[];
  check: QualityCheck;
};

export type ProjectStatus = "in_progress" | "done";

export type Project = {
  id: string;
  name: string;
  status: ProjectStatus;
  stepIndex: number;      // текущий шаг (0..9)
  segments: number;
  interviews: number;
  updatedAt: string;
  pinned: boolean;
};

export type ActivityEvent = {
  at: string;
  projectId: string;
  projectName: string;
  text: string;
  state: "ready" | "review";
};

export type ContextField = {
  key: string;
  slot?: SlotCode;
  tag?: string;           // подпись-метка над вопросом (Роль, Проблема…)
  question: string;
  hint: string;
  example: string;
  value: string;
  /** Текст подсказки, если обязательное поле пустое (макет 03.2: «Заполните поле: …»). */
  required?: string;
  /** Необязательное поле (Д1 «Эффект»). */
  optional?: boolean;
};

export type ContextBlock = { title: string; fields: ContextField[] };

export type ScenarioQuestion = { id: string; topic?: string | null; text: string; hint?: string | null; checks: SlotCode[] };
export type ScenarioSection = { id: string; title: string; questions: ScenarioQuestion[] };

export type OfferKind = "personal" | "forward" | "seed";
export const OFFER_LABEL: Record<OfferKind, string> = {
  personal: "Персональный оффер",
  forward: "Оффер для пересылки",
  seed: "Оффер для посева",
};

export type Channel = { name: string; description: string; url: string };

export type RecruitingPlan = {
  whom: string;
  interviewsTarget: string;
  interviewsNote?: string | null;
  criteria?: string[];
  filterQuestions: string[];
  channels: { order: "Сначала" | "Затем"; channel: string; offer: OfferKind }[];
  /** Модуль коллеги даёт два оффера: персональный и для посева («для пересылки» в макете — открытый вопрос). */
  offers: Partial<Record<OfferKind, string>>;
  recommended?: Channel[];
  fixed?: { caption: string; channels: Channel[] };
};

export type Respondent = { id: string; code: string; name: string; role: string; segmentId: string };

export type InterviewStatus = "transcribed" | "uploading" | "transcribing" | "processing" | "too_long" | "error";

export type Interview = {
  id: string;
  respondentId: string;
  segmentId: string;
  fileType: string;
  fileName?: string;
  durationMin: number;
  sizeMb: number;
  status: InterviewStatus;
  progress?: number | null;
  error?: string | null;
  claims?: number;
  /** Пока запись обрабатывается: «Шаг 2 из 3 · Разбираем ответы» (progress — общий процент 0–100). */
  stageLabel?: string | null;
  recordedAt: string;
};

export type Turn = { index: number; time: string; seconds?: number; speaker: "interviewer" | "respondent"; text: string };

export type Quote = { respondentId: string; time: string; text: string; counter?: boolean };

/** Ячейка стенограммы: ответ респондента на вопрос сценария. */
export type StenogramRow = {
  questionId: string;
  summary: string;               // «Выводы по сегменту»
  answers: Record<string, string>; // respondentId → короткий ответ-цитата
  times?: Record<string, string>;
};

export type InsightRelation = "extends" | "contradicts";

export type Insight = {
  id: string;
  code?: string;
  segmentId: string;
  hypothesisKind: HypothesisKind;
  slot: SlotCode;
  relation: InsightRelation;
  title: string;
  insight?: string;
  expected: string;      // «В гипотезе»
  observed: string;      // «По данным»
  explanation?: string;
  quotes: Quote[];
  comments: number;
  level?: "stable" | "candidate";
  accepted?: boolean;
  source?: "llm" | "user";
  nSupporting?: number | null;
  nSegment?: number | null;
  boundaries?: string[];
  actions?: string[];
};

export type ComponentStatusCode = "confirmed" | "refuted" | "ambiguous" | "insufficient" | "not_tested";

/** Свидетельства ИГ2 по компоненту гипотезы (атомарный компонент внутри слота). */
export type ComponentEvidence = {
  slot: SlotCode;
  componentId?: string;
  text?: string;         // формулировка компонента
  lead?: string | null;
  status?: ComponentStatusCode; // статус считает бэкенд (app/ig1/ig2.py); без него — по k/c
  k: number;             // респондентов «за» (чужой опыт — 0,5)
  c: number;             // респондентов «против»
  riOnly: number;        // обсуждали без однозначного ответа
  pilot?: boolean;       // проверяется пилотом, не интервью
  supporting: Quote[];
  contradicting: Quote[];
};

export type ValidationResult = {
  segmentId: string;
  kind: HypothesisKind;
  hypothesisId: string;
  nInterviews: number;
  lines?: SlotLine[];
  percent?: number | null;
  components: ComponentEvidence[];
};

export type JobState = { status: "running" | "done" | "error"; error?: string | null };
export type JobKind = "hypotheses" | "scenario" | "prepare" | "stenogram" | "insights" | "reformulate";

export type ProductDescription = {
  product_name: string;
  key_function: string;
  research_goal: string;
  problem_and_losses: string;
  current_solutions: string;
  desired_outcome_and_effect: string;
};

export type Reformulated = Record<string, {
  segment: SlotLine[];
  value: SlotLine[];
  changes: { kind: HypothesisKind; slot: SlotCode; before: string; after: string }[];
}>;

/** Всё, что нужно экранам исследования, одним ответом API. */
export type ProjectView = {
  id: string;
  name: string;
  status: ProjectStatus;
  stepIndex: number;
  locked: boolean;
  updatedAt: string;
  context: Record<string, string>;
  jobs: Partial<Record<JobKind, JobState>>;
  segmentVariants: Hypothesis[];
  valueVariants: Hypothesis[];
  selectedSegments: string[];
  selectedValues: Record<string, string[]>;
  segmentLabel: Record<string, string>;
  generationNote: string;
  scenario: Record<string, ScenarioSection[]>;
  recruiting: Record<string, RecruitingPlan>;
  design: ProductDescription | null;
  plannedInterviews: number;
  respondents: Respondent[];
  interviews: Interview[];
  stenogram: Record<string, StenogramRow[]>;
  insights: Insight[];
  validation: ValidationResult[];
  reformulated: Reformulated;
  tokensUsed: number;
};
