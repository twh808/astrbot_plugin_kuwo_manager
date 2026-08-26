import aiohttp
import time
import json
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import logger

class DaidaiManagerPlugin(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        if config is None:
            config = {}
        self.base_url = config.get("base_url", "http://127.0.0.1:5700/api/v1")
        self.app_key = config.get("app_key", "")
        self.app_secret = config.get("app_secret", "")
        self.token = None
        self.token_expiry = 0

        # ---------- 管理员配置（初始化时读取，与 kuwo_manager 一致） ----------
        admin_str = config.get("admin_qq", "").strip()
        self.admin_qqs = [qq.strip() for qq in admin_str.split(',') if qq.strip()]
        if self.admin_qqs:
            logger.info(f"✅ 呆呆面板管理 - 管理员已配置: {self.admin_qqs}")
        else:
            logger.info("ℹ️ 呆呆面板管理 - 未配置管理员，所有用户均可使用")

        logger.info("✅ 呆呆面板插件已加载")

    # ---------- 权限检查辅助方法（同步） ----------
    def _is_admin(self, event: AstrMessageEvent) -> bool:
        """检查发送者是否在管理员列表中"""
        if not self.admin_qqs:
            return True  # 未配置管理员则允许所有人
        try:
            sender = str(event.get_sender_id())
        except:
            # 兼容其他平台
            sender = str(event.get_user_id()) if hasattr(event, 'get_user_id') else "unknown"
        return sender in self.admin_qqs

    # ---------- Token 管理 ----------
    async def _get_token(self):
        if self.token and self.token_expiry > time.time():
            return self.token

        base = self.base_url.replace("/api/v1", "").replace("/api", "")
        token_url = f"{base}/api/open-api/token"
        payload = {
            "app_key": self.app_key,
            "app_secret": self.app_secret
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(token_url, json=payload) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise Exception(f"获取 Token 失败，状态码：{resp.status}，响应：{error_text}")
                result = await resp.json()
                logger.info(f"Token 响应: {result}")
                token = result.get("data", {}).get("access_token")
                if not token:
                    raise Exception(f"Token 响应中未找到 access_token 字段：{result}")
                expires_in = result.get("data", {}).get("expires_in", 86400)
                self.token_expiry = time.time() + expires_in - 60
                self.token = token
                return token

    # ---------- 通用 API 调用 ----------
    async def _call_api(self, endpoint: str, method: str = "POST", data: dict = None):
        token = await self._get_token()
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }
        logger.info(f"请求 URL: {url}")
        logger.info(f"请求方法: {method}")
        logger.info(f"请求体: {data}")
        async with aiohttp.ClientSession() as session:
            async with session.request(method, url, headers=headers, json=data) as resp:
                response_text = await resp.text()
                logger.info(f"响应状态码: {resp.status}")
                logger.info(f"响应内容: {response_text}")
                if resp.status == 401:
                    self.token = None
                    self.token_expiry = 0
                    return await self._call_api(endpoint, method, data)
                try:
                    return await resp.json()
                except:
                    return {"error": f"HTTP {resp.status}", "detail": response_text}

    # ---------- 公共函数 ----------
    async def _fetch_env_list(self):
        result = await self._call_api("envs?page=1&page_size=100", method="GET")
        return result.get("data", [])

    async def _get_env_id_by_name(self, env_name: str) -> int:
        envs = await self._fetch_env_list()
        for env in envs:
            if env.get("name") == env_name:
                return env.get("id")
        return None

    async def _create_env(self, name: str, value: str, group: str = "默认分组") -> bool:
        payload = {"name": name, "value": value, "group": group}
        result = await self._call_api("envs", method="POST", data=payload)
        if result.get("error") or result.get("code") not in [0, None, ""]:
            logger.error(f"创建环境变量失败: {result}")
            return False
        return True

    async def _update_env(self, env_id: int, name: str, value: str) -> bool:
        payload = {"name": name, "value": value}
        result = await self._call_api(f"envs/{env_id}", method="PUT", data=payload)
        if result.get("error") or result.get("code") not in [0, None, ""]:
            logger.error(f"更新环境变量失败: {result}")
            return False
        return True

    async def _update_env_accounts(self, env_name: str, accounts: dict) -> tuple:
        total = len(accounts)
        env_id = await self._get_env_id_by_name(env_name)
        if env_id is None:
            items = [f"{acc}#{val}" for acc, val in accounts.items()]
            initial = '&'.join(items)
            if await self._create_env(env_name, initial):
                return (f"✅ 环境变量 '{env_name}' 已创建", total)
            else:
                return (f"❌ 创建环境变量 '{env_name}' 失败", total)

        envs = await self._fetch_env_list()
        current_value = None
        for env in envs:
            if env.get("id") == env_id:
                current_value = env.get("value", "")
                break
        if current_value is None:
            return ("❌ 未找到该环境变量的当前值", total)

        if '\n' in current_value:
            separator = '\n'
        elif '&' in current_value:
            separator = '&'
        else:
            separator = None

        if separator is None:
            if '#' in current_value:
                parts = current_value.split('#', 1)
                existing_acc = parts[0]
                items = []
                if existing_acc in accounts:
                    items.append(f"{existing_acc}#{accounts[existing_acc]}")
                    accounts.pop(existing_acc)
                else:
                    items.append(current_value)
                for acc, val in accounts.items():
                    items.append(f"{acc}#{val}")
                new_val = '&'.join(items)
            else:
                return ("❌ 当前值不是账号格式，请使用覆盖模式", total)
        else:
            items = current_value.split(separator)
            items = [item for item in items if item.strip()]
            new_items = []
            for item in items:
                if '#' in item:
                    acc, val = item.split('#', 1)
                    if acc in accounts:
                        new_items.append(f"{acc}#{accounts[acc]}")
                        accounts.pop(acc)
                    else:
                        new_items.append(item)
                else:
                    new_items.append(item)
            for acc, val in accounts.items():
                new_items.append(f"{acc}#{val}")
            new_val = separator.join(new_items)

        if await self._update_env(env_id, env_name, new_val):
            return (f"✅ 环境变量 '{env_name}' 已更新", total)
        else:
            return ("❌ 更新失败", total)

    async def _set_env(self, env_name: str, new_value: str) -> str:
        env_id = await self._get_env_id_by_name(env_name)
        if env_id is None:
            if await self._create_env(env_name, new_value):
                return f"✅ 环境变量 '{env_name}' 已创建，值为 '{new_value}'"
            else:
                return f"❌ 创建环境变量 '{env_name}' 失败"
        else:
            if await self._update_env(env_id, env_name, new_value):
                return f"✅ 环境变量 '{env_name}' 已更新为 '{new_value}'"
            else:
                return f"❌ 更新环境变量 '{env_name}' 失败"

    # ========== 指令部分（均添加管理员验证） ==========
    @filter.command("envlist")
    async def envlist(self, event: AstrMessageEvent):
        if not self._is_admin(event):
            yield event.plain_result("⚠️ 您没有权限使用此命令。")
            return
        try:
            envs = await self._fetch_env_list()
            if not envs:
                yield event.plain_result("📭 当前没有环境变量")
            else:
                msg = "📋 环境变量列表：\n"
                for env in envs:
                    name = env.get("name", "未命名")
                    value = env.get("value", "")
                    group = env.get("group", "默认分组")
                    remarks = env.get("remarks", "")
                    remarks_str = f" ({remarks})" if remarks else ""
                    display_value = value if len(value) <= 50 else value[:50] + "..."
                    msg += f"- ID: {env.get('id')} | {name} = {display_value} | 分组: {group}{remarks_str}\n"
                yield event.plain_result(msg)
        except Exception as e:
            logger.error(f"获取环境变量列表失败: {e}")
            yield event.plain_result(f"❌ 请求失败：{str(e)}")

    @filter.command("环境变量列表")
    async def huanjingbianliangliebiao(self, event: AstrMessageEvent):
        if not self._is_admin(event):
            yield event.plain_result("⚠️ 您没有权限使用此命令。")
            return
        try:
            envs = await self._fetch_env_list()
            if not envs:
                yield event.plain_result("📭 当前没有环境变量")
            else:
                msg = "📋 环境变量列表：\n"
                for env in envs:
                    name = env.get("name", "未命名")
                    value = env.get("value", "")
                    group = env.get("group", "默认分组")
                    remarks = env.get("remarks", "")
                    remarks_str = f" ({remarks})" if remarks else ""
                    display_value = value if len(value) <= 50 else value[:50] + "..."
                    msg += f"- ID: {env.get('id')} | {name} = {display_value} | 分组: {group}{remarks_str}\n"
                yield event.plain_result(msg)
        except Exception as e:
            logger.error(f"获取环境变量列表失败: {e}")
            yield event.plain_result(f"❌ 请求失败：{str(e)}")

    @filter.command("变量列表")
    async def bianliangliebiao(self, event: AstrMessageEvent):
        if not self._is_admin(event):
            yield event.plain_result("⚠️ 您没有权限使用此命令。")
            return
        try:
            envs = await self._fetch_env_list()
            if not envs:
                yield event.plain_result("📭 当前没有环境变量")
            else:
                msg = "📋 环境变量列表：\n"
                for env in envs:
                    name = env.get("name", "未命名")
                    value = env.get("value", "")
                    group = env.get("group", "默认分组")
                    remarks = env.get("remarks", "")
                    remarks_str = f" ({remarks})" if remarks else ""
                    display_value = value if len(value) <= 50 else value[:50] + "..."
                    msg += f"- ID: {env.get('id')} | {name} = {display_value} | 分组: {group}{remarks_str}\n"
                yield event.plain_result(msg)
        except Exception as e:
            logger.error(f"获取环境变量列表失败: {e}")
            yield event.plain_result(f"❌ 请求失败：{str(e)}")

    @filter.command("变量")
    async def bianliang(self, event: AstrMessageEvent):
        if not self._is_admin(event):
            yield event.plain_result("⚠️ 您没有权限使用此命令。")
            return
        try:
            envs = await self._fetch_env_list()
            if not envs:
                yield event.plain_result("📭 当前没有环境变量")
            else:
                msg = "📋 环境变量列表：\n"
                for env in envs:
                    name = env.get("name", "未命名")
                    value = env.get("value", "")
                    group = env.get("group", "默认分组")
                    remarks = env.get("remarks", "")
                    remarks_str = f" ({remarks})" if remarks else ""
                    display_value = value if len(value) <= 50 else value[:50] + "..."
                    msg += f"- ID: {env.get('id')} | {name} = {display_value} | 分组: {group}{remarks_str}\n"
                yield event.plain_result(msg)
        except Exception as e:
            logger.error(f"获取环境变量列表失败: {e}")
            yield event.plain_result(f"❌ 请求失败：{str(e)}")

    @filter.command("envs")
    async def envs(self, event: AstrMessageEvent):
        if not self._is_admin(event):
            yield event.plain_result("⚠️ 您没有权限使用此命令。")
            return
        try:
            envs = await self._fetch_env_list()
            if not envs:
                yield event.plain_result("📭 当前没有环境变量")
            else:
                msg = "📋 环境变量列表：\n"
                for env in envs:
                    name = env.get("name", "未命名")
                    value = env.get("value", "")
                    group = env.get("group", "默认分组")
                    remarks = env.get("remarks", "")
                    remarks_str = f" ({remarks})" if remarks else ""
                    display_value = value if len(value) <= 50 else value[:50] + "..."
                    msg += f"- ID: {env.get('id')} | {name} = {display_value} | 分组: {group}{remarks_str}\n"
                yield event.plain_result(msg)
        except Exception as e:
            logger.error(f"获取环境变量列表失败: {e}")
            yield event.plain_result(f"❌ 请求失败：{str(e)}")

    @filter.command("更新环境变量")
    async def update_env_old(self, event: AstrMessageEvent, env_name: str, new_value: str):
        if not self._is_admin(event):
            yield event.plain_result("⚠️ 您没有权限使用此命令。")
            return
        try:
            raw = new_value.replace('\n', '').replace('\r', '').strip()
            if '&' in raw:
                parts = raw.split('&')
                accounts = {}
                for part in parts:
                    part = part.strip()
                    if not part:
                        continue
                    if '#' in part:
                        acc_val = part.split('#', 1)
                        acc = acc_val[0].strip()
                        val = acc_val[1].strip() if len(acc_val) > 1 else ''
                        if acc and val:
                            accounts[acc] = val
                        else:
                            yield event.plain_result(f"❌ 格式错误：'{part}' 缺少账号或值")
                            return
                    else:
                        yield event.plain_result(f"❌ 格式错误：'{part}' 缺少 # 分隔符")
                        return
                if accounts:
                    msg, count = await self._update_env_accounts(env_name, accounts)
                    if "✅" in msg:
                        yield event.plain_result(f"检测到 {count} 个账户，{msg}")
                    else:
                        yield event.plain_result(msg)
                else:
                    yield event.plain_result("❌ 未检测到有效的账户更新条目")
            else:
                if '#' in raw:
                    acc_val = raw.split('#', 1)
                    acc = acc_val[0].strip()
                    val = acc_val[1].strip() if len(acc_val) > 1 else ''
                    if acc and val:
                        msg, count = await self._update_env_accounts(env_name, {acc: val})
                        if "✅" in msg:
                            yield event.plain_result(f"检测到 {count} 个账户，{msg}")
                        else:
                            yield event.plain_result(msg)
                    else:
                        msg = await self._set_env(env_name, raw)
                        yield event.plain_result(msg)
                else:
                    msg = await self._set_env(env_name, raw)
                    yield event.plain_result(msg)
        except Exception as e:
            logger.error(f"更新环境变量失败: {e}")
            yield event.plain_result(f"❌ 请求失败：{str(e)}")

    @filter.command("更新变量")
    async def update_env_new(self, event: AstrMessageEvent, env_name: str, new_value: str):
        if not self._is_admin(event):
            yield event.plain_result("⚠️ 您没有权限使用此命令。")
            return
        try:
            raw = new_value.replace('\n', '').replace('\r', '').strip()
            if '&' in raw:
                parts = raw.split('&')
                accounts = {}
                for part in parts:
                    part = part.strip()
                    if not part:
                        continue
                    if '#' in part:
                        acc_val = part.split('#', 1)
                        acc = acc_val[0].strip()
                        val = acc_val[1].strip() if len(acc_val) > 1 else ''
                        if acc and val:
                            accounts[acc] = val
                        else:
                            yield event.plain_result(f"❌ 格式错误：'{part}' 缺少账号或值")
                            return
                    else:
                        yield event.plain_result(f"❌ 格式错误：'{part}' 缺少 # 分隔符")
                        return
                if accounts:
                    msg, count = await self._update_env_accounts(env_name, accounts)
                    if "✅" in msg:
                        yield event.plain_result(f"检测到 {count} 个账户，{msg}")
                    else:
                        yield event.plain_result(msg)
                else:
                    yield event.plain_result("❌ 未检测到有效的账户更新条目")
            else:
                if '#' in raw:
                    acc_val = raw.split('#', 1)
                    acc = acc_val[0].strip()
                    val = acc_val[1].strip() if len(acc_val) > 1 else ''
                    if acc and val:
                        msg, count = await self._update_env_accounts(env_name, {acc: val})
                        if "✅" in msg:
                            yield event.plain_result(f"检测到 {count} 个账户，{msg}")
                        else:
                            yield event.plain_result(msg)
                    else:
                        msg = await self._set_env(env_name, raw)
                        yield event.plain_result(msg)
                else:
                    msg = await self._set_env(env_name, raw)
                    yield event.plain_result(msg)
        except Exception as e:
            logger.error(f"更新环境变量失败: {e}")
            yield event.plain_result(f"❌ 请求失败：{str(e)}")

    @filter.command("运行脚本")
    async def run_script(self, event: AstrMessageEvent, script_path: str):
        if not self._is_admin(event):
            yield event.plain_result("⚠️ 您没有权限使用此命令。")
            return
        try:
            payload = {"path": script_path}
            result = await self._call_api("scripts/run", data=payload)
            if result.get("error") or result.get("code") not in [0, None, ""] or result.get("status") == "error":
                error_msg = result.get("msg") or result.get("message") or result.get("error") or str(result)
                yield event.plain_result(f"❌ 运行失败：{error_msg}")
            else:
                yield event.plain_result(f"✅ 脚本已成功执行！")
        except Exception as e:
            logger.error(f"调用呆呆面板API失败: {e}")
            yield event.plain_result(f"❌ 请求失败：{str(e)}")

    @filter.command("运行任务")
    async def run_task(self, event: AstrMessageEvent, task_name: str):
        if not self._is_admin(event):
            yield event.plain_result("⚠️ 您没有权限使用此命令。")
            return
        try:
            result = await self._call_api("tasks?page=1&page_size=100", method="GET")
            tasks = result.get("data")
            if not tasks or not isinstance(tasks, list):
                yield event.plain_result("❌ 获取任务列表失败")
                return
            task_id = None
            for task in tasks:
                if task.get("name") == task_name:
                    task_id = task.get("id")
                    break
            if task_id is None:
                yield event.plain_result(f"❌ 未找到名称为 '{task_name}' 的任务")
                return
            result = await self._call_api(f"tasks/{task_id}/run", method="PUT", data={})
            if result.get("error") or result.get("code") not in [0, None, ""] or result.get("status") == "error":
                error_msg = result.get("msg") or result.get("message") or result.get("error") or str(result)
                yield event.plain_result(f"❌ 运行任务失败：{error_msg}")
            else:
                message = result.get("message", "任务已启动")
                yield event.plain_result(f"✅ {message}")
        except Exception as e:
            logger.error(f"调用呆呆面板API失败: {e}")
            yield event.plain_result(f"❌ 请求失败：{str(e)}")
