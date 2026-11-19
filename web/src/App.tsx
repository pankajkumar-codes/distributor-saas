import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { createBrowserRouter, RouterProvider } from "react-router-dom";

import { transient } from "./api/errors";
import { AuthProvider } from "./auth/AuthProvider";
import { clearOnSessionChange } from "./auth/userCache";
import { SkipLink } from "./kit/SkipLink";
import { routes } from "./routes";

export function App() {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          // A read retries twice (after 0.5 s, then 1 s) only when the server or the network failed; a 4xx won't change.
          queries: { retry: (count, e) => count < 2 && transient(e), retryDelay: (n) => Math.min(500 * 2 ** n, 2000) },
          mutations: { retry: false },
        },
      }),
  );
  const [router] = useState(() => createBrowserRouter(routes));
  useEffect(() => clearOnSessionChange(queryClient), [queryClient]);
  return (
    <QueryClientProvider client={queryClient}>
      <SkipLink />
      <AuthProvider>
        <RouterProvider router={router} />
      </AuthProvider>
    </QueryClientProvider>
  );
}
