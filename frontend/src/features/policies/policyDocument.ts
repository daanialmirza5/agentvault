import type { Json, PolicyDocument } from "../../types/api";

/** Removes empty optional match fields so the backend receives a clean document. */
export function normaliseDocument(doc: PolicyDocument): PolicyDocument {
  return {
    default_effect: doc.default_effect,
    rules: doc.rules.map((r) => {
      const match: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(r.match)) {
        if (v === null || v === undefined || (Array.isArray(v) && v.length === 0 && k !== "arguments")) continue;
        match[k] = v;
      }
      return { ...r, match };
    }),
  };
}

/** Condition values are typed as JSON when they parse (numbers, lists, quoted strings), else as plain text. */
export function parseConditionValue(text: string): Json {
  const trimmed = text.trim();
  if (trimmed === "") return null;
  try {
    return JSON.parse(trimmed) as Json;
  } catch {
    return trimmed;
  }
}
