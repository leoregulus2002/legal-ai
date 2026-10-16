from uuid import UUID

from sqlalchemy import Integer, Select, and_, case, cast, column, func, or_, select, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.modules.knowledge.models import KnowledgeBase, KnowledgeDocument, ParseRevision
from app.modules.knowledge.regulation_schemas import RegulationQuery

RegulationRow = tuple[KnowledgeDocument, str, dict[str, object]]


class RegulationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def published() -> Select[tuple[KnowledgeDocument, str, dict[str, object]]]:
        return (
            select(KnowledgeDocument, KnowledgeBase.name, ParseRevision.result)
            .join(KnowledgeBase, KnowledgeBase.id == KnowledgeDocument.knowledge_base_id)
            .join(
                ParseRevision,
                and_(
                    ParseRevision.document_id == KnowledgeDocument.id,
                    ParseRevision.revision == KnowledgeDocument.revision,
                ),
            )
            .where(
                KnowledgeBase.deleted_at.is_(None),
                KnowledgeDocument.deleted_at.is_(None),
                KnowledgeDocument.mode == "LEGAL",
                KnowledgeDocument.status == "PUBLISHED",
                KnowledgeDocument.published_at.is_not(None),
            )
        )

    async def options(self) -> tuple[list[tuple[UUID, str, str, str]], int]:
        source = self.published().subquery()
        rows = await self.session.execute(
            select(
                source.c.knowledge_base_id,
                source.c.name,
                source.c.legal_metadata["authority"].as_string(),
                source.c.legal_metadata["region"].as_string(),
            ).distinct()
        )
        total = await self.session.scalar(select(func.count()).select_from(source))
        return [
            (base, name, authority or "", region or "") for base, name, authority, region in rows
        ], total or 0

    async def detail(self, document_id: UUID) -> RegulationRow | None:
        row = (
            await self.session.execute(self.published().where(KnowledgeDocument.id == document_id))
        ).first()
        return (row[0], row[1], row[2]) if row else None

    async def search(
        self,
        query: RegulationQuery,
        article: tuple[int, int] | None,
    ) -> tuple[list[RegulationRow], int]:
        metadata = KnowledgeDocument.legal_metadata
        title = metadata["title"].as_string()
        number = metadata["document_number"].as_string()
        text = ParseRevision.result["text"].as_string()
        statement = self.published()
        criteria: list[ColumnElement[bool]] = []
        if query.knowledge_base_id:
            criteria.append(KnowledgeDocument.knowledge_base_id == query.knowledge_base_id)
        if query.category:
            criteria.append(
                func.coalesce(metadata["category"].as_string(), "UNCLASSIFIED") == query.category
            )
        for field, value in (("authority", query.authority), ("region", query.region)):
            if value:
                criteria.append(metadata[field].as_string() == value)
        if query.legal_status:
            criteria.append(KnowledgeDocument.legal_status == query.legal_status)
        for field, lower, upper in (
            ("promulgated_on", query.promulgated_from, query.promulgated_to),
            ("effective_on", query.effective_from, query.effective_to),
        ):
            value = metadata[field].as_string()
            if lower:
                criteria.append(value >= lower.isoformat())
            if upper:
                criteria.append(value <= upper.isoformat())

        if article or (query.q and query.match == "exact" and query.scope in {"all", "body"}):
            nodes = (
                func.jsonb_array_elements(cast(ParseRevision.result["nodes"], JSONB))
                .table_valued(column("value", JSONB))
                .lateral("regulation_nodes")
            )
            node = nodes.c.value
            conditions = [node["kind"].as_string() == "ARTICLE"]
            if article:
                conditions.extend(
                    [
                        cast(node["number"].as_string(), Integer) == article[0],
                        func.coalesce(cast(node["suffix"].as_string(), Integer), 0) == article[1],
                    ]
                )
            else:
                conditions.append(
                    func.btrim(
                        func.substring(
                            text,
                            cast(node["start"].as_string(), Integer) + 1,
                            cast(node["end"].as_string(), Integer)
                            - cast(node["start"].as_string(), Integer),
                        ),
                        " \t\n\r\u3000",
                    )
                    == query.q
                )
            article_match = (
                select(1).select_from(nodes).where(*conditions).correlate(ParseRevision).exists()
            )
        else:
            article_match = true()

        if article:
            criteria.extend([title.icontains(query.q, autoescape=True), article_match])
        elif query.q:
            exact = query.match == "exact"
            matches = {
                "title": title == query.q if exact else title.icontains(query.q, autoescape=True),
                "number": number == query.q
                if exact
                else number.icontains(query.q, autoescape=True),
                "body": article_match if exact else text.icontains(query.q, autoescape=True),
            }
            criteria.append(
                or_(*matches.values()) if query.scope == "all" else matches[query.scope]
            )
        statement = statement.where(*criteria)
        total = await self.session.scalar(select(func.count()).select_from(statement.subquery()))
        date_field = "effective_on" if query.sort.startswith("effective") else "promulgated_on"
        date_value = func.nullif(metadata[date_field].as_string(), "")
        date_order = (
            date_value.asc().nulls_last()
            if query.sort.endswith("asc")
            else date_value.desc().nulls_last()
        )
        order = []
        if query.sort == "relevance" and query.q:
            order.append(
                case(
                    (or_(title == query.q, number == query.q), 0),
                    (title.icontains(query.q, autoescape=True), 1),
                    else_=2,
                )
            )
        rows = await self.session.execute(
            statement.order_by(*order, date_order, KnowledgeDocument.id)
            .offset((query.page - 1) * query.page_size)
            .limit(query.page_size)
        )
        return [(row[0], row[1], row[2]) for row in rows], total or 0
