---
name: xfg-zsxq-skills
version: 2.3.0
description: "知识星球自动化技能。支持发帖、回帖、浏览帖子、检查通知、自动回帖、自动发帖。自动读取 ~/.xfg-zsxq/groups.json 配置。支持定时任务自动检查通知和被圈提醒。回复功能使用浏览器自动化（Playwright MCP）。触发词：'知识星球'、'发帖'、'回帖'、'zsxq'、'检查通知'、'浏览帖子'、'回复帖子'、'自动回帖'、'设置定时任务'。"
author: xiaofuge
license: MIT
triggers:
  - "知识星球"
  - "发帖"
  - "回帖"
  - "zsxq"
  - "发布到星球"
  - "检查通知"
  - "浏览帖子"
  - "回复帖子"
  - "自动回帖"
  - "设置定时任务"
  - "被圈提醒"
  - "星球动态"
  - "圈人"
  - "通知"
metadata:
  openclaw:
    emoji: "📝"
---

# 知识星球自动化技能

支持发帖、回帖、浏览帖子、检查通知、自动回帖等完整功能。

## ⚡ 快速开始

### 1. 配置 Cookie

执行技能目录下的脚本：
```bash

# 添加星球配置
node {skills}/scripts/zsxq.js config add \
  --url "https://wx.zsxq.com/group/星球ID" \
  --cookie "你的完整Cookie"
```

**获取 Cookie 方法：**
1. 登录 https://wx.zsxq.com
2. 按 **F12** → **Network** 标签
3. 点击任意请求（如 `api.zsxq.com`）
4. 复制 **Request Headers** 中的完整 `Cookie` 头值

### 2. 查看配置

```bash
node zsxq.js config list
```

---

## 📝 发帖

```bash
# 简单文字发帖
node zsxq.js post --text "今天分享一个技术心得..."

# 带图片发帖（最多9张）
node zsxq.js post --text "内容" --images "/path/a.jpg,/path/b.png"

# 从文件读取内容
node zsxq.js post --file "/tmp/post.txt"
```

---

## 📖 浏览帖子

```bash
# 查看最新帖子（脚本）
node zsxq-auto-check.js

# 或直接用 curl/API
curl "https://api.zsxq.com/v2/groups/{group_id}/topics?count=10" \
  -H "cookie: $COOKIE"
```

---

## 💬 回复帖子（浏览器自动化）

回复功能使用浏览器自动化：

1. **打开星球页面**
   ```javascript
   exec command="open 'https://wx.zsxq.com/group/星球ID'"
   ```

2. **获取页面快照**
   ```javascript
   browser action=snapshot target=host refs=aria
   ```

3. **点击评论按钮**（找到对应帖子的评论按钮 ref）
   ```javascript
   browser action=act target=host ref=<评论按钮ID> kind=click
   ```

4. **输入回复内容**
   ```javascript
   browser action=act target=host ref=<输入框ID> kind=type text="回复内容"
   ```

5. **发送评论**
   ```javascript
   browser action=act target=host ref=<发送按钮ID> kind=click
   ```

---

## 🔔 检查通知

```bash
node zsxq-auto-check.js
```

**参数：**
- `--scope all` - 所有动态（默认）
- `--scope related` - 与我相关（被圈、评论等）
- `--count 30` - 获取数量

---

## 🕐 设置定时任务

当需要自动检查通知时，创建 cron 任务：

```bash
# 使用 cron 工具创建每30分钟检查一次的任务
# 在 OpenClaw 中说"设置定时任务"即可自动创建
```

# 📁 References 路由表

当需要详细参考信息时，按需加载以下文件：

| 文件 | 用途 | 何时读取 |
|------|------|----------|
| [references/api.md](references/api.md) | API 接口文档 | 发帖/浏览/上传图片时 |
| [references/usage.md](references/usage.md) | 详细使用指南 | 需要批量发帖/Git集成时 |
| [references/faq.md](references/faq.md) | 常见问题解答 | 遇到错误时 |
| [references/signature.md](references/signature.md) | 签名生成方法 | 需要手动生成签名时 |
| [references/token-config.md](references/token-config.md) | Token 配置说明 | 配置 Cookie/Token 时 |
| [references/puppeteer.md](references/puppeteer.md) | 浏览器自动化 | 使用自动回复功能时 |

---

# 📁 API 接口状态

| 功能 | 接口 | 方法 | 状态 |
|------|------|------|------|
| 发帖 | `/v2/groups/{group_id}/topics` | POST | ⚠️ 需有效 Cookie |
| 浏览帖子 | `/v2/groups/{group_id}/topics` | GET | ✅ 正常 |
| 回复帖子 | `/v2/topics/{topic_id}/comments` | POST | ⚠️ 需浏览器自动化 |
| 获取动态 | `/v2/dynamics?scope=all` | GET | ✅ 正常 |

---

# 🔧 常见问题

## ❌ 发帖失败 (code: 1004/1059)

**原因：** Cookie 已过期或无效

**解决方法：**
1. 登录 https://wx.zsxq.com
2. 按 F12 → Network
3. 复制新的 Cookie
4. 更新配置：
```bash
node zsxq.js config add --url "https://wx.zsxq.com/group/ID" --cookie "新Cookie"
```

## ❌ 回复帖子失败

**原因：** API 回复有频率限制

**解决方法：** 使用浏览器自动化方式回复（见上方教程）

---

# 🔐 Cookie 格式

确保 Cookie 包含以下关键字段：

```
zsxq_access_token=xxx; sensorsdata2015jssdkcross=xxx; sajssdk_2015_cross_new_user=1; abtest_env=product
```

---

# 📁 项目结构

```
xfg-zsxq-skills/
├── SKILL.md                 # 技能文档
├── README.md                # 说明文档
├── scripts/                 # 可执行脚本
│   ├── zsxq.js              # 主脚本（配置/发帖/浏览）
│   ├── zsxq-auto-check.js   # 自动检查通知
│   ├── zsxq-auto-reply.js   # 自动回复（浏览器自动化）
│   └── zsxq-cron-setup.js   # 定时任务设置
└── references/              # 参考文档（按需加载）
    ├── api.md               # API 接口文档
    ├── usage.md             # 详细使用指南
    ├── faq.md               # 常见问题
    ├── signature.md         # 签名生成
    ├── token-config.md      # Token 配置
    └── puppeteer.md         # 浏览器自动化
```

**注意**：references 目录下的文件不会自动加载到上下文，仅在需要时由 AI 自行读取。

---

# 参考

- 知识星球网页版：https://wx.zsxq.com
- 配置文件：`~/.xfg-zsxq/groups.json`
- 脚本目录：`xfg-zsxq-skills/scripts`
