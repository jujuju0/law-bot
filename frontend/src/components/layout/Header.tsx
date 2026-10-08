import { API_BASE, USE_MOCK } from "../../api/client";
import { LAW_GO_KR } from "../../lib/sourceType";
import { Badge, Icon } from "../ui/Badge";
import { useHealth } from "../../hooks/useHealth";

interface Props {
  debug: boolean;
  onToggleDebug: () => void;
  onMenu: () => void;
  onHome: () => void;
}

export function Header({ debug, onToggleDebug, onMenu, onHome }: Props) {
  const { data, isError, isPending } = useHealth();
  const ok = !isError && !isPending && data?.status !== "degraded" && data?.qdrant !== false;
  const link = "px-space-sm py-1 font-label-md text-label-md text-on-surface-variant hover:text-on-surface hover:underline";

  return (
    <header className="no-print fixed inset-x-0 top-0 z-40 h-16 border-b border-hairline bg-white">
      <div className="flex h-16 items-center justify-between gap-space-md px-margin sm:px-space-lg">
        <div className="flex items-center gap-space-md">
          <button type="button" aria-label="메뉴 열기" onClick={onMenu} className="p-1 lg:hidden">
            <Icon name="menu" />
          </button>
          <button type="button" onClick={onHome} aria-label="Law-bot 처음으로" className="flex items-center gap-space-sm text-left">
            <img src="/logo.png" alt="Law-bot" className="h-9 w-9 object-contain" />
            <span className="flex flex-col">
              <span className="font-headline-sm text-headline-sm leading-none text-primary">Law-bot</span>
              <span className="mt-1 hidden font-label-sm text-label-sm leading-none text-on-surface-variant sm:block">인공지능 기본법 조문 기반 Q&amp;A</span>
            </span>
          </button>
          <div className="hidden h-6 w-px bg-hairline md:block" />
          <nav className="hidden items-center gap-space-sm lg:flex">
            <span aria-current="page" className="bg-primary-container px-space-sm py-1 font-label-md text-label-md text-on-primary">AI 기본법 Q&amp;A</span>
            <a className={link} href={LAW_GO_KR} target="_blank" rel="noopener noreferrer">법령 원문</a>
            <a className={link} href={`${API_BASE}/docs`} target="_blank" rel="noopener noreferrer">API 문서</a>
          </nav>
        </div>
        <div className="flex items-center gap-space-sm">
          {USE_MOCK && <Badge tone="crimson">MOCK</Badge>}
          <label className="flex cursor-pointer items-center gap-1.5 font-label-sm text-label-sm text-on-surface-variant">
            <input type="checkbox" checked={debug} onChange={onToggleDebug} className="h-4 w-4 accent-primary-container" />
            검색 디버그 보기
          </label>
          <div className="hidden items-center gap-space-xs border border-hairline bg-surface-container-low px-space-sm py-1 sm:flex">
            <span className={`h-2 w-2 rounded-full ${isPending ? "bg-outline" : ok ? "bg-teal" : "bg-crimson"}`} />
            <span className="font-code-citation text-code-citation text-on-surface-variant">
              {isPending ? "상태 확인 중" : ok ? "Qdrant 정상" : "Qdrant 연결 확인 불가"}
            </span>
          </div>
        </div>
      </div>
    </header>
  );
}
