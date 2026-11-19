/**
 * "Loading…" for a page's first read. A failed read is tried again twice on its own (see App), which takes a few
 * seconds, so after the first failure it says so instead of looking stuck; the error message and Try again
 * follow if the retries fail too.
 */
export function Loading({ query }: { query: { failureCount: number } }) {
  return (
    <p aria-busy="true">{query.failureCount > 0 ? "Having trouble loading. Trying again…" : "Loading…"}</p>
  );
}
