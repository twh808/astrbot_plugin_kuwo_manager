import json
import os
import time
import re
import asyncio
import aiohttp
import requests
import base64
import random
import string
import uuid
import hashlib
from urllib.parse import quote
from datetime import datetime
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star
from astrbot.api import logger

# ---------- 常量 ----------
SIGN_BASE = 'https://integralapi.kuwo.cn/api/v1/online/sign'
URL_USER_ASSET = SIGN_BASE + '/v1/earningSignIn/earningUserSignList'
URL_NEW_DO_LISTEN = SIGN_BASE + '/v1/earningSignIn/newDoListen'
URL_EVERYDAY_DO_LISTEN = SIGN_BASE + '/v1/earningSignIn/everydaymusic/doListen'
URL_BOX_RENEW = SIGN_BASE + '/new/boxRenew'
URL_NEW_BOX_LIST = SIGN_BASE + '/new/newBoxList'
URL_NEW_BOX_FINISH = SIGN_BASE + '/new/newBoxFinish'
FREEMIUM_SWITCH_URL = 'https://wapi.kuwo.cn/openapi/v1/user/freemium/h5/switches'

static_c = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536, 131072, 262144, 524288, 1048576, 2097152, 4194304, 8388608, 16777216, 33554432, 67108864, 134217728, 268435456, 536870912, 1073741824, 2147483648, 4294967296, 8589934592, 17179869184, 34359738368, 68719476736, 137438953472, 274877906944, 549755813888, 1099511627776, 2199023255552, 4398046511104, 8796093022208, 17592186044416, 35184372088832, 70368744177664, 140737488355328, 281474976710656, 562949953421312, 1125899906842624, 2251799813685248, 4503599627370496, 9007199254740992, 18014398509481984, 36028797018963968, 72057594037927936, 144115188075855872, 288230376151711744, 576460752303423488, 1152921504606846976, 2305843009213693952, 4611686018427387904, -9223372036854775808]
static_i = [56, 48, 40, 32, 24, 16, 8, 0, 57, 49, 41, 33, 25, 17, 9, 1, 58, 50, 42, 34, 26, 18, 10, 2, 59, 51, 43, 35, 62, 54, 46, 38, 30, 22, 14, 6, 61, 53, 45, 37, 29, 21, 13, 5, 60, 52, 44, 36, 28, 20, 12, 4, 27, 19, 11, 3]
static_e = [31, 0, 1, 2, 3, 4, -1, -1, 3, 4, 5, 6, 7, 8, -1, -1, 7, 8, 9, 10, 11, 12, -1, -1, 11, 12, 13, 14, 15, 16, -1, -1, 15, 16, 17, 18, 19, 20, -1, -1, 19, 20, 21, 22, 23, 24, -1, -1, 23, 24, 25, 26, 27, 28, -1, -1, 27, 28, 29, 30, 31, 30, -1, -1]
static_l = [0, 1048577, 3145731]
static_g = [15, 6, 19, 20, 28, 11, 27, 16, 0, 14, 22, 25, 4, 17, 30, 9, 1, 7, 23, 13, 31, 26, 2, 8, 18, 12, 29, 5, 21, 10, 3, 24]
static_f = [[14, 4, 3, 15, 2, 13, 5, 3, 13, 14, 6, 9, 11, 2, 0, 5, 4, 1, 10, 12, 15, 6, 9, 10, 1, 8, 12, 7, 8, 11, 7, 0, 0, 15, 10, 5, 14, 4, 9, 10, 7, 8, 12, 3, 13, 1, 3, 6, 15, 12, 6, 11, 2, 9, 5, 0, 4, 2, 11, 14, 1, 7, 8, 13], [15, 0, 9, 5, 6, 10, 12, 9, 8, 7, 2, 12, 3, 13, 5, 2, 1, 14, 7, 8, 11, 4, 0, 3, 14, 11, 13, 6, 4, 1, 10, 15, 3, 13, 12, 11, 15, 3, 6, 0, 4, 10, 1, 7, 8, 4, 11, 14, 13, 8, 0, 6, 2, 15, 9, 5, 7, 1, 10, 12, 14, 2, 5, 9], [10, 13, 1, 11, 6, 8, 11, 5, 9, 4, 12, 2, 15, 3, 2, 14, 0, 6, 13, 1, 3, 15, 4, 10, 14, 9, 7, 12, 5, 0, 8, 7, 13, 1, 2, 4, 3, 6, 12, 11, 0, 13, 5, 14, 6, 8, 15, 2, 7, 10, 8, 15, 4, 9, 11, 5, 9, 0, 14, 3, 10, 7, 1, 12], [7, 10, 1, 15, 0, 12, 11, 5, 14, 9, 8, 3, 9, 7, 4, 8, 13, 6, 2, 1, 6, 11, 12, 2, 3, 0, 5, 14, 10, 13, 15, 4, 13, 3, 4, 9, 6, 10, 1, 12, 11, 0, 2, 5, 0, 13, 14, 2, 8, 15, 7, 4, 15, 1, 10, 7, 5, 6, 12, 11, 3, 8, 9, 14], [2, 4, 8, 15, 7, 10, 13, 6, 4, 1, 3, 12, 11, 7, 14, 0, 12, 2, 5, 9, 10, 13, 0, 3, 1, 11, 15, 5, 6, 8, 9, 14, 14, 11, 5, 6, 4, 1, 3, 10, 2, 12, 15, 0, 13, 2, 8, 5, 11, 8, 0, 15, 7, 14, 9, 4, 12, 7, 10, 9, 1, 13, 6, 3], [12, 9, 0, 7, 9, 2, 14, 1, 10, 15, 3, 4, 6, 12, 5, 11, 1, 14, 13, 0, 2, 8, 7, 13, 15, 5, 4, 10, 8, 3, 11, 6, 10, 4, 6, 11, 7, 9, 0, 6, 4, 2, 13, 1, 9, 15, 3, 8, 15, 3, 1, 14, 12, 5, 11, 0, 2, 12, 14, 7, 5, 10, 8, 13], [4, 1, 3, 10, 15, 12, 5, 0, 2, 11, 9, 6, 8, 7, 6, 9, 11, 4, 12, 15, 0, 3, 10, 5, 14, 13, 7, 8, 13, 14, 1, 2, 13, 6, 14, 9, 4, 1, 2, 14, 11, 13, 5, 0, 1, 10, 8, 3, 0, 11, 3, 5, 9, 4, 15, 2, 7, 8, 12, 15, 10, 7, 6, 12], [13, 7, 10, 0, 6, 9, 5, 15, 8, 4, 3, 10, 11, 14, 12, 5, 2, 11, 9, 6, 15, 12, 0, 3, 4, 1, 14, 13, 1, 2, 7, 8, 1, 2, 12, 15, 10, 4, 0, 3, 13, 14, 6, 9, 7, 8, 9, 6, 15, 1, 5, 12, 3, 10, 14, 5, 8, 7, 11, 0, 4, 13, 2, 11]]
static_h = [39, 7, 47, 15, 55, 23, 63, 31, 38, 6, 46, 14, 54, 22, 62, 30, 37, 5, 45, 13, 53, 21, 61, 29, 36, 4, 44, 12, 52, 20, 60, 28, 35, 3, 43, 11, 51, 19, 59, 27, 34, 2, 42, 10, 50, 18, 58, 26, 33, 1, 41, 9, 49, 17, 57, 25, 32, 0, 40, 8, 48, 16, 56, 24]
static_d = [57, 49, 41, 33, 25, 17, 9, 1, 59, 51, 43, 35, 27, 19, 11, 3, 61, 53, 45, 37, 29, 21, 13, 5, 63, 55, 47, 39, 31, 23, 15, 7, 56, 48, 40, 32, 24, 16, 8, 0, 58, 50, 42, 34, 26, 18, 10, 2, 60, 52, 44, 36, 28, 20, 12, 4, 62, 54, 46, 38, 30, 22, 14, 6]
static_k = [1, 1, 2, 2, 2, 2, 2, 2, 1, 2, 2, 2, 2, 2, 2, 1]
static_j = [13, 16, 10, 23, 0, 4, -1, -1, 2, 27, 14, 5, 20, 9, -1, -1, 22, 18, 11, 3, 25, 7, -1, -1, 15, 6, 26, 19, 12, 1, -1, -1, 40, 51, 30, 36, 46, 54, -1, -1, 29, 39, 50, 44, 32, 47, -1, -1, 43, 48, 38, 55, 33, 52, -1, -1, 45, 41, 49, 35, 28, 31, -1, -1]

def func_a1(iArr, i2, j2):
    j3 = 0
    for i3 in range(i2):
        if iArr[i3] >= 0:
            jArr = static_c
            if (jArr[iArr[i3]] & j2) != 0:
                j3 |= jArr[i3]
    return j3

def func_a2(j2, jArr, i2):
    a2 = func_a1(static_i, 56, j2)
    for i3 in range(16):
        jArr2 = static_l
        iArr = static_k
        a2 = ((a2 & ~jArr2[iArr[i3]]) >> iArr[i3]) | ((jArr2[iArr[i3]] & a2) << (28 - iArr[i3]))
        jArr[i3] = func_a1(static_j, 64, a2)
    if i2 == 1:
        for i4 in range(8):
            j3 = jArr[i4]
            i5 = 15 - i4
            jArr[i4] = jArr[i5]
            jArr[i5] = j3

def func_a3(jArr, j2):
    p = [0] * 2
    q = [0] * 8
    m = func_a1(static_d, 64, j2)
    iArr = p
    j3 = m
    iArr[0] = int(j3 & 4294967295)
    iArr[1] = int((j3 & -4294967296) >> 32)
    for i2 in range(16):
        o = iArr[1]
        o = func_a1(static_e, 64, o)
        o ^= jArr[i2]
        for i3 in range(8):
            q[i3] = int((o >> (i3 * 8)) & 255)
        r = 0
        i4 = 7
        while True:
            t = i4
            i5 = t
            if i5 >= 0:
                i6 = r
                i6 <<= 4
                if i6 > 2147483647:
                    i6 = -4294967296 + i6
                i6 |= static_f[i5][q[i5]]
                r = i6
                i4 = i5 - 1
            else:
                break
        o = r
        o = func_a1(static_g, 32, o)
        iArr2 = p
        n = iArr2[0]
        iArr2[0] = iArr2[1]
        xor_val = n ^ o
        if -2147483648 < xor_val < 2147483647:
            iArr2[1] = int(xor_val)
            continue
        if xor_val >= 2147483647:
            iArr2[1] = xor_val - 4294967296
        else:
            iArr2[1] = xor_val + 4294967296
    iArr3 = p
    s = iArr3[0]
    iArr3[0] = iArr3[1]
    iArr3[1] = s
    m = ((iArr3[1] << 32) & -4294967296) | (4294967295 & iArr3[0])
    m = func_a1(static_h, 64, m)
    return m

