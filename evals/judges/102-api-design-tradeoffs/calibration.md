# LLM judge 校准：102-api-design-tradeoffs

- 模型：`deepseek-flash`
- 样本：20（标注者：author-draft）
- 一致率：100.0%
- Cohen's κ：1.000
- κ 阈值：0.60；通过阈值：0.70
- 结论：⚠ 不可靠（标注者 author-draft 尚未复核，κ 是草稿值）
- 校准成本：¥0.083567

| 样本 | 人工 | judge | overall | 维度分数 | 理由 |
|---|---|---|---|---|---|
| a-good-01 | ✅ | ✅ | 0.83 | tradeoff_depth=0.50 · constraint_coverage=1.00 · clarity=1.00 | tradeoff_depth: Clear choice and concrete reasoning for batch latency and retry flow, but it mos…；constraint_coverage: Covers 500-item batches, per-item idempot… |
| a-good-02 | ✅ | ✅ | 0.92 | tradeoff_depth=0.85 · constraint_coverage=0.90 · clarity=1.00 | tradeoff_depth: Makes a clear choice for per-transfer requests and touches all five trade-off ar…；constraint_coverage: Covers 500-item handling, per-item idempo… |
| a-good-03 | ✅ | ✅ | 0.87 | tradeoff_depth=0.60 · constraint_coverage=1.00 · clarity=1.00 | tradeoff_depth: It clearly chooses batch endpoint A and gives concrete trade-offs, but mostly ar…；constraint_coverage: Covers 500-item batches, per-item idempot… |
| a-good-04 | ✅ | ✅ | 0.90 | tradeoff_depth=0.70 · constraint_coverage=1.00 · clarity=1.00 | tradeoff_depth: Chooses A and covers all required dimensions with concrete A-side reasoning, but…；constraint_coverage: Covers 500-item batches, per-item idempot… |
| a-good-05 | ✅ | ✅ | 0.87 | tradeoff_depth=0.60 · constraint_coverage=1.00 · clarity=1.00 | tradeoff_depth: Makes a clear choice and gives concrete reasoning for A, including overhead vs 5…；constraint_coverage: Covers all listed requirements: 500-item … |
| a-good-06 | ✅ | ✅ | 0.80 | tradeoff_depth=0.60 · constraint_coverage=0.80 · clarity=1.00 | tradeoff_depth: Chooses B and gives concrete points on latency, retry/idempotency, and partial f…；constraint_coverage: Covers 500 transfers, per-transfer keys, … |
| a-good-07 | ✅ | ✅ | 0.83 | tradeoff_depth=0.50 · constraint_coverage=1.00 · clarity=1.00 | tradeoff_depth: Makes a clear choice and gives concrete A-side reasoning, but does not explicitl…；constraint_coverage: Covers 500-item batches, per-item idempot… |
| a-good-08 | ✅ | ✅ | 0.87 | tradeoff_depth=0.60 · constraint_coverage=1.00 · clarity=1.00 | tradeoff_depth: Clearly chooses A and gives concrete benefits, but mostly argues for the batch s…；constraint_coverage: Covers 500-item batches, per-item idempot… |
| a-good-09 | ✅ | ✅ | 0.83 | tradeoff_depth=0.60 · constraint_coverage=0.90 · clarity=1.00 | tradeoff_depth: Chooses B and gives concrete benefits, but mostly argues B's advantages rather t…；constraint_coverage: Covers 500 requests, per-transfer idempot… |
| a-good-10 | ✅ | ✅ | 0.80 | tradeoff_depth=0.40 · constraint_coverage=1.00 · clarity=1.00 | tradeoff_depth: Chooses A and gives concrete A-side reasoning, but does not compare B on latency…；constraint_coverage: Covers the 500-item cap, per-item idempot… |
| a-bad-01 | ❌ | ❌ | 0.03 | tradeoff_depth=0.00 · constraint_coverage=0.00 · clarity=0.10 | tradeoff_depth: No comparison of shapes A and B, no choice made, only generic REST truisms; none…；constraint_coverage: Ignores every requirement: 500-item batch… |
| a-bad-02 | ❌ | ❌ | 0.27 | tradeoff_depth=0.10 · constraint_coverage=0.10 · clarity=0.60 | tradeoff_depth: Chooses A but does not compare B or analyze latency, retry/idempotency semantics…；constraint_coverage: Mentions 500-item batches only; omits per… |
| a-bad-03 | ❌ | ❌ | 0.10 | tradeoff_depth=0.00 · constraint_coverage=0.00 · clarity=0.30 | tradeoff_depth: Chooses batch submission but gives only generic latency/round-trip benefits and …；constraint_coverage: Misses or contradicts nearly all requirem… |
| a-bad-04 | ❌ | ❌ | 0.08 | tradeoff_depth=0.00 · constraint_coverage=0.00 · clarity=0.25 | tradeoff_depth: Chooses B, but only gives generic simplicity claims and does not compare latency…；constraint_coverage: Misses per-item idempotency keys, per-ite… |
| a-bad-05 | ❌ | ❌ | 0.00 | tradeoff_depth=0.00 · constraint_coverage=0.00 · clarity=0.00 | tradeoff_depth: Never chooses an approach and offers no concrete comparison on latency, retry/id…；constraint_coverage: Ignores 500-item batch limits, per-item s… |
| a-bad-06 | ❌ | ❌ | 0.00 | tradeoff_depth=0.00 · constraint_coverage=0.00 · clarity=0.00 | tradeoff_depth: No API shape is chosen, no concrete comparison of A vs B, and no trade-offs on l…；constraint_coverage: The submission ignores all listed require… |
| a-bad-07 | ❌ | ❌ | 0.33 | tradeoff_depth=0.00 · constraint_coverage=0.00 · clarity=1.00 | tradeoff_depth: Chooses A but does not compare A and B on latency, retry/idempotency, partial fa…；constraint_coverage: Ignores or contradicts most requirements:… |
| a-bad-08 | ❌ | ❌ | 0.23 | tradeoff_depth=0.15 · constraint_coverage=0.15 · clarity=0.40 | tradeoff_depth: Chooses B, but does not compare A vs B on latency, retry/idempotency semantics, …；constraint_coverage: Mentions 500 items and per-request progre… |
| a-bad-09 | ❌ | ❌ | 0.07 | tradeoff_depth=0.10 · constraint_coverage=0.00 · clarity=0.10 | tradeoff_depth: It chooses POST /v1/batches but gives only a generic justification and does not …；constraint_coverage: It misses nearly every requirement: 500-i… |
| a-bad-10 | ❌ | ❌ | 0.23 | tradeoff_depth=0.20 · constraint_coverage=0.00 · clarity=0.50 | tradeoff_depth: Chooses A and mentions latency, but does not compare retry/idempotency semantics…；constraint_coverage: Ignores 500-item batches, per-item idempo… |
