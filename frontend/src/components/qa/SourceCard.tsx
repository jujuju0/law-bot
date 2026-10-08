import { useState } from "react";
import type { Source } from "../../api/types";
import { LAW_GO_KR, SOURCE_LABEL } from "../../lib/sourceType";
import { Badge, Icon } from "../ui/Badge";
import { useToast } from "../ui/toastContext";
import { parsePipeTable } from "../../lib/markdownTable";
import { MarkdownTable } from "./MarkdownTable";

const FOLD_AT = 200;
const isDesktop = () => typeof window.matchMedia !== "function" || window.matchMedia("(min-width: 768px)").matches;

interface Props {
  source: Source;
  index: number;
  domId: string;
  highlighted: boolean;
}

export function SourceCard({ source, index, domId, highlighted }: Props) {
  const toast = useToast();
  const [open, setOpen] = useState(isDesktop);
  const [full, setFull] = useState(false);
  const meta = SOURCE_LABEL[source.source_type];
  const table = source.source_type === "annex" ? parsePipeTable(source.content) : null;
  const long = source.content.length > FOLD_AT;
  const text = long && !full && !table ? source.content.slice(0, FOLD_AT) + "…" : source.content;

  // 인용 배지 클릭으로 강조되면 접힌 카드를 펼친다 (렌더 중 상태 보정)
  if (highlighted && !open) setOpen(true);

  const copy = () => {
    void navigator.clipboard?.writeText(`[${source.citation}] ${source.content}`).then(() => toast("조문이 복사되었습니다."));
  };

  return (
    <div id={domId} className={`border bg-white p-space-md transition-colors ${highlighted ? "border-teal bg-quote-bg" : "border-hairline"}`}>
      <div className="flex flex-wrap items-center justify-between gap-space-xs">
        <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className="flex min-w-0 flex-1 flex-wrap items-center gap-space-xs text-left">
          <Badge tone={index === 0 ? "primary" : "neutral"}>{index === 0 ? "근거 조문" : "관련 조항"}</Badge>
          <Badge tone="spruce">{meta.label}</Badge>
          {meta.note && <span className="font-label-sm text-label-sm text-on-surface-variant">{meta.note}</span>}
          <span className="font-label-md text-label-md font-semibold text-primary">{source.citation}</span>
          <span className="truncate font-body-sm text-body-sm text-on-surface-variant">{source.doc_title}</span>
        </button>
        <span className="font-code-citation text-code-citation text-secondary">관련도 {source.score.toFixed(2)}</span>
      </div>
      {open && (
        <>
          <div className="my-space-sm border-l-[3px] bg-quote-zone p-space-md font-legal-article text-legal-article" style={{ borderLeftColor: index === 0 ? "#0d2538" : "#2E7D8A" }}>
            {table ? <MarkdownTable rows={table} /> : <p className="whitespace-pre-wrap">{text}</p>}
          </div>
          <div className="no-print flex items-center justify-between gap-space-sm">
            {long && !table ? (
              <button type="button" onClick={() => setFull(!full)} className="font-label-sm text-label-sm text-secondary hover:underline">
                {full ? "접기" : "전문 보기"}
              </button>
            ) : <span />}
            <div className="flex items-center gap-space-md">
              <button type="button" onClick={copy} className="inline-flex items-center gap-0.5 font-label-sm text-label-sm text-secondary hover:underline">
                <Icon name="content_copy" className="!text-[15px]" /> 조문 복사
              </button>
              <a href={LAW_GO_KR} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-0.5 font-label-sm text-label-sm text-secondary hover:underline">
                국가법령정보센터 <Icon name="open_in_new" className="!text-[14px]" />
              </a>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
