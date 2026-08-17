import time
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import logger

class KuwoManagerPlugin(Star):
    """酷我账号管理插件 - 支持多用户独立账号与次数管理"""
    
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        # 用户数据存储：{user_id: {'phone': str, 'password': str, 'count': int}}
        self.user_data = {}
        # 用户交互状态：'idle' | 'waiting_phone' | 'waiting_recharge' | 'waiting_withdraw'
        self.user_state = {}
        logger.info("✅ 酷我插件已加载")

    # ---------- 辅助方法：获取用户ID（兼容不同版本） ----------
    def _get_user_id(self, event: AstrMessageEvent) -> str:
        """尝试多种方式获取用户ID"""
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
        logger.warning("无法获取用户ID，使用默认 'unknown'")
        return "unknown"

    # ---------- 辅助方法：获取消息文本（兼容不同版本） ----------
    def _get_text(self, event: AstrMessageEvent) -> str:
        """尝试多种方式获取消息纯文本"""
        if hasattr(event, 'get_plain_text'):
            return event.get_plain_text().strip()
        if hasattr(event, 'message_str'):
            return event.message_str.strip()
        if hasattr(event, 'message'):
            # 如果 message 是对象，尝试转为字符串
            msg = event.message
            if hasattr(msg, 'get_plain_text'):
                return msg.get_plain_text().strip()
            return str(msg).strip()
        if hasattr(event, 'raw_message'):
            return event.raw_message.strip()
        logger.warning("无法获取消息文本，返回空字符串")
        return ""

    # ---------- 辅助方法：生成菜单文本 ----------
    def _get_menu_text(self, user_id: str) -> str:
        """返回菜单字符串，不直接发送"""
        data = self.user_data.get(user_id)
        if data and data.get('phone'):
            account_count = 1
            count = data.get('count', 0)
        else:
            account_count = 0
            count = 0
        return (
            f"=====酷我=====\n"
            f"账号{account_count}个，可用次数{count}\n"
            "[1] 提交账号\n"
            "[2] 充值次数\n"
            "[3] 删除账号\n"
            "[4] 账号提现\n"
            "[q] 退出"
        )

    # ---------- 主菜单命令 ----------
    @filter.command("酷我")
    async def kuwo_menu(self, event: AstrMessageEvent):
        """显示酷我主菜单"""
        user_id = self._get_user_id(event)
        self.user_state[user_id] = 'idle'
        yield event.plain_result(self._get_menu_text(user_id))

    # ---------- 处理主菜单选项 ----------
    @filter.regex(r'^[1-4qQ]$')
    async def handle_menu_choice(self, event: AstrMessageEvent):
        """处理主菜单的数字选择（1-4或q）"""
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
            if user_id in self.user_data:
                del self.user_data[user_id]
                yield event.plain_result("✅ 账号已删除")
            else:
                yield event.plain_result("❌ 您还没有提交账号")
            # 删除后显示菜单
            yield event.plain_result(self._get_menu_text(user_id))
        elif text == '4':
            self.user_state[user_id] = 'waiting_withdraw'
            yield event.plain_result("请输入要提现的次数（数字）")
        elif text == 'q':
            yield event.plain_result("👋 已退出菜单")
            self.user_state[user_id] = 'idle'
        else:
            yield event.plain_result("无效选项，请重新选择")

    # ---------- 处理账号提交 ----------
    @filter.regex(r'^\d{11}#.+$')
    async def handle_phone_submit(self, event: AstrMessageEvent):
        """处理手机号#密码提交"""
        user_id = self._get_user_id(event)
        if self.user_state.get(user_id) != 'waiting_phone':
            return
        
        text = self._get_text(event)
        phone, password = text.split('#', 1)
        
        if user_id not in self.user_data:
            self.user_data[user_id] = {'count': 0}
        self.user_data[user_id]['phone'] = phone
        self.user_data[user_id]['password'] = password
        
        yield event.plain_result(f"✅ 账号 {phone} 已保存")
        self.user_state[user_id] = 'idle'
        yield event.plain_result(self._get_menu_text(user_id))

    # ---------- 处理充值 ----------
    @filter.regex(r'^\d+$')
    async def handle_recharge(self, event: AstrMessageEvent):
        """处理充值次数"""
        user_id = self._get_user_id(event)
        if self.user_state.get(user_id) != 'waiting_recharge':
            return
        
        text = self._get_text(event)
        try:
            count = int(text)
        except ValueError:
            yield event.plain_result("❌ 请输入有效的数字")
            return
        
        if count <= 0:
            yield event.plain_result("❌ 次数必须为正整数")
            return
        
        if user_id not in self.user_data:
            self.user_data[user_id] = {'count': 0}
        self.user_data[user_id]['count'] += count
        
        yield event.plain_result(f"✅ 成功充值 {count} 次，当前可用次数：{self.user_data[user_id]['count']}")
        self.user_state[user_id] = 'idle'
        yield event.plain_result(self._get_menu_text(user_id))

    # ---------- 处理提现 ----------
    @filter.regex(r'^\d+$')
    async def handle_withdraw(self, event: AstrMessageEvent):
        """处理提现次数"""
        user_id = self._get_user_id(event)
        if self.user_state.get(user_id) != 'waiting_withdraw':
            return
        
        text = self._get_text(event)
        try:
            count = int(text)
        except ValueError:
            yield event.plain_result("❌ 请输入有效的数字")
            return
        
        if count <= 0:
            yield event.plain_result("❌ 次数必须为正整数")
            return
        
        data = self.user_data.get(user_id)
        if not data or data.get('count', 0) < count:
            yield event.plain_result(f"❌ 可用次数不足！当前可用：{data.get('count', 0) if data else 0}")
        else:
            data['count'] -= count
            yield event.plain_result(f"✅ 成功提现 {count} 次，剩余次数：{data['count']}")
        
        self.user_state[user_id] = 'idle'
        yield event.plain_result(self._get_menu_text(user_id))
