# 90-second demo script

Setup (before recording): `.\scripts\setup.ps1`, then `.\scripts\dev.ps1`. Open http://127.0.0.1:5173.
Optionally run one evaluation first so the dashboard has data.

| Time | Screen | Action | What to say |
|---|---|---|---|
| 0:00 | Dashboard | — | "AgentVault sits between an AI agent and its tools. Every tool call goes through a schema check, a deterministic policy, and if needed a human, and every step is recorded." |
| 0:10 | Executions | Launch **Follow up with an enterprise customer** under *baseline* | "This is a scripted agent with no API key. It looks up a customer, drafts an email and asks to send it." |
| 0:20 | Execution detail → Timeline | Click *Policy decision: require approval* | "Reads were allowed. Sending email matched a require-approval rule, so the run paused. Here's the exact rule, the arguments and the decision ID." |
| 0:32 | Approval card | Point at the claims warning, click **Approve** | "The agent claims the email is safe. That claim is logged but never used. I approve this exact action: the approval is bound to this execution and this action hash." |
| 0:42 | Timeline / Sandbox effects | Show *Approval granted → Tool executed*, the outbox has 1 item | "It resumed and sent the email to a mock outbox. Nothing leaves the sandbox." |
| 0:50 | Verify audit trail | Click it | "The event log is append-only and hash-chained, and the completeness checks pass." |
| 0:57 | Replay | Simulate under *strict lockdown*, **Jump to divergence** | "Replay re-runs the same execution in isolation under a stricter policy. The first divergence is right here: the CRM lookup is now denied." |
| 1:10 | Evaluation results | Scroll the metrics table | "Twelve deterministic scenarios across three policies. Strict blocks every unsafe action but also 80% of legitimate ones. Permissive lets a third of unsafe actions through. Blocking more is not automatically safer." |
| 1:25 | Export | Click **Results Markdown** | "And every result exports with the event IDs that back it." |
