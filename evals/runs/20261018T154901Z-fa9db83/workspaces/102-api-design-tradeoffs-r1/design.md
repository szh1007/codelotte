# Batch payments: API shape decision

Scope: how clients submit up to 500 transfers (requirements.md). Compares
(A) `POST /v1/batches` with a JSON array, and (B) one request per transfer under
`POST /v1/transfers`.

**Decision: A is the main path.** B is kept, but only as the degenerate case
(a batch of one) for single transfers and for repairing individual failed items.

## 1. The two shapes

**A — batch endpoint**

```http
POST /v1/batches
Idempotency-Key: 6f0c...e1        # optional, batch envelope only
{ "items": [ { "idempotency_key": "u-8412", "amount": "12.50", "currency": "EUR",
               "iban": "..." }, ... ] }   # 1..500 items

202 Accepted
{ "batch_id": "bch_01J...", "status": "processing",
  "counts": { "received": 500, "accepted": 497, "rejected": 3 },
  "items_url": "/v1/batches/bch_01J.../items",
  "reason": null }
```

Results, progress and errors are all read back per batch:
`GET /v1/batches/{batch_id}` (counters) and
`GET /v1/batches/{batch_id}/items?cursor=...&limit=100` (per-item status).
Every item carries its own `idempotency_key`; that key, not the batch, is the
unit of exactly-once.

**B — one request per transfer**

```http
POST /v1/transfers
Idempotency-Key: u-8412
{ "amount": "12.50", ... }        ->  201 { "transfer_id": "tr_...", "status": "settled" }
```

500 items = 500 requests. Each is independently idempotent and independently
retryable, but the client owns all aggregation.

Both shapes reuse the same item-level idempotency semantics, so switching shape
never changes money movement rules: key scope is `(client_id, idempotency_key)`,
retention 90 days, replay of a key returns the original outcome, and the same key
with a materially different payload is a hard `409 idempotency_key_reuse` (never
overwrite).

## 2. Trade-offs

| Axis | A: `POST /v1/batches` | B: one request per transfer |
|---|---|---|
| Latency (500 items) | 1 network round trip, ~100–200 KB body, submit ack in ~300–800 ms p95. | 500 trips: ~40 s if sequential at 80 ms RTT; ~1–4 s best case with 6 parallel connections/host (HTTP/1.1), worse on mobile radio wake-ups; realistically minutes with per-client rate limits. Cannot meet the 2 s progress requirement without a client-side batch orchestration layer. |
| Progress feedback (2 s) | Native: `202` + `batch_id` in <2 s, then counters on `GET /v1/batches/{id}` (or webhook) give real % complete. | No aggregate to report. Client must invent progress by counting its own futures; a crash loses it. |
| Retries | One retryable unit for the submission envelope. A retried body is safe because each item dedupes on its own key — a partial batch that partially applied on attempt 1 settles correctly on attempt 2. Retry storms are also 1 request instead of 500. | Retry granularity is excellent (retry only the failed transfer), but the client must persist 500 keys and 500 in-flight states before sending; without an outbox this is where double-charges and lost items happen. |
| Idempotency | Per-item keys (correctness) + optional batch key (dedupes a duplicate submission envelope, returns the same `batch_id`). Both are needed; the batch key alone would be wrong, since a client that retries with a corrected body must still not re-execute already-applied items. | Single key per request — simplest possible model, but there is no batch identity to dedupe a whole retried submission against. |
| Partial failure | First-class: structural validation is per item (bad amount → item `422`, batch still processes). Whole-request `400` only for envelope errors (malformed JSON, >500 items, unknown field under strict mode). Per-item `status`/`error.code`/`error.retryable`. | Also per item, but the client must reconstruct the failed subset from 500 responses, and a single failed connection is indistinguishable from a declined transfer unless it kept every response body. |
| Pagination | `GET /v1/batches/{id}/items` with opaque cursor, `limit` ≤ 200, stable order by item index (not arrival order), `has_more`/`next_cursor`. Counters endpoint gives cheap totals without paging. | Doesn't apply at the API; "list batch results" becomes a client-side join over 500 `GET /v1/transfers/{id}` calls. Requirement 6 has no server-side answer. |
| Versioning | One envelope to version (`/v1` → `/v2`), one contract for item schema, error schema, and paging. Breaking change = new major path, additive fields stay in `/v1` (clients must ignore unknown fields and treat enums as open). | 500× the surface to keep compatible; paging and list filters also version independently. Cheaper per-endpoint, more places to get it wrong. |
| Payload/limits | Bounded, checkable up front: 500 items, 1 MiB body, `413`/`400` before any money moves. | No payload risk, but 500 independent rate-limit decisions (`429` storms) and 500 chances to be throttled mid-batch. |
| Ops/debuggability | One batch id in logs and support tooling; whole-batch replay and audit. | Correlation only by client-supplied grouping field; support must stitch ids by hand. |
| Simplicity | Bigger request contract, async result model, two resources. | Smaller contract, synchronous per-transfer result, trivial for a human/CLI to use. |

