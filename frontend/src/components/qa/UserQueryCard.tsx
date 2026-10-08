import { formatKst } from "../../lib/format";
import { Icon } from "../ui/Badge";

export function UserQueryCard({ question, askedAt }: { question: string; askedAt: Date }) {
  return (
    <div className="flex items-start gap-space-md border border-hairline bg-white p-space-md">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center bg-surface-container-high">
        <Icon name="person" className="!text-[18px]" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex items-center justify-between gap-2">
          <span className="font-label-sm text-label-sm font-semibold text-secondary">사용자 질의</span>
          <span className="font-code-citation text-code-citation text-outline">{formatKst(askedAt)}</span>
        </div>
        <p className="whitespace-pre-wrap break-words font-body-lg text-body-lg font-medium text-on-surface">{question}</p>
      </div>
    </div>
  );
}
