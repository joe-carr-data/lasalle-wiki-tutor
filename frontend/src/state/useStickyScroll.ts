import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Sticky-bottom scroll behavior for chat threads.
 *
 * Design intent (from user feedback): the streaming cursor must NEVER
 * fight a manual scroll. Concretely:
 *
 * - On every contentTick, if "sticky" is armed, we pin the scroll to
 *   the bottom so streaming text stays in view.
 * - "Sticky" is *released* by any explicit user-initiated scroll
 *   gesture: wheel up, touch swipe, Page Up / arrow / Home key. Once
 *   released, no programmatic scroll happens — the user's reading
 *   position is sacred until they ask to come back down.
 * - "Sticky" is *re-armed* in two ways: the user scrolls all the way
 *   back to the bottom themselves, OR they click the floating
 *   "Jump to latest" button (`scrollToBottom`).
 *
 * The previous version used a 120 px threshold on every scroll event
 * to set sticky from the current position, which meant a tiny manual
 * scroll up still landed within threshold and the next delta yanked
 * the user back down. This version reads user *intent*, not just
 * position.
 */
export function useStickyScroll<T extends HTMLElement>(opts: {
  /** A monotonic value that bumps each time content is appended. */
  contentTick: unknown;
}) {
  const ref = useRef<T | null>(null);
  const stickyRef = useRef(true);
  const programmaticScrollRef = useRef(false);
  const programmaticTimerRef = useRef<number | null>(null);
  const [atBottom, setAtBottom] = useState(true);

  const measureDistance = useCallback((): number => {
    const el = ref.current;
    if (!el) return 0;
    return el.scrollHeight - el.scrollTop - el.clientHeight;
  }, []);

  const beginProgrammaticScroll = useCallback((ms = 0) => {
    programmaticScrollRef.current = true;
    if (programmaticTimerRef.current !== null) {
      window.clearTimeout(programmaticTimerRef.current);
      programmaticTimerRef.current = null;
    }
    if (ms <= 0) {
      requestAnimationFrame(() => {
        programmaticScrollRef.current = false;
      });
      return;
    }
    programmaticTimerRef.current = window.setTimeout(() => {
      programmaticScrollRef.current = false;
      programmaticTimerRef.current = null;
    }, ms);
  }, []);

  // Bottom re-arms sticky. Leaving bottom by user scroll disarms sticky.
  // This is the key invariant that prevents yank-back races.
  const onScroll = useCallback(() => {
    const distance = measureDistance();
    // 4 px tolerance for sub-pixel rounding.
    const isAtBottom = distance <= 4;
    setAtBottom(isAtBottom);
    if (isAtBottom) {
      stickyRef.current = true;
      // If a smooth programmatic scroll just reached bottom, we can stop
      // suppressing user-intent detection now.
      programmaticScrollRef.current = false;
    } else if (!programmaticScrollRef.current) {
      stickyRef.current = false;
    }
  }, [measureDistance]);

  // Keep explicit user-intent handling for immediate release on wheel/key/touch.
  const releaseOnUpward = useCallback(() => {
    // If the user is already off the bottom, they clearly want to read
    // earlier content; release sticky so subsequent deltas don't yank.
    if (measureDistance() > 4) {
      stickyRef.current = false;
    }
  }, [measureDistance]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    function onWheel(e: WheelEvent) {
      // Wheel events with negative deltaY are explicit upward intent.
      // Any positive deltaY that doesn't reach the bottom also implies
      // active reading — handled by onScroll's at-bottom check.
      if (e.deltaY < 0) {
        stickyRef.current = false;
      } else {
        releaseOnUpward();
      }
    }
    function onTouchMove() {
      releaseOnUpward();
    }
    function onKey(e: KeyboardEvent) {
      // Keyboard navigation that scrolls the thread.
      const k = e.key;
      if (
        k === "ArrowUp" ||
        k === "PageUp" ||
        k === "Home" ||
        k === "ArrowDown" ||
        k === "PageDown" ||
        k === "End"
      ) {
        // Defer to next frame so the browser has applied the scroll.
        requestAnimationFrame(releaseOnUpward);
      }
    }

    el.addEventListener("wheel", onWheel, { passive: true });
    el.addEventListener("touchmove", onTouchMove, { passive: true });
    el.addEventListener("scroll", onScroll, { passive: true });
    el.addEventListener("keydown", onKey);
    onScroll();

    return () => {
      if (programmaticTimerRef.current !== null) {
        window.clearTimeout(programmaticTimerRef.current);
      }
      el.removeEventListener("wheel", onWheel);
      el.removeEventListener("touchmove", onTouchMove);
      el.removeEventListener("scroll", onScroll);
      el.removeEventListener("keydown", onKey);
    };
  }, [onScroll, releaseOnUpward]);

  // On every content tick, pin to the bottom IFF sticky is armed.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (!stickyRef.current) return;
    beginProgrammaticScroll();
    el.scrollTop = el.scrollHeight;
  }, [beginProgrammaticScroll, opts.contentTick]);

  const scrollToBottom = useCallback((smooth = true) => {
    const el = ref.current;
    if (!el) return;
    beginProgrammaticScroll(smooth ? 700 : 0);
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "auto" });
    stickyRef.current = true;
    setAtBottom(true);
  }, [beginProgrammaticScroll]);

  return { ref, atBottom, scrollToBottom };
}
