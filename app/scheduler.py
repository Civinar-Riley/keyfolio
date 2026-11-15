"""定时任务：asyncio 循环，按 settings 里的间隔自动查余额/同步模型。

未登录（无 data key）时不跑；定时同步只新增不删除，避免误伤。
"""
import asyncio
import logging
import time

from . import db, services

log = logging.getLogger("keyfolio.scheduler")


async def run_loop() -> None:
    log.info("定时任务循环启动")
    while True:
        try:
            await tick()
        except Exception:
            log.exception("定时任务执行异常")
        await asyncio.sleep(60)


def _enabled(interval_setting: str) -> bool:
    from .auth import State

    return (
        State.data_key is not None
        and bool(db.get_setting("sched_enabled", False))
        and float(db.get_setting(interval_setting, 12 if interval_setting == "sched_balance_hours" else 24) or 0) > 0
    )


async def tick() -> None:
    if _enabled("sched_balance_hours"):
        interval = float(db.get_setting("sched_balance_hours", 12))
        now_ts = time.time()
        last = float(db.get_setting("last_balance_run", 0) or 0)
        if now_ts - last >= interval * 3600:
            db.set_setting("last_balance_run", now_ts)
            await run_all_balances()

    # 查余额可能耗时较长，进入下一类任务时重新读取开关和间隔。
    if _enabled("sched_models_hours"):
        interval = float(db.get_setting("sched_models_hours", 24))
        now_ts = time.time()
        last = float(db.get_setting("last_models_run", 0) or 0)
        if now_ts - last >= interval * 3600:
            db.set_setting("last_models_run", now_ts)
            await run_all_model_sync()


def _iter_enabled_pairs():
    with db.get_conn() as conn:
        channels = conn.execute("SELECT * FROM channels WHERE enabled=1").fetchall()
        keys = conn.execute("SELECT * FROM keys WHERE enabled=1").fetchall()
    by_channel: dict[int, list] = {}
    for key in keys:
        by_channel.setdefault(key["channel_id"], []).append(key)
    for channel in channels:
        for key in by_channel.get(channel["id"], []):
            yield channel, key


async def run_all_balances() -> None:
    for channel, key in _iter_enabled_pairs():
        if not _enabled("sched_balance_hours"):
            return
        with db.get_conn() as conn:
            current = services.current_request_key(conn, channel, key)
        if current is None or not current["enabled"] or not current["channel_enabled"]:
            continue
        try:
            result = await services.check_balance(channel, current)
            if not result.get("ok"):
                log.warning("自动查余额失败 key=%s: %s", key["id"], result.get("error"))
        except Exception:
            log.warning("自动查余额异常 key=%s", key["id"], exc_info=True)


async def run_all_model_sync() -> None:
    with db.get_conn() as conn:
        channels = conn.execute("SELECT * FROM channels WHERE enabled=1").fetchall()
    for channel in channels:
        if not _enabled("sched_models_hours"):
            return
        key = services.first_enabled_key(channel["id"])
        if key is None:
            continue
        with db.get_conn() as conn:
            current = services.current_request_key(conn, channel, key)
        if current is None or not current["enabled"] or not current["channel_enabled"]:
            continue
        try:
            ids = await services.pull_models_async(channel, current)
            if not _enabled("sched_models_hours"):
                return
            diff = services.diff_models(channel["id"], ids)
            added = diff["added"]
            revived = diff["revived"]
            if added or revived:
                services.apply_sync(
                    channel["id"], added, [], "disable", revived,
                    request_rows=(channel, current),
                )
                log.info(
                    "自动同步渠道 %s：新增 %d 个模型，恢复 %d 个",
                    channel["id"], len(added), len(revived),
                )
        except Exception:
            log.warning("自动同步模型异常 channel=%s", channel["id"], exc_info=True)
