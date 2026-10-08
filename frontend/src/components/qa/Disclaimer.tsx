import { Icon } from "../ui/Badge";

export function Disclaimer() {
  return (
    <div className="flex items-start gap-space-xs border border-hairline bg-surface-container-low p-space-md font-body-sm text-body-sm leading-relaxed text-on-surface-variant">
      <Icon name="info" className="mt-0.5 shrink-0 text-teal !text-[18px]" />
      <p>
        <strong>법적 고지:</strong> 본 서비스(Law-bot)는 국가 법령 데이터 기반의 자동 질의응답 및 해석 지원 도구이며, 개별 사업 현장의 구체적 소송·행정처분에 대한 변호사의 정식 법률 대리 의견을 대신하지 않습니다. 실무 적용 시 주무부처 행정해석을 확인하시기 바랍니다.
      </p>
    </div>
  );
}
