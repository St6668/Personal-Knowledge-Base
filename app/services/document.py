"""
多格式文档解析器 + 文本分块器

功能：
- 支持 PDF、Word(.docx)、纯文本(.txt)、Markdown(.md)、XMind(.xmind) 格式解析
- 提供智能文本分块，优先按段落切分，段落过长则按句子切分
- 分块使用滑动窗口策略，相邻块之间有重叠以保持语义连续性

依赖：pdfplumber、python-docx、xmindparser
"""

import re


class DocumentParser:
    """
    多格式文档解析器

    根据文件类型将文档内容提取为纯文本。
    支持 PDF、Word、TXT、Markdown、XMind 五种格式。
    """

    @staticmethod
    def parse_pdf(file_path: str) -> str:
        """
        使用 pdfplumber 解析 PDF 文件，提取所有页面的文本

        参数:
            file_path: PDF 文件的绝对路径

        返回:
            提取的纯文本内容（各页之间以双换行分隔）

        异常:
            ImportError: 未安装 pdfplumber 库
        """
        import pdfplumber

        text_parts = []
        with pdfplumber.open(file_path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
        return "\n\n".join(text_parts)

    @staticmethod
    def parse_docx(file_path: str) -> str:
        """
        使用 python-docx 解析 Word 文档，提取所有段落的文本

        参数:
            file_path: .docx 文件的绝对路径

        返回:
            提取的纯文本内容（各段落之间以双换行分隔）

        异常:
            ImportError: 未安装 python-docx 库
        """
        from docx import Document as DocxDocument

        doc = DocxDocument(file_path)
        paragraphs = []
        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                paragraphs.append(text)
        return "\n\n".join(paragraphs)

    @staticmethod
    def parse_txt(file_path: str) -> str:
        """
        直接读取文本文件，自动处理编码

        尝试顺序：UTF-8 → GBK → Latin-1（兜底，不会抛出解码异常）

        参数:
            file_path: 文本文件的绝对路径

        返回:
            文件内容字符串
        """
        # 优先尝试 UTF-8（最通用的编码）
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
        except UnicodeDecodeError:
            pass

        # 回退到 GBK（Windows 中文环境常见编码）
        try:
            with open(file_path, "r", encoding="gbk") as f:
                return f.read()
        except UnicodeDecodeError:
            pass

        # 最终兜底使用 Latin-1（逐字节映射，不会抛出解码异常）
        with open(file_path, "r", encoding="latin-1") as f:
            return f.read()

    @staticmethod
    def parse_markdown(file_path: str) -> str:
        """
        读取 Markdown 文件，去除格式标记后返回纯文本

        处理的 Markdown 标记：
        - 代码块（```...```）
        - 行内代码（`...`）
        - 图片（![alt](url)）
        - 链接（[text](url)）
        - 标题（# 标记）
        - 粗体/斜体（**、*、__、_）
        - 水平线（---、***、___）
        - 列表标记（-、*、+、1.）
        - 引用（> ）

        参数:
            file_path: .md 或 .markdown 文件的绝对路径

        返回:
            去除格式标记后的纯文本
        """
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # 去除代码块（```...```），包括带语言标识的
        content = re.sub(r'```[\s\S]*?```', '', content)
        # 去除行内代码标记 `...`
        content = re.sub(r'`([^`]*)`', r'\1', content)
        # 去除图片 ![alt](url)
        content = re.sub(r'!\[.*?\]\(.*?\)', '', content)
        # 去除链接 [text](url)，保留链接文字
        content = re.sub(r'\[([^\]]*)\]\(.*?\)', r'\1', content)
        # 去除标题标记 #、## 等，保留标题文字
        content = re.sub(r'^#{1,6}\s+', '', content, flags=re.MULTILINE)
        # 去除粗体标记 **text**
        content = re.sub(r'\*\*([^*]*)\*\*', r'\1', content)
        # 去除斜体标记 *text*
        content = re.sub(r'\*([^*]*)\*', r'\1', content)
        # 去除粗体标记 __text__
        content = re.sub(r'__([^_]*)__', r'\1', content)
        # 去除斜体标记 _text_
        content = re.sub(r'_([^_]*)_', r'\1', content)
        # 去除水平线（---、***、___）
        content = re.sub(r'^[-*_]{3,}\s*$', '', content, flags=re.MULTILINE)
        # 去除无序列表标记（-、*、+）
        content = re.sub(r'^\s*[-*+]\s+', '', content, flags=re.MULTILINE)
        # 去除有序列表标记（1.、2. 等）
        content = re.sub(r'^\s*\d+\.\s+', '', content, flags=re.MULTILINE)
        # 去除引用标记 >
        content = re.sub(r'^>\s+', '', content, flags=re.MULTILINE)

        return content.strip()

    @staticmethod
    def parse_xmind(file_path: str) -> str:
        """
        使用 xmindparser 解析 XMind 文件，提取主题树结构和所有文本

        递归遍历思维导图的主题树，用缩进层级表示父子关系。

        参数:
            file_path: .xmind 文件的绝对路径

        返回:
            树形文本（层级用缩进表示，多个画布以【画布名】分隔）

        异常:
            ImportError: 未安装 xmindparser 库
        """
        import xmindparser

        # 配置 xmindparser 输出为字典格式（而非 JSON 字符串）
        xmindparser.config["dict"] = True
        content = xmindparser.xmind_to_dict(file_path)

        def _extract_topic(topic: dict, level: int = 0) -> list[str]:
            """
            递归提取主题树中的文本

            参数:
                topic: 主题字典，包含 title 和 topics 字段
                level: 当前缩进层级

            返回:
                文本行列表
            """
            lines = []
            title = topic.get("title", "")
            if title:
                indent = "  " * level
                lines.append(f"{indent}- {title}")

            # 递归处理子主题
            children = topic.get("topics", [])
            for child in children:
                lines.extend(_extract_topic(child, level + 1))

            return lines

        result_lines = []
        # xmindparser 返回列表（每个元素为一个画布）或字典（单画布）
        sheets = content if isinstance(content, list) else [content]

        for sheet in sheets:
            sheet_title = sheet.get("title", "")
            if sheet_title:
                result_lines.append(f"【{sheet_title}】")
            root_topic = sheet.get("topic", {})
            result_lines.extend(_extract_topic(root_topic))

        return "\n".join(result_lines)

    @classmethod
    def parse(cls, file_path: str, file_type: str) -> str:
        """
        根据文件类型分发到对应的解析方法

        参数:
            file_path: 文件的绝对路径
            file_type: 文件类型标识（不区分大小写）

        支持的类型（含别名）：
            - pdf
            - word / docx
            - txt / text
            - markdown / md
            - xmind

        返回:
            解析后的纯文本内容

        异常:
            ValueError: 不支持的文件类型
        """
        parsers = {
            "pdf": cls.parse_pdf,
            "word": cls.parse_docx,
            "docx": cls.parse_docx,
            "txt": cls.parse_txt,
            "text": cls.parse_txt,
            "markdown": cls.parse_markdown,
            "md": cls.parse_markdown,
            "xmind": cls.parse_xmind,
        }

        file_type_lower = file_type.lower()
        parser = parsers.get(file_type_lower)
        if parser is None:
            raise ValueError(
                f"不支持的文件类型: '{file_type}'，"
                f"支持的类型: {sorted(set(parsers.keys()))}"
            )

        return parser(file_path)


class TextChunker:
    """
    文本分块器

    将长文本切分为有重叠的语义块，用于向量化检索。
    策略：优先按段落切分 → 段落过长则按句子切分 → 滑动窗口合并。
    """

    @staticmethod
    def chunk(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
        """
        将长文本切分为有重叠的块

        分块策略（按优先级）：
        1. 先按段落（双换行 \\n\\n）切分
        2. 段落仍超过 chunk_size 的，按句子分隔符（。！？!?.\\n）进一步切分
        3. 以 chunk_size 为窗口、overlap 为重叠量，按滑动窗口合并句子为块

        参数:
            text: 原始文本
            chunk_size: 每块最大字符数（默认 500）
            overlap: 相邻块之间的重叠字符数（默认 50）

        返回:
            文本块列表，每个元素为一个文本片段
        """
        if not text or not text.strip():
            return []

        # 第一步：按段落（双换行或多换行）切分
        paragraphs = re.split(r'\n\s*\n', text.strip())

        # 第二步：将长段落进一步切分为句子
        sentences = []
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            if len(para) <= chunk_size:
                sentences.append(para)
            else:
                # 按句子分隔符切分长段落（在分隔符之后切分，保留分隔符）
                para_sentences = re.split(r'(?<=[。！？!?.\n])', para)
                for sent in para_sentences:
                    sent = sent.strip()
                    if sent:
                        sentences.append(sent)

        # 第三步：以滑动窗口合并句子为块
        chunks = []
        current_chunk = ""

        for sentence in sentences:
            # 如果单个句子就超过 chunk_size，强制按长度截断
            if len(sentence) > chunk_size:
                # 先保存当前累积的块
                if current_chunk:
                    chunks.append(current_chunk.strip())
                    current_chunk = ""
                # 将超长句子分段处理
                for i in range(0, len(sentence), chunk_size - overlap):
                    piece = sentence[i:i + chunk_size]
                    if piece.strip():
                        chunks.append(piece.strip())
                continue

            # 尝试将句子加入当前块
            if len(current_chunk) + len(sentence) + 1 <= chunk_size:
                if current_chunk:
                    current_chunk += "\n" + sentence
                else:
                    current_chunk = sentence
            else:
                # 当前块已满，保存并开始新块（带重叠）
                if current_chunk:
                    chunks.append(current_chunk.strip())

                # 重叠处理：新块的开头从旧块末尾截取 overlap 个字符
                if overlap > 0 and len(current_chunk) > overlap:
                    overlap_text = current_chunk[-overlap:]
                    current_chunk = overlap_text + "\n" + sentence
                else:
                    current_chunk = sentence

        # 保存最后一块（可能不满 chunk_size）
        if current_chunk.strip():
            chunks.append(current_chunk.strip())

        return chunks
