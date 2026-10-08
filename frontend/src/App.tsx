import { useEffect, useState } from "react";
import { AnswerCard } from "./components/qa/AnswerCard";
import { AnswerSkeleton } from "./components/qa/AnswerSkeleton";
import { Disclaimer } from "./components/qa/Disclaimer";
import { EmptyState } from "./components/qa/EmptyState";
import { QueryHero } from "./components/qa/QueryHero";
import { UserQueryCard } from "./components/qa/UserQueryCard";
import { Header } from "./components/layout/Header";
import { RightRail } from "./components/layout/RightRail";
import { Sidebar } from "./components/layout/Sidebar";
import { Button } from "./components/ui/Button";
import { useAsk } from "./hooks/useAsk";
import { useHealth } from "./hooks/useHealth";
import { useHistory } from "./hooks/useHistory";
import { readJson, writeJson } from "./lib/storage";

const DEBUG_KEY = "lawbot.debug";

export default function App() {
  const ask = useAsk();
  const health = useHealth();
  const history = useHistory();
  const [draft, setDraft] = useState("");
  const [turn, setTurn] = useState<{ question: string; askedAt: Date } | null>(null);
  const [debug, setDebug] = useState(() => readJson(DEBUG_KEY, false));
  const [menu, setMenu] = useState(false);

  useEffect(() => writeJson(DEBUG_KEY, debug), [debug]);

  const submit = (q: string) => {
    setDraft(q);
    setTurn({ question: q, askedAt: new Date() });
    history.add(q);
    ask.mutate({ question: q, debug });
  };
  const home = () => {
    ask.reset();
    setTurn(null);
    setDraft("");
  };

  const data = ask.data;
  const snapshot = data?.data_snapshot ?? health.data?.data_snapshot;

  return (
    <>
      <Header debug={debug} onToggleDebug={() => setDebug((d) => !d)} onMenu={() => setMenu(true)} onHome={home} />
      <Sidebar history={history.items} onPick={submit} onClearHistory={history.clear} snapshot={snapshot} open={menu} onClose={() => setMenu(false)} />
      <div className="lg:pl-72">
        <main className="min-h-screen bg-background pt-16">
          <div className="print-root mx-auto max-w-5xl px-margin py-space-lg sm:px-space-lg lg:py-space-xl">
            <div className="flex flex-col gap-space-lg">
              <QueryHero value={draft} onChange={setDraft} onSubmit={submit} loading={ask.isPending} />
              <div className="grid grid-cols-1 gap-space-lg lg:grid-cols-12">
                <div className="flex flex-col gap-space-lg lg:col-span-8" aria-busy={ask.isPending}>
                  {!turn ? (
                    <EmptyState onPick={submit} />
                  ) : (
                    <>
                      <UserQueryCard question={turn.question} askedAt={turn.askedAt} />
                      {ask.isPending && <AnswerSkeleton />}
                      {ask.isError && (
                        <div role="alert" className="flex flex-col items-start gap-space-sm border border-crimson bg-white p-space-md">
                          <p className="font-body-md text-body-md font-medium text-crimson">답변을 가져오지 못했습니다. {ask.error.message}</p>
                          <Button onClick={() => submit(turn.question)}>다시 시도</Button>
                        </div>
                      )}
                      {data && !ask.isPending && <AnswerCard key={ask.submittedAt} data={data} question={turn.question} onPick={submit} />}
                    </>
                  )}
                  <Disclaimer />
                </div>
                <div className="lg:col-span-4">
                  <RightRail sources={data && !ask.isPending ? data.sources : null} onPick={submit} />
                </div>
              </div>
            </div>
          </div>
        </main>
      </div>
    </>
  );
}
