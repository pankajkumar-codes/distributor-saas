import { Link } from "react-router-dom";

import { TopBar } from "./TopBar";

/**
 * A signed-in member opened a page their role does not include. This says so, instead of the
 * "couldn't find that page" shown for a wrong link or a business that is not theirs (that one
 * stays vague on purpose, LLD-1 §11.2: it must not reveal which businesses exist).
 */
export function NoAccess({ businessId }: { businessId: string }) {
  return (
    <>
      <TopBar />
      <main className="page">
        <h1>You don't have access to this page</h1>
        <p>Your role in this business doesn't include it. Ask an owner or admin if you need it.</p>
        <Link to={`/b/${businessId}/home`}>Back to Home</Link>
      </main>
    </>
  );
}
