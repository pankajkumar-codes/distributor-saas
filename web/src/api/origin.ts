// Where the API is. In production the API is a regional API Gateway endpoint in Mumbai on its own name (api.<domain>,
// built in as VITE_API_ORIGIN), not behind the CDN that serves these files: tenant data stays in India (D-094).
// Locally and in the demo there is no such variable, so the API is on the page's own origin (the dev server or nginx
// proxies /api) and nothing crosses sites.
export function apiOrigin(configured: string | undefined = import.meta.env.VITE_API_ORIGIN, own: string = window.location.origin): string {
  const value = (configured ?? "").trim().replace(/\/+$/, "");
  return value === "" ? own : value;
}

export const API_ORIGIN = apiOrigin();

// The refresh cookie is sent to the API's own site only when asked; a call to another origin needs "include".
export const API_CREDENTIALS: RequestCredentials = API_ORIGIN === window.location.origin ? "same-origin" : "include";
