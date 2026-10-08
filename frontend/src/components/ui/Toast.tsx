import { useCallback, useState, type ReactNode } from "react";
import { ToastCtx } from "./toastContext";

export function ToastProvider({ children }: { children: ReactNode }) {
  const [msg, setMsg] = useState<string | null>(null);
  const show = useCallback((m: string) => {
    setMsg(m);
    setTimeout(() => setMsg(null), 2500);
  }, []);
  return (
    <ToastCtx.Provider value={show}>
      {children}
      <div role="status" aria-live="polite" className="no-print">
        {msg && (
          <div className="fixed bottom-6 right-6 z-50 border border-primary bg-primary-container px-4 py-2.5 text-body-sm font-body-sm text-on-primary shadow-flat">
            {msg}
          </div>
        )}
      </div>
    </ToastCtx.Provider>
  );
}
