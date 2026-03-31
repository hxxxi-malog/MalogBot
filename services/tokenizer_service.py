"""
分词服务

提供中文和英文分词功能：
- 中文：使用jieba分词器 + 自定义词典（支持搜狗细胞词库scel格式）
- 英文：保持原词并统一转小写
"""
import re
import logging
import os
import struct
import urllib.request
import tempfile
from typing import List, Set
import json

try:
    import jieba
    import jieba.analyse
    HAS_JIEBA = True
except ImportError:
    HAS_JIEBA = False

logger = logging.getLogger(__name__)

# 词库目录
DICT_DIR = os.path.join(os.path.dirname(__file__), '..', 'dicts')

# 常用搜狗细胞词库下载链接
# 可以从这里查找: https://pinyin.sogou.com/dict/
SOGOU_DICT_URLS = {
    'computer': 'https://pinyin.sogou.com/d/dict/download_cell.php?id=4&name=计算机词汇大全',
    'it': 'https://pinyin.sogou.com/d/dict/download_cell.php?id=30&name=IT计算机',
    'ai': 'https://pinyin.sogou.com/d/dict/download_cell.php?id=18674&name=人工智能',
    'database': 'https://pinyin.sogou.com/d/dict/download_cell.php?id=3494&name=数据库',
}

# 基础自定义词典 - 作为兜底（当搜狗词库不可用时）
BASIC_CUSTOM_DICT = """
后端 3 n
前端 3 n
硬编码 3 n
软编码 3 n
微服务 3 n
分布式 3 n
数据库 3 n
云计算 3 n
人工智能 3 n
机器学习 3 n
深度学习 3 n
"""


class SogouDictParser:
    """搜狗细胞词库解析器（scel格式）"""
    
    @staticmethod
    def parse(scel_path: str) -> Set[str]:
        """
        解析搜狗细胞词库文件（scel格式）
        
        搜狗scel文件是二进制格式，需要解析提取词库
        
        Args:
            scel_path: scel文件路径
            
        Returns:
            词语集合
        """
        words = set()
        
        try:
            with open(scel_path, 'rb') as f:
                data = f.read()
            
            # scel文件格式解析
            # 参考: https://github.com/xwchris/scel2txt
            
            # 检查文件头
            if len(data) < 12:
                return words
            
            # 拼音表偏移量
            py_offset = struct.unpack('<I', data[12:16])[0]
            
            # 拼音表
            py_table = {}
            pos = py_offset
            while pos < len(data) - 4:
                # 读取拼音索引和拼音
                idx = struct.unpack('<H', data[pos:pos+2])[0]
                py_len = struct.unpack('<H', data[pos+2:pos+4])[0]
                if py_len > 0 and pos + 4 + py_len <= len(data):
                    py = data[pos+4:pos+4+py_len].decode('utf-8', errors='ignore')
                    py_table[idx] = py
                    pos += 4 + py_len
                else:
                    break
            
            # 词语表
            # 跳过拼音表，找到词语数据
            word_start = py_offset
            for _ in py_table:
                word_start += 4 + len(next(iter(py_table.values())).encode('utf-8'))
            
            # 简化解析：直接搜索中文词语
            # 搜狗词库中词语以特定格式存储
            pos = 0
            while pos < len(data) - 4:
                # 查找词语标记
                marker = data[pos:pos+2]
                if marker == b'\x02\x00':
                    # 尝试读取词语长度
                    try:
                        word_len = struct.unpack('<H', data[pos+2:pos+4])[0]
                        if 0 < word_len < 100 and pos + 4 + word_len * 2 <= len(data):
                            # 尝试解码为UTF-16
                            word_bytes = data[pos+4:pos+4+word_len*2]
                            try:
                                word = word_bytes.decode('utf-16-le', errors='ignore').strip()
                                # 只保留有效中文词语
                                if word and all('\u4e00' <= c <= '\u9fff' for c in word):
                                    words.add(word)
                            except:
                                pass
                    except:
                        pass
                pos += 1
            
            # 备用方法：直接提取所有连续中文字符序列
            if not words:
                chinese_pattern = re.compile(r'[\u4e00-\u9fff]+')
                text = data.decode('utf-16-le', errors='ignore')
                matches = chinese_pattern.findall(text)
                for word in matches:
                    if len(word) >= 2:  # 只保留2字及以上
                        words.add(word)
            
            logger.info(f"[SogouParser] 从 {scel_path} 解析出 {len(words)} 个词语")
            
        except Exception as e:
            logger.error(f"[SogouParser] 解析scel文件失败: {str(e)}")
        
        return words
    
    @staticmethod
    def download(url: str, save_path: str) -> bool:
        """
        下载搜狗细胞词库
        
        Args:
            url: 下载链接
            save_path: 保存路径
            
        Returns:
            是否成功
        """
        try:
            logger.info(f"[SogouParser] 下载词库: {url}")
            
            # 设置请求头
            request = urllib.request.Request(
                url,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
            )
            
            with urllib.request.urlopen(request, timeout=30) as response:
                data = response.read()
                
            with open(save_path, 'wb') as f:
                f.write(data)
                
            logger.info(f"[SogouParser] 词库已保存到: {save_path}")
            return True
            
        except Exception as e:
            logger.error(f"[SogouParser] 下载词库失败: {str(e)}")
            return False


