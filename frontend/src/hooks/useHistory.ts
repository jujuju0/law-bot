import { useCallback, useState } from "react";
import { readJson, writeJson } from "../lib/storage";

export interface HistoryItem {
  q: string;
  at: number;
}
const KEY = "lawbot.history";
const MAX = 10;

/** 최근 질의 이력 (localStorage, 최대 10개, 중복 제거). */
export function useHistory() {
  const [items, setItems] = useState<HistoryItem[]>(() => readJson<HistoryItem[]>(KEY, []));

  const add = useCallback((q: string) => {
    setItems((prev) => {
      const next = [{ q, at: Date.now() }, ...prev.filter((i) => i.q !== q)].slice(0, MAX);
      writeJson(KEY, next);
      return next;
    });
  }, []);

  const clear = useCallback(() => {
    writeJson(KEY, []);
    setItems([]);
  }, []);

  return { items, add, clear };
}

/** "10분 전" 형태의 상대시간. */
export function relativeTime(at: number, now = Date.now()): string {
  const min = Math.floor((now - at) / 60_000);
  if (min < 1) return "방금 전";
  if (min < 60) return `${min}분 전`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h}시간 전`;
  return `${Math.floor(h / 24)}일 전`;
}
