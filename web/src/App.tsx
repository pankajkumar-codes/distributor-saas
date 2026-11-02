import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { createBrowserRouter, RouterProvider } from "react-router-dom";

import { transient } from "./api/errors";
import { AuthProvider } from "./auth/AuthProvider";
import { clearOnSessionChange } from "./auth/userCache";
import { routes } from "./routes";

export function App() {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          // A read retries twice only when the server or the network failed; a 4xx won't change.
          queries: { retry: (count, e) => count < 2 && transient(e) },
          mutations: { retry: false },
        },
      }),
  );
  const [router] = useState(() => createBrowserRouter(routes));
  useEffect(() => clearOnSessionChange(queryClient), [queryClient]);
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <RouterProvider router={router} />
      </AuthProvider>
    </QueryClientProvider>
  );
}
