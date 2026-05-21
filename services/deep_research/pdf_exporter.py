"""
研究报告 PDF 导出器

将 Markdown 格式的研究报告导出为 PDF。

使用 weasyprint 进行 PDF 渲染，支持：
- 中文内容
- 代码块
- 表格
- 页眉页脚
"""
import logging
import os
from datetime import datetime
from typing import Optional
import re

logger = logging.getLogger(__name__)


class PDFExporter:
    """
    PDF 导出器

    将 Markdown 转换为 HTML，再使用 weasyprint 渲染为 PDF。
    """

    def __init__(self):
        """初始化 PDF 导出器"""
        self._weasyprint_available = self._check_weasyprint()
        self._markdown_available = self._check_markdown()
        logger.info(f"PDFExporter initialized (weasyprint={self._weasyprint_available}, markdown={self._markdown_available})")

    def _check_weasyprint(self) -> bool:
        """检查 weasyprint 是否可用"""
        try:
            import weasyprint
            logger.info(f"[PDFExporter] weasyprint available, version: {weasyprint.__version__}")
            return True
        except ImportError:
            logger.warning("[PDFExporter] weasyprint not installed, PDF export will be disabled")
            return False
        except OSError as e:
            # weasyprint 安装了但系统库缺失
            logger.warning(f"[PDFExporter] weasyprint import failed (missing system libs): {e}")
            logger.warning("[PDFExporter] On macOS, install: brew install cairo pango glib harfbuzz fribidi")
            logger.warning("[PDFExporter] Then set: export DYLD_LIBRARY_PATH=/opt/homebrew/opt/glib/lib:/opt/homebrew/opt/cairo/lib:/opt/homebrew/opt/pango/lib:/opt/homebrew/opt/harfbuzz/lib:/opt/homebrew/opt/fribidi/lib:$DYLD_LIBRARY_PATH")
            return False
        except Exception as e:
            logger.warning(f"[PDFExporter] weasyprint check failed: {e}")
            return False

    def _check_markdown(self) -> bool:
        """检查 markdown 库是否可用"""
        try:
            import markdown
            return True
        except ImportError:
            logger.warning("markdown not installed, using simple HTML conversion")
            return False

    def export_pdf(
        self,
        markdown_content: str,
        title: str = "研究报告",
        output_path: Optional[str] = None,
    ) -> bytes:
        """
        将 Markdown 转换为 PDF

        Args:
            markdown_content: Markdown 格式的内容
            title: 报告标题
            output_path: 输出文件路径（可选，如果不提供则只返回 bytes）

        Returns:
            PDF 内容的字节数据

        Raises:
            RuntimeError: 如果 weasyprint 不可用
        """
        if not self._weasyprint_available:
            raise RuntimeError(
                "weasyprint is not installed. "
                "Please install it with: pip install weasyprint"
            )

        logger.info(f"[PDFExporter] Exporting PDF for report: {title}")

        # 1. Markdown 转 HTML
        html_content = self._markdown_to_html(markdown_content)

        # 2. 添加样式
        styled_html = self._add_styles(html_content, title)

        # 3. 生成 PDF
        import weasyprint

        pdf_bytes = weasyprint.HTML(string=styled_html).write_pdf()

        logger.info(f"[PDFExporter] PDF generated, size: {len(pdf_bytes)} bytes")

        # 4. 保存到文件（如果指定了路径）
        if output_path:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, 'wb') as f:
                f.write(pdf_bytes)
            logger.info(f"[PDFExporter] PDF saved to: {output_path}")

        return pdf_bytes

    def _markdown_to_html(self, markdown_content: str) -> str:
        """将 Markdown 转换为 HTML"""
        if self._markdown_available:
            import markdown

            # 使用 markdown 库进行转换
            md = markdown.Markdown(
                extensions=[
                    'tables',
                    'fenced_code',
                    'codehilite',
                    'toc',
                    'nl2br',
                ]
            )
            return md.convert(markdown_content)
        else:
            # 简单转换：处理基本的 Markdown 语法
            return self._simple_markdown_to_html(markdown_content)

    def _simple_markdown_to_html(self, text: str) -> str:
        """简单的 Markdown 到 HTML 转换"""
        html = text

        # 标题
        html = re.sub(r'^### (.*?)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
        html = re.sub(r'^## (.*?)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
        html = re.sub(r'^# (.*?)$', r'<h1>\1</h1>', html, flags=re.MULTILINE)

        # 粗体和斜体
        html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
        html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)

        # 链接
        html = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2">\1</a>', html)

        # 引用
        html = re.sub(r'^> (.*?)$', r'<blockquote>\1</blockquote>', html, flags=re.MULTILINE)

        # 列表
        html = re.sub(r'^- (.*?)$', r'<li>\1</li>', html, flags=re.MULTILINE)

        # 分割线
        html = re.sub(r'^---$', r'<hr>', html, flags=re.MULTILINE)

        # 段落
        html = re.sub(r'\n\n', r'</p><p>', html)
        html = f'<p>{html}</p>'

        return html

    def _add_styles(self, html_content: str, title: str) -> str:
        """添加 CSS 样式"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # CSS 样式
        css = """
        @page {
            size: A4;
            margin: 2cm;
            @top-center {
                content: "MalogBot 研究报告";
                font-size: 10pt;
                color: #666;
            }
            @bottom-center {
                content: "第 " counter(page) " 页";
                font-size: 10pt;
                color: #666;
            }
        }

        body {
            font-family: "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", sans-serif;
            font-size: 11pt;
            line-height: 1.6;
            color: #333;
        }

        h1 {
            font-size: 20pt;
            color: #1a1a1a;
            border-bottom: 2px solid #4a90d9;
            padding-bottom: 10px;
            margin-top: 0;
        }

        h2 {
            font-size: 16pt;
            color: #2a2a2a;
            border-bottom: 1px solid #ddd;
            padding-bottom: 5px;
            margin-top: 20px;
        }

        h3 {
            font-size: 14pt;
            color: #3a3a3a;
            margin-top: 15px;
        }

        p {
            text-align: justify;
            margin: 10px 0;
        }

        blockquote {
            border-left: 3px solid #4a90d9;
            padding-left: 15px;
            margin: 10px 0;
            color: #666;
            background-color: #f9f9f9;
            padding: 10px 15px;
        }

        code {
            background-color: #f5f5f5;
            padding: 2px 5px;
            border-radius: 3px;
            font-family: "Consolas", "Monaco", monospace;
            font-size: 10pt;
        }

        pre {
            background-color: #f5f5f5;
            padding: 10px;
            border-radius: 5px;
            overflow-x: auto;
            border: 1px solid #ddd;
        }

        pre code {
            background-color: transparent;
            padding: 0;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            margin: 15px 0;
        }

        th, td {
            border: 1px solid #ddd;
            padding: 8px;
            text-align: left;
        }

        th {
            background-color: #f5f5f5;
            font-weight: bold;
        }

        a {
            color: #4a90d9;
            text-decoration: none;
        }

        a:hover {
            text-decoration: underline;
        }

        ul, ol {
            margin: 10px 0;
            padding-left: 25px;
        }

        li {
            margin: 5px 0;
        }

        hr {
            border: none;
            border-top: 1px solid #ddd;
            margin: 20px 0;
        }

        strong {
            color: #1a1a1a;
        }

        .report-meta {
            color: #666;
            font-size: 10pt;
            margin-bottom: 20px;
        }

        .footer {
            margin-top: 30px;
            padding-top: 10px;
            border-top: 1px solid #ddd;
            font-size: 9pt;
            color: #999;
            text-align: center;
        }
        """

        # 完整的 HTML 文档
        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{title}</title>
    <style>{css}</style>
</head>
<body>
{html_content}
<div class="footer">
    本报告由 MalogBot 自动生成于 {timestamp}
</div>
</body>
</html>"""

        return html


def export_to_pdf(
    markdown_content: str,
    title: str = "研究报告",
    output_path: Optional[str] = None,
) -> bytes:
    """
    导出 PDF 的便捷函数

    Args:
        markdown_content: Markdown 内容
        title: 报告标题
        output_path: 输出文件路径（可选）

    Returns:
        PDF 字节数据
    """
    exporter = PDFExporter()
    return exporter.export_pdf(markdown_content, title, output_path)
