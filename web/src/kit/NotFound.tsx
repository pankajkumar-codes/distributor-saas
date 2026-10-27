import { Link } from "react-router-dom";

// One page for "doesn't exist" and "not yours" alike, so it reveals nothing (LLD-1 §11.2).
export function NotFound() {
  return (
    <main className="page">
      <h1>We couldn't find that page</h1>
      <p>The link may be wrong, or it belongs to a business you don't have access to.</p>
      <Link to="/signin">Go to sign-in</Link>
    </main>
  );
}
