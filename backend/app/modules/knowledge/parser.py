import re
from datetime import date

from app.modules.knowledge.extraction import Extracted
from app.modules.knowledge.metadata import CATEGORY_VALUES
from app.modules.knowledge.schemas import (
    Anchor,
    LegalMetadata,
    ParseIssue,
    ParseResult,
    StructureNode,
)
from app.modules.knowledge.validation import validate_structure

NUM = r"[零〇一二三四五六七八九十百千万两\d]+"
HEADING = re.compile(
    rf"(?m)^[ \t\u3000]*(?:\#{{1,6}}[ \t]+)?(?:\*\*)?"
    rf"(?P<label>第\s*(?P<number>{NUM})\s*(?P<unit>[编章节条])"
    rf"(?:\s*之\s*(?P<suffix>{NUM}))?|附\s*则|附\s*件(?:\s*{NUM})?[:：]?)"
)
ARTICLE_INLINE = re.compile(rf"(?<=[。；;\n\u3000 ])第\s*({NUM})\s*条(?:之\s*({NUM}))?")
KINDS = {"编": "PART", "章": "CHAPTER", "节": "SECTION", "条": "ARTICLE"}
LEVEL = {"PART": 1, "CHAPTER": 2, "SECTION": 3, "SUPPLEMENT": 2, "ANNEX": 0, "ARTICLE": 4}


def numeral(text: str) -> int | None:
    text = re.sub(r"\s", "", text)
    if len(text) > 12:
        return None
    if text.isdigit():
        return int(text) if 0 < int(text) <= 100000 else None
    digits = {char: index for index, char in enumerate("零一二三四五六七八九")}
    digits.update({"〇": 0, "两": 2})
    units = {"十": 10, "百": 100, "千": 1000, "万": 10000}
    if not any(char in units for char in text):
        value = int("".join(str(digits[char]) for char in text)) if text else 0
        return value if 0 < value <= 100000 else None
    total = section = number = 0
    for char in text:
        if char in digits:
            number = digits[char]
        elif char == "万":
            total += (section + number or 1) * 10000
            section = number = 0
        elif char in units:
            section += (number or 1) * units[char]
            number = 0
    value = total + section + number
    return value if 0 < value <= 100000 else None


def metadata(text: str) -> tuple[LegalMetadata, list[Anchor]]:
    data = LegalMetadata()
    anchors: list[Anchor] = []

    def set_value(field: str, match: re.Match[str], group: int = 1) -> None:
        value = match.group(group).strip().strip("《》")
        setattr(data, field, value)
        anchors.append(
            Anchor(
                field=field, start=match.start(group), end=match.end(group), text=match.group(group)
            )
        )

    front = text[:16000]
    title = re.search(r"(?m)^[\s#]*(?:法律名称|名称|标题)[:：]\s*([^\n]{2,300})", front)
    if not title:
        title = re.search(
            r"(?m)^[ \t\u3000#*]*[《]?([^\n《》]{2,180}"
            r"(?:法典|法|条例|规定|办法|细则|决定|解释|规则))[》]?"
            r"(?:[ \t\u3000]*([（(][^\n）)]{1,150}[）)]))?[ \t\u3000*]*$",
            front,
        )
    if title:
        set_value("title", title)
        if (
            title.lastindex
            and title.lastindex >= 2
            and title[2]
            and re.search("修订|修正|版本", title[2])
        ):
            set_value("version_label", title, 2)
    authority = re.search(
        r"(?:公布机关|发布机关|制定机关|发文机关)\s*[:：]\s*([^\n]{2,200})", front
    )
    if not authority:
        authority = re.search(
            r"(?m)^[ \t\u3000]*(中华人民共和国主席|全国人民代表大会常务委员会|"
            r"全国人民代表大会|国务院|最高人民法院|最高人民检察院|"
            r"[^\n]{2,40}人民政府)(?=[ \t\u3000]*(?:令|公告|$))",
            front,
        )
    if authority:
        set_value("authority", authority)
    number = re.search(r"(?:文号|发文字号)\s*[:：]\s*([^\n]{1,120})", front)
    if not number:
        number = re.search(
            r"((?:[^\n\s]{1,30})[〔\[（(]\d{4}[〕\]）)]\s*第?\s*\d+\s*号|(?:主席令|国务院令|令)\s*第\s*[零〇一二三四五六七八九十百\d]+\s*号)",
            front,
        )
    if number:
        set_value("document_number", number)
    version = re.search(r"(?:版本说明|版本信息|修订说明)\s*[:：]\s*([^\n]{1,200})", front)
    if version:
        set_value("version_label", version)
    region = re.search(r"(?:适用地区|适用地域|行政区域)\s*[:：]\s*([^\n]{1,100})", front)
    if region:
        set_value("region", region)
    category = re.search(r"(?:法规类别|法律法规分类|效力级别)\s*[:：]\s*([^\n]{1,50})", front)
    if category and category[1].strip() in CATEGORY_VALUES:
        data.category = CATEGORY_VALUES[category[1].strip()]
        anchors.append(
            Anchor(field="category", start=category.start(1), end=category.end(1), text=category[1])
        )
    date_pattern = r"(\d{4})\s*[年./-]\s*(\d{1,2})\s*[月./-]\s*(\d{1,2})\s*日?"
    for field, labels in (
        ("promulgated_on", "公布日期|发布日期|颁布日期"),
        ("effective_on", "施行日期|实施日期|生效日期"),
    ):
        match = re.search(rf"(?:{labels})\s*[:：]?\s*({date_pattern})", front)
        if not match and field == "effective_on":
            match = re.search(rf"(?:自|于)\s*({date_pattern})\s*(?:起施行|施行|起实施|实施)", text)
        if match:
            try:
                setattr(data, field, date(int(match[2]), int(match[3]), int(match[4])))
                anchors.append(
                    Anchor(field=field, start=match.start(1), end=match.end(1), text=match[1])
                )
            except ValueError:
                pass
    return data, anchors


