import io
import re
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

from pypdf import PdfReader

from app.common.exceptions import AppError
from app.modules.knowledge.schemas import ParseIssue, SourceSpan

MAX_TEXT = 2_000_000
MAX_XML = 64 * 1024 * 1024
MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".html": "text/html",
    ".htm": "text/html",
}


@dataclass
class Extracted:
    text: str = ""
    spans: list[SourceSpan] = field(default_factory=list)
    issues: list[ParseIssue] = field(default_factory=list)

    def append(self, text: str, kind: str, index: int) -> None:
        start = len(self.text)
        if start + len(text) + 1 > MAX_TEXT:
            raise AppError("document_too_long", "文档提取内容过长，请拆分文件后导入")
        self.text += text + "\n"
        self.spans.append(SourceSpan(kind=kind, index=index, start=start, end=len(self.text)))


class HTMLText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0
        self.length = 0

    def add(self, value: str) -> None:
        self.length += len(value)
        if self.length > MAX_TEXT:
            raise AppError("document_too_long", "HTML 正文过长，请拆分后导入")
        self.parts.append(value)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "template"}:
            self.hidden += 1
        if not self.hidden and tag in {
            "p",
            "div",
            "br",
            "li",
            "tr",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "hr",
        }:
            self.add("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "template"}:
            self.hidden = max(0, self.hidden - 1)
        if not self.hidden and tag in {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.add("\n")
        if not self.hidden and tag in {"td", "th"}:
            self.add("\t")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.add(data)


def decode(data: bytes) -> str:
    encodings = (
        ["utf-16"] if data.startswith((b"\xff\xfe", b"\xfe\xff")) else ["utf-8-sig", "gb18030"]
    )
    for encoding in encodings:
        try:
            text = data.decode(encoding)
            if "\x00" in text:
                break
            return text.replace("\r\n", "\n").replace("\r", "\n")
        except UnicodeError:
            continue
    raise AppError("text_encoding", "无法识别文本编码，请使用 UTF-8、UTF-16 或 GB18030 保存")


def extract(filename: str, data: bytes) -> Extracted:
    suffix = Path(filename).suffix.lower()
    result = Extracted()
    if suffix == ".pdf":
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise AppError("encrypted_pdf", "PDF 已加密，请解密后重新导入")
        if len(reader.pages) > 1000:
            raise AppError("too_many_pages", "PDF 超过 1000 页，请拆分后导入")
        for index, page in enumerate(reader.pages, 1):
            start = len(result.text)
            blank = False
            has_images = False
            try:
                content = page.get_contents()
                stream = content.get_data() if content else b""
                blank = not stream.strip()
                if len(stream) > MAX_XML:
                    raise ValueError("page stream too large")
                text = page.extract_text() or ""
                try:
                    has_images = bool(page.images)
                except Exception:
                    result.issues.append(
                        ParseIssue(
                            id=f"pdf_images:{index}",
                            code="pdf_images",
                            severity="WARNING",
                            message=f"第 {index} 页图像信息无法识别，请核对是否包含未提取文字",
                        )
                    )
            except Exception:
                text = ""
                result.issues.append(
                    ParseIssue(
                        id=f"page_failed:{index}",
                        code="page_failed",
                        severity="ERROR",
                        message=f"第 {index} 页无法提取，需检查原件后重新导入",
                        start=start,
                        end=start,
                    )
                )
            result.append(text, "page", index)
            if len(re.sub(r"\s", "", text)) < 15:
                needs_ocr = not blank and (not text.strip() or has_images)
                result.issues.append(
                    ParseIssue(
                        id=f"{'ocr_required' if needs_ocr else 'sparse_page'}:{index}",
                        code="ocr_required" if needs_ocr else "sparse_page",
                        severity="ERROR" if needs_ocr else "WARNING",
                        message=(
                            f"第 {index} 页可能为扫描页，需 OCR 后重新导入"
                            if needs_ocr
                            else f"第 {index} 页为空白或文字很少，请对照原件核对"
                        ),
                        start=start,
                        end=len(result.text),
                    )
                )
        result.issues.append(
            ParseIssue(
                id="pdf_layout",
                code="pdf_layout",
                severity="WARNING",
                message="PDF 阅读顺序与换行由文本层提取，请对照原件检查页眉、表格及条文顺序",
            )
        )
    elif suffix == ".docx":
        namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if sum(info.file_size for info in archive.infolist()) > MAX_XML:
                raise AppError("docx_too_large", "DOCX 解压内容过大，请拆分后导入")
            names = archive.namelist()
            if "word/document.xml" not in names:
                raise AppError("invalid_docx", "文件不是有效的 DOCX 文档")
            parts = ["word/document.xml"] + sorted(
                name
                for name in names
                if re.fullmatch(r"word/(?:footnotes|endnotes|header\d*|footer\d*)\.xml", name)
            )
            for part in parts:
                xml = archive.read(part)
                if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
                    raise AppError("invalid_docx", "DOCX 含不支持的 XML 声明")
                root = ElementTree.fromstring(xml)
                tags = {element.tag for element in root.iter()}
                for tag, code, message in (
                    ("numPr", "docx_numbering", "文档含自动编号，请核对提取文本及项、目编号"),
                    ("drawing", "docx_drawing", "文档含图像或文本框，请核对其文字是否完整提取"),
                    ("altChunk", "docx_embedded", "文档含嵌入内容，需要转换后重新导入"),
                    ("del", "docx_changes", "文档含修订标记，请对照原件确认最终版本"),
                ):
                    if namespace + tag in tags and not any(
                        issue.code == code for issue in result.issues
                    ):
                        result.issues.append(
                            ParseIssue(
                                id=code,
                                code=code,
                                severity="ERROR" if tag == "altChunk" else "WARNING",
                                message=message,
                            )
                        )
                pending = [root]
                while pending:
                    paragraph = pending.pop()
                    if paragraph.tag != namespace + "p":
                        pending.extend(reversed(list(paragraph)))
                        continue
                    # 文本框的嵌套段落已按其原位置包含，避免第二次遍历重复加入。
                    text = "".join(
                        (element.text or "")
                        if element.tag == namespace + "t"
                        else "\n"
                        if element.tag in {namespace + "br", namespace + "cr"}
                        else "\t"
                        if element.tag == namespace + "tab"
                        else ""
                        for element in paragraph.iter()
                    )
                    result.append(text, part, len(result.spans) + 1)
            if len(parts) > 1:
                result.issues.append(
                    ParseIssue(
                        id="docx_extra_parts",
                        code="docx_extra_parts",
                        severity="WARNING",
                        message="页眉、页脚、脚注或尾注已附于正文之后，请核对法律结构边界",
                    )
                )
    else:
        text = decode(data)
        if suffix in {".html", ".htm"}:
            parser = HTMLText()
            parser.feed(text)
            parser.close()
            text = "".join(parser.parts)
        if len(text) > MAX_TEXT:
            raise AppError("document_too_long", "文档提取内容过长，请拆分后导入")
        result.text = text
        offset = 0
        for index, line in enumerate(text.splitlines(keepends=True), 1):
            result.spans.append(
                SourceSpan(kind="line", index=index, start=offset, end=offset + len(line))
            )
            offset += len(line)
    if not result.text.strip():
        result.issues.append(
            ParseIssue(
                id="empty_text",
                code="empty_text",
                severity="ERROR",
                message="未提取到正文；原件已保留，扫描 PDF 需要 OCR 后重新导入",
            )
        )
    return result
