/**
 * Role checks the SPA uses to hide actions a role can't take. The server is the authority and
 * refuses them anyway (docs/PERMISSIONS.md); these only keep read-only roles, such as CA and
 * support view, from seeing buttons that would end in a 404 [Staff 2, #98].
 */
const CATALOG_EDITORS = new Set(["owner", "admin", "billing"]); // catalog.edit
const RATE_CONFIRMERS = new Set(["owner", "admin"]); // L3-3, a rule inside catalog.edit

export const canEditCatalog = (role: string) => CATALOG_EDITORS.has(role);
export const canConfirmRates = (role: string) => RATE_CONFIRMERS.has(role);

const DOCUMENT_EDITORS = new Set(["owner", "admin", "billing"]); // documents.create
export const canCreateDocuments = (role: string) => DOCUMENT_EDITORS.has(role);

const UPLOADERS = new Set(["owner", "admin"]); // uploads.create
const UPLOAD_VIEWERS = new Set(["owner", "admin", "ca"]); // uploads.view; billing gets a 404
export const canUpload = (role: string) => UPLOADERS.has(role);
export const canViewUploads = (role: string) => UPLOAD_VIEWERS.has(role);

const RETURN_PREPARERS = new Set(["owner", "admin", "ca"]); // returns.prepare; billing gets a 404
export const canPrepareReturns = (role: string) => RETURN_PREPARERS.has(role);

const RETURN_LOCKERS = new Set(["owner", "admin", "ca"]); // returns.lock: mark filed
// returns.view: the same roles, plus a support session reading a business that granted access.
export const canViewReturns = (role: string) => canPrepareReturns(role) || role === "support";

export const canLockReturns = (role: string) => RETURN_LOCKERS.has(role);
export const canUnlockReturns = (role: string) => role === "owner"; // returns.unlock
