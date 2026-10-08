import type { AskResponse, HealthResponse } from "./types";

const NOTICE = "AI가 생성한 답변입니다. 법률 자문이 아니며 원문을 확인하세요.";
export const REFUSAL = "제공된 AI 기본법 관련 법령에서 확인할 수 없습니다.";

const general: AskResponse = {
  answer:
    "① (mock) 고영향 인공지능은 사람의 생명·신체·기본권에 중대한 영향을 미칠 수 있는 인공지능입니다. [법 제2조]\n\n" +
    "② (mock) 쉬운 설명입니다. 해당 여부가 불확실하면 확인을 요청할 수 있습니다. [법 제33조 제1항]\n\n" +
    "1. 서비스가 이용자의 권리에 미치는 영향을 먼저 점검합니다.\n2. 불확실하면 주무부처에 확인을 요청합니다.\n\n" +
    "③ 근거: [법 제2조], [법 제33조 제1항]",
  sources: [
    { article: "제2조", source_type: "law", citation: "법 제2조", doc_title: "인공지능 발전과 신뢰 기반 조성 등에 관한 기본법", content: "(mock) 조문 원문 자리", score: 0.89, cited: true, added_by: "search" },
    { article: "제33조", source_type: "law", citation: "법 제33조 제1항", doc_title: "인공지능 발전과 신뢰 기반 조성 등에 관한 기본법", content: "(mock) 조문 원문 자리 — 길이 확인용 문장입니다. ".repeat(8), score: 0.82, cited: true, added_by: "search" },
  ],
  notice: NOTICE,
  grounded: true,
  data_snapshot: "(mock) 2026-01-01",
  debug: { candidates: [{ citation: "법 제2조", dense: 0.71 }], stage_scores: { rrf: 0.03, rerank: 0.89 }, added_by: { "법 제2조": "search" }, warnings: [], usage: { input_tokens: 0, output_tokens: 0 } },
};

const penalty: AskResponse = {
  answer:
    "① (mock) 위반 시 과태료가 부과될 수 있으며 구체적 기준은 시행령 별표에 위임되어 있습니다. [법 제43조 제1항]\n\n" +
    "② (mock) 금액·기준은 별표를 확인하세요. [영 별표 1]\n\n③ 근거: [법 제43조 제1항], [영 별표 1]",
  sources: [
    { article: "제43조", source_type: "law", citation: "법 제43조 제1항", doc_title: "인공지능 발전과 신뢰 기반 조성 등에 관한 기본법", content: "(mock) 조문 원문 자리", score: 0.91, cited: true, added_by: "search" },
    { article: "별표 1", source_type: "annex", citation: "영 별표 1", doc_title: "시행령 별표 1", content: "| 위반 행위 | 근거 | 금액 |\n|---|---|---|\n| (mock) 행위 A | (mock) | (mock) |\n| (mock) 행위 B | (mock) | (mock) |", score: 0.77, cited: true, added_by: "delegation" },
  ],
  notice: NOTICE,
  grounded: true,
  data_snapshot: "(mock) 2026-01-01",
  debug: null,
};

const refusal: AskResponse = { answer: REFUSAL, sources: [], notice: NOTICE, grounded: true, data_snapshot: "(mock) 2026-01-01", debug: null };

/** 질문 키워드로 fixture 선택 (고영향 / 과태료 / 그 외 거절) */
export function mockAsk(question: string): AskResponse {
  if (question.includes("고영향")) return general;
  if (question.includes("과태료")) return penalty;
  return refusal;
}

export const mockHealth: HealthResponse = {
  status: "ok",
  qdrant: true,
  points_by_source: { law: 120, decree: 80, annex: 6 },
  data_snapshot: "(mock) 2026-01-01",
};
