import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "ghost";
const STYLES: Record<Variant, string> = {
  primary: "bg-primary-container text-on-primary hover:bg-secondary disabled:opacity-50 disabled:hover:bg-primary-container",
  secondary: "border border-primary-container bg-white text-primary-container hover:bg-background",
  ghost: "text-secondary hover:underline",
};

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
}

export function Button({ variant = "primary", className = "", type = "button", ...rest }: Props) {
  return (
    <button
      type={type}
      className={`inline-flex items-center justify-center gap-1.5 px-4 py-2.5 font-label-md text-label-md transition-colors ${STYLES[variant]} ${className}`}
      {...rest}
    />
  );
}
