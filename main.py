import json
import os
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import logger

class KuwoManagerPlugin(Star):
    """酷我账号管理 - 本地文件存储，每个QQ独立管理"""

    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        # 数据文件路径
        self.data_dir = os.path.join(os.path.dirname(__file__), "data")
        self.data_file = os.path.join(self.data_dir, "user_data.json")
        # 确保目录存在
        os.makedirs(self.data_dir, exist_ok=True)
        # 加载或初始化数据
        self.user_data = self._load_data()
        # 用户交互状态
        self.user_state = {}   # {user_id: 'idle'|'waiting_phone'|'waiting_recharge'|'waiting_withdraw'|'waiting_delete'}
        logger.info("✅ 酷我插件（本地存储版）已加载")

    # ---------- 数据持久化 ----------
    def _load_data(self) -> dict:
        """从文件加载用户数据，若文件不存在则返回空字典"""
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"加载数据失败: {e}")
                return {}
        return {}

    def _save_data(self):
        """保存用户数据到文件"""
        try:
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(self.user_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存数据失败: {e}")

    def _get_user_record(self, user_id: str) -> dict:
        """获取某个用户的记录，若不存在则创建默认"""
        if user_id not in self.user_data:
            self.user_data[user_id] = {
                "accounts": [],   # [{"phone": "138...", "password": "..."}, ...]
                "count": 0        # 可用次数
            }
            self._save_data()
        return self.user_data[user_id]

    def _save_user_record(self, user_id: str, record: dict):
        self.user_data[user_id] = record
        self._save_data()

    # ---------- 辅助：获取用户ID和消息文本（兼容不同版本） ----------
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

    # ---------- 命令处理 ----------
    @filter.command("酷我")
    async def kuwo_menu(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        self.user_state[user_id] = 'idle'
        menu = self._get_menu_text(user_id)
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

        record = self._get_user_record(user_id)
        # 检查是否已有该手机号
        for acc in record["accounts"]:
            if acc["phone"] == phone:
                # 更新密码
                acc["password"] = password
                self._save_user_record(user_id, record)
                yield event.plain_result(f"✅ 账号 {phone} 密码已更新")
                self.user_state[user_id] = 'idle'
                menu = self._get_menu_text(user_id)
                yield event.plain_result(menu)
                return

        # 新增
        record["accounts"].append({"phone": phone, "password": password})
        self._save_user_record(user_id, record)
        yield event.plain_result(f"✅ 账号 {phone} 已保存")
        self.user_state[user_id] = 'idle'
        menu = self._get_menu_text(user_id)
        yield event.plain_result(menu)

    # ---------- 删除账号 ----------
    @filter.regex(r'^\d{11}$')
    async def handle_delete_phone(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        if self.user_state.get(user_id) != 'waiting_delete':
            return

        phone = self._get_text(event)
        record = self._get_user_record(user_id)
        # 查找并删除
        for idx, acc in enumerate(record["accounts"]):
            if acc["phone"] == phone:
                del record["accounts"][idx]
                self._save_user_record(user_id, record)
                yield event.plain_result(f"✅ 已删除账号 {phone}")
                break
        else:
            yield event.plain_result(f"❌ 未找到您绑定的手机号 {phone}")

        self.user_state[user_id] = 'idle'
        menu = self._get_menu_text(user_id)
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

        record = self._get_user_record(user_id)
        record["count"] += count
        self._save_user_record(user_id, record)
        yield event.plain_result(f"✅ 充值 {count} 次，当前可用：{record['count']}")
        self.user_state[user_id] = 'idle'
        menu = self._get_menu_text(user_id)
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

        record = self._get_user_record(user_id)
        if record["count"] < count:
            yield event.plain_result(f"❌ 可用次数不足！当前可用：{record['count']}")
        else:
            record["count"] -= count
            self._save_user_record(user_id, record)
            yield event.plain_result(f"✅ 提现 {count} 次，剩余：{record['count']}")

        self.user_state[user_id] = 'idle'
        menu = self._get_menu_text(user_id)
        yield event.plain_result(menu)
