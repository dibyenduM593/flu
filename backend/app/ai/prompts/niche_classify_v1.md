---
model: fast
effort: low
eval_set: evals/niche_100_accounts.jsonl
eval_status: not_run
---
Classify an Instagram or YouTube creator into up to 3 niches from the fixed taxonomy given below, based on the captions of their recent posts. Return niches ordered by how much of their content they cover, each with a confidence between 0 and 1. Only use taxonomy values exactly as written.
