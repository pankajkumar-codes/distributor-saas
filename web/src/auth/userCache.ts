import type { QueryClient } from "@tanstack/react-query";

import { onSessionChange } from "./session";

/**
 * Cached answers belong to one user: drop them when the session ends or may now be
 * someone else's (a sign-in here or in another tab), so the next person in this tab never
 * sees the last one's businesses. A plain token refresh keeps them.
 */
export function clearOnSessionChange(client: QueryClient): () => void {
  return onSessionChange((signedIn, change) => {
    if (!signedIn || change === "new") client.clear();
  });
}
