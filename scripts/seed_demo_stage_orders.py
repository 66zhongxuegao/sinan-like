"""维护脚本：把 demo-flow 恢复为三个阶段性演示订单的初始状态。"""

from tripcraft.api.context import AppContext
from tripcraft.services import demo_stage_state


def main() -> None:
    ctx = AppContext()
    user = ctx.get_auth().store.user_by_name(demo_stage_state.USERNAME)
    if not user:
        raise SystemExit(f"演示账号不存在: {demo_stage_state.USERNAME}")
    print(demo_stage_state.reset_initial(ctx, user["user_id"]))


if __name__ == "__main__":
    main()