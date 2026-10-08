import { useState } from "react";
import { Badge, Icon } from "../ui/Badge";

const KNOWN = ["candidates", "stage_scores", "added_by", "warnings", "usage"];

export function DebugDrawer({ debug }: { debug: Record<string, unknown> }) {
  const [open, setOpen] = useState(false);
  const warnings = Array.isArray(debug.warnings) ? debug.warnings.length : 0;
  const rest = Object.fromEntries(Object.entries(debug).filter(([k]) => !KNOWN.includes(k)));
  return (
    <div className="no-print border border-hairline bg-surface-container-low p-space-md">
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className="flex w-full items-center justify-between text-left font-label-md text-label-md text-secondary">
        <span className="flex items-center gap-1.5">
          <Icon name="terminal" className="!text-[18px]" /> 검색 디버그
          {warnings > 0 && <Badge tone="crimson">경고 {warnings}</Badge>}
        </span>
        <Icon name={open ? "expand_less" : "expand_more"} className="!text-[18px]" />
      </button>
      {open && (
        <div className="mt-space-md flex flex-col gap-space-sm font-code-citation text-code-citation">
          {KNOWN.filter((k) => k in debug).map((k) => (
            <div key={k}>
              <div className="mb-1 font-semibold text-primary">{k}</div>
              <pre className="overflow-x-auto whitespace-pre-wrap border border-hairline bg-white p-2">{JSON.stringify(debug[k], null, 2)}</pre>
            </div>
          ))}
          {Object.keys(rest).length > 0 && <pre className="overflow-x-auto whitespace-pre-wrap border border-hairline bg-white p-2">{JSON.stringify(rest, null, 2)}</pre>}
        </div>
      )}
    </div>
  );
}
