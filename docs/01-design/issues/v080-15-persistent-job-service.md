# Task 15 — Persistent bounded JobService

## Goal

Run expensive application use cases through one bounded, restart-aware scheduler without adding a
message broker or a second worker process.

## Limits and semantics

- Analysis executor: 4 workers; scan executor: 1 worker; side effects: 2 workers.
- One global bounded admission limit (default 100) prevents unbounded executor queues.
- Active dedupe keys are unique only while a job is queued/running; completed work may be retried.
- Progress is monotonic, cancellation is cooperative, and deadlines are checked before and after
  handler execution.
- Jobs left `running` after a process restart become `interrupted/WORKER_RESTARTED`.
- A semaphore-wrapped LLM port limits all concurrent model calls to 2 and observes the request
  deadline.
