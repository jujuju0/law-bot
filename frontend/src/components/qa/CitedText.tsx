import type { Source } from "../../api/types";
import { findSourceIndex, tokenize } from "../../lib/citations";

interface Props {
  text: string;
  sources: Source[];
  onCite: (index: number) => void;
}

/** 본문의 [법 제N조] 등 인용을 클릭 가능한 배지로 바꾼다. 출처에 없으면 점선 회색 배지. */
export function CitedText({ text, sources, onCite }: Props) {
  return (
    <>
      {tokenize(text).map((t, i) => {
        if (t.type === "text") return <span key={i}>{t.text}</span>;
        const idx = findSourceIndex(sources, t.citation);
        if (idx < 0) {
          return (
            <span key={i} title="출처 목록에 없는 인용" className="mx-0.5 border border-dashed border-outline px-1 font-code-citation text-code-citation text-outline">
              {t.citation}
            </span>
          );
        }
        return (
          <button
            key={i}
            type="button"
            onClick={() => onCite(idx)}
            aria-label={`${t.citation} 근거 조문으로 이동`}
            className="mx-0.5 border border-teal bg-white px-1 align-baseline font-code-citation text-code-citation text-teal hover:bg-quote-bg"
          >
            {t.citation}
          </button>
        );
      })}
    </>
  );
}

/** 문단(\n\n) 단위로 렌더하며 `1.` 번호 목록 문단은 <ol>로 만든다. */
export function CitedBlocks({ text, sources, onCite }: Props) {
  const blocks = text.split(/\n{2,}/).filter((b) => b.trim());
  return (
    <div className="flex flex-col gap-space-sm">
      {blocks.map((b, i) => {
        const lines = b.split("\n").map((l) => l.trim()).filter(Boolean);
        if (lines.length > 0 && lines.every((l) => /^\d+\.\s/.test(l))) {
          return (
            <ol key={i} className="list-decimal pl-5 text-[15px] leading-[1.6]">
              {lines.map((l, j) => (
                <li key={j} className="pl-1">
                  <CitedText text={l.replace(/^\d+\.\s/, "")} sources={sources} onCite={onCite} />
                </li>
              ))}
            </ol>
          );
        }
        return (
          <p key={i} className="whitespace-pre-line text-[15px] leading-[1.6]">
            <CitedText text={b} sources={sources} onCite={onCite} />
          </p>
        );
      })}
    </div>
  );
}
