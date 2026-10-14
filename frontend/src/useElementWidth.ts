import { type RefObject, useEffect } from "react";

/** Calls `onWidth` with the element's content width whenever it is resized (if ResizeObserver exists). */
export function useElementWidth(ref: RefObject<Element | null>, onWidth: (width: number) => void): void {
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver((entries) => onWidth(Math.round(entries[0]?.contentRect.width ?? 0)));
    observer.observe(el);
    return () => observer.disconnect();
    // onWidth is expected to be stable (a state setter or a ref-backed callback).
  }, [ref, onWidth]);
}
