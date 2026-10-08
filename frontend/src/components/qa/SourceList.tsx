import type { Source } from "../../api/types";
import { sourceDomId } from "../../lib/citations";
import { Icon } from "../ui/Badge";
import { SourceCard } from "./SourceCard";

interface Props {
  sources: Source[];
  highlight: number | null;
}

export function SourceList({ sources, highlight }: Props) {
  if (sources.length === 0) return null;
  return (
    <section>
      <div className="mb-space-sm flex items-center justify-between">
        <h2 className="flex items-center gap-space-xs font-headline-sm text-headline-sm text-primary">
          <Icon name="menu_book" className="text-teal !text-[20px]" />
          인용된 근거 조문
        </h2>
        <span className="font-code-citation text-code-citation text-on-surface-variant">출처 {sources.length}건</span>
      </div>
      <div className="flex flex-col gap-space-md">
        {sources.map((s, i) => (
          <SourceCard key={`${s.citation}-${i}`} source={s} index={i} domId={sourceDomId(i)} highlighted={highlight === i} />
        ))}
      </div>
    </section>
  );
}
