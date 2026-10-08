export function AnswerSkeleton() {
  return (
    <div className="border border-hairline bg-white" aria-busy="true">
      <div className="h-14 animate-pulse bg-primary-container" />
      <div className="flex flex-col gap-space-sm p-space-lg">
        <p className="font-body-sm text-body-sm text-on-surface-variant">관련 조문을 검색하고 있습니다…</p>
        {[100, 92, 96, 70].map((w) => (
          <div key={w} className="h-4 animate-pulse bg-surface-container-high" style={{ width: `${w}%` }} />
        ))}
      </div>
    </div>
  );
}