B's real advantages — smallest contract, immediate synchronous result for one
transfer, no async polling — are all preserved by keeping
`POST /v1/transfers` for N=1. What B cannot do is satisfy the 2 s progress and
batch-results-pagination requirements, and it pushes exactly-once bookkeeping
onto every client. That is where the money risk lives, so the server should own
it.

## 3. Item state machine (both shapes)

`received → validated → submitted → settled | declined` (terminal) and
`unknown → resolved`, where `unknown` means "we sent it and did not learn the
outcome". An item in `unknown` is **never** reported as failed-and-retryable —
that is the exact path to a double charge. `unknown` is cleared only by
reconciliation against the scheme/ledger, after which it becomes `settled` or
`declined`. Clients see `pending` for both `submitted` and `unknown`.

## 4. Retry flow

1. **Before sending**, the client derives `idempotency_key` per logical payment
   (UUIDv7 or equivalent) and persists item + key in a local outbox. Keys are
   never regenerated for the same payment intent.
2. **Submit** `POST /v1/batches` with the outbox items.
3. **Transient failure** — timeout, connection reset, `429`, `500/502/503/504`:
   the outcome is unknown, so retry the *same body with the same keys*.
   Backoff 0.5 s → 1 s → 2 s → 4 s → 8 s → 16 s (cap 30 s), full jitter, max 6
   attempts; honor `Retry-After` on `429`. `202` or `200` ends the loop.
4. **Server dedupe on retry**: for each item, the keyed write is a conditional
   insert. Replay hits the existing record and returns its current status; the
   transfer is never re-executed. The optional batch key makes the retry return
   the original `batch_id` instead of a new one, so the client does not lose
   progress tracking.
5. **Lost response recovery**: if no `batch_id` arrived, the client either
   re-POSTs the batch (safe, step 4) or resolves items individually with
   `GET /v1/transfers?idempotency_key=u-8412` — the "did it land?" probe. Never
   resolve by creating a new key.
6. **Partial failure**: read `GET /v1/batches/{id}/items?cursor=...` to the last
   page, collect items failing with `error.retryable: true`
   (`network_issuer_unavailable`, `rate_limited`, `timeout`). Non-retryable
   (`insufficient_funds`, `invalid_iban`, `idempotency_key_reuse`) are reported
   to the user, not retried. Retry only the retryable subset as a **new batch
   with the original keys** (or `POST /v1/transfers` for a single item); if a
   key from the subset turns out to have settled, the server returns that
   settlement instead of charging again.
7. **Key conflict**: same key, different amount/currency/creditor →
   `409 idempotency_key_reuse`, surfaced as an item error and counted as
   rejected. Automated retry stops; a human decides.
8. **Giving up**: after the 6th attempt with no `batch_id`, the client stops and
   alerts. The outbox rows stay in `unknown`, and a background sweeper probes
   each key with `GET /v1/transfers?idempotency_key=...` before the 90-day key
   retention window expires. Items are only ever declared lost after such a
   probe returns 404.

## 5. Concrete A contract decisions

- `POST /v1/batches` always returns `202` with a batch resource; per-item
  outcomes are read, not returned inline. Keeps the <2 s ack independent of 500
  settlement round trips.
- Envelope errors (`400`) never carry money: malformed JSON, `items` empty or
  >500, body >1 MiB (`413`). Item-level validation errors are recorded as item
  statuses inside a successful batch.
- `GET /v1/batches/{id}` → `{status, counts{received, pending, settled,
  declined, unknown}, created_at, completed_at}`; counts are the progress feed
  for mobile.
- `GET /v1/batches/{id}/items?limit=100&cursor=` → cursor paging, stable order
  by item index, `next_cursor: null` on the last page. Results retained 90 days
  (matching key retention), then `410 batch_expired`.
- `Idempotent-Replay: true` response header whenever a request was served from
  an existing key, so clients can detect it.
- Within a batch, items are processed with bounded server concurrency
  (8–16 workers); no ordering guarantee between items. A client needing ordered
  effects must sequence them in separate requests.
- Versioning: major in the path (`/v1`, `/v2`), additive-only within a major,
  open enums, `Sunset` header plus 12-month overlap on deprecation. Item schema
  and error schema version together with the envelope, so a client pins one
  version for the whole batch.

## 6. Rejected alternative, for the record

B as the main path was rejected primarily on progress and pagination: with no
batch identity there is nothing for the server to paginate or to report
progress against, and the 2 s feedback requirement would have to be met by a
client-side orchestration layer that also has to persist 500 idempotency keys
before the first request — i.e. exactly the bookkeeping A puts on the server,
but reimplemented per client and unaudited.
