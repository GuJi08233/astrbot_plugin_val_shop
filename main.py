import base64
import json
import logging
import os
import shutil
import asyncio
import aiohttp
import subprocess
import sys
from PIL import Image as PILImage, ImageDraw, ImageFont
from typing import Dict, Any, Optional
from datetime import datetime
import urllib.parse
import re

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.core.message.components import Plain, At
from astrbot.core.message.components import Image
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

# 导入Playwright
from playwright.async_api import async_playwright

# 配置日志
logger = logging.getLogger("astrbot")

@register("astrbot_plugin_val_shop", "GuJi08233", "无畏契约每日商店查询插件", "v3.2.0")
class ValorantShopPlugin(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        # 获取当前插件目录的字体文件路径
        import os
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        self.font_path = os.path.join(plugin_dir, "fontFamily.ttf")
        
        # 使用AstrBot自动传入的配置
        self.config = config if config is not None else {}
        
        # QQ登录配置
        self.LOGIN_URL = "https://xui.ptlogin2.qq.com/cgi-bin/xlogin?pt_enable_pwd=1&appid=716027609&pt_3rd_aid=102061775&daid=381&pt_skey_valid=0&style=35&force_qr=1&autorefresh=1&s_url=http%3A%2F%2Fconnect.qq.com&refer_cgi=m_authorize&ucheck=1&fall_to_wv=1&status_os=12&redirect_uri=auth%3A%2F%2Ftauth.qq.com%2F&client_id=102061775&pf=openmobile_android&response_type=token&scope=all&sdkp=a&sdkv=3.5.17.lite&sign=a6479455d3e49b597350f13f776a6288&status_machine=MjMxMTdSSzY2Qw%3D%3D&switch=1&time=1763280194&show_download_ui=true&h5sig=trobryxo8IPM0GaSQH12mowKG-CY65brFzkK7_-9EW4&loginty=6"
        
    async def initialize(self):
        """初始化插件，创建数据库表"""
        db = self.context.get_db()
        
        # 创建用户配置表
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
        
        # 创建监控列表表
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
        
        # 检查并安装Playwright
        await self.check_and_install_playwright()
        
        # 运行 playwright install-deps 安装系统依赖
        logger.info("运行 playwright install-deps 安装系统依赖...")
        try:
            subprocess.run([sys.executable, "-m", "playwright", "install-deps", "chromium"],
                         check=True, capture_output=True)
            logger.info("✅ 系统依赖安装完成")
        except subprocess.CalledProcessError as e:
            logger.error(f"系统依赖安装失败: {e}")
            logger.error(f"错误输出: {e.stderr.decode() if e.stderr else '无'}")
        except Exception as e:
            logger.error(f"系统依赖安装过程出错: {e}")
        
        # 启动定时任务调度器
        await self.setup_scheduler()
        
        logger.info("无畏契约插件初始化完成")
        
    async def terminate(self):
        """插件终止时清理"""
        # 关闭定时任务调度器
        if hasattr(self, '_scheduler') and self._scheduler:
            self._scheduler.shutdown()
            logger.info("定时任务调度器已关闭")

    def _get_config_value(self, key: str, default=None):
        """获取配置值"""
        return self.config.get(key, default)

    async def check_and_install_playwright(self):
        """检查并安装Playwright浏览器，避免重复安装"""
        logger.info("开始检查Playwright浏览器安装状态...")
        
        # 检查是否需要跳过安装（用于开发环境）
        skip_install = self._get_config_value('skip_playwright_install', False)
        if skip_install:
            logger.info("配置中设置了跳过Playwright安装检查")
            return
        
        # 检查Chromium浏览器是否已安装
        try:
            from playwright.async_api import async_playwright
            logger.info("✅ Playwright库已安装")
            
            # 使用async with正确管理异步上下文
            async with async_playwright() as p:
                try:
                    # 尝试获取Chromium路径
                    chromium_path = p.chromium.executable_path
                    if chromium_path and os.path.exists(chromium_path):
                        logger.info(f"✅ Chromium浏览器已安装，路径: {chromium_path}")
                        return  # 已安装，直接返回
                    else:
                        logger.info("Chromium浏览器未安装或路径不存在，准备安装...")
                except Exception as e:
                    logger.info(f"检查Chromium时出错: {e}，准备安装...")
                
        except ImportError:
            logger.error("❌ Playwright库未安装，请确保在requirements.txt中包含playwright")
            return
        except Exception as e:
            logger.error(f"检查Playwright时出错: {e}")
            return
        
        # 执行安装
        try:
            logger.info("开始安装Playwright浏览器组件...")
            
            # 安装Chromium浏览器
            logger.info("安装Chromium浏览器...")
            subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"],
                         check=True, capture_output=True)
            logger.info("✅ Chromium浏览器安装完成")
            
            # 安装系统依赖
            logger.info("安装系统依赖...")
            subprocess.run([sys.executable, "-m", "playwright", "install-deps", "chromium"],
                         check=True, capture_output=True)
            logger.info("✅ 系统依赖安装完成")
            
            logger.info("🎉 Playwright浏览器安装检查完成！")
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Playwright安装失败: {e}")
            logger.error(f"错误输出: {e.stderr.decode() if e.stderr else '无'}")
        except Exception as e:
            logger.error(f"Playwright安装过程出错: {e}")

    async def setup_scheduler(self):
        """设置定时任务调度器"""
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            from apscheduler.triggers.cron import CronTrigger
            
            # 获取时区配置
            timezone = self._get_config_value('timezone', 'Asia/Shanghai')
            
            # 创建带时区的调度器
            self._scheduler = AsyncIOScheduler(timezone=timezone)
            
            # 从配置中获取监控时间
            monitor_time = self._get_config_value('monitor_time', '08:01')
            hour, minute = map(int, monitor_time.split(':'))
            
            # 添加定时任务，指定时区
            self._scheduler.add_job(
                self.daily_auto_check,
                CronTrigger(hour=hour, minute=minute, timezone=timezone),
                id='daily_shop_check',
                replace_existing=True
            )
            
            self._scheduler.start()
            logger.info(f"定时任务调度器已启动，每天{monitor_time}（{timezone}时区）执行商店监控")
            
        except Exception as e:
            logger.error(f"定时任务调度器启动失败: {e}")

    async def daily_auto_check(self):
        """每日自动检查商店（定时任务）"""
        logger.info("开始执行每日商店自动检查任务")
        
        try:
            # 获取所有开启自动查询的用户
            db = self.context.get_db()
            async with db.get_db() as session:
                session: AsyncSession
                result = await session.execute(
                    text("SELECT user_id FROM valo_users WHERE auto_check = 1")
                )
                users = result.fetchall()
                
                if not users:
                    logger.info("没有用户开启自动查询")
                    return
                
                logger.info(f"找到 {len(users)} 个用户需要检查")
                
                # 遍历每个用户
                for row in users:
                    user_id = row[0]
                    try:
                        # 定时任务中，使用配置中的机器人ID构建会话ID
                        bot_id = self._get_config_value('bot_id', 'default')
                        unified_msg_origin = f"{bot_id}:FriendMessage:{user_id}"
                        logger.info(f"定时任务使用会话ID: {unified_msg_origin}")
                        await self.check_user_watchlist(user_id, unified_msg_origin)
                    except Exception as e:
                        logger.error(f"检查用户 {user_id} 的监控列表时出错: {e}")
                        continue
                        
        except Exception as e:
            logger.error(f"每日自动检查任务执行失败: {e}")

    async def check_user_watchlist(self, user_id: str, unified_msg_origin: str = None):
        """检查单个用户的监控列表"""
        logger.info(f"检查用户 {user_id} 的监控列表")
        
        # 获取用户配置
        user_config = await self.get_user_config(user_id)
        if not user_config:
            logger.warning(f"用户 {user_id} 未绑定账户")
            return
        
        # 获取监控列表
        watchlist = await self.get_watchlist(user_id)
        if not watchlist:
            logger.info(f"用户 {user_id} 的监控列表为空")
            return
        
        # 获取商店商品
        goods_list = self.get_shop_items_raw(user_id, user_config)
        if not goods_list:
            logger.info(f"用户 {user_id} 的商店数据为空")
            return
        
        # 匹配监控商品
        matched_items = []
        watchlist_names = [item['item_name'] for item in watchlist]
        
        logger.info(f"监控列表: {watchlist_names}")
        logger.info(f"商店商品: {[goods.get('goods_name', '') for goods in goods_list]}")
        
        for goods in goods_list:
            goods_name = goods.get('goods_name', '')
            logger.info(f"检查商品: {goods_name}")
            for watch_name in watchlist_names:
                logger.info(f"匹配监控项: {watch_name} vs {goods_name}")
                if watch_name in goods_name or goods_name in watch_name:
                    matched_items.append({
                        'name': goods_name,
                        'price': goods.get('rmb_price', '0')
                    })
                    logger.info(f"匹配成功: {goods_name}")
                    break
        
        # 如果有匹配的商品，发送通知
        if matched_items:
            logger.info(f"用户 {user_id} 有 {len(matched_items)} 个监控商品上架")
            await self.send_notification(user_id, matched_items, unified_msg_origin)
        else:
            logger.info(f"用户 {user_id} 没有监控商品上架")

    async def send_notification(self, user_id: str, matched_items: list, unified_msg_origin: str = None):
        """发送监控通知"""
        try:
            # 获取当前日期
            from datetime import datetime
            current_date = datetime.now().strftime("%Y-%m-%d")
            
            # 构建通知内容
            items_text = "\n".join([f"  🎯 {item['name']} ({item['price']})" for item in matched_items])
            matched_names = [item['name'] for item in matched_items]
            
            notification_text = (
                f"🎉 {current_date} 商店监控通知！\n\n"
                f"✨ 以下监控商品已上架：\n"
                f"{items_text}\n\n"
                f"💰 快去看看吧！使用 /每日商店 查看详情\n\n"
                f"🔍 匹配的商品：{', '.join(matched_names)}"
            )
            
            # 使用context的send_message方法发送通知
            # 使用传入的unified_msg_origin，如果没有则尝试构建
            from astrbot.api.event import MessageChain
            
            if unified_msg_origin:
                session_id = unified_msg_origin
            else:
                # 如果没有提供unified_msg_origin，尝试构建默认格式
                session_id = f"qq/{user_id}"
            
            message_chain = MessageChain().message(notification_text)
            await self.context.send_message(session_id, message_chain)
            logger.info(f"已发送通知给用户 {user_id}, 会话ID: {session_id}")
            
        except Exception as e:
            logger.error(f"发送通知失败: {e}")

    async def add_watch_item(self, user_id: str, item_name: str) -> bool:
        """添加监控项"""
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
                        return False  # 已存在
                    
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
        """删除监控项"""
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
        """获取用户监控列表"""
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
                
                logger.info(f"用户 {user_id} 的监控列表: {len(watchlist)} 项")
                return watchlist
                
        except Exception as e:
            logger.error(f"获取监控列表失败: {e}")
            return []

    async def update_auto_check(self, user_id: str, status: int):
        """更新用户自动查询状态"""
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

    async def save_qr_screenshot(self, page, filename=None):
        """保存二维码截图"""
        try:
            if filename is None:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"qr_code_{timestamp}.png"
            
            # 等待二维码元素加载
            qr_element = await page.wait_for_selector("#qrimg", state="visible", timeout=20000)
            
            # 截图二维码元素
            await qr_element.screenshot(path=filename)
            
            logger.info(f"✅ 二维码截图已保存: {filename}")
            return filename
        except Exception as e:
            logger.error(f"❌ 保存二维码截图失败: {e}")
            return None

    async def get_final_cookies(self, login_data):
        """使用获取到的登录凭证调用mval API获取最终的cookie"""
        logger.info("\n正在获取最终cookie...")
        
        # 从login_data中提取参数
        openid = login_data.get("openid", "")
        access_token = login_data.get("access_token", "")
        
        if not openid or not access_token:
            logger.error("错误：缺少必要的参数 openid 或 access_token")
            return None
        
        # 构造请求数据
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
                        
                        # 构造最终cookie
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
                        
                        logger.info("✅ 成功获取最终cookie!")
                        
                        return {
                            "userId": user_id,
                            "tid": wt,
                            "openid": openid,
                            "uin": uin,
                            "final_cookie": final_cookie
                        }
                    else:
                        logger.error(f"获取最终cookie失败: {result.get('msg', '未知错误')}")
                        return None
        except Exception as e:
            logger.error(f"获取最终cookie时出错: {e}")
            return None

    async def generate_qr_code(self):
        """生成二维码截图，返回浏览器对象和页面对象"""
        p = await async_playwright().__aenter__()
        
        # 尝试多种浏览器启动策略
        browser = None
        context = None
        page = None
        
        # 策略1: 尝试使用系统安装的 Chromium
        try:
            logger.info("尝试使用系统安装的 Chromium...")
            browser = await p.chromium.launch(
                headless=True,
                executable_path="/usr/bin/chromium-browser"  # 常见的系统 Chromium 路径
            )
            logger.info("✅ 系统 Chromium 启动成功")
        except Exception as e:
            logger.warning(f"系统 Chromium 启动失败: {e}")
            
            # 策略2: 尝试使用 Playwright 的 Chromium 但添加更多参数
            try:
                logger.info("尝试使用 Playwright Chromium（带额外参数）...")
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        '--disable-dev-shm-usage',
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-gpu',
                        '--disable-web-security',
                        '--disable-features=VizDisplayCompositor',
                        '--disable-background-timer-throttling',
                        '--disable-backgrounding-occluded-windows',
                        '--disable-renderer-backgrounding',
                        '--disable-extensions',
                        '--disable-plugins',
                        '--disable-default-apps',
                        '--no-first-run',
                        '--no-default-browser-check',
                        '--disable-background-networking',
                        '--disable-sync',
                        '--disable-translate',
                        '--hide-scrollbars',
                        '--mute-audio',
                        '--no-zygote',
                        '--single-process',
                        '--disable-ipc-flooding-protection',
                        '--disable-logging',
                        '--disable-permissions-api',
                        '--disable-notifications',
                        '--disable-popup-blocking',
                        '--disable-prompt-on-repost',
                        '--disable-component-extensions-with-background-pages',
                        '--disable-background-fetch',
                        '--disable-background-sync',
                        '--disable-client-side-phishing-detection',
                        '--disable-default-apps',
                        '--disable-hang-monitor',
                        '--disable-popup-blocking',
                        '--disable-prompt-on-repost',
                        '--disable-web-resources',
                        '--enable-automation',
                        '--no-default-browser-check',
                        '--no-first-run',
                        '--disable-features=TranslateUI',
                        '--disable-features=Translate',
                        '--disable-blink-features=AutomationControlled',
                        '--disable-features=IsolateOrigins,site-per-process'
                    ]
                )
                logger.info("✅ Playwright Chromium 启动成功")
            except Exception as e2:
                logger.warning(f"Playwright Chromium 启动失败: {e2}")
                
                # 策略3: 尝试使用 Firefox
                try:
                    logger.info("尝试使用 Firefox...")
                    browser = await p.firefox.launch(headless=True)
                    logger.info("✅ Firefox 启动成功")
                except Exception as e3:
                    logger.warning(f"Firefox 启动失败: {e3}")
                    
                    # 策略4: 尝试使用 WebKit
                    try:
                        logger.info("尝试使用 WebKit...")
                        browser = await p.webkit.launch(headless=True)
                        logger.info("✅ WebKit 启动成功")
                    except Exception as e4:
                        logger.error(f"所有浏览器启动策略都失败了: {e4}")
                        await p.__aexit__(None, None, None)
                        return None, None, None
        
        try:
            # 创建浏览器上下文
            context = await browser.new_context(
                viewport={'width': 375, 'height': 667},
                user_agent="Mozilla/5.0 (Linux; Android 12; 23117RK66C Build/V417IR; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/101.0.4951.61 Mobile Safari/537.36 tencent_game_emulator"
            )
            page = await context.new_page()

            # 使用更宽松的页面加载策略
            try:
                await page.goto(self.LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                logger.warning(f"页面加载失败，尝试备用方案: {e}")
                # 尝试不等待任何加载状态
                await page.goto(self.LOGIN_URL, wait_until="commit", timeout=20000)
            
            # 等待页面完全加载后再查找二维码
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except Exception as e:
                logger.warning(f"等待网络空闲超时，继续尝试查找二维码: {e}")
            
            # 尝试多种方式等待二维码加载
            qr_element = None
            for attempt in range(3):
                try:
                    logger.info(f"尝试查找二维码元素 (第 {attempt + 1} 次)")
                    qr_element = await page.wait_for_selector("#qrimg", state="visible", timeout=10000)
                    if qr_element:
                        break
                except Exception as e:
                    logger.warning(f"第 {attempt + 1} 次查找二维码失败: {e}")
                    if attempt < 2:
                        # 等待一下再重试
                        await asyncio.sleep(2)
                        # 尝试刷新页面
                        await page.reload(wait_until="domcontentloaded", timeout=15000)
            
            if not qr_element:
                logger.error("无法找到二维码元素")
                await browser.close()
                return None, None, None
            qr_img_element = await page.query_selector("#qrimg")
            qr_img_src = await qr_img_element.get_attribute("src")
            if not qr_img_src:
                logger.error("错误：未能找到二维码图片的 src 属性。")
                await browser.close()
                return None, None, None
            logger.info("二维码已加载成功！")
            
            # 保存二维码截图
            qr_filename = await self.save_qr_screenshot(page)
            if not qr_filename:
                await browser.close()
                return None, None, None
                
            # 返回文件名、浏览器对象和页面对象
            return qr_filename, browser, page
            
        except Exception as e:
            logger.error(f"加载二维码时出错: {e}")
            if browser:
                await browser.close()
            return None, None, None

    async def wait_for_login_result(self, user_id: str, event: AstrMessageEvent):
        """异步等待登录结果"""
        if not hasattr(self, '_login_browser') or not hasattr(self, '_login_page'):
            logger.error("登录浏览器或页面对象不存在")
            return
            
        browser = self._login_browser
        page = self._login_page
        
        login_successful = asyncio.Event()
        login_failed = asyncio.Event()
        login_data = None

        # 监听响应事件，用于轮询状态
        async def handle_response(response):
            nonlocal login_data
            if "ptqrlogin" in response.url:
                try:
                    text = await response.text()
                    if "登录成功" in text:
                        # 从响应文本中提取登录成功后的URL
                        url_match = re.search(r"ptuiCB\('0','0','([^']+)'", text)
                        if url_match:
                            success_url = url_match.group(1)
                            
                            # 解析URL中的参数
                            parsed_url = urllib.parse.urlparse(success_url)
                            fragment = parsed_url.fragment
                            
                            params = {}
                            if fragment:
                                if fragment.startswith('#&'):
                                    fragment = fragment[2:]
                                
                                query_string = fragment.replace('#&', '&')
                                parsed_params = urllib.parse.parse_qs(query_string)
                                
                                for key, value in parsed_params.items():
                                    if value:
                                        params[key] = value[0]
                            
                            # 提取关键参数
                            login_data = {
                                "openid": params.get("openid", ""),
                                "appid": params.get("appid", ""),
                                "access_token": params.get("access_token", ""),
                                "pay_token": params.get("pay_token", ""),
                                "key": params.get("key", ""),
                                "redirect_uri_key": params.get("redirect_uri_key", ""),
                                "expires_in": params.get("expires_in", "7776000"),
                                "pf": params.get("pf", "openmobile_android"),
                                "status_os": params.get("status_os", "12"),
                                "status_machine": params.get("status_machine", ""),
                                "full_params": params
                            }
                            
                            logger.info("✅ QQ登录成功!")
                            login_successful.set()
                    elif "二维码已失效" in text:
                        logger.error("❌ 二维码已失效。")
                        login_failed.set()
                except Exception as e:
                    logger.error(f"处理响应时出错: {e}")

        # 添加事件监听器
        page.on("response", handle_response)

        # 等待登录成功或失败，或者超时
        try:
            done, pending = await asyncio.wait(
                [
                    asyncio.create_task(login_successful.wait(), name="login_successful"),
                    asyncio.create_task(login_failed.wait(), name="login_failed"),
                ],
                return_when=asyncio.FIRST_COMPLETED,
                timeout=30,  # 30秒超时
            )

            for task in done:
                if task.get_name() == "login_successful":
                    logger.info("--- 登录流程结束 (成功) ---")
                    break
                elif task.get_name() == "login_failed":
                    logger.info("--- 登录流程结束 (失败) ---")
                    break

        except asyncio.TimeoutError:
            logger.error("⏰ 轮询超时，登录可能未完成。")

        await browser.close()
        
        # 清理全局变量
        if hasattr(self, '_login_browser'):
            delattr(self, '_login_browser')
        if hasattr(self, '_login_page'):
            delattr(self, '_login_page')

        if login_successful.is_set() and login_data:
            # 获取最终cookie
            final_data = await self.get_final_cookies(login_data)
            if final_data:
                # 保存用户配置
                await self.save_user_config(
                    user_id,
                    final_data['userId'],
                    final_data['tid'],
                    final_data.get('nickname')
                )
                
                # 发送登录成功消息
                try:
                    # 使用context的send_message方法发送消息
                    await self.context.send_message(
                        event.get_message_type(),
                        event.get_target_id(),
                        f"登录成功！\n用户ID: {final_data['userId']}\n现在可以使用 /每日商店 查看每日商店了"
                    )
                except Exception as e:
                    logger.error(f"发送登录成功消息失败: {e}")
        else:
            # 发送登录失败消息
            try:
                # 使用context的send_message方法发送消息
                await self.context.send_message(
                    event.get_message_type(),
                    event.get_target_id(),
                    "登录失败或超时，请重试"
                )
            except Exception as e:
                logger.error(f"发送登录失败消息失败: {e}")

    async def qr_login(self):
        """执行二维码登录流程（保留原方法以兼容其他可能的调用）"""
        # 生成二维码并获取浏览器对象
        qr_filename, browser, page = await self.generate_qr_code()
        if not qr_filename or not browser or not page:
            return None, None
            
        # 等待登录结果
        login_successful = asyncio.Event()
        login_failed = asyncio.Event()
        login_data = None

        # 监听响应事件，用于轮询状态
        async def handle_response(response):
            nonlocal login_data
            if "ptqrlogin" in response.url:
                try:
                    text = await response.text()
                    if "登录成功" in text:
                        # 从响应文本中提取登录成功后的URL
                        url_match = re.search(r"ptuiCB\('0','0','([^']+)'", text)
                        if url_match:
                            success_url = url_match.group(1)
                            
                            # 解析URL中的参数
                            parsed_url = urllib.parse.urlparse(success_url)
                            fragment = parsed_url.fragment
                            
                            params = {}
                            if fragment:
                                if fragment.startswith('#&'):
                                    fragment = fragment[2:]
                                
                                query_string = fragment.replace('#&', '&')
                                parsed_params = urllib.parse.parse_qs(query_string)
                                
                                for key, value in parsed_params.items():
                                    if value:
                                        params[key] = value[0]
                            
                            # 提取关键参数
                            login_data = {
                                "openid": params.get("openid", ""),
                                "appid": params.get("appid", ""),
                                "access_token": params.get("access_token", ""),
                                "pay_token": params.get("pay_token", ""),
                                "key": params.get("key", ""),
                                "redirect_uri_key": params.get("redirect_uri_key", ""),
                                "expires_in": params.get("expires_in", "7776000"),
                                "pf": params.get("pf", "openmobile_android"),
                                "status_os": params.get("status_os", "12"),
                                "status_machine": params.get("status_machine", ""),
                                "full_params": params
                            }
                            
                            logger.info("✅ QQ登录成功!")
                            login_successful.set()
                    elif "二维码已失效" in text:
                        logger.error("❌ 二维码已失效。")
                        login_failed.set()
                except Exception as e:
                    logger.error(f"处理响应时出错: {e}")

        # 添加事件监听器
        page.on("response", handle_response)

        # 等待登录成功或失败，或者超时
        try:
            done, pending = await asyncio.wait(
                [
                    asyncio.create_task(login_successful.wait(), name="login_successful"),
                    asyncio.create_task(login_failed.wait(), name="login_failed"),
                ],
                return_when=asyncio.FIRST_COMPLETED,
                timeout=30,  # 30秒超时
            )

            for task in done:
                if task.get_name() == "login_successful":
                    logger.info("--- 登录流程结束 (成功) ---")
                    break
                elif task.get_name() == "login_failed":
                    logger.info("--- 登录流程结束 (失败) ---")
                    break

        except asyncio.TimeoutError:
            logger.error("⏰ 轮询超时，登录可能未完成。")

        await browser.close()

        if login_successful.is_set() and login_data:
            # 获取最终cookie
            final_data = await self.get_final_cookies(login_data)
            if final_data:
                return qr_filename, final_data
        
        return qr_filename, None

    async def download_image(self, url: str, user_id: str, filename: str) -> Optional[str]:
        """下载图片到临时目录"""
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
        """获取商店原始商品数据"""
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
                        
                        # 打印完整的API响应用于调试
                        logger.info(f"API响应: {json.dumps(response_data, indent=2, ensure_ascii=False)}")
                        
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
                            
                        logger.info(f"获取到 {len(goods_list)} 件商品")
                        
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

    async def get_shop_data(self, user_id: str, user_config: Dict[str, Any]) -> Optional[str]:
        """获取商店信息并生成图片的base64编码"""
        logger.info(f"开始获取商店数据，user_id: {user_id}, userId: {user_config.get('userId', '未知')}")
        
        # 调用get_shop_items_raw获取原始商品数据
        goods_list = await self.get_shop_items_raw(user_id, user_config)
        
        if not goods_list:
            return None
                
        # 处理商品图片
        processed_images = []
        
        for i, goods in enumerate(goods_list):
            logger.info(f"处理商品 {i+1}/{len(goods_list)}: {goods['goods_name']}")
            
            # 下载背景图和商品图
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
                
            # 处理图片
            try:
                # 打开图片 - 使用PILImage而不是Image
                img1 = PILImage.open(bg_img_path)
                img2 = PILImage.open(goods_img_path)
                
                # 调整第二张图片的大小
                height = 180
                width = int((img2.width * height) / img2.height)
                img2_resized = img2.resize((width, height))
                
                # 计算居中粘贴的位置
                x = (img1.width - img2_resized.width) // 2
                y = (img1.height - img2_resized.height) // 2
                
                # 创建新图像 - 使用PILImage而不是Image
                new_img = PILImage.new('RGB', img1.size)
                new_img.paste(img1, (0, 0))
                
                # 粘贴商品图片 (支持透明通道)
                if img2_resized.mode in ('RGBA', 'LA'):
                    new_img.paste(img2_resized, (x, y), mask=img2_resized)
                else:
                    new_img.paste(img2_resized, (x, y))
                
                # 绘制文字
                draw = ImageDraw.Draw(new_img)
                
                # 加载字体
                try:
                    font = ImageFont.truetype(self.font_path, 36)
                except IOError:
                    logger.warning("无法加载指定字体，使用默认字体")
                    font = ImageFont.load_default()
                
                # 商品名称
                text = goods['goods_name']
                text_bbox = draw.textbbox((0, 0), text, font=font)
                text_width = text_bbox[2] - text_bbox[0]
                text_position = (36, new_img.height - 50)
                text_color = (255, 255, 255)  # 白色
                draw.text(text_position, text, fill=text_color, font=font)
                
                # 商品价格
                price = goods.get('rmb_price', '0')
                price_bbox = draw.textbbox((0, 0), price, font=font)
                price_width = price_bbox[2] - price_bbox[0]
                text_position = (new_img.width - price_width - 36, new_img.height - 50)
                draw.text(text_position, price, fill=text_color, font=font)
                
                # 保存处理后的图片
                processed_image_path = os.path.join(f"./temp/valo/{user_id}", f"{goods['goods_id']}.jpg")
                new_img.save(processed_image_path)
                processed_images.append(processed_image_path)
                logger.info(f"商品 {goods['goods_name']} 处理完成")
                
            except Exception as e:
                logger.error(f"图片处理失败: {e}")
            finally:
                # 清理临时文件
                for path in [bg_img_path, goods_img_path]:
                    if path and os.path.exists(path):
                        os.remove(path)
        
        if not processed_images:
            logger.error("没有商品图片处理成功")
            return None
            
        logger.info(f"成功处理 {len(processed_images)} 张商品图片")
        
        # 合并所有处理后的图片
        logger.info("合并所有图片")
        images = [PILImage.open(img_path) for img_path in processed_images]
        
        # 计算合并后的图片尺寸
        max_width = max(img.width for img in images)
        total_height = sum(img.height for img in images) + (len(images) - 1) * 20  # 20px 间距
        
        # 创建合并后的图片
        merged_image = PILImage.new('RGB', (max_width, total_height), color='white')
        
        # 将所有图片堆叠在一起
        y_offset = 0
        for img in images:
            merged_image.paste(img, (0, y_offset))
            y_offset += img.height + 20
        
        # 保存合并后的图片
        merged_image_path = f"./temp/valo/{user_id}/merged.jpg"
        merged_image.save(merged_image_path)
        logger.info(f"合并图片保存到: {merged_image_path}")
        
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
        return base64_data

    async def get_user_config(self, user_id: str) -> Optional[Dict[str, Any]]:
        """从数据库获取用户配置"""
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
                logger.info(f"找到用户配置: userId={row[0]}, tid={row[1][:20]}..., auto_check={row[3]}")
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
        """保存用户配置到数据库"""
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
        """从消息中获取被@的用户ID"""
        try:
            # 遍历消息组件，查找At类型的组件
            for seg in event.get_messages():
                if isinstance(seg, At):
                    # 排除机器人自己
                    if str(seg.qq) != event.get_self_id():
                        return str(seg.qq)
        except Exception as e:
            logger.error(f"获取被@用户ID失败: {e}")
        return None

    @filter.command("每日商店")
    async def daily_shop_command(self, event: AstrMessageEvent):
        """每日商店指令处理"""
        # 检查是否是 @ 某人的情况
        target_user_id = await self.get_at_id(event)
        
        if target_user_id:
            logger.info(f"检测到@用户，目标用户ID: {target_user_id}")
        
        # 确定查询的用户ID
        if target_user_id:
            # 查询其他用户的商店
            user_id = target_user_id
            user_config = await self.get_user_config(user_id)
            if not user_config:
                yield event.plain_result(f"未找到用户 {target_user_id} 的配置")
                return
        else:
            # 查询自己的商店
            user_id = event.get_sender_id()
            user_config = await self.get_user_config(user_id)
            if not user_config:
                yield event.plain_result("您尚未绑定无畏契约账户信息，请使用 /瓦 指令进行绑定")
                return

        logger.info(f"开始为用户 {user_id} 获取商店信息")
        
        # 获取商店信息
        shop_data = await self.get_shop_data(user_id, user_config)
        
        if shop_data:
            # 发送图片消息
            try:
                # 解码base64数据
                import base64
                image_data = base64.b64decode(shop_data)
                # 使用Image.fromBytes创建图片组件
                yield event.chain_result([Image.fromBytes(image_data)])
            except Exception as e:
                logger.error(f"图片消息创建失败: {e}")
                if target_user_id:
                    yield event.plain_result(f"获取用户 {target_user_id} 的商店信息失败，图片生成错误")
                else:
                    yield event.plain_result("获取商店信息失败，图片生成错误")
        else:
            # 获取商店信息失败
            if target_user_id:
                yield event.plain_result(f"获取用户 {target_user_id} 的商店信息失败，可能是配置过期或网络问题")
            else:
                yield event.plain_result("获取商店信息失败，可能是配置过期或网络问题，请使用 /瓦 重新绑定")

    async def test_config_validity(self, user_id: str, user_config: Dict[str, Any]) -> bool:
        """测试用户配置是否有效"""
        logger.info(f"测试用户配置有效性，user_id: {user_id}")
        try:
            # 调用商店API测试配置有效性
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
                    
                    # 检查API返回结果
                    if response_data.get('result') == 0:
                        logger.info("✅ 用户配置有效")
                        return True
                    else:
                        err_msg = response_data.get('errMsg', response_data.get('msg', '未知错误'))
                        logger.warning(f"❌ 用户配置无效: {err_msg}")
                        return False
                
        except Exception as e:
            logger.error(f"测试配置有效性时出错: {e}")
            return False

    @filter.command("商店监控")
    async def watchlist_command(self, event: AstrMessageEvent):
        """商店监控指令主入口"""
        user_id = event.get_sender_id()
        message = event.get_message_str()
        
        # 解析指令参数
        parts = message.split(maxsplit=2)
        
        if len(parts) < 2:
            # 显示帮助信息
            user_config = await self.get_user_config(user_id)
            auto_check_status = "已开启" if user_config and user_config.get('auto_check') == 1 else "已关闭"
            
            help_text = (
                "🎯 商店监控功能\n\n"
                "可用子命令：\n"
                "• /商店监控 添加 \"皮肤 武器\" - 添加监控项\n"
                "• /商店监控 删除 \"皮肤 武器\" - 删除监控项\n"
                "• /商店监控 列表 - 查看监控列表\n"
                "• /商店监控 查询 - 立即执行一次监控查询\n"
                "• /商店监控 开启 - 启用自动查询\n"
                "• /商店监控 关闭 - 停用自动查询\n\n"
                f"当前自动查询状态：{auto_check_status}\n"
                f"⏰ 自动查询时间：每天{self._get_config_value('monitor_time', '08:01')}\n"
                f"🌍 时区设置：{self._get_config_value('timezone', 'Asia/Shanghai')}"
            )
            yield event.plain_result(help_text)
            return
        
        sub_command = parts[1].strip()
        
        if sub_command == "添加" and len(parts) >= 3:
            # 添加监控项
            item_name = parts[2].strip().strip('"')
            if not item_name:
                yield event.plain_result("❌ 请提供商品名称，例如：/商店监控 添加 \"侦察力量 幻象\"")
                return
            
            success = await self.add_watch_item(user_id, item_name)
            if success:
                yield event.plain_result(f"✅ 已添加 \"{item_name}\" 到监控列表")
            else:
                yield event.plain_result(f"⚠️ \"{item_name}\" 已在监控列表中")
                
        elif sub_command == "删除" and len(parts) >= 3:
            # 删除监控项
            item_name = parts[2].strip().strip('"')
            if not item_name:
                yield event.plain_result("❌ 请提供商品名称，例如：/商店监控 删除 \"侦察力量 幻象\"")
                return
            
            success = await self.remove_watch_item(user_id, item_name)
            if success:
                yield event.plain_result(f"✅ 已从监控列表删除 \"{item_name}\"")
            else:
                yield event.plain_result(f"❌ 监控列表中不存在 \"{item_name}\"")
                
        elif sub_command == "列表":
            # 查看监控列表
            watchlist = await self.get_watchlist(user_id)
            if not watchlist:
                yield event.plain_result("🎯 您的监控列表为空\n使用 /商店监控 添加 \"商品名称\" 来添加监控项")
            else:
                items_text = "\n".join([f"  • {item['item_name']}" for item in watchlist])
                yield event.plain_result(f"🎯 您的监控列表 ({len(watchlist)}项)：\n{items_text}")
                
        elif sub_command == "查询":
            # 立即执行一次监控查询
            yield event.plain_result("🔍 正在执行监控查询，请稍候...")
            
            try:
                # 获取unified_msg_origin用于后续通知发送
                unified_msg_origin = event.unified_msg_origin
                await self.check_user_watchlist(user_id, unified_msg_origin)
                yield event.plain_result("✅ 监控查询完成")
            except Exception as e:
                logger.error(f"手动监控查询失败: {e}")
                yield event.plain_result("❌ 监控查询失败，请稍后重试")
                
        elif sub_command == "开启":
            # 开启自动查询
            await self.update_auto_check(user_id, 1)
            yield event.plain_result(
                f"✅ 每日自动查询已开启\n"
                f"⏰ 将在每天{self._get_config_value('monitor_time', '08:01')}（{self._get_config_value('timezone', 'Asia/Shanghai')}时区）执行\n"
                "📢 查询到商品才会通知，无匹配不打扰"
            )
            
        elif sub_command == "关闭":
            # 关闭自动查询
            await self.update_auto_check(user_id, 0)
            yield event.plain_result("✅ 每日自动查询已关闭")
            
        else:
            yield event.plain_result("❌ 未知子命令，请使用 /商店监控 查看帮助")

    @filter.command("瓦")
    async def bind_wallet_command(self, event: AstrMessageEvent):
        """绑定无畏契约钱包指令 - 发送二维码登录"""
        user_id = event.get_sender_id()
        
        # 检查用户是否已绑定
        user_config = await self.get_user_config(user_id)
        
        if user_config:
            # 用户已绑定，测试配置有效性
            logger.info(f"用户 {user_id} 已绑定，测试配置有效性...")
            yield event.plain_result("检测到您已绑定账户，正在测试配置有效性...")
            
            is_valid = await self.test_config_validity(user_id, user_config)
            
            if is_valid:
                # 配置有效
                logger.info(f"用户 {user_id} 的配置有效")
                yield event.plain_result(
                    f"✅ 您的账户已绑定且配置有效！\n"
                    f"用户ID: {user_config['userId']}\n"
                    f"可以直接使用 /每日商店 查看商店内容"
                )
                return
            else:
                # 配置无效，需要重新登录
                logger.warning(f"用户 {user_id} 的配置无效，需要重新登录")
                yield event.plain_result("⚠️ 您的配置已失效，需要重新登录...")
        else:
            # 用户未绑定，显示提示
            logger.info(f"用户 {user_id} 未绑定，开始绑定流程")
            yield event.plain_result("正在生成登录二维码，请稍候...")
        
        # 添加重试机制
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                # 生成二维码并获取浏览器对象
                qr_filename, browser, page = await self.generate_qr_code()
                
                if qr_filename and browser and page:
                    # 发送二维码图片
                    try:
                        with open(qr_filename, 'rb') as f:
                            qr_image_data = f.read()
                        
                        # 发送二维码图片和提示
                        yield event.chain_result([
                            Image.fromBytes(qr_image_data),
                            Plain("请在30秒内扫码登录")
                        ])
                        
                        # 清理二维码文件
                        if os.path.exists(qr_filename):
                            os.remove(qr_filename)
                            logger.info(f"清理二维码文件: {qr_filename}")
                            
                    except Exception as e:
                        logger.error(f"发送二维码失败: {e}")
                        await browser.close()
                        yield event.plain_result("发送二维码失败，请重试")
                        return
                    
                    # 等待登录结果
                    login_successful = asyncio.Event()
                    login_failed = asyncio.Event()
                    login_data = None

                    # 监听响应事件，用于轮询状态
                    async def handle_response(response):
                        nonlocal login_data
                        if "ptqrlogin" in response.url:
                            try:
                                text = await response.text()
                                if "登录成功" in text:
                                    # 从响应文本中提取登录成功后的URL
                                    url_match = re.search(r"ptuiCB\('0','0','([^']+)'", text)
                                    if url_match:
                                        success_url = url_match.group(1)
                                        
                                        # 解析URL中的参数
                                        parsed_url = urllib.parse.urlparse(success_url)
                                        fragment = parsed_url.fragment
                                        
                                        params = {}
                                        if fragment:
                                            if fragment.startswith('#&'):
                                                fragment = fragment[2:]
                                            
                                            query_string = fragment.replace('#&', '&')
                                            parsed_params = urllib.parse.parse_qs(query_string)
                                            
                                            for key, value in parsed_params.items():
                                                if value:
                                                    params[key] = value[0]
                                        
                                        # 提取关键参数
                                        login_data = {
                                            "openid": params.get("openid", ""),
                                            "appid": params.get("appid", ""),
                                            "access_token": params.get("access_token", ""),
                                            "pay_token": params.get("pay_token", ""),
                                            "key": params.get("key", ""),
                                            "redirect_uri_key": params.get("redirect_uri_key", ""),
                                            "expires_in": params.get("expires_in", "7776000"),
                                            "pf": params.get("pf", "openmobile_android"),
                                            "status_os": params.get("status_os", "12"),
                                            "status_machine": params.get("status_machine", ""),
                                            "full_params": params
                                        }
                                        
                                        logger.info("✅ QQ登录成功!")
                                        login_successful.set()
                                elif "二维码已失效" in text:
                                    logger.error("❌ 二维码已失效。")
                                    login_failed.set()
                            except Exception as e:
                                logger.error(f"处理响应时出错: {e}")

                    # 添加事件监听器
                    page.on("response", handle_response)

                    # 等待登录成功或失败，或者超时
                    try:
                        done, pending = await asyncio.wait(
                            [
                                asyncio.create_task(login_successful.wait(), name="login_successful"),
                                asyncio.create_task(login_failed.wait(), name="login_failed"),
                            ],
                            return_when=asyncio.FIRST_COMPLETED,
                            timeout=30,  # 30秒超时
                        )

                        for task in done:
                            if task.get_name() == "login_successful":
                                logger.info("--- 登录流程结束 (成功) ---")
                                break
                            elif task.get_name() == "login_failed":
                                logger.info("--- 登录流程结束 (失败) ---")
                                break

                    except asyncio.TimeoutError:
                        logger.error("⏰ 轮询超时，登录可能未完成。")

                    await browser.close()

                    if login_successful.is_set() and login_data:
                        # 获取最终cookie
                        final_data = await self.get_final_cookies(login_data)
                        if final_data:
                            # 保存用户配置
                            await self.save_user_config(
                                user_id,
                                final_data['userId'],
                                final_data['tid'],
                                final_data.get('nickname')
                            )
                            
                            yield event.plain_result(
                                f"登录成功！\n"
                                f"用户ID: {final_data['userId']}\n"
                                f"现在可以使用 /每日商店 查看每日商店了"
                            )
                            return  # 成功，退出重试循环
                        else:
                            yield event.plain_result("获取最终登录信息失败，请重试")
                    else:
                        yield event.plain_result("登录失败或超时，请重试")
                        return  # 失败，退出重试循环
                else:
                    if retry_count < max_retries - 1:
                        retry_count += 1
                        logger.warning(f"二维码生成失败，正在重试 ({retry_count}/{max_retries})...")
                        yield event.plain_result(f"二维码生成失败，正在重试 ({retry_count}/{max_retries})...")
                        await asyncio.sleep(2)  # 等待2秒后重试
                        continue
                    else:
                        yield event.plain_result("二维码生成失败，已达到最大重试次数")
                        return
                        
            except Exception as e:
                logger.error(f"二维码登录失败: {e}")
                if retry_count < max_retries - 1:
                    retry_count += 1
                    logger.warning(f"登录过程出错，正在重试 ({retry_count}/{max_retries})...")
                    yield event.plain_result(f"登录过程出错，正在重试 ({retry_count}/{max_retries})...")
                    await asyncio.sleep(2)  # 等待2秒后重试
                    continue
                else:
                    yield event.plain_result("登录过程出错，已达到最大重试次数")
                    return
