# 完全自动化方案 - Puppeteer

使用 Puppeteer 实现知识星球完全自动化发帖，无需手动获取签名。

## 安装

```bash
cd scripts
npm install
```

## 使用方法

```bash
node zsxq-auto-post.js \
  --cookie "完整的 cookie 字符串" \
  --text "帖子内容"
```

## 示例

```bash
node zsxq-auto-post.js \
  --cookie "sajssdk_2015_cross_new_user=1; zsxq_access_token=..." \
  --text "🎉 自动化测试帖子\n\n这是一条通过 Puppeteer 自动发布的帖子！"
```

## 工作原理

1. **启动浏览器**：使用 Puppeteer 启动 Chrome
2. **设置 Cookie**：将提供的 cookie 注入浏览器
3. **访问知识星球**：自动登录并访问星球页面
4. **模拟操作**：
   - 查找发帖按钮并点击
   - 在输入框中输入内容
   - 点击发布按钮
5. **完成发帖**：等待页面响应，确认发帖成功

## 特点

- ✅ **无需手动获取签名**：完全模拟浏览器操作
- ✅ **可视化**：可以看到浏览器自动操作过程
- ✅ **稳定可靠**：模拟真实用户行为
- ⚠️ **需要安装 Chrome**：Puppeteer 会自动下载

## 注意事项

1. **Cookie 时效性**：cookie 有过期时间，失效后需重新获取
2. **频率限制**：避免短时间内大量发帖
3. ** headless 模式**：默认显示浏览器窗口，如需隐藏修改 `headless: true`

## 故障排除

### 找不到发帖按钮

如果脚本找不到发帖按钮，可能是页面结构变化。可以：
1. 打开浏览器开发者工具
2. 检查发帖按钮的 class 或 id
3. 更新脚本中的选择器

### Cookie 失效

如果出现登录失效：
1. 重新登录 https://wx.zsxq.com
2. 复制新的 cookie
3. 重新运行脚本

## 进阶：无头模式

修改脚本中的 `headless` 参数：

```javascript
const browser = await puppeteer.launch({
    headless: true, // 隐藏浏览器窗口
    args: ['--no-sandbox']
});
```

## 参考

- Puppeteer 文档：https://pptr.dev
- 知识星球：https://wx.zsxq.com