import re

from app.modules.knowledge.schemas import ParseIssue, ParseResult, StructureNode

ALLOWED_PARENTS: dict[str, set[str]] = {
    "PART": {"ANNEX"},
    "CHAPTER": {"PART", "ANNEX"},
    "SECTION": {"PART", "CHAPTER", "ANNEX"},
    "ARTICLE": {"PART", "CHAPTER", "SECTION", "SUPPLEMENT", "ANNEX"},
    "PARAGRAPH": {"ARTICLE"},
    "ITEM": {"ARTICLE", "PARAGRAPH"},
    "SUBITEM": {"ITEM"},
    "SUPPLEMENT": {"PART", "ANNEX"},
    "ANNEX": set(),
}


def validate_structure(result: ParseResult, mode: str) -> list[ParseIssue]:
    issues = list(result.extraction_issues)

    def add(
        code: str, message: str, node: StructureNode | None = None, *, error: bool = False
    ) -> None:
        issues.append(
            ParseIssue(
                id=f"{code}:{node.id if node else 'document'}",
                code=code,
                severity="ERROR" if error else "WARNING",
                message=message,
                node_id=node.id if node else None,
                start=node.start if node else None,
                end=node.end if node else None,
            )
        )

    if not result.text.strip() and not any(i.code == "empty_text" for i in issues):
        add("empty_text", "正文为空", error=True)
    if mode != "LEGAL":
        return issues
    for field, label in (
        ("title", "法律名称"),
        ("authority", "公布机关"),
        ("document_number", "文号"),
        ("promulgated_on", "公布日期"),
        ("effective_on", "施行日期"),
    ):
        if not getattr(result.metadata, field):
            add(f"metadata_{field}", f"缺少{label}，请补充或核对确认原件未载明")
    nodes = {node.id: node for node in result.nodes}
    if len(nodes) != len(result.nodes):
        add("duplicate_node_id", "结构节点标识重复", error=True)
    seen: dict[tuple[str, int, int], StructureNode] = {}
    previous: dict[str, tuple[int, int]] = {}
    articles = []
    for node in result.nodes:
        if node.start >= node.end or node.end > len(result.text):
            add("invalid_range", "节点边界超出正文或为空", node, error=True)
            continue
        if node.label and not result.text[node.start : node.end].startswith(node.label):
            add("label_mismatch", "节点标签与该位置原文不一致", node, error=True)
        if node.parent_id:
            parent = nodes.get(node.parent_id)
            if (
                not parent
                or parent.kind not in ALLOWED_PARENTS[node.kind]
                or parent.start > node.start
                or parent.end < node.end
            ):
                add("invalid_hierarchy", "章节归属或父子边界异常", node, error=True)
        elif node.kind in {"PARAGRAPH", "ITEM", "SUBITEM"}:
            add("missing_parent", "款、项、目缺少所属条文", node, error=True)
        elif node.kind == "SECTION":
            add("section_without_chapter", "节缺少所属章节，请核对层级", node)
        if node.kind != "ARTICLE":
            continue
        articles.append(node)
        scope = "main"
        ancestor = nodes.get(node.parent_id or "")
        visited: set[str] = set()
        while ancestor and ancestor.id not in visited:
            visited.add(ancestor.id)
            if ancestor.kind == "ANNEX":
                scope = ancestor.id
            ancestor = nodes.get(ancestor.parent_id or "")
        if node.number is None:
            add("invalid_number", "条文编号无法识别", node, error=True)
            continue
        key = (scope, node.number, node.suffix)
        if key in seen:
            add("duplicate_article", "条文编号重复，可能包含目录或多个法律版本", node, error=True)
        seen[key] = node
        last = previous.get(scope)
        current = (node.number, node.suffix)
        if last:
            if current < last:
                add("number_order", "条文编号倒序，请核对原件", node)
            elif node.number > last[0] + 1 or (
                node.number == last[0] and node.suffix > last[1] + 1
            ):
                add("possible_gap", "条文编号不连续，可能为节选、删条或遗漏，请检查", node)
        elif node.number != 1 or node.suffix:
            add("first_article", "首个条文并非第一条，请确认是否为节选", node)
        previous[scope] = current
        body = result.text[node.start + len(node.label) : node.end]
        if not re.sub(r"[\s#*。；:：，、.·…\d]", "", body):
            add("empty_article", "条文内容缺失或疑似目录条目", node, error=True)
    articles.sort(key=lambda node: node.start)
    for left, right in zip(articles, articles[1:], strict=False):
        if right.start < left.end:
            add("overlapping_articles", "条文区间重叠", right, error=True)
    if not articles:
        add("no_articles", "没有可靠识别出法律条文，请人工标注边界或改用普通文档导入", error=True)
    if re.search(r"(?m)^\s*目\s*录\s*$", result.text):
        add("contains_toc", "文档含目录，请检查目录条目是否误识别为正文")
    return issues
