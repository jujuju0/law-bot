import { useState } from "react";
import { sendFeedback } from "../../api/client";
import type { AskResponse } from "../../api/types";
import { parseAnswer } from "../../lib/parseAnswer";
import { Button } from "../ui/Button";
import { Icon } from "../ui/Badge";
import { useToast } from "../ui/toastContext";

function toPlainText(data: AskResponse): string {
  const { summary, explanation } = parseAnswer(data.answer);
  const refs = data.sources.map((s) => `- ${s.citation}`).join("\n");
  return [summary, explanation, refs && `근거\n${refs}`, data.notice].filter(Boolean).join("\n\n");
}

export function ActionTray({ data, question }: { data: AskResponse; question: string }) {
  const toast = useToast();
  const [vote, setVote] = useState<"positive" | "negative" | null>(null);
  const [copied, setCopied] = useState(false);

  const feedback = (k: "positive" | "negative") => {
    setVote(k);
    sendFeedback(question, k);
    toast("피드백이 기록되었습니다");
  };
  const copy = () => {
    void navigator.clipboard?.writeText(toPlainText(data)).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };
  const fb = (k: "positive" | "negative") =>
    `inline-flex items-center gap-1 px-3 py-1.5 font-label-md text-label-md ${vote === k ? "bg-primary-container text-on-primary" : "bg-surface-container text-on-surface hover:bg-surface-container-high"}`;

  return (
    <footer className="no-print flex flex-wrap items-center justify-between gap-space-md">
      <div className="flex gap-space-xs">
        <button type="button" aria-pressed={vote === "positive"} className={fb("positive")} onClick={() => feedback("positive")}>
          <Icon name="thumb_up" className="!text-[18px]" /> 도움이 되었어요
        </button>
        <button type="button" aria-pressed={vote === "negative"} className={fb("negative")} onClick={() => feedback("negative")}>
          <Icon name="thumb_down" className="!text-[18px]" /> 정확하지 않아요
        </button>
      </div>
      <div className="flex gap-space-sm">
        <Button variant="secondary" onClick={copy}>
          <Icon name="content_copy" className="!text-[16px]" /> {copied ? "복사 완료" : "답변 복사"}
        </Button>
        <Button onClick={() => window.print()}>
          <Icon name="print" className="!text-[16px]" /> 인쇄
        </Button>
      </div>
    </footer>
  );
}
