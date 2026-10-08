import type { ReactNode } from "react";
import { Badge, Icon } from "../ui/Badge";

export function PlainSummary({ children }: { children: ReactNode }) {
  return (
    <div className="border border-hairline bg-white p-space-md">
      <Badge tone="spruce">
        <Icon name="lightbulb" className="!text-[14px]" />
        핵심 요약 해설
      </Badge>
      <div className="mt-space-sm">{children}</div>
    </div>
  );
}
