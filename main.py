import base64
import json
import logging
import os
import shutil
import asyncio
import aiohttp
import time
import random
from PIL import Image as PILImage, ImageDraw, ImageFont
from typing import Dict, Any, Optional, Tuple
from datetime import datetime
import urllib.parse
import re
from pathlib import Path

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.core.message.components import Plain, At
from astrbot.core.message.components import Image
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

# 配置日志
logger = logging.getLogger("astrbot")

@register("astrbot_plugin_val_shop", "GuJi08233", "无畏契约每日商店查询插件", "v3.2.4")
class ValorantShopPlugin(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        # 鑾峰彇褰撳墠鎻掍欢鐩綍鐨勫瓧浣撴枃浠惰矾寰?
        import os
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        self.font_path = os.path.join(plugin_dir, "fontFamily.ttf")
        
        # 浣跨敤AstrBot鑷姩浼犲叆鐨勯厤缃?
        self.config = config if config is not None else {}
        
        # QQ 登录配置
        self.LOGIN_URL_TEMPLATE = "https://xui.ptlogin2.qq.com/cgi-bin/xlogin?pt_enable_pwd=1&appid=716027609&pt_3rd_aid=102061775&daid=381&pt_skey_valid=0&style=35&force_qr=1&autorefresh=1&s_url=http%3A%2F%2Fconnect.qq.com&refer_cgi=m_authorize&ucheck=1&fall_to_wv=1&status_os=12&redirect_uri=auth%3A%2F%2Ftauth.qq.com%2F&client_id=102061775&pf=openmobile_android&response_type=token&scope=all&sdkp=a&sdkv=3.5.17.lite&sign=a6479455d3e49b597350f13f776a6288&status_machine=MjMxMTdSSzY2Qw%3D%3D&switch=1&time=1763280194&show_download_ui=true&h5sig=trobryxo8IPM0GaSQH12mowKG-CY65brFzkK7_-9EW4&loginty=6"
        # 按抓包链路固定为 xui 域名 + /ssl 路径，避免落入旧 check_sig 链路
        self.PTQR_SHOW_URL = "https://xui.ptlogin2.qq.com/ssl/ptqrshow"
        self.PTQR_LOGIN_URL = "https://xui.ptlogin2.qq.com/ssl/ptqrlogin"
        self.OPENMOBILE_REDIRECT_URL = "https://openmobile.qq.com/oauth2.0/m_get_redirect_url"
        self.PTQR_AID = "716027609"
        self.PTQR_DAID = "381"
        self.PTQR_THIRD_AID = "102061775"
        # 从 HAR 成功链路看，xlogin/ptqrlogin 默认使用 connect.qq.com 更稳定
        self.DEFAULT_LOGIN_CALLBACK_URL = "http://connect.qq.com"
        self.DEFAULT_LOGIN_U1_URL = "http://connect.qq.com"
        
    async def initialize(self):
        """??"""
        db = self.context.get_db()
        
        # 鍒涘缓鐢ㄦ埛閰嶇疆琛?
        async with db.get_db() as session:
            session: AsyncSession
            async with session.begin():
                await session.execute(text("""
                    CREATE TABLE IF NOT EXISTS valo_users (
                        user_id TEXT PRIMARY KEY,
                        userId TEXT NOT NULL,
                        tid TEXT NOT NULL,
                        nickname TEXT,
                        auto_check INTEGER DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """))
        
        # 鍒涘缓鐩戞帶鍒楄〃琛?
        async with db.get_db() as session:
            session: AsyncSession
            async with session.begin():
                await session.execute(text("""
                    CREATE TABLE IF NOT EXISTS valo_watchlist (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id TEXT NOT NULL,
                        item_name TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES valo_users(user_id),
                        UNIQUE(user_id, item_name)
                    )
                """))
        
        # 初始化定时任务
        await self.setup_scheduler()
        logger.info("插件初始化完成")
    
    def _is_kook_platform(self, event: AstrMessageEvent) -> bool:
        """??"""
        try:
            platform_name = event.get_platform_name().lower()
            return 'kook' in platform_name or 'kaiheila' in platform_name or '开黑啦' in platform_name
        except Exception as e:
            logger.warning(f"检测平台类型失败: {e}")
            return False
    
    async def _get_kook_token(self, event: AstrMessageEvent) -> Optional[str]:
        """??"""
        try:
            # 灏濊瘯浠庡钩鍙扮鐞嗗櫒鑾峰彇Kook骞冲彴瀹炰緥
            platform_manager = self.context.platform_manager
            for platform in platform_manager.platform_insts:
                platform_meta = platform.meta()
                platform_name_lower = platform_meta.name.lower()
                if 'kook' in platform_name_lower or 'kaiheila' in platform_name_lower:
                    kook_client = getattr(platform, 'client', None)
                    if kook_client:
                        token = getattr(kook_client, 'token', None)
                        if token:
                            return token
            logger.warning("未能获取Kook Token")
            return None
        except Exception as e:
            logger.error(f"获取Kook Token失败: {e}")
            return None
    
    async def _upload_image_to_kook(self, image_path: str, token: str) -> Optional[str]:
        """??"""
        try:
            if not os.path.exists(image_path):
                logger.error(f"图片文件不存在: {image_path}")
                return None
            
            file_size = os.path.getsize(image_path)
            logger.info(f"准备上传图片到Kook，文件大小: {file_size} 字节 ({file_size / (1024 * 1024):.2f} MB)")
            
            upload_url = "https://www.kookapp.cn/api/v3/asset/create"
            headers = {'Authorization': f'Bot {token}'}
            
            async with aiohttp.ClientSession() as session:
                with open(image_path, 'rb') as f:
                    data = aiohttp.FormData()
                    data.add_field('file', f, filename=Path(image_path).name)
                    
                    async with session.post(upload_url, data=data, headers=headers) as response:
                        logger.info(f"Kook图片上传响应状态码: {response.status}")
                        
                        if response.status == 200:
                            result = await response.json()
                            logger.info(f"Kook图片上传响应: {result}")
                            
                            if result.get('code') == 0 and 'data' in result:
                                asset_data = result['data']
                                # 灏濊瘯鑾峰彇URL锛孠ook鍙兘杩斿洖涓嶅悓鐨勫瓧娈靛悕
                                asset_url = (asset_data.get('url') or
                                           asset_data.get('file_url') or
                                           asset_data.get('link') or
                                           asset_data.get('asset_url'))
                                
                                if asset_url:
                                    logger.info(f"Kook图片上传成功，URL: {asset_url}")
                                    return asset_url
                                else:
                                    logger.error(f"无法从Kook响应中提取图片URL: {asset_data}")
                                    return None
                            else:
                                error_msg = result.get('message', '未知错误')
                                error_code = result.get('code', 'N/A')
                                logger.error(f"Kook图片上传失败 (代码: {error_code}): {error_msg}")
                                return None
                        else:
                            response_text = await response.text()
                            logger.error(f"Kook图片上传HTTP错误: {response.status}, 详情: {response_text}")
                            return None
                            
        except Exception as e:
            logger.error(f"上传图片到Kook异常: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    async def _send_kook_image_message(self, channel_id: str, image_url: str, token: str) -> bool:
        """??"""
        try:
            url = "https://www.kookapp.cn/api/v3/message/create"
            headers = {
                "Authorization": f"Bot {token}",
                "Content-Type": "application/json"
            }
            payload = {
                "target_id": channel_id,
                "content": image_url,
                "type": 2  # type=2 表示图片消息
            }
            
            logger.info(f"发送Kook图片消息到频道: {channel_id}")
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload) as resp:
                    logger.info(f"Kook发送图片响应状态码: {resp.status}")
                    
                    if resp.status == 200:
                        result = await resp.json()
                        logger.info(f"Kook发送图片响应: {result}")
                        
                        if result.get('code') == 0:
                            logger.info("Kook图片消息发送成功")
                            return True
                        else:
                            error_msg = result.get('message', '未知错误')
                            logger.error(f"Kook图片消息发送失败: {error_msg}")
                            return False
                    else:
                        response_text = await resp.text()
                        logger.error(f"Kook发送图片HTTP错误: {resp.status}, 详情: {response_text}")
                        return False
                        
        except Exception as e:
            logger.error(f"发送Kook图片消息异常: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    async def _send_image_for_kook(self, event: AstrMessageEvent, image_path: str) -> Tuple[bool, Optional[str]]:
        """??"""
        try:
            # 获取Kook Token
            token = await self._get_kook_token(event)
            if not token:
                return False, "无法获取Kook认证信息"
            
            # 上传图片到Kook
            image_url = await self._upload_image_to_kook(image_path, token)
            if not image_url:
                return False, "图片上传到Kook失败"
            
            # 获取目标频道ID
            channel_id = event.message_obj.group_id or event.session_id
            if not channel_id:
                return False, "无法获取目标频道ID"
            
            # 发送图片消息
            success = await self._send_kook_image_message(channel_id, image_url, token)
            if success:
                return True, None
            else:
                return False, "Kook消息发送失败"
                
        except Exception as e:
            logger.error(f"Kook图片发送异常: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False, str(e)
        
    async def terminate(self):
        """??"""
        # 关闭定时任务调度器
        if hasattr(self, '_scheduler') and self._scheduler:
            self._scheduler.shutdown()
            logger.info("定时任务调度器已关闭")

    def _get_config_value(self, key: str, default=None):
        """??"""
        return self.config.get(key, default)

    def _normalize_url(self, value: str, default: str = "") -> str:
        """??"""
        url = (value or default or "").strip()
        if not url:
            return ""
        if not re.match(r"^https?://", url, re.IGNORECASE):
            url = f"https://{url.lstrip('/')}"
        return url

    def _get_login_callback_url(self) -> str:
        """??"""
        value = str(
            self._get_config_value("login_callback_url", self.DEFAULT_LOGIN_CALLBACK_URL)
            or self.DEFAULT_LOGIN_CALLBACK_URL
        )
        return self._normalize_url(value, self.DEFAULT_LOGIN_CALLBACK_URL)

    def _get_login_u1_url(self, callback_url: str) -> str:
        """??"""
        value = str(
            self._get_config_value("login_u1_url", self.DEFAULT_LOGIN_U1_URL)
            or self.DEFAULT_LOGIN_U1_URL
        )
        return self._normalize_url(value, self.DEFAULT_LOGIN_U1_URL)

    def _build_login_url(self, callback_url: str) -> str:
        """??"""
        encoded_callback = urllib.parse.quote(callback_url, safe="")
        if "s_url=" not in self.LOGIN_URL_TEMPLATE:
            return self.LOGIN_URL_TEMPLATE
        return re.sub(
            r"([?&])s_url=[^&]*",
            lambda m: f"{m.group(1)}s_url={encoded_callback}",
            self.LOGIN_URL_TEMPLATE,
            count=1,
        )

    async def setup_scheduler(self):
        """初始化每日自动监控定时任务。"""
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            from apscheduler.triggers.cron import CronTrigger

            timezone = self._get_config_value('timezone', 'Asia/Shanghai')
            self._scheduler = AsyncIOScheduler(timezone=timezone)

            monitor_time = self._get_config_value('monitor_time', '08:01')
            hour, minute = map(int, monitor_time.split(':'))

            self._scheduler.add_job(
                self.daily_auto_check,
                CronTrigger(hour=hour, minute=minute, timezone=timezone),
                id='daily_shop_check',
                replace_existing=True
            )

            self._scheduler.start()
            logger.info(f"自动监控定时任务已启动：每天 {monitor_time} ({timezone})")

        except Exception as e:
            logger.error(f"定时任务调度器启动失败: {e}")

    async def daily_auto_check(self):
        """执行每日自动监控。"""
        logger.info("开始执行每日自动监控任务")

        try:
            db = self.context.get_db()
            async with db.get_db() as session:
                session: AsyncSession
                result = await session.execute(
                    text("SELECT user_id FROM valo_users WHERE auto_check = 1")
                )
                users = result.fetchall()

                if not users:
                    logger.info("当前没有开启自动监控的用户")
                    return

                logger.info(f"自动监控用户数量: {len(users)}")

                for row in users:
                    user_id = row[0]
                    try:
                        bot_id = self._get_config_value('bot_id', 'default')
                        unified_msg_origin = f"{bot_id}:FriendMessage:{user_id}"
                        logger.info(f"定时任务会话ID: {unified_msg_origin}")
                        await self.check_user_watchlist(user_id, unified_msg_origin)
                    except Exception as e:
                        logger.error(f"检查用户 {user_id} 监控列表时出错: {e}")
                        continue

        except Exception as e:
            logger.error(f"每日自动监控任务执行失败: {e}")

    async def check_user_watchlist(self, user_id: str, unified_msg_origin: str = None):
        """检查用户监控列表并匹配今日商店。"""
        logger.info(f"开始检查用户 {user_id} 的监控列表")

        user_config = await self.get_user_config(user_id)
        if not user_config:
            logger.warning(f"用户 {user_id} 未绑定配置，跳过监控")
            return

        watchlist = await self.get_watchlist(user_id)
        if not watchlist:
            logger.info(f"用户 {user_id} 监控列表为空")
            return

        goods_list = await self.get_shop_items_raw(user_id, user_config)
        if not goods_list:
            logger.info(f"用户 {user_id} 商店数据为空或获取失败")
            return

        matched_items = []
        watchlist_names = [item['item_name'] for item in watchlist]

        logger.info(f"监控列表: {watchlist_names}")
        logger.info(f"商店商品: {[goods.get('goods_name', '') for goods in goods_list]}")

        for goods in goods_list:
            goods_name = goods.get('goods_name', '')
            for watch_name in watchlist_names:
                if watch_name in goods_name or goods_name in watch_name:
                    matched_items.append({
                        'name': goods_name,
                        'price': goods.get('rmb_price', '0')
                    })
                    logger.info(f"匹配成功: {goods_name}")
                    break

        if matched_items:
            logger.info(f"用户 {user_id} 命中 {len(matched_items)} 个监控商品")
            await self.send_notification(user_id, matched_items, unified_msg_origin)
        else:
            logger.info(f"用户 {user_id} 今日无监控商品上架")

    async def send_notification(self, user_id: str, matched_items: list, unified_msg_origin: str = None):
        """发送监控命中通知。"""
        try:
            from datetime import datetime
            current_date = datetime.now().strftime("%Y-%m-%d")

            items_text = "\n".join([f"  - {item['name']} ({item['price']})" for item in matched_items])
            matched_names = [item['name'] for item in matched_items]

            notification_text = (
                f"{current_date} 商店监控通知\n\n"
                f"以下监控商品已上架：\n"
                f"{items_text}\n\n"
                f"请使用 /每日商店 查看详情\n\n"
                f"匹配商品：{', '.join(matched_names)}"
            )

            from astrbot.api.event import MessageChain

            if unified_msg_origin:
                session_id = unified_msg_origin
            else:
                session_id = f"qq/{user_id}"

            message_chain = MessageChain().message(notification_text)
            await self.context.send_message(session_id, message_chain)
            logger.info(f"已发送通知给用户 {user_id}, 会话ID: {session_id}")

        except Exception as e:
            logger.error(f"发送通知失败: {e}")

    async def add_watch_item(self, user_id: str, item_name: str) -> bool:
        """添加监控项。"""
        try:
            db = self.context.get_db()
            async with db.get_db() as session:
                session: AsyncSession
                async with session.begin():
                    result = await session.execute(
                        text("SELECT COUNT(*) FROM valo_watchlist WHERE user_id = :user_id AND item_name = :item_name"),
                        {"user_id": user_id, "item_name": item_name}
                    )
                    count = result.scalar()
                    
                    if count > 0:
                        return False  # 宸插瓨鍦?
                    
                    await session.execute(
                        text("INSERT INTO valo_watchlist (user_id, item_name) VALUES (:user_id, :item_name)"),
                        {"user_id": user_id, "item_name": item_name}
                    )
                    logger.info(f"用户 {user_id} 添加监控项: {item_name}")
                    return True

        except Exception as e:
            logger.error(f"添加监控项失败: {e}")
            return False

    async def remove_watch_item(self, user_id: str, item_name: str) -> bool:
        """删除监控项。"""
        try:
            db = self.context.get_db()
            async with db.get_db() as session:
                session: AsyncSession
                async with session.begin():
                    result = await session.execute(
                        text("DELETE FROM valo_watchlist WHERE user_id = :user_id AND item_name = :item_name"),
                        {"user_id": user_id, "item_name": item_name}
                    )
                    
                    if result.rowcount > 0:
                        logger.info(f"用户 {user_id} 删除监控项: {item_name}")
                        return True
                    else:
                        logger.warning(f"用户 {user_id} 尝试删除不存在的监控项: {item_name}")
                        return False

        except Exception as e:
            logger.error(f"删除监控项失败: {e}")
            return False

    async def get_watchlist(self, user_id: str) -> list:
        """获取用户监控列表。"""
        try:
            db = self.context.get_db()
            async with db.get_db() as session:
                session: AsyncSession
                result = await session.execute(
                    text("SELECT item_name, created_at FROM valo_watchlist WHERE user_id = :user_id ORDER BY created_at"),
                    {"user_id": user_id}
                )
                rows = result.fetchall()
                
                watchlist = []
                for row in rows:
                    watchlist.append({
                        'item_name': row[0],
                        'created_at': row[1]
                    })

                logger.info(f"用户 {user_id} 监控项数量: {len(watchlist)}")
                return watchlist

        except Exception as e:
            logger.error(f"获取监控列表失败: {e}")
            return []

    async def update_auto_check(self, user_id: str, status: int):
        """更新自动监控开关状态。"""
        try:
            db = self.context.get_db()
            async with db.get_db() as session:
                session: AsyncSession
                async with session.begin():
                    await session.execute(
                        text("UPDATE valo_users SET auto_check = :status, updated_at = CURRENT_TIMESTAMP WHERE user_id = :user_id"),
                        {"status": status, "user_id": user_id}
                    )
                    logger.info(f"用户 {user_id} 自动查询状态更新为: {status}")

        except Exception as e:
            logger.error(f"更新自动查询状态失败: {e}")

    def _get_cookie_value(self, session: aiohttp.ClientSession, url: str, name: str) -> str:
        """读取 Cookie 值。"""
        try:
            cookies = session.cookie_jar.filter_cookies(url)
            cookie = cookies.get(name)
            if cookie:
                return cookie.value
        except Exception as e:
            logger.warning(f"读取Cookie失败: {name}, {e}")
        return ""

    def _calc_ptqrtoken(self, qrsig: str) -> int:
        """??"""
        token = 0
        for ch in qrsig:
            token += (token << 5) + ord(ch)
        return token & 2147483647

    def _parse_ptui_callback(self, text: str) -> Optional[Dict[str, str]]:
        """??"""
        match = re.search(r"ptuiCB\('([^']*)','([^']*)','([^']*)','([^']*)','([^']*)'", text)
        if not match:
            return None

        redirect_url = match.group(3).replace("\\/", "/").replace("\\x26", "&")
        return {
            "code": match.group(1),
            "redirect_url": redirect_url,
            "message": match.group(5),
        }

    def _extract_login_data_from_success_url(self, success_url: str) -> Dict[str, Any]:
        """??"""
        def normalize_url(url: str) -> str:
            return (url or "").replace("\\/", "/").replace("\\x26", "&").strip()

        def parse_param_str(raw: str) -> Dict[str, str]:
            parsed: Dict[str, str] = {}
            if not raw:
                return parsed
            part = raw.replace("#&", "&").lstrip("&")
            for key, value in urllib.parse.parse_qs(part, keep_blank_values=True).items():
                if value:
                    parsed[key] = value[0]
            return parsed

        nested_keys = {
            "u1",
            "url",
            "jump_url",
            "redirect_uri",
            "redirect_url",
            "target_url",
            "s_url",
            "f_url",
            "qtarget",
            "jump",
            "ru",
        }

        merged_params: Dict[str, str] = {}
        queue = [normalize_url(success_url)]
        visited = set()

        while queue:
            candidate = queue.pop(0)
            if not candidate or candidate in visited:
                continue
            visited.add(candidate)

            decoded = candidate
            for _ in range(3):
                next_decoded = urllib.parse.unquote(decoded)
                if next_decoded == decoded:
                    break
                decoded = next_decoded

            parsed_url = urllib.parse.urlparse(decoded)
            candidate_params: Dict[str, str] = {}
            for raw_part in (parsed_url.query, parsed_url.fragment):
                candidate_params.update(parse_param_str(raw_part))

            if not candidate_params and ("openid=" in decoded or "access_token=" in decoded):
                candidate_params.update(parse_param_str(decoded))

            if candidate_params:
                logger.info(
                    f"[HTTP登录] 参数提取：来源={decoded[:180]}，命中键={sorted(candidate_params.keys())}"
                )
            for key, value in candidate_params.items():
                if key not in merged_params:
                    merged_params[key] = value

            for nested_key in nested_keys:
                nested_value = candidate_params.get(nested_key, "")
                if nested_value and nested_value not in visited:
                    logger.info(
                        f"[HTTP登录] 发现嵌套跳转参数 {nested_key}={str(nested_value)[:220]}"
                    )
                    queue.append(normalize_url(nested_value))

        logger.info(
            f"[HTTP登录] 汇总参数键={sorted(merged_params.keys())}, "
            f"openid={bool(merged_params.get('openid'))}, "
            f"access_token={bool(merged_params.get('access_token'))}"
        )
        return {
            "openid": merged_params.get("openid", ""),
            "appid": merged_params.get("appid", ""),
            "access_token": merged_params.get("access_token", ""),
            "pay_token": merged_params.get("pay_token", ""),
            "key": merged_params.get("key", ""),
            "redirect_uri_key": merged_params.get("redirect_uri_key", ""),
            "expires_in": merged_params.get("expires_in", "7776000"),
            "pf": merged_params.get("pf", "openmobile_android"),
            "status_os": merged_params.get("status_os", "12"),
            "status_machine": merged_params.get("status_machine", ""),
            "full_params": merged_params,
        }

    def _build_pt_openlogin_data(self, login_url: str, session: aiohttp.ClientSession) -> str:
        """构造 ptqrlogin 请求里的 pt_openlogin_data。"""
        parsed = urllib.parse.urlparse(login_url)
        query_map = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)

        def q(name: str, default: str = "") -> str:
            values = query_map.get(name, [])
            return values[0] if values else default

        tid = self._get_cookie_value(session, "https://xui.ptlogin2.qq.com", "idt") or str(int(time.time()))
        auth_time = str(int(time.time() * 1000))
        items = [
            ("which", ""),
            ("refer_cgi", q("refer_cgi", "m_authorize")),
            ("response_type", q("response_type", "token")),
            ("client_id", q("client_id", self.PTQR_THIRD_AID)),
            ("state", ""),
            ("display", ""),
            ("openapi", "1011"),
            ("switch", q("switch", "1")),
            ("src", "1"),
            ("sdkv", q("sdkv", "3.5.17.lite")),
            ("sdkp", q("sdkp", "a")),
            ("tid", tid),
            ("pf", q("pf", "openmobile_android")),
            ("need_pay", "0"),
            ("browser", "0"),
            ("browser_error", ""),
            ("serial", ""),
            ("token_key", ""),
            ("redirect_uri", q("redirect_uri", "auth://tauth.qq.com/")),
            ("sign", q("sign", "")),
            ("time", q("time", "")),
            ("status_version", ""),
            ("status_os", q("status_os", "12")),
            ("status_machine", q("status_machine", "")),
            ("page_type", "1"),
            ("has_auth", "1"),
            ("update_auth", "1"),
            ("auth_time", auth_time),
            ("loginfrom", ""),
            ("h5sig", q("h5sig", "")),
            ("loginty", q("loginty", "6")),
        ]
        pt_openlogin_data = urllib.parse.urlencode(items)
        logger.info(
            f"[HTTP登录] 生成pt_openlogin_data: len={len(pt_openlogin_data)}, "
            f"tid={tid}, auth_time={auth_time}, sign_prefix={q('sign', '')[:8]}, "
            f"h5sig_prefix={q('h5sig', '')[:8]}"
        )
        return pt_openlogin_data

    def _extract_jsver_from_login_page(self, login_page: str) -> str:
        """从 xlogin HTML 中提取 jsver（monorepo 版本号）。"""
        text = login_page or ""
        patterns = [
            r"/monorepo/([0-9A-Za-z]+)/ptlogin/js/login_10\.js",
            r"/monorepo/([0-9A-Za-z]+)/ptlogin/js/",
            r"https://qq-web\.cdn-go\.cn/monorepo/([0-9A-Za-z]+)",
        ]
        for pattern in patterns:
            m = re.search(pattern, text)
            if m:
                return m.group(1)
        return "28d22679"

    def _build_aegis_uid(self, session: aiohttp.ClientSession) -> str:
        """构造 ptqrlogin 的 aegis_uid。"""
        aegis_uid = self._get_cookie_value(session, "https://xui.ptlogin2.qq.com", "__aegis_uid")
        if aegis_uid:
            return aegis_uid
        server_ip = self._get_cookie_value(session, "https://xui.ptlogin2.qq.com", "pt_serverip")
        client_ip = self._get_cookie_value(session, "https://xui.ptlogin2.qq.com", "pt_clientip")
        if server_ip and client_ip:
            return f"{server_ip}-{client_ip}-4458"
        return ""

    def _extract_auth_url_from_callback_body(self, text: str) -> str:
        """从 _Callback({...}) 文本里提取 auth:// URL。"""
        if not text:
            return ""
        callback_match = re.search(r"_Callback\s*\(\s*(\{.*?\})\s*\)\s*;?\s*$", text, re.DOTALL)
        if callback_match:
            payload_text = callback_match.group(1)
            try:
                payload = json.loads(payload_text)
                callback_url = str(payload.get("url", "") or "").strip()
                if callback_url.startswith("auth://"):
                    return callback_url
            except Exception as e:
                logger.warning(
                    f"[HTTP登录] 解析_Callback JSON失败: type={type(e).__name__}, repr={repr(e)}"
                )

        auth_match = re.search(r"(auth://tauth\.qq\.com/[^\s\"'<>]+)", text)
        if auth_match:
            return auth_match.group(1)
        return ""

    def _merge_login_data(self, base_data: Dict[str, Any], extra_data: Dict[str, Any]) -> Dict[str, Any]:
        """合并两份登录参数，优先保留已有值。"""
        base = dict(base_data or {})
        extra = dict(extra_data or {})
        merged_params: Dict[str, str] = dict(base.get("full_params", {}) or {})
        merged_params.update(extra.get("full_params", {}) or {})

        for key in (
            "openid",
            "appid",
            "access_token",
            "pay_token",
            "key",
            "redirect_uri_key",
            "expires_in",
            "pf",
            "status_os",
            "status_machine",
        ):
            if not base.get(key) and extra.get(key):
                base[key] = extra[key]
        base["full_params"] = merged_params
        return base

    def _collect_redirect_key_candidates(
        self,
        session: aiohttp.ClientSession,
        login_data: Dict[str, Any],
        success_url: str,
    ) -> list:
        """收集可用于 m_get_redirect_url 的 keystr 候选。"""
        result = []
        seen = set()

        def add_key(value: str, source: str):
            keystr = (value or "").strip()
            if not keystr or keystr in seen:
                return
            seen.add(keystr)
            result.append((keystr, source))

        full_params = (login_data or {}).get("full_params", {}) or {}
        for key_name in ("redirect_uri_key", "keystr", "key", "uikey", "superkey", "supertoken"):
            add_key(str(full_params.get(key_name, "")), f"param:{key_name}")

        normalized_url = (success_url or "").replace("\\/", "/").replace("\\x26", "&")
        parsed = urllib.parse.urlparse(normalized_url)
        raw_parts = [parsed.query, parsed.fragment]
        if not parsed.query and not parsed.fragment:
            raw_parts.append(normalized_url)

        for raw in raw_parts:
            if not raw:
                continue
            raw_params = urllib.parse.parse_qs(raw.replace("#&", "&"), keep_blank_values=True)
            for key_name in ("redirect_uri_key", "keystr", "key", "uikey", "superkey", "supertoken"):
                values = raw_params.get(key_name, [])
                if values:
                    add_key(values[0], f"url:{key_name}")

        cookie_domains = [
            "https://xui.ptlogin2.qq.com",
            "https://ssl.ptlogin2.qq.com",
            "https://ptlogin4.openmobile.qq.com",
            "https://openmobile.qq.com",
            "https://connect.qq.com",
        ]
        for domain in cookie_domains:
            host = urllib.parse.urlparse(domain).netloc
            for key_name in ("redirect_uri_key", "keystr", "uikey", "superkey", "supertoken", "key"):
                add_key(self._get_cookie_value(session, domain, key_name), f"cookie:{host}:{key_name}")

        return result

    async def _fetch_auth_url_by_redirect_key(
        self,
        session: aiohttp.ClientSession,
        redirect_uri_key: str,
    ) -> str:
        """调用 m_get_redirect_url，根据 keystr 获取 auth:// 回调。"""
        keystr = (redirect_uri_key or "").strip()
        if not keystr:
            return ""

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 12; 23117RK66C Build/V417IR; wv) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
                "Chrome/101.0.4951.61 Mobile Safari/537.36 tencent_game_emulator"
            ),
            "Accept": "*/*",
            "Referer": "https://imgcache.qq.com/",
        }
        logger.info(f"[HTTP登录] 调用m_get_redirect_url, keystr前24位={keystr[:24]}")
        try:
            async with session.get(
                self.OPENMOBILE_REDIRECT_URL,
                params={"keystr": keystr},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=20, connect=10, sock_connect=10, sock_read=15),
            ) as response:
                body = await response.text(errors="ignore")
                logger.info(
                    f"[HTTP登录] m_get_redirect_url status={response.status}, body={body[:220]}"
                )
                if response.status != 200:
                    return ""
                auth_url = self._extract_auth_url_from_callback_body(body)
                if auth_url:
                    logger.info(f"[HTTP登录] m_get_redirect_url成功提取auth: {auth_url[:220]}")
                else:
                    logger.warning("[HTTP登录] m_get_redirect_url未提取到auth://tauth.qq.com")
                return auth_url
        except Exception as e:
            logger.warning(
                f"[HTTP登录] m_get_redirect_url异常: type={type(e).__name__}, repr={repr(e)}"
            )
            return ""


    async def _resolve_login_success_url(
        self,
        session: aiohttp.ClientSession,
        success_url: str,
        referer_url: str = "",
    ) -> str:
        """对 check_sig 做单次解析，尝试拿到下一跳 URL。"""
        current_url = (success_url or "").replace("\\/", "/").replace("\\x26", "&").strip()
        if not current_url:
            return ""
        if "check_sig" not in current_url:
            return current_url

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 12; 23117RK66C Build/V417IR; wv) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
                "Chrome/101.0.4951.61 Mobile Safari/537.36 tencent_game_emulator"
            ),
            "Accept": "*/*",
            "Referer": referer_url or "https://openmobile.qq.com/",
        }
        logger.info(f"[HTTP登录] 尝试解析check_sig: {current_url[:220]}")
        try:
            async with session.get(
                current_url,
                headers=headers,
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=15, connect=8, sock_connect=8, sock_read=10),
            ) as response:
                body = await response.text(errors="ignore")
                location = (response.headers.get("Location", "") or "").strip()
                logger.info(
                    f"[HTTP登录] check_sig响应: status={response.status}, "
                    f"location={location[:220] if location else ''}"
                )
                if location:
                    next_url = urllib.parse.urljoin(str(response.url), location)
                    logger.info(f"[HTTP登录] check_sig下一跳URL: {next_url[:220]}")
                    return next_url

                body_url = self._extract_url_from_body(body)
                if body_url:
                    logger.info(f"[HTTP登录] check_sig正文提取URL: {body_url[:220]}")
                    return body_url

                logger.warning(f"[HTTP登录] check_sig未提取到下一跳，body片段={body[:220]}")
        except Exception as e:
            logger.warning(
                f"[HTTP登录] check_sig解析异常: type={type(e).__name__}, repr={repr(e)}"
            )
        return current_url

    def _extract_url_from_body(self, body: str) -> str:
        """从响应正文中提取跳转 URL。"""
        text = (body or "").replace("\\/", "/").replace("\\x26", "&")
        patterns = [
            r"ptuiCB\('[^']*','[^']*','([^']+)'",
            r"ptui_auth_CB\('[^']*','[^']*','([^']+)'",
            r"location\.href\s*=\s*['\"]([^'\"]+)['\"]",
            r"location\.replace\(\s*['\"]([^'\"]+)['\"]\s*\)",
            r"window\.location\s*=\s*['\"]([^'\"]+)['\"]",
            r"(auth://tauth\.qq\.com/[^\s\"'<>]+)",
            r"(https?://imgcache\.qq\.com/[^\s\"'<>]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return ""

    async def generate_qr_code_http(self) -> Optional[Dict[str, Any]]:
        """通过纯 HTTP 协议生成登录二维码。"""
        logger.info("[HTTP登录] 开始生成二维码")

        session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20))
        callback_url = self._get_login_callback_url()
        u1_url = self._get_login_u1_url(callback_url)
        login_url = self._build_login_url(callback_url)
        logger.info(
            f"[HTTP登录] 使用回调参数: s_url={callback_url}, u1={u1_url}"
        )
        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 12; 23117RK66C Build/V417IR; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/101.0.4951.61 Mobile Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": "https://openmobile.qq.com/",
            "X-Requested-With": "com.tencent.apps.valorant",
            "Cookie": "accountType=5; clientType=9",
        }

        try:
            # 绗竴姝ワ細璁块棶xlogin锛屽垵濮嬪寲浼氳瘽骞惰幏鍙杔ogin_sig
            async with session.get(login_url, headers=headers) as response:
                response.raise_for_status()
                login_page = await response.text(errors="ignore")
                logger.info(
                    f"[HTTP登录] xlogin status={response.status}, len={len(login_page)}"
                )

            login_sig = ""
            login_sig_match = re.search(r"g_login_sig=encodeURIComponent\(\"([^\"]+)\"\)", login_page)
            if login_sig_match:
                login_sig = login_sig_match.group(1)
            if not login_sig:
                login_sig = self._get_cookie_value(session, "https://xui.ptlogin2.qq.com", "pt_login_sig")
            if not login_sig:
                login_sig = self._get_cookie_value(session, "https://ssl.ptlogin2.qq.com", "pt_login_sig")
            logger.info(
                f"[HTTP登录] login_sig={'已获取' if login_sig else '未获取'}, "
                f"prefix={login_sig[:12] if login_sig else ''}"
            )


            # 从 xlogin 链路中提取轮询关键参数
            parsed_login_url = urllib.parse.urlparse(login_url)
            login_query_map = urllib.parse.parse_qs(parsed_login_url.query, keep_blank_values=True)
            login_s_url = login_query_map.get("s_url", [callback_url])[0] or callback_url
            login_u1 = u1_url
            if login_s_url != login_u1:
                logger.info(f"[HTTP登录] 检测到 s_url 与 u1 不一致: s_url={login_s_url}, u1={login_u1}")
            pt_uistyle = login_query_map.get("style", ["35"])[0] or "35"
            ptlang = login_query_map.get("ptlang", ["2052"])[0] or "2052"
            jsver = self._extract_jsver_from_login_page(login_page)
            pt_openlogin_data = self._build_pt_openlogin_data(login_url, session)
            aegis_uid = self._build_aegis_uid(session)
            logger.info(
                f"[HTTP登录] 轮询参数: u1={login_u1}, ptlang={ptlang}, "
                f"pt_uistyle={pt_uistyle}, jsver={jsver}, "
                f"pt_openlogin_data_len={len(pt_openlogin_data)}, aegis_uid={aegis_uid or '无'}"
            )

            qr_params = {
                "s": "8",
                "e": "0",
                "appid": self.PTQR_AID,
                "type": "0",
                "t": str(random.random()),
                "u1": login_u1,
                "daid": self.PTQR_DAID,
                "pt_3rd_aid": self.PTQR_THIRD_AID,
            }
            qr_headers = {
                "User-Agent": headers["User-Agent"],
                "Referer": login_url,
                "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                "X-Requested-With": "com.tencent.apps.valorant",
            }
            logger.info(f"[HTTP登录] ptqrshow params={qr_params}")
            async with session.get(self.PTQR_SHOW_URL, params=qr_params, headers=qr_headers) as response:
                response.raise_for_status()
                qr_image_bytes = await response.read()
                logger.info(
                    f"[HTTP登录] ptqrshow status={response.status}, bytes={len(qr_image_bytes)}"
                )

            if not qr_image_bytes:
                raise RuntimeError("二维码内容为空")

            qrsig = self._get_cookie_value(session, "https://xui.ptlogin2.qq.com", "qrsig")
            if not qrsig:
                qrsig = self._get_cookie_value(session, "https://ssl.ptlogin2.qq.com", "qrsig")
            if not qrsig:
                raise RuntimeError("未获取到qrsig")
            logger.info(f"[HTTP登录] qrsig前12位={qrsig[:12]}")

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"qr_code_http_{timestamp}.png"
            with open(filename, "wb") as f:
                f.write(qr_image_bytes)

            logger.info("[HTTP登录] 二维码生成成功")
            return {
                "session": session,
                "filename": filename,
                "ptqrtoken": self._calc_ptqrtoken(qrsig),
                "login_sig": login_sig,
                "login_url": login_url,
                "u1_url": login_u1,
                "callback_url": callback_url,
                "pt_openlogin_data": pt_openlogin_data,
                "aegis_uid": aegis_uid,
                "jsver": jsver,
                "pt_uistyle": pt_uistyle,
                "ptlang": ptlang,
            }

        except Exception as e:
            logger.warning(
                f"[HTTP登录] 生成二维码失败: type={type(e).__name__}, repr={repr(e)}"
            )
            await session.close()
            return None


    async def wait_for_http_login_result(
        self,
        session: aiohttp.ClientSession,
        ptqrtoken: int,
        login_sig: str,
        login_u1: str,
        referer_url: str,
        pt_openlogin_data: str = "",
        aegis_uid: str = "",
        jsver: str = "28d22679",
        pt_uistyle: str = "35",
        ptlang: str = "2052",
        timeout: int = 30,
    ) -> Optional[Dict[str, Any]]:
        """通过 HTTP 轮询二维码登录状态并提取 openid/access_token。"""
        logger.info(
            f"[HTTP登录] 开始轮询: ptqrtoken={ptqrtoken}, "
            f"login_sig={'有' if login_sig else '无'}, u1={login_u1}, "
            f"pt_openlogin_data_len={len(pt_openlogin_data)}, "
            f"aegis_uid={aegis_uid or '无'}, jsver={jsver}, "
            f"pt_uistyle={pt_uistyle}, ptlang={ptlang}"
        )
        poll_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 12; 23117RK66C Build/V417IR; wv) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
                "Chrome/101.0.4951.61 Mobile Safari/537.36 tencent_game_emulator"
            ),
            "Referer": referer_url,
            "Accept": "*/*",
            "X-Requested-With": "com.tencent.apps.valorant",
        }

        start_time = time.time()
        poll_index = 0
        while time.time() - start_time < timeout:
            poll_index += 1
            try:
                params = {
                    "u1": login_u1,
                    "from_ui": "1",
                    "type": "1",
                    "ptlang": str(ptlang or "2052"),
                    "ptqrtoken": str(ptqrtoken),
                    "daid": self.PTQR_DAID,
                    "aid": self.PTQR_AID,
                    "pt_3rd_aid": self.PTQR_THIRD_AID,
                    "pt_openlogin_data": pt_openlogin_data,
                    "device": "2",
                    "ptopt": "1",
                    "pt_uistyle": str(pt_uistyle or "35"),
                    "jsver": str(jsver or "28d22679"),
                    "r": str(random.random()),
                }
                if login_sig:
                    params["login_sig"] = login_sig
                if aegis_uid:
                    params["aegis_uid"] = aegis_uid

                async with session.get(self.PTQR_LOGIN_URL, params=params, headers=poll_headers) as response:
                    response.raise_for_status()
                    text = await response.text(errors="ignore")
                    logger.info(
                        f"[HTTP登录] 轮询#{poll_index} status={response.status}, text={text[:160]}"
                    )

                callback = self._parse_ptui_callback(text)
                if not callback:
                    logger.warning(f"[HTTP登录] 无法解析ptui回调, text={text[:160]}")
                    await asyncio.sleep(2)
                    continue

                code = callback["code"]
                message = callback["message"]
                redirect_url = callback.get("redirect_url", "")
                logger.info(
                    f"[HTTP登录] 轮询#{poll_index} code={code}, message={message}, "
                    f"redirect_url={redirect_url[:220]}"
                )

                if code == "0":
                    success_url = redirect_url
                    logger.info(f"[HTTP登录] 登录成功回调URL: {success_url[:220]}")
                    cookie_names = [c.key for c in session.cookie_jar]
                    logger.info(f"[HTTP登录] 登录成功Cookie键: {sorted(set(cookie_names))}")

                    login_data = self._extract_login_data_from_success_url(success_url)
                    if not (login_data.get("openid") and login_data.get("access_token")):
                        resolved_url = await self._resolve_login_success_url(
                            session=session,
                            success_url=success_url,
                            referer_url=referer_url,
                        )
                        if resolved_url and resolved_url != success_url:
                            logger.info(f"[HTTP登录] check_sig解析结果URL: {resolved_url[:220]}")
                            resolved_data = self._extract_login_data_from_success_url(resolved_url)
                            login_data = self._merge_login_data(login_data, resolved_data)

                        candidate_url = resolved_url if resolved_url else success_url
                        key_candidates = self._collect_redirect_key_candidates(
                            session=session,
                            login_data=login_data,
                            success_url=candidate_url,
                        )
                        source_preview = [src for _, src in key_candidates[:8]]
                        logger.info(
                            f"[HTTP登录] 当前缺少openid/access_token，"
                            f"keystr候选数={len(key_candidates)}, 来源预览={source_preview}"
                        )
                        for idx, (keystr, source) in enumerate(key_candidates, start=1):
                            logger.info(
                                f"[HTTP登录] 尝试m_get_redirect_url keystr#{idx}: "
                                f"source={source}, len={len(keystr)}, prefix={keystr[:24]}"
                            )
                            auth_url = await self._fetch_auth_url_by_redirect_key(session, keystr)
                            if not auth_url:
                                continue
                            auth_data = self._extract_login_data_from_success_url(auth_url)
                            login_data = self._merge_login_data(login_data, auth_data)
                            if login_data.get("openid") and login_data.get("access_token"):
                                logger.info(
                                    f"[HTTP登录] m_get_redirect_url成功补齐token, source={source}"
                                )
                                break

                    if login_data.get("openid") and login_data.get("access_token"):
                        logger.info("[HTTP登录] HTTP登录成功，已拿到openid/access_token")
                        return login_data

                    logger.error(
                        "[HTTP登录] 登录成功但缺少openid/access_token，"
                        f"keys={sorted(login_data.get('full_params', {}).keys())}"
                    )
                    return None

                if code == "65":
                    logger.warning(f"[HTTP登录] 二维码已失效: {message}")
                    return None

                if code in ("66", "67"):
                    await asyncio.sleep(2)
                    continue

                logger.warning(f"[HTTP登录] 登录状态异常: code={code}, message={message}")
                await asyncio.sleep(2)

            except Exception as e:
                logger.warning(
                    f"[HTTP登录] 轮询异常: type={type(e).__name__}, repr={repr(e)}, poll={poll_index}"
                )
                await asyncio.sleep(2)

        logger.warning("[HTTP登录] 轮询超时")
        return None

    async def get_final_cookies(self, login_data):
        """??"""
        logger.info("\n正在获取最终Cookie...")
        
        # 浠巐ogin_data涓彁鍙栧弬鏁?
        openid = login_data.get("openid", "")
        access_token = login_data.get("access_token", "")
        
        if not openid or not access_token:
            logger.error("缺少必要参数 openid 或 access_token")
            return None
        
        # 鏋勯€犺姹傛暟鎹?
        login_url = "https://app.mval.qq.com/go/auth/login_by_qq?source_game_zone=agame&game_zone=agame"
        
        headers = {
            "Cookie": "clientType=9; openid=null; access_token=null;",
            "User-Agent": "mval/2.4.0.10053 Channel/10068 Manufacturer/Redmi  Mozilla/5.0 (Linux; Android 12; 23117RK66C Build/V417IR; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/101.0.4951.61 Mobile Safari/537.36",
            "Content-Type": "application/json",
            "Host": "app.mval.qq.com",
            "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip"
        }
        
        data = {
            "clienttype": 9,
            "config_params": {
                "client_dev_name": "23117RK66C",
                "lang_type": 0
            },
            "login_info": {
                "appid": 102061775,
                "openid": openid,
                "qq_info_type": 5,
                "sig": access_token,
                "uin": 0
            },
            "mappid": 10200,
            "mcode": "132f0a77d34402abc8463d60100011d19b0e",
            "source_game_zone": "agame",
            "game_zone": "agame"
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(login_url, headers=headers, json=data) as response:
                    response.raise_for_status()
                    result = await response.json()
                    
                    if result.get("result") == 0:
                        login_info = result.get("data", {}).get("login_info", {})
                        uin = login_info.get("uin", 0)
                        user_id = login_info.get("user_id", "")
                        wt = login_info.get("wt", "")
                        
                        # 鏋勯€犳渶缁坈ookie
                        final_cookie = (
                            f"clientType=9; "
                            f"uin=o{uin}; "
                            f"appid=102061775; "
                            f"acctype=qc; "
                            f"openid={openid}; "
                            f"access_token=null; "
                            f"userId={user_id}; "
                            f"accountType=5; "
                            f"tid={wt};"
                        )
                        
                        logger.info("成功获取最终Cookie")
                        
                        return {
                            "userId": user_id,
                            "tid": wt,
                            "openid": openid,
                            "uin": uin,
                            "final_cookie": final_cookie
                        }
                    else:
                        logger.error(f"获取最终Cookie失败: {result.get('msg', '未知错误')}")
                        return None
        except Exception as e:
            logger.error(f"获取最终Cookie时出错: {e}")
            return None

    async def download_image(self, url: str, user_id: str, filename: str) -> Optional[str]:
        """??"""
        temp_dir = f"./temp/valo/{user_id}"
        os.makedirs(temp_dir, exist_ok=True)
        
        filepath = os.path.join(temp_dir, filename)
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    response.raise_for_status()
                    content = await response.read()
                    with open(filepath, 'wb') as file:
                        file.write(content)
                    return filepath
        except aiohttp.ClientError as e:
            logger.error(f"下载图片失败: {e}")
            return None

    async def get_shop_items_raw(self, user_id: str, user_config: Dict[str, Any]) -> Optional[list]:
        """??"""
        logger.info(f"开始获取商店原始数据，user_id: {user_id}, userId: {user_config.get('userId', '未知')}")
        url = "https://app.mval.qq.com/go/mlol_store/agame/user_store"
        
        # 检查配置是否完整
        if not all(k in user_config for k in ['userId', 'tid']):
            logger.error("配置不完整，需要包含 userId 和 tid")
            return None
        
        # 添加时间戳参数防止缓存
        import time
        timestamp = int(time.time())
        
        headers = {
            "Accept": "*/*",
            "Upload-Draft-Interop-Version": "5",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Content-Type": "application/json",
            "User-Agent": "mval/2.3.0.10050 Channel/5 Manufacturer/Xiaomi  Mozilla/5.0 (Linux; Android 14; 23078RKD5C Build/UP1A.230905.011; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/140.0.7339.207 Mobile Safari/537.36",
            "Connection": "keep-alive",
            "Upload-Complete": "?1",
            "GH-HEADER": "1-2-105-160-0",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Cookie": f"clientType=9; uin=o105940478; appid=102061775; acctype=qc; openid=03A18A61C761D3C44890E2992BB868CE; access_token=551176E5981C1F5422A08C227D193827; userId={user_config['userId']}; accountType=5; tid={user_config['tid']}"
        }
        
        # 添加时间戳到请求数据中防止缓存
        data = {
            "_t": timestamp
        }
        
        # 设置固定的重试配置
        max_retries = 3
        timeout = 15
        
        for attempt in range(max_retries):
            try:
                logger.info(f"发送API请求到 {url} (尝试 {attempt + 1}/{max_retries}), 时间戳: {timestamp}")
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, headers=headers, json=data, timeout=aiohttp.ClientTimeout(total=timeout)) as response:
                        response.raise_for_status()
                        
                        response_data = await response.json()
                        
                        # 打印完整API响应用于调试
                        logger.info(f"API鍝嶅簲: {json.dumps(response_data, indent=2, ensure_ascii=False)}")
                        
                        if response_data['result'] == 1001 or response_data['result'] == 1003 or response_data['result'] == 999999:
                            err_msg = response_data.get('errMsg', response_data.get('msg', ''))
                            logger.error(f"API请求失败，错误码: {response_data['result']}，错误信息: {err_msg}")
                            return None
                        
                        if 'data' not in response_data:
                            logger.error("API返回数据格式不正确，缺少'data'字段")
                            return None
                        
                        if not response_data['data']:
                            logger.info("API返回数据为空")
                            return None
                        
                        if not isinstance(response_data['data'], list):
                            data = response_data['data']
                        else:
                            data = response_data['data'][0]
                        
                        goods_list = data.get('list', [])
                        
                        if not goods_list:
                            logger.info("今日商店没有商品")
                            return None
                            
                        logger.info(f"获取到 {len(goods_list)} 个商品")
                        
                        # 返回原始商品数据
                        return goods_list
                        
            except aiohttp.ClientError as e:
                logger.error(f"网络请求失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    continue
                return None
            except Exception as e:
                logger.error(f"处理失败 (尝试 {attempt + 1}/{max_retries}): {e}", exc_info=True)
                if attempt < max_retries - 1:
                    continue
                return None
        
        logger.error(f"API请求失败，已达到最大重试次数 {max_retries}")
        return None

    async def get_shop_data(self, user_id: str, user_config: Dict[str, Any], keep_file: bool = False) -> Tuple[Optional[str], Optional[str]]:
        """??"""











        logger.info(f"开始获取商店数据，user_id: {user_id}, userId: {user_config.get('userId', '未知')}")
        
        # 璋冪敤get_shop_items_raw鑾峰彇鍘熷鍟嗗搧鏁版嵁
        goods_list = await self.get_shop_items_raw(user_id, user_config)
        
        if not goods_list:
            return None, None
                
        # 澶勭悊鍟嗗搧鍥剧墖
        processed_images = []
        
        for i, goods in enumerate(goods_list):
            logger.info(f"处理商品 {i+1}/{len(goods_list)}: {goods['goods_name']}")
            
            # 涓嬭浇鑳屾櫙鍥惧拰鍟嗗搧鍥?
            bg_img_url = goods.get('bg_image')
            goods_img_url = goods.get('goods_pic')
            
            if not bg_img_url or not goods_img_url:
                logger.error("商品缺少图片URL")
                continue
                
            bg_img_path = await self.download_image(bg_img_url, user_id, 'bg.jpg')
            goods_img_path = await self.download_image(goods_img_url, user_id, 'goods.jpg')
            
            if not bg_img_path or not goods_img_path:
                logger.error("图片下载失败，跳过该商品")
                continue
                
            # 澶勭悊鍥剧墖
            try:
                # 鎵撳紑鍥剧墖 - 浣跨敤PILImage鑰屼笉鏄疘mage
                img1 = PILImage.open(bg_img_path)
                img2 = PILImage.open(goods_img_path)
                
                # 璋冩暣绗簩寮犲浘鐗囩殑澶у皬
                height = 180
                width = int((img2.width * height) / img2.height)
                img2_resized = img2.resize((width, height))
                
                # 璁＄畻灞呬腑绮樿创鐨勪綅缃?
                x = (img1.width - img2_resized.width) // 2
                y = (img1.height - img2_resized.height) // 2
                
                # 鍒涘缓鏂板浘鍍?- 浣跨敤PILImage鑰屼笉鏄疘mage
                new_img = PILImage.new('RGB', img1.size)
                new_img.paste(img1, (0, 0))
                
                # 绮樿创鍟嗗搧鍥剧墖 (鏀寔閫忔槑閫氶亾)
                if img2_resized.mode in ('RGBA', 'LA'):
                    new_img.paste(img2_resized, (x, y), mask=img2_resized)
                else:
                    new_img.paste(img2_resized, (x, y))
                
                # 缁樺埗鏂囧瓧
                draw = ImageDraw.Draw(new_img)
                
                # 鍔犺浇瀛椾綋
                try:
                    font = ImageFont.truetype(self.font_path, 36)
                except IOError:
                    logger.warning("字体加载失败，改用默认字体")
                    font = ImageFont.load_default()
                
                # 鍟嗗搧鍚嶇О
                text = goods['goods_name']
                text_bbox = draw.textbbox((0, 0), text, font=font)
                text_width = text_bbox[2] - text_bbox[0]
                text_position = (36, new_img.height - 50)
                text_color = (255, 255, 255)  # 鐧借壊
                draw.text(text_position, text, fill=text_color, font=font)
                
                # 鍟嗗搧浠锋牸
                price = goods.get('rmb_price', '0')
                price_bbox = draw.textbbox((0, 0), price, font=font)
                price_width = price_bbox[2] - price_bbox[0]
                text_position = (new_img.width - price_width - 36, new_img.height - 50)
                draw.text(text_position, price, fill=text_color, font=font)
                
                # 淇濆瓨澶勭悊鍚庣殑鍥剧墖
                processed_image_path = os.path.join(f"./temp/valo/{user_id}", f"{goods['goods_id']}.jpg")
                new_img.save(processed_image_path)
                processed_images.append(processed_image_path)
                logger.info(f"商品 {goods['goods_name']} 处理完成")
                
            except Exception as e:
                logger.error(f"图片处理失败: {e}")
            finally:
                # 娓呯悊涓存椂鏂囦欢
                for path in [bg_img_path, goods_img_path]:
                    if path and os.path.exists(path):
                        os.remove(path)
        
        if not processed_images:
            logger.error("没有商品图片处理成功")
            return None, None
            
        logger.info(f"成功处理 {len(processed_images)} 张图片")
        
        # 合并所有处理后的图片
        logger.info("开始合并图片")
        images = [PILImage.open(img_path) for img_path in processed_images]
        
        # 璁＄畻鍚堝苟鍚庣殑鍥剧墖灏哄
        max_width = max(img.width for img in images)
        total_height = sum(img.height for img in images) + (len(images) - 1) * 20  # 20px 闂磋窛
        
        # 鍒涘缓鍚堝苟鍚庣殑鍥剧墖
        merged_image = PILImage.new('RGB', (max_width, total_height), color='white')
        
        # 灏嗘墍鏈夊浘鐗囧爢鍙犲湪涓€璧?
        y_offset = 0
        for img in images:
            merged_image.paste(img, (0, y_offset))
            y_offset += img.height + 20
        
        # 保存合并后的图片
        merged_image_path = f"./temp/valo/{user_id}/merged.jpg"
        merged_image.save(merged_image_path)
        logger.info(f"合并图片保存到: {merged_image_path}")
        
        # 如果需要保留文件（Kook平台），直接返回文件路径
        if keep_file:
            logger.info("Kook平台模式，返回本地图片路径")
            return None, merged_image_path
        
        # 转换为base64
        with open(merged_image_path, 'rb') as f:
            image_bytes = f.read()
            base64_data = base64.b64encode(image_bytes).decode('utf-8')
            logger.info(f"图片转换为base64，原始大小: {len(image_bytes)} 字节, base64长度: {len(base64_data)}")
        
        # 清理临时目录
        temp_dir = f"./temp/valo/{user_id}"
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
            logger.info(f"清理临时目录: {temp_dir}")
            
        logger.info("商店图片生成完成")
        return base64_data, None

    async def get_user_config(self, user_id: str) -> Optional[Dict[str, Any]]:
        """??"""
        logger.info(f"查询用户配置，user_id: {user_id}")
        db = self.context.get_db()
        async with db.get_db() as session:
            session: AsyncSession
            result = await session.execute(
                text("SELECT userId, tid, nickname, auto_check FROM valo_users WHERE user_id = :user_id"),
                {"user_id": user_id}
            )
            row = result.fetchone()
            if row:
                logger.info(
                    f"找到用户配置: userId={row[0]}, tid={row[1][:20]}..., auto_check={row[3]}"
                )
                return {
                    'userId': row[0],
                    'tid': row[1],
                    'nickname': row[2],
                    'auto_check': row[3] if row[3] is not None else 0
                }
            else:
                logger.warning(f"未找到用户 {user_id} 的配置")
        return None

    async def save_user_config(self, user_id: str, userId: str, tid: str, nickname: Optional[str] = None):
        """??"""
        logger.info(f"保存用户配置: user_id={user_id}, userId={userId[:20]}...")
        db = self.context.get_db()
        async with db.get_db() as session:
            session: AsyncSession
            async with session.begin():
                await session.execute(
                    text("""
                        INSERT OR REPLACE INTO valo_users
                        (user_id, userId, tid, nickname, updated_at)
                        VALUES (:user_id, :userId, :tid, :nickname, CURRENT_TIMESTAMP)
                    """),
                    {"user_id": user_id, "userId": userId, "tid": tid, "nickname": nickname}
                )
                logger.info(f"用户配置保存成功: user_id={user_id}")

    async def get_at_id(self, event: AstrMessageEvent) -> Optional[str]:
        """获取消息中被 @ 的用户ID（排除机器人自身）。"""
        try:
            for seg in event.get_messages():
                if isinstance(seg, At):
                    if str(seg.qq) != event.get_self_id():
                        return str(seg.qq)
        except Exception as e:
            logger.error(f"获取被@用户ID失败: {e}")
        return None

    @filter.command("每日商店")
    async def daily_shop_command(self, event: AstrMessageEvent):
        """查询每日商店，支持 @其他用户。"""
        target_user_id = await self.get_at_id(event)
        if target_user_id:
            logger.info(f"检测到@用户，目标用户ID: {target_user_id}")

        if target_user_id:
            user_id = target_user_id
            user_config = await self.get_user_config(user_id)
            if not user_config:
                yield event.plain_result(f"用户 {target_user_id} 未绑定账号")
                return
        else:
            user_id = event.get_sender_id()
            user_config = await self.get_user_config(user_id)
            if not user_config:
                yield event.plain_result("您尚未绑定无畏契约账号，请先使用 /瓦 进行绑定")
                return

        logger.info(f"开始为用户 {user_id} 获取商店信息")
        is_kook = self._is_kook_platform(event)
        logger.info(f"当前平台: {'Kook' if is_kook else '其他'}")

        shop_data, image_path = await self.get_shop_data(user_id, user_config, keep_file=is_kook)

        if shop_data or image_path:
            try:
                if is_kook and image_path:
                    logger.info(f"Kook平台：开始上传并发送图片 {image_path}")
                    success, error_msg = await self._send_image_for_kook(event, image_path)

                    temp_dir = f"./temp/valo/{user_id}"
                    if os.path.exists(temp_dir):
                        shutil.rmtree(temp_dir)
                        logger.info(f"清理临时目录: {temp_dir}")

                    if not success:
                        logger.error(f"Kook平台图片发送失败: {error_msg}")
                        if target_user_id:
                            yield event.plain_result(f"获取用户 {target_user_id} 的商店信息失败: {error_msg}")
                        else:
                            yield event.plain_result(f"获取商店信息失败: {error_msg}")
                else:
                    import base64
                    image_data = base64.b64decode(shop_data)
                    yield event.chain_result([Image.fromBytes(image_data)])
            except Exception as e:
                logger.error(f"图片消息创建失败: {e}")
                import traceback
                logger.error(traceback.format_exc())
                if target_user_id:
                    yield event.plain_result(f"获取用户 {target_user_id} 的商店信息失败，图片生成错误")
                else:
                    yield event.plain_result("获取商店信息失败，图片生成错误")
        else:
            if target_user_id:
                yield event.plain_result(f"获取用户 {target_user_id} 的商店信息失败，可能是配置过期或网络问题")
            else:
                yield event.plain_result("获取商店信息失败，可能是配置过期或网络问题，请使用 /瓦 重新绑定")

    async def test_config_validity(self, user_id: str, user_config: Dict[str, Any]) -> bool:
        """??"""
        logger.info(f"测试用户配置有效性，user_id: {user_id}")
        try:
            # 璋冪敤鍟嗗簵API娴嬭瘯閰嶇疆鏈夋晥鎬?
            url = "https://app.mval.qq.com/go/mlol_store/agame/user_store"
            
            headers = {
                "Accept": "*/*",
                "Upload-Draft-Interop-Version": "5",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Content-Type": "application/json",
                "User-Agent": "mval/2.3.0.10050 Channel/5 Manufacturer/Xiaomi  Mozilla/5.0 (Linux; Android 14; 23078RKD5C Build/UP1A.230905.011; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/140.0.7339.207 Mobile Safari/537.36",
                "Connection": "keep-alive",
                "Upload-Complete": "?1",
                "GH-HEADER": "1-2-105-160-0",
                "Cookie": f"clientType=9; uin=o105940478; appid=102061775; acctype=qc; openid=03A18A61C761D3C44890E2992BB868CE; access_token=551176E5981C1F5422A08C227D193827; userId={user_config['userId']}; accountType=5; tid={user_config['tid']}"
            }
            
            data = {}
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=data, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    response.raise_for_status()
                    
                    response_data = await response.json()
                    logger.info(f"配置有效性测试API响应: {response_data.get('result', '未知')}")

                    if response_data.get('result') == 0:
                        logger.info("用户配置有效")
                        return True
                    else:
                        err_msg = response_data.get('errMsg', response_data.get('msg', '未知错误'))
                        logger.warning(f"用户配置无效: {err_msg}")
                        return False
                
        except Exception as e:
            logger.error(f"测试配置有效性时出错: {e}")
            return False

    @filter.command("商店监控")
    async def watchlist_command(self, event: AstrMessageEvent):
        """商店监控子命令：添加、删除、列表、查询、开启、关闭。"""
        user_id = event.get_sender_id()
        message = event.get_message_str()
        parts = message.split(maxsplit=2)

        if len(parts) < 2:
            user_config = await self.get_user_config(user_id)
            auto_check_status = "已开启" if user_config and user_config.get('auto_check') == 1 else "已关闭"

            help_text = (
                "商店监控功能\n\n"
                "可用子命令：\n"
                "/商店监控 添加 \"皮肤 武器\" - 添加监控项\n"
                "/商店监控 删除 \"皮肤 武器\" - 删除监控项\n"
                "/商店监控 列表 - 查看监控列表\n"
                "/商店监控 查询 - 立即执行一次监控查询\n"
                "/商店监控 开启 - 启用自动查询\n"
                "/商店监控 关闭 - 停用自动查询\n\n"
                f"当前自动查询状态：{auto_check_status}\n"
                f"监控时间：{self._get_config_value('monitor_time', '08:01')}\n"
                f"时区：{self._get_config_value('timezone', 'Asia/Shanghai')}"
            )
            yield event.plain_result(help_text)
            return

        sub_command = parts[1].strip()

        if sub_command == "添加" and len(parts) >= 3:
            item_name = parts[2].strip().strip('"')
            if not item_name:
                yield event.plain_result("请提供商品名称，例如：/商店监控 添加 \"侦察力量 幻象\"")
                return

            success = await self.add_watch_item(user_id, item_name)
            if success:
                yield event.plain_result(f"已添加监控项 \"{item_name}\"")
            else:
                yield event.plain_result(f"监控项 \"{item_name}\" 已存在")

        elif sub_command == "删除" and len(parts) >= 3:
            item_name = parts[2].strip().strip('"')
            if not item_name:
                yield event.plain_result("请提供商品名称，例如：/商店监控 删除 \"侦察力量 幻象\"")
                return

            success = await self.remove_watch_item(user_id, item_name)
            if success:
                yield event.plain_result(f"已从监控列表删除 \"{item_name}\"")
            else:
                yield event.plain_result(f"监控列表中不存在 \"{item_name}\"")

        elif sub_command == "列表":
            watchlist = await self.get_watchlist(user_id)
            if not watchlist:
                yield event.plain_result("您的监控列表为空\n使用 /商店监控 添加 \"商品名称\" 来添加监控项")
            else:
                items_text = "\n".join([f"  - {item['item_name']}" for item in watchlist])
                yield event.plain_result(f"您的监控列表（{len(watchlist)}项）：\n{items_text}")

        elif sub_command == "查询":
            yield event.plain_result("正在执行监控查询，请稍候...")
            try:
                unified_msg_origin = event.unified_msg_origin
                await self.check_user_watchlist(user_id, unified_msg_origin)
                yield event.plain_result("监控查询完成")
            except Exception as e:
                logger.error(f"手动监控查询失败: {e}")
                yield event.plain_result("监控查询失败，请稍后重试")

        elif sub_command == "开启":
            await self.update_auto_check(user_id, 1)
            yield event.plain_result(
                f"已开启自动查询\n"
                f"每天 {self._get_config_value('monitor_time', '08:01')} "
                f"({self._get_config_value('timezone', 'Asia/Shanghai')}) 执行\n"
                "监控到上架后会自动通知你"
            )

        elif sub_command == "关闭":
            await self.update_auto_check(user_id, 0)
            yield event.plain_result("已关闭自动查询")

        else:
            yield event.plain_result("未知子命令，请使用 /商店监控 查看帮助")


    @filter.command("\u74e6")
    async def bind_wallet_command(self, event: AstrMessageEvent):
        """绑定无畏契约账号（HTTP二维码登录）。"""
        user_id = event.get_sender_id()

        user_config = await self.get_user_config(user_id)
        if user_config:
            logger.info(f"[HTTP登录] 用户 {user_id} 已绑定，先校验配置")
            yield event.plain_result("检测到你已绑定账号，正在测试配置有效性...")
            is_valid = await self.test_config_validity(user_id, user_config)
            if is_valid:
                yield event.plain_result(
                    f"账号已绑定且配置有效。\n"
                    f"用户ID: {user_config['userId']}\n"
                    f"可直接使用 /每日商店"
                )
                return
            yield event.plain_result("检测到当前配置已失效，需要重新登录。")
        else:
            logger.info(f"[HTTP登录] 用户 {user_id} 未绑定，开始绑定流程")
            yield event.plain_result("正在生成登录二维码，请稍候...")

        try:
            http_ctx = await self.generate_qr_code_http()
            if not http_ctx:
                yield event.plain_result("生成登录二维码失败，请稍后重试")
                return

            http_session: aiohttp.ClientSession = http_ctx["session"]
            qr_filename = http_ctx["filename"]
            try:
                is_kook = self._is_kook_platform(event)
                logger.info(f"[HTTP登录] 二维码发送平台: {'Kook' if is_kook else 'Other'}")

                if is_kook:
                    success, error_msg = await self._send_image_for_kook(event, qr_filename)
                    if success:
                        yield event.plain_result("请在30秒内扫码登录")
                    else:
                        logger.error(f"[HTTP登录] Kook发送二维码失败: {error_msg}")
                        yield event.plain_result(f"发送二维码失败: {error_msg}")
                        return
                else:
                    with open(qr_filename, 'rb') as f:
                        qr_image_data = f.read()
                    yield event.chain_result([
                        Image.fromBytes(qr_image_data),
                        Plain("请在30秒内扫码登录"),
                    ])

                login_data = await self.wait_for_http_login_result(
                    session=http_session,
                    ptqrtoken=http_ctx["ptqrtoken"],
                    login_sig=http_ctx.get("login_sig", ""),
                    login_u1=http_ctx.get("u1_url", self._get_login_u1_url(self._get_login_callback_url())),
                    referer_url=http_ctx.get("login_url", self._build_login_url(self._get_login_callback_url())),
                    pt_openlogin_data=http_ctx.get("pt_openlogin_data", ""),
                    aegis_uid=http_ctx.get("aegis_uid", ""),
                    jsver=http_ctx.get("jsver", "28d22679"),
                    pt_uistyle=http_ctx.get("pt_uistyle", "35"),
                    ptlang=http_ctx.get("ptlang", "2052"),
                    timeout=30,
                )
                if not login_data:
                    yield event.plain_result("登录失败或超时，请重试")
                    return

                final_data = await self.get_final_cookies(login_data)
                if not final_data:
                    yield event.plain_result("获取最终登录信息失败，请重试")
                    return

                await self.save_user_config(
                    user_id,
                    final_data['userId'],
                    final_data['tid'],
                    final_data.get('nickname'),
                )
                yield event.plain_result(
                    f"登录成功！\n"
                    f"用户ID: {final_data['userId']}\n"
                    f"现在可以使用 /每日商店"
                )
                return
            finally:
                await http_session.close()
                logger.info("[HTTP登录] HTTP会话已关闭")
                if os.path.exists(qr_filename):
                    os.remove(qr_filename)
                    logger.info(f"[HTTP登录] 清理二维码文件: {qr_filename}")

        except Exception as e:
            logger.error(f"[HTTP登录] 绑定流程异常: type={type(e).__name__}, repr={repr(e)}")
            yield event.plain_result("登录过程出错，请稍后重试")

