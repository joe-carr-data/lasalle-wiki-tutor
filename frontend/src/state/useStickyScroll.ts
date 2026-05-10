import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Sticky-bottom scroll behavior for chat threads.
 *
 * - While the user is within `threshold` px of the bottom, every new
 *   render pulls the view to the bottom (during streaming this means
 *   tokens roll out smoothly).
 * - If the user scrolls up, we *don't* yank them — the sticky flag
 *   flips off until they scroll back down within the threshold or
 *   click the "jump to latest" affordance.
 *
 * Returns: a ref to attach to the scroll container, an ``atBottom``
 * flag for the UI, and a ``scrollToBottom`` callback for the jump
 * button.
 */
export function useStickyScroll<T extends HTMLElement>(opts: {
  threshold?: number;
  /** A monotonic value that bumps each time content is appended. */
  contentTick: unknown;
}) {
  const threshold = opts.threshold ?? 120;
  const ref = useRef<T | null>(null);
  const stickyRef = useRef(true);
  const [atBottom, setAtBottom] = useState(true);

  const update = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    const isAtBottom = distance <= threshold;
    stickyRef.current = isAtBottom;
    setAtBottom(isAtBottom);
  }, [threshold]);

  // Observe scroll so the sticky flag tracks the user's intent.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.addEventListener("scroll", update, { passive: true });
    update();
    return () => el.removeEventListener("scroll", update);
  }, [update]);

  // On every content tick (new delta, new turn) — if sticky, scroll.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (!stickyRef.current) return;
    el.scrollTop = el.scrollHeight;
  }, [opts.contentTick]);

  const scrollToBottom = useCallback((smooth = true) => {
    const el = ref.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "auto" });
    stickyRef.current = true;
    setAtBottom(true);
  }, []);

  return { ref, atBottom, scrollToBottom };
}
