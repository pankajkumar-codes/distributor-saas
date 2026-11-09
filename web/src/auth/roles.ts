/**
 * Role checks the SPA uses to hide actions a role can't take. The server is the authority and
 * refuses them anyway (docs/PERMISSIONS.md); these only keep read-only roles, such as CA and
 * support view, from seeing buttons that would end in a 404 [Staff 2, #98].
 */
const CATALOG_EDITORS = new Set(["owner", "admin", "billing"]); // catalog.edit
const RATE_CONFIRMERS = new Set(["owner", "admin"]); // L3-3, a rule inside catalog.edit

export const canEditCatalog = (role: string) => CATALOG_EDITORS.has(role);
export const canConfirmRates = (role: string) => RATE_CONFIRMERS.has(role);
