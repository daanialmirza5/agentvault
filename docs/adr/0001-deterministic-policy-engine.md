# ADR 0001: A deterministic, model-independent policy engine with deny-overrides

**Status:** accepted

## Context
Agents propose tool calls. If the code that authorises those calls takes anything the agent writes as
input, a manipulated model can authorise itself. That includes free text, "this is safe" claims and
suggested risk levels.

## Decision
* Policies are data (JSON documents validated by Pydantic): no code, no regular expressions (`glob`
  is the only pattern operator).
* `evaluate()` is a pure function of (policy document, tool definition, validated arguments,
  execution context). Agent claims are recorded in the audit log but are not a parameter.
* Precedence: unknown tool → deny; invalid arguments → deny; matched rules resolve **deny >
  require_approval > allow**; otherwise the policy default; finally a tool that declares
  `requires_approval` can never come out as a plain allow.
* `priority` only orders rules that share an effect, to choose which rule is reported as the deciding one.

## Consequences
* Rule order cannot accidentally weaken a deny, which makes conflicts easy to reason about. The
  editor reports overlapping and shadowed rules as information, not as errors.
* Expressing "allow X unless Y" requires a deny rule for Y, rather than an allow rule with higher priority.
* Policy versions are immutable and every decision stores `policy_id@version`, so any decision can be
  reproduced exactly.
