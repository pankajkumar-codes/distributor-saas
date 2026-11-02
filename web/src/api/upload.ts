import { toApiError, type ApiError } from "./errors";

export type PresignedPost = { url: string; fields: Record<string, string> };

/**
 * Sends a file to a presigned POST (H-4): the policy's fields first, the file last, as S3
 * requires. Storage gets no Authorization header and no cookies: the policy is the only
 * permission, and the access token never leaves the app's own API. Rejects with an
 * ApiError: status 0 when storage was unreachable (worth retrying), else storage's status.
 */
export async function uploadTo(target: PresignedPost, file: File): Promise<void> {
  const form = new FormData();
  for (const [name, value] of Object.entries(target.fields)) form.append(name, value);
  form.append("file", file, file.name); // the key is fixed by the policy; the name is only a courtesy
  let response: Response;
  try {
    response = await globalThis.fetch(target.url, { method: "POST", body: form, credentials: "omit" });
  } catch {
    throw toApiError(undefined, undefined);
  }
  if (!response.ok) {
    let body: unknown;
    try {
      body = await response.json(); // the local dev route answers in the platform shape; S3 in XML
    } catch {
      body = undefined;
    }
    throw toApiError(response, body) satisfies ApiError;
  }
}
