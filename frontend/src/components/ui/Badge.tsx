import type { ReactNode } from "react";

type Tone = "primary" | "neutral" | "teal" | "crimson" | "spruce";
const TONES: Record<Tone, string> = {
  primary: "bg-primary-container text-on-primary",
  neutral: "bg-surface-container-high text-on-surface",
  teal: "bg-teal text-white",
  crimson: "bg-crimson text-white",
  spruce: "bg-spruce-bg text-spruce",
};

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`inline-flex items-center gap-1 px-2 py-0.5 font-label-sm text-label-sm ${TONES[tone]}`}>{children}</span>;
}

export function Icon({ name, className = "" }: { name: string; className?: string }) {
  return (
    <span aria-hidden="true" className={`material-symbols-outlined ${className}`}>
      {name}
    </span>
  );
}
