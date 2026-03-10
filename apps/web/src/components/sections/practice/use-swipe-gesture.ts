import { useCallback, useRef, useState } from "react";

const SWIPE_THRESHOLD = 80;

interface SwipeGestureOptions {
  enabled: boolean;
  onSwipeRight: () => void;
  onSwipeLeft: () => void;
}

export function useSwipeGesture({ enabled, onSwipeRight, onSwipeLeft }: SwipeGestureOptions) {
  const swipeState = useRef<{ startX: number; currentX: number } | null>(null);
  const [swipeOffset, setSwipeOffset] = useState(0);

  const handlePointerDown = useCallback(
    (e: React.PointerEvent) => {
      if (!enabled) return;
      swipeState.current = { startX: e.clientX, currentX: e.clientX };
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
    },
    [enabled],
  );

  const handlePointerMove = useCallback((e: React.PointerEvent) => {
    if (!swipeState.current) return;
    swipeState.current.currentX = e.clientX;
    const dx = e.clientX - swipeState.current.startX;
    setSwipeOffset(dx);
  }, []);

  const handlePointerUp = useCallback(() => {
    if (!swipeState.current) return;
    const dx = swipeState.current.currentX - swipeState.current.startX;
    swipeState.current = null;
    setSwipeOffset(0);
    if (dx > SWIPE_THRESHOLD) {
      onSwipeRight();
    } else if (dx < -SWIPE_THRESHOLD) {
      onSwipeLeft();
    }
  }, [onSwipeRight, onSwipeLeft]);

  const swipeStyle = swipeOffset
    ? {
        transform: `translateX(${swipeOffset}px) rotate(${swipeOffset * 0.05}deg)`,
        transition: "none" as const,
      }
    : { transition: "transform 0.3s ease" as const };

  return {
    swipeOffset,
    swipeStyle,
    handlers: {
      onPointerDown: handlePointerDown,
      onPointerMove: handlePointerMove,
      onPointerUp: handlePointerUp,
    },
  };
}
