# LLM judge 校准：101-concurrency-review

- 模型：`deepseek-flash`
- 样本：20（标注者：author-draft）
- 一致率：100.0%
- Cohen's κ：1.000
- κ 阈值：0.60；通过阈值：0.70
- 结论：⚠ 不可靠（标注者 author-draft 尚未复核，κ 是草稿值）
- 校准成本：¥0.071073

| 样本 | 人工 | judge | overall | 维度分数 | 理由 |
|---|---|---|---|---|---|
| c-good-01 | ✅ | ✅ | 1.00 | correctness=1.00 · specificity=1.00 · clarity=1.00 | correctness: Identifies the lost update, explains GIL is not atomic for read-modify-write, an…；specificity: Quotes the racy lines, gives a concrete two-thread i… |
| c-good-02 | ✅ | ✅ | 1.00 | correctness=1.00 · specificity=1.00 · clarity=1.00 | correctness: Identifies the lost update on counter, explains two threads reading the same old…；specificity: Quotes the exact racy lines, names counter as shared… |
| c-good-03 | ✅ | ✅ | 1.00 | correctness=1.00 · specificity=1.00 · clarity=1.00 | correctness: Identifies the lost update, explains two threads reading the same old value, sta…；specificity: Quotes the racy lines, gives a concrete A/B interlea… |
| c-good-04 | ✅ | ✅ | 1.00 | correctness=1.00 · specificity=1.00 · clarity=1.00 | correctness: Identifies the lost update, states the GIL does not make read-modify-write atomi…；specificity: Quotes the exact racy lines, names shared counter, a… |
| c-good-05 | ✅ | ✅ | 1.00 | correctness=1.00 · specificity=1.00 · clarity=1.00 | correctness: Identifies the lost-update race in the read-modify-write, explains the GIL does …；specificity: Quotes the racy lines, gives a concrete two-thread i… |
| c-good-06 | ✅ | ✅ | 1.00 | correctness=1.00 · specificity=1.00 · clarity=1.00 | correctness: Identifies the non-atomic read-modify-write lost update, explains both threads c…；specificity: Quotes the racy lines, gives a concrete two-thread i… |
| c-good-07 | ✅ | ✅ | 1.00 | correctness=1.00 · specificity=1.00 · clarity=1.00 | correctness: Identifies the lost update from separate read/write of counter, explains two thr…；specificity: Quotes the racy lines `value = counter` and `counter… |
| c-good-08 | ✅ | ✅ | 1.00 | correctness=1.00 · specificity=1.00 · clarity=1.00 | correctness: Identifies the lost update, explains two threads reading the same old value, cor…；specificity: Quotes the exact racy lines, gives a concrete two-th… |
| c-good-09 | ✅ | ✅ | 1.00 | correctness=1.00 · specificity=1.00 · clarity=1.00 | correctness: Identifies the lost update, explains two threads reading the same old counter va…；specificity: Quotes the racy read/write lines, describes the two-… |
| c-good-10 | ✅ | ✅ | 0.83 | correctness=1.00 · specificity=0.50 · clarity=1.00 | correctness: Identifies the lost update, explains both threads can read the same old value, s…；specificity: Quotes the racy statements and uses counter, but doe… |
| c-bad-01 | ❌ | ❌ | 0.33 | correctness=0.00 · specificity=0.00 · clarity=1.00 | correctness: The review claims the GIL makes the increment atomic and says no fix is needed, …；specificity: It only vaguely gestures at `value = counter`/`count… |
| c-bad-02 | ❌ | ❌ | 0.33 | correctness=0.00 · specificity=0.00 · clarity=1.00 | correctness: The proposed fix `counter += 1` is still an unsynchronized read-modify-write and…；specificity: It does not quote the racy lines, give a concrete tw… |
| c-bad-03 | ❌ | ❌ | 0.33 | correctness=0.00 · specificity=0.00 · clarity=1.00 | correctness: The proposed fix locks only the read; the increment and write happen outside the…；specificity: It quotes only `value = counter`, does not walk thro… |
| c-bad-04 | ❌ | ❌ | 0.20 | correctness=0.00 · specificity=0.00 · clarity=0.60 | correctness: Does not identify the lost update in value = counter / counter = value, does not…；specificity: No exact racy lines quoted, no concrete two-thread i… |
| c-bad-05 | ❌ | ❌ | 0.17 | correctness=0.00 · specificity=0.00 · clarity=0.50 | correctness: Does not identify the lost update in value = counter / counter = value, never me…；specificity: No quoted lines, no concrete two-thread interleaving… |
| c-bad-06 | ❌ | ❌ | 0.33 | correctness=0.00 · specificity=0.00 · clarity=1.00 | correctness: Does not identify the lost update, does not explain same-old-value reads, and pr…；specificity: No exact racy lines quoted, no concrete two-thread i… |
| c-bad-07 | ❌ | ❌ | 0.17 | correctness=0.00 · specificity=0.00 · clarity=0.50 | correctness: Never identifies the lost update on the counter read-modify-write, says nothing …；specificity: No racy lines quoted, no concrete two-thread interle… |
| c-bad-08 | ❌ | ❌ | 0.27 | correctness=0.10 · specificity=0.00 · clarity=0.70 | correctness: It vaguely mentions a race and a lock but never identifies the lost update in `v…；specificity: No quoted racy lines, no concrete two-thread interle… |
| c-bad-09 | ❌ | ❌ | 0.17 | correctness=0.00 · specificity=0.00 · clarity=0.50 | correctness: Misidentifies the bug as `for worker in workers` instead of the `value = counter…；specificity: No exact racy lines quoted, no concrete two-thread i… |
| c-bad-10 | ❌ | ❌ | 0.50 | correctness=0.50 · specificity=0.00 · clarity=1.00 | correctness: It generically identifies a lost update and mentions using a lock, but it does n…；specificity: It gives no exact quoted lines, no concrete two-thre… |
