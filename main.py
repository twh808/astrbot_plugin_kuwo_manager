import json
import os
import time
import aiohttp
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import logger

class KuwoManagerPlugin(Star):
    """酷我账号管理 - 环境变量为主存储，本地文件为缓存，删除时按序号"""

    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        if config is None:
            config = {}
        # 呆呆面板配置
        self.base_url = config.get("base_url", "").strip()
        self.app_key = config.get("app_key", "").strip()
        self.app_secret = config.get("app_secret", "").strip()
        self.token = None
        self.token_expiry = 0
        self.env_name = "kwtx"

        # 本地缓存文件
        self.data_dir = os.path.join(os.path.dirname(__file__), "data")
        self.cache_file = os.path.join(self.data_dir, "user_data.json")
        os.makedirs(self.data_dir, exist_ok=True)
        self.cache = self._load_cache()

        # 用户交互状态
        self.user_state = {}   # idle, waiting_phone, waiting_recharge, waiting_withdraw, waiting_delete

        logger.info("✅ 酷我插件（删除按序号）已加载")

    # ---------- 缓存读写 ----------
    def _load_cache(self) -> dict:
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"加载缓存失败: {e}")
                return {}
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

    # ---------- 环境变量账号读写（主存储） ----------
    async def _get_all_accounts_from_env(self) -> list:
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
        accounts = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            parts = line.split('#')
            if len(parts) >= 2:
                phone = parts[0].strip()
                password = parts[1].strip()
                owner = parts[2].strip() if len(parts) >= 3 else ""
                accounts.append({"phone": phone, "password": password, "owner": owner})
        return accounts

    async def _save_all_accounts_to_env(self, accounts: list) -> bool:
        if not accounts:
            new_value = ""
        else:
            lines = []
            for acc in accounts:
                owner_part = f"#{acc['owner']}" if acc.get('owner') else ""
                lines.append(f"{acc['phone']}#{acc['password']}{owner_part}")
            new_value = '\n'.join(lines)
        return await self._update_env_value(self.env_name, new_value)

    # ---------- 获取当前用户的账号（缓存优先） ----------
    async def _get_my_accounts(self, user_id: str) -> list:
        cache_user = self._get_cache_user(user_id)
        if cache_user["accounts"]:
            return cache_user["accounts"]
        all_acc = await self._get_all_accounts_from_env()
        my_acc = [acc for acc in all_acc if acc.get('owner') == user_id]
        self._update_cache_user(user_id, my_acc, cache_user["count"])
        return my_acc

    # ---------- 更新账号（提交/删除） ----------
    async def _update_my_accounts(self, user_id: str, new_my_accounts: list, count: int = None):
        all_acc = await self._get_all_accounts_from_env()
        all_acc = [acc for acc in all_acc if acc.get('owner') != user_id]
        all_acc.extend(new_my_accounts)
        if await self._save_all_accounts_to_env(all_acc):
            self._update_cache_user(user_id, new_my_accounts, count)
            return True
        return False

    # ---------- 辅助：获取用户ID和消息文本 ----------
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

    # ---------- 菜单生成 ----------
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
            "[q] 退出"
        )

    # ---------- 命令处理 ----------
    @filter.command("酷我")
    async def kuwo_menu(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        self.user_state[user_id] = 'idle'
        menu = await self._get_menu_text(user_id)
        yield event.plain_result(menu)

    @filter.regex(r'^[1-4qQ]$')
    async def handle_menu_choice(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        text = self._get_text(event).lower()
        state = self.user_state.get(user_id, 'idle')
        if state != 'idle':
            return

        if text == '1':
            self.user_state[user_id] = 'waiting_phone'
            yield event.plain_result("请输入手机号#密码（例如：13800138000#mypassword）")
        elif text == '2':
            self.user_state[user_id] = 'waiting_recharge'
            yield event.plain_result("请输入要充值的次数（数字）")
        elif text == '3':
            my_acc = await self._get_my_accounts(user_id)
            if not my_acc:
                yield event.plain_result("❌ 您没有绑定任何账号")
            else:
                # 生成带编号的列表
                lines = [f"{idx+1}. {acc['phone']}" for idx, acc in enumerate(my_acc)]
                prompt = "您的账号：\n" + "\n".join(lines) + "\n请输入要删除的序号（如 1）："
                yield event.plain_result(prompt)
                self.user_state[user_id] = 'waiting_delete'
        elif text == '4':
            self.user_state[user_id] = 'waiting_withdraw'
            yield event.plain_result("请输入要提现的次数（数字）")
        elif text == 'q':
            yield event.plain_result("👋 已退出菜单")
            self.user_state[user_id] = 'idle'
        else:
            yield event.plain_result("无效选项")

    # ---------- 提交账号 ----------
    @filter.regex(r'^\d{11}#.+$')
    async def handle_phone_submit(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        if self.user_state.get(user_id) != 'waiting_phone':
            return

        text = self._get_text(event)
        phone, password = text.split('#', 1)
        phone = phone.strip()
        password = password.strip()

        all_acc = await self._get_all_accounts_from_env()
        my_acc = [acc for acc in all_acc if acc.get('owner') == user_id]
        found = None
        for acc in my_acc:
            if acc["phone"] == phone:
                found = acc
                break
        if found:
            found["password"] = password
            if await self._update_my_accounts(user_id, my_acc):
                yield event.plain_result(f"✅ 账号 {phone} 密码已更新")
            else:
                yield event.plain_result("❌ 更新失败")
        else:
            my_acc.append({"phone": phone, "password": password, "owner": user_id})
            if await self._update_my_accounts(user_id, my_acc):
                yield event.plain_result(f"✅ 账号 {phone} 已保存")
            else:
                yield event.plain_result("❌ 保存失败")

        self.user_state[user_id] = 'idle'
        menu = await self._get_menu_text(user_id)
        yield event.plain_result(menu)

    # ---------- 删除账号（按序号） ----------
    @filter.regex(r'^\d+$')
    async def handle_delete_index(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        if self.user_state.get(user_id) != 'waiting_delete':
            return

        try:
            index = int(self._get_text(event))
        except ValueError:
            yield event.plain_result("❌ 请输入有效的数字")
            self.user_state[user_id] = 'idle'
            menu = await self._get_menu_text(user_id)
            yield event.plain_result(menu)
            return

        my_acc = await self._get_my_accounts(user_id)
        if index < 1 or index > len(my_acc):
            yield event.plain_result(f"❌ 序号无效，请输入 1 到 {len(my_acc)} 之间的数字")
            self.user_state[user_id] = 'idle'
            menu = await self._get_menu_text(user_id)
            yield event.plain_result(menu)
            return

        # 删除对应账号
        removed = my_acc.pop(index - 1)
        if await self._update_my_accounts(user_id, my_acc):
            yield event.plain_result(f"✅ 已删除账号 {removed['phone']}")
        else:
            yield event.plain_result("❌ 删除失败")

        self.user_state[user_id] = 'idle'
        menu = await self._get_menu_text(user_id)
        yield event.plain_result(menu)

    # ---------- 充值 ----------
    @filter.regex(r'^\d+$')
    async def handle_recharge(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        if self.user_state.get(user_id) != 'waiting_recharge':
            return

        try:
            count = int(self._get_text(event))
        except:
            yield event.plain_result("❌ 请输入有效数字")
            return
        if count <= 0:
            yield event.plain_result("❌ 次数必须为正整数")
            return

        cache_user = self._get_cache_user(user_id)
        cache_user["count"] += count
        self._save_cache()
        yield event.plain_result(f"✅ 充值 {count} 次，当前可用：{cache_user['count']}")
        self.user_state[user_id] = 'idle'
        menu = await self._get_menu_text(user_id)
        yield event.plain_result(menu)

    # ---------- 提现 ----------
    @filter.regex(r'^\d+$')
    async def handle_withdraw(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        if self.user_state.get(user_id) != 'waiting_withdraw':
            return

        try:
            count = int(self._get_text(event))
        except:
            yield event.plain_result("❌ 请输入有效数字")
            return
        if count <= 0:
            yield event.plain_result("❌ 次数必须为正整数")
            return

        cache_user = self._get_cache_user(user_id)
        if cache_user["count"] < count:
            yield event.plain_result(f"❌ 可用次数不足！当前可用：{cache_user['count']}")
        else:
            cache_user["count"] -= count
            self._save_cache()
            yield event.plain_result(f"✅ 提现 {count} 次，剩余：{cache_user['count']}")

        self.user_state[user_id] = 'idle'
        menu = await self._get_menu_text(user_id)
        yield event.plain_result(menu)
