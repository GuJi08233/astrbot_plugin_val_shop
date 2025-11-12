import base64
import json
import logging
import os
import shutil
import asyncio
import requests
from PIL import Image, ImageDraw, ImageFont
from typing import Dict, Any, Optional

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.core.message.components import Image as AstrImage, Plain, At
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

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
            
            for goods in goods_list:
                logger.info(f"处理商品: {goods['goods_name']}")
                
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
                    # 打开图片
                    img1 = Image.open(bg_img_path)
                    img2 = Image.open(goods_img_path)
                    
                    # 调整第二张图片的大小
                    height = 180
                    width = int((img2.width * height) / img2.height)
                    img2_resized = img2.resize((width, height))
                    
                    # 计算居中粘贴的位置
                    x = (img1.width - img2_resized.width) // 2
                    y = (img1.height - img2_resized.height) // 2
                    
                    # 创建新图像
                    new_img = Image.new('RGB', img1.size)
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
                
            # 合并所有处理后的图片
            logger.info("合并所有图片")
            images = [Image.open(img_path) for img_path in processed_images]
            
            # 计算合并后的图片尺寸
            max_width = max(img.width for img in images)
            total_height = sum(img.height for img in images) + (len(images) - 1) * 20  # 20px 间距
            
            # 创建合并后的图片
            merged_image = Image.new('RGB', (max_width, total_height), color='white')
            
            # 将所有图片堆叠在一起
            y_offset = 0
            for img in images:
                merged_image.paste(img, (0, y_offset))
                y_offset += img.height + 20
            
            # 保存合并后的图片
            merged_image_path = f"./temp/valo/{user_id}/merged.jpg"
            merged_image.save(merged_image_path)
            
            # 转换为base64
            with open(merged_image_path, 'rb') as f:
                base64_data = base64.b64encode(f.read()).decode('utf-8')
            
            # 清理临时目录
            temp_dir = f"./temp/valo/{user_id}"
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
                
            return base64_data
            
        except requests.RequestException as e:
            logger.error(f"网络请求失败: {e}")
            return None
        except Exception as e:
            logger.error(f"处理失败: {e}")
            return None

    async def get_user_config(self, user_id: str) -> Optional[Dict[str, Any]]:
        """从数据库获取用户配置"""
        db = self.context.get_db()
        async with db.get_db() as session:
            session: AsyncSession
            result = await session.execute(
                text("SELECT userId, tid, nickname FROM valo_users WHERE user_id = :user_id"),
                {"user_id": user_id}
            )
            row = result.fetchone()
            if row:
                return {
                    'userId': row[0],
                    'tid': row[1],
                    'nickname': row[2]
                }
        return None

    async def save_user_config(self, user_id: str, userId: str, tid: str, nickname: Optional[str] = None):
        """保存用户配置到数据库"""
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

    def parse_config_simple(self, message_str: str) -> Optional[Dict[str, str]]:
        """简单规则解析配置信息"""
        try:
            config = {}
            
            # 支持多种分隔符：分号、换行、空格
            separators = [';', '\n', ' ']
            
            # 尝试按分号分割（Cookie格式）
            if ';' in message_str:
                parts = message_str.split(';')
            else:
                # 按换行分割
                parts = message_str.strip().split('\n')
            
            for part in parts:
                part = part.strip()
                if not part:
                    continue
                    
                # 尝试多种分隔符
                if ':' in part:
                    key, value = part.split(':', 1)
                elif '=' in part:
                    key, value = part.split('=', 1)
                elif '：' in part:  # 中文冒号
                    key, value = part.split('：', 1)
                else:
                    continue
                    
                key = key.strip()
                value = value.strip()
                
                # 标准化键名
                if key.lower() in ['userid', 'user_id', '用户id']:
                    config['userId'] = value
                elif key.lower() in ['tid', 'token', '令牌']:
                    config['tid'] = value
                elif key.lower() in ['nickname', '昵称']:
                    config['nickname'] = value
                elif key.lower() in ['clienttype', 'client_type']:
                    config['clientType'] = value
                elif key.lower() in ['uin']:
                    config['uin'] = value
                elif key.lower() in ['appid']:
                    config['appid'] = value
                elif key.lower() in ['acctype']:
                    config['acctype'] = value
                elif key.lower() in ['openid']:
                    config['openid'] = value
                elif key.lower() in ['access_token']:
                    config['access_token'] = value
                elif key.lower() in ['accounttype', 'account_type']:
                    config['accountType'] = value
                else:
                    config[key] = value
            
            # 验证必需字段
            if 'userId' in config and 'tid' in config:
                return config
                
        except Exception as e:
            logger.error(f"简单解析失败: {e}")
            
        return None

    async def parse_config_with_llm(self, message_str: str) -> Optional[Dict[str, str]]:
        """使用LLM解析配置信息"""
        try:
            # 获取插件配置（简化版本，直接使用默认LLM提供者）
            get_using = self.context.get_using_provider()
            if not get_using:
                logger.warning("无法获取默认LLM提供者")
                return None
                
            # 调试模式日志
            logger.info("使用默认LLM提供者进行配置解析")
                
            system_prompt = """你是一个配置信息解析助手。请从用户提供的文本中提取无畏契约账户的配置信息。

需要提取的字段：
- userId: 无畏契约用户ID，通常以"JA-"开头
- tid: 认证令牌，通常是很长的字符串
- nickname: 用户昵称（可选）
- 其他可能的字段：clientType, uin, appid, acctype, openid, access_token, accountType

请严格按照以下JSON格式返回，不要添加任何其他文字：
{
    "userId": "提取的userId",
    "tid": "提取的tid",
    "nickname": "提取的昵称（如果有）",
    "clientType": "提取的clientType（如果有）",
    "uin": "提取的uin（如果有）",
    "appid": "提取的appid（如果有）",
    "acctype": "提取的acctype（如果有）",
    "openid": "提取的openid（如果有）",
    "access_token": "提取的access_token（如果有）",
    "accountType": "提取的accountType（如果有）"
}

如果某个字段无法提取，请用null表示。特别注意：
1. Cookie格式通常用分号分隔多个键值对
2. userId通常以"JA-"开头
3. tid通常是很长的十六进制字符串"""

            llm_response = await get_using.text_chat(
                system_prompt=system_prompt,
                prompt=f"请解析以下配置信息：\n{message_str}",
            )
            
            if not llm_response or not llm_response.completion_text:
                logger.error("LLM响应为空")
                return None
                
            # 尝试解析JSON响应
            import re
            json_match = re.search(r'\{.*\}', llm_response.completion_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
                config = json.loads(json_str)
                
                # 验证必需字段
                if config.get('userId') and config.get('tid'):
                    return config
                    
        except Exception as e:
            logger.error(f"LLM解析失败: {e}")
            
        return None

    async def parse_config_smart(self, message_str: str) -> Optional[Dict[str, str]]:
        """智能解析配置信息（简单规则+LLM备用）"""
        # 首先尝试简单规则解析
        config = self.parse_config_simple(message_str)
        if config:
            logger.info("使用简单规则解析成功")
            return config
            
        # 简单解析失败，使用LLM
        logger.info("简单解析失败，尝试使用LLM解析")
        config = await self.parse_config_with_llm(message_str)
        if config:
            logger.info("使用LLM解析成功")
            return config
            
        logger.error("所有解析方法都失败")
        return None

    async def handle_daily_shop(self, event: AstrMessageEvent, target_user_id: Optional[str] = None) -> MessageEventResult:
        """处理每日商店指令"""
        # 确定查询的用户ID
        if target_user_id:
            # 查询其他用户的商店
            user_id = target_user_id
            user_config = await self.get_user_config(user_id)
            if not user_config:
                return event.plain_result(f"未找到用户 {target_user_id} 的配置")
        else:
            # 查询自己的商店
            user_id = event.get_sender_id()
            user_config = await self.get_user_config(user_id)
            if not user_config:
                return event.plain_result("您尚未绑定无畏契约账户信息，请使用 /瓦 指令进行绑定")

        logger.info(f"开始为用户 {user_id} 获取商店信息")
        
        # 获取商店信息
        shop_data = self.get_shop_data(user_id, user_config)
        
        if shop_data:
            # 发送图片消息
            return event.image_result(shop_data)
        else:
            # 获取商店信息失败
            if target_user_id:
                return event.plain_result(f"获取用户 {target_user_id} 的商店信息失败，可能是配置过期或网络问题")
            else:
                return event.plain_result("获取商店信息失败，可能是配置过期或网络问题，请使用 /瓦 重新绑定")

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
        
        # 调用处理函数，传入目标用户ID（如果有）
        result = await self.handle_daily_shop(event, target_user_id)
        yield result

    @filter.command("瓦")
    async def bind_wallet_command(self, event: AstrMessageEvent):
        """绑定无畏契约钱包指令"""
        user_id = event.get_sender_id()
        message_str = event.message_str
        
        # 检查是否为私聊 - 移除严格检查
        # 用户反馈在私聊中也被拒绝，说明私聊检测逻辑不准确
        # 暂时移除这个检查，允许在任何地方绑定
        # 后续可以根据用户反馈再添加更精确的判断
        
        # 方式1：尝试获取群组ID，如果成功获取到则说明是群聊
        # try:
        #     group_id = event.get_group_id()
        #     if group_id and group_id != "":
        #         # 成功获取到群组ID，说明是群聊
        #         yield event.plain_result("绑定指令请在私聊中使用")
        #         return
        # except:
        #     # 获取群组ID失败，可能是私聊，继续执行
        #     pass
        
        # 暂时允许在任何地方绑定配置
        # 因为用户反馈在私聊中也被拒绝，说明检测逻辑有问题
        # 移除这个限制，让用户可以在任何地方绑定
        
        if not message_str or message_str.strip() == "":
            # 提示用户输入完整配置
            yield event.plain_result(
                "请输入完整配置信息，格式：\n"
                "userId:您的userId\n"
                "tid:您的tid\n\n"
                "示例：\n"
                "userId:JA-xxxxxxxxxxxxx\n"
                "tid:B3C4B3BEA580ED2CD07880058D52F21D11141D4991EFD101B1EA88D7D6271549DA6AD543983551CDF6144BE9742D8D3F5984ED1E21DD48F098474AF8E51C5336A90E6B3965D4EBE32A60120BAEE687EA5C5E1316E9D03B5BEA47A021C858F386EF998E0C5C3850DF8F18DF1965B3463915B1426023BA69B2FADDC988B695BA139A61B777ED6CD53AEF9CC97B758CE163FFE5846EA9CAEF4EE39425AC098BC4539CA9AD0D0277251F0F13F2556F39B947"
            )
            return
        
        # 智能解析配置信息
        try:
            config = await self.parse_config_smart(message_str)
            
            if not config:
                yield event.plain_result(
                    "无法识别配置信息，请确保包含以下内容：\n"
                    "• userId: 无畏契约用户ID（通常以JA-开头）\n"
                    "• tid: 认证令牌（长字符串）\n\n"
                    "支持的格式示例：\n"
                    "userId:JA-xxxxxxxxxxxxx\n"
                    "tid:您的tid字符串\n\n"
                    "或者直接粘贴包含这些信息的文本，我会智能识别"
                )
                return
            
            # 保存配置
            await self.save_user_config(
                user_id,
                config['userId'],
                config['tid'],
                config.get('nickname')
            )
            
            yield event.plain_result(
                f"配置保存成功！\n"
                f"用户ID: {config['userId']}\n"
                f"现在可以使用 /每日商店 查看每日商店了"
            )
            
        except Exception as e:
            logger.error(f"解析配置失败: {e}")
            yield event.plain_result("配置解析失败，请检查输入信息是否正确")
