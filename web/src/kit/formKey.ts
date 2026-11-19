import { useCallback } from "react";

// One idempotency key per form fill, kept outside the component so that if the page is rebuilt while a save is
// still in flight (for example when the session refreshes), pressing Save again sends the same key and the
// server returns the first result instead of creating a second record.
const keys = new Map<string, string>();

export function useFormKey(scope: string): { current: () => string; reset: () => void } {
  const current = useCallback(() => {
    let key = keys.get(scope);
    if (!key) {
      key = crypto.randomUUID();
      keys.set(scope, key);
    }
    return key;
  }, [scope]);
  const reset = useCallback(() => void keys.delete(scope), [scope]);
  return { current, reset };
}

/** Tests start every form fresh. */
export function resetFormKeysForTests() {
  keys.clear();
}
