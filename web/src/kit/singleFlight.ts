import { useRef } from "react";

/**
 * One request at a time for a button. A mutation's `isPending` reaches the page a moment after the click (the query
 * library batches its updates), so a quick second press still gets through the disabled check. This flag is set
 * synchronously: `start` gets a `done` to call when the request settles (use it as `onSettled`).
 */
export function useSingleFlight(): (start: (done: () => void) => void) => void {
  const busy = useRef(false);
  return (start) => {
    if (busy.current) return;
    busy.current = true;
    start(() => {
      busy.current = false;
    });
  };
}
