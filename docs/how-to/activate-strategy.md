# Validate and activate an opportunity strategy

Production strategy state is deliberately separate from analysis-engine configuration.

## 1. Produce reproducible evidence

Research data must come through the Data Gateway and record Provider traces, schema/gateway version,
adjustment method, point-in-time listing intervals, snapshot hash and code/config identity. For
`mean_reversion_v1`, use the fixed train/validation/OOS windows and gates in
[`docs/research/roadmap.md`](../research/roadmap.md).

Passing evidence creates an immutable `ExperimentManifest` and moves a candidate to `validated`
only. It does not approve or activate it.

## 2. Review and approve

The Owner reviews the report and manifest hash, then calls the Owner-only approve endpoint documented
in OpenAPI:

```text
POST /api/v1/admin/strategies/{name}/{version}/approve
```

Browser writes require a valid HttpOnly session, exact Origin and `X-CSRF-Token`. Do not automate
approval from a research job.

## 3. Activate explicitly

After approval, the Owner calls:

```text
POST /api/v1/admin/strategies/{name}/{version}/activate
```

Activation is atomic per strategy name. The production selected name must match strict configuration.
Previous active versions are replaced; no draft/validated candidate can be loaded by the scanner.

## 4. Run and inspect a scan

```text
POST /api/v1/scans
GET  /api/v1/jobs/{job_id}
GET  /api/v1/opportunities
```

The scan cache identity includes strategy/version, manifest, factor version, data date and config
hash. Public opportunities only read the latest completed result for the exact active version and
never compute during GET.

## 5. Retire

Use the Owner-only retire endpoint when the evidence is obsolete. With no active version,
opportunities return an empty result plus `NO_ACTIVE_STRATEGY`; this is preferable to stale fallback.
