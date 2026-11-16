import type { ApiError } from "../api/errors";

/** The request that failed, in small print under an error, so it can be read out to support. Nothing when unknown. */
export function ErrorDetail({ error }: { error: ApiError }) {
  return error.detail ? <small className="hint"> Details: {error.detail}.</small> : null;
}
