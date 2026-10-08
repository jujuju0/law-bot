# Law-bot Frontend

AI 기본법 근거 기반 Q&A 웹 UI (Vite + React + TypeScript + Tailwind 3 + TanStack Query).
디자인 기준은 "Statutory Precision"(모서리 0, 그림자 없음, 1px 헤어라인).

## 실행
```bash
npm i
cp .env.example .env.local
npm run dev        # http://localhost:5173
npm run build && npm run lint && npm test
```

## 환경변수
| 변수 | 기본 | 설명 |
|---|---|---|
| `VITE_API_BASE` | `/api` | API prefix. Vite 프록시가 `/api/*` → `http://localhost:8000/*`로 전달 |
| `VITE_USE_MOCK` | `true` | true면 네트워크 없이 fixture 사용 ("고영향" → 일반, "과태료" → 별표, 그 외 → 거절) |

## 실제 백엔드 연결
```bash
# 저장소 루트에서 (Qdrant 기동 후)
uv run uvicorn app.main:app --port 8000
# frontend/.env.local 에서 VITE_USE_MOCK=false
```
헤더의 "검색 디버그 보기"를 켜면 `debug: true`로 요청하고 후보·점수·warnings를 표시한다.

## 구조
`src/api`(타입·클라이언트·mock) · `src/lib`(parseAnswer·citations 등 순수 함수) · `src/hooks` · `src/components/{layout,qa,ui}`
