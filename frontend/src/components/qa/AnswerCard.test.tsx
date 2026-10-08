import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { mockAsk } from "../../api/mock";
import { ToastProvider } from "../ui/Toast";
import { AnswerCard } from "./AnswerCard";

const wrap = (q: string) =>
  render(<ToastProvider><AnswerCard data={mockAsk(q)} question={q} onPick={vi.fn()} /></ToastProvider>);

describe("AnswerCard", () => {
  it("일반 답변: 인용 배지 클릭 시 출처 카드로 이동", () => {
    Element.prototype.scrollIntoView = vi.fn();
    wrap("고영향");
    expect(screen.getByText("근거 확인됨")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: /법 제2조 근거 조문으로 이동/ })[0]);
    expect(screen.getByText("출처 2건")).toBeInTheDocument();
  });
  it("별표 답변: 표 렌더", () => {
    wrap("과태료");
    expect(screen.getByRole("table")).toBeInTheDocument();
  });
  it("거절 답변: 출처 없음", () => {
    wrap("날씨");
    expect(screen.queryByText(/출처 \d+건/)).toBeNull();
    expect(screen.getByText(/질문을 더 구체적으로/)).toBeInTheDocument();
  });
});
