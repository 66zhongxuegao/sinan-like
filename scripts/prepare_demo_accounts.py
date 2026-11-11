"""维护脚本：移除遗留 new 账号，并确保空白演示账号存在。"""

from tripcraft.api.context import AppContext
from tripcraft.services import demo_blank_state
from tripcraft.services.scenario_service import ScenarioService


def remove_account(ctx, username: str) -> str:
    user = ctx.store.user_by_name(username)
    if not user:
        return ""
    uid = user["user_id"]
    ScenarioService(ctx).reset(uid, all_orders=True, include_profile=True)
    ctx.store._exec("DELETE FROM sessions WHERE user_id=?", (uid,))
    ctx.store._exec("DELETE FROM users WHERE user_id=?", (uid,))
    return uid


def main() -> None:
    ctx = AppContext()
    removed = remove_account(ctx, "new")
    print({"removed": removed})
    print(demo_blank_state.ensure_account(ctx, reset=True))


if __name__ == "__main__":
    main()
