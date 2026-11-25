/**
 * Previous / Next under a list (mocks v16: lists use pages so a screen never scrolls).
 * `page` counts from 0. With `total` unknown (the server only says whether more exist),
 * pass `hasMore` instead and the text reads "Rows 6–10".
 */
export function Pager({
  page,
  size,
  shown,
  total,
  hasMore,
  noun,
  onPage,
}: {
  page: number;
  size: number;
  shown: number;
  total?: number;
  hasMore?: boolean;
  noun: string;
  onPage: (page: number) => void;
}) {
  const from = page * size + 1;
  const to = page * size + shown;
  const more = total !== undefined ? to < total : !!hasMore;
  const text = shown === 0 ? `No ${noun}` : total !== undefined ? `${from}–${to} of ${total} ${noun}` : `${noun[0].toUpperCase()}${noun.slice(1)} ${from}–${to}`;
  return (
    <nav className="pager" aria-label={`Pages of ${noun}`}>
      <span aria-live="polite">{text}</span>
      <span className="row-actions">
        <button type="button" className="btn btn-secondary btn-sm" disabled={page === 0} onClick={() => onPage(page - 1)}>
          Previous
        </button>
        <button type="button" className="btn btn-secondary btn-sm" disabled={!more} onClick={() => onPage(page + 1)}>
          Next
        </button>
      </span>
    </nav>
  );
}
