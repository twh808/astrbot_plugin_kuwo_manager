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
    """酷我账号管理 - 超时主动发送（session_id报错修复版）"""
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
        logger.info("✅ 酷我插件（超时主动发送最终版）已加载")
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
            return str(event.get_session_id())
        return "unknown"
    # ----- 【修复】获取 session 字符串（框架可识别）优先原生session_id -----
    def _get_session_str(self, event: AstrMessageEvent) -> str:
        """返回可用的 session 字符串，优先框架原生三段式session_id"""
        if hasattr(event, 'session_id'):
            sid = event.session_id
            if isinstance(sid, str) and sid:
                return sid
        if hasattr(event, 'get_session_id'):
            try:
                sid = event.get_session_id()
                if sid and isinstance(sid, str):
                    return sid
            except Exception:
                pass
        # 兜底，仅实在拿不到原生会话才构造标准onebot会话
        user_id = self._get_user_id(event)
        return f"onebot:private:{user_id}"

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
                'session_id': None,      # 存储字符串形式的 session
            }
        return self.state_info[user_id]
    def _set_state(self, user_id: str, state: str, admin_mode: bool = False,
                   tmp_data: dict = None, trigger_msg: str = None,
                   in_menu: bool = False, session_id: str = None):
        old = self.state_info.get(user_id, {})
        self.state_info[user_id] = {
            'state': state,
            'last_active': time.time(),
            'admin_mode': admin_mode,
            'tmp_data': tmp_data or {},
            'trigger_msg': trigger_msg,
            'in_menu': in_menu,
            'timeout_triggered': False,
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
    # ---------- 【修复】超时任务管理 ----------
    async def _timeout_callback(self, user_id: str):
        info = self._get_state_info(user_id)
        if info['in_menu'] or info['state'] != 'idle':
            sid = info.get('session_id')
            sent = False
            # 优先使用保存好的session
            if sid:
                try:
                    await self.context.send_message(sid, "⏰ 操作已超时，已退出交互。")
                    logger.info(f"✅ 已通过 session_id 字符串 '{sid}' 发送超时提醒")
                    sent = True
                except Exception as e:
                    logger.warning(f"使用 session_id '{sid}' 发送失败: {e}")
            # 兜底强制构造标准 onebot 三段会话，解决纯数字QQ报错split问题
            if not sent:
                candidate = f"onebot:private:{user_id}"
                try:
                    await self.context.send_message(candidate, "⏰ 操作已超时，已退出交互。")
                    logger.info(f"✅ 兜底构造会话 {candidate} 发送超时提醒成功")
                    sent = True
                except Exception as e:
                    logger.warning(f"兜底会话{candidate}发送失败: {e}")
            if not sent:
                logger.error(f"❌ 所有 session_id 格式均失败，无法发送超时提醒 (user_id={user_id})")
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
                session_id = self._get_session_str(event)
                self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, session_id=session_id)
                self._schedule_timeout(user_id)
                menu = await self._get_admin_menu_text()
                yield event.plain_result(menu)
            else:
                yield event.plain_result("👋 已取消操作，返回菜单")
                session_id = self._get_session_str(event)
                self._set_state(user_id, 'menu_idle', admin_mode=False, in_menu=True, session_id=session_id)
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
        session_id = self._get_session_str(event)
        self._set_state(user_id, 'menu_idle', admin_mode=False, in_menu=True, session_id=session_id)
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
            session_id = self._get_session_str(event)
            self._set_state(user_id, 'waiting_phone', admin_mode=False, in_menu=True, session_id=session_id)
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
                session_id = self._get_session_str(event)
                self._set_state(user_id, 'waiting_delete', admin_mode=False, trigger_msg=text, in_menu=True, session_id=session_id)
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
            session_id = self._get_session_str(event)
            self._set_state(user_id, 'menu_idle', admin_mode=False, in_menu=True, session_id=session_id)
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
                session_id = self._get_session_str(event)
                self._set_state(user_id, 'waiting_code_phone', admin_mode=False, trigger_msg=text, in_menu=True, session_id=session_id)
                self._schedule_timeout(user_id)
        elif text == 'r':
            await self._reset_user_data(user_id)
            yield event.plain_result("✅ 您的所有数据已重置")
            session_id = self._get_session_str(event)
            self._set_state(user_id, 'menu_idle', admin_mode=False, in_menu=True, session_id=session_id)
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
            session_id = self._get_session_str(event)
            self._set_state(user_id, 'menu_idle', admin_mode=False, in_menu=True, session_id=session_id)
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
        session_id = self._get_session_str(event)
        self._set_state(user_id, 'menu_idle', admin_mode=False, in_menu=True, session_id=session_id)
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
            yield event.plain_result(f"❌ 序号无效
