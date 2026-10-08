import { useQuery } from "@tanstack/react-query";
import { getHealth } from "../api/client";

/** /health 30초 주기 조회. */
export function useHealth() {
  return useQuery({ queryKey: ["health"], queryFn: getHealth, refetchInterval: 30_000, retry: false });
}
