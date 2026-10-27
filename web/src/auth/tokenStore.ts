// The access token lives in this module only, never in localStorage or sessionStorage
// (LLD-1 §11.3), so a reload signs the tab out until /auth/refresh lands in S1.
let token: string | null = null;
let expiresAt = 0;

export const tokenStore = {
  set(accessToken: string, expiresInSeconds: number, now = Date.now()) {
    token = accessToken;
    expiresAt = now + expiresInSeconds * 1000;
  },
  get(now = Date.now()): string | null {
    return token !== null && now < expiresAt ? token : null;
  },
  clear() {
    token = null;
    expiresAt = 0;
  },
};
