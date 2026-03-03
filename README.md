# 无畏契约每日商店插件

一个用于 AstrBot 的无畏契约（Valorant）每日商店插件。  
当前版本支持**QQ 扫码登录**和**微信扫码登录**两种方式，纯 HTTP 协议实现，不依赖浏览器自动化。

## 功能特性

- `/瓦`：QQ 二维码登录绑定账号（纯 HTTP 协议）。
- `/wvx`：微信二维码登录绑定账号（纯 HTTP 协议）。
- `/每日商店`：查询自己的每日商店。
- `/每日商店 @某人`：查询被 @ 用户的商店（该用户需已绑定）。
- `/商店监控`：添加/删除/查看监控项，支持定时自动查询与通知。
- 自动生成商店图片并发送。
- 支持 Kook 与其他常见平台。

## 安装方式

### 方式一：手动安装

```bash
# 1) 获取插件
git clone https://github.com/GuJi08233/astrbot_plugin_val_shop

# 2) 放入 AstrBot 插件目录（示例）
cp -r astrbot_plugin_val_shop /path/to/astrbot/data/plugins/

# 3) 安装依赖
pip install -r requirements.txt

# 4) 重启 AstrBot
```

### 方式二：插件管理器

```bash
astrbot plug install https://github.com/GuJi08233/astrbot_plugin_val_shop
pip install -r requirements.txt
```

## 命令说明

### 1. 账号绑定

#### QQ 登录

```text
/瓦
```

流程：
1. 生成并发送 QQ 二维码。
2. 30 秒内使用 QQ 扫码确认。
3. 自动获取并保存 `userId`、`tid`。

#### 微信登录（新增）

```text
/wvx
```

别名：`/wx`、`/微信扫码`、`/微信登录`

流程：
1. 生成并发送微信二维码。
2. 30 秒内使用微信扫码确认。
3. 自动获取并保存 `userId`、`tid`。

> 💡 两种登录方式获取的凭证格式一致，可选择任意一种方式登录。

### 2. 商店查询

```text
/每日商店
/每日商店 @某人
```

### 3. 商店监控

```text
/商店监控
/商店监控 添加 "侦察力量 幻象"
/商店监控 删除 "侦察力量 幻象"
/商店监控 列表
/商店监控 查询
/商店监控 开启
/商店监控 关闭
```

## 配置项

配置文件：`_conf_schema.json`

- `monitor_time`：每日自动监控时间，默认 `08:01`
- `timezone`：时区，默认 `Asia/Shanghai`
- `bot_id`：机器人 ID，默认 `default`
- `login_callback_url`：登录 `s_url`，默认 `http://connect.qq.com`
- `login_u1_url`：登录 `u1`，默认 `http://connect.qq.com`

建议：
- 如果你没有特殊需求，保持 `login_callback_url` 和 `login_u1_url` 默认值即可。
- 若切换这两个地址，建议保持同域并实际验证 `/瓦` 流程。

## 依赖

`requirements.txt`：

- `aiohttp>=3.8.0`
- `pillow>=12.0.0`
- `apscheduler>=3.10.0`

## 常见问题

### Q1：提示"尚未绑定"
先执行：

```text
/瓦
```
或
```text
/wvx
```

### Q2：QQ 登录失败或超时

- 30 秒内完成扫码与确认。
- 检查网络连通性。
- 重新执行 `/瓦`。
- 也可以尝试使用微信登录 `/wvx`。

### Q3：微信登录失败或超时

- 30 秒内完成扫码与确认。
- 确保使用绑定了无畏契约的微信账号扫码。
- 检查网络连通性。
- 也可以尝试使用 QQ 登录 `/瓦`。

### Q4：商店查询失败

- 可能是配置过期，重新执行 `/瓦` 或 `/wvx` 绑定。
- 检查日志中的 HTTP 登录关键节点（二维码生成、轮询、token 提取）。

### Q5：监控无通知

- 确认已开启：`/商店监控 开启`
- 确认列表非空：`/商店监控 列表`
- 检查 `monitor_time` 和 `timezone`

## 版本说明（当前）

- 当前版本：`v3.2.5`
- 登录方式：QQ 扫码登录 + 微信扫码登录（双通道）
- 浏览器依赖：已移除（不需要 Playwright）
- 登录默认链路：`connect.qq.com`（`s_url/u1`）

## 更新日志

### v3.2.5（最新）
- 新增微信扫码登录功能 `/wvx`
- 支持 `/wx`、`/微信扫码`、`/微信登录` 别名
- 优化错误提示信息

### v3.2.4
- 纯 HTTP 二维码登录（QQ）
- 移除浏览器依赖

## 开发信息

- 插件名：`astrbot_plugin_val_shop`
- 作者：`GuJi08233`
- 仓库：<https://github.com/GuJi08233/astrbot_plugin_val_shop>
- 许可证：MIT（见 `LICENSE`）
