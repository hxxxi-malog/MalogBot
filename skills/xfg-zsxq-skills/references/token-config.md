# Token 配置说明

## 配置文件位置

本地配置文件保存在：

```
~/.xfg-zsxq/config
```

## 配置文件格式

```bash
# 知识星球配置
# 生成时间: Wed Mar 25 10:00:00 CST 2026
ZSXQ_ACCESS_TOKEN=85034009-ACAB-4F23-A200-0FD488D2D520_D625BA7FD9CBBDFA
ZSXQ_GROUP_ID=48885154455258
```

## 首次使用流程

### 1. 获取 Access Token

1. 登录知识星球网页版：https://wx.zsxq.com
2. 按 `F12` 打开开发者工具
3. 切换到 **Application** → **Cookies** → **https://wx.zsxq.com**
4. 找到 `zsxq_access_token`，复制值

### 2. 运行脚本并提供 Token

```bash
bash scripts/post.sh \
  --token "YOUR_ACCESS_TOKEN" \
  --text "Hello 知识星球！"
```

### 3. Token 自动保存

脚本会自动将 token 保存到 `~/.xfg-zsxq/config`，并设置权限为 600（仅所有者可读写）。

输出示例：
```
✓ Token 已保存到 /Users/xxx/.xfg-zsxq/config
  配置文件权限已设置为 600（仅所有者可读写）
```

## 后续使用

### 自动读取 Token

保存后，后续使用无需再提供 `--token`：

```bash
bash scripts/post.sh --text "今天分享..."
```

脚本会自动从 `~/.xfg-zsxq/config` 读取 token。

## Token 过期处理

### 过期提示

如果 token 过期，会显示：

```
❌ 发帖失败

╔════════════════════════════════════════════════╗
║  Token 已过期或无效                            ║
╠════════════════════════════════════════════════╣
║  请重新获取 zsxq_access_token：               ║
║  1. 访问 https://wx.zsxq.com                  ║
║  2. 按 F12 → Application → Cookies            ║
║  3. 复制新的 zsxq_access_token                ║
║  4. 重新运行脚本并提供 --token 参数           ║
╚════════════════════════════════════════════════╝

示例: bash post.sh --token "NEW_TOKEN" --text "内容"
```

### 更新 Token

提供新的 `--token` 参数即可更新本地配置：

```bash
bash scripts/post.sh \
  --token "NEW_ACCESS_TOKEN" \
  --text "测试新 token"
```

## 手动管理配置

### 查看当前配置

```bash
cat ~/.xfg-zsxq/config
```

### 修改配置

```bash
# 编辑配置文件
nano ~/.xfg-zsxq/config

# 或一键更新 token
bash scripts/post.sh --token "NEW_TOKEN" --text "test"
```

### 删除配置

```bash
rm -rf ~/.xfg-zsxq
```

## 安全说明

- **文件权限**：配置文件自动设置为 600，仅所有者可读写
- **不要提交到 Git**：已添加到 `.gitignore`
- **定期更新**：建议定期更换 token

## 多账号支持

如需管理多个账号，可使用 `--token` 参数临时指定：

```bash
# 使用默认配置（账号A）
bash scripts/post.sh --text "内容"

# 临时使用账号B
bash scripts/post.sh \
  --token "ACCOUNT_B_TOKEN" \
  --text "内容"
```

临时指定的 token 不会覆盖本地默认配置。