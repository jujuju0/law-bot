import { createContext, useContext } from "react";

export const ToastCtx = createContext<(msg: string) => void>(() => {});

/** 토스트 표시 함수를 반환한다. */
export const useToast = () => useContext(ToastCtx);
