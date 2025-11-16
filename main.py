import base64
import json
import logging
import os
import shutil
import asyncio
import requests
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

@register("astrbot_plugin_val_shop", "YourName", "无畏契约每日商店查询插件", "v1.0.0")
class ValorantShopPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        # 获取当前插件目录的字体文件路径
        import os
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        self.font_path = os.path.join(plugin_dir, "fontFamily.ttf")
        
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
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """))
        logger.info("无畏契约插件初始化完成")
        
    async def terminate(self):
        """插件终止时清理"""
        pass

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
            response = requests.post(login_url, headers=headers, json=data)
            response.raise_for_status()
            result = response.json()
            
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
        # 启动无头浏览器
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={'width': 375, 'height': 667},
            user_agent="Mozilla/5.0 (Linux; Android 12; 23117RK66C Build/V417IR; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/101.0.4951.61 Mobile Safari/537.36 tencent_game_emulator"
        )
        page = await context.new_page()

        try:
            await page.goto(self.LOGIN_URL)
            
            # 等待二维码加载
            await page.wait_for_selector("#qrimg", state="visible", timeout=20000)
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

    def download_image(self, url: str, user_id: str, filename: str) -> Optional[str]:
        """下载图片到临时目录"""
        temp_dir = f"./temp/valo/{user_id}"
        os.makedirs(temp_dir, exist_ok=True)
        
        filepath = os.path.join(temp_dir, filename)
        
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            with open(filepath, 'wb') as file:
                file.write(response.content)
            return filepath
        except requests.RequestException as e:
            logger.error(f"下载图片失败: {e}")
            return None

    def get_shop_data(self, user_id: str, user_config: Dict[str, Any]) -> Optional[str]:
        """获取商店信息并生成图片的base64编码"""
        logger.info(f"开始获取商店数据，user_id: {user_id}, userId: {user_config.get('userId', '未知')}")
        url = "https://app.mval.qq.com/go/mlol_store/agame/user_store"
        
        # 检查配置是否完整
        if not all(k in user_config for k in ['userId', 'tid']):
            logger.error("配置不完整，需要包含 userId 和 tid")
            return None
        
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
        
        try:
            logger.info(f"发送API请求到 {url}")
            response = requests.post(url, headers=headers, json=data, timeout=15)
            response.raise_for_status()
            
            response_data = response.json()
            
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
                    
                bg_img_path = self.download_image(bg_img_url, user_id, 'bg.jpg')
                goods_img_path = self.download_image(goods_img_url, user_id, 'goods.jpg')
                
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
            
        except requests.RequestException as e:
            logger.error(f"网络请求失败: {e}")
            return None
        except Exception as e:
            logger.error(f"处理失败: {e}", exc_info=True)
            return None

    async def get_user_config(self, user_id: str) -> Optional[Dict[str, Any]]:
        """从数据库获取用户配置"""
        logger.info(f"查询用户配置，user_id: {user_id}")
        db = self.context.get_db()
        async with db.get_db() as session:
            session: AsyncSession
            result = await session.execute(
                text("SELECT userId, tid, nickname FROM valo_users WHERE user_id = :user_id"),
                {"user_id": user_id}
            )
            row = result.fetchone()
            if row:
                logger.info(f"找到用户配置: userId={row[0]}, tid={row[1][:20]}...")
                return {
                    'userId': row[0],
                    'tid': row[1],
                    'nickname': row[2]
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
        shop_data = self.get_shop_data(user_id, user_config)
        
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

    @filter.command("瓦")
    async def bind_wallet_command(self, event: AstrMessageEvent):
        """绑定无畏契约钱包指令 - 发送二维码登录"""
        user_id = event.get_sender_id()
        
        yield event.plain_result("正在生成登录二维码，请稍候...")
        
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
                    else:
                        yield event.plain_result("获取最终登录信息失败，请重试")
                else:
                    yield event.plain_result("登录失败或超时，请重试")
            else:
                yield event.plain_result("二维码生成失败，请重试")
                
        except Exception as e:
            logger.error(f"二维码登录失败: {e}")
            yield event.plain_result("登录过程出错，请重试")
