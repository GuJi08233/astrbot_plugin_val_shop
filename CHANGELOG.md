# 更新日志

## v3.2.6

### 修复

- 修复 `/每日商店` 在登录凭证已过期时不会提醒、直接漏到后续服务的问题
- 查询每日商店前增加凭证可用性检测，凭证过期时直接提示重新绑定
- 统一商店接口错误判定与配置有效性检测逻辑，避免不同入口行为不一致

## v3.2.5

### 新增功能

#### 1. 微信扫码登录 (`/wvx`)

新增通过微信扫码绑定无畏契约账号的方式，作为 QQ 登录的替代方案。

**新增命令：**
- `/wvx` - 主命令
- `/wx` - 别名
- `/微信扫码` - 别名
- `/微信登录` - 别名

**实现原理：**
1. 调用 `app.mval.qq.com/go/auth/get_sdk_ticket` 获取 `sdk_ticket`
2. 使用 ticket 生成微信开放平台签名
3. 调用 `open.weixin.qq.com/connect/sdk/qrconnect` 获取 UUID 和二维码
4. 通过 `long.open.weixin.qq.com/connect/l/qrconnect` 长轮询等待扫码
5. 获取 `wx_code` 后调用 `app.mval.qq.com/go/auth/login_by_wechat` 完成登录

### 代码变更详情

#### 新增常量（`__init__` 方法）

```python
# 微信登录配置
self.WECHAT_QRCONNECT_URL = "https://open.weixin.qq.com/connect/sdk/qrconnect"
self.WECHAT_LONG_POLL_URL = "https://long.open.weixin.qq.com/connect/l/qrconnect"
self.WECHAT_APP_ID = "wxcbb49f1f39656c2a"  # 掌上无畏契约 appid
self.WECHAT_APP_NAME = "掌上无畏契约"

# Wechat internal state
self.wechat_login_tasks = {}
```

#### 新增方法

1. **`wechat_login()`** (第 1900-2021 行)
   - 命令处理函数，装饰器 `@filter.command("wvx", alias=["wx", "微信扫码", "微信登录"])`
   - 负责获取 sdk_ticket、生成签名、请求二维码、发送图片、启动轮询任务

2. **`_val_wechat_login_task()`** (第 2023-2140 行)
   - 异步任务函数，处理微信长轮询逻辑
   - 最多轮询 30 次（每次间隔 2 秒，总计 60 秒）
   - 处理多种 `wx_errcode` 状态码：
     - `408` - 等待扫码
     - `404` - 已扫码，等待确认
     - `405/0` - 授权成功，返回 `wx_code`
   - 使用 `wx_code` 调用 `login_by_wechat` API 获取最终凭证

#### 错误信息修改

`daily_shop_command()` 方法中的错误提示从：
```python
yield event.plain_result("获取商店信息失败，图片生成错误")
```
改为：
```python
yield event.plain_result("获取商店信息失败，可能是配置过期或网络问题，请使用 /瓦 重新绑定")
```

### 文件差异统计

| 项目 | 原文件 | 新文件 | 差异 |
|------|--------|--------|------|
| 总行数 | 1896 | 2142 | +246 行 |
| 新增方法 | - | 2 | `wechat_login`, `_val_wechat_login_task` |
| 新增常量 | - | 5 | 微信登录相关配置 |
| 新增依赖 | - | `hashlib` | 用于签名计算 |

### 技术细节

#### 微信登录流程图

```
用户发送 /wvx
    │
    ▼
获取 sdk_ticket (app.mval.qq.com)
    │
    ▼
生成签名 SHA1(appid + noncestr + sdk_ticket + timestamp)
    │
    ▼
请求二维码 (open.weixin.qq.com)
    │
    ▼
发送二维码图片给用户
    │
    ▼
长轮询等待扫码 (long.open.weixin.qq.com)
    │
    ├─ 408: 继续等待
    ├─ 404: 已扫码，等待确认
    ├─ 405/0: 获取 wx_code
    │
    ▼
调用 login_by_wechat (app.mval.qq.com)
    │
    ▼
保存用户配置 (userId, tid)
    │
    ▼
登录成功
```

#### 签名算法

```python
raw_string = f"appid={self.WECHAT_APP_ID}&noncestr={noncestr}&sdk_ticket={sdk_ticket}&timestamp={timestamp}"
signature = hashlib.sha1(raw_string.encode('utf-8')).hexdigest()
```

### 兼容性说明

- 本次更新完全向后兼容
- 原有 QQ 登录功能 (`/瓦`) 保持不变
- 微信登录是新增的可选登录方式
- 两种登录方式获取的凭证格式一致，可互换使用
