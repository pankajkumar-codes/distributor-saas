/** While the session is being checked (or the server is slow), "/" shows a plain loading line, never a blank page. */
export function SigninRedirectNotice({ status }: { status: string }) {
  return (
    <main className="page" aria-busy={status === "checking" || undefined}>
      <p>{status === "checking" ? "Loading…" : "We couldn't reach the server. Reload the page to try again."}</p>
    </main>
  );
}
