"""外部数据工具层冒烟（真实调用高德 + Open-Meteo）。

用法：python scripts/smoke_external.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tripcraft.tools.external import check_itinerary, geocode, weather  # noqa: E402


def main() -> int:
    spots = ["北京市天安门", "北京市故宫博物院", "北京市颐和园"]
    points = []
    for s in spots:
        p = geocode(s)
        print(("OK  " if p else "FAIL"), s, (p.amap_location if p else ""))
        if p:
            points.append(p)

    if len(points) >= 2:
        rep = check_itinerary(points)
        print(f"\n行程核验：总距离 {rep.total_distance_m / 1000:.1f} km | 总耗时 {rep.total_duration_s / 60:.0f} 分钟")
        for leg in rep.legs:
            print(f"  {leg.from_name} -> {leg.to_name}: {leg.distance_m / 1000:.1f} km / {leg.duration_s / 60:.0f} 分钟")
        print("  问题:", rep.issues or "无")

    # 故意制造折返：A -> B -> A
    if len(points) >= 2:
        back = check_itinerary([points[0], points[1], points[0]])
        print("\n折返用例 问题:", back.issues or "无")

    w = weather(points[0].lat, points[0].lng) if points else None
    print("\n天气:", w)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())