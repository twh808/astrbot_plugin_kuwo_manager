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
        """尝试多种方式获取用户ID，兼容 AstrBot 不同版本"""
        # 方法1：如果有 get_user_id
        if hasattr(event, 'get_user_id'):
            return event.get_user_id()
        # 方法2：如果有 get_sender_id（OneBot 适配器常用）
        if hasattr(event, 'get_sender_id'):
            return event.get_sender_id()
        # 方法3：直接访问 message_obj 属性
        if hasattr(event, 'message_obj') and hasattr(event.message_obj, 'from_user_id'):
            return str(event.message_obj.from_user_id)
        # 方法4：尝试访问 sender_id 属性
        if hasattr(event, 'sender_id'):
            return event.sender_id
        # 方法5：尝试 get_session_id（可能会返回群号，不推荐）
        if hasattr(event, 'get_session_id'):
            return event.get_session_id()
        # 最后回退到使用事件对象的 id 属性（可能不可靠）
        logger.warning("无法获取用户ID，使用默认 'unknown'")
        return "unknown"

    # ---------- 主菜单命令 ----------
    @filter.command("酷我")
    async def kuwo_menu(self, event: AstrMessageEvent):
        """显示酷我主菜单"""
        user_id = self._get_user_id(event)
        self.user_state[user_id] = 'idle'
        await self._show_menu(event, user_id)

    # ---------- 处理后续输入（使用正则匹配） ----------
    @filter.regex(r'^[1-4qQ]$')
    async def handle_menu_choice(self, event: AstrMessageEvent):
        """处理主菜单的数字选择（1-4或q）"""
        user_id = self._get_user_id(event)
        text = event.get_plain_text().strip().lower()
        state = self.user_state.get(user_id, 'idle')
        
        if state != 'idle':
            return

        if text == '1':
            self.user_state[user_id] = 'waiting_phone'
            await event.reply("请输入手机号#密码（例如：13800138000#mypassword）")
        elif text == '2':
            self.user_state[user_id] = 'waiting_recharge'
            await event.reply("请输入要充值的次数（数字）")
        elif text == '3':
            if user_id in self.user_data:
                del self.user_data[user_id]
                await event.reply("✅ 账号已删除")
            else:
                await event.reply("❌ 您还没有提交账号")
            await self._show_menu(event, user_id)
        elif text == '4':
            self.user_state[user_id] = 'waiting_withdraw'
            await event.reply("请输入要提现的次数（数字）")
        elif text == 'q':
            await event.reply("👋 已退出菜单")
            self.user_state[user_id] = 'idle'
        else:
            await event.reply("无效选项，请重新选择")

    # ---------- 处理账号提交 ----------
    @filter.regex(r'^\d{11}#.+$')
    async def handle_phone_submit(self, event: AstrMessageEvent):
        """处理手机号#密码提交"""
        user_id = self._get_user_id(event)
        if self.user_state.get(user_id) != 'waiting_phone':
            return
        
        text = event.get_plain_text().strip()
        phone, password = text.split('#', 1)
        
        if user_id not in self.user_data:
            self.user_data[user_id] = {'count': 0}
        self.user_data[user_id]['phone'] = phone
        self.user_data[user_id]['password'] = password
        
        await event.reply(f"✅ 账号 {phone} 已保存")
        self.user_state[user_id] = 'idle'
        await self._show_menu(event, user_id)

    # ---------- 处理充值 ----------
    @filter.regex(r'^\d+$')
    async def handle_recharge(self, event: AstrMessageEvent):
        """处理充值次数"""
        user_id = self._get_user_id(event)
        if self.user_state.get(user_id) != 'waiting_recharge':
            return
        
        count = int(event.get_plain_text().strip())
        if count <= 0:
            await event.reply("❌ 次数必须为正整数")
            return
        
        if user_id not in self.user_data:
            self.user_data[user_id] = {'count': 0}
        self.user_data[user_id]['count'] += count
        
        await event.reply(f"✅ 成功充值 {count} 次，当前可用次数：{self.user_data[user_id]['count']}")
        self.user_state[user_id] = 'idle'
        await self._show_menu(event, user_id)

    # ---------- 处理提现 ----------
    @filter.regex(r'^\d+$')
    async def handle_withdraw(self, event: AstrMessageEvent):
        """处理提现次数"""
        user_id = self._get_user_id(event)
        if self.user_state.get(user_id) != 'waiting_withdraw':
            return
        
        count = int(event.get_plain_text().strip())
        if count <= 0:
            await event.reply("❌ 次数必须为正整数")
            return
        
        data = self.user_data.get(user_id)
        if not data or data.get('count', 0) < count:
            await event.reply(f"❌ 可用次数不足！当前可用：{data.get('count', 0) if data else 0}")
        else:
            data['count'] -= count
            await event.reply(f"✅ 成功提现 {count} 次，剩余次数：{data['count']}")
        
        self.user_state[user_id] = 'idle'
        await self._show_menu(event, user_id)

    # ---------- 辅助方法 ----------
    async def _show_menu(self, event: AstrMessageEvent, user_id: str):
        """显示主菜单"""
        data = self.user_data.get(user_id)
        if data and data.get('phone'):
            account_count = 1
            count = data.get('count', 0)
        else:
            account_count = 0
            count = 0
        
        menu = (
            f"=====酷我=====\n"
            f"账号{account_count}个，可用次数{count}\n"
            "[1] 提交账号\n"
            "[2] 充值次数\n"
            "[3] 删除账号\n"
            "[4] 账号提现\n"
            "[q] 退出"
        )
        await event.reply(menu)