def parse(extracted: Extracted, mode: str) -> ParseResult:
    text = extracted.text
    result = ParseResult(text=text, spans=extracted.spans, extraction_issues=extracted.issues)
    if mode == "GENERAL":
        result.issues = validate_structure(result, mode)
        return result
    result.metadata, result.anchors = metadata(text)
    result.metadata_sources = {anchor.field: "TEXT" for anchor in result.anchors}
    markers: list[tuple[int, int, str, str, int | None, int]] = []
    article_starts: set[int] = set()
    for match in HEADING.finditer(text):
        label = match["label"]
        compact = re.sub(r"\s", "", label)
        kind = KINDS.get(match["unit"] or "", "SUPPLEMENT" if compact == "附则" else "ANNEX")
        if kind == "CHAPTER":
            supplement = re.match(r"[ \t\u3000]+附\s*则", text[match.end() :])
            if supplement:
                kind = "SUPPLEMENT"
                label += supplement[0]
        number = numeral(match["number"]) if match["number"] else None
        markers.append(
            (
                match.start("label"),
                match.end(),
                kind,
                label,
                number,
                numeral(match["suffix"]) or 0 if match["suffix"] else 0,
            )
        )
        if kind == "ARTICLE":
            article_starts.add(match.start("label"))
    # 同一行多个条文亦可识别；不在正文中无边界匹配“第X条”引用。
    for match in ARTICLE_INLINE.finditer(text):
        if match.start() in article_starts:
            continue
        # 行内引用常有“规定/所称/的”等后缀，保守跳过，保留原文交人工检查。
        tail = text[match.end() : match.end() + 6]
        if tail.startswith(("规定", "所称", "的", "至", "、", "，", "和", "及")):
            continue
        if not tail or not tail[0].isspace():
            continue
        markers.append(
            (
                match.start(),
                match.end(),
                "ARTICLE",
                match[0],
                numeral(match[1]),
                numeral(match[2]) or 0 if match[2] else 0,
            )
        )
    markers.sort()
    stack: list[StructureNode] = []

    def too_many_nodes() -> bool:
        if len(result.nodes) < 20000:
            return False
        if not any(issue.code == "structure_limit" for issue in result.extraction_issues):
            result.extraction_issues.append(
                ParseIssue(
                    id="structure_limit",
                    code="structure_limit",
                    severity="ERROR",
                    message="结构节点超过处理上限，正文已完整保留，请拆分文件后导入",
                )
            )
        return True

    for start, label_end, kind, label, number, suffix in markers:
        if too_many_nodes():
            break
        level = LEVEL[kind]
        while stack and LEVEL[stack[-1].kind] >= level:
            stack.pop().end = start
        node = StructureNode(
            id=f"n{len(result.nodes) + 1}",
            kind=kind,
            label=label,
            number=number,
            suffix=suffix,
            parent_id=stack[-1].id if stack else None,
            start=start,
            end=len(text),
        )
        result.nodes.append(node)
        stack.append(node)
        if kind == "ARTICLE":
            # 正文起点由下方按 label_end 计算；原始标签和换行不被改写。
            article_starts.add(label_end)
    articles = [node for node in result.nodes if node.kind == "ARTICLE"]
    for article in articles:
        body_start = article.start + len(article.label)
        body = text[body_start : article.end]
        # 以真实段落行建立款；PDF 断行不声称语义确定，另有布局校验提示。
        paragraph: StructureNode | None = None
        item: StructureNode | None = None
        paragraph_number = 0
        offset = body_start
        for line in body.splitlines(keepends=True):
            if too_many_nodes():
                break
            if not line.strip():
                offset += len(line)
                continue
            leading = len(line) - len(line.lstrip())
            item_match = re.match(rf"[（(]({NUM})[）)]", line.lstrip())
            sub_match = re.match(rf"({NUM})[.．、]", line.lstrip())
            kind = "ITEM" if item_match else "SUBITEM" if sub_match and item else "PARAGRAPH"
            parent = (
                item.id
                if kind == "SUBITEM" and item
                else paragraph.id
                if kind == "ITEM" and paragraph
                else article.id
            )
            label_match = item_match or sub_match
            if kind == "PARAGRAPH":
                paragraph_number += 1
            node = StructureNode(
                id=f"n{len(result.nodes) + 1}",
                kind=kind,
                label=label_match[0] if label_match else "",
                number=paragraph_number
                if kind == "PARAGRAPH"
                else numeral(label_match[1])
                if label_match
                else None,
                parent_id=parent,
                start=offset + leading,
                end=offset + len(line),
            )
            result.nodes.append(node)
            if kind == "PARAGRAPH":
                paragraph, item = node, None
            elif kind == "ITEM":
                item = node
            offset += len(line)
        # 扩大父款/项范围覆盖其子项，保证父子区间可验证。
    by_id = {node.id: node for node in result.nodes}
    for node in reversed(result.nodes):
        if node.parent_id and node.parent_id in by_id:
            by_id[node.parent_id].end = max(by_id[node.parent_id].end, node.end)
    result.nodes.sort(key=lambda node: (node.start, -node.end))
    result.issues = validate_structure(result, mode)
    return result
