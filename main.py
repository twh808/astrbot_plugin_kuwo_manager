import json
import os
import time
import aiohttp
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import logger

class KuwoManagerPlugin(Star):
    """酷我账号管理 - 修复命令与数字冲突"""

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

        self.data_dir = os.path.join(os.path.dirname(__file__), "data")
        self.cache_file = os.path.join(self.data_dir, "user_data.json")
        os.makedirs(self.data_dir, exist_ok=True)
        self.cache = self._load_cache()

        self.state_info = {}   # user_id: {'state':, 'last_active':, 'trigger_msg':}
        self.TIMEOUT = 120

        logger.info("✅ 酷我插件（修复命令冲突）已加载")

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
            self.cache[user_id] = {"accounts": [], "count": 0}
            self._save_cache()
        return self.cache[user_id]

    def _update_cache_user(self, user_id: str, accounts: list, count: int = None):
        if user_id not in self.cache:
            self.cache[user_id] = {"accounts": accounts, "count": count if count is not None else 0}
        else:
            self.cache[user_id]["accounts"] = accounts
            if count is not None:
                self.cache[user_id]["count"] = count
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

    # ---------- 环境变量读写（无QQ） ----------
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
                auth_count = int(parts[2].strip()) if len(parts) >= 3 else 0
                entries.append({"phone": phone, "password": password, "auth_count": auth_count})
        return entries

    async def _save_all_env_entries(self, entries: list) -> bool:
        if not entries:
            new_value = ""
        else:
            lines = [f"{e['phone']}#{e['password']}#{e['auth_count']}" for e in entries]
            new_value = '\n'.join(lines)
        return await self._update_env_value(self.env_name, new_value)

    # ---------- 当前用户账号 ----------
    async def _get_my_accounts(self, user_id: str) -> list:
        return self._get_cache_user(user_id)["accounts"]

    def _is_phone_owned_by_other(self, user_id: str, phone: str) -> bool:
        for qq, data in self.cache.items():
            if qq == user_id:
                continue
            for acc in data["accounts"]:
                if acc["phone"] == phone:
                    return True
        return False

    async def _sync_auth_counts_for_user(self, user_id: str, new_count: int):
        cache_user = self._get_cache_user(user_id)
        phones = [acc["phone"] for acc in cache_user["accounts"]]
        if not phones:
            return
        env_entries = await self._get_all_env_entries()
        updated = False
        for entry in env_entries:
            if entry["phone"] in phones:
                entry["auth_count"] = new_count
                updated = True
        if updated:
            await self._save_all_env_entries(env_entries)

    async def _reset_user_data(self, user_id: str) -> bool:
        cache_user = self._get_cache_user(user_id)
        phones = [acc["phone"] for acc in cache_user["accounts"]]
        self.cache[user_id] = {"accounts": [], "count": 0}
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
            self.state_info[user_id] = {'state': 'idle', 'last_active': now, 'trigger_msg': None}
        info = self.state_info[user_id]
        if info['state'] != 'idle' and (now - info['last_active']) > self.TIMEOUT:
            info['state'] = 'idle'
            info['trigger_msg'] = None
        return info

    def _set_state(self, user_id: str, state: str, trigger_msg: str = None):
        self.state_info[user_id] = {
            'state': state,
            'last_active': time.time(),
            'trigger_msg': trigger_msg
        }

    # ---------- 菜单 ----------
    async def _get_menu_text(self, user_id: str) -> str:
        my_acc = await self._get_my_accounts(user_id)
        count = len(my_acc)
        cache_user = self._get_cache_user(user_id)
        times = cache_user.get("count", 0)
        return (
            f"=====酷我=====\n"
            f"账号{count}个，可用次数{times}\n"
            "[1] 提交账号\n"
            "[2] 充值次数\n"
            "[3] 删除账号\n"
            "[4] 账号提现\n"
            "[r] 重置我的所有数据\n"
            "[q] 退出"
        )

    # ---------- 命令 ----------
    @filter.command("酷我")
    async def kuwo_menu(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        self._set_state(user_id, 'idle')
        menu = await self._get_menu_text(user_id)
        yield event.plain_result(menu)

    @filter.regex(r'^[1-4rRqQ]$')
    async def handle_menu_choice(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        text = self._get_text(event).lower()
        state_info = self._get_state_info(user_id)
        if state_info['state'] != 'idle':
            yield event.plain_result("⚠️ 请先完成当前操作，或等待超时重置。")
            return

        if text == '1':
            self._set_state(user_id, 'waiting_phone', text)
            yield event.plain_result("请输入手机号#密码（例如：13800138000#mypassword）")
        elif text == '2':
            self._set_state(user_id, 'waiting_recharge', text)
            yield event.plain_result("请输入要充值的次数（数字）")
        elif text == '3':
            my_acc = await self._get_my_accounts(user_id)
            if not my_acc:
                yield event.plain_result("❌ 您没有绑定任何账号")
            else:
                lines = [f"{idx+1}. {acc['phone']}" for idx, acc in enumerate(my_acc)]
                prompt = "您的账号：\n" + "\n".join(lines) + "\n请输入要删除的序号（如 1）："
                yield event.plain_result(prompt)
                self._set_state(user_id, 'waiting_delete', text)
        elif text == '4':
            self._set_state(user_id, 'waiting_withdraw', text)
            yield event.plain_result("请输入要提现的次数（数字）")
        elif text == 'r':
            await self._reset_user_data(user_id)
            yield event.plain_result("✅ 您的所有数据已重置")
            menu = await self._get_menu_text(user_id)
            yield event.plain_result(menu)
        elif text == 'q':
            yield event.plain_result("👋 已退出菜单")
            self._set_state(user_id, 'idle')

    # ---------- 提交账号 ----------
    @filter.regex(r'^\d{11}#.+$')
    async def handle_phone_submit(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        state_info = self._get_state_info(user_id)
        if state_info['state'] != 'waiting_phone':
            return

        text = self._get_text(event)
        phone, password = text.split('#', 1)
        phone = phone.strip()
        password = password.strip()

        if self._is_phone_owned_by_other(user_id, phone):
            yield event.plain_result(f"❌ 手机号 {phone} 已被其他用户绑定")
            self._set_state(user_id, 'idle')
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
            self._update_cache_user(user_id, my_acc, cache_user["count"])
            env_entries = await self._get_all_env_entries()
            for entry in env_entries:
                if entry["phone"] == phone:
                    entry["password"] = password
                    break
            await self._save_all_env_entries(env_entries)
            yield event.plain_result(f"✅ 账号 {phone} 密码已更新")
        else:
            my_acc.append({"phone": phone, "password": password})
            self._update_cache_user(user_id, my_acc, cache_user["count"])
            env_entries = await self._get_all_env_entries()
            env_entries.append({"phone": phone, "password": password, "auth_count": 0})
            await self._save_all_env_entries(env_entries)
            yield event.plain_result(f"✅ 账号 {phone} 已保存")

        self._set_state(user_id, 'idle')
        menu = await self._get_menu_text(user_id)
        yield event.plain_result(menu)

    # ---------- 删除账号 ----------
    @filter.regex(r'^\d+$')
    async def handle_delete_index(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        state_info = self._get_state_info(user_id)
        if state_info['state'] != 'waiting_delete':
            return
        # 忽略触发命令本身
        current_text = self._get_text(event)
        if state_info.get('trigger_msg') == current_text:
            logger.debug(f"忽略触发消息: {current_text}")
            return

        try:
            index = int(current_text)
        except ValueError:
            yield event.plain_result("❌ 请输入有效的数字")
            self._set_state(user_id, 'idle')
            menu = await self._get_menu_text(user_id)
            yield event.plain_result(menu)
            return

        cache_user = self._get_cache_user(user_id)
        my_acc = cache_user["accounts"]
        if index < 1 or index > len(my_acc):
            yield event.plain_result(f"❌ 序号无效，请输入 1 到 {len(my_acc)} 之间的数字")
            self._set_state(user_id, 'idle')
            menu = await self._get_menu_text(user_id)
            yield event.plain_result(menu)
            return

        phone_to_del = my_acc[index-1]["phone"]
        del my_acc[index-1]
        self._update_cache_user(user_id, my_acc, cache_user["count"])
        env_entries = await self._get_all_env_entries()
        env_entries = [e for e in env_entries if e["phone"] != phone_to_del]
        await self._save_all_env_entries(env_entries)

        yield event.plain_result(f"✅ 已删除账号 {phone_to_del}")
        self._set_state(user_id, 'idle')
        menu = await self._get_menu_text(user_id)
        yield event.plain_result(menu)

    # ---------- 充值 ----------
    @filter.regex(r'^\d+$')
    async def handle_recharge(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        state_info = self._get_state_info(user_id)
        if state_info['state'] != 'waiting_recharge':
            return
        current_text = self._get_text(event)
        if state_info.get('trigger_msg') == current_text:
            return

        try:
            count = int(current_text)
        except:
            yield event.plain_result("❌ 请输入有效数字")
            self._set_state(user_id, 'idle')
            menu = await self._get_menu_text(user_id)
            yield event.plain_result(menu)
            return
        if count <= 0:
            yield event.plain_result("❌ 次数必须为正整数")
            self._set_state(user_id, 'idle')
            menu = await self._get_menu_text(user_id)
            yield event.plain_result(menu)
            return

        cache_user = self._get_cache_user(user_id)
        new_total = cache_user["count"] + count
        cache_user["count"] = new_total
        self._save_cache()
        await self._sync_auth_counts_for_user(user_id, new_total)
        yield event.plain_result(f"✅ 充值 {count} 次，当前可用：{new_total}")
        self._set_state(user_id, 'idle')
        menu = await self._get_menu_text(user_id)
        yield event.plain_result(menu)

    # ---------- 提现 ----------
    @filter.regex(r'^\d+$')
    async def handle_withdraw(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        state_info = self._get_state_info(user_id)
        if state_info['state'] != 'waiting_withdraw':
            return
        current_text = self._get_text(event)
        if state_info.get('trigger_msg') == current_text:
            return

        try:
            count = int(current_text)
        except:
            yield event.plain_result("❌ 请输入有效数字")
            self._set_state(user_id, 'idle')
            menu = await self._get_menu_text(user_id)
            yield event.plain_result(menu)
            return
        if count <= 0:
            yield event.plain_result("❌ 次数必须为正整数")
            self._set_state(user_id, 'idle')
            menu = await self._get_menu_text(user_id)
            yield event.plain_result(menu)
            return

        cache_user = self._get_cache_user(user_id)
        if cache_user["count"] < count:
            yield event.plain_result(f"❌ 可用次数不足！当前可用：{cache_user['count']}")
        else:
            new_total = cache_user["count"] - count
            cache_user["count"] = new_total
            self._save_cache()
            await self._sync_auth_counts_for_user(user_id, new_total)
            yield event.plain_result(f"✅ 提现 {count} 次，剩余：{new_total}")
        self._set_state(user_id, 'idle')
        menu = await self._get_menu_text(user_id)
        yield event.plain_result(menu)
