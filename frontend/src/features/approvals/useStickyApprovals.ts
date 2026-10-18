import { useCallback, useState } from "react";

import type { Approval } from "../../types/api";

/**
 * Pending approvals plus the ones decided in this view. Decided cards keep their key, so React
 * keeps the same card instance (and its result message) after the refreshed pending list drops them.
 */
export function useStickyApprovals(pending: Approval[]): [Approval[], (decided: Approval) => void] {
  const [decided, setDecided] = useState<Approval[]>([]);
  const onDecided = useCallback(
    (a: Approval) => setDecided((list) => [a, ...list.filter((x) => x.id !== a.id)].slice(0, 10)),
    [],
  );
  const recent = decided.filter((d) => !pending.some((p) => p.id === d.id));
  return [[...pending, ...recent], onDecided];
}
