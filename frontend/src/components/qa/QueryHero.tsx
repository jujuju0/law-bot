import { useEffect, useRef } from "react";
import { SUGGESTED } from "../../data/presets";
import { Button } from "../ui/Button";
import { Badge, Icon } from "../ui/Badge";
import { SuggestionChips } from "./SuggestionChips";

const MAX_LEN = 500;

interface Props {
  value: string;
  onChange: (v: string) => void;
  onSubmit: (q: string) => void;
  loading: boolean;
}

export function QueryHero({ value, onChange, onSubmit, loading }: Props) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const canSubmit = value.trim().length > 0 && !loading;

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 22 * 4 + 4)}px`;
  }, [value]);

  const submit = () => canSubmit && onSubmit(value.trim());

  return (
    <section className="no-print border border-hairline bg-surface-container-low p-space-lg">
      <div className="mb-space-md max-w-2xl">
        <Badge tone="spruce">
          <Icon name="verified" className="!text-[14px]" />
          인공지능 발전과 신뢰 기반 조성 등에 관한 기본법 기준
        </Badge>
        <h1 className="mt-space-xs font-headline-lg text-headline-lg tracking-tight text-primary">
          인공지능 기본법, 법률 조문과 함께 알기 쉽게 답해드립니다
        </h1>
        <p className="mt-1.5 font-body-md text-body-md leading-relaxed text-on-surface-variant">
          복잡한 법률 용어를 일반인도 이해하기 쉬운 문장으로 풀고, 정확한 법 조문(출처)을 투명하게 확인하세요.
        </p>
      </div>
      <form
        className="flex flex-col items-stretch gap-space-xs border border-hairline bg-white p-space-sm sm:flex-row"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <div className="flex flex-1 items-start bg-surface-container-low px-space-md py-space-sm">
          <Icon name="search" className="mr-space-sm mt-0.5 text-secondary !text-[22px]" />
          <textarea
            ref={ref}
            rows={1}
            value={value}
            maxLength={MAX_LEN}
            aria-label="질문 입력"
            placeholder="인공지능 기본법 조문, 고영향 인공지능 사업자 의무 등을 질문하세요."
            className="w-full resize-none bg-transparent font-body-md text-body-md text-on-surface placeholder:text-[#758794] focus:outline-none"
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                submit();
              }
            }}
          />
          <span className="ml-2 shrink-0 font-code-citation text-code-citation text-outline">{value.length}/{MAX_LEN}</span>
          {value && (
            <button type="button" aria-label="내용 지우기" onClick={() => onChange("")} className="ml-1 p-1 text-outline hover:text-on-surface">
              <Icon name="close" className="!text-[18px]" />
            </button>
          )}
        </div>
        <Button type="submit" disabled={!canSubmit} className="px-space-lg py-3">
          법률 질의 실행 <Icon name="arrow_forward" className="!text-[18px]" />
        </Button>
      </form>
      <div className="mt-space-md">
        <SuggestionChips items={SUGGESTED} onPick={onSubmit} />
      </div>
    </section>
  );
}
