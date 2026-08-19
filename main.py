import json
import os
import time
import re
import asyncio
import aiohttp
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import logger

class KuwoManagerPlugin(Star):
    """酷我账号管理 - 超时主动回复（使用 event.reply）"""

    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        if config is None:
            config = {}
        self.base_url = config.get("base_url", "").strip()
        self.app_key = config.get("app_key", "").strip()
        self.app_secret = config.get("app_secret", "").strip()
        self.token = None
        self.token_expiry = 0
        self.env_name = "kwtx"
        self.code_env_name = "CODE"

        admin_str = config.get("admin_qq", "").strip()
        self.admin_qqs = [qq.strip() for qq in admin_str.split(',') if qq.strip()]

        self.data_dir = os.path.join(os.getcwd(), "data", "kuwo_data")
        self.cache_file = os.path.join(self.data_dir, "user_data.json")
        os.makedirs(self.data_dir, exist_ok=True)
        self.cache = self._load_cache()

        self.state_info = {}
        self.TIMEOUT = 120
        self.timeout_tasks = {}

        logger.info("✅ 酷我插件（超时主动回复版）已加载")

    # ---------- 缓存读写 ----------
    def _load_cache(self) -> dict:
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"加载缓存失败: {e}")
        return {}

    def _save_cache(self):
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存缓存失败: {e}")

    def _get_cache_user(self, user_id: str) -> dict:
        if user_id not in self.cache:
            self.cache[user_id] = {"accounts": []}
            self._save_cache()
        return self.cache[user_id]

    def _update_cache_user(self, user_id: str, accounts: list):
        self.cache[user_id] = {"accounts": accounts}
        self._save_cache()

    # ---------- 呆呆面板 API ----------
    async def _get_token(self):
        if self.token and self.token_expiry > time.time():
            return self.token
        if not all([self.base_url, self.app_key, self.app_secret]):
            raise Exception("呆呆面板配置不完整")
        base = self.base_url.replace("/api/v1", "").replace("/api", "")
        token_url = f"{base}/api/open-api/token"
        payload = {"app_key": self.app_key, "app_secret": self.app_secret}
        async with aiohttp.ClientSession() as session:
            async with session.post(token_url, json=payload) as resp:
                if resp.status != 200:
                    raise Exception(f"获取 Token 失败：{resp.status}")
                result = await resp.json()
                token = result.get("data", {}).get("access_token")
                if not token:
                    raise Exception("响应中无 access_token")
                expires_in = result.get("data", {}).get("expires_in", 86400)
                self.token_expiry = time.time() + expires_in - 60
                self.token = token
                return token

    async def _call_api(self, endpoint: str, method: str = "POST", data: dict = None):
        token = await self._get_token()
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
        async with aiohttp.ClientSession() as session:
            async with session.request(method, url, headers=headers, json=data) as resp:
                if resp.status == 401:
                    self.token = None
                    self.token_expiry = 0
                    return await self._call_api(endpoint, method, data)
                try:
                    return await resp.json()
                except:
                    return {"error": f"HTTP {resp.status}", "detail": await resp.text()}

    async def _fetch_env_list(self):
        result = await self._call_api("envs?page=1&page_size=100", method="GET")
        return result.get("data", [])

    async def _get_env_id_by_name(self, env_name: str) -> int:
        envs = await self._fetch_env_list()
        for env in envs:
            if env.get("name") == env_name:
                return env.get("id")
        return None

    async def _update_env_value(self, env_name: str, new_value: str) -> bool:
        env_id = await self._get_env_id_by_name(env_name)
        if env_id is None:
            payload = {"name": env_name, "value": new_value, "group": "默认分组"}
            result = await self._call_api("envs", method="POST", data=payload)
        else:
            payload = {"name": env_name, "value": new_value}
            result = await self._call_api(f"envs/{env_id}", method="PUT", data=payload)
        return result.get("code") in [0, None, ""] and not result.get("error")

    # ---------- 环境变量读写（kwtx，支持无限制） ----------
    async def _get_all_env_entries(self) -> list:
        value = ""
        env_id = await self._get_env_id_by_name(self.env_name)
        if env_id:
            envs = await self._fetch_env_list()
            for env in envs:
                if env.get("id") == env_id:
                    value = env.get("value", "")
                    break
        if not value:
            return []
        lines = value.split('\n')
        entries = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            parts = line.split('#')
            if len(parts) >= 2:
                phone = parts[0].strip()
                password = parts[1].strip()
                auth_count = None
                if len(parts) >= 3 and parts[2].strip():
                    try:
                        auth_count = int(parts[2].strip())
                    except:
                        auth_count = None
                entries.append({"phone": phone, "password": password, "auth_count": auth_count})
        return entries

    async def _save_all_env_entries(self, entries: list) -> bool:
        if not entries:
            new_value = ""
        else:
            lines = []
            for e in entries:
                if e["auth_count"] is None:
                    lines.append(f"{e['phone']}#{e['password']}")
                else:
                    lines.append(f"{e['phone']}#{e['password']}#{e['auth_count']}")
            new_value = '\n'.join(lines)
        return await self._update_env_value(self.env_name, new_value)

    # ---------- 验证码环境变量读写 ----------
    async def _get_code_env_value(self) -> str:
        value = ""
        env_id = await self._get_env_id_by_name(self.code_env_name)
        if env_id:
            envs = await self._fetch_env_list()
            for env in envs:
                if env.get("id") == env_id:
                    value = env.get("value", "")
                    break
        return value

    async def _update_code_env(self, phone: str, code: str) -> bool:
        current = await self._get_code_env_value()
        lines = current.split('\n') if current else []
        lines = [line.strip() for line in lines if line.strip()]
        found = False
        new_lines = []
        for line in lines:
            if '#' in line:
                p, c = line.split('#', 1)
                if p.strip() == phone:
                    new_lines.append(f"{phone}#{code}")
                    found = True
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f"{phone}#{code}")
        new_value = '\n'.join(new_lines)
        return await self._update_env_value(self.code_env_name, new_value)

    # ---------- 账号相关 ----------
    async def _get_my_accounts(self, user_id: str) -> list:
        return self._get_cache_user(user_id)["accounts"]

    async def _get_my_env_entries(self, user_id: str) -> list:
        all_entries = await self._get_all_env_entries()
        my_phones = [acc["phone"] for acc in await self._get_my_accounts(user_id)]
        return [entry for entry in all_entries if entry["phone"] in my_phones]

    async def _get_user_total_auth(self, user_id: str) -> tuple:
        my_entries = await self._get_my_env_entries(user_id)
        total = 0
        has_unlimited = False
        for entry in my_entries:
            if entry["auth_count"] is None:
                has_unlimited = True
            else:
                total += entry["auth_count"]
        return total, has_unlimited

    def _is_phone_owned_by_other(self, user_id: str, phone: str) -> bool:
        for qq, data in self.cache.items():
            if qq == user_id:
                continue
            for acc in data["accounts"]:
                if acc["phone"] == phone:
                    return True
        return False

    async def _reset_user_data(self, user_id: str) -> bool:
        cache_user = self._get_cache_user(user_id)
        phones = [acc["phone"] for acc in cache_user["accounts"]]
        self.cache[user_id] = {"accounts": []}
        self._save_cache()
        if phones:
            env_entries = await self._get_all_env_entries()
            env_entries = [e for e in env_entries if e["phone"] not in phones]
            await self._save_all_env_entries(env_entries)
        return True

    # ---------- 辅助 ----------
    def _get_user_id(self, event: AstrMessageEvent) -> str:
        if hasattr(event, 'get_user_id'):
            return event.get_user_id()
        if hasattr(event, 'get_sender_id'):
            return event.get_sender_id()
        if hasattr(event, 'message_obj') and hasattr(event.message_obj, 'from_user_id'):
            return str(event.message_obj.from_user_id)
        if hasattr(event, 'sender_id'):
            return event.sender_id
        if hasattr(event, 'get_session_id'):
            return event.get_session_id()
        return "unknown"

    def _get_text(self, event: AstrMessageEvent) -> str:
        if hasattr(event, 'get_plain_text'):
            return event.get_plain_text().strip()
        if hasattr(event, 'message_str'):
            return event.message_str.strip()
        if hasattr(event, 'message'):
            msg = event.message
            if hasattr(msg, 'get_plain_text'):
                return msg.get_plain_text().strip()
            return str(msg).strip()
        if hasattr(event, 'raw_message'):
            return event.raw_message.strip()
        return ""

    # ---------- 状态管理 ----------
    def _get_state_info(self, user_id: str) -> dict:
        now = time.time()
        if user_id not in self.state_info:
            self.state_info[user_id] = {
                'state': 'idle',
                'last_active': now,
                'admin_mode': False,
                'tmp_data': {},
                'trigger_msg': None,
                'in_menu': False,
                'timeout_triggered': False,
                'event': None,          # 存储事件对象用于超时回复
                'session_id': None
            }
        return self.state_info[user_id]

    def _set_state(self, user_id: str, state: str, admin_mode: bool = False,
                   tmp_data: dict = None, trigger_msg: str = None,
                   in_menu: bool = False, session_id: str = None,
                   event: AstrMessageEvent = None):
        old = self.state_info.get(user_id, {})
        self.state_info[user_id] = {
            'state': state,
            'last_active': time.time(),
            'admin_mode': admin_mode,
            'tmp_data': tmp_data or {},
            'trigger_msg': trigger_msg,
            'in_menu': in_menu,
            'timeout_triggered': False,
            'event': event if event is not None else old.get('event'),
            'session_id': session_id if session_id is not None else old.get('session_id')
        }

    def _reset_admin_state(self, user_id: str):
        info = self._get_state_info(user_id)
        if info['state'] != 'idle':
            info['state'] = 'idle'
            info['tmp_data'] = {}
            info['trigger_msg'] = None
            info['in_menu'] = False
            info['timeout_triggered'] = False
            # 保留 event，可能在超时后仍需使用？但超时后会重置，可清空 event
            info['event'] = None

    # ---------- 超时任务管理 ----------
    async def _timeout_callback(self, user_id: str):
        info = self._get_state_info(user_id)
        if info['in_menu'] or info['state'] != 'idle':
            # 尝试使用存储的 event 对象主动回复
            event = info.get('event')
            sent = False
            if event:
                try:
                    # 使用 event.reply 方法（同步，但可在异步中调用）
                    event.reply("⏰ 操作已超时，已退出交互。")
                    logger.info(f"✅ 已通过 event.reply 发送超时提醒给用户 {user_id}")
                    sent = True
                except Exception as e:
                    logger.warning(f"使用 event.reply 发送超时失败: {e}")

            # 如果 event.reply 失败，尝试其他方式（但之前的 session 方式均失败，保留作为 fallback）
            if not sent:
                # 尝试使用 context.send_message 和 event（如果支持）
                if event:
                    try:
                        await self.context.send_message(event, "⏰ 操作已超时，已退出交互。")
                        logger.info(f"✅ 已通过 context.send_message(event) 发送超时提醒")
                        sent = True
                    except Exception as e:
                        logger.warning(f"使用 context.send_message(event) 失败: {e}")

            # 最后仍尝试旧方法（但不太可能成功）
            if not sent:
                sid = info.get('session_id')
                if sid:
                    try:
                        await self.context.send_message(sid, "⏰ 操作已超时，已退出交互。")
                        logger.info(f"✅ 已向会话 {sid} 发送超时提醒")
                        sent = True
                    except Exception as e:
                        logger.debug(f"session_id {sid} 发送失败: {e}")

            if not sent:
                logger.error(f"❌ 所有方式均失败，无法发送超时提醒 (user_id={user_id})")

            # 重置状态
            self._set_state(user_id, 'idle', admin_mode=False, tmp_data={}, in_menu=False)
            if user_id in self.timeout_tasks:
                del self.timeout_tasks[user_id]

    def _schedule_timeout(self, user_id: str):
        if user_id in self.timeout_tasks:
            self.timeout_tasks[user_id].cancel()
            del self.timeout_tasks[user_id]
        task = asyncio.create_task(self._timeout_after_delay(user_id))
        self.timeout_tasks[user_id] = task

    async def _timeout_after_delay(self, user_id: str):
        try:
            await asyncio.sleep(self.TIMEOUT)
            await self._timeout_callback(user_id)
        except asyncio.CancelledError:
            pass

    def _cancel_timeout(self, user_id: str):
        if user_id in self.timeout_tasks:
            self.timeout_tasks[user_id].cancel()
            del self.timeout_tasks[user_id]

    # ---------- 菜单 ----------
    async def _get_menu_text(self, user_id: str) -> str:
        my_acc = await self._get_my_accounts(user_id)
        count = len(my_acc)
        total, has_unlimited = await self._get_user_total_auth(user_id)
        if has_unlimited:
            total_display = "不限"
        else:
            total_display = str(total)
        return (
            f"=====酷我=====\n"
            f"账号{count}个，可用次数{total_display}\n"
            "[1] 提交账号\n"
            "[2] 删除账号\n"
            "[3] 查询授权次数明细\n"
            "[4] 提交验证码\n"
            "[r] 重置我的所有数据\n"
            "[q] 退出"
        )

    async def _get_admin_menu_text(self) -> str:
        return (
            "=====管理面板=====\n"
            "[1] 查看所有绑定关系\n"
            "[2] 查看所有环境变量账号\n"
            "[3] 绑定账号（为QQ绑定手机号）\n"
            "[4] 解除绑定（从QQ移除绑定，保留环境变量）\n"
            "[5] 删除账号（从所有绑定和环境变量移除）\n"
            "[6] 修改授权次数（设置具体值或无限制）\n"
            "[7] 提现审核（扣减授权次数）\n"
            "[8] 重置用户所有数据\n"
            "[q] 退出"
        )

    # ---------- 全局 q 处理器 ----------
    @filter.regex(r'^[qQ]$')
    async def handle_global_q(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        state_info = self._get_state_info(user_id)
        if state_info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 操作已超时，已退出交互。")
            self._set_state(user_id, 'idle', admin_mode=False, in_menu=False)
            self._cancel_timeout(user_id)
            return

        current_state = state_info['state']
        admin_mode = state_info.get('admin_mode', False)
        in_menu = state_info.get('in_menu', False)

        if current_state == 'menu_idle' and in_menu:
            yield event.plain_result("👋 已退出菜单")
            self._set_state(user_id, 'idle', admin_mode=False, in_menu=False)
            self._cancel_timeout(user_id)
            return

        if current_state == 'admin_menu_idle' and in_menu and admin_mode:
            yield event.plain_result("👋 已退出管理面板")
            self._set_state(user_id, 'idle', admin_mode=False, in_menu=False)
            self._cancel_timeout(user_id)
            return

        if in_menu and current_state not in ['idle', 'menu_idle', 'admin_menu_idle']:
            if admin_mode:
                yield event.plain_result("👋 已取消操作，返回管理面板")
                self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, event=event)
                self._schedule_timeout(user_id)
                menu = await self._get_admin_menu_text()
                yield event.plain_result(menu)
            else:
                yield event.plain_result("👋 已取消操作，返回菜单")
                self._set_state(user_id, 'menu_idle', admin_mode=False, in_menu=True, event=event)
                self._schedule_timeout(user_id)
                menu = await self._get_menu_text(user_id)
                yield event.plain_result(menu)
            return

    # ---------- 普通用户菜单 ----------
    @filter.command("酷我")
    async def kuwo_menu(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        state_info = self._get_state_info(user_id)
        if state_info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 操作已超时，已退出交互。")
            self._set_state(user_id, 'idle', admin_mode=False, in_menu=False)
            self._cancel_timeout(user_id)
            return
        if state_info.get('admin_mode', False):
            yield event.plain_result("👋 已退出管理面板")
            self._set_state(user_id, 'idle', admin_mode=False, in_menu=False)
            self._cancel_timeout(user_id)
        self._reset_admin_state(user_id)
        # 传入 event 对象
        self._set_state(user_id, 'menu_idle', admin_mode=False, in_menu=True, event=event)
        self._schedule_timeout(user_id)
        menu = await self._get_menu_text(user_id)
        yield event.plain_result(menu)

    @filter.regex(r'^[1-4rR]$')
    async def handle_menu_choice(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        state_info = self._get_state_info(user_id)
        if state_info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 操作已超时，已退出交互。")
            self._set_state(user_id, 'idle', admin_mode=False, in_menu=False)
            self._cancel_timeout(user_id)
            return
        if state_info.get('admin_mode', False):
            return
        if not state_info.get('in_menu', False) or state_info['state'] != 'menu_idle':
            return

        text = self._get_text(event).lower()

        if text == '1':
            self._set_state(user_id, 'waiting_phone', admin_mode=False, in_menu=True, event=event)
            self._schedule_timeout(user_id)
            yield event.plain_result("请输入手机号#密码（例如：13800138000#mypassword）（发送 q 取消）")
        elif text == '2':
            my_acc = await self._get_my_accounts(user_id)
            if not my_acc:
                yield event.plain_result("❌ 您没有绑定任何账号")
            else:
                lines = [f"{idx+1}. {acc['phone']}" for idx, acc in enumerate(my_acc)]
                prompt = "您的账号：\n" + "\n".join(lines) + "\n请输入要删除的序号（如 1）（发送 q 取消）："
                yield event.plain_result(prompt)
                self._set_state(user_id, 'waiting_delete', admin_mode=False, trigger_msg=text, in_menu=True, event=event)
                self._schedule_timeout(user_id)
        elif text == '3':
            my_env_entries = await self._get_my_env_entries(user_id)
            if not my_env_entries:
                yield event.plain_result("📭 您当前没有绑定任何账号，或账号尚未同步到环境变量。")
            else:
                msg = "📋 您的账号授权次数明细：\n"
                total = 0
                has_unlimited = False
                for entry in my_env_entries:
                    auth_display = "无限制" if entry["auth_count"] is None else str(entry["auth_count"])
                    msg += f"手机号：{entry['phone']} ｜ 授权次数：{auth_display}\n"
                    if entry["auth_count"] is not None:
                        total += entry["auth_count"]
                    else:
                        has_unlimited = True
                if has_unlimited:
                    msg += f"合计：存在无限制账号，总可用次数不限"
                else:
                    msg += f"合计可用次数：{total}"
                yield event.plain_result(msg)
            self._set_state(user_id, 'menu_idle', admin_mode=False, in_menu=True, event=event)
            self._schedule_timeout(user_id)
            menu = await self._get_menu_text(user_id)
            yield event.plain_result(menu)
        elif text == '4':
            my_acc = await self._get_my_accounts(user_id)
            if not my_acc:
                yield event.plain_result("❌ 您没有绑定任何账号，请先提交账号")
            else:
                lines = [f"{idx+1}. {acc['phone']}" for idx, acc in enumerate(my_acc)]
                prompt = "请选择要提交验证码的账号序号：\n" + "\n".join(lines) + "\n请输入序号（发送 q 取消）："
                yield event.plain_result(prompt)
                self._set_state(user_id, 'waiting_code_phone', admin_mode=False, trigger_msg=text, in_menu=True, event=event)
                self._schedule_timeout(user_id)
        elif text == 'r':
            await self._reset_user_data(user_id)
            yield event.plain_result("✅ 您的所有数据已重置")
            self._set_state(user_id, 'menu_idle', admin_mode=False, in_menu=True, event=event)
            self._schedule_timeout(user_id)
            menu = await self._get_menu_text(user_id)
            yield event.plain_result(menu)

    # ---------- 提交验证码：输入验证码 ----------
    @filter.regex(r'^.+$')
    async def handle_code_input(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        state_info = self._get_state_info(user_id)
        if state_info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 操作已超时，已退出交互。")
            self._set_state(user_id, 'idle', admin_mode=False, in_menu=False)
            self._cancel_timeout(user_id)
            return
        if state_info['state'] != 'waiting_code_input' or not state_info.get('in_menu', False):
            return

        text = self._get_text(event)
        code = text
        if not code:
            yield event.plain_result("❌ 验证码不能为空")
            return
        phone = state_info.get('tmp_data', {}).get('phone')
        if not phone:
            yield event.plain_result("❌ 会话错误，请重新操作")
            self._set_state(user_id, 'menu_idle', admin_mode=False, in_menu=True, event=event)
            self._schedule_timeout(user_id)
            menu = await self._get_menu_text(user_id)
            yield event.plain_result(menu)
            return

        self._set_state(user_id, 'idle', admin_mode=False, in_menu=False)
        self._cancel_timeout(user_id)

        if await self._update_code_env(phone, code):
            yield event.plain_result(f"✅ 验证码已提交：手机号 {phone} -> {code}")
        else:
            yield event.plain_result("❌ 提交验证码失败，请稍后重试")

        self._set_state(user_id, 'menu_idle', admin_mode=False, in_menu=True, event=event)
        self._schedule_timeout(user_id)
        menu = await self._get_menu_text(user_id)
        yield event.plain_result(menu)

    # ---------- 提交验证码：选择手机号 ----------
    @filter.regex(r'^\d+$')
    async def handle_code_phone_select(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        state_info = self._get_state_info(user_id)
        if state_info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 操作已超时，已退出交互。")
            self._set_state(user_id, 'idle', admin_mode=False, in_menu=False)
            self._cancel_timeout(user_id)
            return
        if state_info['state'] != 'waiting_code_phone' or not state_info.get('in_menu', False):
            return
        current_text = self._get_text(event)
        if state_info.get('trigger_msg') == current_text:
            return
        try:
            idx = int(current_text)
        except:
            yield event.plain_result("❌ 请输入有效的数字")
            return

        my_acc = await self._get_my_accounts(user_id)
        if idx < 1 or idx > len(my_acc):
            yield event.plain_result(f"❌ 序号无效，请输入 1 到 {len(my_acc)} 之间的数字")
            return
        phone = my_acc[idx-1]["phone"]
        self._set_state(user_id, 'waiting_code_input', admin_mode=False, tmp_data={'phone': phone}, in_menu=True, event=event)
        self._schedule_timeout(user_id)
        yield event.plain_result(f"已选择账号 {phone}，请输入验证码（发送 q 取消）：")

    # ---------- 提交账号（普通用户） ----------
    @filter.regex(r'^\d{11}#.+$')
    async def handle_phone_submit(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        state_info = self._get_state_info(user_id)
        if state_info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 操作已超时，已退出交互。")
            self._set_state(user_id, 'idle', admin_mode=False, in_menu=False)
            self._cancel_timeout(user_id)
            return
        if state_info['state'] != 'waiting_phone' or not state_info.get('in_menu', False):
            return

        text = self._get_text(event)
        phone, password = text.split('#', 1)
        phone = phone.strip()
        password = password.strip()

        if self._is_phone_owned_by_other(user_id, phone):
            yield event.plain_result(f"❌ 手机号 {phone} 已被其他用户绑定")
            self._set_state(user_id, 'menu_idle', admin_mode=False, in_menu=True, event=event)
            self._schedule_timeout(user_id)
            menu = await self._get_menu_text(user_id)
            yield event.plain_result(menu)
            return

        cache_user = self._get_cache_user(user_id)
        my_acc = cache_user["accounts"]
        found = None
        for acc in my_acc:
            if acc["phone"] == phone:
                found = acc
                break
        if found:
            found["password"] = password
            self._update_cache_user(user_id, my_acc)
            env_entries = await self._get_all_env_entries()
            for entry in env_entries:
                if entry["phone"] == phone:
                    entry["password"] = password
                    break
            await self._save_all_env_entries(env_entries)
            yield event.plain_result(f"✅ 账号 {phone} 密码已更新")
        else:
            my_acc.append({"phone": phone, "password": password})
            self._update_cache_user(user_id, my_acc)
            env_entries = await self._get_all_env_entries()
            env_entries.append({"phone": phone, "password": password, "auth_count": None})
            await self._save_all_env_entries(env_entries)
            yield event.plain_result(f"✅ 账号 {phone} 已保存（默认无限制）")

        self._set_state(user_id, 'menu_idle', admin_mode=False, in_menu=True, event=event)
        self._schedule_timeout(user_id)
        menu = await self._get_menu_text(user_id)
        yield event.plain_result(menu)

    # ---------- 删除账号（普通用户） ----------
    @filter.regex(r'^\d+$')
    async def handle_delete_index(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        state_info = self._get_state_info(user_id)
        if state_info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 操作已超时，已退出交互。")
            self._set_state(user_id, 'idle', admin_mode=False, in_menu=False)
            self._cancel_timeout(user_id)
            return
        if state_info['state'] != 'waiting_delete' or not state_info.get('in_menu', False):
            return
        current_text = self._get_text(event)
        if state_info.get('trigger_msg') == current_text:
            return
        try:
            idx = int(current_text)
        except:
            yield event.plain_result("❌ 请输入有效的数字")
            self._set_state(user_id, 'menu_idle', admin_mode=False, in_menu=True, event=event)
            self._schedule_timeout(user_id)
            menu = await self._get_menu_text(user_id)
            yield event.plain_result(menu)
            return

        cache_user = self._get_cache_user(user_id)
        my_acc = cache_user["accounts"]
        if idx < 1 or idx > len(my_acc):
            yield event.plain_result(f"❌ 序号无效，请输入 1 到 {len(my_acc)} 之间的数字")
            self._set_state(user_id, 'menu_idle', admin_mode=False, in_menu=True, event=event)
            self._schedule_timeout(user_id)
            menu = await self._get_menu_text(user_id)
            yield event.plain_result(menu)
            return

        phone_to_del = my_acc[idx-1]["phone"]
        del my_acc[idx-1]
        self._update_cache_user(user_id, my_acc)
        env_entries = await self._get_all_env_entries()
        env_entries = [e for e in env_entries if e["phone"] != phone_to_del]
        await self._save_all_env_entries(env_entries)

        yield event.plain_result(f"✅ 已删除账号 {phone_to_del}")
        self._set_state(user_id, 'menu_idle', admin_mode=False, in_menu=True, event=event)
        self._schedule_timeout(user_id)
        menu = await self._get_menu_text(user_id)
        yield event.plain_result(menu)

    # ---------- 管理员交互 ----------
    @filter.command("酷我管理")
    async def admin_menu(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        if user_id not in self.admin_qqs:
            yield event.plain_result("❌ 你没有权限执行此操作")
            return
        state_info = self._get_state_info(user_id)
        if state_info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 操作已超时，已退出交互。")
            self._set_state(user_id, 'idle', admin_mode=False, in_menu=False)
            self._cancel_timeout(user_id)
            return
        if state_info['state'] != 'idle' and not state_info.get('admin_mode', False):
            yield event.plain_result("👋 已退出普通用户菜单")
            self._set_state(user_id, 'idle', admin_mode=False, in_menu=False)
            self._cancel_timeout(user_id)
        self._reset_admin_state(user_id)
        self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, event=event)
        self._schedule_timeout(user_id)
        menu = await self._get_admin_menu_text()
        yield event.plain_result(menu)

    # ---------- 数字专用处理器（管理员） ----------
    @filter.regex(r'^\d+$')
    async def handle_admin_digit(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        if user_id not in self.admin_qqs:
            return
        state_info = self._get_state_info(user_id)
        if state_info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 操作已超时，已退出交互。")
            self._set_state(user_id, 'idle', admin_mode=False, in_menu=False)
            self._cancel_timeout(user_id)
            return
        if not state_info.get('admin_mode', False) or not state_info.get('in_menu', False):
            return

        current_state = state_info['state']
        text = self._get_text(event)
        try:
            num = int(text)
        except:
            return

        if current_state == 'admin_delete_wait_confirm':
            return

        if current_state == 'admin_auth_wait_new_value':
            phone = state_info.get('tmp_data', {}).get('phone')
            if not phone:
                yield event.plain_result("❌ 会话错误，请重新操作")
                self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, event=event)
                self._schedule_timeout(user_id)
                menu = await self._get_admin_menu_text()
                yield event.plain_result(menu)
                return
            if num < 0:
                yield event.plain_result("❌ 授权次数不能为负数")
                return
            env_entries = await self._get_all_env_entries()
            found = False
            for entry in env_entries:
                if entry["phone"] == phone:
                    entry["auth_count"] = num
                    found = True
                    break
            if not found:
                yield event.plain_result(f"❌ 手机号 {phone} 不存在于环境变量中")
                self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, event=event)
                self._schedule_timeout(user_id)
                menu = await self._get_admin_menu_text()
                yield event.plain_result(menu)
                return
            if await self._save_all_env_entries(env_entries):
                yield event.plain_result(f"✅ 手机号 {phone} 授权次数已设置为 {num}")
            else:
                yield event.plain_result("❌ 保存失败")
            self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, event=event)
            self._schedule_timeout(user_id)
            menu = await self._get_admin_menu_text()
            yield event.plain_result(menu)
            return

        if current_state == 'admin_menu_idle':
            if num == 1:
                result = await self._admin_view_all_bindings()
                yield event.plain_result(result)
                self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, event=event)
                self._schedule_timeout(user_id)
                menu = await self._get_admin_menu_text()
                yield event.plain_result(menu)
            elif num == 2:
                result = await self._admin_view_all_env_accounts()
                yield event.plain_result(result)
                self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, event=event)
                self._schedule_timeout(user_id)
                menu = await self._get_admin_menu_text()
                yield event.plain_result(menu)
            elif num == 3:
                self._set_state(user_id, 'admin_bind_wait_phone_select', admin_mode=True, in_menu=True, tmp_data={}, event=event)
                self._schedule_timeout(user_id)
                async for msg in self._admin_bind_select_phone(event):
                    yield msg
            elif num == 4:
                self._set_state(user_id, 'admin_unbind_wait_select', admin_mode=True, in_menu=True, tmp_data={}, event=event)
                self._schedule_timeout(user_id)
                async for msg in self._admin_unbind_select(event):
                    yield msg
            elif num == 5:
                self._set_state(user_id, 'admin_delete_wait_select', admin_mode=True, in_menu=True, tmp_data={}, event=event)
                self._schedule_timeout(user_id)
                async for msg in self._admin_delete_select(event):
                    yield msg
            elif num == 6:
                self._set_state(user_id, 'admin_auth_wait_select', admin_mode=True, in_menu=True, tmp_data={}, event=event)
                self._schedule_timeout(user_id)
                async for msg in self._admin_auth_select(event):
                    yield msg
            elif num == 7:
                self._set_state(user_id, 'admin_withdraw_wait_select', admin_mode=True, in_menu=True, tmp_data={}, event=event)
                self._schedule_timeout(user_id)
                async for msg in self._admin_withdraw_select(event):
                    yield msg
            elif num == 8:
                self._set_state(user_id, 'admin_reset_wait_select', admin_mode=True, in_menu=True, tmp_data={}, event=event)
                self._schedule_timeout(user_id)
                async for msg in self._admin_reset_select(event):
                    yield msg
            else:
                yield event.plain_result("❌ 无效选项，请输入 1-8 或 q")
        else:
            # 子状态（所有子状态操作均传入 event）
            if current_state == 'admin_bind_wait_phone_select':
                async for msg in self._admin_bind_phone_select_handle(event):
                    yield msg
            elif current_state == 'admin_bind_wait_qq_select':
                result = await self._admin_bind_qq_select_handle(event)
                yield event.plain_result(result)
                self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, event=event)
                self._schedule_timeout(user_id)
                menu = await self._get_admin_menu_text()
                yield event.plain_result(menu)
            elif current_state == 'admin_bind_wait_qq_input':
                result = await self._admin_bind_qq_input_handle(event)
                yield event.plain_result(result)
                self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, event=event)
                self._schedule_timeout(user_id)
                menu = await self._get_admin_menu_text()
                yield event.plain_result(menu)
            elif current_state == 'admin_unbind_wait_select':
                async for msg in self._admin_unbind_select_handle(event):
                    yield msg
            elif current_state == 'admin_delete_wait_select':
                async for msg in self._admin_delete_select_handle(event):
                    yield msg
            elif current_state == 'admin_auth_wait_select':
                async for msg in self._admin_auth_select_handle(event):
                    yield msg
            elif current_state == 'admin_withdraw_wait_select':
                async for msg in self._admin_withdraw_select_handle(event):
                    yield msg
            elif current_state == 'admin_reset_wait_select':
                async for msg in self._admin_reset_select_handle(event):
                    yield msg

    # ---------- 非数字通用处理器（管理员） ----------
    @filter.regex(r'^[^0-9].*$')
    async def handle_admin_non_digit(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        if user_id not in self.admin_qqs:
            return
        state_info = self._get_state_info(user_id)
        if state_info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 操作已超时，已退出交互。")
            self._set_state(user_id, 'idle', admin_mode=False, in_menu=False)
            self._cancel_timeout(user_id)
            return
        if not state_info.get('admin_mode', False) or not state_info.get('in_menu', False):
            return

        current_state = state_info['state']
        text = self._get_text(event).strip()

        if current_state == 'admin_auth_wait_new_value':
            if text in ['无限制', '无限', 'unlimited']:
                phone = state_info.get('tmp_data', {}).get('phone')
                if not phone:
                    yield event.plain_result("❌ 会话错误，请重新操作")
                    self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, event=event)
                    self._schedule_timeout(user_id)
                    menu = await self._get_admin_menu_text()
                    yield event.plain_result(menu)
                    return
                env_entries = await self._get_all_env_entries()
                found = False
                for entry in env_entries:
                    if entry["phone"] == phone:
                        entry["auth_count"] = None
                        found = True
                        break
                if not found:
                    yield event.plain_result(f"❌ 手机号 {phone} 不存在于环境变量中")
                    self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, event=event)
                    self._schedule_timeout(user_id)
                    menu = await self._get_admin_menu_text()
                    yield event.plain_result(menu)
                    return
                if await self._save_all_env_entries(env_entries):
                    yield event.plain_result(f"✅ 手机号 {phone} 已设为无限制")
                else:
                    yield event.plain_result("❌ 保存失败")
                self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, event=event)
                self._schedule_timeout(user_id)
                menu = await self._get_admin_menu_text()
                yield event.plain_result(menu)
            else:
                yield event.plain_result("❌ 输入无效，请输入数字或 '无限制'")
            return

        if current_state == 'admin_delete_wait_confirm':
            if text.lower() == 'y':
                phone_to_del = state_info.get('tmp_data', {}).get('phone_to_del')
                if not phone_to_del:
                    yield event.plain_result("❌ 会话错误，请重新操作")
                else:
                    result = await self._admin_do_delete(phone_to_del)
                    yield event.plain_result(result)
                self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, event=event)
                self._schedule_timeout(user_id)
                menu = await self._get_admin_menu_text()
                yield event.plain_result(menu)
            elif text.lower() == 'n':
                yield event.plain_result("❌ 已取消删除操作")
                self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, event=event)
                self._schedule_timeout(user_id)
                menu = await self._get_admin_menu_text()
                yield event.plain_result(menu)
            else:
                yield event.plain_result("❌ 已取消删除操作")
                self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, event=event)
                self._schedule_timeout(user_id)
                menu = await self._get_admin_menu_text()
                yield event.plain_result(menu)

    # ---------- 管理员查看功能 ----------
    async def _admin_view_all_bindings(self) -> str:
        if not self.cache:
            return "📭 暂无任何用户绑定数据"
        msg = "📋 所有绑定关系（手机号，密码已隐藏）\n\n"
        total_users = 0
        total_accounts = 0
        for qq, data in self.cache.items():
            accounts = data.get("accounts", [])
            if not accounts:
                continue
            total_users += 1
            total_accounts += len(accounts)
            msg += f"👤 QQ: {qq}\n"
            for acc in accounts:
                msg += f"  📱 {acc['phone']}\n"
            msg += "\n"
        if total_users == 0:
            return "📭 暂无任何用户绑定数据"
        msg += f"统计：共 {total_users} 个用户，{total_accounts} 个绑定账号"
        return msg

    async def _admin_view_all_env_accounts(self) -> str:
        env_entries = await self._get_all_env_entries()
        if not env_entries:
            return "📭 环境变量中暂无任何账号"
        phone_to_qq = {}
        for qq, data in self.cache.items():
            for acc in data.get("accounts", []):
                phone_to_qq[acc["phone"]] = qq

        msg = "📋 环境变量账号列表（含未绑定QQ）\n\n"
        for entry in env_entries:
            phone = entry["phone"]
            auth_display = "无限制" if entry["auth_count"] is None else str(entry["auth_count"])
            qq = phone_to_qq.get(phone, "未绑定")
            msg += f"📱 {phone} ｜ 授权: {auth_display} ｜ 绑定QQ: {qq}\n"
        return msg

    # ---------- 绑定账号子操作 ----------
    async def _admin_bind_select_phone(self, event):
        user_id = self._get_user_id(event)
        state_info = self._get_state_info(user_id)
        if state_info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 操作已超时，已退出交互。")
            self._set_state(user_id, 'idle', admin_mode=False, in_menu=False)
            self._cancel_timeout(user_id)
            return
        if state_info['state'] != 'admin_bind_wait_phone_select':
            return

        env_entries = await self._get_all_env_entries()
        if not env_entries:
            yield event.plain_result("❌ 环境变量中暂无账号，请先让用户提交账号或手动添加")
            self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, event=event)
            self._schedule_timeout(user_id)
            menu = await self._get_admin_menu_text()
            yield event.plain_result(menu)
            return

        bound_phones = set()
        for qq, data in self.cache.items():
            for acc in data.get("accounts", []):
                bound_phones.add(acc["phone"])
        unbound_phones = [entry for entry in env_entries if entry["phone"] not in bound_phones]
        if not unbound_phones:
            yield event.plain_result("✅ 所有环境变量账号均已绑定，无需操作")
            self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, event=event)
            self._schedule_timeout(user_id)
            menu = await self._get_admin_menu_text()
            yield event.plain_result(menu)
            return

        msg = "📋 未绑定的手机号列表：\n"
        for idx, entry in enumerate(unbound_phones, 1):
            auth_display = "无限制" if entry["auth_count"] is None else str(entry["auth_count"])
            msg += f"{idx}. {entry['phone']} ｜ 授权次数: {auth_display}\n"
        msg += "请选择要绑定的手机号序号（发送 q 取消）："
        self._set_state(user_id, 'admin_bind_wait_phone_select', admin_mode=True, in_menu=True, tmp_data={'unbound_phones': unbound_phones}, event=event)
        self._schedule_timeout(user_id)
        yield event.plain_result(msg)

    async def _admin_bind_phone_select_handle(self, event):
        user_id = self._get_user_id(event)
        state_info = self._get_state_info(user_id)
        if state_info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 操作已超时，已退出交互。")
            self._set_state(user_id, 'idle', admin_mode=False, in_menu=False)
            self._cancel_timeout(user_id)
            return
        if state_info['state'] != 'admin_bind_wait_phone_select':
            return
        current_text = self._get_text(event)
        if state_info.get('trigger_msg') == current_text:
            return
        try:
            idx = int(current_text)
        except:
            yield event.plain_result("❌ 请输入有效的数字")
            return
        unbound_phones = state_info.get('tmp_data', {}).get('unbound_phones', [])
        if idx < 1 or idx > len(unbound_phones):
            yield event.plain_result(f"❌ 序号无效，请输入 1 到 {len(unbound_phones)} 之间的数字")
            return

        selected_phone = unbound_phones[idx-1]["phone"]
        qq_list = list(self.cache.keys())
        if qq_list:
            msg = "📋 可绑定的QQ列表：\n"
            for i, qq in enumerate(qq_list, 1):
                acc_count = len(self.cache[qq].get("accounts", []))
                msg += f"{i}. {qq} ｜ 账号数: {acc_count}\n"
            msg += f"请输入要绑定到该手机号的QQ序号（或直接输入新QQ号，发送 q 取消）："
            self._set_state(user_id, 'admin_bind_wait_qq_select', admin_mode=True, in_menu=True, tmp_data={'selected_phone': selected_phone, 'qq_list': qq_list}, event=event)
            self._schedule_timeout(user_id)
            yield event.plain_result(msg)
        else:
            self._set_state(user_id, 'admin_bind_wait_qq_input', admin_mode=True, in_menu=True, tmp_data={'selected_phone': selected_phone}, event=event)
            self._schedule_timeout(user_id)
            yield event.plain_result("当前无绑定记录，请输入要绑定的QQ号（发送 q 取消）：")

    async def _admin_bind_qq_select_handle(self, event) -> str:
        user_id = self._get_user_id(event)
        state_info = self._get_state_info(user_id)
        if state_info.get('timeout_triggered', False):
            return "⏰ 操作已超时，已退出交互。"
        if state_info['state'] != 'admin_bind_wait_qq_select':
            return "状态错误，请重新操作"
        current_text = self._get_text(event)
        tmp = state_info.get('tmp_data', {})
        selected_phone = tmp.get('selected_phone')
        qq_list = tmp.get('qq_list', [])

        if current_text.isdigit():
            if len(current_text) <= 5:
                idx = int(current_text)
                if 1 <= idx <= len(qq_list):
                    target_qq = qq_list[idx-1]
                else:
                    return f"❌ 序号无效，请输入 1 到 {len(qq_list)} 之间的数字，或输入6位以上新QQ号"
            else:
                target_qq = current_text
        else:
            return "❌ 请输入数字（序号或新QQ号）"

        result = await self._admin_do_bind(target_qq, selected_phone)
        self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, event=event)
        self._schedule_timeout(user_id)
        return result

    async def _admin_bind_qq_input_handle(self, event) -> str:
        user_id = self._get_user_id(event)
        state_info = self._get_state_info(user_id)
        if state_info.get('timeout_triggered', False):
            return "⏰ 操作已超时，已退出交互。"
        if state_info['state'] != 'admin_bind_wait_qq_input':
            return "状态错误，请重新操作"
        current_text = self._get_text(event)
        if not current_text.isdigit():
            return "❌ QQ号须为数字"
        target_qq = current_text
        selected_phone = state_info.get('tmp_data', {}).get('selected_phone')
        if not selected_phone:
            return "❌ 会话错误，请重新操作"
        result = await self._admin_do_bind(target_qq, selected_phone)
        self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, event=event)
        self._schedule_timeout(user_id)
        return result

    async def _admin_do_bind(self, target_qq: str, phone: str) -> str:
        existing_owner = None
        for qq, data in self.cache.items():
            for acc in data["accounts"]:
                if acc["phone"] == phone:
                    existing_owner = qq
                    break
            if existing_owner:
                break
        target_cache = self._get_cache_user(target_qq)
        accounts = target_cache["accounts"]
        for acc in accounts:
            if acc["phone"] == phone:
                return f"⚠️ 用户 {target_qq} 已绑定该手机号"
        password = "admin_placeholder"
        accounts.append({"phone": phone, "password": password})
        self._update_cache_user(target_qq, accounts)
        msg = f"✅ 已为用户 {target_qq} 绑定手机号 {phone}"
        if existing_owner and existing_owner != target_qq:
            msg += f"\n⚠️ 注意：该手机号原本属于用户 {existing_owner}，已被管理员强制迁移至 {target_qq}"
        return msg

    # ---------- 解除绑定子操作 ----------
    async def _admin_unbind_select(self, event):
        user_id = self._get_user_id(event)
        state_info = self._get_state_info(user_id)
        if state_info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 操作已超时，已退出交互。")
            self._set_state(user_id, 'idle', admin_mode=False, in_menu=False)
            self._cancel_timeout(user_id)
            return
        if state_info['state'] != 'admin_unbind_wait_select':
            return

        env_entries = await self._get_all_env_entries()
        if not env_entries:
            yield event.plain_result("❌ 环境变量中暂无账号")
            self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, event=event)
            self._schedule_timeout(user_id)
            menu = await self._get_admin_menu_text()
            yield event.plain_result(menu)
            return

        phone_to_qq = {}
        for qq, data in self.cache.items():
            for acc in data.get("accounts", []):
                phone_to_qq[acc["phone"]] = qq

        bound_list = []
        for entry in env_entries:
            phone = entry["phone"]
            if phone in phone_to_qq:
                bound_list.append({
                    "phone": phone,
                    "auth_count": entry["auth_count"],
                    "qq": phone_to_qq[phone]
                })

        if not bound_list:
            yield event.plain_result("✅ 没有已绑定的账号需要解除")
            self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, event=event)
            self._schedule_timeout(user_id)
            menu = await self._get_admin_menu_text()
            yield event.plain_result(menu)
            return

        msg = "📋 已绑定的账号列表（解除绑定将保留环境变量）：\n"
        for idx, item in enumerate(bound_list, 1):
            auth_display = "无限制" if item["auth_count"] is None else str(item["auth_count"])
            msg += f"{idx}. {item['phone']} ｜ 授权: {auth_display} ｜ 绑定QQ: {item['qq']}\n"
        msg += "请输入要解除绑定的账号序号（发送 q 取消）："
        self._set_state(user_id, 'admin_unbind_wait_select', admin_mode=True, in_menu=True, tmp_data={'bound_list': bound_list}, event=event)
        self._schedule_timeout(user_id)
        yield event.plain_result(msg)

    async def _admin_unbind_select_handle(self, event):
        user_id = self._get_user_id(event)
        state_info = self._get_state_info(user_id)
        if state_info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 操作已超时，已退出交互。")
            self._set_state(user_id, 'idle', admin_mode=False, in_menu=False)
            self._cancel_timeout(user_id)
            return
        if state_info['state'] != 'admin_unbind_wait_select':
            return
        current_text = self._get_text(event)
        if state_info.get('trigger_msg') == current_text:
            return
        try:
            idx = int(current_text)
        except:
            yield event.plain_result("❌ 请输入有效的数字")
            return
        bound_list = state_info.get('tmp_data', {}).get('bound_list', [])
        if idx < 1 or idx > len(bound_list):
            yield event.plain_result(f"❌ 序号无效，请输入 1 到 {len(bound_list)} 之间的数字")
            return
        item = bound_list[idx-1]
        phone = item["phone"]
        qq = item["qq"]

        cache_user = self._get_cache_user(qq)
        accounts = cache_user["accounts"]
        new_accounts = [acc for acc in accounts if acc["phone"] != phone]
        if len(new_accounts) == len(accounts):
            yield event.plain_result(f"❌ 手机号 {phone} 不在用户 {qq} 的绑定列表中")
            self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, event=event)
            self._schedule_timeout(user_id)
            menu = await self._get_admin_menu_text()
            yield event.plain_result(menu)
            return
        self._update_cache_user(qq, new_accounts)
        yield event.plain_result(f"✅ 已解除绑定：手机号 {phone} 从 QQ {qq} 移除（环境变量中的账号保留）")
        self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, event=event)
        self._schedule_timeout(user_id)
        menu = await self._get_admin_menu_text()
        yield event.plain_result(menu)

    # ---------- 删除账号子操作 ----------
    async def _admin_delete_select(self, event):
        user_id = self._get_user_id(event)
        state_info = self._get_state_info(user_id)
        if state_info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 操作已超时，已退出交互。")
            self._set_state(user_id, 'idle', admin_mode=False, in_menu=False)
            self._cancel_timeout(user_id)
            return
        if state_info['state'] != 'admin_delete_wait_select':
            return

        env_entries = await self._get_all_env_entries()
        if not env_entries:
            yield event.plain_result("❌ 环境变量中暂无账号")
            self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, event=event)
            self._schedule_timeout(user_id)
            menu = await self._get_admin_menu_text()
            yield event.plain_result(menu)
            return
        msg = "📋 所有环境变量账号：\n"
        for idx, entry in enumerate(env_entries, 1):
            phone = entry["phone"]
            auth_display = "无限制" if entry["auth_count"] is None else str(entry["auth_count"])
            bound_qq = "未绑定"
            for qq, data in self.cache.items():
                for acc in data["accounts"]:
                    if acc["phone"] == phone:
                        bound_qq = qq
                        break
                if bound_qq != "未绑定":
                    break
            msg += f"{idx}. {phone} ｜ 授权: {auth_display} ｜ 绑定QQ: {bound_qq}\n"
        msg += "请输入要删除的账号序号（发送 q 取消）："
        self._set_state(user_id, 'admin_delete_wait_select', admin_mode=True, in_menu=True, tmp_data={'env_entries': env_entries}, event=event)
        self._schedule_timeout(user_id)
        yield event.plain_result(msg)

    async def _admin_delete_select_handle(self, event):
        user_id = self._get_user_id(event)
        state_info = self._get_state_info(user_id)
        if state_info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 操作已超时，已退出交互。")
            self._set_state(user_id, 'idle', admin_mode=False, in_menu=False)
            self._cancel_timeout(user_id)
            return
        if state_info['state'] != 'admin_delete_wait_select':
            return
        current_text = self._get_text(event)
        if state_info.get('trigger_msg') == current_text:
            return
        try:
            idx = int(current_text)
        except:
            yield event.plain_result("❌ 请输入有效的数字")
            return
        env_entries = state_info.get('tmp_data', {}).get('env_entries', [])
        if idx < 1 or idx > len(env_entries):
            yield event.plain_result(f"❌ 序号无效，请输入 1 到 {len(env_entries)} 之间的数字")
            return
        phone_to_del = env_entries[idx-1]["phone"]
        self._set_state(user_id, 'admin_delete_wait_confirm', admin_mode=True, in_menu=True, tmp_data={'phone_to_del': phone_to_del}, event=event)
        self._schedule_timeout(user_id)
        yield event.plain_result(f"⚠️ 确认删除该账号（{phone_to_del}）吗？回复 y 确认，n 取消，数字忽略。")

    async def _admin_do_delete(self, phone: str) -> str:
        deleted = False
        for qq, data in self.cache.items():
            accounts = data["accounts"]
            for idx, acc in enumerate(accounts):
                if acc["phone"] == phone:
                    del accounts[idx]
                    self._update_cache_user(qq, accounts)
                    deleted = True
                    break
        env_entries = await self._get_all_env_entries()
        env_entries = [e for e in env_entries if e["phone"] != phone]
        await self._save_all_env_entries(env_entries)
        if deleted:
            return f"✅ 已删除手机号 {phone}（从所有绑定和环境变量中移除）"
        else:
            return f"✅ 已从环境变量删除手机号 {phone}（未发现绑定记录）"

    # ---------- 修改授权次数子操作 ----------
    async def _admin_auth_select(self, event):
        user_id = self._get_user_id(event)
        state_info = self._get_state_info(user_id)
        if state_info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 操作已超时，已退出交互。")
            self._set_state(user_id, 'idle', admin_mode=False, in_menu=False)
            self._cancel_timeout(user_id)
            return
        if state_info['state'] != 'admin_auth_wait_select':
            return

        env_entries = await self._get_all_env_entries()
        if not env_entries:
            yield event.plain_result("❌ 环境变量中暂无账号")
            self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, event=event)
            self._schedule_timeout(user_id)
            menu = await self._get_admin_menu_text()
            yield event.plain_result(menu)
            return
        msg = "📋 所有环境变量账号（当前授权次数）：\n"
        for idx, entry in enumerate(env_entries, 1):
            auth_display = "无限制" if entry["auth_count"] is None else str(entry["auth_count"])
            msg += f"{idx}. {entry['phone']} ｜ 授权: {auth_display}\n"
        msg += "请输入要修改授权次数的账号序号（发送 q 取消）："
        self._set_state(user_id, 'admin_auth_wait_select', admin_mode=True, in_menu=True, tmp_data={'env_entries': env_entries}, event=event)
        self._schedule_timeout(user_id)
        yield event.plain_result(msg)

    async def _admin_auth_select_handle(self, event):
        user_id = self._get_user_id(event)
        state_info = self._get_state_info(user_id)
        if state_info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 操作已超时，已退出交互。")
            self._set_state(user_id, 'idle', admin_mode=False, in_menu=False)
            self._cancel_timeout(user_id)
            return
        if state_info['state'] != 'admin_auth_wait_select':
            return
        current_text = self._get_text(event)
        if state_info.get('trigger_msg') == current_text:
            return
        try:
            idx = int(current_text)
        except:
            yield event.plain_result("❌ 请输入有效的数字")
            return
        env_entries = state_info.get('tmp_data', {}).get('env_entries', [])
        if idx < 1 or idx > len(env_entries):
            yield event.plain_result(f"❌ 序号无效，请输入 1 到 {len(env_entries)} 之间的数字")
            return
        phone = env_entries[idx-1]["phone"]
        self._set_state(user_id, 'admin_auth_wait_new_value', admin_mode=True, in_menu=True, tmp_data={'phone': phone}, event=event)
        self._schedule_timeout(user_id)
        yield event.plain_result(f"已选择账号 {phone}，请输入新的授权次数（数字）或输入 '无限制'（发送 q 取消）：")

    # ---------- 提现审核子操作 ----------
    async def _admin_withdraw_select(self, event):
        user_id = self._get_user_id(event)
        state_info = self._get_state_info(user_id)
        if state_info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 操作已超时，已退出交互。")
            self._set_state(user_id, 'idle', admin_mode=False, in_menu=False)
            self._cancel_timeout(user_id)
            return
        if state_info['state'] != 'admin_withdraw_wait_select':
            return

        env_entries = await self._get_all_env_entries()
        if not env_entries:
            yield event.plain_result("❌ 环境变量中暂无账号")
            self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, event=event)
            self._schedule_timeout(user_id)
            menu = await self._get_admin_menu_text()
            yield event.plain_result(menu)
            return
        msg = "📋 所有环境变量账号（当前授权次数）：\n"
        for idx, entry in enumerate(env_entries, 1):
            auth_display = "无限制" if entry["auth_count"] is None else str(entry["auth_count"])
            msg += f"{idx}. {entry['phone']} ｜ 授权: {auth_display}\n"
        msg += "请输入要提现扣减的账号序号（发送 q 取消）："
        self._set_state(user_id, 'admin_withdraw_wait_select', admin_mode=True, in_menu=True, tmp_data={'env_entries': env_entries}, event=event)
        self._schedule_timeout(user_id)
        yield event.plain_result(msg)

    async def _admin_withdraw_select_handle(self, event):
        user_id = self._get_user_id(event)
        state_info = self._get_state_info(user_id)
        if state_info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 操作已超时，已退出交互。")
            self._set_state(user_id, 'idle', admin_mode=False, in_menu=False)
            self._cancel_timeout(user_id)
            return
        if state_info['state'] != 'admin_withdraw_wait_select':
            return
        current_text = self._get_text(event)
        if state_info.get('trigger_msg') == current_text:
            return
        try:
            idx = int(current_text)
        except:
            yield event.plain_result("❌ 请输入有效的数字")
            return
        env_entries = state_info.get('tmp_data', {}).get('env_entries', [])
        if idx < 1 or idx > len(env_entries):
            yield event.plain_result(f"❌ 序号无效，请输入 1 到 {len(env_entries)} 之间的数字")
            return
        phone = env_entries[idx-1]["phone"]
        for entry in env_entries:
            if entry["phone"] == phone:
                if entry["auth_count"] is None:
                    yield event.plain_result(f"❌ 账号 {phone} 为无限制，无法提现扣减")
                    self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, event=event)
                    self._schedule_timeout(user_id)
                    menu = await self._get_admin_menu_text()
                    yield event.plain_result(menu)
                    return
                break
        self._set_state(user_id, 'admin_withdraw_wait_amount', admin_mode=True, in_menu=True, tmp_data={'phone': phone}, event=event)
        self._schedule_timeout(user_id)
        yield event.plain_result(f"已选择账号 {phone}，请输入要提现扣减的数量（正整数，发送 q 取消）：")

    @filter.regex(r'^\d+$')
    async def handle_admin_withdraw_amount(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        if user_id not in self.admin_qqs:
            return
        state_info = self._get_state_info(user_id)
        if state_info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 操作已超时，已退出交互。")
            self._set_state(user_id, 'idle', admin_mode=False, in_menu=False)
            self._cancel_timeout(user_id)
            return
        if state_info['state'] != 'admin_withdraw_wait_amount' or not state_info.get('in_menu', False):
            return
        current_text = self._get_text(event)
        if state_info.get('trigger_msg') == current_text:
            return
        try:
            amount = int(current_text)
        except:
            yield event.plain_result("❌ 请输入有效的正整数")
            return
        if amount <= 0:
            yield event.plain_result("❌ 提现数量须为正整数")
            return
        phone = state_info.get('tmp_data', {}).get('phone')
        if not phone:
            yield event.plain_result("❌ 会话错误，请重新操作")
            self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, event=event)
            self._schedule_timeout(user_id)
            menu = await self._get_admin_menu_text()
            yield event.plain_result(menu)
            return
        result = await self._admin_do_withdraw(phone, amount)
        yield event.plain_result(result)
        self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, event=event)
        self._schedule_timeout(user_id)
        menu = await self._get_admin_menu_text()
        yield event.plain_result(menu)

    async def _admin_do_withdraw(self, phone: str, amount: int) -> str:
        env_entries = await self._get_all_env_entries()
        entry_found = None
        for entry in env_entries:
            if entry["phone"] == phone:
                entry_found = entry
                break
        if not entry_found:
            return f"❌ 手机号 {phone} 不存在于环境变量中"
        if entry_found["auth_count"] is None:
            return f"❌ 账号 {phone} 为无限制，无法提现"
        if entry_found["auth_count"] < amount:
            return f"❌ 授权次数不足！当前 {entry_found['auth_count']}，需扣减 {amount}"
        entry_found["auth_count"] -= amount
        await self._save_all_env_entries(env_entries)
        return f"✅ 提现成功！手机号 {phone} 减少 {amount} 次，剩余 {entry_found['auth_count']}"

    # ---------- 重置用户子操作 ----------
    async def _admin_reset_select(self, event):
        user_id = self._get_user_id(event)
        state_info = self._get_state_info(user_id)
        if state_info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 操作已超时，已退出交互。")
            self._set_state(user_id, 'idle', admin_mode=False, in_menu=False)
            self._cancel_timeout(user_id)
            return
        if state_info['state'] != 'admin_reset_wait_select':
            return

        qq_list = [qq for qq, data in self.cache.items() if data.get("accounts")]
        if not qq_list:
            yield event.plain_result("📭 暂无任何用户绑定数据")
            self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, event=event)
            self._schedule_timeout(user_id)
            menu = await self._get_admin_menu_text()
            yield event.plain_result(menu)
            return
        msg = "📋 有绑定记录的QQ列表：\n"
        for idx, qq in enumerate(qq_list, 1):
            acc_count = len(self.cache[qq].get("accounts", []))
            msg += f"{idx}. {qq} ｜ 账号数: {acc_count}\n"
        msg += "请输入要重置的QQ序号（发送 q 取消）："
        self._set_state(user_id, 'admin_reset_wait_select', admin_mode=True, in_menu=True, tmp_data={'qq_list': qq_list}, event=event)
        self._schedule_timeout(user_id)
        yield event.plain_result(msg)

    async def _admin_reset_select_handle(self, event):
        user_id = self._get_user_id(event)
        state_info = self._get_state_info(user_id)
        if state_info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 操作已超时，已退出交互。")
            self._set_state(user_id, 'idle', admin_mode=False, in_menu=False)
            self._cancel_timeout(user_id)
            return
        if state_info['state'] != 'admin_reset_wait_select':
            return
        current_text = self._get_text(event)
        if state_info.get('trigger_msg') == current_text:
            return
        try:
            idx = int(current_text)
        except:
            yield event.plain_result("❌ 请输入有效的数字")
            return
        qq_list = state_info.get('tmp_data', {}).get('qq_list', [])
        if idx < 1 or idx > len(qq_list):
            yield event.plain_result(f"❌ 序号无效，请输入 1 到 {len(qq_list)} 之间的数字")
            return
        target_qq = qq_list[idx-1]
        await self._reset_user_data(target_qq)
        yield event.plain_result(f"✅ 已重置用户 {target_qq} 的所有数据")
        self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, event=event)
        self._schedule_timeout(user_id)
        menu = await self._get_admin_menu_text()
        yield event.plain_result(menu)
