import { useState } from "react";

/**
 * Page-by-page through a list the server pages with a cursor: the cursor of every page seen
 * so far is kept, so Previous goes back without asking the server to count. `page` counts from 0.
 */
export function useCursorPages() {
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const [page, setPage] = useState(0);
  return {
    page,
    cursor: cursors[page] ?? null,
    go(to: number, next: string | null | undefined) {
      if (to > page && next) setCursors((c) => [...c.slice(0, page + 1), next]);
      setPage(Math.max(0, to));
    },
  };
}
