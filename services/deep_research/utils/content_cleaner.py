"""
网页内容清洗器

清洗网页原始内容，去除 HTML 标签、脚本、样式等噪音，
提取核心正文内容。
"""
import re
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# 尝试导入可选依赖
try:
    import trafilatura
    TRAFILATURA_AVAILABLE = True
except ImportError:
    TRAFILATURA_AVAILABLE = False
    logger.warning("trafilatura not available, using BeautifulSoup fallback")

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False
    logger.warning("BeautifulSoup not available, content cleaning limited")


@dataclass
class CleanedContent:
    """清洗后的内容"""
    text: str
    title: str = ""
    headings: list[str] = field(default_factory=list)
    links: list[dict] = field(default_factory=list)
    original_length: int = 0
    cleaned_length: int = 0
    compression_ratio: float = 0.0
    
    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "title": self.title,
            "headings": self.headings,
            "links": self.links,
            "original_length": self.original_length,
            "cleaned_length": self.cleaned_length,
            "compression_ratio": self.compression_ratio,
        }


class WebContentCleaner:
    """
    网页内容清洗器
    
    清洗步骤：
    1. 移除 HTML/XML 标签
    2. 移除脚本和样式
    3. 移除注释
    4. 提取正文
    5. 规范空白字符
    
    使用方式：
        cleaner = WebContentCleaner()
        
        # 简单清洗
        clean_text = cleaner.clean(html_content)
        
        # 带结构的清洗
        result = cleaner.clean_with_structure(html_content)
    """
    
    # 需要移除的标签
    REMOVE_TAGS = [
        'script', 'style', 'nav', 'footer', 'header', 
        'aside', 'form', 'iframe', 'noscript', 'svg'
    ]
    
    # 需要保留的标签（用于结构化提取）
    KEEP_TAGS = ['h1', 'h2', 'h3', 'h4', 'h5', 'p', 'li', 'td', 'th']
    
    def __init__(
        self,
        min_content_length: int = 50,
        max_content_length: int = 10000,
    ):
        """
        初始化清洗器
        
        Args:
            min_content_length: 最小内容长度
            max_content_length: 最大内容长度
        """
        self.min_content_length = min_content_length
        self.max_content_length = max_content_length
        
        logger.info(
            f"WebContentCleaner initialized, trafilatura={TRAFILATURA_AVAILABLE}, "
            f"bs4={BS4_AVAILABLE}"
        )
    
    def clean(self, html_content: str, url: str = "") -> str:
        """
        清洗网页内容，返回纯净文本
        
        Args:
            html_content: 原始 HTML 内容
            url: 来源 URL（用于日志）
            
        Returns:
            清洗后的纯文本
        """
        if not html_content:
            return ""
        
        original_length = len(html_content)
        
        # 方法1：使用 trafilatura 提取正文（推荐）
        if TRAFILATURA_AVAILABLE:
            try:
                clean_text = trafilatura.extract(
                    html_content,
                    include_comments=False,
                    include_tables=True,
                    no_fallback=False
                )
                
                if clean_text and len(clean_text) > self.min_content_length:
                    clean_text = self._normalize_whitespace(clean_text)
                    clean_text = self._truncate(clean_text)
                    
                    logger.debug(
                        f"Trafilatura cleaned {url}: {original_length} -> {len(clean_text)} chars"
                    )
                    return clean_text
            except Exception as e:
                logger.warning(f"Trafilatura extraction failed for {url}: {e}")
        
        # 方法2：BeautifulSoup 备用方案
        if BS4_AVAILABLE:
            try:
                clean_text = self._clean_with_beautifulsoup(html_content)
                
                if clean_text and len(clean_text) > self.min_content_length:
                    clean_text = self._truncate(clean_text)
                    
                    logger.debug(
                        f"BeautifulSoup cleaned {url}: {original_length} -> {len(clean_text)} chars"
                    )
                    return clean_text
            except Exception as e:
                logger.error(f"HTML parsing failed for {url}: {e}")
        
        # 方法3：正则表达式简单清洗
        clean_text = self._clean_with_regex(html_content)
        clean_text = self._truncate(clean_text)
        
        logger.debug(f"Regex cleaned {url}: {original_length} -> {len(clean_text)} chars")
        return clean_text
    
    def clean_with_structure(self, html_content: str) -> CleanedContent:
        """
        清洗并保留基本结构
        
        Args:
            html_content: 原始 HTML 内容
            
        Returns:
            CleanedContent 对象
        """
        original_length = len(html_content)
        
        result = CleanedContent(
            text="",
            original_length=original_length,
        )
        
        if not html_content:
            return result
        
        if not BS4_AVAILABLE:
            # 降级为简单清洗
            result.text = self.clean(html_content)
            result.cleaned_length = len(result.text)
            result.compression_ratio = self._calc_ratio(original_length, result.cleaned_length)
            return result
        
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # 移除噪音
            for tag in self.REMOVE_TAGS:
                for element in soup.find_all(tag):
                    element.decompose()
            
            # 提取标题
            title_tag = soup.find('title') or soup.find('h1')
            if title_tag:
                result.title = title_tag.get_text(strip=True)
            
            # 提取各级标题
            for i in range(1, 6):
                for h in soup.find_all(f'h{i}'):
                    text = h.get_text(strip=True)
                    if text:
                        result.headings.append(text)
            
            # 提取链接（用于溯源）
            for a in soup.find_all('a', href=True):
                text = a.get_text(strip=True)
                if text and len(text) > 3:
                    result.links.append({
                        "text": text[:100],  # 限制长度
                        "url": a['href']
                    })
            
            # 提取正文
            result.text = self.clean(html_content)
            result.cleaned_length = len(result.text)
            result.compression_ratio = self._calc_ratio(original_length, result.cleaned_length)
            
        except Exception as e:
            logger.error(f"Structured cleaning failed: {e}")
            result.text = self.clean(html_content)
            result.cleaned_length = len(result.text)
            result.compression_ratio = self._calc_ratio(original_length, result.cleaned_length)
        
        return result
    
    def is_valid_content(self, text: str) -> bool:
        """
        检查是否为有效内容
        
        Args:
            text: 待检查文本
            
        Returns:
            是否有效
        """
        if not text:
            return False
        
        # 长度检查
        if len(text) < self.min_content_length:
            return False
        
        # 检查是否包含垃圾内容特征
        garbage_patterns = [
            r'please enable javascript',
            r'登录后查看',
            r'请登录后继续',
            r'404 not found',
            r'页面不存在',
        ]
        
        for pattern in garbage_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return False
        
        return True
    
    # ============ 私有方法 ============
    
    def _clean_with_beautifulsoup(self, html_content: str) -> str:
        """使用 BeautifulSoup 清洗"""
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # 移除不需要的标签
        for tag in self.REMOVE_TAGS:
            for element in soup.find_all(tag):
                element.decompose()
        
        # 移除注释
        from bs4 import Comment
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()
        
        # 获取文本
        text = soup.get_text(separator='\n')
        return self._normalize_whitespace(text)
    
    def _clean_with_regex(self, html_content: str) -> str:
        """使用正则表达式简单清洗"""
        # 移除 script 和 style 块
        text = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
        
        # 移除 HTML 注释
        text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
        
        # 移除 HTML 标签
        text = re.sub(r'<[^>]+>', ' ', text)
        
        # 解码 HTML 实体
        import html
        text = html.unescape(text)
        
        return self._normalize_whitespace(text)
    
    def _normalize_whitespace(self, text: str) -> str:
        """规范化空白字符"""
        # 移除多余空格
        text = re.sub(r'[ \t]+', ' ', text)
        # 移除多余换行
        text = re.sub(r'\n{3,}', '\n\n', text)
        # 移除行首行尾空格
        lines = [line.strip() for line in text.split('\n')]
        return '\n'.join(lines)
    
    def _truncate(self, text: str) -> str:
        """截断文本到最大长度"""
        if len(text) > self.max_content_length:
            return text[:self.max_content_length] + "..."
        return text
    
    @staticmethod
    def _calc_ratio(original: int, cleaned: int) -> float:
        """计算压缩率"""
        if original == 0:
            return 0.0
        return round(cleaned / original, 2)


async def fetch_and_clean(url: str, cleaner: Optional[WebContentCleaner] = None) -> str:
    """
    获取并清洗网页内容（异步版本）
    
    Args:
        url: 网页 URL
        cleaner: WebContentCleaner 实例（可选）
        
    Returns:
        清洗后的纯文本
    """
    import httpx
    
    if cleaner is None:
        cleaner = WebContentCleaner()
    
    # 1. 获取网页
    async with httpx.AsyncClient() as client:
        response = await client.get(url, follow_redirects=True, timeout=30)
        response.raise_for_status()
    
    # 2. 检测编码
    response.encoding = response.apparent_encoding or 'utf-8'
    html_content = response.text
    
    # 3. 清洗内容
    clean_text = cleaner.clean(html_content, url)
    
    # 4. 验证清洗结果
    if len(clean_text) < 50:
        logger.warning(f"Content too short after cleaning: {url}")
        return ""
    
    logger.info(f"Cleaned content from {url}: {len(html_content)} -> {len(clean_text)} chars")
    return clean_text
