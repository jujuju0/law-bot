export type SourceType = "law" | "decree" | "admrul" | "annex" | "term" | "expc";

export interface AskRequest {
  question: string;
  debug?: boolean;
}

export interface Source {
  article: string;
  source_type: SourceType;
  /** 답변 본문 인용(`[법 제31조 제2항]`)과 매칭되는 키 */
  citation: string;
  doc_title: string;
  content: string;
  score: number;
  cited?: boolean;
  added_by?: string;
}

export interface AskResponse {
  answer: string;
  sources: Source[];
  notice: string;
  grounded: boolean;
  data_snapshot: string | null;
  debug: Record<string, unknown> | null;
}

export interface HealthResponse {
  status?: string;
  qdrant?: boolean | string;
  collection?: string;
  points_by_source?: Partial<Record<SourceType, number>>;
  preset?: string;
  data_snapshot?: string | null;
}
