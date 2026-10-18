"""Built-in example policies. They are seeded data, not hard-coded engine behaviour; every one
of them can be edited (creating a new version) or replaced in the policy editor."""

from __future__ import annotations

from typing import Any

BASELINE: dict[str, Any] = {
    "id": "baseline",
    "name": "Baseline support policy",
    "description": "Least-privilege default for a customer-support agent: reads allowed, outbound "
    "communication and record changes need approval, admin and protected data denied.",
    "document": {
        "default_effect": "deny",
        "rules": [
            {
                "id": "allow-low-risk-reads",
                "effect": "allow",
                "priority": 100,
                "description": "Read-only tools with low or medium risk are permitted.",
                "match": {"operations": ["read"], "risk_levels": ["low", "medium"]},
            },
            {
                "id": "deny-restricted-documents",
                "effect": "deny",
                "priority": 10,
                "description": "Documents whose ID starts with 'restricted-' are off limits to agents.",
                "match": {
                    "tool_ids": ["docs.read"],
                    "arguments": [{"path": "doc_id", "op": "prefix", "value": "restricted-"}],
                },
            },
            {
                "id": "allow-email-drafts",
                "effect": "allow",
                "priority": 100,
                "description": "Drafting email is local to the mailbox and permitted.",
                "match": {"tool_ids": ["email.draft"]},
            },
            {
                "id": "approve-outbound-email",
                "effect": "require_approval",
                "priority": 50,
                "description": "Sending email leaves the organisation and needs a human decision.",
                "match": {"tool_ids": ["email.send"]},
            },
            {
                "id": "allow-support-tickets",
                "effect": "allow",
                "priority": 100,
                "description": "Agents may open support tickets.",
                "match": {"categories": ["support"]},
            },
            {
                "id": "deny-agent-p0-tickets",
                "effect": "deny",
                "priority": 20,
                "description": "P0 incidents page on-call engineers; agents may not open them.",
                "match": {
                    "tool_ids": ["ticket.create"],
                    "arguments": [{"path": "priority", "op": "eq", "value": "p0"}],
                },
            },
            {
                "id": "approve-crm-updates",
                "effect": "require_approval",
                "priority": 50,
                "description": "Changes to customer records need a human decision.",
                "match": {"tool_ids": ["crm.update_record"]},
            },
            {
                "id": "deny-protected-crm-fields",
                "effect": "deny",
                "priority": 10,
                "description": "Credit limits and account status are protected fields.",
                "match": {
                    "tool_ids": ["crm.update_record"],
                    "arguments": [{"path": "field", "op": "in", "value": ["credit_limit", "status"]}],
                },
            },
            {
                "id": "deny-system-accounts",
                "effect": "deny",
                "priority": 10,
                "description": "Internal system accounts (CUST-0xxx) are protected resources.",
                "match": {
                    "tool_ids": ["crm.update_record"],
                    "arguments": [{"path": "customer_id", "op": "prefix", "value": "CUST-0"}],
                },
            },
            {
                "id": "deny-admin-tools",
                "effect": "deny",
                "priority": 1,
                "description": "Administrative bulk operations are never available to agents.",
                "match": {"categories": ["admin"]},
            },
            {
                "id": "approve-production-writes",
                "effect": "require_approval",
                "priority": 40,
                "description": "Any mutating call in the production environment needs approval.",
                "match": {"environments": ["production"], "operations": ["write"]},
            },
        ],
    },
}

STRICT: dict[str, Any] = {
    "id": "strict-lockdown",
    "name": "Strict lockdown",
    "description": "Deliberately over-restrictive policy: only document reads are allowed and every "
    "write needs approval. Used to measure legitimate-task disruption.",
    "document": {
        "default_effect": "deny",
        "rules": [
            {
                "id": "allow-document-reads",
                "effect": "allow",
                "priority": 100,
                "description": "Only the document store may be read.",
                "match": {"tool_ids": ["docs.read"]},
            },
            {
                "id": "deny-restricted-documents",
                "effect": "deny",
                "priority": 10,
                "description": "Restricted documents are off limits.",
                "match": {
                    "tool_ids": ["docs.read"],
                    "arguments": [{"path": "doc_id", "op": "prefix", "value": "restricted-"}],
                },
            },
            {
                "id": "approve-all-writes",
                "effect": "require_approval",
                "priority": 50,
                "description": "Every mutating tool requires approval.",
                "match": {"operations": ["write"]},
            },
            {
                "id": "deny-admin-tools",
                "effect": "deny",
                "priority": 1,
                "description": "Administrative tools are denied.",
                "match": {"categories": ["admin"]},
            },
        ],
    },
}

PERMISSIVE: dict[str, Any] = {
    "id": "permissive-dev",
    "name": "Permissive development",
    "description": "Default-allow policy that only relies on tool-level approval flags. Included to "
    "show what a weak policy lets through.",
    "document": {
        "default_effect": "allow",
        "rules": [
            {
                "id": "deny-production-writes",
                "effect": "deny",
                "priority": 1,
                "description": "Mutating calls are not allowed in the production environment.",
                "match": {"environments": ["production"], "operations": ["write"]},
            },
        ],
    },
}

DEFAULT_POLICIES = [BASELINE, STRICT, PERMISSIVE]
