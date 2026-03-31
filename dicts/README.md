# 搜狗细胞词库使用说明

## 简介

搜狗细胞词库是搜狗输入法的专业词库，包含各领域的专业术语。使用这些词库可以显著提升jieba分词的准确性。

## 如何获取词库

### 方法一：官网下载

1. 访问搜狗词库官网：https://pinyin.sogou.com/dict/
2. 搜索需要的词库，如"计算机"、"IT"、"人工智能"等
3. 点击"下载"按钮，下载 `.scel` 格式文件
4. 将下载的文件放入 `dicts/` 目录

### 方法二：直接使用链接下载

以下是一些常用词库的下载链接：

| 词库名称 | 下载链接 |
|---------|---------|
| 计算机词汇大全 | https://pinyin.sogou.com/d/dict/download_cell.php?id=4&name=计算机词汇大全 |
| IT计算机 | https://pinyin.sogou.com/d/dict/download_cell.php?id=30&name=IT计算机 |
| 人工智能 | https://pinyin.sogou.com/d/dict/download_cell.php?id=18674&name=人工智能 |
| 数据库 | https://pinyin.sogou.com/d/dict/download_cell.php?id=3494&name=数据库 |

### 方法三：使用命令下载

```bash
# 进入词库目录
cd dicts

# 下载计算机词库
curl -L -o computer.scel "https://pinyin.sogou.com/d/dict/download_cell.php?id=4&name=计算机词汇大全"

# 下载IT词库
curl -L -o it.scel "https://pinyin.sogou.com/d/dict/download_cell.php?id=30&name=IT计算机"
```

## 推荐词库

对于IT/技术类知识库，建议下载以下词库：

1. **计算机词汇大全** - 包含大量计算机专业术语
2. **IT计算机** - IT行业常用词汇
3. **人工智能** - AI相关术语
4. **数据库** - 数据库专业词汇
5. **网络技术** - 网络协议、架构术语
6. **软件工程** - 开发流程、方法学术语

## 效果对比

### 加载词库前
```
"后端开发使用硬编码" -> ["后", "端", "开发", "使用", "硬", "编码"]
```

### 加载词库后
```
"后端开发使用硬编码" -> ["后端开发", "使用", "硬编码"]
```

## 注意事项

1. 词库文件格式必须为 `.scel`
2. 重启应用后新词库才会生效
3. 如果词库解析失败，会使用内置的基础词典作为兜底