class TokenizerService:
    """分词服务"""

    _initialized = False

    def __init__(self):
        """初始化分词器"""
        if not HAS_JIEBA:
            logger.warning("jieba未安装，BM25功能将不可用")
            return

        # 中文停用词（常见的无意义词汇）
        self.chinese_stopwords = set([
            '的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都', '一', '一个',
            '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有', '看', '好',
            '自己', '这', '那', '里', '为', '什么', '他', '她', '它', '们', '这个', '那个',
            '这些', '那些', '这里', '那里', '哪个', '哪些', '哪里', '怎么', '怎样', '如何',
            '可以', '能', '应该', '需要', '必须', '可能', '大概', '也许', '或者', '但', '但是',
            '因为', '所以', '如果', '虽然', '即使', '无论', '不管', '只要', '除非', '当',
            '然后', '接着', '于是', '因此', '否则', '而且', '并且', '或者', '还是', '以及'
        ])
        
        # 英文停用词
        self.english_stopwords = set([
            'a', 'an', 'the', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
            'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
            'should', 'may', 'might', 'must', 'can', 'need', 'dare', 'ought',
            'used', 'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from',
            'as', 'into', 'through', 'during', 'before', 'after', 'above', 'below',
            'between', 'under', 'again', 'further', 'then', 'once', 'here', 'there',
            'when', 'where', 'why', 'how', 'all', 'each', 'few', 'more', 'most',
            'other', 'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same',
            'so', 'than', 'too', 'very', 'just', 'and', 'but', 'if', 'or', 'because',
            'until', 'while', 'this', 'that', 'these', 'those', 'i', 'me', 'my',
            'myself', 'we', 'our', 'ours', 'ourselves', 'you', 'your', 'yours',
            'yourself', 'yourselves', 'he', 'him', 'his', 'himself', 'she', 'her',
            'hers', 'herself', 'it', 'its', 'itself', 'they', 'them', 'their',
            'theirs', 'themselves', 'what', 'which', 'who', 'whom', 'am'
        ])

        # 只初始化一次自定义词典
        if not TokenizerService._initialized:
            self._init_custom_dict()
            TokenizerService._initialized = True

    def _init_custom_dict(self):
        """
        初始化自定义词典
        
        优先级：
        1. 本地scel文件（dicts目录）
        2. 下载搜狗词库
        3. 基础词典（兜底）
        """
        total_words = 0
        
        # 确保词典目录存在
        os.makedirs(DICT_DIR, exist_ok=True)
        
        # 1. 尝试加载本地scel文件
        scel_files = [f for f in os.listdir(DICT_DIR) if f.endswith('.scel')]
        for scel_file in scel_files:
            scel_path = os.path.join(DICT_DIR, scel_file)
            words = SogouDictParser.parse(scel_path)
            if words:
                self._load_words_to_jieba(words)
                total_words += len(words)
                logger.info(f"[Tokenizer] 从 {scel_file} 加载 {len(words)} 个词语")
        
        # 2. 如果没有本地词库，尝试下载（可选，默认关闭避免网络依赖）
        # 取消注释下面代码可启用自动下载
        # if total_words == 0:
        #     total_words = self._download_and_load_sogou_dicts()
        
        # 3. 加载基础词典作为兜底
        if total_words == 0:
            self._load_basic_dict()
            logger.info("[Tokenizer] 已加载基础词典（建议下载搜狗细胞词库以获得更好效果）")
        else:
            logger.info(f"[Tokenizer] 词典初始化完成，共加载 {total_words} 个词语")

    def _load_words_to_jieba(self, words: Set[str], freq: int = 3, tag: str = 'n'):
        """
        将词语加载到jieba
        
        Args:
            words: 词语集合
            freq: 词频
            tag: 词性
        """
        for word in words:
            jieba.add_word(word, freq, tag)

    def _load_basic_dict(self):
        """加载基础词典"""
        import tempfile
        
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
                lines = []
                for line in BASIC_CUSTOM_DICT.strip().split('\n'):
                    line = line.strip()
                    if line:
                        lines.append(line)
                f.write('\n'.join(lines))
                temp_path = f.name
            
            jieba.load_userdict(temp_path)
            
            try:
                os.unlink(temp_path)
            except:
                pass
                
        except Exception as e:
            logger.error(f"[Tokenizer] 加载基础词典失败: {str(e)}")

    def _download_and_load_sogou_dicts(self) -> int:
        """
        下载并加载搜狗词库
        
        Returns:
            加载的词语数量
        """
        total_words = 0
        
        for name, url in SOGOU_DICT_URLS.items():
            save_path = os.path.join(DICT_DIR, f'{name}.scel')
            
            # 如果已存在则跳过
            if os.path.exists(save_path):
                logger.info(f"[Tokenizer] 词库已存在: {name}.scel")
                words = SogouDictParser.parse(save_path)
                if words:
                    self._load_words_to_jieba(words)
                    total_words += len(words)
                continue
            
            # 下载词库
            if SogouDictParser.download(url, save_path):
                words = SogouDictParser.parse(save_path)
                if words:
                    self._load_words_to_jieba(words)
                    total_words += len(words)
        
        return total_words

    def add_word(self, word: str, freq: int = 3, tag: str = 'n'):
        """
        动态添加词语到词典
        
        Args:
            word: 词语
            freq: 词频（越高越优先）
            tag: 词性
        """
        if HAS_JIEBA:
            jieba.add_word(word, freq, tag)
            logger.info(f"[Tokenizer] 添加词语: {word}")

    def add_words(self, words: List[str], freq: int = 3, tag: str = 'n'):
        """
        批量添加词语
        
        Args:
            words: 词语列表
            freq: 词频
            tag: 词性
        """
        for word in words:
            self.add_word(word, freq, tag)

    def load_sogou_dict(self, scel_path: str):
        """
        加载搜狗细胞词库
        
        Args:
            scel_path: scel文件路径
        """
        words = SogouDictParser.parse(scel_path)
        if words:
            self._load_words_to_jieba(words)
            logger.info(f"[Tokenizer] 从 {scel_path} 加载 {len(words)} 个词语")
        return len(words) if words else 0

    def tokenize(self, text: str, remove_stopwords: bool = True) -> List[str]:
        """
        对文本进行分词
        
        处理规则：
        - 中文：使用jieba分词
        - 英文：保持原词，统一转小写
        - 数字：保留
        - 停用词：可选择过滤
        
        Args:
            text: 输入文本
            remove_stopwords: 是否移除停用词
            
        Returns:
            分词结果列表
        """
        if not text or not text.strip():
            return []
        
        tokens = []
        
        # 分离中文和英文部分
        chinese_pattern = re.compile(r'[\u4e00-\u9fff]+')
        english_pattern = re.compile(r'[a-zA-Z]+')
        number_pattern = re.compile(r'[0-9]+')
        
        # 提取中文部分并分词
        chinese_texts = chinese_pattern.findall(text)
        for chinese_text in chinese_texts:
            if HAS_JIEBA:
                # 使用jieba精确模式分词
                words = jieba.lcut(chinese_text)
                for word in words:
                    word = word.strip()
                    if len(word) > 0:
                        if remove_stopwords and word in self.chinese_stopwords:
                            continue
                        tokens.append(word)
            else:
                # 如果jieba不可用，按字符分割
                for char in chinese_text:
                    if char.strip():
                        if remove_stopwords and char in self.chinese_stopwords:
                            continue
                        tokens.append(char)
        
        # 提取英文部分并处理
        english_texts = english_pattern.findall(text)
        for english_text in english_texts:
            word = english_text.lower()  # 统一转小写
            if len(word) > 1:  # 过滤单字母
                if remove_stopwords and word in self.english_stopwords:
                    continue
                tokens.append(word)
        
        # 提取数字
        numbers = number_pattern.findall(text)
        for num in numbers:
            if len(num) > 0:
                tokens.append(num)
        
        return tokens

    def tokenize_batch(self, texts: List[str], remove_stopwords: bool = True) -> List[List[str]]:
        """
        批量分词
        
        Args:
            texts: 文本列表
            remove_stopwords: 是否移除停用词
            
        Returns:
            分词结果列表的列表
        """
        return [self.tokenize(text, remove_stopwords) for text in texts]

    def tokenize_to_json(self, text: str, remove_stopwords: bool = True) -> str:
        """
        分词并返回JSON字符串（用于存储到数据库）
        
        Args:
            text: 输入文本
            remove_stopwords: 是否移除停用词
            
        Returns:
            JSON格式的分词结果
        """
        tokens = self.tokenize(text, remove_stopwords)
        return json.dumps(tokens, ensure_ascii=False)

    def json_to_tokens(self, json_str: str) -> List[str]:
        """
        从JSON字符串解析分词结果
        
        Args:
            json_str: JSON格式的分词结果
            
        Returns:
            分词列表
        """
        if not json_str:
            return []
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            return []


# 创建全局实例
tokenizer_service = TokenizerService()

__all__ = ['TokenizerService', 'tokenizer_service', 'SogouDictParser']
