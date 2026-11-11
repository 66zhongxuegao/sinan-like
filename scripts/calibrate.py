"""跑人工校准集，标定低置信度阈值，并把基线写入数据库。

用法：
    python -X utf8 scripts/calibrate.py            # 默认 1 轮
    python -X utf8 scripts/calibrate.py --repeats 2
    python -X utf8 scripts/calibrate.py --limit 6  # 快速试跑

产出：
    data/calibration/report.json   完整报告
    tripcraft.sqlite               calibration_run 表（作为评分主链的准入门槛）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tripcraft.agents.llm import DeepSeekClient  # noqa: E402
from tripcraft.calibration import audit_dataset, load_samples, run_calibration  # noqa: E402
from tripcraft.storage import Store  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=1, help="重复轮数（测稳定性）")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 条（快速试跑）")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--audit", action="store_true", help="只做数据集结构审计，不调用模型")
    args = ap.parse_args()

    samples = load_samples()
    if args.limit:
        samples = samples[:args.limit]
    if not samples:
        print("没有校准样本：data/calibration/samples.jsonl")
        return 2

    audit = audit_dataset(samples)
    if args.audit:
        print("校准集审计（PRD 25.2）")
        print(f"  样本 {audit['samples']} 条 / 技能点 {audit['skill_points']} 个 / 难例 {audit['hard_cases']} 条")
        print(f"  档位分布 {audit['levels']}")
        print(f"  客源市场 {len(audit['markets'])} 个：{'、'.join(audit['markets'])}")
        print(f"  语言 {audit['languages']}")
        if audit["gaps"]:
            print("  缺口：")
            for g in audit["gaps"]:
                print("    -", g)
        else:
            print("  结论：无缺口（每个技能点 ≥ "
                  f"{audit['min_per_skill_point']} 条，M1–M5 均有样本）")
        return 0 if audit["passed"] else 1

    print(f"校准样本 {len(samples)} 条 / 重复 {max(1, args.repeats)} 轮 "
          f"/ 预计 {len(samples) * max(1, args.repeats)} 次模型调用")
    llm = DeepSeekClient()

    def progress(i: int, n: int, sid: str) -> None:
        if not args.quiet:
            print(f"  [{i}/{n}] {sid}", flush=True)

    report = run_calibration(llm, samples, repeats=max(1, args.repeats), on_progress=progress)

    store = Store()
    store.add_calibration_run(
        report["run_id"], report["samples"], report["predictions"],
        report["agreement"], report["evidence_accuracy"], report["stability"],
        report["threshold"]["confidence"], report["threshold"]["boundary_delta"],
        report["passed"], report)

    d = report.get("dataset") or {}
    if d:
        print(f"\n集内计量：技能点 {d.get('skill_points')} 个 / 难例 {d.get('hard_cases')} 条 / "
              f"客源 {len(d.get('markets') or {})} 个 / 语言 {len(d.get('languages') or {})} 种"
              + ("" if d.get("passed") else f"（有缺口：{'；'.join(d.get('gaps') or [])}）"))
    print("\n===== 校准结果 =====")
    print(f"M 档一致率   {report['agreement']:.1%}（门槛 {report['target_agreement']:.0%}）")
    print(f"证据准确率   {report['evidence_accuracy']:.1%}（门槛 {report['target_evidence']:.0%}）")
    print(f"稳定性       {report['stability']:.1%}")
    t = report["threshold"]
    print(f"标定阈值     置信度 >= {t['confidence']}，档位边界 ±{t['boundary_delta']} 分")
    print(f"             该阈值下一致率 {t['accuracy_at']}，保留 {t['kept']} 条判定（{t['kept_ratio']:.0%}）")
    print(f"结论         {'通过：评分 Agent 可进入主链影响画像' if report['passed'] else '未达标：需修 Rubric / Prompt 后再跑'}")
    if report["confusion"]:
        print("混淆分布     ", json.dumps(report["confusion"], ensure_ascii=False))
    if report["errors"] and not args.quiet:
        print("错误样本：")
        for e in report["errors"][:10]:
            print(f"  {e['sample_id']} {e['skill_point_id']}: 人工 {e['human']} / 预测 {e['predicted']}"
                  f"（置信 {e['confidence']}）")
    print("\n报告已写入 data/calibration/report.json，基线已入库 calibration_run。")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())