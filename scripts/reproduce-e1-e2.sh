#!/usr/bin/env bash
# E1（压缩策略/模板矩阵）+ E2（成本曲线）的复现脚本。
#
# 用法：
#   ./scripts/reproduce-e1-e2.sh [用于 E2 的 run 目录 ...]
#   不传 run 时默认用正式 run 20261018T154112Z-fa9db83
#
# E1 会真实调用模型（72 条案例）；E2 只读会话 usage，离线。
set -euo pipefail

cd "$(dirname "$0")/.."

echo "== E1: compaction matrix (6 tasks x k=0,1,3,5 x 3 combos) =="
uv run codelotte eval compaction \
  --k 0,1,3,5 \
  --repeat 1 \
  --combo minimal:seven \
  --combo minimal:compact \
  --combo wide:seven \
  --task 001-audit-report \
  --task 002-fix-off-by-one \
  --task 003-constrained-append \
  --task 004-prompt-injection-resistance \
  --task 005-scope-discipline \
  --task 006-multi-bug-pipeline \
  --out evals/runs

if [[ $# -eq 0 ]]; then
  set -- evals/runs/20261018T154112Z-fa9db83
fi
for run_dir in "$@"; do
  if [[ ! -f "$run_dir/report.json" ]]; then
    echo "E2 skipped: $run_dir has no report.json" >&2
    exit 0
  fi
done

echo "== E2: cache / off-peak cost curve =="
args=(--out evals/cost)
for run_dir in "$@"; do
  args+=(--run "$run_dir")
done
uv run codelotte eval cost "${args[@]}"
