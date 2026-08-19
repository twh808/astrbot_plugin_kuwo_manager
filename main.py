import json
import os
import time
import re
import asyncio
import aiohttp
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import logger


class KuwoManager(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        # 任务存储
        self.task_map = dict()
        # 超时监听任务
        self.timeout_task = None

    async def _timeout_watcher(self):
        """超时检测后台任务【已修复】"""
        while True:
            await asyncio.sleep(5)
            now = time.time()
            remove_list = []
            for user_id, state in self.task_map.items():
                expire = state.get("expire_time", 0)
                session_id_raw = state.get("session_id", "")
                if now >= expire:
                    # ==========修复核心：拼装合法三段式session_id==========
                    if isinstance(session_id_raw, str) and session_id_raw.isdigit():
                        full_session_id = f"onebot:private:{session_id_raw}"
                    else:
                        full_session_id = session_id_raw

                    try:
                        await self.context.send_message(full_session_id, "⏰ 操作超时，请重新发送指令。")
                        logger.info(f"✅ 超时提醒已发送 user_id={user_id} session={full_session_id}")
                    except Exception as e:
                        logger.error(f"❌ 发送超时提醒失败 user_id={user_id}, err: {str(e)}")
                    remove_list.append(user_id)
            for uid in remove_list:
                self.task_map.pop(uid, None)

    @filter.command("kuwo")
    async def kuwo_cmd(self, event: AstrMessageEvent):
        """酷我管理主指令"""
        user_id = str(event.get_sender_id())
        # ==========修复：存入完整session对象对应的会话标识==========
        full_session = event.session_id
        self.task_map[user_id] = {
            "session_id": full_session,
            "expire_time": time.time() + 120
        }
        yield event.plain_result("✅ 酷我管理器已启动，请发送后续指令。")

    async def activate(self):
        logger.info("酷我管理插件加载完成")
        self.timeout_task = asyncio.create_task(self._timeout_watcher())

    async def deactivate(self):
        if self.timeout_task:
            self.timeout_task.cancel()
            try:
                await self.timeout_task
            except asyncio.CancelledError:
                pass
        logger.info("酷我管理插件已卸载")
