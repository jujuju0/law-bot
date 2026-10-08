import { useCallback, useEffect, useRef, useState } from "react";
import type { AskResponse } from "../../api/types";
import { sourceDomId } from "../../lib/citations";
import { REFUSAL } from "../../api/mock";
import { parseAnswer } from "../../lib/parseAnswer";
import { FAQ } from "../../data/presets";
import { Badge, Icon } from "../ui/Badge";
import { ActionTray } from "./ActionTray";
import { CitedBlocks, CitedText } from "./CitedText";
import { DebugDrawer } from "./DebugDrawer";
import { PlainSummary } from "./PlainSummary";
import { SourceList } from "./SourceList";
import { SuggestionChips } from "./SuggestionChips";

interface Props {
  data: AskResponse;
  question: string;
  onPick: (q: string) => void;
}

export function AnswerCard({ data, question, onPick }: Props) {
  const [highlight, setHighlight] = useState<number | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const refused = data.answer.includes(REFUSAL) && data.sources.length === 0;
  const { summary, explanation } = parseAnswer(data.answer);

  useEffect(() => () => clearTimeout(timer.current), []);

  const onCite = useCallback((i: number) => {
    setHighlight(i);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setHighlight(null), 1000);
    // 접힌 카드가 펼쳐진 뒤 스크롤하도록 다음 프레임에 이동
    requestAnimationFrame(() => document.getElementById(sourceDomId(i))?.scrollIntoView({ behavior: "smooth", block: "center" }));
  }, []);

  return (
    <article className="print-root flex flex-col border border-hairline bg-white" aria-live="polite">
      <header className="flex flex-wrap items-center justify-between gap-space-sm bg-primary-container p-space-md text-on-primary">
        <div className="flex items-center gap-space-sm">
          <div className="flex h-7 w-7 items-center justify-center bg-on-primary text-primary-container">
            <Icon name="balance" className="!text-[18px]" />
          </div>
          <div>
            <div className="font-headline-sm text-headline-sm leading-tight text-white">Law-bot 답변</div>
            <div className="font-label-sm text-label-sm text-primary-fixed-dim">법령 조문 근거 기반 응답</div>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-space-xs">
          {data.grounded ? <Badge tone="teal">근거 확인됨</Badge> : <Badge tone="crimson">근거 부족 — 원문 확인 필요</Badge>}
          {data.data_snapshot && <Badge tone="primary">데이터 기준 {data.data_snapshot}</Badge>}
        </div>
      </header>

      <div className="flex flex-col gap-space-lg p-space-lg">
        {refused ? (
          <div className="border border-hairline bg-surface-container-low p-space-md">
            <p className="font-body-lg text-body-lg font-medium text-on-surface">{REFUSAL}</p>
            <p className="mt-1 font-body-md text-body-md text-on-surface-variant">질문을 더 구체적으로 바꿔보세요. 예를 들어 조문 주제나 의무 대상을 함께 적어주세요.</p>
            <div className="mt-space-md">
              <SuggestionChips items={FAQ} onPick={onPick} label="이런 질문은 어떨까요 :" />
            </div>
          </div>
        ) : (
          <>
            {!data.grounded && (
              <p role="alert" className="border border-crimson bg-error-container p-space-sm font-body-sm text-body-sm text-crimson">
                검색된 근거로 답변을 충분히 뒷받침하지 못했습니다. 반드시 법령 원문을 확인하세요.
              </p>
            )}
            {summary && (
              <p className="font-body-lg text-body-lg font-semibold text-primary">
                <CitedText text={summary} sources={data.sources} onCite={onCite} />
              </p>
            )}
            {explanation && (
              <PlainSummary>
                <CitedBlocks text={explanation} sources={data.sources} onCite={onCite} />
              </PlainSummary>
            )}
            <SourceList sources={data.sources} highlight={highlight} />
          </>
        )}
        {data.debug && <DebugDrawer debug={data.debug} />}
        <ActionTray data={data} question={question} />
        <p className="font-body-sm text-body-sm text-on-surface-variant">{data.notice}</p>
      </div>
    </article>
  );
}
