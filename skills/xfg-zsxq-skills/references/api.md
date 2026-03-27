# 知识星球 API 接口文档

## 基础信息

- **Base URL**: `https://api.zsxq.com/v2`
- **Content-Type**: `application/json`
- **认证方式**: Cookie + Token

## 接口列表

### 1. 发布帖子

发布新主题到指定星球。

**URL**: `POST /groups/{group_id}/topics`

**Headers**:
```
accept: application/json, text/plain, */*
accept-language: zh-CN,zh;q=0.9
content-type: application/json
origin: https://wx.zsxq.com
referer: https://wx.zsxq.com/
x-request-id: {uuid}
x-signature: {signature}
x-timestamp: {timestamp}
x-version: 2.89.0
Cookie: zsxq_access_token={token}
```

**Path Parameters**:
| 参数 | 类型 | 说明 |
|------|------|------|
| group_id | string | 星球ID，如：48885154455258 |

**Request Body**:
```json
{
  "req_data": {
    "type": "topic",
    "text": "帖子内容",
    "image_ids": [],
    "file_ids": [],
    "mentioned_user_ids": []
  }
}
```

**参数说明**:
| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| type | string | 是 | 固定值 "topic" |
| text | string | 是 | 帖子正文内容 |
| image_ids | array | 否 | 图片ID列表 |
| file_ids | array | 否 | 文件ID列表 |
| mentioned_user_ids | array | 否 | @用户ID列表 |

**Response**:
```json
{
  "succeeded": true,
  "data": {
    "topic_id": 4848484848484848
  }
}
```

### 2. 上传图片

先上传图片获取 image_id，再发布帖子。

**URL**: `POST /upload`

**Headers**:
```
content-type: multipart/form-data
Cookie: zsxq_access_token={token}
```

**Request Body**:
```
file: [二进制图片数据]
```

**Response**:
```json
{
  "succeeded": true,
  "data": {
    "image_id": 123456789
  }
}
```

### 3. 获取星球信息

**URL**: `GET /groups/{group_id}`

**Headers**:
```
Cookie: zsxq_access_token={token}
```

**Response**:
```json
{
  "succeeded": true,
  "data": {
    "group": {
      "group_id": 48885154455258,
      "name": "小傅哥的星球",
      "description": "..."
    }
  }
}
```

## 错误码

| 错误码 | 说明 |
|--------|------|
| 401 | Token 失效或过期 |
| 403 | 无权限访问 |
| 429 | 请求过于频繁 |
| 500 | 服务器错误 |

## 请求示例

### cURL 示例

```bash
curl 'https://api.zsxq.com/v2/groups/48885154455258/topics' \
  -H 'content-type: application/json' \
  -H 'x-request-id: c5aba2394-1790-4f97-84c8-ebca01cb272' \
  -H 'x-signature: 9a50178a81cd42977b7688a2a347a1218c5025fe' \
  -H 'x-timestamp: 1774404109' \
  -H 'x-version: 2.89.0' \
  -b 'zsxq_access_token=YOUR_TOKEN' \
  --data-raw '{
    "req_data": {
      "type": "topic",
      "text": "测试内容",
      "image_ids": [],
      "file_ids": [],
      "mentioned_user_ids": []
    }
  }'
```

### Python 示例

```python
import requests
import uuid
import time

url = "https://api.zsxq.com/v2/groups/48885154455258/topics"
headers = {
    "content-type": "application/json",
    "x-request-id": str(uuid.uuid4()),
    "x-signature": "YOUR_SIGNATURE",
    "x-timestamp": str(int(time.time())),
    "x-version": "2.89.0",
}
cookies = {
    "zsxq_access_token": "YOUR_TOKEN"
}
data = {
    "req_data": {
        "type": "topic",
        "text": "Hello 知识星球",
        "image_ids": [],
        "file_ids": [],
        "mentioned_user_ids": []
    }
}

response = requests.post(url, headers=headers, cookies=cookies, json=data)
print(response.json())
```