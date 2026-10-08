export function SuggestionChips({ items, onPick, label = "추천 질의 :" }: { items: string[]; onPick: (q: string) => void; label?: string }) {
  return (
    <div className="flex flex-wrap items-center gap-space-xs">
      <span className="mr-1 font-label-sm text-label-sm text-on-surface-variant">{label}</span>
      {items.map((q) => (
        <button key={q} type="button" onClick={() => onPick(q)} className="flex items-center gap-1 border border-hairline bg-white px-2.5 py-1 text-left font-body-sm text-body-sm text-primary-container hover:border-primary-container hover:bg-quote-bg">
          <span className="font-bold text-teal">§</span> {q}
        </button>
      ))}
    </div>
  );
}
