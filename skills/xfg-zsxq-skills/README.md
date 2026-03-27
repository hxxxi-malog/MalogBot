# xfg-zsxq-skills

知识星球自动发帖技能包，支持多星球管理、图片上传，适配 OpenClaw / QClaw。

## 功能特性

- ✅ 发布纯文字帖子
- ✅ 支持 Markdown 格式
- ✅ 多星球管理（配置多个知识星球）
- ✅ 自动生成签名（无需手动获取 x-signature）
- ✅ 图片上传（最多9张，上传到七牛云）
- ✅ Cookie 自动保存和读取
- ✅ 首次配置引导

## 快速开始

### 1. 首次使用（配置 Cookie）

1. 登录 https://wx.zsxq.com
2. 按 **F12** → **Network** → 点击任意请求 → 复制 **Cookie**

```bash
node scripts/zsxq.js config add \
  --url "https://wx.zsxq.com/group/你的星球ID" \
  --cookie "你的完整cookie"
```

> Cookie 自动保存到 `~/.xfg-zsxq/groups.json`（权限 600）

### 2. 发帖（自动读取配置，无需任何参数）

```bash
# 纯文字
node scripts/zsxq.js post --text "今天分享一个设计模式..."

# 带图片（最多9张，逗号分隔）
node scripts/zsxq.js post --text "内容" --images "/path/a.jpg,/path/b.png"

# 指定星球
node scripts/zsxq.js post --text "内容" --name "星球名称"
```

### 3. 管理配置

```bash
# 查看已配置的星球
node scripts/zsxq.js config list

# 设置默认星球
node scripts/zsxq.js config default --name "星球名称"

# 移除星球
node scripts/zsxq.js config remove --name "星球名称"
```

## 在 OpenClaw / QClaw 中使用

安装此 skill 后，直接对话即可发帖：

> "帮我在知识星球发帖：今天分享一个设计模式..."

Skill 会自动读取 `~/.xfg-zsxq/groups.json` 配置，**无需手动提供 Cookie 或签名**。

## 文档

| 文档 | 说明 |
|------|------|
| [SKILL.md](SKILL.md) | 技能主文档 |
| [references/api.md](references/api.md) | API 接口文档 |
| [references/usage.md](references/usage.md) | 使用指南 |
| [references/signature.md](references/signature.md) | 签名算法说明 |
| [references/faq.md](references/faq.md) | 常见问题 |
| [references/token-config.md](references/token-config.md) | Token 配置说明 |

## 触发词

- "知识星球"
- "发帖"
- "发星球"
- "zsxq"
- "发布到星球"

## 配置文件

- **位置**：`~/.xfg-zsxq/groups.json`
- **格式**：JSON，包含星球名称、groupId、cookie、url
- **权限**：600（仅所有者可读写）

## 注意事项

1. **Cookie 安全**：不要将 cookie 提交到代码仓库
2. **Cookie 过期**：过期后重新登录获取即可
3. **频率限制**：避免短时间内大量发帖

## License

MIT
