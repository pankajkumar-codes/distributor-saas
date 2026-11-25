import { useEffect, useRef, useState } from "react";
import type { SetURLSearchParams } from "react-router-dom";

import { useDebounced } from "./useDebounced";

/** Rows from "Load more" pages, each once: an insert between two page loads shifts the offsets. */
export function uniqueById<T extends { id: string }>(rows: T[]): T[] {
  const seen = new Set<string>();
  return rows.filter((r) => (seen.has(r.id) ? false : (seen.add(r.id), true)));
}

/**
 * A list's search box kept in ?q: typing writes the URL once it pauses, and a URL change the
 * user didn't type (Back, a link) puts its q back in the box.
 */
export function useUrlSearch(params: URLSearchParams, setParams: SetURLSearchParams) {
  const fromUrl = params.get("q") ?? "";
  const [search, setSearch] = useState(fromUrl);
  const q = useDebounced(search.trim());
  const written = useRef(q);

  // Only when the typed search settles on something new: setParams changes identity with
  // every URL change, and re-running on that would write the old q over a Back.
  useEffect(() => {
    if (written.current === q) return;
    written.current = q;
    setParams(
      (prev) => {
        if ((prev.get("q") ?? "") === q) return prev;
        const next = new URLSearchParams(prev);
        if (q) next.set("q", q);
        else next.delete("q");
        next.delete("page"); // a new search starts on its first page
        return next;
      },
      { replace: true },
    );
  }, [q, setParams]);

  useEffect(() => {
    written.current = fromUrl;
    setSearch((typed) => (typed.trim() === fromUrl ? typed : fromUrl));
  }, [fromUrl]);

  return { search, setSearch, q };
}

/** Rows per page on the v16 lists (mocks v16: a list pages so the screen never scrolls). */
export const ROWS_PER_PAGE = 5;

/** A list's page kept in ?page (1-based in the URL, 0-based here); page 1 leaves the URL clean. */
export function useUrlPage(params: URLSearchParams, setParams: SetURLSearchParams) {
  const raw = Number(params.get("page"));
  const page = Number.isInteger(raw) && raw > 1 ? raw - 1 : 0;
  const setPage = (to: number) =>
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      if (to > 0) next.set("page", String(to + 1));
      else next.delete("page");
      return next;
    });
  return { page, setPage };
}
