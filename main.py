import time
import aiohttp
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import logger

class KuwoManagerPlugin(Star):
    """酷我账号管理插件 - 与呆呆面板环境变量联动（kwtx）"""
    
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        if config is None:
            config = {}
        # 从 AstrBot 插件配置中读取呆呆面板参数
        self.base_url = config.get("base_url", "").strip()
        self.app_key = config.get("app_key", "").strip()
        self.app_secret = config.get("app_secret", "").strip()
        
        # 检查配置是否完整
        if not all([self.base_url, self.app_key, self.app_secret]):
            logger.warning("⚠️ 呆呆面板配置不完整，请检查 base_url、app_key、app_secret 是否已填写")
        else:
            logger.info(f"✅ 呆呆面板配置已加载，base_url: {self.base_url}")
        
        self.token = None
        self.token_expiry = 0
        self.env_name = "kwtx"  # 固定环境变量名
        
        # 充值次数暂存内存（如需持久化可扩展）
        self.user_counts = {}
        self.user_state = {}
        
        logger.info("✅ 酷我插件（呆呆面板联动版）已加载")

    # ---------- 呆呆面板 API（复用参考插件的实现） ----------
    async def _get_token(self):
        if self.token and self.token_expiry > time.time():
            return self.token

        if not self.base_url or not self.app_key or not self.app_secret:
            raise Exception("呆呆面板配置不完整，无法获取 Token")

        base = self.base_url.replace("/api/v1", "").replace("/api", "")
        token_url = f"{base}/api/open-api/token"
        payload = {"app_key": self.app_key, "app_secret": self.app_secret}
        
        async with aiohttp.ClientSession() as session:
            async with session.post(token_url, json=payload) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise Exception(f"获取 Token 失败：{resp.status}，{error_text}")
                result = await resp.json()
                token = result.get("data", {}).get("access_token")
                if not token:
                    raise Exception(f"响应中无 access_token：{result}")
                expires_in = result.get("data", {}).get("expires_in", 86400)
                self.token_expiry = time.time() + expires_in - 60
                self.token = token
                return token

    async def _call_api(self, endpoint: str, method: str = "POST", data: dict = None):
        token = await self._get_token()
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }
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
            return result.get("code") in [0, None, ""] and not result.get("error")
        else:
            payload = {"name": env_name, "value": new_value}
            result = await self._call_api(f"envs/{env_id}", method="PUT", data=payload)
            return result.get("code") in [0, None, ""] and not result.get("error")

    # ---------- 账号读写 ----------
    async def _get_accounts(self) -> dict:
        value = ""
        env_id = await self._get_env_id_by_name(self.env_name)
        if env_id:
            envs = await self._fetch_env_list()
            for env in envs:
                if env.get("id") == env_id:
                    value = env.get("value", "")
                    break
        if not value:
            return {}
        if '\n' in value:
            sep = '\n'
        elif '&' in value:
            sep = '&'
        else:
            if '#' in value:
                phone, pwd = value.split('#', 1)
                return {phone.strip(): pwd.strip()}
            return {}
        
        accounts = {}
        for item in value.split(sep):
            item = item.strip()
            if not item:
                continue
            if '#' in item:
                phone, pwd = item.split('#', 1)
                accounts[phone.strip()] = pwd.strip()
            else:
                logger.warning(f"忽略格式错误项: {item}")
        return accounts

    async def _save_accounts(self, accounts: dict) -> bool:
        if not accounts:
            new_value = ""
        else:
            items = [f"{phone}#{pwd}" for phone, pwd in accounts.items()]
            new_value = '&'.join(items)
        return await self._update_env_value(self.env_name, new_value)

    # ---------- 辅助：获取用户ID和文本 ----------
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

    # ---------- 菜单 ----------
    async def _get_menu_text(self, user_id: str) -> str:
        try:
            accounts = await self._get_accounts()
            count = len(accounts)
        except Exception as e:
            logger.error(f"获取账号失败: {e}")
            count = 0
        times = self.user_counts.get(user_id, 0)
        return (
            f"=====酷我=====\n"
            f"账号{count}个，可用次数{times}\n"
            "[1] 提交账号\n"
            "[2] 充值次数\n"
            "[3] 删除账号\n"
            "[4] 账号提现\n"
            "[q] 退出"
        )

    # ---------- 命令 ----------
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
            try:
                accounts = await self._get_accounts()
                if not accounts:
                    yield event.plain_result("❌ 当前没有账号")
                else:
                    phone_list = list(accounts.keys())
                    yield event.plain_result(f"当前账号：{', '.join(phone_list)}\n请输入要删除的手机号：")
                    self.user_state[user_id] = 'waiting_delete'
            except Exception as e:
                logger.error(f"获取账号列表失败: {e}")
                yield event.plain_result("❌ 获取账号列表失败，请检查呆呆面板配置")
        elif text == '4':
            self.user_state[user_id] = 'waiting_withdraw'
            yield event.plain_result("请输入要提现的次数（数字）")
        elif text == 'q':
            yield event.plain_result("👋 已退出菜单")
            self.user_state[user_id] = 'idle'
        else:
            yield event.plain_result("无效选项")

    @filter.regex(r'^\d{11}#.+$')
    async def handle_phone_submit(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        if self.user_state.get(user_id) != 'waiting_phone':
            return
        
        text = self._get_text(event)
        phone, password = text.split('#', 1)
        try:
            accounts = await self._get_accounts()
            accounts[phone] = password
            if await self._save_accounts(accounts):
                yield event.plain_result(f"✅ 账号 {phone} 已保存")
            else:
                yield event.plain_result("❌ 保存到环境变量失败")
        except Exception as e:
            logger.error(f"提交账号失败: {e}")
            yield event.plain_result("❌ 操作失败，请检查呆呆面板配置")
        
        self.user_state[user_id] = 'idle'
        menu = await self._get_menu_text(user_id)
        yield event.plain_result(menu)

    @filter.regex(r'^\d{11}$')
    async def handle_delete_phone(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        if self.user_state.get(user_id) != 'waiting_delete':
            return
        
        phone = self._get_text(event)
        try:
            accounts = await self._get_accounts()
            if phone in accounts:
                del accounts[phone]
                if await self._save_accounts(accounts):
                    yield event.plain_result(f"✅ 已删除账号 {phone}")
                else:
                    yield event.plain_result("❌ 删除失败")
            else:
                yield event.plain_result(f"❌ 未找到手机号 {phone}")
        except Exception as e:
            logger.error(f"删除账号失败: {e}")
            yield event.plain_result("❌ 操作失败，请检查呆呆面板配置")
        
        self.user_state[user_id] = 'idle'
        menu = await self._get_menu_text(user_id)
        yield event.plain_result(menu)

    @filter.regex(r'^\d+$')
    async def handle_recharge(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        if self.user_state.get(user_id) != 'waiting_recharge':
            return
        
        try:
            count = int(self._get_text(event))
        except ValueError:
            yield event.plain_result("❌ 请输入有效数字")
            return
        if count <= 0:
            yield event.plain_result("❌ 次数必须为正整数")
            return
        
        self.user_counts[user_id] = self.user_counts.get(user_id, 0) + count
        yield event.plain_result(f"✅ 成功充值 {count} 次，当前可用次数：{self.user_counts[user_id]}")
        self.user_state[user_id] = 'idle'
        menu = await self._get_menu_text(user_id)
        yield event.plain_result(menu)

    @filter.regex(r'^\d+$')
    async def handle_withdraw(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        if self.user_state.get(user_id) != 'waiting_withdraw':
            return
        
        try:
            count = int(self._get_text(event))
        except ValueError:
            yield event.plain_result("❌ 请输入有效数字")
            return
        if count <= 0:
            yield event.plain_result("❌ 次数必须为正整数")
            return
        
        current = self.user_counts.get(user_id, 0)
        if current < count:
            yield event.plain_result(f"❌ 可用次数不足！当前可用：{current}")
        else:
            self.user_counts[user_id] = current - count
            yield event.plain_result(f"✅ 成功提现 {count} 次，剩余次数：{self.user_counts[user_id]}")
        
        self.user_state[user_id] = 'idle'
        menu = await self._get_menu_text(user_id)
        yield event.plain_result(menu)
