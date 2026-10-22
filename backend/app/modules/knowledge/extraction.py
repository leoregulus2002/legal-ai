import io
import logging
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from time import perf_counter
from typing import BinaryIO
from xml.etree import ElementTree

from pypdf import PdfReader

from app.common.exceptions import AppError
from app.core.logging import redact_log_text
from app.modules.knowledge.schemas import ParseIssue, SourceSpan

MAX_TEXT = 2_000_000
MAX_XML = 64 * 1024 * 1024
OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
logger = logging.getLogger(__name__)
MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
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


def assign_text(result: Extracted, text: str) -> None:
    if len(text) > MAX_TEXT:
        raise AppError("document_too_long", "文档提取内容过长，请拆分后导入")
    result.text = text
    offset = 0
    for index, line in enumerate(text.splitlines(keepends=True), 1):
        result.spans.append(
            SourceSpan(kind="line", index=index, start=offset, end=offset + len(line))
        )
        offset += len(line)


def log_word_failure(
    error: BaseException,
    stderr: BinaryIO,
    *,
    executable: str,
    input_size: int,
    started: float,
    stage: str = "legacy_word_extract",
) -> str:
    try:
        stderr.seek(0, io.SEEK_END)
        size = stderr.tell()
        stderr.seek(0)
        raw = stderr.read(4096)
    except OSError as diagnostic_error:
        logger.error(
            "旧版 Word 诊断信息读取失败 stage=legacy_word_diagnostics "
            "executable=%s input_bytes=%s，保留原始提取异常",
            executable,
            input_size,
            exc_info=diagnostic_error,
        )
        size, raw = -1, b""
    diagnostic = redact_log_text(raw.decode("utf-8", errors="replace"))
    logger.error(
        "旧版 Word 提取失败 stage=%s executable=%s returncode=%s "
        "input_bytes=%s duration_ms=%.1f stderr_bytes=%s stderr_encoding=utf-8 "
        "stderr_decode_replacements=%s stderr_truncated=%s stderr_excerpt=%r",
        stage,
        executable,
        getattr(error, "returncode", None),
        input_size,
        (perf_counter() - started) * 1000,
        size,
        diagnostic.count("\ufffd"),
        size > len(raw),
        diagnostic,
        exc_info=error,
    )
    return diagnostic.lower()


def read_word_text(output: BinaryIO) -> str:
    output.seek(0)
    value = output.read(MAX_TEXT * 4 + 1)
    if len(value) > MAX_TEXT * 4:
        raise AppError("document_too_long", "文档提取内容过长，请拆分后导入")
    try:
        return value.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    except UnicodeError as exc:
        raise AppError(
            "legacy_word_encoding", "旧版 Word 文字编码无法识别，请转换为 DOCX 后重新导入"
        ) from exc


def extract_small_word(source: Path, converter: str, *, input_size: int) -> str:
    if converter:
        executable = shutil.which(converter)
    elif sys.platform == "darwin":
        executable = "/usr/bin/textutil" if Path("/usr/bin/textutil").is_file() else None
    else:
        executable = shutil.which("soffice") or shutil.which("libreoffice")
    if not executable:
        logger.error(
            "短篇 Word 兼容组件未找到 stage=legacy_word_convert "
            "configured_executable=%s platform=%s input_bytes=%s",
            converter or "auto",
            sys.platform,
            input_size,
        )
        raise AppError(
            "word_converter_unavailable",
            "此短篇 Word 需要兼容解析组件，请联系管理员配置，或另存为 DOCX 后导入",
            503,
        )
    directory = source.parent
    if Path(executable).name.lower() == "textutil":
        command = [
            executable,
            "-convert",
            "txt",
            "-encoding",
            "UTF-8",
            "-noload",
            "-nostore",
            "-stdout",
            str(source),
        ]
        converted_file = None
    else:
        # 独立用户配置与输出目录，避免并发转换复用进程或污染原件。
        output_directory = directory / "converted"
        output_directory.mkdir()
        profile = directory / "office-profile"
        command = [
            executable,
            f"-env:UserInstallation={profile.as_uri()}",
            "--headless",
            "--nologo",
            "--nodefault",
            "--norestore",
            "--convert-to",
            "txt:Text (encoded):UTF8",
            "--outdir",
            str(output_directory),
            str(source),
        ]
        converted_file = output_directory / "original.txt"
    started = perf_counter()
    logger.info(
        "启用短篇 Word 兼容解析 stage=legacy_word_convert executable=%s "
        "input_bytes=%s reason=antiword_small_text_stream",
        executable,
        input_size,
    )
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as stderr:
        try:
            completed = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=stderr,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            log_word_failure(
                exc,
                stderr,
                executable=executable,
                input_size=input_size,
                started=started,
                stage="legacy_word_convert",
            )
            raise AppError(
                "word_conversion_failed", "Word 兼容解析未完成，请稍后重试或另存为 DOCX 后导入"
            ) from exc
        if completed.returncode != 0 or (
            converted_file is not None and not converted_file.is_file()
        ):
            failure: Exception = (
                subprocess.CalledProcessError(completed.returncode, command)
                if completed.returncode != 0
                else RuntimeError(
                    "Word converter returned success without creating its output file"
                )
            )
            if converted_file is not None:
                # LibreOffice 的 stdout 为转换状态；textutil 的 stdout 是正文，不写入日志。
                output.seek(0)
                status = output.read(4096)
                logger.error(
                    "Word 转换未生成可用文件 stage=legacy_word_convert executable=%s "
                    "returncode=%s output_exists=%s status_excerpt=%r status_truncated=%s",
                    executable,
                    completed.returncode,
                    converted_file.is_file(),
                    redact_log_text(status.decode("utf-8", errors="replace")),
                    bool(output.read(1)),
                )
            log_word_failure(
                failure,
                stderr,
                executable=executable,
                input_size=input_size,
                started=started,
                stage="legacy_word_convert",
            )
            raise AppError(
                "word_conversion_failed", "Word 兼容解析失败，请确认文件完整或另存为 DOCX 后导入"
            ) from failure
        if converted_file is None:
            text = read_word_text(output)
        else:
            with converted_file.open("rb") as converted:
                text = read_word_text(converted)
    if not text.strip():
        logger.warning(
            "短篇 Word 兼容解析未返回正文 stage=legacy_word_convert executable=%s "
            "input_bytes=%s duration_ms=%.1f",
            executable,
            input_size,
            (perf_counter() - started) * 1000,
        )
        raise AppError("word_conversion_empty", "Word 未提取到正文，请确认内容或另存为 DOCX 后导入")
    logger.info(
        "短篇 Word 兼容解析完成 stage=legacy_word_convert executable=%s "
        "input_bytes=%s characters=%s duration_ms=%.1f",
        executable,
        input_size,
        len(text),
        (perf_counter() - started) * 1000,
    )
    return text


