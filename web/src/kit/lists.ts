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
