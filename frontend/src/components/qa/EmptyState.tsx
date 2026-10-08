import { SUGGESTED } from "../../data/presets";
import { SuggestionChips } from "./SuggestionChips";

export function EmptyState({ onPick }: { onPick: (q: string) => void }) {
  return (
    <div className="flex flex-col items-center gap-space-md border border-hairline bg-white p-space-xl text-center">
      <img src="/logo.png" alt="Law-bot" className="h-24 w-24 object-contain" />
      <ul className="flex flex-col gap-1 font-body-md text-body-md text-on-surface-variant">
        <li>AI 기본법과 시행령 조문을 근거로 답변합니다.</li>
        <li>답변 속 인용을 누르면 해당 근거 조문으로 이동합니다.</li>
        <li>근거가 없는 질문에는 답하지 않습니다.</li>
      </ul>
      <SuggestionChips items={SUGGESTED} onPick={onPick} label="이렇게 물어보세요 :" />
    </div>
  );
}
