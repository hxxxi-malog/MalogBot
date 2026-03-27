#!/bin/bash

# 知识星球自动发帖脚本
# 使用方法: bash post.sh --cookie "COOKIE" --signature "SIG" --timestamp "TS" --text "内容"

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 默认配置
GROUP_ID="48885154455258"
API_URL="https://api.zsxq.com/v2/groups/${GROUP_ID}/topics"

# 参数解析
COOKIE=""
SIGNATURE=""
TIMESTAMP=""
TEXT=""
IMAGES=""

# 显示帮助
show_help() {
    cat << EOF
知识星球自动发帖脚本

使用方法:
    bash post.sh --cookie "COOKIE" --signature "SIG" --timestamp "TS" --text "内容"

必填参数:
    --cookie        完整的 cookie 字符串
    --signature     x-signature 值（从浏览器获取）
    --timestamp     x-timestamp 值（从浏览器获取）
    --text          帖子内容

可选参数:
    --images        图片路径，多个用逗号分隔
    --group         星球ID (默认: 48885154455258)
    --help          显示帮助

获取签名方法:
    1. 打开 https://wx.zsxq.com 并登录
    2. 按 F12 → Network 标签
    3. 发布一条测试帖子
    4. 在 Network 中找到 topics 请求
    5. 复制 x-signature 和 x-timestamp

示例:
    bash post.sh \\
      --cookie "sajssdk_2015_cross_new_user=1; zsxq_access_token=..." \\
      --signature "9a50178a81cd42977b7688a2a347a1218c5025fe" \\
      --timestamp "1774404109" \\
      --text "Hello 知识星球"
EOF
}

# 解析参数
while [[ $# -gt 0 ]]; do
    case $1 in
        --cookie)
            COOKIE="$2"
            shift 2
            ;;
        --signature)
            SIGNATURE="$2"
            shift 2
            ;;
        --timestamp)
            TIMESTAMP="$2"
            shift 2
            ;;
        --text)
            TEXT="$2"
            shift 2
            ;;
        --images)
            IMAGES="$2"
            shift 2
            ;;
        --group)
            GROUP_ID="$2"
            API_URL="https://api.zsxq.com/v2/groups/${GROUP_ID}/topics"
            shift 2
            ;;
        --help)
            show_help
            exit 0
            ;;
        *)
            echo -e "${RED}未知参数: $1${NC}"
            show_help
            exit 1
            ;;
    esac
done

# 验证必填参数
if [[ -z "$COOKIE" ]]; then
    echo -e "${RED}错误: 缺少 --cookie 参数${NC}"
    exit 1
fi

if [[ -z "$SIGNATURE" ]]; then
    echo -e "${RED}错误: 缺少 --signature 参数${NC}"
    echo "请在知识星球发布测试帖子，从 Network 中复制 x-signature"
    exit 1
fi

if [[ -z "$TIMESTAMP" ]]; then
    echo -e "${RED}错误: 缺少 --timestamp 参数${NC}"
    echo "请在知识星球发布测试帖子，从 Network 中复制 x-timestamp"
    exit 1
fi

if [[ -z "$TEXT" ]]; then
    echo -e "${RED}错误: 缺少 --text 参数${NC}"
    exit 1
fi

# 生成请求ID
REQUEST_ID=$(uuidgen 2>/dev/null || python3 -c "import uuid; print(uuid.uuid4())" 2>/dev/null || echo "$(date +%s)-$$")

# 处理图片
IMAGE_IDS="[]"
if [[ -n "$IMAGES" ]]; then
    echo -e "${YELLOW}注意: 图片上传功能需要额外实现${NC}"
fi

# 构建请求体
TEXT_ESCAPED=$(echo "$TEXT" | sed 's/"/\\"/g' | sed 's/\n/\\n/g')

REQUEST_BODY=$(cat << EOF
{
  "req_data": {
    "type": "topic",
    "text": "${TEXT_ESCAPED}",
    "image_ids": ${IMAGE_IDS},
    "file_ids": [],
    "mentioned_user_ids": []
  }
}
EOF
)

echo -e "${YELLOW}正在发帖...${NC}"

# 发送请求
RESPONSE=$(curl -s -X POST "${API_URL}" \
    -H "accept: application/json, text/plain, */*" \
    -H "accept-language: zh-CN,zh;q=0.9" \
    -H "content-type: application/json" \
    -H "origin: https://wx.zsxq.com" \
    -H "referer: https://wx.zsxq.com/" \
    -H "x-request-id: ${REQUEST_ID}" \
    -H "x-signature: ${SIGNATURE}" \
    -H "x-timestamp: ${TIMESTAMP}" \
    -H "x-version: 2.89.0" \
    -b "${COOKIE}" \
    --data-raw "${REQUEST_BODY}" 2>&1)

# 检查响应
if echo "$RESPONSE" | grep -q '"succeeded":true'; then
    echo -e "${GREEN}✅ 发帖成功！${NC}"
    TOPIC_ID=$(echo "$RESPONSE" | grep -o '"topic_id":[0-9]*' | cut -d':' -f2)
    echo -e "${GREEN}帖子ID: ${TOPIC_ID}${NC}"
else
    echo -e "${RED}❌ 发帖失败${NC}"
    echo "响应: $RESPONSE"
    
    if echo "$RESPONSE" | grep -q '401'; then
        echo -e "${RED}Cookie 或签名已过期${NC}"
    fi
    exit 1
fi