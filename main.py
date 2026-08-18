import json
import os
import time
import re
import aiohttp
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import logger

class KuwoManagerPlugin(Star):
    """酷我账号管理 - 管理员交互式菜单"""

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

        # 管理员QQ列表
        admin_str = config.get("admin_qq", "").strip()
        self.admin_qqs = [qq.strip() for qq in admin_str.split(',') if qq.strip()]

        # 全局数据存储
        self.data_dir = os.path.join(os.getcwd(), "data", "kuwo_data")
        self.cache_file = os.path.join(self.data_dir, "user_data.json")
        os.makedirs(self.data_dir, exist_ok=True)
        self.cache = self._load_cache()

        # 用户状态（普通用户菜单和管理员菜单共用）
        self.state_info = {}   # 存储用户状态
        self.TIMEOUT = 120

        logger.info("✅ 酷我插件（管理员交互式菜单）已加载")
        if self.admin_qqs:
            logger.info(f"管理员QQ: {', '.join(self.admin_qqs)}")
        else:
            logger.warning("⚠️ 未配置管理员QQ，管理功能不可用")

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

    # ---------- 环境变量读写 ----------
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

    # ---------- 账号相关 ----------
    async def _get_my_accounts(self, user_id: str) -> list:
        return self._get_cache_user(user_id)["accounts"]

    async def _get_my_env_entries(self, user_id: str) -> list:
        all_entries = await self._get_all_env_entries()
        my_phones = [acc["phone"] for acc in await self._get_my_accounts(user_id)]
        return [entry for entry in all_entries if entry["phone"] in my_phones]

    async def _get_user_total_auth(self, user_id: str) -> int:
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

    # ---------- 状态管理（普通用户和管理员共用） ----------
    def _get_state_info(self, user_id: str) -> dict:
        now = time.time()
        if user_id not in self.state_info:
            self.state_info[user_id] = {'state': 'idle', 'last_active': now, 'trigger_msg': None, 'admin_mode': False}
        info = self.state_info[user_id]
        if info['state'] != 'idle' and (now - info['last_active']) > self.TIMEOUT:
            info['state'] = 'idle'
            info['trigger_msg'] = None
            info['admin_mode'] = False
        return info

    def _set_state(self, user_id: str, state: str, trigger_msg: str = None, admin_mode: bool = False):
        self.state_info[user_id] = {
            'state': state,
            'last_active': time.time(),
            'trigger_msg': trigger_msg,
            'admin_mode': admin_mode
        }

    # ---------- 普通用户菜单 ----------
    async def _get_menu_text(self, user_id: str) -> str:
        my_acc = await self._get_my_accounts(user_id)
        count = len(my_acc)
        total_auth = await self._get_user_total_auth(user_id)
        return (
            f"=====酷我=====\n"
            f"账号{count}个，可用次数{total_auth}\n"
            "[1] 提交账号\n"
            "[2] 删除账号\n"
            "[3] 查询授权次数明细\n"
            "[r] 重置我的所有数据\n"
            "[q] 退出"
        )

    @filter.command("酷我")
    async def kuwo_menu(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        self._set_state(user_id, 'idle', admin_mode=False)
        menu = await self._get_menu_text(user_id)
        yield event.plain_result(menu)

    @filter.regex(r'^[1-3rRqQ]$')
    async def handle_menu_choice(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        state_info = self._get_state_info(user_id)
        # 如果当前处于管理员模式，则忽略普通菜单选择
        if state_info.get('admin_mode', False):
            return
        if state_info['state'] != 'idle':
            return

        text = self._get_text(event).lower()

        if text == '1':
            self._set_state(user_id, 'waiting_phone', text, admin_mode=False)
            yield event.plain_result("请输入手机号#密码（例如：13800138000#mypassword）")
        elif text == '2':
            my_acc = await self._get_my_accounts(user_id)
            if not my_acc:
                yield event.plain_result("❌ 您没有绑定任何账号")
            else:
                lines = [f"{idx+1}. {acc['phone']}" for idx, acc in enumerate(my_acc)]
                prompt = "您的账号：\n" + "\n".join(lines) + "\n请输入要删除的序号（如 1）："
                yield event.plain_result(prompt)
                self._set_state(user_id, 'waiting_delete', text, admin_mode=False)
        elif text == '3':
            my_env_entries = await self._get_my_env_entries(user_id)
            if not my_env_entries:
                yield event.plain_result("📭 您当前没有绑定任何账号，或账号尚未同步到环境变量。")
            else:
                msg = "📋 您的账号授权次数明细：\n"
                total = 0
                for entry in my_env_entries:
                    msg += f"手机号：{entry['phone']} ｜ 授权次数：{entry['auth_count']}\n"
                    total += entry['auth_count']
                msg += f"合计可用次数：{total}"
                yield event.plain_result(msg)
            menu = await self._get_menu_text(user_id)
            yield event.plain_result(menu)
        elif text == 'r':
            await self._reset_user_data(user_id)
            yield event.plain_result("✅ 您的所有数据已重置")
            menu = await self._get_menu_text(user_id)
            yield event.plain_result(menu)
        elif text == 'q':
            yield event.plain_result("👋 已退出菜单")
            self._set_state(user_id, 'idle', admin_mode=False)

    # ---------- 提交账号（普通用户） ----------
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
            self._set_state(user_id, 'idle', admin_mode=False)
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

        self._set_state(user_id, 'idle', admin_mode=False)
        menu = await self._get_menu_text(user_id)
        yield event.plain_result(menu)

    # ---------- 删除账号（普通用户） ----------
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
            self._set_state(user_id, 'idle', admin_mode=False)
            menu = await self._get_menu_text(user_id)
            yield event.plain_result(menu)
            return

        cache_user = self._get_cache_user(user_id)
        my_acc = cache_user["accounts"]
        if idx < 1 or idx > len(my_acc):
            yield event.plain_result(f"❌ 序号无效，请输入 1 到 {len(my_acc)} 之间的数字")
            self._set_state(user_id, 'idle', admin_mode=False)
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
        self._set_state(user_id, 'idle', admin_mode=False)
        menu = await self._get_menu_text(user_id)
        yield event.plain_result(menu)

    # ---------- 管理员交互式菜单 ----------
    async def _get_admin_menu_text(self) -> str:
        return (
            "=====管理面板=====\n"
            "[1] 查看所有绑定关系（按QQ分组）\n"
            "[2] 查看所有环境变量账号（含未绑定QQ）\n"
            "[3] 绑定账号（为QQ绑定手机号）\n"
            "[4] 删除账号（从缓存和环境变量删除）\n"
            "[5] 修改授权次数（增/减/设）\n"
            "[6] 提现审核（扣减授权次数）\n"
            "[7] 重置用户所有数据\n"
            "[q] 退出"
        )

    @filter.command("管理")
    async def admin_menu(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        if user_id not in self.admin_qqs:
            yield event.plain_result("❌ 你没有权限执行此操作")
            return
        self._set_state(user_id, 'idle', admin_mode=True)
        menu = await self._get_admin_menu_text()
        yield event.plain_result(menu)

    @filter.regex(r'^[1-7qQ]$')
    async def handle_admin_choice(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        state_info = self._get_state_info(user_id)
        # 只有管理员且处于管理状态才处理
        if user_id not in self.admin_qqs:
            return
        if not state_info.get('admin_mode', False):
            return
        if state_info['state'] != 'idle':
            # 如果正在执行某个子操作，不能选择菜单
            return

        text = self._get_text(event).lower()

        if text == '1':
            await self._admin_view_all_bindings(event)
        elif text == '2':
            await self._admin_view_all_env_accounts(event)
        elif text == '3':
            self._set_state(user_id, 'admin_bind_wait_qq', admin_mode=True)
            yield event.plain_result("请输入要绑定的QQ号：")
        elif text == '4':
            self._set_state(user_id, 'admin_delete_wait_phone', admin_mode=True)
            yield event.plain_result("请输入要删除的手机号（11位）：")
        elif text == '5':
            self._set_state(user_id, 'admin_auth_wait_phone', admin_mode=True)
            yield event.plain_result("请输入要修改授权次数的手机号：")
        elif text == '6':
            self._set_state(user_id, 'admin_withdraw_wait_phone', admin_mode=True)
            yield event.plain_result("请输入要提现扣减的手机号：")
        elif text == '7':
            self._set_state(user_id, 'admin_reset_wait_qq', admin_mode=True)
            yield event.plain_result("请输入要重置的QQ号：")
        elif text == 'q':
            yield event.plain_result("👋 已退出管理面板")
            self._set_state(user_id, 'idle', admin_mode=False)

    # ---------- 管理员子操作 ----------
    async def _admin_view_all_bindings(self, event):
        """查看所有绑定关系"""
        if not self.cache:
            yield event.plain_result("📭 暂无任何用户绑定数据")
            return
        msg = "📋 **所有绑定关系**\n（仅显示手机号，密码已隐藏）\n\n"
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
            yield event.plain_result("📭 暂无任何用户绑定数据")
            return
        msg += f"统计：共 {total_users} 个用户，{total_accounts} 个绑定账号"
        yield event.plain_result(msg)
        # 返回菜单
        menu = await self._get_admin_menu_text()
        yield event.plain_result(menu)

    async def _admin_view_all_env_accounts(self, event):
        """查看所有环境变量账号（含未绑定QQ）"""
        env_entries = await self._get_all_env_entries()
        if not env_entries:
            yield event.plain_result("📭 环境变量中暂无任何账号")
            return
        # 构建手机号到QQ的映射
        phone_to_qq = {}
        for qq, data in self.cache.items():
            for acc in data.get("accounts", []):
                phone_to_qq[acc["phone"]] = qq

        msg = "📋 **环境变量账号列表**\n"
        msg += "（含未绑定QQ的账号）\n\n"
        for entry in env_entries:
            phone = entry["phone"]
            auth = entry["auth_count"]
            qq = phone_to_qq.get(phone, "未绑定")
            msg += f"📱 {phone} ｜ 授权次数: {auth} ｜ 绑定QQ: {qq}\n"
        yield event.plain_result(msg)
        menu = await self._get_admin_menu_text()
        yield event.plain_result(menu)

    # ---------- 管理员状态机处理 ----------
    @filter.regex(r'^\d+$')
    async def handle_admin_input_qq(self, event: AstrMessageEvent):
        """处理管理员输入的QQ号"""
        user_id = self._get_user_id(event)
        if user_id not in self.admin_qqs:
            return
        state_info = self._get_state_info(user_id)
        if state_info['state'] == 'admin_bind_wait_qq':
            target_qq = self._get_text(event)
            # 验证QQ号是否为数字
            if not target_qq.isdigit():
                yield event.plain_result("❌ QQ号须为数字，请重新输入")
                return
            # 保存到状态
            self.state_info[user_id]['tmp_data'] = {'target_qq': target_qq}
            self._set_state(user_id, 'admin_bind_wait_phone', admin_mode=True)
            yield event.plain_result(f"请输入要绑定到 QQ {target_qq} 的手机号（11位）：")
        elif state_info['state'] == 'admin_reset_wait_qq':
            target_qq = self._get_text(event)
            if not target_qq.isdigit():
                yield event.plain_result("❌ QQ号须为数字，请重新输入")
                return
            # 执行重置
            await self._reset_user_data(target_qq)
            yield event.plain_result(f"✅ 已重置用户 {target_qq} 的所有数据")
            self._set_state(user_id, 'idle', admin_mode=True)
            menu = await self._get_admin_menu_text()
            yield event.plain_result(menu)

    @filter.regex(r'^\d{11}$')
    async def handle_admin_input_phone(self, event: AstrMessageEvent):
        """处理管理员输入的手机号"""
        user_id = self._get_user_id(event)
        if user_id not in self.admin_qqs:
            return
        state_info = self._get_state_info(user_id)
        phone = self._get_text(event)

        if state_info['state'] == 'admin_bind_wait_phone':
            target_qq = state_info.get('tmp_data', {}).get('target_qq')
            if not target_qq:
                yield event.plain_result("❌ 会话错误，请重新执行")
                self._set_state(user_id, 'idle', admin_mode=True)
                menu = await self._get_admin_menu_text()
                yield event.plain_result(menu)
                return
            # 执行绑定
            await self._admin_do_bind(target_qq, phone, event)
            self._set_state(user_id, 'idle', admin_mode=True)
            menu = await self._get_admin_menu_text()
            yield event.plain_result(menu)
        elif state_info['state'] == 'admin_delete_wait_phone':
            await self._admin_do_delete(phone, event)
            self._set_state(user_id, 'idle', admin_mode=True)
            menu = await self._get_admin_menu_text()
            yield event.plain_result(menu)
        elif state_info['state'] == 'admin_auth_wait_phone':
            # 保存手机号，等待输入数量
            self.state_info[user_id]['tmp_data'] = {'phone': phone}
            self._set_state(user_id, 'admin_auth_wait_delta', admin_mode=True)
            yield event.plain_result(f"请输入要修改的差值（正数增加，负数减少）：")
        elif state_info['state'] == 'admin_withdraw_wait_phone':
            # 保存手机号，等待输入提现数量
            self.state_info[user_id]['tmp_data'] = {'phone': phone}
            self._set_state(user_id, 'admin_withdraw_wait_amount', admin_mode=True)
            yield event.plain_result(f"请输入要提现扣减的数量（正整数）：")

    @filter.regex(r'^-?\d+$')
    async def handle_admin_input_delta(self, event: AstrMessageEvent):
        """处理管理员输入的数量差值"""
        user_id = self._get_user_id(event)
        if user_id not in self.admin_qqs:
            return
        state_info = self._get_state_info(user_id)
        delta = int(self._get_text(event))

        if state_info['state'] == 'admin_auth_wait_delta':
            phone = state_info.get('tmp_data', {}).get('phone')
            if not phone:
                yield event.plain_result("❌ 会话错误，请重新执行")
                self._set_state(user_id, 'idle', admin_mode=True)
                menu = await self._get_admin_menu_text()
                yield event.plain_result(menu)
                return
            await self._admin_do_auth(phone, delta, event)
            self._set_state(user_id, 'idle', admin_mode=True)
            menu = await self._get_admin_menu_text()
            yield event.plain_result(menu)
        elif state_info['state'] == 'admin_withdraw_wait_amount':
            if delta <= 0:
                yield event.plain_result("❌ 提现数量须为正整数，请重新输入")
                return
            phone = state_info.get('tmp_data', {}).get('phone')
            if not phone:
                yield event.plain_result("❌ 会话错误，请重新执行")
                self._set_state(user_id, 'idle', admin_mode=True)
                menu = await self._get_admin_menu_text()
                yield event.plain_result(menu)
                return
            await self._admin_do_withdraw(phone, delta, event)
            self._set_state(user_id, 'idle', admin_mode=True)
            menu = await self._get_admin_menu_text()
            yield event.plain_result(menu)

    # ---------- 管理员实际执行函数 ----------
    async def _admin_do_bind(self, target_qq: str, phone: str, event):
        """执行绑定"""
        if not re.match(r'^\d{11}$', phone):
            yield event.plain_result("❌ 手机号格式错误，须为11位数字")
            return
        # 检查是否被其他用户绑定
        existing_owner = None
        for qq, data in self.cache.items():
            for acc in data["accounts"]:
                if acc["phone"] == phone:
                    existing_owner = qq
                    break
            if existing_owner:
                break
        # 获取目标用户缓存
        target_cache = self._get_cache_user(target_qq)
        accounts = target_cache["accounts"]
        found = None
        for acc in accounts:
            if acc["phone"] == phone:
                found = acc
                break
        if found:
            # 密码已存在，无法修改（管理员可强制更新，但此处我们不提供密码设置，只绑定）
            yield event.plain_result(f"⚠️ 用户 {target_qq} 已绑定该手机号")
            return
        # 新增
        # 需要密码，但管理员不提供密码，我们随机生成一个占位符
        password = "admin_placeholder"
        accounts.append({"phone": phone, "password": password})
        self._update_cache_user(target_qq, accounts)
        # 环境变量：若手机号已存在（可能未绑定QQ），则保留，否则新增
        env_entries = await self._get_all_env_entries()
        entry_found = False
        for entry in env_entries:
            if entry["phone"] == phone:
                entry_found = True
                break
        if not entry_found:
            env_entries.append({"phone": phone, "password": password, "auth_count": 0})
            await self._save_all_env_entries(env_entries)
        msg = f"✅ 已为用户 {target_qq} 绑定手机号 {phone}"
        if existing_owner and existing_owner != target_qq:
            msg += f"\n⚠️ 注意：该手机号原本属于用户 {existing_owner}，已被管理员强制迁移至 {target_qq}"
        yield event.plain_result(msg)

    async def _admin_do_delete(self, phone: str, event):
        """执行删除"""
        if not re.match(r'^\d{11}$', phone):
            yield event.plain_result("❌ 手机号格式错误，须为11位数字")
            return
        # 从所有用户的缓存中删除该手机号
        deleted = False
        for qq, data in self.cache.items():
            accounts = data["accounts"]
            for idx, acc in enumerate(accounts):
                if acc["phone"] == phone:
                    del accounts[idx]
                    self._update_cache_user(qq, accounts)
                    deleted = True
                    break
        if not deleted:
            yield event.plain_result(f"❌ 手机号 {phone} 不存在于任何用户绑定中")
            return
        # 从环境变量删除
        env_entries = await self._get_all_env_entries()
        env_entries = [e for e in env_entries if e["phone"] != phone]
        await self._save_all_env_entries(env_entries)
        yield event.plain_result(f"✅ 已删除手机号 {phone}（从所有绑定和环境变量中移除）")

    async def _admin_do_auth(self, phone: str, delta: int, event):
        """修改授权次数"""
        env_entries = await self._get_all_env_entries()
        entry_found = None
        for entry in env_entries:
            if entry["phone"] == phone:
                entry_found = entry
                break
        if not entry_found:
            yield event.plain_result(f"❌ 手机号 {phone} 不存在于环境变量中")
            return
        new_count = entry_found["auth_count"] + delta
        if new_count < 0:
            yield event.plain_result(f"❌ 授权次数不能为负数，当前 {entry_found['auth_count']}，变化 {delta}")
            return
        entry_found["auth_count"] = new_count
        await self._save_all_env_entries(env_entries)
        yield event.plain_result(f"✅ 手机号 {phone} 授权次数已更新为 {new_count}（变动 {delta}）")

    async def _admin_do_withdraw(self, phone: str, amount: int, event):
        """提现扣减"""
        env_entries = await self._get_all_env_entries()
        entry_found = None
        for entry in env_entries:
            if entry["phone"] == phone:
                entry_found = entry
                break
        if not entry_found:
            yield event.plain_result(f"❌ 手机号 {phone} 不存在于环境变量中")
            return
        if entry_found["auth_count"] < amount:
            yield event.plain_result(f"❌ 授权次数不足！当前 {entry_found['auth_count']}，需扣减 {amount}")
            return
        entry_found["auth_count"] -= amount
        await self._save_all_env_entries(env_entries)
        yield event.plain_result(f"✅ 提现成功！手机号 {phone} 减少 {amount} 次，剩余 {entry_found['auth_count']}")
