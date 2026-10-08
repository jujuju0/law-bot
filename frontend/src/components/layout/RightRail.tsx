import type { Source, SourceType } from "../../api/types";
import { FAQ } from "../../data/presets";
import { useHealth } from "../../hooks/useHealth";
import { LAW_GO_KR, SOURCE_LABEL } from "../../lib/sourceType";
import { Icon } from "../ui/Badge";

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex items-center justify-between bg-surface-container-low p-space-sm">
      <span className="text-on-surface-variant">{k}</span>
      <span className="font-semibold text-primary-container">{v}</span>
    </div>
  );
}

export function RightRail({ sources, onPick }: { sources: Source[] | null; onPick: (q: string) => void }) {
  const { data } = useHealth();
  const points = Object.entries(data?.points_by_source ?? {}) as [SourceType, number][];
  const dist = sources ? Object.entries(sources.reduce<Record<string, number>>((a, s) => ({ ...a, [s.source_type]: (a[s.source_type] ?? 0) + 1 }), {})) : [];
  const max = Math.max(1, ...dist.map(([, n]) => n));
  const box = "border border-hairline bg-white p-space-md";

  return (
    <aside className="no-print flex flex-col gap-space-lg">
      {(points.length > 0 || data?.data_snapshot || data?.status) && (
        <section className={box}>
          <h2 className="mb-space-sm flex items-center gap-space-xs font-headline-sm text-headline-sm text-primary">
            <Icon name="database" className="text-teal !text-[20px]" /> 법령 데이터 상태
          </h2>
          <div className="flex flex-col gap-space-xs font-code-citation text-code-citation">
            {data?.status && <Row k="서비스 상태" v={data.status} />}
            {points.map(([t, n]) => <Row key={t} k={`색인 ${SOURCE_LABEL[t]?.label ?? t}`} v={`${n.toLocaleString()}개 청크`} />)}
            {data?.data_snapshot && <Row k="데이터 기준일" v={data.data_snapshot} />}
          </div>
        </section>
      )}
      {dist.length > 0 && (
        <section className={box}>
          <h2 className="mb-space-sm font-headline-sm text-headline-sm text-primary">이번 답변의 근거 분포</h2>
          <div className="flex flex-col gap-space-xs">
            {dist.map(([t, n]) => (
              <div key={t} className="flex items-center gap-space-sm font-code-citation text-code-citation">
                <span className="w-16 shrink-0 text-on-surface-variant">{SOURCE_LABEL[t as SourceType]?.label ?? t}</span>
                <div className="h-3 flex-1 bg-surface-container"><div className="h-3 bg-primary-container" style={{ width: `${(n / max) * 100}%` }} /></div>
                <span className="w-4 text-right">{n}</span>
              </div>
            ))}
          </div>
        </section>
      )}
      <section className={box}>
        <h2 className="mb-space-sm font-headline-sm text-headline-sm text-primary">자주 묻는 질의</h2>
        <ul className="flex flex-col gap-space-xs">
          {FAQ.map((q, i) => (
            <li key={q}>
              <button type="button" onClick={() => onPick(q)} className="flex w-full items-start gap-space-xs bg-surface-container p-space-sm text-left font-body-sm text-body-sm font-medium text-on-surface hover:bg-surface-container-high">
                <span className="font-code-citation text-code-citation font-bold text-teal">{String(i + 1).padStart(2, "0")}</span>
                {q}
              </button>
            </li>
          ))}
        </ul>
      </section>
      <section className="bg-primary p-space-md text-on-primary">
        <h2 className="mb-space-xs font-headline-sm text-headline-sm text-white">법적 판단이 필요하신가요?</h2>
        <p className="mb-space-md font-body-sm text-body-sm text-primary-fixed-dim">
          법적 판단이 필요하면 주무부처(과학기술정보통신부) 안내와 법령 원문을 확인하세요.
        </p>
        <a href={LAW_GO_KR} target="_blank" rel="noopener noreferrer" className="flex items-center justify-center gap-1 bg-secondary px-space-md py-2 font-label-md text-label-md text-white hover:bg-secondary-container hover:text-on-secondary-container">
          국가법령정보센터 <Icon name="open_in_new" className="!text-[16px]" />
        </a>
      </section>
    </aside>
  );
}
