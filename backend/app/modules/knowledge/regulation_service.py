import re
from uuid import UUID

from app.common.exceptions import AppError
from app.modules.knowledge.parser import NUM, numeral
from app.modules.knowledge.regulation_repository import RegulationRepository, RegulationRow
from app.modules.knowledge.regulation_schemas import (
    RegulationBaseOption,
    RegulationDetail,
    RegulationOptions,
    RegulationPage,
    RegulationQuery,
    RegulationSummary,
)
from app.modules.knowledge.schemas import LegalMetadata, ParseResult, StructureNode

ARTICLE_QUERY = re.compile(rf"^(.*?)第\s*({NUM})\s*条(?:\s*之\s*({NUM}))?\s*$")


def article_number(value: str) -> int:
    if not value.isdecimal() and any(char.isdecimal() for char in value):
        raise AppError("invalid_article_number", "条文编号请使用中文数字或阿拉伯数字，不能混写")
    try:
        number = numeral(value)
    except (KeyError, ValueError):
        number = None
    if number is None:
        raise AppError("invalid_article_number", "请检查条文编号")
    return number


def article_text(result: ParseResult, node: StructureNode) -> str:
    return result.text[node.start : node.end].strip()


def summary(row: RegulationRow) -> RegulationSummary:
    document, base_name, _ = row
    return RegulationSummary(
        document_id=document.id,
        knowledge_base_id=document.knowledge_base_id,
        knowledge_base_name=base_name,
        revision=document.revision,
        metadata=LegalMetadata.model_validate(document.legal_metadata),
        legal_status=document.legal_status,
        source_kind=document.source_kind,
        version_confirmed=document.version_confirmed,
        source_url=document.source_url,
        updated_at=document.updated_at,
    )


class RegulationService:
    def __init__(self, repository: RegulationRepository) -> None:
        self.repo = repository

    async def options(self) -> RegulationOptions:
        rows, count = await self.repo.options()
        bases = {base: name for base, name, _, _ in rows}
        return RegulationOptions(
            knowledge_bases=[
                RegulationBaseOption(id=key, name=name)
                for key, name in sorted(bases.items(), key=lambda item: (item[1], str(item[0])))
            ],
            authorities=sorted({authority for _, _, authority, _ in rows if authority}),
            regions=sorted({region for _, _, _, region in rows if region}),
            document_count=count,
        )

    async def search(self, query: RegulationQuery) -> RegulationPage:
        query = query.model_copy(update={"q": query.q.strip()})
        for lower, upper in (
            (query.promulgated_from, query.promulgated_to),
            (query.effective_from, query.effective_to),
        ):
            if lower and upper and lower > upper:
                raise AppError("invalid_date_range", "开始日期不能晚于结束日期")
        article = None
        match = ARTICLE_QUERY.fullmatch(query.q) if query.scope in {"all", "body"} else None
        if match:
            name = match[1].strip().strip("《》").strip()
            if not name:
                raise AppError("regulation_name_required", "请同时输入法规名称和条号")
            number = article_number(match[2])
            suffix = article_number(match[3]) if match[3] else 0
            article = (number, suffix)
            query = query.model_copy(update={"q": name})
        rows, total = await self.repo.search(query, article)
        items = []
        for row in rows:
            item = summary(row)
            result = ParseResult.model_validate(row[2])
            articles = [node for node in result.nodes if node.kind == "ARTICLE"]
            if article:
                matching = [node for node in articles if (node.number, node.suffix) == article]
            elif query.q:
                matching = [
                    node
                    for node in articles
                    if (
                        article_text(result, node) == query.q
                        if query.match == "exact"
                        else query.q.casefold() in article_text(result, node).casefold()
                    )
                ]
            else:
                matching = []
            item.matched_articles = len(matching)
            node = matching[0] if matching else None
            content = article_text(result, node) if node else result.text
            position = content.casefold().find(query.q.casefold()) if query.q and not article else 0
            start = max(0, position - 60)
            item.excerpt = (
                ("…" if start else "")
                + content[start : start + 260]
                + ("…" if len(content) > start + 260 else "")
            )
            item.node_id = node.id if node else None
            item.article_label = node.label if node else ""
            items.append(item)
        return RegulationPage(
            items=items, total=total, page=query.page, page_size=query.page_size, highlight=query.q
        )

    async def detail(self, document_id: UUID) -> RegulationDetail:
        row = await self.repo.detail(document_id)
        if row is None:
            raise AppError("regulation_unavailable", "该法规资料已撤回、删除或尚未发布", 404)
        result = ParseResult.model_validate(row[2])
        return RegulationDetail(regulation=summary(row), text=result.text, nodes=result.nodes)
