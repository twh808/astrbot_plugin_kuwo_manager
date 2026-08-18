import json
import os
import time
import aiohttp
import uuid
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import logger

class KuwoManagerPlugin(Star):
    """酷我账号管理 - 次数以环境变量kwtx为准，每次核对"""

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

        # 全局数据存储
        self.data_dir = os.path.join(os.getcwd(), "data", "kuwo_data")
        self.cache_file = os.path.join(self.data_dir, "user_data.json")
        os.makedirs(self.data_dir, exist_ok=True)
        self.cache = self._load_cache()  # {user_id: {"accounts": [{"phone":, "password":}]}}

        # 状态管理
        self.state_info = {}  # user_id: {state, last_active, trigger_msg, order_data}
        self.TIMEOUT = 300    # 支付等待超时5分钟

        # 临时订单存储
        self.pending_orders = {}

        logger.info("✅ 酷我插件（环境变量为准）已加载")

    # ---------- 缓存读写（仅账号列表） ----------
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

    # ---------- 获取用户所有账号及统计 ----------
    async def _get_my_accounts(self, user_id: str) -> list:
        """返回当前用户绑定的账号列表（仅手机号和密码）"""
        return self._get_cache_user(user_id)["accounts"]

    async def _get_my_env_entries(self, user_id: str) -> list:
        """从环境变量中筛选出当前用户的所有账号（完整条目）"""
        all_entries = await self._get_all_env_entries()
        my_phones = [acc["phone"] for acc in await self._get_my_accounts(user_id)]
        return [entry for entry in all_entries if entry["phone"] in my_phones]

    async def _get_user_total_auth(self, user_id: str) -> int:
        """计算当前用户所有账号的授权次数总和"""
        my_entries = await self._get_my_env_entries(user_id)
        return sum(entry["auth_count"] for entry in my_entries)

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
            self.state_info[user_id] = {'state': 'idle', 'last_active': now, 'trigger_msg': None, 'order_data': None}
        info = self.state_info[user_id]
        if info['state'] != 'idle' and (now - info['last_active']) > self.TIMEOUT:
            info['state'] = 'idle'
            info['trigger_msg'] = None
            info['order_data'] = None
        return info

    def _set_state(self, user_id: str, state: str, trigger_msg: str = None, order_data: dict = None):
        self.state_info[user_id] = {
            'state': state,
            'last_active': time.time(),
            'trigger_msg': trigger_msg,
            'order_data': order_data
        }

    # ---------- 菜单 ----------
    async def _get_menu_text(self, user_id: str) -> str:
        my_acc = await self._get_my_accounts(user_id)
        count = len(my_acc)
        total_auth = await self._get_user_total_auth(user_id)
        return (
            f"=====酷我=====\n"
            f"账号{count}个，可用次数{total_auth}\n"
            "[1] 提交账号\n"
            "[2] 充值次数（按账号）\n"
            "[3] 删除账号\n"
            "[4] 提现次数（按账号）\n"
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
        state_info = self._get_state_info(user_id)
        if state_info['state'] != 'idle':
            return

        text = self._get_text(event).lower()

        if text == '1':
            self._set_state(user_id, 'waiting_phone', text)
            yield event.plain_result("请输入手机号#密码（例如：13800138000#mypassword）")
        elif text == '2':
            my_acc = await self._get_my_accounts(user_id)
            if not my_acc:
                yield event.plain_result("❌ 您没有绑定任何账号，请先提交账号")
            else:
                lines = [f"{idx+1}. {acc['phone']}" for idx, acc in enumerate(my_acc)]
                prompt = "请选择要充值的账号序号：\n" + "\n".join(lines) + "\n请输入序号："
                yield event.plain_result(prompt)
                self._set_state(user_id, 'waiting_recharge_acc', text)
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
            my_acc = await self._get_my_accounts(user_id)
            if not my_acc:
                yield event.plain_result("❌ 您没有绑定任何账号，请先提交账号")
            else:
                lines = [f"{idx+1}. {acc['phone']}" for idx, acc in enumerate(my_acc)]
                prompt = "请选择要提现的账号序号：\n" + "\n".join(lines) + "\n请输入序号："
                yield event.plain_result(prompt)
                self._set_state(user_id, 'waiting_withdraw_acc', text)
        elif text == 'r':
            await self._reset_user_data(user_id)
            yield event.plain_result("✅ 您的所有数据已重置")
            menu = await self._get_menu_text(user_id)
            yield event.plain_result(menu)
        elif text == 'q':
            yield event.plain_result("👋 已退出菜单")
            self._set_state(user_id, 'idle')

    # ---------- 选择账号（充值） ----------
    @filter.regex(r'^\d+$')
    async def handle_recharge_acc(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        state_info = self._get_state_info(user_id)
        if state_info['state'] != 'waiting_recharge_acc':
            return
        current_text = self._get_text(event)
        if state_info.get('trigger_msg') == current_text:
            return

        try:
            idx = int(current_text)
        except:
            yield event.plain_result("❌ 请输入有效数字")
            self._set_state(user_id, 'idle')
            menu = await self._get_menu_text(user_id)
            yield event.plain_result(menu)
            return

        my_acc = await self._get_my_accounts(user_id)
        if idx < 1 or idx > len(my_acc):
            yield event.plain_result(f"❌ 序号无效，请输入 1 到 {len(my_acc)} 之间的数字")
            self._set_state(user_id, 'idle')
            menu = await self._get_menu_text(user_id)
            yield event.plain_result(menu)
            return

        phone = my_acc[idx-1]["phone"]
        # 进入等待输入充值次数
        self._set_state(user_id, 'waiting_recharge_count', trigger_msg=current_text, order_data={'phone': phone})
        yield event.plain_result(f"已选择账号 {phone}，请输入要充值的次数（0.5元/次）：")

    # ---------- 输入充值次数，生成订单 ----------
    @filter.regex(r'^\d+$')
    async def handle_recharge_count(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        state_info = self._get_state_info(user_id)
        if state_info['state'] != 'waiting_recharge_count':
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

        phone = state_info.get('order_data', {}).get('phone')
        if not phone:
            yield event.plain_result("❌ 系统错误，请重新操作")
            self._set_state(user_id, 'idle')
            menu = await self._get_menu_text(user_id)
            yield event.plain_result(menu)
            return

        amount = count * 0.5
        order_id = str(uuid.uuid4())[:8]
        self.pending_orders[order_id] = {
            'user_id': user_id,
            'phone': phone,
            'count': count,
            'amount': amount,
            'status': 'pending',
            'created_at': time.time()
        }
        self._set_state(user_id, 'waiting_payment', trigger_msg=current_text, order_data={'order_id': order_id})

        pay_info = (
            f"📋 订单号：{order_id}\n"
            f"📱 充值账号：{phone}\n"
            f"🔢 充值次数：{count}\n"
            f"💰 金额：{amount:.2f} 元\n"
            f"💳 请支付后发送「支付确认 {order_id}」完成充值\n"
            f"（模拟支付，实际请对接支付接口）"
        )
        yield event.plain_result(pay_info)

    # ---------- 支付确认（充值到账） ----------
    @filter.regex(r'^支付确认\s+(\w+)$')
    async def handle_payment_confirm(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        order_id = self._get_text(event).split()[1]
        order = self.pending_orders.get(order_id)
        if not order:
            yield event.plain_result("❌ 订单不存在或已过期")
            return
        if order['user_id'] != user_id:
            yield event.plain_result("❌ 该订单不属于您")
            return
        if order['status'] == 'completed':
            yield event.plain_result("✅ 该订单已完成充值")
            return

        # 支付成功，增加环境变量中的授权次数
        phone = order['phone']
        count = order['count']
        env_entries = await self._get_all_env_entries()
        target_entry = None
        for entry in env_entries:
            if entry['phone'] == phone:
                target_entry = entry
                break
        if not target_entry:
            yield event.plain_result(f"❌ 账号 {phone} 在环境变量中不存在，请联系管理员")
            return

        # 增加授权次数
        target_entry['auth_count'] += count
        if await self._save_all_env_entries(env_entries):
            order['status'] = 'completed'
            yield event.plain_result(f"✅ 充值成功！账号 {phone} 增加 {count} 次，当前授权次数：{target_entry['auth_count']}")
        else:
            yield event.plain_result("❌ 充值失败，请稍后重试或联系管理员")

        # 清理订单和状态
        del self.pending_orders[order_id]
        state_info = self._get_state_info(user_id)
        if state_info['state'] == 'waiting_payment':
            self._set_state(user_id, 'idle')
            menu = await self._get_menu_text(user_id)
            yield event.plain_result(menu)

    # ---------- 选择账号（提现） ----------
    @filter.regex(r'^\d+$')
    async def handle_withdraw_acc(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        state_info = self._get_state_info(user_id)
        if state_info['state'] != 'waiting_withdraw_acc':
            return
        current_text = self._get_text(event)
        if state_info.get('trigger_msg') == current_text:
            return

        try:
            idx = int(current_text)
        except:
            yield event.plain_result("❌ 请输入有效数字")
            self._set_state(user_id, 'idle')
            menu = await self._get_menu_text(user_id)
            yield event.plain_result(menu)
            return

        my_acc = await self._get_my_accounts(user_id)
        if idx < 1 or idx > len(my_acc):
            yield event.plain_result(f"❌ 序号无效，请输入 1 到 {len(my_acc)} 之间的数字")
            self._set_state(user_id, 'idle')
            menu = await self._get_menu_text(user_id)
            yield event.plain_result(menu)
            return

        phone = my_acc[idx-1]["phone"]
        self._set_state(user_id, 'waiting_withdraw_count', trigger_msg=current_text, order_data={'phone': phone})
        yield event.plain_result(f"已选择账号 {phone}，请输入要提现的次数：")

    # ---------- 输入提现次数，执行扣减 ----------
    @filter.regex(r'^\d+$')
    async def handle_withdraw_count(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        state_info = self._get_state_info(user_id)
        if state_info['state'] != 'waiting_withdraw_count':
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

        phone = state_info.get('order_data', {}).get('phone')
        if not phone:
            yield event.plain_result("❌ 系统错误，请重新操作")
            self._set_state(user_id, 'idle')
            menu = await self._get_menu_text(user_id)
            yield event.plain_result(menu)
            return

        # 读取环境变量中该账号的当前授权次数
        env_entries = await self._get_all_env_entries()
        target_entry = None
        for entry in env_entries:
            if entry['phone'] == phone:
                target_entry = entry
                break
        if not target_entry:
            yield event.plain_result(f"❌ 账号 {phone} 在环境变量中不存在，请联系管理员")
            self._set_state(user_id, 'idle')
            menu = await self._get_menu_text(user_id)
            yield event.plain_result(menu)
            return

        if target_entry['auth_count'] < count:
            yield event.plain_result(f"❌ 该账号授权次数不足！当前可用：{target_entry['auth_count']}")
            self._set_state(user_id, 'idle')
            menu = await self._get_menu_text(user_id)
            yield event.plain_result(menu)
            return

        # 扣减
        target_entry['auth_count'] -= count
        if await self._save_all_env_entries(env_entries):
            yield event.plain_result(f"✅ 提现成功！账号 {phone} 减少 {count} 次，剩余：{target_entry['auth_count']}")
        else:
            yield event.plain_result("❌ 提现失败，请稍后重试")

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
        current_text = self._get_text(event)
        if state_info.get('trigger_msg') == current_text:
            return

        try:
            idx = int(current_text)
        except:
            yield event.plain_result("❌ 请输入有效的数字")
            self._set_state(user_id, 'idle')
            menu = await self._get_menu_text(user_id)
            yield event.plain_result(menu)
            return

        cache_user = self._get_cache_user(user_id)
        my_acc = cache_user["accounts"]
        if idx < 1 or idx > len(my_acc):
            yield event.plain_result(f"❌ 序号无效，请输入 1 到 {len(my_acc)} 之间的数字")
            self._set_state(user_id, 'idle')
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
        self._set_state(user_id, 'idle')
        menu = await self._get_menu_text(user_id)
        yield event.plain_result(menu)

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
            env_entries.append({"phone": phone, "password": password, "auth_count": 0})
            await self._save_all_env_entries(env_entries)
            yield event.plain_result(f"✅ 账号 {phone} 已保存")

        self._set_state(user_id, 'idle')
        menu = await self._get_menu_text(user_id)
        yield event.plain_result(menu)

    # ---------- 超时清理订单（内部调用） ----------
    async def _clean_expired_orders(self):
        now = time.time()
        expired = [oid for oid, order in self.pending_orders.items()
                   if order['status'] == 'pending' and (now - order['created_at']) > 300]
        for oid in expired:
            del self.pending_orders[oid]
            logger.info(f"订单 {oid} 已超时清理")
