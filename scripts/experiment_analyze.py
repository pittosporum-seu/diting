"""实验分析：相关性 + 回归 + 排名一致性（纯计算，不调 AI，可反复试组合）。

读取 experiment/data.csv（采集脚本产出），分析哪些快速指标能逼近最终引擎评分。

用法：
  python scripts/experiment_analyze.py [--data experiment/data.csv]
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np
from scipy import stats

# 快速指标列（自变量候选）
FAST_INDICATORS = [
    "change_pct",
    "intraday_pos",
    "amplitude",
    "open_strength",
    "rsi_14",
    "macd_histogram",
    "kdj_k",
    "kdj_d",
    "kdj_j",
    "bollinger_position",
    "vwap_deviation",
    "volume_ratio",
    "ma_alignment",
    "price_vs_ma20",
]
TARGET = "consensus_score"
AI_ENGINE_COLS = ["eng_wyckoff", "eng_buffett", "eng_can_slim"]


def load_data(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    # 转数值
    for r in rows:
        for k, v in r.items():
            if v in (None, "", "None"):
                r[k] = None
            else:
                try:
                    r[k] = float(v)
                except (ValueError, TypeError):
                    pass
    return rows


def clean_matrix(rows: list[dict], cols: list[str]):
    """提取完整矩阵（丢弃任一列为空的行），返回 (X, y, valid_rows)。"""
    valid = []
    for r in rows:
        if r.get(TARGET) is None:
            continue
        if all(r.get(c) is not None for c in cols):
            valid.append(r)
    X = np.array([[r[c] for c in cols] for r in valid], dtype=float)
    y = np.array([r[TARGET] for r in valid], dtype=float)
    return X, y, valid


def standardize(X: np.ndarray):
    mu = X.mean(axis=0)
    sd = X.std(axis=0)
    sd[sd == 0] = 1.0
    return (X - mu) / sd, mu, sd


def linreg_r2(X: np.ndarray, y: np.ndarray) -> tuple[float, np.ndarray]:
    """多元线性回归，返回 (R², 系数含截距)。"""
    Xb = np.column_stack([np.ones(len(X)), X])
    coef, _, _, _ = np.linalg.lstsq(Xb, y, rcond=None)
    pred = Xb @ coef
    ss_res = np.sum((y - pred) ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return r2, coef


def correlation_analysis(rows: list[dict], out_dir: Path):
    """每个快速指标 vs 共识分（+ vs 各 AI 引擎分）的相关性。"""
    results = []
    targets = [TARGET] + AI_ENGINE_COLS
    for ind in FAST_INDICATORS:
        row = {"indicator": ind}
        for tgt in targets:
            pairs = [
                (r[ind], r[tgt])
                for r in rows
                if r.get(ind) is not None and r.get(tgt) is not None
            ]
            if len(pairs) < 5:
                row[f"{tgt}_pearson"] = None
                row[f"{tgt}_spearman"] = None
                row[f"{tgt}_n"] = len(pairs)
                continue
            x = np.array([p[0] for p in pairs])
            yv = np.array([p[1] for p in pairs])
            pr = stats.pearsonr(x, yv)[0]
            sp = stats.spearmanr(x, yv)[0]
            row[f"{tgt}_pearson"] = round(float(pr), 4)
            row[f"{tgt}_spearman"] = round(float(sp), 4)
            row[f"{tgt}_n"] = len(pairs)
        results.append(row)

    # 按 vs 共识分的 |spearman| 排序
    results.sort(
        key=lambda r: abs(r.get(f"{TARGET}_spearman") or 0), reverse=True
    )
    cols = list(results[0].keys())
    with open(out_dir / "correlation.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(results)
    return results


def stepwise_regression(rows: list[dict], out_dir: Path, max_features: int = 6):
    """前向逐步回归：找最简约且 R² 高的指标组合。"""
    X_full, y, valid = clean_matrix(rows, FAST_INDICATORS)
    if len(valid) < 10:
        print("[warn] 有效样本不足，跳过回归")
        return None
    Xs, mu, sd = standardize(X_full)

    selected: list[int] = []
    history = []
    remaining = list(range(len(FAST_INDICATORS)))

    for _ in range(max_features):
        best = None
        for idx in remaining:
            trial = selected + [idx]
            r2, _ = linreg_r2(Xs[:, trial], y)
            if best is None or r2 > best[1]:
                best = (idx, r2)
        if best is None:
            break
        idx, r2 = best
        # 若新增指标 R² 提升 < 0.005 则停止
        if selected and r2 - history[-1]["r2"] < 0.005:
            break
        selected.append(idx)
        remaining.remove(idx)
        _, coef = linreg_r2(Xs[:, selected], y)
        history.append(
            {
                "n_features": len(selected),
                "r2": round(float(r2), 4),
                "features": [FAST_INDICATORS[i] for i in selected],
                "coef_standardized": {
                    FAST_INDICATORS[i]: round(float(coef[j + 1]), 4)
                    for j, i in enumerate(selected)
                },
                "intercept": round(float(coef[0]), 4),
            }
        )

    with open(out_dir / "regression.json", "w", encoding="utf-8") as f:
        json.dump(
            {"standardize_mu": mu.tolist(), "standardize_sd": sd.tolist(), "steps": history},
            f,
            ensure_ascii=False,
            indent=2,
        )
    return history


def ranking_consistency(rows: list[dict], reg_history, out_dir: Path):
    """用最优快速公式打分排名 vs 全量共识分排名的一致性。"""
    if not reg_history:
        return None
    best = reg_history[-1]
    features = best["features"]
    coef_std = best["coef_standardized"]
    intercept = best["intercept"]

    # 用标准化系数需要 mu/sd；这里直接用原始值做线性组合（用 regression.json 的标准化）
    with open(out_dir / "regression.json", encoding="utf-8") as f:
        reg = json.load(f)
    mu = np.array(reg["standardize_mu"])
    sd = np.array(reg["standardize_sd"])
    full_cols = FAST_INDICATORS

    valid = [
        r
        for r in rows
        if r.get(TARGET) is not None and all(r.get(c) is not None for c in full_cols)
    ]
    if len(valid) < 5:
        return None

    fast_scores = []
    consensus = []
    for r in valid:
        x = np.array([r[c] for c in full_cols])
        xs = (x - mu) / np.where(sd == 0, 1, sd)
        s = intercept + sum(
            coef_std.get(full_cols[i], 0) * xs[i] for i in range(len(full_cols))
        )
        fast_scores.append(s)
        consensus.append(r[TARGET])

    fast_rank = stats.rankdata([-s for s in fast_scores])
    cons_rank = stats.rankdata([-c for c in consensus])
    spearman = stats.spearmanr(fast_rank, cons_rank)[0]

    # Top-K 命中率
    n = len(valid)
    k = min(20, n // 3) if n >= 6 else n
    fast_topk = set(np.argsort(fast_scores)[-k:])
    cons_topk = set(np.argsort(consensus)[-k:])
    hit = len(fast_topk & cons_topk)

    result = {
        "n_samples": n,
        "fast_formula_features": features,
        "rank_spearman": round(float(spearman), 4),
        "top_k": k,
        "top_k_hit": hit,
        "top_k_hit_rate": round(hit / k, 4) if k else 0,
    }
    with open(out_dir / "ranking.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return result


def write_report(corr, reg_history, ranking, rows, out_dir: Path):
    n = len(rows)
    n_ai = sum(1 for r in rows if r.get("has_ai"))
    lines = [
        "# 快速筛选指标实验报告",
        "",
        f"- 样本数: {n}（含 AI 全量分析: {n_ai}）",
        f"- 目标: 最终 6 引擎共识分 (consensus_score)",
        "",
        "## 1. 指标相关性排名（vs 共识分，按 |Spearman|）",
        "",
        "| 指标 | Pearson | Spearman | N |",
        "|------|---------|----------|---|",
    ]
    for r in corr:
        p = r.get(f"{TARGET}_pearson")
        s = r.get(f"{TARGET}_spearman")
        nn = r.get(f"{TARGET}_n")
        lines.append(f"| {r['indicator']} | {p} | {s} | {nn} |")

    lines += ["", "## 2. 逐步回归（R² 随指标数）", ""]
    if reg_history:
        lines.append("| 指标数 | R² | 指标组合 |")
        lines.append("|--------|-----|----------|")
        for h in reg_history:
            lines.append(f"| {h['n_features']} | {h['r2']} | {', '.join(h['features'])} |")
        best = reg_history[-1]
        lines += [
            "",
            f"**最优组合 R²={best['r2']}**，标准化系数：",
            "",
        ]
        for feat, c in best["coef_standardized"].items():
            lines.append(f"- {feat}: {c}")
    else:
        lines.append("（样本不足，未做回归）")

    lines += ["", "## 3. 排名一致性（快速公式 vs 全量共识）", ""]
    if ranking:
        lines += [
            f"- 排名 Spearman 相关: **{ranking['rank_spearman']}**",
            f"- Top-{ranking['top_k']} 命中率: **{ranking['top_k_hit']}/{ranking['top_k']} "
            f"= {ranking['top_k_hit_rate']}**",
        ]
    else:
        lines.append("（样本不足）")

    lines += [
        "",
        "## 4. 结论",
        "",
        "见上述 R² 与排名一致性：R² 越高、排名 Spearman 越接近 1，",
        "说明快速公式越能逼近全量引擎评分，初筛越有效。",
    ]
    (out_dir / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="experiment/data.csv")
    parser.add_argument("--out", default="experiment")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = load_data(args.data)
    print(f"加载 {len(rows)} 行")

    corr = correlation_analysis(rows, out_dir)
    print("相关性分析完成 → correlation.csv")

    reg_history = stepwise_regression(rows, out_dir)
    print("逐步回归完成 → regression.json")

    ranking = ranking_consistency(rows, reg_history, out_dir)
    print("排名一致性完成 → ranking.json")

    write_report(corr, reg_history, ranking, rows, out_dir)
    print("报告 → REPORT.md")

    if reg_history:
        print(f"\n最优 R²={reg_history[-1]['r2']} 组合={reg_history[-1]['features']}")
    if ranking:
        print(
            f"排名 Spearman={ranking['rank_spearman']} "
            f"Top-{ranking['top_k']} 命中={ranking['top_k_hit_rate']}"
        )


if __name__ == "__main__":
    main()