def extract_legacy_word(data: bytes, executable: str, converter: str = "") -> str:
    # 在后台提取线程中执行；独立临时目录，原件保持不变。
    with tempfile.TemporaryDirectory(prefix="legal-ai-word-") as directory:
        source = Path(directory) / "original.doc"
        source.write_bytes(data)
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as stderr:
            command = [executable, "-t", "-w", "0", "-m", "UTF-8.txt", str(source)]
            started = perf_counter()
            try:
                completed = subprocess.run(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=stderr,
                    timeout=30,
                    check=False,
                )
            except OSError as exc:
                log_word_failure(
                    exc, stderr, executable=executable, input_size=len(data), started=started
                )
                raise AppError(
                    "word_extractor_unavailable", "旧版 Word 解析组件未就绪，请联系管理员"
                ) from exc
            except subprocess.TimeoutExpired as exc:
                log_word_failure(
                    exc, stderr, executable=executable, input_size=len(data), started=started
                )
                raise AppError(
                    "legacy_word_timeout", "旧版 Word 提取超时，请转换为 DOCX 或 PDF 后重新导入"
                ) from exc
            if completed.returncode != 0:
                failure = subprocess.CalledProcessError(completed.returncode, command)
                diagnostic = log_word_failure(
                    failure, stderr, executable=executable, input_size=len(data), started=started
                )
                if "text stream of this file is too small to handle" in diagnostic:
                    return extract_small_word(source, converter, input_size=len(data))
                if (
                    "mapping file" in diagnostic
                    or "mappingfile" in diagnostic
                    or "can't set the utf-8 locale" in diagnostic
                ):
                    raise AppError(
                        "word_extractor_unavailable",
                        "旧版 Word 解析组件配置异常，请联系管理员",
                    ) from failure
                if "encrypt" in diagnostic or "password protected" in diagnostic:
                    raise AppError(
                        "encrypted_legacy_word", "Word 文件已加密，请解密后重新导入"
                    ) from failure
                if "version of word" in diagnostic and (
                    "not supported" in diagnostic or "before word 6" in diagnostic
                ):
                    raise AppError(
                        "unsupported_legacy_word",
                        "此 Word 版本暂不支持，请另存为 DOCX 或 PDF 后重新导入",
                    ) from failure
                if completed.returncode < 0:
                    raise AppError(
                        "word_extractor_failed", "Word 解析组件运行异常，请联系管理员", 503
                    ) from failure
                raise AppError(
                    "invalid_legacy_word",
                    "旧版 Word 文本提取失败，请另存为 DOCX 或 PDF 后重新导入",
                ) from failure
            return read_word_text(output)


def extract(
    filename: str, data: bytes, word_extractor_path: str = "antiword", word_converter_path: str = ""
) -> Extracted:
    suffix = Path(filename).suffix.lower()
    result = Extracted()
    if suffix in {".doc", ".docx"} and data.startswith(OLE_SIGNATURE):
        assign_text(result, extract_legacy_word(data, word_extractor_path, word_converter_path))
        result.issues.append(
            ParseIssue(
                id="legacy_word_layout",
                code="legacy_word_layout",
                severity="WARNING",
                message="原件为旧版 Word 格式，已提取正文，请对照原件核对表格及段落顺序",
            )
        )
    elif suffix == ".doc":
        raise AppError(
            "invalid_legacy_word", "文件不是可识别的旧版 Word 文档，请核对格式后重新导入"
        )
    elif suffix == ".pdf":
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
        try:
            archive = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as exc:
            raise AppError("invalid_docx", "DOCX 文件内容或格式无效，请重新保存后导入") from exc
        with archive:
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
        assign_text(result, text)
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
