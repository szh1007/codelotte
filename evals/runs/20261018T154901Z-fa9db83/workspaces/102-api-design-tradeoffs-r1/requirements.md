# Batch payment API requirements

- Clients submit up to 500 transfers in one request.
- Each transfer must be idempotent by a client-supplied idempotency key.
- Partial success is allowed: return per-item status and errors.
- Retries must not double-charge a transfer.
- Mobile clients need progress feedback within 2 seconds.
- The system must support pagination when listing batch results.
- Breaking changes require a version bump.