def generate_q(bArr, bArr2):
    length = len(bArr)
    jArr = [0] * 16
    j2 = 0
    j3 = 0
    for i3 in range(8):
        j3 |= bArr2[i3] << (i3 * 8)
    func_a2(j3, jArr, 0)
    i4 = length // 8
    jArr2 = [0] * i4
    for i5 in range(i4):
        for i6 in range(8):
            jArr2[i5] = jArr2[i5] | ((bArr[i5 * 8 + i6] & 255) << (i6 * 8))
    jArr3 = [0] * (((i4 + 1) * 8 + 1) // 8)
    for i7 in range(i4):
        jArr3[i7] = func_a3(jArr, jArr2[i7])
    i8 = length % 8
    i9 = i4 * 8
    i10 = length - i9
    r12 = [None] * i10
    r12[0:i10] = bArr[i9:i9 + i10]
    for i11 in range(i8):
        j2 |= (r12[i11] & 255) << (i11 * 8)
    jArr3[i4] = func_a3(jArr, j2)
    bArr3 = [None] * (len(jArr3) * 8)
    i12 = 0
    i13 = 0
    while i12 < len(jArr3):
        i14 = i13
        for i15 in range(8):
            bArr3[i14] = 255 & (jArr3[i12] >> (i15 * 8))
            i14 += 1
        i12 += 1
        i13 = i14
    return base64.b64encode(bytearray(bArr3)).decode()

def create_sx():
    timestamp = int(time.time() * 1000)
    combined_string = str(timestamp) + '12345678'
    result = combined_string[:8]
    return result

def encrypt_devid(dev_id):
    padded_id = dev_id.ljust(16, '0')[:16]
    return base64.b64encode(padded_id.encode()).decode()

def get_q(username, password):
    dev_id = ''.join([random.choice(string.digits) for _ in range(10)])
    dev_name = '安卓设备'
    devType = 'arr'
    data = f"username={quote(username)}&password={quote(base64.b64encode(password.encode()).decode())}&dev_id={dev_id}&user={str(uuid.uuid4()).replace('-', '')}&dev_name={quote(dev_name)}&urlencode=0&src=kwplayer_ar11.1.4.1_40.apk&devResolution=720*1080&&from=android&devType={devType}&sx={create_sx()}&version=11.1.4.1"
    q_value = generate_q(data.encode('UTF-8'), 'kwks&@69'.encode('UTF-8'))
    encrypted_dev_id = encrypt_devid(dev_id)
    return q_value, encrypted_dev_id

def encrypt_phone(phone):
    key = b'ysiVkLJHHnvMWCHq'
    iv = b'ichYooX+Mb1gRetP'
    if isinstance(phone, str):
        phone = phone.encode('utf-8')
    cipher = AES.new(key, AES.MODE_CBC, iv)
    padded_plaintext = pad(phone, AES.block_size)
    ciphertext = cipher.encrypt(padded_plaintext)
    ciphertext_base64 = base64.b64encode(ciphertext).decode('utf-8')
    return ciphertext_base64

def login_kuwo(username, password):
    try:
        q, encrypted_dev_id = get_q(username, password)
        url = 'http://ar.i.kuwo.cn/US_NEW/kuwo/login_kw'
        headers = {
            'User-Agent': 'Dalvik/2.1.0 (Linux; U; Android 10; MI 8 MIUI/V12.5.2.0.QEACNXM)',
            'Accept': '*/*',
            'Host': 'ar.i.kuwo.cn',
            'Connection': 'Keep-Alive',
            'Accept-Encoding': 'gzip',
        }
        params = {'f': 'ar', 'q': q}
        response = requests.get(url, headers=headers, params=params, timeout=10)
        set_cookie = response.headers.get('Set-Cookie', '')
        username_match = re.search(r'uname3=([^;]+)', set_cookie)
        sid_match = re.search(r'websid=([^;]+)', set_cookie)
        uid_match = re.search(r'userid=([^;]+)', set_cookie)
        account_match = re.search(r't3kwid=([^;]+)', set_cookie)
        if all([username_match, sid_match, uid_match, account_match]):
            loginUid = uid_match.group(1)
            loginSid = sid_match.group(1)
            appUid = account_match.group(1)
            return loginUid, loginSid, appUid, encrypted_dev_id
        return None
    except Exception as e:
        logger.error(f"酷我登录异常: {e}")
        return None

def check_withdraw_today(loginUid, loginSid):
    url = 'https://integralapi.kuwo.cn/api/v1/online/sign/v1/withdrawDetails'
    params = {
        'loginUid': loginUid,
        'loginSid': loginSid,
        'pn': 1,
        'rn': 10,
    }
    headers = {
        'Host': 'integralapi.kuwo.cn',
        'Accept': 'application/json, text/plain, */*',
        'Origin': 'https://h5app.kuwo.cn',
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 KWMusic/12.1.2.0 DeviceModel/iPhone18,3 NetType/WIFI kuwopage',
        'Referer': 'https://h5app.kuwo.cn/apps/earning-sign/bill.html?random=1783815372333&kwflag=2758068154_1783815205',
        'Accept-Language': 'zh-CN,zh-Hans;q=0.9',
        'Connection': 'keep-alive',
    }
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=5, verify=False)
        if resp.status_code != 200:
            return False
        data = resp.json()
        if data.get('code') != 200:
            return False
        records = data.get('data', {}).get('list', [])
        today_str = datetime.now().strftime('%Y-%m-%d')
        for item in records:
            create_time = item.get('createTime', '')
            if create_time.startswith(today_str):
                if item.get('status') == 1 or '提现成功' in item.get('description', ''):
                    return True
        return False
    except Exception:
        return False

def send_code_once(loginUid, loginSid, appUid, encrypted_phone, quota_id='60004'):
    url = 'https://integralapi.kuwo.cn/api/v1/online/sign/v1/withdraw/sendCode'
    params = {
        'loginUid': loginUid,
        'loginSid': loginSid,
        'mobile': encrypted_phone,
        'appuid': appUid,
        'apiv': '9',
        'terminal': '1',
        'quotaId': quota_id,
        'type': 'blindBox',
    }
    headers = {
        'Host': 'integralapi.kuwo.cn',
        'Connection': 'keep-alive',
        'Accept': 'application/json, text/plain, */*',
        'User-Agent': 'Mozilla/5.0 (Linux; Android 13; MEIZU 18 Pro Build/TKQ1.221114.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/89.0.4389.72 MQQBrowser/6.2 TBS/046295 Mobile Safari/537.36/ kuwopage',
        'Origin': 'https://h5app.kuwo.cn',
        'X-Requested-With': 'cn.kuwo.player',
        'Sec-Fetch-Site': 'same-site',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Dest': 'empty',
        'Referer': 'https://h5app.kuwo.cn/',
        'Accept-Encoding': 'gzip, deflate, br',
        'Accept-Language': 'zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7',
    }
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=5, verify=False)
        text = resp.text
        try:
            data = resp.json()
            msg = data.get('msg', '')
            desc = data.get('data', {}).get('description', '')
            combined = f"{msg}|{desc}"
        except:
            combined = text
        lower_text = (text + str(data.get('msg', '')) + str(data.get('data', {}).get('description', ''))).lower()
        success = '发送成功' in lower_text
        return success, combined
    except Exception as e:
        return False, str(e)


