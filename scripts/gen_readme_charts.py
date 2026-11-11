"""生成 README 用的数据图（价值测算 + 损失场景）。

数据口径：一线旅行社定制师调研（问卷 + 线下访谈）。图上只画调研得到的量，不编造分布。
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "charts"
OUT.mkdir(parents=True, exist_ok=True)

BLUE = "#2577e3"
BLUE_LIGHT = "#eaf3fe"
BLUE_DEEP = "#1a63c4"
ORANGE = "#e08a1e"
GREEN = "#12a76a"
TEXT = "#16223a"
MUTED = "#6b7a90"

plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False


def style(ax, spine_color="#e8eaed"):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(spine_color)


def chart_cost() -> None:
    """培养投入期：4 个月 → 缩短 30% → 约 2.8 个月"""
    fig, ax = plt.subplots(figsize=(7.2, 3.5), dpi=200)
    labels = ["传统培养\n（师傅带教 + 真客户练）", "司南礼客实训后\n（缩短 30%）"]
    values, ys = [4.0, 2.8], [1, 0]
    ax.axvspan(2.8, 4.0, color=ORANGE, alpha=0.10, zorder=1)          # 省下来的那段
    ax.barh(ys, values, height=0.5, color=[MUTED, BLUE], zorder=3)
    ax.set_yticks(ys)
    ax.set_yticklabels(labels, fontsize=11, color=TEXT)
    for y, v in zip(ys, values):
        ax.text(v + 0.08, y, f"{v:g} 个月", va="center", fontsize=12.5, color=TEXT, fontweight="bold")

    # 差额量尺画在两根柱子下面，避免压住柱体文字
    ax.annotate("", xy=(2.8, -0.62), xytext=(4.0, -0.62),
                arrowprops=dict(arrowstyle="<->", color=ORANGE, lw=1.6), zorder=4)
    ax.text(3.4, -0.95, "节省 1.2 个月 ≈ ¥1 万 / 人", ha="center", fontsize=11.5,
            color=ORANGE, fontweight="bold")

    ax.set_xlim(0, 5.2)
    ax.set_ylim(-1.35, 1.6)
    ax.set_xlabel("新人可独立产出前的投入期（月）", fontsize=11, color=MUTED)
    ax.set_title("单个新人节省培养成本约 1 万元", fontsize=14, fontweight="bold", color=TEXT, pad=12)
    ax.grid(axis="x", color="#f0f2f5", zorder=0)
    style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "value-cost.png", facecolor="white")
    plt.close(fig)


def chart_hours() -> None:
    """师傅工时：每天 1 小时重复答疑，系统承接 60% → 年释放约 150 小时"""
    fig, ax = plt.subplots(figsize=(7.2, 3.2), dpi=200)
    daily_total, taken = 1.0, 0.6
    ax.barh(["师傅每天\n重复答疑"], [daily_total], height=0.42, color=BLUE_LIGHT, zorder=3)
    ax.barh(["师傅每天\n重复答疑"], [taken], height=0.42, color=BLUE, zorder=4)
    ax.text(taken / 2, 0, "系统承接 60%", ha="center", va="center", fontsize=11.5,
            color="white", fontweight="bold", zorder=5)
    ax.text(daily_total + 0.04, 0, "1 小时/天", va="center", fontsize=11.5, color=MUTED)
    ax.text(0.02, -0.62, "→ 每人每年释放约 150 小时工时", fontsize=13, color=GREEN,
            fontweight="bold")
    ax.set_xlim(0, 1.35)
    ax.set_ylim(-1.0, 0.8)
    ax.set_xlabel("每天用于重复答疑的时间（小时）", fontsize=11, color=MUTED)
    ax.set_title("把师傅从重复答疑里解放出来", fontsize=14, fontweight="bold", color=TEXT, pad=12)
    ax.grid(axis="x", color="#f0f2f5", zorder=0)
    style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "value-hours.png", facecolor="white")
    plt.close(fig)


def chart_losses() -> None:
    """四类真实损失场景（访谈记录，不含频率数据）"""
    scenes = [
        ("漏算保险与停车费", "报价时漏项，行程结束才发现亏损"),
        ("酒店超售临时换房", "旺季被顶房，客户体验受损、需补偿"),
        ("车辆故障临时调度", "行中突发，需在时限内换车并安抚客户"),
        ("高铁票抢不到", "只能多买一站补偿，成本与行程双受影响"),
    ]
    fig, ax = plt.subplots(figsize=(7.6, 3.4), dpi=200)
    ax.axis("off")
    ax.set_xlim(0, 10)
    ax.set_ylim(0, len(scenes) * 1.0 + 0.4)
    for i, (title, desc) in enumerate(scenes):
        y = len(scenes) - i - 0.5
        box = FancyBboxPatch((0.1, y - 0.38), 9.8, 0.78, boxstyle="round,pad=0.02,rounding_size=0.12",
                             linewidth=1, edgecolor="#e8eaed", facecolor="#fbfdff")
        ax.add_patch(box)
        ax.add_patch(FancyBboxPatch((0.24, y - 0.30), 0.10, 0.60,
                                    boxstyle="round,pad=0.0,rounding_size=0.05",
                                    linewidth=0, facecolor=ORANGE))
        ax.text(0.52, y + 0.10, title, fontsize=12.5, color=TEXT, fontweight="bold", va="center")
        ax.text(0.52, y - 0.16, desc, fontsize=10.5, color=MUTED, va="center")
    ax.set_title("线下访谈记录的四类真实损失场景", fontsize=14, fontweight="bold",
                 color=TEXT, pad=10)
    fig.tight_layout()
    fig.savefig(OUT / "loss-scenes.png", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    chart_cost()
    chart_hours()
    chart_losses()
    for f in sorted(OUT.glob("*.png")):
        print(f"  {f.name}  {f.stat().st_size / 1024:.0f} KB")
