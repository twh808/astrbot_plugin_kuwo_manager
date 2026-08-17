import json
import os
import time
import aiohttp
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import logger

class KuwoManagerPlugin(Star):
    """酷我账号管理 - 本地文件存储绑定信息，同时同步到环境变量kwtx"""

    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        if config is None:
            config = {}
        # 呆呆面板配置（用于操作环境变量）
        self.base_url = config.get("base_url", "").strip()
        self.app_key = config.get("app_key", "").strip()
        self.app_secret = config.get("app_secret", "").strip()
        self.token = None
        self.token_expiry = 0
        self.env_name = "kwtx"

        # 本地文件存储
        self.data_dir = os.path.join(os.path.dirname(__file__), "data")
        self.data_file = os.path.join(self.data_dir, "user_data.json")
        os.makedirs(self.data_dir, exist_ok=True)
        self.user_data = self._load_data()

        # 用户交互状态
        self.user_state = {}   # {user_id: 'idle'|...}
        logger.info("✅ 酷我插件（本地+环境变量双重存储）已加载")

    # ---------- 本地文件操作 ----------
    def _load_data(self) -> dict:
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"加载数据失败: {e}")
                return {}
        return {}

    def _save_data(self):
        try:
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(self.user_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存数据失败: {e}")

    def _get_user_record(self, user_id: str) -> dict:
        if user_id not in self.user_data:
            self.user_data[user_id] = {"accounts": [], "count": 0}
            self._save_data()
        return self.user_data[user_id]

    def _save_user_record(self, user_id: str, record: dict):
        self.user_data[user_id] = record
        self._save_data()

    # ---------- 环境变量操作（呆呆面板API） ----------
    async def _get_token(self):
        if self.token and self.token_expiry > time.time():
            return self.token
        if not all([self.base_url, self.app_key, self.app_secret]):
            raise Exception("呆呆面板配置不完整，无法操作环境变量")
        base = self.base_url.replace("/api/v1", "").replace("/api", "")
        token_url = f"{base}/api/open-api/token"
        payload = {"app_key": self.app_key, "app_secret": self.app_secret}
        async with aiohttp.ClientSession() as session:
            async with session.post(token_url, json=payload) as resp:
                if resp.status != 200:
                    raise Exception(f"获取Token失败: {resp.status}")
                result = await resp.json()
                token = result.get("data", {}).get("access_token")
                if not token:
                    raise Exception("响应中无access_token")
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

    async def _get_env_accounts_dict(self) -> dict:
        """从环境变量解析全局账号字典 {phone: password}"""
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
        # 解析
        accounts = {}
        if '\n' in value:
            sep = '\n'
        elif '&' in value:
            sep = '&'
        else:
            if '#' in value:
                phone, pwd = value.split('#', 1)
                accounts[phone.strip()] = pwd.strip()
            return accounts
        for item in value.split(sep):
            item = item.strip()
            if not item or '#' not in item:
                continue
            phone, pwd = item.split('#', 1)
            accounts[phone.strip()] = pwd.strip()
        return accounts

    async def _set_env_accounts(self, accounts_dict: dict) -> bool:
        """将全局账号字典写入环境变量"""
        if not accounts_dict:
            new_value = ""
        else:
            items = [f"{phone}#{pwd}" for phone, pwd in accounts_dict.items()]
            new_value = '&'.join(items)
        return await self._update_env_value(self.env_name, new_value)

    # ---------- 辅助：用户ID和文本 ----------
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
    def _get_menu_text(self, user_id: str) -> str:
        record = self._get_user_record(user_id)
        count = len(record["accounts"])
        times = record["count"]
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
        yield event.plain_result(self._get_menu_text(user_id))

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
            record = self._get_user_record(user_id)
            if not record["accounts"]:
                yield event.plain_result("❌ 您没有绑定任何账号")
            else:
                phones = [acc["phone"] for acc in record["accounts"]]
                yield event.plain_result(f"您的账号：{', '.join(phones)}\n请输入要删除的手机号：")
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

        # 1. 更新环境变量（全局账号表）
        try:
            env_accounts = await self._get_env_accounts_dict()
            env_accounts[phone] = password  # 更新或新增
            if not await self._set_env_accounts(env_accounts):
                yield event.plain_result("❌ 更新环境变量失败")
                return
        except Exception as e:
            logger.error(f"更新环境变量失败: {e}")
            yield event.plain_result("❌ 更新环境变量异常，请检查呆呆面板配置")
            return

        # 2. 更新本地文件（当前用户的账号列表）
        record = self._get_user_record(user_id)
        # 检查是否已存在
        for acc in record["accounts"]:
            if acc["phone"] == phone:
                acc["password"] = password
                self._save_user_record(user_id, record)
                yield event.plain_result(f"✅ 账号 {phone} 密码已更新")
                self.user_state[user_id] = 'idle'
                yield event.plain_result(self._get_menu_text(user_id))
                return
        # 新增
        record["accounts"].append({"phone": phone, "password": password})
        self._save_user_record(user_id, record)
        yield event.plain_result(f"✅ 账号 {phone} 已保存")
        self.user_state[user_id] = 'idle'
        yield event.plain_result(self._get_menu_text(user_id))

    # ---------- 删除账号 ----------
    @filter.regex(r'^\d{11}$')
    async def handle_delete_phone(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        if self.user_state.get(user_id) != 'waiting_delete':
            return

        phone = self._get_text(event)
        record = self._get_user_record(user_id)

        # 检查该手机号是否属于当前用户
        found = False
        for idx, acc in enumerate(record["accounts"]):
            if acc["phone"] == phone:
                found = True
                # 从本地文件中删除
                del record["accounts"][idx]
                self._save_user_record(user_id, record)
                break
        if not found:
            yield event.plain_result(f"❌ 未找到您绑定的手机号 {phone}")
            self.user_state[user_id] = 'idle'
            yield event.plain_result(self._get_menu_text(user_id))
            return

        # 检查该手机号是否还被其他用户绑定
        other_uses = False
        for uid, data in self.user_data.items():
            if uid == user_id:
                continue
            for acc in data.get("accounts", []):
                if acc["phone"] == phone:
                    other_uses = True
                    break
            if other_uses:
                break

        if not other_uses:
            # 从环境变量中删除该手机号
            try:
                env_accounts = await self._get_env_accounts_dict()
                if phone in env_accounts:
                    del env_accounts[phone]
                    if not await self._set_env_accounts(env_accounts):
                        yield event.plain_result("⚠️ 环境变量删除失败，但本地已删除")
                    else:
                        yield event.plain_result(f"✅ 已删除账号 {phone}（全局环境变量已同步）")
                else:
                    yield event.plain_result(f"✅ 已删除账号 {phone}（环境变量中未找到，忽略）")
            except Exception as e:
                logger.error(f"删除环境变量失败: {e}")
                yield event.plain_result(f"✅ 本地已删除，但环境变量删除失败: {e}")
        else:
            yield event.plain_result(f"✅ 已删除账号 {phone}（该手机号仍被其他用户使用，环境变量保留）")

        self.user_state[user_id] = 'idle'
        yield event.plain_result(self._get_menu_text(user_id))

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

        record = self._get_user_record(user_id)
        record["count"] += count
        self._save_user_record(user_id, record)
        yield event.plain_result(f"✅ 充值 {count} 次，当前可用：{record['count']}")
        self.user_state[user_id] = 'idle'
        yield event.plain_result(self._get_menu_text(user_id))

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

        record = self._get_user_record(user_id)
        if record["count"] < count:
            yield event.plain_result(f"❌ 可用次数不足！当前可用：{record['count']}")
        else:
            record["count"] -= count
            self._save_user_record(user_id, record)
            yield event.plain_result(f"✅ 提现 {count} 次，剩余：{record['count']}")

        self.user_state[user_id] = 'idle'
        yield event.plain_result(self._get_menu_text(user_id))
