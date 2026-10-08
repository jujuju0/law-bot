import { mockAsk, mockHealth } from "./mock";
import type { AskRequest, AskResponse, HealthResponse } from "./types";

export const API_BASE: string = import.meta.env.VITE_API_BASE ?? "/api";
export const USE_MOCK: boolean = import.meta.env.VITE_USE_MOCK === "true";
const TIMEOUT_MS = 60_000;
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(`${API_BASE}${path}`, { ...init, signal: ctrl.signal });
    if (!res.ok) throw new Error(`요청 실패 (${res.status})`);
    return (await res.json()) as T;
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw new Error("응답 시간이 초과되었습니다.");
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

/** 질문 → 답변. VITE_USE_MOCK=true면 fixture(지연 800ms). */
export async function ask(req: AskRequest): Promise<AskResponse> {
  if (USE_MOCK) {
    await sleep(800);
    return mockAsk(req.question);
  }
  return request<AskResponse>("/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
}

/** 서비스 상태 조회. */
export async function getHealth(): Promise<HealthResponse> {
  if (USE_MOCK) return mockHealth;
  return request<HealthResponse>("/health");
}

// TODO: 백엔드에 POST /feedback이 생기면 연결한다.
export function sendFeedback(question: string, kind: "positive" | "negative"): void {
  console.info("[feedback]", kind, question);
}
