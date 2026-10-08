import { useMutation } from "@tanstack/react-query";
import { ask } from "../api/client";
import type { AskRequest } from "../api/types";

/** /ask 호출 mutation. */
export function useAsk() {
  return useMutation({ mutationFn: (req: AskRequest) => ask(req) });
}