class KuwoManagerPlugin(Star):
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
        self.code_env_name = "CODE"
        admin_str = config.get("admin_qq", "").strip()
        self.admin_qqs = [qq.strip() for qq in admin_str.split(',') if qq.strip()]
        self.data_dir = os.path.join(os.getcwd(), "data", "kuwo_data")
        self.cache_file = os.path.join(self.data_dir, "user_data.json")
        os.makedirs(self.data_dir, exist_ok=True)
        self.cache = self._load_cache()
        self.state_info = {}
        self.TIMEOUT = 120
        self.timeout_tasks = {}

        # ---------- 缓存 ----------
        self._envs_cache = None
        self._envs_cache_time = 0
        self._envs_cache_ttl = 600
        self._kwtx_cache = None
        self._kwtx_cache_time = 0
        self._kwtx_cache_ttl = 600
        self._code_cache = None
        self._code_cache_time = 0
        self._code_cache_ttl = 600
        self._code_env_id = None

        # 后台任务跟踪
        self._update_tasks = {}

        asyncio.create_task(self._preload())
        logger.info("✅ 酷我插件（异步更新优化版）已加载")

    async def _preload(self):
        try:
            await self._get_all_env_entries()
            await self._get_code_env_value()
            logger.info("✅ 预加载完成")
        except Exception as e:
            logger.warning(f"预加载失败: {e}")

    async def _log_time(self, operation: str, start: float):
        elapsed = (time.time() - start) * 1000
        logger.info(f"⏱️ {operation} 耗时: {elapsed:.1f}ms")

    def _log_sync_time(self, operation: str, start: float):
        elapsed = (time.time() - start) * 1000
        logger.info(f"⏱️ {operation} 耗时: {elapsed:.1f}ms")

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

    async def _get_token(self):
        start = time.time()
        if self.token and self.token_expiry > time.time():
            await self._log_time("获取Token（缓存）", start)
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
                await self._log_time("获取Token（网络）", start)
                return token

    async def _call_api(self, endpoint: str, method: str = "POST", data: dict = None):
        start = time.time()
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
                    result = await resp.json()
                    await self._log_time(f"API调用 {endpoint}", start)
                    return result
                except:
                    await self._log_time(f"API调用 {endpoint}（异常）", start)
                    return {"error": f"HTTP {resp.status}", "detail": await resp.text()}

    async def _fetch_env_list(self):
        start = time.time()
        now = time.time()
        if self._envs_cache is not None and (now - self._envs_cache_time) < self._envs_cache_ttl:
            await self._log_time("获取环境变量列表（缓存命中）", start)
            return self._envs_cache
        result = await self._call_api("envs?page=1&page_size=100", method="GET")
        data = result.get("data", [])
        self._envs_cache = data
        self._envs_cache_time = now
        await self._log_time("获取环境变量列表（网络）", start)
        return data

    async def _get_env_id_by_name(self, env_name: str) -> int:
        envs = await self._fetch_env_list()
        for env in envs:
            if env.get("name") == env_name:
                return env.get("id")
        return None

    async def _update_env_value(self, env_name: str, new_value: str, env_id: int = None) -> bool:
        start = time.time()
        if env_id is None:
            env_id = await self._get_env_id_by_name(env_name)
        if env_id is None:
            payload = {"name": env_name, "value": new_value, "group": "默认分组"}
            result = await self._call_api("envs", method="POST", data=payload)
            self._envs_cache = None
            self._envs_cache_time = 0
        else:
            payload = {"name": env_name, "value": new_value}
            result = await self._call_api(f"envs/{env_id}", method="PUT", data=payload)
        if env_name == self.code_env_name:
            self._code_cache = None
            self._code_cache_time = 0
            if env_id is None and result.get("data") and result["data"].get("id"):
                self._code_env_id = result["data"]["id"]
        await self._log_time(f"更新环境变量 {env_name}", start)
        return result.get("code") in [0, None, ""] and not result.get("error")

    async def _get_all_env_entries(self) -> list:
        start = time.time()
        now = time.time()
        if self._kwtx_cache is not None and (now - self._kwtx_cache_time) < self._kwtx_cache_ttl:
            await self._log_time("读取kwtx（缓存命中）", start)
            return self._kwtx_cache
        envs = await self._fetch_env_list()
        value = ""
        for env in envs:
            if env.get("name") == self.env_name:
                value = env.get("value", "")
                break
        if not value:
            entries = []
        else:
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
                    auth_count = None
                    if len(parts) >= 3 and parts[2].strip():
                        try:
                            auth_count = int(parts[2].strip())
                        except:
                            auth_count = None
                    entries.append({"phone": phone, "password": password, "auth_count": auth_count})
        self._kwtx_cache = entries
        self._kwtx_cache_time = now
        await self._log_time("读取kwtx（缓存未命中，网络）", start)
        return entries

    async def _save_all_env_entries(self, entries: list) -> bool:
        start = time.time()
        if not entries:
            new_value = ""
        else:
            lines = []
            for e in entries:
                if e["auth_count"] is None:
                    lines.append(f"{e['phone']}#{e['password']}")
                else:
                    lines.append(f"{e['phone']}#{e['password']}#{e['auth_count']}")
            new_value = '\n'.join(lines)
        env_id = await self._get_env_id_by_name(self.env_name)
        result = await self._update_env_value(self.env_name, new_value, env_id)
        if result:
            self._kwtx_cache = entries
            self._kwtx_cache_time = time.time()
        await self._log_time("保存kwtx", start)
        return result

    async def _get_code_env_value(self) -> str:
        start = time.time()
        now = time.time()
        if self._code_cache is not None and (now - self._code_cache_time) < self._code_cache_ttl:
            await self._log_time("读取CODE（缓存命中）", start)
            return self._code_cache
        envs = await self._fetch_env_list()
        value = ""
        code_id = None
        for env in envs:
            if env.get("name") == self.code_env_name:
                value = env.get("value", "")
                code_id = env.get("id")
                break
        if code_id is not None:
            self._code_env_id = code_id
        self._code_cache = value
        self._code_cache_time = now
        await self._log_time("读取CODE（缓存未命中，网络）", start)
        return value

    async def _update_code_env(self, phone: str, code: str, umo: str) -> bool:
        if phone in self._update_tasks:
            self._update_tasks[phone].cancel()
        task = asyncio.create_task(self._async_update_code(phone, code, umo))
        self._update_tasks[phone] = task
        return True

    async def _async_update_code(self, phone: str, code: str, umo: str):
        try:
            start = time.time()
            current = await self._get_code_env_value()
            lines = current.split('\n') if current else []
            lines = [line.strip() for line in lines if line.strip()]
            found = False
            new_lines = []
            for line in lines:
                if '#' in line:
                    p, c = line.split('#', 1)
                    if p.strip() == phone:
                        new_lines.append(f"{phone}#{code}")
                        found = True
                    else:
                        new_lines.append(line)
                else:
                    new_lines.append(line)
            if not found:
                new_lines.append(f"{phone}#{code}")
            new_value = '\n'.join(new_lines)
            result = await self._update_env_value(self.code_env_name, new_value, self._code_env_id)
            if not result and self._code_env_id is not None:
                self._code_env_id = None
                result = await self._update_env_value(self.code_env_name, new_value, None)
            chain = MessageChain().message(f"✅ 验证码已提交：手机号 {phone} -> {code}" if result else f"❌ 验证码提交失败：手机号 {phone}")
            await self.context.send_message(umo, chain)
            await self._log_time(f"后台更新CODE（{phone}）", start)
        except asyncio.CancelledError:
            logger.info(f"后台更新任务被取消: {phone}")
        except Exception as e:
            logger.error(f"后台更新异常: {e}")
            try:
                chain = MessageChain().message(f"❌ 验证码提交异常：{phone} - {str(e)}")
                await self.context.send_message(umo, chain)
            except:
                pass

    async def _get_my_accounts(self, user_id: str) -> list:
        return self._get_cache_user(user_id)["accounts"]

    async def _get_my_env_entries(self, user_id: str) -> list:
        all_entries = await self._get_all_env_entries()
        my_phones = [acc["phone"] for acc in await self._get_my_accounts(user_id)]
        return [entry for entry in all_entries if entry["phone"] in my_phones]

    async def _get_user_total_auth(self, user_id: str) -> tuple:
        my_entries = await self._get_my_env_entries(user_id)
        total = 0
        has_unlimited = False
        for entry in my_entries:
            if entry["auth_count"] is None:
                has_unlimited = True
            else:
                total += entry["auth_count"]
        return total, has_unlimited

    def _is_phone_owned_by_other(self, user_id: str, phone: str) -> bool:
        for qq, data in self.cache.items():
            if qq == user_id:
                continue
            for acc in data["accounts"]:
                if acc["phone"] == phone:
                    return True
        return False

    async def _reset_user_data(self, user_id: str) -> bool:
        start = time.time()
        cache_user = self._get_cache_user(user_id)
        phones = [acc["phone"] for acc in cache_user["accounts"]]
        self.cache[user_id] = {"accounts": []}
        self._save_cache()
        if phones:
            env_entries = await self._get_all_env_entries()
            env_entries = [e for e in env_entries if e["phone"] not in phones]
            await self._save_all_env_entries(env_entries)
        await self._log_time("重置用户数据", start)
        return True

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
            return str(event.get_session_id())
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

    def _get_state_info(self, user_id: str) -> dict:
        now = time.time()
        if user_id not in self.state_info:
            self.state_info[user_id] = {
                'state': 'idle',
                'last_active': now,
                'admin_mode': False,
                'tmp_data': {},
                'trigger_msg': None,
                'in_menu': False,
                'timeout_triggered': False,
                'umo': None,
            }
        return self.state_info[user_id]

    def _set_state(self, user_id: str, state: str, admin_mode: bool = False,
                   tmp_data: dict = None, trigger_msg: str = None,
                   in_menu: bool = False, umo: str = None):
        old = self.state_info.get(user_id, {})
        self.state_info[user_id] = {
            'state': state,
            'last_active': time.time(),
            'admin_mode': admin_mode,
            'tmp_data': tmp_data or {},
            'trigger_msg': trigger_msg,
            'in_menu': in_menu,
            'timeout_triggered': old.get('timeout_triggered', False),
            'umo': umo if umo is not None else old.get('umo'),
        }

    def _reset_admin_state(self, user_id: str):
        info = self._get_state_info(user_id)
        if info['state'] != 'idle':
            info['state'] = 'idle'
            info['tmp_data'] = {}
            info['trigger_msg'] = None
            info['in_menu'] = False
            info['timeout_triggered'] = False

    async def _timeout_callback(self, user_id: str):
        info = self._get_state_info(user_id)
        if info['in_menu'] or info['state'] != 'idle':
            umo = info.get('umo')
            sent = False
            if umo:
                try:
                    chain = MessageChain().message("⏰ 操作已超时，已退出交互。")
                    await self.context.send_message(umo, chain)
                    logger.info(f"✅ 已通过 UMO '{umo}' 主动发送超时提醒")
                    sent = True
                except Exception as e:
                    logger.warning(f"使用 UMO 发送超时失败: {e}")
            if not sent:
                logger.error(f"❌ 无法发送超时提醒 (user_id={user_id})")
            self._set_state(user_id, 'idle', admin_mode=False, tmp_data={}, in_menu=False)
            if user_id in self.timeout_tasks:
                del self.timeout_tasks[user_id]

    def _schedule_timeout(self, user_id: str):
        if user_id in self.timeout_tasks:
            self.timeout_tasks[user_id].cancel()
            del self.timeout_tasks[user_id]
        task = asyncio.create_task(self._timeout_after_delay(user_id))
        self.timeout_tasks[user_id] = task

    async def _timeout_after_delay(self, user_id: str):
        try:
            await asyncio.sleep(self.TIMEOUT)
            await self._timeout_callback(user_id)
        except asyncio.CancelledError:
            pass

    def _cancel_timeout(self, user_id: str):
        if user_id in self.timeout_tasks:
            self.timeout_tasks[user_id].cancel()
            del self.timeout_tasks[user_id]

    async def _send_withdraw_code(self, phones: list, quota_id: str = '60004') -> str:
        start = time.time()
        if not phones:
            return "❌ 未指定任何手机号。"
        env_entries = await self._get_all_env_entries()
        phone_to_pass = {entry['phone']: entry['password'] for entry in env_entries}
        results = []
        for phone in phones:
            phone_start = time.time()
            password = phone_to_pass.get(phone)
            if not password:
                results.append(f"❌ {phone}: 未在环境变量中找到密码，跳过。")
                continue
            login_result = login_kuwo(phone, password)
            if not login_result:
                results.append(f"❌ {phone}: 登录失败")
                continue
            loginUid, loginSid, appUid, _ = login_result
            encrypted_phone = encrypt_phone(phone)
            if check_withdraw_today(loginUid, loginSid):
                results.append(f"⏭️  {phone}: 今日已提现，跳过发送")
                continue
            success, msg = send_code_once(loginUid, loginSid, appUid, encrypted_phone, quota_id)
            if success:
                results.append(f"✅ {phone}: 验证码发送成功")
            else:
                results.append(f"❌ {phone}: 发送失败 ({msg})")
            self._log_sync_time(f"发送验证码 {phone}", phone_start)
        await self._log_time("发送验证码（全部）", start)
        return "\n".join(results)

    def _sync_send_codes(self, phones):
        quota_id = os.getenv('QUOTA_ID', '60004')
        return asyncio.run(self._send_withdraw_code(phones, quota_id))

    async def _get_menu_text(self, user_id: str) -> str:
        start = time.time()
        my_acc = await self._get_my_accounts(user_id)
        count = len(my_acc)
        total, has_unlimited = await self._get_user_total_auth(user_id)
        if has_unlimited:
            total_display = "不限"
        else:
            total_display = str(total)
        await self._log_time("生成菜单文本", start)
        return (f"=====酷我=====\n账号{count}个，可用次数{total_display}\n[1] 提交账号\n[2] 删除账号\n[3] 查询授权次数明细\n[4] 发送验证码\n[5] 提交验证码\n[r] 重置我的所有数据\n[q] 退出")

    async def _get_admin_menu_text(self) -> str:
        return ("=====管理面板=====\n[1] 查看所有绑定关系\n[2] 查看所有环境变量账号\n[3] 绑定账号（为QQ绑定手机号）\n[4] 解除绑定（从QQ移除绑定，保留环境变量）\n[5] 删除账号（从所有绑定和环境变量移除）\n[6] 修改授权次数（设置具体值或无限制）\n[7] 提现审核（扣减授权次数）\n[8] 重置用户所有数据\n[9] 发送验证码（全部账号）\n[q] 退出")

    @filter.regex(r'^[qQ]$')
    async def handle_global_q(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        info = self._get_state_info(user_id)
        if info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 您上次操作已超时，已自动退出。请重新输入命令。")
            info['timeout_triggered'] = False
            info['state'] = 'idle'
            info['tmp_data'] = {}
            info['trigger_msg'] = None
            info['in_menu'] = False
            info['admin_mode'] = False
            self._cancel_timeout(user_id)
            return
        current_state = info['state']
        admin_mode = info.get('admin_mode', False)
        in_menu = info.get('in_menu', False)
        if current_state == 'menu_idle' and in_menu:
            yield event.plain_result("👋 已退出菜单")
            self._set_state(user_id, 'idle', admin_mode=False, in_menu=False)
            self._cancel_timeout(user_id)
            return
        if current_state == 'admin_menu_idle' and in_menu and admin_mode:
            yield event.plain_result("👋 已退出管理面板")
            self._set_state(user_id, 'idle', admin_mode=False, in_menu=False)
            self._cancel_timeout(user_id)
            return
        if in_menu and current_state not in ['idle', 'menu_idle', 'admin_menu_idle']:
            if admin_mode:
                yield event.plain_result("👋 已取消操作，返回管理面板")
                umo = event.unified_msg_origin
                self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, umo=umo)
                self._schedule_timeout(user_id)
                menu = await self._get_admin_menu_text()
                yield event.plain_result(menu)
            else:
                yield event.plain_result("👋 已取消操作，返回菜单")
                umo = event.unified_msg_origin
                self._set_state(user_id, 'menu_idle', admin_mode=False, in_menu=True, umo=umo)
                self._schedule_timeout(user_id)
                menu = await self._get_menu_text(user_id)
                yield event.plain_result(menu)
            return

    @filter.command("酷我")
    async def kuwo_menu(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        info = self._get_state_info(user_id)
        if info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 您上次操作已超时，已自动退出。请重新输入命令。")
            info['timeout_triggered'] = False
            info['state'] = 'idle'
            info['tmp_data'] = {}
            info['trigger_msg'] = None
            info['in_menu'] = False
            info['admin_mode'] = False
            self._cancel_timeout(user_id)
            return
        if info.get('admin_mode', False):
            yield event.plain_result("👋 已退出管理面板")
            self._set_state(user_id, 'idle', admin_mode=False, in_menu=False)
            self._cancel_timeout(user_id)
        self._reset_admin_state(user_id)
        umo = event.unified_msg_origin
        self._set_state(user_id, 'menu_idle', admin_mode=False, in_menu=True, umo=umo)
        self._schedule_timeout(user_id)
        menu = await self._get_menu_text(user_id)
        yield event.plain_result(menu)

    @filter.regex(r'^[1-5rR]$')
    async def handle_menu_choice(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        info = self._get_state_info(user_id)
        if info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 您上次操作已超时，已自动退出。请重新输入命令。")
            info['timeout_triggered'] = False
            info['state'] = 'idle'
            info['tmp_data'] = {}
            info['trigger_msg'] = None
            info['in_menu'] = False
            info['admin_mode'] = False
            self._cancel_timeout(user_id)
            return
        if info.get('admin_mode', False):
            return
        if not info.get('in_menu', False) or info['state'] != 'menu_idle':
            return
        text = self._get_text(event).lower()
        umo = event.unified_msg_origin
        if text == '1':
            self._set_state(user_id, 'waiting_phone', admin_mode=False, in_menu=True, umo=umo)
            self._schedule_timeout(user_id)
            yield event.plain_result("请输入手机号#密码（例如：13800138000#mypassword）（发送 q 取消）")
        elif text == '2':
            my_acc = await self._get_my_accounts(user_id)
            if not my_acc:
                yield event.plain_result("❌ 您没有绑定任何账号")
            else:
                lines = [f"{idx+1}. {acc['phone']}" for idx, acc in enumerate(my_acc)]
                prompt = "您的账号：\n" + "\n".join(lines) + "\n请输入要删除的序号（如 1）（发送 q 取消）："
                yield event.plain_result(prompt)
                self._set_state(user_id, 'waiting_delete', admin_mode=False, trigger_msg=text, in_menu=True, umo=umo)
                self._schedule_timeout(user_id)
        elif text == '3':
            my_env_entries = await self._get_my_env_entries(user_id)
            if not my_env_entries:
                yield event.plain_result("📭 您当前没有绑定任何账号，或账号尚未同步到环境变量。")
            else:
                msg = "📋 您的账号授权次数明细：\n"
                total = 0
                has_unlimited = False
                for entry in my_env_entries:
                    auth_display = "无限制" if entry["auth_count"] is None else str(entry["auth_count"])
                    msg += f"手机号：{entry['phone']} ｜ 授权次数：{auth_display}\n"
                    if entry["auth_count"] is not None:
                        total += entry["auth_count"]
                    else:
                        has_unlimited = True
                if has_unlimited:
                    msg += f"合计：存在无限制账号，总可用次数不限"
                else:
                    msg += f"合计可用次数：{total}"
                yield event.plain_result(msg)
            self._set_state(user_id, 'menu_idle', admin_mode=False, in_menu=True, umo=umo)
            self._schedule_timeout(user_id)
            menu = await self._get_menu_text(user_id)
            yield event.plain_result(menu)
        elif text == '4':
            my_acc = await self._get_my_accounts(user_id)
            if not my_acc:
                yield event.plain_result("❌ 您没有绑定任何账号，无法发送验证码。")
                self._set_state(user_id, 'menu_idle', admin_mode=False, in_menu=True, umo=umo)
                self._schedule_timeout(user_id)
                menu = await self._get_menu_text(user_id)
                yield event.plain_result(menu)
                return
            lines = [f"{idx+1}. {acc['phone']}" for idx, acc in enumerate(my_acc)]
            prompt = "选择要发送验证码的账号序号（可多选，用逗号分隔，如 1,3），或输入 all 发送全部：\n" + "\n".join(lines) + "\n（发送 q 取消）："
            yield event.plain_result(prompt)
            self._set_state(user_id, 'waiting_send_select', admin_mode=False, tmp_data={'all_phones': [acc['phone'] for acc in my_acc]}, in_menu=True, umo=umo, trigger_msg=text)
            self._schedule_timeout(user_id)
        elif text == '5':
            my_acc = await self._get_my_accounts(user_id)
            if not my_acc:
                yield event.plain_result("❌ 您没有绑定任何账号，请先提交账号")
                self._set_state(user_id, 'menu_idle', admin_mode=False, in_menu=True, umo=umo)
                self._schedule_timeout(user_id)
                menu = await self._get_menu_text(user_id)
                yield event.plain_result(menu)
                return
            lines = [f"{idx+1}. {acc['phone']}" for idx, acc in enumerate(my_acc)]
            prompt = "请选择要提交验证码的账号序号：\n" + "\n".join(lines) + "\n请输入序号（发送 q 取消）："
            yield event.plain_result(prompt)
            self._set_state(user_id, 'waiting_code_phone', admin_mode=False, trigger_msg=text, in_menu=True, umo=umo)
            self._schedule_timeout(user_id)
        elif text == 'r':
            await self._reset_user_data(user_id)
            yield event.plain_result("✅ 您的所有数据已重置")
            self._set_state(user_id, 'menu_idle', admin_mode=False, in_menu=True, umo=umo)
            self._schedule_timeout(user_id)
            menu = await self._get_menu_text(user_id)
            yield event.plain_result(menu)

    @filter.regex(r'^.+$')
    async def handle_send_selection(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        info = self._get_state_info(user_id)
        if info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 您上次操作已超时，已自动退出。请重新输入命令。")
            info['timeout_triggered'] = False
            info['state'] = 'idle'
            info['tmp_data'] = {}
            info['trigger_msg'] = None
            info['in_menu'] = False
            info['admin_mode'] = False
            self._cancel_timeout(user_id)
            return
        if info['state'] != 'waiting_send_select' or not info.get('in_menu', False):
            return
        text = self._get_text(event).strip().lower()
        all_phones = info.get('tmp_data', {}).get('all_phones', [])
        umo = info.get('umo')
        if text == info.get('trigger_msg'):
            return
        if text in ['q', 'x', '取消', 'back', '-1', '返回']:
            yield event.plain_result("👋 已返回菜单。")
            self._set_state(user_id, 'menu_idle', admin_mode=False, in_menu=True, umo=umo)
            self._schedule_timeout(user_id)
            menu = await self._get_menu_text(user_id)
            yield event.plain_result(menu)
            return
        if text == 'all' or text == '0':
            phones = all_phones
        else:
            try:
                indices = [int(x.strip()) for x in text.split(',') if x.strip().isdigit()]
            except ValueError:
                yield event.plain_result("❌ 输入格式错误，请使用逗号分隔数字（如 1,3）。")
                lines = [f"{idx+1}. {phone}" for idx, phone in enumerate(all_phones)]
                prompt = "选择要发送验证码的账号序号（可多选，用逗号分隔，如 1,3），输入 0/all 发送全部：\n" + "\n".join(lines) + "\n（输入 -1/back/q/取消 返回菜单）："
                yield event.plain_result(prompt)
                return
            phones = []
            invalid_indices = []
            for idx in indices:
                if 1 <= idx <= len(all_phones):
                    phones.append(all_phones[idx-1])
                else:
                    invalid_indices.append(str(idx))
            if invalid_indices:
                yield event.plain_result(f"❌ 序号 {', '.join(invalid_indices)} 无效，有效范围 1-{len(all_phones)}。")
                lines = [f"{idx+1}. {phone}" for idx, phone in enumerate(all_phones)]
                prompt = "选择要发送验证码的账号序号（可多选，用逗号分隔，如 1,3），输入 0/all 发送全部：\n" + "\n".join(lines) + "\n（输入 -1/back/q/取消 返回菜单）："
                yield event.plain_result(prompt)
                return
            if not phones:
                yield event.plain_result("❌ 未选择任何账号。")
                self._set_state(user_id, 'menu_idle', admin_mode=False, in_menu=True, umo=umo)
                self._schedule_timeout(user_id)
                menu = await self._get_menu_text(user_id)
                yield event.plain_result(menu)
                return
        try:
            result = await asyncio.to_thread(self._sync_send_codes, phones)
            yield event.plain_result(result)
        except Exception as e:
            yield event.plain_result(f"❌ 发送异常: {e}")
        self._set_state(user_id, 'menu_idle', admin_mode=False, in_menu=True, umo=umo)
        self._schedule_timeout(user_id)
        menu = await self._get_menu_text(user_id)
        yield event.plain_result(menu)

    @filter.regex(r'^.+$')
    async def handle_code_input(self, event: AstrMessageEvent):
        overall_start = time.time()
        user_id = self._get_user_id(event)
        info = self._get_state_info(user_id)
        if info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 您上次操作已超时，已自动退出。请重新输入命令。")
            info['timeout_triggered'] = False
            info['state'] = 'idle'
            info['tmp_data'] = {}
            info['trigger_msg'] = None
            info['in_menu'] = False
            info['admin_mode'] = False
            self._cancel_timeout(user_id)
            return
        if info['state'] == 'waiting_send_select':
            return
        if info['state'] != 'waiting_code_input' or not info.get('in_menu', False):
            return
        text = self._get_text(event)
        code = text
        if not code:
            yield event.plain_result("❌ 验证码不能为空")
            return
        phone = info.get('tmp_data', {}).get('phone')
        if not phone:
            yield event.plain_result("❌ 会话错误，请重新操作")
            umo = event.unified_msg_origin
            self._set_state(user_id, 'menu_idle', admin_mode=False, in_menu=True, umo=umo)
            self._schedule_timeout(user_id)
            menu = await self._get_menu_text(user_id)
            yield event.plain_result(menu)
            return
        umo = event.unified_msg_origin
        yield event.plain_result("⏳ 正在提交验证码，请稍候...")
        await self._update_code_env(phone, code, umo)
        self._set_state(user_id, 'idle', admin_mode=False, in_menu=False)
        self._cancel_timeout(user_id)
        umo = event.unified_msg_origin
        self._set_state(user_id, 'menu_idle', admin_mode=False, in_menu=True, umo=umo)
        self._schedule_timeout(user_id)
        menu = await self._get_menu_text(user_id)
        yield event.plain_result(menu)
        await self._log_time("提交验证码（整体流程）", overall_start)

    @filter.regex(r'^\d+$')
    async def handle_code_phone_select(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        info = self._get_state_info(user_id)
        if info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 您上次操作已超时，已自动退出。请重新输入命令。")
            info['timeout_triggered'] = False
            info['state'] = 'idle'
            info['tmp_data'] = {}
            info['trigger_msg'] = None
            info['in_menu'] = False
            info['admin_mode'] = False
            self._cancel_timeout(user_id)
            return
        if info['state'] == 'waiting_send_select':
            return
        if info['state'] != 'waiting_code_phone' or not info.get('in_menu', False):
            return
        current_text = self._get_text(event)
        if info.get('trigger_msg') == current_text:
            return
        try:
            idx = int(current_text)
        except:
            yield event.plain_result("❌ 请输入有效的数字")
            return
        my_acc = await self._get_my_accounts(user_id)
        if idx < 1 or idx > len(my_acc):
            yield event.plain_result(f"❌ 序号无效，请输入 1 到 {len(my_acc)} 之间的数字")
            return
        phone = my_acc[idx-1]["phone"]
        umo = event.unified_msg_origin
        self._set_state(user_id, 'waiting_code_input', admin_mode=False, tmp_data={'phone': phone}, in_menu=True, umo=umo)
        self._schedule_timeout(user_id)
        yield event.plain_result(f"已选择账号 {phone}，请输入验证码（发送 q 取消）：")

    @filter.regex(r'^\d{11}#.+$')
    async def handle_phone_submit(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        info = self._get_state_info(user_id)
        if info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 您上次操作已超时，已自动退出。请重新输入命令。")
            info['timeout_triggered'] = False
            info['state'] = 'idle'
            info['tmp_data'] = {}
            info['trigger_msg'] = None
            info['in_menu'] = False
            info['admin_mode'] = False
            self._cancel_timeout(user_id)
            return
        if info['state'] != 'waiting_phone' or not info.get('in_menu', False):
            return
        text = self._get_text(event)
        phone, password = text.split('#', 1)
        phone = phone.strip()
        password = password.strip()
        if self._is_phone_owned_by_other(user_id, phone):
            yield event.plain_result(f"❌ 手机号 {phone} 已被其他用户绑定")
            umo = event.unified_msg_origin
            self._set_state(user_id, 'menu_idle', admin_mode=False, in_menu=True, umo=umo)
            self._schedule_timeout(user_id)
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
            env_entries.append({"phone": phone, "password": password, "auth_count": None})
            await self._save_all_env_entries(env_entries)
            yield event.plain_result(f"✅ 账号 {phone} 已保存（默认无限制）")
        umo = event.unified_msg_origin
        self._set_state(user_id, 'menu_idle', admin_mode=False, in_menu=True, umo=umo)
        self._schedule_timeout(user_id)
        menu = await self._get_menu_text(user_id)
        yield event.plain_result(menu)

    @filter.regex(r'^\d+$')
    async def handle_delete_index(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        info = self._get_state_info(user_id)
        if info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 您上次操作已超时，已自动退出。请重新输入命令。")
            info['timeout_triggered'] = False
            info['state'] = 'idle'
            info['tmp_data'] = {}
            info['trigger_msg'] = None
            info['in_menu'] = False
            info['admin_mode'] = False
            self._cancel_timeout(user_id)
            return
        if info['state'] != 'waiting_delete' or not info.get('in_menu', False):
            return
        current_text = self._get_text(event)
        if info.get('trigger_msg') == current_text:
            return
        try:
            idx = int(current_text)
        except:
            yield event.plain_result("❌ 请输入有效的数字")
            umo = event.unified_msg_origin
            self._set_state(user_id, 'menu_idle', admin_mode=False, in_menu=True, umo=umo)
            self._schedule_timeout(user_id)
            menu = await self._get_menu_text(user_id)
            yield event.plain_result(menu)
            return
        cache_user = self._get_cache_user(user_id)
        my_acc = cache_user["accounts"]
        if idx < 1 or idx > len(my_acc):
            yield event.plain_result(f"❌ 序号无效，请输入 1 到 {len(my_acc)} 之间的数字")
            umo = event.unified_msg_origin
            self._set_state(user_id, 'menu_idle', admin_mode=False, in_menu=True, umo=umo)
            self._schedule_timeout(user_id)
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
        umo = event.unified_msg_origin
        self._set_state(user_id, 'menu_idle', admin_mode=False, in_menu=True, umo=umo)
        self._schedule_timeout(user_id)
        menu = await self._get_menu_text(user_id)
        yield event.plain_result(menu)

    @filter.command("酷我管理")
    async def admin_menu(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        if user_id not in self.admin_qqs:
            yield event.plain_result("❌ 你没有权限执行此操作")
            return
        info = self._get_state_info(user_id)
        if info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 您上次操作已超时，已自动退出。请重新输入命令。")
            info['timeout_triggered'] = False
            info['state'] = 'idle'
            info['tmp_data'] = {}
            info['trigger_msg'] = None
            info['in_menu'] = False
            info['admin_mode'] = False
            self._cancel_timeout(user_id)
            return
        if info.get('admin_mode', False):
            yield event.plain_result("👋 已退出普通用户菜单")
            self._set_state(user_id, 'idle', admin_mode=False, in_menu=False)
            self._cancel_timeout(user_id)
        self._reset_admin_state(user_id)
        umo = event.unified_msg_origin
        self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, umo=umo)
        self._schedule_timeout(user_id)
        menu = await self._get_admin_menu_text()
        yield event.plain_result(menu)

    @filter.regex(r'^\d+$')
    async def handle_admin_digit(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        if user_id not in self.admin_qqs:
            return
        info = self._get_state_info(user_id)
        if info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 您上次操作已超时，已自动退出。请重新输入命令。")
            info['timeout_triggered'] = False
            info['state'] = 'idle'
            info['tmp_data'] = {}
            info['trigger_msg'] = None
            info['in_menu'] = False
            info['admin_mode'] = False
            self._cancel_timeout(user_id)
            return
        if not info.get('admin_mode', False) or not info.get('in_menu', False):
            return
        current_state = info['state']
        text = self._get_text(event)
        try:
            num = int(text)
        except:
            return
        if current_state == 'admin_delete_wait_confirm':
            return
        if current_state == 'admin_auth_wait_new_value':
            phone = info.get('tmp_data', {}).get('phone')
            if not phone:
                yield event.plain_result("❌ 会话错误，请重新操作")
                umo = event.unified_msg_origin
                self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, umo=umo)
                self._schedule_timeout(user_id)
                menu = await self._get_admin_menu_text()
                yield event.plain_result(menu)
                return
            if num < 0:
                yield event.plain_result("❌ 授权次数不能为负数")
                return
            env_entries = await self._get_all_env_entries()
            found = False
            for entry in env_entries:
                if entry["phone"] == phone:
                    entry["auth_count"] = num
                    found = True
                    break
            if not found:
                yield event.plain_result(f"❌ 手机号 {phone} 不存在于环境变量中")
                umo = event.unified_msg_origin
                self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, umo=umo)
                self._schedule_timeout(user_id)
                menu = await self._get_admin_menu_text()
                yield event.plain_result(menu)
                return
            if await self._save_all_env_entries(env_entries):
                yield event.plain_result(f"✅ 手机号 {phone} 授权次数已设置为 {num}")
            else:
                yield event.plain_result("❌ 保存失败")
            umo = event.unified_msg_origin
            self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, umo=umo)
            self._schedule_timeout(user_id)
            menu = await self._get_admin_menu_text()
            yield event.plain_result(menu)
            return
        if current_state == 'admin_menu_idle':
            umo = event.unified_msg_origin
            if num == 1:
                result = await self._admin_view_all_bindings()
                yield event.plain_result(result)
                self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, umo=umo)
                self._schedule_timeout(user_id)
                menu = await self._get_admin_menu_text()
                yield event.plain_result(menu)
            elif num == 2:
                result = await self._admin_view_all_env_accounts()
                yield event.plain_result(result)
                self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, umo=umo)
                self._schedule_timeout(user_id)
                menu = await self._get_admin_menu_text()
                yield event.plain_result(menu)
            elif num == 3:
                self._set_state(user_id, 'admin_bind_wait_phone_select', admin_mode=True, in_menu=True, tmp_data={}, umo=umo)
                self._schedule_timeout(user_id)
                async for msg in self._admin_bind_select_phone(event):
                    yield msg
            elif num == 4:
                self._set_state(user_id, 'admin_unbind_wait_select', admin_mode=True, in_menu=True, tmp_data={}, umo=umo)
                self._schedule_timeout(user_id)
                async for msg in self._admin_unbind_select(event):
                    yield msg
            elif num == 5:
                self._set_state(user_id, 'admin_delete_wait_select', admin_mode=True, in_menu=True, tmp_data={}, umo=umo)
                self._schedule_timeout(user_id)
                async for msg in self._admin_delete_select(event):
                    yield msg
            elif num == 6:
                self._set_state(user_id, 'admin_auth_wait_select', admin_mode=True, in_menu=True, tmp_data={}, umo=umo)
                self._schedule_timeout(user_id)
                async for msg in self._admin_auth_select(event):
                    yield msg
            elif num == 7:
                self._set_state(user_id, 'admin_withdraw_wait_select', admin_mode=True, in_menu=True, tmp_data={}, umo=umo)
                self._schedule_timeout(user_id)
                async for msg in self._admin_withdraw_select(event):
                    yield msg
            elif num == 8:
                self._set_state(user_id, 'admin_reset_wait_select', admin_mode=True, in_menu=True, tmp_data={}, umo=umo)
                self._schedule_timeout(user_id)
                async for msg in self._admin_reset_select(event):
                    yield msg
            elif num == 9:
                env_entries = await self._get_all_env_entries()
                if not env_entries:
                    yield event.plain_result("❌ 环境变量中没有账号。")
                    self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, umo=umo)
                    self._schedule_timeout(user_id)
                    menu = await self._get_admin_menu_text()
                    yield event.plain_result(menu)
                    return
                phones = [entry['phone'] for entry in env_entries]
                tutorial = f"📖 管理员验证码发送：将向环境变量中所有账号发送验证码（共 {len(phones)} 个）。\n确认发送？回复 y 确认，n 取消。"
                yield event.plain_result(tutorial)
                self._set_state(user_id, 'admin_wait_send_all', admin_mode=True, tmp_data={'phones': phones}, in_menu=True, umo=umo)
                self._schedule_timeout(user_id)
            else:
                yield event.plain_result("❌ 无效选项，请输入 1-9 或 q")
        else:
            umo = event.unified_msg_origin
            if current_state == 'admin_bind_wait_phone_select':
                async for msg in self._admin_bind_phone_select_handle(event):
                    yield msg
            elif current_state == 'admin_bind_wait_qq_select':
                result = await self._admin_bind_qq_select_handle(event)
                yield event.plain_result(result)
                self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, umo=umo)
                self._schedule_timeout(user_id)
                menu = await self._get_admin_menu_text()
                yield event.plain_result(menu)
            elif current_state == 'admin_bind_wait_qq_input':
                result = await self._admin_bind_qq_input_handle(event)
                yield event.plain_result(result)
                self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, umo=umo)
                self._schedule_timeout(user_id)
                menu = await self._get_admin_menu_text()
                yield event.plain_result(menu)
            elif current_state == 'admin_unbind_wait_select':
                async for msg in self._admin_unbind_select_handle(event):
                    yield msg
            elif current_state == 'admin_delete_wait_select':
                async for msg in self._admin_delete_select_handle(event):
                    yield msg
            elif current_state == 'admin_auth_wait_select':
                async for msg in self._admin_auth_select_handle(event):
                    yield msg
            elif current_state == 'admin_withdraw_wait_select':
                async for msg in self._admin_withdraw_select_handle(event):
                    yield msg
            elif current_state == 'admin_reset_wait_select':
                async for msg in self._admin_reset_select_handle(event):
                    yield msg
            elif current_state == 'admin_wait_send_all':
                if text.lower() == 'y':
                    phones = info.get('tmp_data', {}).get('phones', [])
                    if phones:
                        try:
                            result = await asyncio.to_thread(self._sync_send_codes, phones)
                            yield event.plain_result(result)
                        except Exception as e:
                            yield event.plain_result(f"❌ 发送异常: {e}")
                    else:
                        yield event.plain_result("❌ 没有可发送的账号。")
                else:
                    yield event.plain_result("❌ 已取消发送。")
                self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, umo=umo)
                self._schedule_timeout(user_id)
                menu = await self._get_admin_menu_text()
                yield event.plain_result(menu)

    @filter.regex(r'^[^0-9].*$')
    async def handle_admin_non_digit(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        if user_id not in self.admin_qqs:
            return
        info = self._get_state_info(user_id)
        if info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 您上次操作已超时，已自动退出。请重新输入命令。")
            info['timeout_triggered'] = False
            info['state'] = 'idle'
            info['tmp_data'] = {}
            info['trigger_msg'] = None
            info['in_menu'] = False
            info['admin_mode'] = False
            self._cancel_timeout(user_id)
            return
        if not info.get('admin_mode', False) or not info.get('in_menu', False):
            return
        current_state = info['state']
        text = self._get_text(event).strip()
        if current_state == 'admin_auth_wait_new_value':
            umo = event.unified_msg_origin
            if text in ['无限制', '无限', 'unlimited']:
                phone = info.get('tmp_data', {}).get('phone')
                if not phone:
                    yield event.plain_result("❌ 会话错误，请重新操作")
                    self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, umo=umo)
                    self._schedule_timeout(user_id)
                    menu = await self._get_admin_menu_text()
                    yield event.plain_result(menu)
                    return
                env_entries = await self._get_all_env_entries()
                found = False
                for entry in env_entries:
                    if entry["phone"] == phone:
                        entry["auth_count"] = None
                        found = True
                        break
                if not found:
                    yield event.plain_result(f"❌ 手机号 {phone} 不存在于环境变量中")
                    self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, umo=umo)
                    self._schedule_timeout(user_id)
                    menu = await self._get_admin_menu_text()
                    yield event.plain_result(menu)
                    return
                if await self._save_all_env_entries(env_entries):
                    yield event.plain_result(f"✅ 手机号 {phone} 已设为无限制")
                else:
                    yield event.plain_result("❌ 保存失败")
                self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, umo=umo)
                self._schedule_timeout(user_id)
                menu = await self._get_admin_menu_text()
                yield event.plain_result(menu)
            else:
                yield event.plain_result("❌ 输入无效，请输入数字或 '无限制'")
            return
        if current_state == 'admin_delete_wait_confirm':
            umo = event.unified_msg_origin
            if text.lower() == 'y':
                phone_to_del = info.get('tmp_data', {}).get('phone_to_del')
                if not phone_to_del:
                    yield event.plain_result("❌ 会话错误，请重新操作")
                else:
                    result = await self._admin_do_delete(phone_to_del)
                    yield event.plain_result(result)
                self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, umo=umo)
                self._schedule_timeout(user_id)
                menu = await self._get_admin_menu_text()
                yield event.plain_result(menu)
            elif text.lower() == 'n':
                yield event.plain_result("❌ 已取消删除操作")
                self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, umo=umo)
                self._schedule_timeout(user_id)
                menu = await self._get_admin_menu_text()
                yield event.plain_result(menu)
            else:
                yield event.plain_result("❌ 已取消删除操作")
                self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, umo=umo)
                self._schedule_timeout(user_id)
                menu = await self._get_admin_menu_text()
                yield event.plain_result(menu)

    # ---------- 管理员辅助方法 ----------
    async def _admin_view_all_bindings(self) -> str:
        if not self.cache:
            return "📭 暂无任何用户绑定数据"
        msg = "📋 所有绑定关系（手机号，密码已隐藏）\n\n"
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
            return "📭 暂无任何用户绑定数据"
        msg += f"统计：共 {total_users} 个用户，{total_accounts} 个绑定账号"
        return msg

    async def _admin_view_all_env_accounts(self) -> str:
        env_entries = await self._get_all_env_entries()
        if not env_entries:
            return "📭 环境变量中暂无任何账号"
        phone_to_qq = {}
        for qq, data in self.cache.items():
            for acc in data.get("accounts", []):
                phone_to_qq[acc["phone"]] = qq
        msg = "📋 环境变量账号列表（含未绑定QQ）\n\n"
        for entry in env_entries:
            phone = entry["phone"]
            auth_display = "无限制" if entry["auth_count"] is None else str(entry["auth_count"])
            qq = phone_to_qq.get(phone, "未绑定")
            msg += f"📱 {phone} ｜ 授权: {auth_display} ｜ 绑定QQ: {qq}\n"
        return msg

    async def _admin_bind_select_phone(self, event):
        user_id = self._get_user_id(event)
        info = self._get_state_info(user_id)
        if info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 操作已超时，已退出交互。")
            info['timeout_triggered'] = False
            info['state'] = 'idle'
            info['tmp_data'] = {}
            info['trigger_msg'] = None
            info['in_menu'] = False
            info['admin_mode'] = False
            self._cancel_timeout(user_id)
            return
        if info['state'] != 'admin_bind_wait_phone_select':
            return
        env_entries = await self._get_all_env_entries()
        if not env_entries:
            yield event.plain_result("❌ 环境变量中暂无账号，请先让用户提交账号或手动添加")
            umo = event.unified_msg_origin
            self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, umo=umo)
            self._schedule_timeout(user_id)
            menu = await self._get_admin_menu_text()
            yield event.plain_result(menu)
            return
        bound_phones = set()
        for qq, data in self.cache.items():
            for acc in data.get("accounts", []):
                bound_phones.add(acc["phone"])
        unbound_phones = [entry for entry in env_entries if entry["phone"] not in bound_phones]
        if not unbound_phones:
            yield event.plain_result("✅ 所有环境变量账号均已绑定，无需操作")
            umo = event.unified_msg_origin
            self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, umo=umo)
            self._schedule_timeout(user_id)
            menu = await self._get_admin_menu_text()
            yield event.plain_result(menu)
            return
        msg = "📋 未绑定的手机号列表：\n"
        for idx, entry in enumerate(unbound_phones, 1):
            auth_display = "无限制" if entry["auth_count"] is None else str(entry["auth_count"])
            msg += f"{idx}. {entry['phone']} ｜ 授权次数: {auth_display}\n"
        msg += "请选择要绑定的手机号序号（发送 q 取消）："
        umo = event.unified_msg_origin
        self._set_state(user_id, 'admin_bind_wait_phone_select', admin_mode=True, in_menu=True, tmp_data={'unbound_phones': unbound_phones}, umo=umo)
        self._schedule_timeout(user_id)
        yield event.plain_result(msg)

    async def _admin_bind_phone_select_handle(self, event):
        user_id = self._get_user_id(event)
        info = self._get_state_info(user_id)
        if info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 操作已超时，已退出交互。")
            info['timeout_triggered'] = False
            info['state'] = 'idle'
            info['tmp_data'] = {}
            info['trigger_msg'] = None
            info['in_menu'] = False
            info['admin_mode'] = False
            self._cancel_timeout(user_id)
            return
        if info['state'] != 'admin_bind_wait_phone_select':
            return
        current_text = self._get_text(event)
        if info.get('trigger_msg') == current_text:
            return
        try:
            idx = int(current_text)
        except:
            yield event.plain_result("❌ 请输入有效的数字")
            return
        unbound_phones = info.get('tmp_data', {}).get('unbound_phones', [])
        if idx < 1 or idx > len(unbound_phones):
            yield event.plain_result(f"❌ 序号无效，请输入 1 到 {len(unbound_phones)} 之间的数字")
            return
        selected_phone = unbound_phones[idx-1]["phone"]
        qq_list = list(self.cache.keys())
        umo = event.unified_msg_origin
        if qq_list:
            msg = "📋 可绑定的QQ列表：\n"
            for i, qq in enumerate(qq_list, 1):
                acc_count = len(self.cache[qq].get("accounts", []))
                msg += f"{i}. {qq} ｜ 账号数: {acc_count}\n"
            msg += f"请输入要绑定到该手机号的QQ序号（或直接输入新QQ号，发送 q 取消）："
            self._set_state(user_id, 'admin_bind_wait_qq_select', admin_mode=True, in_menu=True, tmp_data={'selected_phone': selected_phone, 'qq_list': qq_list}, umo=umo)
            self._schedule_timeout(user_id)
            yield event.plain_result(msg)
        else:
            self._set_state(user_id, 'admin_bind_wait_qq_input', admin_mode=True, in_menu=True, tmp_data={'selected_phone': selected_phone}, umo=umo)
            self._schedule_timeout(user_id)
            yield event.plain_result("当前无绑定记录，请输入要绑定的QQ号（发送 q 取消）：")

    async def _admin_bind_qq_select_handle(self, event) -> str:
        user_id = self._get_user_id(event)
        info = self._get_state_info(user_id)
        if info.get('timeout_triggered', False):
            return "⏰ 操作已超时，已退出交互。"
        if info['state'] != 'admin_bind_wait_qq_select':
            return "状态错误，请重新操作"
        current_text = self._get_text(event)
        tmp = info.get('tmp_data', {})
        selected_phone = tmp.get('selected_phone')
        qq_list = tmp.get('qq_list', [])
        if current_text.isdigit():
            if len(current_text) <= 5:
                idx = int(current_text)
                if 1 <= idx <= len(qq_list):
                    target_qq = qq_list[idx-1]
                else:
                    return f"❌ 序号无效，请输入 1 到 {len(qq_list)} 之间的数字，或输入6位以上新QQ号"
            else:
                target_qq = current_text
        else:
            return "❌ 请输入数字（序号或新QQ号）"
        result = await self._admin_do_bind(target_qq, selected_phone)
        umo = event.unified_msg_origin
        self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, umo=umo)
        self._schedule_timeout(user_id)
        return result

    async def _admin_bind_qq_input_handle(self, event) -> str:
        user_id = self._get_user_id(event)
        info = self._get_state_info(user_id)
        if info.get('timeout_triggered', False):
            return "⏰ 操作已超时，已退出交互。"
        if info['state'] != 'admin_bind_wait_qq_input':
            return "状态错误，请重新操作"
        current_text = self._get_text(event)
        if not current_text.isdigit():
            return "❌ QQ号须为数字"
        target_qq = current_text
        selected_phone = info.get('tmp_data', {}).get('selected_phone')
        if not selected_phone:
            return "❌ 会话错误，请重新操作"
        result = await self._admin_do_bind(target_qq, selected_phone)
        umo = event.unified_msg_origin
        self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, umo=umo)
        self._schedule_timeout(user_id)
        return result

    async def _admin_do_bind(self, target_qq: str, phone: str) -> str:
        existing_owner = None
        for qq, data in self.cache.items():
            for acc in data["accounts"]:
                if acc["phone"] == phone:
                    existing_owner = qq
                    break
            if existing_owner:
                break
        target_cache = self._get_cache_user(target_qq)
        accounts = target_cache["accounts"]
        for acc in accounts:
            if acc["phone"] == phone:
                return f"⚠️ 用户 {target_qq} 已绑定该手机号"
        password = "admin_placeholder"
        accounts.append({"phone": phone, "password": password})
        self._update_cache_user(target_qq, accounts)
        msg = f"✅ 已为用户 {target_qq} 绑定手机号 {phone}"
        if existing_owner and existing_owner != target_qq:
            msg += f"\n⚠️ 注意：该手机号原本属于用户 {existing_owner}，已被管理员强制迁移至 {target_qq}"
        return msg

    async def _admin_unbind_select(self, event):
        user_id = self._get_user_id(event)
        info = self._get_state_info(user_id)
        if info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 操作已超时，已退出交互。")
            info['timeout_triggered'] = False
            info['state'] = 'idle'
            info['tmp_data'] = {}
            info['trigger_msg'] = None
            info['in_menu'] = False
            info['admin_mode'] = False
            self._cancel_timeout(user_id)
            return
        if info['state'] != 'admin_unbind_wait_select':
            return
        env_entries = await self._get_all_env_entries()
        if not env_entries:
            yield event.plain_result("❌ 环境变量中暂无账号")
            umo = event.unified_msg_origin
            self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, umo=umo)
            self._schedule_timeout(user_id)
            menu = await self._get_admin_menu_text()
            yield event.plain_result(menu)
            return
        phone_to_qq = {}
        for qq, data in self.cache.items():
            for acc in data.get("accounts", []):
                phone_to_qq[acc["phone"]] = qq
        bound_list = []
        for entry in env_entries:
            phone = entry["phone"]
            if phone in phone_to_qq:
                bound_list.append({
                    "phone": phone,
                    "auth_count": entry["auth_count"],
                    "qq": phone_to_qq[phone]
                })
        if not bound_list:
            yield event.plain_result("✅ 没有已绑定的账号需要解除")
            umo = event.unified_msg_origin
            self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, umo=umo)
            self._schedule_timeout(user_id)
            menu = await self._get_admin_menu_text()
            yield event.plain_result(menu)
            return
        msg = "📋 已绑定的账号列表（解除绑定将保留环境变量）：\n"
        for idx, item in enumerate(bound_list, 1):
            auth_display = "无限制" if item["auth_count"] is None else str(item["auth_count"])
            msg += f"{idx}. {item['phone']} ｜ 授权: {auth_display} ｜ 绑定QQ: {item['qq']}\n"
        msg += "请输入要解除绑定的账号序号（发送 q 取消）："
        umo = event.unified_msg_origin
        self._set_state(user_id, 'admin_unbind_wait_select', admin_mode=True, in_menu=True, tmp_data={'bound_list': bound_list}, umo=umo)
        self._schedule_timeout(user_id)
        yield event.plain_result(msg)

    async def _admin_unbind_select_handle(self, event):
        user_id = self._get_user_id(event)
        info = self._get_state_info(user_id)
        if info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 操作已超时，已退出交互。")
            info['timeout_triggered'] = False
            info['state'] = 'idle'
            info['tmp_data'] = {}
            info['trigger_msg'] = None
            info['in_menu'] = False
            info['admin_mode'] = False
            self._cancel_timeout(user_id)
            return
        if info['state'] != 'admin_unbind_wait_select':
            return
        current_text = self._get_text(event)
        if info.get('trigger_msg') == current_text:
            return
        try:
            idx = int(current_text)
        except:
            yield event.plain_result("❌ 请输入有效的数字")
            return
        bound_list = info.get('tmp_data', {}).get('bound_list', [])
        if idx < 1 or idx > len(bound_list):
            yield event.plain_result(f"❌ 序号无效，请输入 1 到 {len(bound_list)} 之间的数字")
            return
        item = bound_list[idx-1]
        phone = item["phone"]
        qq = item["qq"]
        cache_user = self._get_cache_user(qq)
        accounts = cache_user["accounts"]
        new_accounts = [acc for acc in accounts if acc["phone"] != phone]
        if len(new_accounts) == len(accounts):
            yield event.plain_result(f"❌ 手机号 {phone} 不在用户 {qq} 的绑定列表中")
            umo = event.unified_msg_origin
            self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, umo=umo)
            self._schedule_timeout(user_id)
            menu = await self._get_admin_menu_text()
            yield event.plain_result(menu)
            return
        self._update_cache_user(qq, new_accounts)
        yield event.plain_result(f"✅ 已解除绑定：手机号 {phone} 从 QQ {qq} 移除（环境变量中的账号保留）")
        umo = event.unified_msg_origin
        self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, umo=umo)
        self._schedule_timeout(user_id)
        menu = await self._get_admin_menu_text()
        yield event.plain_result(menu)

    async def _admin_delete_select(self, event):
        user_id = self._get_user_id(event)
        info = self._get_state_info(user_id)
        if info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 操作已超时，已退出交互。")
            info['timeout_triggered'] = False
            info['state'] = 'idle'
            info['tmp_data'] = {}
            info['trigger_msg'] = None
            info['in_menu'] = False
            info['admin_mode'] = False
            self._cancel_timeout(user_id)
            return
        if info['state'] != 'admin_delete_wait_select':
            return
        env_entries = await self._get_all_env_entries()
        if not env_entries:
            yield event.plain_result("❌ 环境变量中暂无账号")
            umo = event.unified_msg_origin
            self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, umo=umo)
            self._schedule_timeout(user_id)
            menu = await self._get_admin_menu_text()
            yield event.plain_result(menu)
            return
        msg = "📋 所有环境变量账号：\n"
        for idx, entry in enumerate(env_entries, 1):
            phone = entry["phone"]
            auth_display = "无限制" if entry["auth_count"] is None else str(entry["auth_count"])
            bound_qq = "未绑定"
            for qq, data in self.cache.items():
                for acc in data["accounts"]:
                    if acc["phone"] == phone:
                        bound_qq = qq
                        break
                if bound_qq != "未绑定":
                    break
            msg += f"{idx}. {phone} ｜ 授权: {auth_display} ｜ 绑定QQ: {bound_qq}\n"
        msg += "请输入要删除的账号序号（发送 q 取消）："
        umo = event.unified_msg_origin
        self._set_state(user_id, 'admin_delete_wait_select', admin_mode=True, in_menu=True, tmp_data={'env_entries': env_entries}, umo=umo)
        self._schedule_timeout(user_id)
        yield event.plain_result(msg)

    async def _admin_delete_select_handle(self, event):
        user_id = self._get_user_id(event)
        info = self._get_state_info(user_id)
        if info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 操作已超时，已退出交互。")
            info['timeout_triggered'] = False
            info['state'] = 'idle'
            info['tmp_data'] = {}
            info['trigger_msg'] = None
            info['in_menu'] = False
            info['admin_mode'] = False
            self._cancel_timeout(user_id)
            return
        if info['state'] != 'admin_delete_wait_select':
            return
        current_text = self._get_text(event)
        if info.get('trigger_msg') == current_text:
            return
        try:
            idx = int(current_text)
        except:
            yield event.plain_result("❌ 请输入有效的数字")
            return
        env_entries = info.get('tmp_data', {}).get('env_entries', [])
        if idx < 1 or idx > len(env_entries):
            yield event.plain_result(f"❌ 序号无效，请输入 1 到 {len(env_entries)} 之间的数字")
            return
        phone_to_del = env_entries[idx-1]["phone"]
        umo = event.unified_msg_origin
        self._set_state(user_id, 'admin_delete_wait_confirm', admin_mode=True, in_menu=True, tmp_data={'phone_to_del': phone_to_del}, umo=umo)
        self._schedule_timeout(user_id)
        yield event.plain_result(f"⚠️ 确认删除该账号（{phone_to_del}）吗？回复 y 确认，n 取消，数字忽略。")

    async def _admin_do_delete(self, phone: str) -> str:
        deleted = False
        for qq, data in self.cache.items():
            accounts = data["accounts"]
            for idx, acc in enumerate(accounts):
                if acc["phone"] == phone:
                    del accounts[idx]
                    self._update_cache_user(qq, accounts)
                    deleted = True
                    break
        env_entries = await self._get_all_env_entries()
        env_entries = [e for e in env_entries if e["phone"] != phone]
        await self._save_all_env_entries(env_entries)
        if deleted:
            return f"✅ 已删除手机号 {phone}（从所有绑定和环境变量中移除）"
        else:
            return f"✅ 已从环境变量删除手机号 {phone}（未发现绑定记录）"

    async def _admin_auth_select(self, event):
        user_id = self._get_user_id(event)
        info = self._get_state_info(user_id)
        if info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 操作已超时，已退出交互。")
            info['timeout_triggered'] = False
            info['state'] = 'idle'
            info['tmp_data'] = {}
            info['trigger_msg'] = None
            info['in_menu'] = False
            info['admin_mode'] = False
            self._cancel_timeout(user_id)
            return
        if info['state'] != 'admin_auth_wait_select':
            return
        env_entries = await self._get_all_env_entries()
        if not env_entries:
            yield event.plain_result("❌ 环境变量中暂无账号")
            umo = event.unified_msg_origin
            self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, umo=umo)
            self._schedule_timeout(user_id)
            menu = await self._get_admin_menu_text()
            yield event.plain_result(menu)
            return
        msg = "📋 所有环境变量账号（当前授权次数）：\n"
        for idx, entry in enumerate(env_entries, 1):
            auth_display = "无限制" if entry["auth_count"] is None else str(entry["auth_count"])
            msg += f"{idx}. {entry['phone']} ｜ 授权: {auth_display}\n"
        msg += "请输入要修改授权次数的账号序号（发送 q 取消）："
        umo = event.unified_msg_origin
        self._set_state(user_id, 'admin_auth_wait_select', admin_mode=True, in_menu=True, tmp_data={'env_entries': env_entries}, umo=umo)
        self._schedule_timeout(user_id)
        yield event.plain_result(msg)

    async def _admin_auth_select_handle(self, event):
        user_id = self._get_user_id(event)
        info = self._get_state_info(user_id)
        if info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 操作已超时，已退出交互。")
            info['timeout_triggered'] = False
            info['state'] = 'idle'
            info['tmp_data'] = {}
            info['trigger_msg'] = None
            info['in_menu'] = False
            info['admin_mode'] = False
            self._cancel_timeout(user_id)
            return
        if info['state'] != 'admin_auth_wait_select':
            return
        current_text = self._get_text(event)
        if info.get('trigger_msg') == current_text:
            return
        try:
            idx = int(current_text)
        except:
            yield event.plain_result("❌ 请输入有效的数字")
            return
        env_entries = info.get('tmp_data', {}).get('env_entries', [])
        if idx < 1 or idx > len(env_entries):
            yield event.plain_result(f"❌ 序号无效，请输入 1 到 {len(env_entries)} 之间的数字")
            return
        phone = env_entries[idx-1]["phone"]
        umo = event.unified_msg_origin
        self._set_state(user_id, 'admin_auth_wait_new_value', admin_mode=True, in_menu=True, tmp_data={'phone': phone}, umo=umo)
        self._schedule_timeout(user_id)
        yield event.plain_result(f"已选择账号 {phone}，请输入新的授权次数（数字）或输入 '无限制'（发送 q 取消）：")

    async def _admin_withdraw_select(self, event):
        user_id = self._get_user_id(event)
        info = self._get_state_info(user_id)
        if info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 操作已超时，已退出交互。")
            info['timeout_triggered'] = False
            info['state'] = 'idle'
            info['tmp_data'] = {}
            info['trigger_msg'] = None
            info['in_menu'] = False
            info['admin_mode'] = False
            self._cancel_timeout(user_id)
            return
        if info['state'] != 'admin_withdraw_wait_select':
            return
        env_entries = await self._get_all_env_entries()
        if not env_entries:
            yield event.plain_result("❌ 环境变量中暂无账号")
            umo = event.unified_msg_origin
            self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, umo=umo)
            self._schedule_timeout(user_id)
            menu = await self._get_admin_menu_text()
            yield event.plain_result(menu)
            return
        msg = "📋 所有环境变量账号（当前授权次数）：\n"
        for idx, entry in enumerate(env_entries, 1):
            auth_display = "无限制" if entry["auth_count"] is None else str(entry["auth_count"])
            msg += f"{idx}. {entry['phone']} ｜ 授权: {auth_display}\n"
        msg += "请输入要提现扣减的账号序号（发送 q 取消）："
        umo = event.unified_msg_origin
        self._set_state(user_id, 'admin_withdraw_wait_select', admin_mode=True, in_menu=True, tmp_data={'env_entries': env_entries}, umo=umo)
        self._schedule_timeout(user_id)
        yield event.plain_result(msg)

    async def _admin_withdraw_select_handle(self, event):
        user_id = self._get_user_id(event)
        info = self._get_state_info(user_id)
        if info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 操作已超时，已退出交互。")
            info['timeout_triggered'] = False
            info['state'] = 'idle'
            info['tmp_data'] = {}
            info['trigger_msg'] = None
            info['in_menu'] = False
            info['admin_mode'] = False
            self._cancel_timeout(user_id)
            return
        if info['state'] != 'admin_withdraw_wait_select':
            return
        current_text = self._get_text(event)
        if info.get('trigger_msg') == current_text:
            return
        try:
            idx = int(current_text)
        except:
            yield event.plain_result("❌ 请输入有效的数字")
            return
        env_entries = info.get('tmp_data', {}).get('env_entries', [])
        if idx < 1 or idx > len(env_entries):
            yield event.plain_result(f"❌ 序号无效，请输入 1 到 {len(env_entries)} 之间的数字")
            return
        phone = env_entries[idx-1]["phone"]
        for entry in env_entries:
            if entry["phone"] == phone:
                if entry["auth_count"] is None:
                    yield event.plain_result(f"❌ 账号 {phone} 为无限制，无法提现扣减")
                    umo = event.unified_msg_origin
                    self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, umo=umo)
                    self._schedule_timeout(user_id)
                    menu = await self._get_admin_menu_text()
                    yield event.plain_result(menu)
                    return
                break
        umo = event.unified_msg_origin
        self._set_state(user_id, 'admin_withdraw_wait_amount', admin_mode=True, in_menu=True, tmp_data={'phone': phone}, umo=umo)
        self._schedule_timeout(user_id)
        yield event.plain_result(f"已选择账号 {phone}，请输入要提现扣减的数量（正整数，发送 q 取消）：")

    @filter.regex(r'^\d+$')
    async def handle_admin_withdraw_amount(self, event: AstrMessageEvent):
        user_id = self._get_user_id(event)
        if user_id not in self.admin_qqs:
            return
        info = self._get_state_info(user_id)
        if info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 您上次操作已超时，已自动退出。请重新输入命令。")
            info['timeout_triggered'] = False
            info['state'] = 'idle'
            info['tmp_data'] = {}
            info['trigger_msg'] = None
            info['in_menu'] = False
            info['admin_mode'] = False
            self._cancel_timeout(user_id)
            return
        if info['state'] != 'admin_withdraw_wait_amount' or not info.get('in_menu', False):
            return
        current_text = self._get_text(event)
        if info.get('trigger_msg') == current_text:
            return
        try:
            amount = int(current_text)
        except:
            yield event.plain_result("❌ 请输入有效的正整数")
            return
        if amount <= 0:
            yield event.plain_result("❌ 提现数量须为正整数")
            return
        phone = info.get('tmp_data', {}).get('phone')
        if not phone:
            yield event.plain_result("❌ 会话错误，请重新操作")
            umo = event.unified_msg_origin
            self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, umo=umo)
            self._schedule_timeout(user_id)
            menu = await self._get_admin_menu_text()
            yield event.plain_result(menu)
            return
        result = await self._admin_do_withdraw(phone, amount)
        yield event.plain_result(result)
        umo = event.unified_msg_origin
        self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, umo=umo)
        self._schedule_timeout(user_id)
        menu = await self._get_admin_menu_text()
        yield event.plain_result(menu)

    async def _admin_do_withdraw(self, phone: str, amount: int) -> str:
        env_entries = await self._get_all_env_entries()
        entry_found = None
        for entry in env_entries:
            if entry["phone"] == phone:
                entry_found = entry
                break
        if not entry_found:
            return f"❌ 手机号 {phone} 不存在于环境变量中"
        if entry_found["auth_count"] is None:
            return f"❌ 账号 {phone} 为无限制，无法提现"
        if entry_found["auth_count"] < amount:
            return f"❌ 授权次数不足！当前 {entry_found['auth_count']}，需扣减 {amount}"
        entry_found["auth_count"] -= amount
        await self._save_all_env_entries(env_entries)
        return f"✅ 提现成功！手机号 {phone} 减少 {amount} 次，剩余 {entry_found['auth_count']}"

    async def _admin_reset_select(self, event):
        user_id = self._get_user_id(event)
        info = self._get_state_info(user_id)
        if info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 操作已超时，已退出交互。")
            info['timeout_triggered'] = False
            info['state'] = 'idle'
            info['tmp_data'] = {}
            info['trigger_msg'] = None
            info['in_menu'] = False
            info['admin_mode'] = False
            self._cancel_timeout(user_id)
            return
        if info['state'] != 'admin_reset_wait_select':
            return
        qq_list = [qq for qq, data in self.cache.items() if data.get("accounts")]
        if not qq_list:
            yield event.plain_result("📭 暂无任何用户绑定数据")
            umo = event.unified_msg_origin
            self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, umo=umo)
            self._schedule_timeout(user_id)
            menu = await self._get_admin_menu_text()
            yield event.plain_result(menu)
            return
        msg = "📋 有绑定记录的QQ列表：\n"
        for idx, qq in enumerate(qq_list, 1):
            acc_count = len(self.cache[qq].get("accounts", []))
            msg += f"{idx}. {qq} ｜ 账号数: {acc_count}\n"
        msg += "请输入要重置的QQ序号（发送 q 取消）："
        umo = event.unified_msg_origin
        self._set_state(user_id, 'admin_reset_wait_select', admin_mode=True, in_menu=True, tmp_data={'qq_list': qq_list}, umo=umo)
        self._schedule_timeout(user_id)
        yield event.plain_result(msg)

    async def _admin_reset_select_handle(self, event):
        user_id = self._get_user_id(event)
        info = self._get_state_info(user_id)
        if info.get('timeout_triggered', False):
            yield event.plain_result("⏰ 操作已超时，已退出交互。")
            info['timeout_triggered'] = False
            info['state'] = 'idle'
            info['tmp_data'] = {}
            info['trigger_msg'] = None
            info['in_menu'] = False
            info['admin_mode'] = False
            self._cancel_timeout(user_id)
            return
        if info['state'] != 'admin_reset_wait_select':
            return
        current_text = self._get_text(event)
        if info.get('trigger_msg') == current_text:
            return
        try:
            idx = int(current_text)
        except:
            yield event.plain_result("❌ 请输入有效的数字")
            return
        qq_list = info.get('tmp_data', {}).get('qq_list', [])
        if idx < 1 or idx > len(qq_list):
            yield event.plain_result(f"❌ 序号无效，请输入 1 到 {len(qq_list)} 之间的数字")
            return
        target_qq = qq_list[idx-1]
        await self._reset_user_data(target_qq)
        yield event.plain_result(f"✅ 已重置用户 {target_qq} 的所有数据")
        umo = event.unified_msg_origin
        self._set_state(user_id, 'admin_menu_idle', admin_mode=True, in_menu=True, umo=umo)
        self._schedule_timeout(user_id)
        menu = await self._get_admin_menu_text()
        yield event.plain_result(menu)
