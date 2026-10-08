import { THEMES } from "../../data/presets";
import { relativeTime, type HistoryItem } from "../../hooks/useHistory";
import { Icon } from "../ui/Badge";

interface Props {
  history: HistoryItem[];
  onPick: (q: string) => void;
  onClearHistory: () => void;
  snapshot: string | null | undefined;
  open: boolean;
  onClose: () => void;
}

export function Sidebar({ history, onPick, onClearHistory, snapshot, open, onClose }: Props) {
  const pick = (q: string) => {
    onPick(q);
    onClose();
  };
  return (
    <>
      {open && <div className="no-print fixed inset-0 top-16 z-20 bg-primary/40 lg:hidden" onClick={onClose} aria-hidden="true" />}
      <aside
        aria-label="사이드바"
        className={`no-print fixed bottom-0 left-0 top-16 z-30 flex w-72 flex-col justify-between overflow-y-auto border-r border-hairline bg-white ${open ? "" : "hidden"} lg:flex`}
      >
        <div className="flex flex-col gap-space-lg p-space-md">
          <section>
            <div className="mb-space-sm flex items-center justify-between px-space-sm">
              <h2 className="font-label-sm text-label-sm uppercase tracking-wider text-on-surface-variant">주요 법률 테마</h2>
              <span className="font-code-citation text-code-citation text-secondary">{THEMES.length}개 항목</span>
            </div>
            <nav className="flex flex-col gap-1">
              {THEMES.map((t) => (
                <button key={t.title} type="button" onClick={() => pick(t.q)} className="flex items-start gap-space-sm p-space-sm text-left hover:bg-surface-container-low">
                  <Icon name={t.icon} className="mt-0.5 text-teal !text-[18px]" />
                  <span className="flex flex-col">
                    <span className="font-label-md text-label-md leading-tight text-on-surface">{t.title}</span>
                    <span className="font-body-sm text-body-sm text-on-surface-variant">{t.sub}</span>
                  </span>
                </button>
              ))}
            </nav>
          </section>
          <section>
            <div className="mb-space-sm flex items-center justify-between px-space-sm">
              <h2 className="font-label-sm text-label-sm uppercase tracking-wider text-on-surface-variant">최근 질의 이력</h2>
              {history.length > 0 && (
                <button type="button" onClick={onClearHistory} className="font-label-sm text-label-sm text-secondary hover:underline">이력 지우기</button>
              )}
            </div>
            {history.length === 0 ? (
              <p className="px-space-sm font-body-sm text-body-sm text-outline">아직 질의 이력이 없습니다.</p>
            ) : (
              <div className="flex flex-col gap-1">
                {history.map((h) => (
                  <button key={h.q} type="button" onClick={() => pick(h.q)} className="flex flex-col p-space-sm text-left hover:bg-surface-container-low">
                    <span className="line-clamp-1 font-label-md text-label-md text-on-surface">{h.q}</span>
                    <span className="mt-0.5 font-code-citation text-code-citation text-outline">{relativeTime(h.at)}</span>
                  </button>
                ))}
              </div>
            )}
          </section>
        </div>
        <div className="flex items-center justify-between border-t border-hairline bg-surface-container-low p-space-md">
          <span className="font-label-sm text-label-sm text-on-surface-variant">법령 기준</span>
          <span className="border border-hairline bg-white px-1.5 py-0.5 font-code-citation text-code-citation text-primary-container">{snapshot ?? "법률 제20676호"}</span>
        </div>
      </aside>
    </>
  );
}
