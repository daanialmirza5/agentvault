# Benchmarks

`results/latest.md` and `results/latest.json` are produced by running the scenario suite in
[`../scenarios`](../scenarios) under the three seeded example policies:

```powershell
cd backend
$env:AGENTVAULT_DATABASE_URL = "sqlite:///./data/bench.db"   # keep benchmark runs out of your dev database
.\.venv\Scripts\python -m app.cli evaluate --output ..\benchmarks\results
```

What the numbers mean:

* Every scenario, agent and mock tool is deterministic (fixed seeds), so the **rates** reproduce exactly
  between runs and machines. **Latencies** are wall-clock measurements on the machine that ran the
  command and will vary.
* The scenarios are synthetic and labelled by hand. A 100% score means the platform enforced the
  configured controls on these 12 cases. It says nothing about how well a real model-driven agent
  would be contained against attacks that are not in the suite.
* `strict-lockdown` and `permissive-dev` are deliberately bad policies, included to show the
  trade-off between blocking unsafe actions and disrupting legitimate work.

Metric definitions are in [`backend/app/services/evaluation/metrics.py`](../backend/app/services/evaluation/metrics.py)
and in the README's *Evaluation methodology* section.
