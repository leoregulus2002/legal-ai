from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import AppError
from app.modules.consultation.models import Attachment, Conversation, Turn


class ConsultationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def conversation(self, conversation_id: UUID, *, lock: bool = False) -> Conversation:
        row = await self.session.get(Conversation, conversation_id, with_for_update=lock)
        if not row:
            raise AppError("conversation_not_found", "会话不存在", 404)
        return row

    async def conversations(self, offset: int, limit: int) -> list[Conversation]:
        return list(
            await self.session.scalars(
                select(Conversation)
                .order_by(Conversation.updated_at.desc())
                .offset(offset)
                .limit(limit)
            )
        )

    async def create(self, title: str) -> Conversation:
        row = Conversation(title=title)
        self.session.add(row)
        await self.session.flush()
        return row

    async def turns(self, conversation_id: UUID, after: int = 0, limit: int = 100) -> list[Turn]:
        return list(
            await self.session.scalars(
                select(Turn)
                .where(Turn.conversation_id == conversation_id, Turn.sequence > after)
                .order_by(Turn.sequence)
                .limit(limit)
            )
        )

    async def previous(self, conversation_id: UUID, request_id: UUID) -> Turn | None:
        return await self.session.scalar(
            select(Turn).where(
                Turn.conversation_id == conversation_id, Turn.request_id == request_id
            )
        )

    async def attachments(
        self, conversation_id: UUID, ids: list[UUID] | None = None
    ) -> list[Attachment]:
        statement = select(Attachment).where(Attachment.conversation_id == conversation_id)
        if ids is not None:
            statement = statement.where(Attachment.id.in_(ids))
        return list(await self.session.scalars(statement))

    async def attachment(self, attachment_id: UUID) -> Attachment:
        row = await self.session.get(Attachment, attachment_id)
        if not row:
            raise AppError("attachment_not_found", "附件不存在", 404)
        return row

    async def save_attachment(self, row: Attachment) -> Attachment:
        self.session.add(row)
        await self.session.flush()
        return row

    async def delete_attachment(self, row: Attachment) -> None:
        await self.session.delete(row)

    async def delete_conversation(self, row: Conversation) -> None:
        await self.session.delete(row)

    async def stale_attachments(self) -> list[Attachment]:
        now = datetime.now(UTC)
        return list(
            await self.session.scalars(
                select(Attachment)
                .join(Conversation)
                .where(
                    Attachment.bound.is_(False),
                    Attachment.created_at < now - timedelta(hours=24),
                    or_(Conversation.active_token.is_(None), Conversation.active_until < now),
                )
                .limit(100)
                .with_for_update(skip_locked=True)
            )
        )

    async def claim(self, conversation_id: UUID, token: UUID) -> Conversation:
        row = await self.conversation(conversation_id, lock=True)
        now = datetime.now(UTC)
        if row.active_token and row.active_until and row.active_until > now:
            raise AppError("conversation_busy", "当前会话正在生成，请稍后再发送", 409)
        row.active_token, row.active_until = token, now + timedelta(seconds=45)
        return row

    async def renew(self, conversation_id: UUID, token: UUID) -> bool:
        result = await self.session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id, Conversation.active_token == token)
            .values(active_until=datetime.now(UTC) + timedelta(seconds=45))
        )
        return bool(result.rowcount)

    async def release(self, conversation_id: UUID, token: UUID) -> None:
        await self.session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id, Conversation.active_token == token)
            .values(active_token=None, active_until=None)
        )

    async def save_turn(self, conversation_id: UUID, token: UUID, row: Turn) -> Turn:
        conversation = await self.conversation(conversation_id, lock=True)
        if conversation.active_token != token:
            raise AppError("generation_expired", "本次生成已失效，请重新发送", 409)
        conversation.history_version += 1
        conversation.updated_at = datetime.now(UTC)
        if conversation.history_version == 1:
            conversation.title = row.user_text[:40] or "附件咨询"
        row.sequence = conversation.history_version
        self.session.add(row)
        if row.attachment_ids:
            await self.session.execute(
                update(Attachment)
                .where(
                    Attachment.conversation_id == conversation_id,
                    Attachment.id.in_([UUID(value) for value in row.attachment_ids]),
                )
                .values(bound=True)
            )
        await self.session.flush()
        return row
