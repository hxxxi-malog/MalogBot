# 常见问题

## Q1: 提示 "Token 已过期"

**原因**：`zsxq_access_token` 有效期有限

**解决**：
1. 重新登录 https://wx.zsxq.com
2. 从浏览器 Cookie 中获取新的 token
3. 更新脚本中的 `--token` 参数

## Q2: 提示 "签名错误"

**原因**：`x-signature` 或 `x-timestamp` 不正确或已过期

**解决**：
1. 在知识星球网页版发布一条新帖子
2. 从 Network 中复制最新的 `x-signature` 和 `x-timestamp`
3. 重新运行脚本输入新签名

## Q3: 提示 "请求过于频繁"

**原因**：短时间内发送了太多请求

**解决**：
- 等待几分钟后再试
- 在脚本中添加 `sleep` 延迟

## Q4: 如何发布图片？

**当前状态**：脚本目前仅支持文字发布

**解决方案**：
1. 先调用图片上传接口获取 `image_id`
2. 在发布帖子时传入 `image_ids` 数组

图片上传接口：
```bash
curl -X POST "https://api.zsxq.com/v2/upload" \
  -H "Cookie: zsxq_access_token=YOUR_TOKEN" \
  -F "file=@/path/to/image.jpg"
```

## Q5: 可以@用户吗？

可以，在 `mentioned_user_ids` 数组中添加用户ID：

```json
{
  "req_data": {
    "type": "topic",
    "text": "@小傅哥 请看",
    "mentioned_user_ids": [123456789]
  }
}
```

## Q6: 如何获取用户ID？

1. 在知识星球中点击用户头像
2. 查看 URL 中的数字，如 `/users/123456789`
3. `123456789` 就是用户ID

## Q7: 可以发布文件吗？

可以，流程与图片类似：
1. 先上传文件获取 `file_id`
2. 在发布帖子时传入 `file_ids` 数组

## Q8: 如何删除帖子？

目前脚本不支持删除功能，需要：
1. 登录知识星球网页版
2. 手动找到帖子并删除

## Q9: 支持哪些内容格式？

支持 Markdown 语法：
- `**粗体**`
- `*斜体*`
- `` `代码` ``
- ```` ```代码块``` ````
- `[链接](url)`
- `- 列表项`

## Q10: 如何调试脚本？

添加 `-v` 参数查看详细输出：

```bash
bash -x scripts/post.sh --token "xxx" --text "test"
```

或在脚本中设置：
```bash
set -x  # 开启调试模式
```

## Q11: Mac苹果系统如何排查Node not found in PATH问题？

- mac可能安装了nvm来管理node版本，但是当前环境下可能未加载node，尝试执行
```bash

source ~/.nvm/nvm.sh && nvm list

```
或
```bash

source ~/.nvm/nvm.sh && nvm use [指定版本号] && node --version

```
或


