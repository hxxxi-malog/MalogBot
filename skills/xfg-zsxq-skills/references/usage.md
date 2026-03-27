# 使用指南

## 快速开始

### 1. 获取 Access Token

1. 登录 https://wx.zsxq.com
2. 按 `F12` 打开开发者工具
3. 切换到 **Application** → **Cookies**
4. 找到 `zsxq_access_token`，复制值

### 2. 测试发帖

```bash
cd /Users/fuzhengwei/Documents/project/xfg-zsxq-skills

bash scripts/post.sh \
  --token "YOUR_ACCESS_TOKEN" \
  --text "Hello 知识星球！"
```

### 3. 按提示输入签名

脚本会提示输入 `x-signature` 和 `x-timestamp`，从浏览器开发者工具获取。

## 高级用法

### 发布带格式的内容

**代码块**：
```bash
bash scripts/post.sh \
  --token "xxx" \
  --text $'```java\npublic class Hello {\n    public static void main(String[] args) {\n        System.out.println("Hello");\n    }\n}\n```'
```

**多行文本**：
```bash
bash scripts/post.sh \
  --token "xxx" \
  --text $'第一行\n第二行\n第三行'
```

**Markdown 格式**：
```bash
bash scripts/post.sh \
  --token "xxx" \
  --text "**粗体** 和 *斜体* 和 \`代码\`"
```

### 发布到不同星球

```bash
bash scripts/post.sh \
  --token "xxx" \
  --text "内容" \
  --group "48885154455258"
```

## 集成到工作流

### 与 Git 钩子结合

在 `.git/hooks/post-commit` 中添加：

```bash
#!/bin/bash
# 提交后自动发布到知识星球

COMMIT_MSG=$(git log -1 --pretty=%B)

bash /path/to/xfg-zsxq-skills/scripts/post.sh \
  --token "YOUR_TOKEN" \
  --text "新提交: $COMMIT_MSG"
```

### 与 CI/CD 结合

GitHub Actions 示例：

```yaml
name: Post to ZSXQ

on:
  push:
    branches: [ main ]

jobs:
  post:
    runs-on: ubuntu-latest
    steps:
      - name: Post to ZSXQ
        run: |
          bash scripts/post.sh \
            --token "${{ secrets.ZSXQ_TOKEN }}" \
            --text "项目更新: ${{ github.event.head_commit.message }}"
```

## 批量发帖

创建 `posts.txt`：

```
帖子1内容
---
帖子2内容
---
帖子3内容
```

批量发布脚本：

```bash
#!/bin/bash

TOKEN="YOUR_TOKEN"
IFS='---' read -d '' -ra posts < posts.txt

for post in "${posts[@]}"; do
    trimmed=$(echo "$post" | xargs)
    if [[ -n "$trimmed" ]]; then
        bash scripts/post.sh --token "$TOKEN" --text "$trimmed"
        sleep 5  # 避免频繁请求
    fi
done
```