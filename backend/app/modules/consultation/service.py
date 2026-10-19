import asyncio
import contextlib
import json
import logging
import math
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4

import anyio
from fastapi import UploadFile
from pydantic import ValidationError
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.prompts.context import SUMMARY_INSTRUCTION, consultation_system
from app.ai.providers.client import Provider, estimate_text_tokens
from app.ai.retrieval.client import InternalSource, Source
from app.common.exceptions import AppError
from app.core.config import Settings
from app.core.secrets import decrypt
from app.modules.consultation.attachments import AttachmentStorage
from app.modules.consultation.memory import MemoryStore, policy_version
from app.modules.consultation.models import Conversation, Turn
from app.modules.consultation.repository import ConsultationRepository
from app.modules.consultation.schemas import (
    AttachmentView,
    ContextUsageInput,
    ContextUsageView,
    ConversationView,
    GenerateInput,
    Memory,
    MemoryTurn,
    SummaryResult,
    TurnView,
)
from app.modules.knowledge.repository import KnowledgeRepository
from app.modules.knowledge.service import KnowledgeService
from app.modules.system_config.repository import ConfigRepository
from app.modules.system_config.schemas import ModelView, Policy, PromptView
from app.modules.system_config.service import ConfigService

logger = logging.getLogger(__name__)


@dataclass
class Generation:
    conversation_id: UUID
    token: UUID
    data: GenerateInput
    history_version: int
    policy: Policy
    provider: Provider
    model: ModelView
    prompt: PromptView | None
    model_key_encrypted: str | None
    previous: TurnView | None = None


def event(kind: str, payload: object) -> str:
    return f"event: {kind}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


class ConsultationService:
    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], settings: Settings, memory: MemoryStore
    ) -> None:
        self.sessions, self.settings, self.memory = sessions, settings, memory
        self.files = AttachmentStorage(settings.attachment_directory)

    @staticmethod
    def busy(conversation: Conversation) -> bool:
        return bool(
            conversation.active_token
            and conversation.active_until
            and conversation.active_until > datetime.now(UTC)
        )

    async def cleanup_attachments(self) -> None:
        async with self.sessions.begin() as session:
            repo = ConsultationRepository(session)
            rows = await repo.stale_attachments()
            keys = [row.storage_key for row in rows]
            for row in rows:
                await repo.delete_attachment(row)
        for key in keys:
            await self.files.remove(key)

    async def maintain_attachments(self) -> None:
        while True:
            await asyncio.sleep(3600)
            try:
                await self.cleanup_attachments()
            except Exception as exc:
                logger.warning("未发送附件清理延迟 type=%s", type(exc).__name__)

    async def options(self) -> dict[str, object]:
        async with self.sessions() as session:
            repo = ConfigRepository(session)
            policy = Policy.model_validate((await repo.policy()).settings)
            models = [
                ConfigService.model_view(row).model_dump(mode="json")
                for row in await repo.models()
                if row.id in policy.allowed_model_ids and row.enabled and row.model_type == "chat"
            ]
            prompts = [
                PromptView.model_validate(row).model_dump(mode="json")
                for row in await repo.prompts()
                if row.enabled
            ]
            return {"models": models, "prompts": prompts, "policy": policy.model_dump(mode="json")}

    async def context_usage(self, data: ContextUsageInput) -> ContextUsageView:
        async with self.sessions() as session:
            config = ConfigRepository(session)
            policy = Policy.model_validate((await config.policy()).settings)
            model = await config.model(data.model_id)
            if (
                not model
                or model.id not in policy.allowed_model_ids
                or not model.enabled
                or model.model_type != "chat"
            ):
                raise AppError("invalid_model", "请选择可用的法律咨询模型")
            prompt = (
                await config.prompt(policy.default_prompt_id) if policy.default_prompt_id else None
            )
            prompt_text = prompt.content if prompt and prompt.enabled else ""
            result = ContextUsageView(
                used_tokens=None,
                context_tokens=model.context_tokens,
                max_output_tokens=model.max_output_tokens,
            )
            history_version = 0
            if data.conversation_id:
                repo = ConsultationRepository(session)
                history_version = (await repo.conversation(data.conversation_id)).history_version

        memory = Memory(policy_version=policy_version(policy))
        if history_version and data.conversation_id:
            cached = await self.memory.read(data.conversation_id, policy.memory_ttl_days * 86400)
            if (
                not cached
                or cached.history_version != history_version
                or cached.policy_version != policy_version(policy)
            ):
                # 统计不触发模型调用；等待正常对话流程恢复摘要后再显示用量。
                return result
            memory = cached

        system = consultation_system(
            prompt_text,
            memory.summary,
            memory.keywords,
            [],
            data.knowledge_enabled and bool(data.text.strip()),
        )
        messages: list[dict[str, Any]] = []
        text_tokens = estimate_text_tokens(system)
        attachment_ids: list[UUID] = []
        turns = [
            *memory.recent,
            MemoryTurn(
                sequence=history_version + 1,
                user_text=data.text.strip(),
                answer="",
                attachment_ids=data.attachment_ids,
            ),
        ]
        for turn in turns:
            text = turn.user_text or "请查看附件"
            messages.append(
                {
                    "role": "user",
                    "content": [{"type": "text", "text": text}] if turn.attachment_ids else text,
                }
            )
            text_tokens += estimate_text_tokens(text)
            if turn.answer:
                messages.append({"role": "assistant", "content": turn.answer})
                text_tokens += estimate_text_tokens(turn.answer)
            attachment_ids.extend(turn.attachment_ids)

        attachment_tokens = 0
        if attachment_ids:
            if not data.conversation_id:
                raise AppError("invalid_attachment", "请先上传附件")
            async with self.sessions() as session:
                files = await ConsultationRepository(session).attachments(
                    data.conversation_id, list(set(attachment_ids))
                )
            by_id = {row.id: row for row in files}
            if len(by_id) != len(set(attachment_ids)):
                raise AppError("invalid_attachment", "会话附件缺失，请重新上传或新建会话")
            for attachment_id in attachment_ids:
                file = by_id[attachment_id]
                # 与 Provider 的附件预算一致，无需读取文件或生成 base64。
                attachment_tokens += (
                    math.ceil(
                        (len("data:application/pdf;base64,") + 4 * math.ceil(file.size / 3)) / 6
                    )
                    if file.mime_type == "application/pdf"
                    else 4096
                )

        # 同时覆盖业务层和 Provider 的两种现有预算检查；检索资料尚未加入。
        serialized_tokens = estimate_text_tokens(system + json.dumps(messages, ensure_ascii=False))
        provider_tokens = text_tokens + attachment_tokens
        result.used_tokens = max(serialized_tokens, provider_tokens)
        return result

    async def conversations(self, offset: int, limit: int) -> list[ConversationView]:
        async with self.sessions() as session:
            return [
                ConversationView.model_validate(row)
                for row in await ConsultationRepository(session).conversations(offset, limit)
            ]

    async def create(self, title: str) -> ConversationView:
        async with self.sessions.begin() as session:
            return ConversationView.model_validate(
                await ConsultationRepository(session).create(title)
            )

    async def turns(self, conversation_id: UUID, after: int, limit: int) -> list[TurnView]:
        async with self.sessions() as session:
            repo = ConsultationRepository(session)
            await repo.conversation(conversation_id)
            return [
                TurnView.model_validate(row)
                for row in await repo.turns(conversation_id, after, limit)
            ]

    async def delete(self, conversation_id: UUID) -> None:
        async with self.sessions.begin() as session:
            repo = ConsultationRepository(session)
            row = await repo.claim(conversation_id, uuid4())
            attachments = await repo.attachments(conversation_id)
            keys = [file.storage_key for file in attachments]
            await repo.delete_conversation(row)
        try:
            await self.memory.delete(conversation_id)
        except (RedisError, OSError):
            logger.warning("会话记忆清理延迟 conversation_id=%s", conversation_id)
        for key in keys:
            await self.files.remove(key)

    async def upload(self, conversation_id: UUID, upload: UploadFile) -> AttachmentView:
        key: str | None = None
        try:
            await self.cleanup_attachments()
            async with self.sessions.begin() as session:
                repo = ConsultationRepository(session)
                conversation = await repo.conversation(conversation_id, lock=True)
                if self.busy(conversation):
                    raise AppError("conversation_busy", "请等待当前回答完成后上传附件", 409)
                policy = Policy.model_validate((await ConfigRepository(session).policy()).settings)
                # 未发送文件也计入上传配额，避免无限制堆积。
                unbound = [
                    file for file in await repo.attachments(conversation_id) if not file.bound
                ]
                if len(unbound) >= policy.max_attachments:
                    raise AppError("attachment_limit", "请先发送或移除待发送的附件")
                row = await self.files.upload(upload, conversation_id, policy)
                key = row.storage_key
                await repo.save_attachment(row)
                result = AttachmentView.model_validate(row)
            return result
        except BaseException:
            if key:
                with contextlib.suppress(OSError):
                    await self.files.remove(key)
            raise
        finally:
            await upload.close()

    async def attachments(self, conversation_id: UUID) -> list[AttachmentView]:
        async with self.sessions() as session:
            repo = ConsultationRepository(session)
            await repo.conversation(conversation_id)
            return [
                AttachmentView.model_validate(row)
                for row in await repo.attachments(conversation_id)
            ]

    async def attachment(self, attachment_id: UUID) -> tuple[str, str, str]:
        async with self.sessions() as session:
            repo = ConsultationRepository(session)
            row = await repo.attachment(attachment_id)
            await repo.conversation(row.conversation_id)
            return str(self.files.path(row.storage_key)), row.mime_type, row.name

    async def remove_attachment(self, attachment_id: UUID) -> None:
        async with self.sessions.begin() as session:
            repo = ConsultationRepository(session)
            row = await repo.attachment(attachment_id)
            conversation = await repo.conversation(row.conversation_id, lock=True)
            if row.bound or self.busy(conversation):
                raise AppError("attachment_in_use", "已发送或正在使用的附件无法移除", 409)
            key = row.storage_key
            await repo.delete_attachment(row)
        await self.files.remove(key)

    async def prepare(self, conversation_id: UUID, data: GenerateInput) -> Generation:
        token = uuid4()
        async with self.sessions.begin() as session:
            config = ConfigRepository(session)
            policy_row = await config.policy(lock=True)
            policy = Policy.model_validate(policy_row.settings)
            model = await config.model(data.model_id)
            prompt = await config.prompt(data.prompt_id) if data.prompt_id else None
            if (
                not model
                or model.id not in policy.allowed_model_ids
                or not model.enabled
                or model.model_type != "chat"
            ):
                raise AppError("invalid_model", "请选择可用的法律咨询模型")
            if data.prompt_id and (not prompt or not prompt.enabled):
                raise AppError("invalid_prompt", "请选择已启用的系统提示词")
            repo = ConsultationRepository(session)
            conversation = await repo.conversation(conversation_id, lock=True)
            previous = await repo.previous(conversation_id, data.request_id)
            if previous and (
                previous.user_text != data.text
                or previous.attachment_ids != [str(value) for value in data.attachment_ids]
                or previous.config_snapshot.get("knowledge_enabled") != data.knowledge_enabled
                or previous.config_snapshot.get("model", {}).get("id") != str(data.model_id)
                or (previous.config_snapshot.get("prompt") or {}).get("id")
                != (str(data.prompt_id) if data.prompt_id else None)
            ):
                raise AppError("request_id_conflict", "此发送标识已被使用，请重新发送", 409)
            if previous is None:
                if data.knowledge_enabled:
                    if not policy.knowledge_base_ids:
                        raise AppError(
                            "knowledge_not_configured", "请先在法律咨询模型中添加内部知识库"
                        )
                    existing = await KnowledgeRepository(session).existing_base_ids(
                        policy.knowledge_base_ids
                    )
                    if existing != set(policy.knowledge_base_ids):
                        raise AppError("invalid_knowledge_base", "咨询知识库已不存在，请重新配置")
                await repo.claim(conversation_id, token)
            return Generation(
                conversation_id=conversation_id,
                token=token,
                data=data,
                history_version=conversation.history_version,
                policy=policy,
                provider=Provider(
                    protocol=model.protocol,
                    base_url=model.base_url,
                    model_name=model.model_name,
                    api_key="",
                    context_tokens=model.context_tokens,
                    max_output_tokens=model.max_output_tokens,
                    temperature=model.temperature,
                    timeout=policy.request_timeout,
                    token_parameter=model.token_parameter,
                    supports_json_mode=model.supports_json_mode,
                ),
                model=ConfigService.model_view(model),
                prompt=PromptView.model_validate(prompt) if prompt else None,
                model_key_encrypted=model.api_key_encrypted,
                previous=TurnView.model_validate(previous) if previous else None,
            )

    async def _messages(
        self, generation: Generation, turns: list[MemoryTurn]
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        for turn in turns:
            parts: list[dict[str, Any]] = [{"type": "text", "text": turn.user_text or "请查看附件"}]
            if turn.attachment_ids:
                async with self.sessions() as session:
                    attachments = await ConsultationRepository(session).attachments(
                        generation.conversation_id, turn.attachment_ids
                    )
                if len(attachments) != len(turn.attachment_ids):
                    raise AppError("invalid_attachment", "会话附件缺失，请重新上传或新建会话")
                if (
                    len(attachments) > generation.policy.max_attachments
                    or sum(row.size for row in attachments)
                    > generation.policy.max_total_mb * 1024 * 1024
                ):
                    raise AppError("attachment_limit", "附件数量或总大小超过当前限制")
                for row in attachments:
                    if row.mime_type == "application/pdf" and not generation.model.supports_pdf:
                        raise AppError(
                            "pdf_unsupported",
                            "所选模型不支持会话中的 PDF，请选择兼容模型或新建会话",
                        )
                    if row.mime_type.startswith("image/") and not generation.model.supports_images:
                        raise AppError(
                            "image_unsupported",
                            "所选模型不支持会话中的图片，请选择兼容模型或新建会话",
                        )
                    if row.size > generation.policy.max_file_mb * 1024 * 1024:
                        raise AppError("attachment_limit", "会话附件超过当前单文件限制")
                    parts.append(await self.files.content(row))
            messages.append(
                {"role": "user", "content": parts if len(parts) > 1 else parts[0]["text"]}
            )
            if turn.answer:
                messages.append({"role": "assistant", "content": turn.answer})
        return messages

    async def _update_memory(
        self, generation: Generation, memory: Memory, queue: asyncio.Queue[str]
    ) -> Memory:
        policy = generation.policy
        # 按 N 轮整批压缩，在 N、2N、3N……轮完成后的下一次回答前执行。
        count = len(memory.recent) // policy.recent_turns * policy.recent_turns
        if not count:
            return memory
        await queue.put(event("status", {"phase": "compressing_context"}))
        older = memory.recent[:count]
        recent = memory.recent[count:]
        # 摘要仅合并完整批次；未满一批的原文继续直接参与对话。
        instruction = (
            SUMMARY_INSTRUCTION
            + f"\n摘要最多 {policy.summary_chars} 字，关键词最多 {policy.keyword_count} 个。"
        )
        instruction += "summary 只能合并此前摘要和待压缩轮次；近期背景只用于关键词，不写入摘要。"
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": instruction},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "previous_summary": memory.summary,
                        "previous_keywords": memory.keywords,
                        "recent_background": [
                            {"question": row.user_text, "answer": row.answer} for row in recent
                        ],
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        messages.extend(await self._messages(generation, older))
        try:
            result = SummaryResult.model_validate(await generation.provider.json_result(messages))
            if (
                len(result.summary) > policy.summary_chars
                or len(result.keywords) > policy.keyword_count
                or any(not word.strip() or len(word) > 100 for word in result.keywords)
            ):
                raise ValueError
            if not result.summary.strip():
                raise ValueError
        except (ValidationError, ValueError) as exc:
            raise AppError(
                "invalid_memory", "记忆摘要生成失败，请调整模型配置或重新发送", 502
            ) from exc
        updated = Memory(
            history_version=memory.history_version,
            policy_version=policy_version(policy),
            covered_through=older[-1].sequence,
            summary=result.summary,
            keywords=result.keywords,
            recent=recent,
        )
        await queue.put(event("status", {"phase": "generating"}))
        return updated

    async def _load_memory(self, generation: Generation, queue: asyncio.Queue[str]) -> Memory:
        ttl = generation.policy.memory_ttl_days * 86400
        memory = await self.memory.read(generation.conversation_id, ttl)
        if (
            memory
            and memory.history_version == generation.history_version
            and memory.policy_version == policy_version(generation.policy)
        ):
            # 仅在新增完整对话累积到 N 轮时，才在本轮回答前压缩上下文。
            # 新快照随本轮成功回答发布，失败时保留原缓存以便重试。
            return await self._update_memory(generation, memory, queue)
        memory = Memory(policy_version=policy_version(generation.policy))
        after = 0
        while True:
            async with self.sessions() as session:
                rows = await ConsultationRepository(session).turns(
                    generation.conversation_id, after, 20
                )
                batch = [
                    MemoryTurn(
                        sequence=row.sequence,
                        user_text=row.user_text,
                        answer=row.answer,
                        attachment_ids=row.attachment_ids,
                    )
                    for row in rows
                ]
            if not batch:
                break
            for row in batch:
                memory.recent.append(row)
                memory.history_version = row.sequence
                # 小批次控制恢复时单次模型上下文，长历史不会一次全部送入模型。
                if len(memory.recent) >= generation.policy.recent_turns:
                    memory = await self._update_memory(generation, memory, queue)
            after = batch[-1].sequence
        if memory.recent:
            memory = await self._update_memory(generation, memory, queue)
        await self.memory.write(generation.conversation_id, memory, ttl)
        return memory

    async def _generate(self, generation: Generation, queue: asyncio.Queue[str]) -> None:
        data, policy = generation.data, generation.policy
        cached = await self.memory.read(generation.conversation_id, policy.memory_ttl_days * 86400)
        sources: list[Source] = []
        retrieval_method = None
        if data.knowledge_enabled:
            retrieval_started = perf_counter()
            async with self.sessions() as session:
                found = await KnowledgeService(
                    KnowledgeRepository(session), self.settings
                ).retrieve_local(
                    data.text,
                    policy.knowledge_limit,
                    base_ids=policy.knowledge_base_ids,
                    vector_threshold=policy.knowledge_vector_threshold,
                    keyword_threshold=policy.knowledge_keyword_threshold,
                )
                retrieval_method = found.retrieval_method
                sources = [
                    InternalSource(
                        id=f"{hit.document_id}:{hit.revision}:{hit.start}",
                        title=hit.title,
                        content=(
                            f"[来源分类：{hit.source_kind}；效力状态：{hit.legal_status}；"
                            f"已发布版本 r{hit.revision}]\n" + hit.content
                        ),
                        source=(
                            hit.source_url
                            or f"/knowledge/{hit.knowledge_base_id}/documents/{hit.document_id}"
                        ),
                        score=hit.score,
                        score_type=hit.score_type,
                        fusion_score=hit.fusion_score,
                        bm25_score=hit.bm25_score,
                        cosine_score=hit.cosine_score,
                        keyword_coverage=hit.keyword_coverage,
                        lexical_rank=hit.lexical_rank,
                        vector_rank=hit.vector_rank,
                        retrieval_method=found.retrieval_method,
                    )
                    for hit in found.items
                ]
            logger.info(
                "咨询知识库检索完成 request_id=%s method=%s sources=%d duration_ms=%.1f",
                data.request_id,
                retrieval_method,
                len(sources),
                (perf_counter() - retrieval_started) * 1000,
            )
        no_hit = data.knowledge_enabled and not sources
        if no_hit:
            memory = (
                cached
                if cached
                and cached.history_version == generation.history_version
                and cached.policy_version == policy_version(policy)
                else None
            )
            if generation.history_version == 0:
                memory = Memory(policy_version=policy_version(policy))
        else:
            generation.provider = replace(
                generation.provider, api_key=decrypt(generation.model_key_encrypted, self.settings)
            )
            memory_started = perf_counter()
            memory = await self._load_memory(generation, queue)
            logger.info(
                "咨询记忆准备完成 request_id=%s duration_ms=%.1f",
                data.request_id,
                (perf_counter() - memory_started) * 1000,
            )
        current = MemoryTurn(
            sequence=generation.history_version + 1,
            user_text=data.text,
            answer="",
            attachment_ids=data.attachment_ids,
        )
        messages = await self._messages(
            generation, [current] if no_hit else [*memory.recent, current]
        )
        await queue.put(event("sources", [source.model_dump() for source in sources]))
        reasoning = ""
        if no_hit:
            answer = "知识库找不到对应信息"
            await queue.put(event("delta", {"text": answer}))
        else:
            system = consultation_system(
                generation.prompt.content if generation.prompt else "",
                memory.summary,
                memory.keywords,
                sources,
                data.knowledge_enabled,
            )
            if (
                estimate_text_tokens(
                    system
                    + json.dumps(
                        [
                            {
                                **m,
                                "content": m["content"]
                                if isinstance(m["content"], str)
                                else [p for p in m["content"] if p["type"] == "text"],
                            }
                            for m in messages
                        ],
                        ensure_ascii=False,
                    )
                )
                + generation.model.max_output_tokens
                >= generation.model.context_tokens
            ):
                raise AppError(
                    "context_exceeded", "上下文过长，请缩短压缩间隔或减少附件，或切换模型"
                )
            answer = ""
            async for part in generation.provider.stream_parts(
                [{"role": "system", "content": system}, *messages]
            ):
                if part.kind == "reasoning":
                    reasoning += part.text
                else:
                    answer += part.text
                if len(answer) + len(reasoning) > 500000:
                    raise AppError("answer_too_long", "回答过长，请缩小问题范围", 502)
                await queue.put(
                    event(
                        "reasoning_delta" if part.kind == "reasoning" else "delta",
                        {"text": part.text},
                    )
                )
            if not answer.strip():
                raise AppError("empty_answer", "模型未返回回答，请重新发送", 502)
        current.answer = answer
        if memory:
            memory.recent.append(current)
            memory.history_version = current.sequence
        if no_hit:
            # 原文摘录仅表示会话背景，不生成模型输出或新的法律结论。
            if memory:
                count = len(memory.recent) // policy.recent_turns * policy.recent_turns
                older = memory.recent[:count]
                if older:
                    excerpt = "\n历史会话原文（未经核实）：" + json.dumps(
                        [{"question": row.user_text, "answer": row.answer} for row in older],
                        ensure_ascii=False,
                    )
                    if (
                        any(row.attachment_ids for row in older)
                        or len(memory.summary + excerpt) > policy.summary_chars
                    ):
                        memory = None
                    else:
                        memory.summary += excerpt
                        memory.covered_through = older[-1].sequence
                        memory.recent = memory.recent[count:]
                if memory:
                    words = re.findall(
                        r"[A-Za-z][A-Za-z0-9_-]{1,30}|[\u4e00-\u9fff]{2,20}|\d+(?:[./-]\d+)*",
                        data.text,
                    )
                    memory.keywords = list(dict.fromkeys([*words, *memory.keywords]))[
                        : policy.keyword_count
                    ]
        snapshot = {
            "model": generation.model.model_dump(mode="json"),
            "prompt": generation.prompt.model_dump(mode="json") if generation.prompt else None,
            "knowledge_enabled": data.knowledge_enabled,
            "knowledge_base_ids": [str(base_id) for base_id in policy.knowledge_base_ids]
            if data.knowledge_enabled
            else [],
            "retrieval_method": retrieval_method,
            "recent_turns": policy.recent_turns,
        }
        async with self.sessions.begin() as session:
            row = Turn(
                conversation_id=generation.conversation_id,
                request_id=data.request_id,
                user_text=data.text,
                answer=answer,
                reasoning=reasoning,
                attachment_ids=[str(value) for value in data.attachment_ids],
                sources=[source.model_dump() for source in sources],
                config_snapshot=snapshot,
            )
            row = await ConsultationRepository(session).save_turn(
                generation.conversation_id, generation.token, row
            )
            view = TurnView.model_validate(row)
        memory_status = "ready" if memory else "deferred"
        try:
            if memory and not await self.memory.write(
                generation.conversation_id, memory, policy.memory_ttl_days * 86400
            ):
                memory_status = "rebuild_required"
        except AppError:
            memory_status = "rebuild_required"
        await queue.put(
            event("done", {"turn": view.model_dump(mode="json"), "memory_status": memory_status})
        )

    async def stream(self, generation: Generation) -> AsyncIterator[str]:
        if generation.previous:
            yield event("start", {"request_id": generation.data.request_id})
            yield event(
                "done",
                {"turn": generation.previous.model_dump(mode="json"), "memory_status": "ready"},
            )
            return
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=128)
        task = asyncio.create_task(self._generate(generation, queue))
        task_result_observed = False
        deadline = asyncio.get_running_loop().time() + generation.policy.request_timeout
        last_renewed = asyncio.get_running_loop().time()
        try:
            yield event(
                "start",
                {"request_id": generation.data.request_id, "model_name": generation.model.name},
            )
            while True:
                if asyncio.get_running_loop().time() >= deadline:
                    raise AppError("generation_timeout", "生成超时，请缩小问题范围或稍后重试", 504)
                get = asyncio.create_task(queue.get())
                try:
                    done, _ = await asyncio.wait(
                        {task, get}, timeout=10, return_when=asyncio.FIRST_COMPLETED
                    )
                    if get in done:
                        yield get.result()
                    if task in done:
                        task_result_observed = True
                        await task
                        while not queue.empty():
                            yield queue.get_nowait()
                        break
                    if asyncio.get_running_loop().time() - last_renewed >= 10:
                        async with self.sessions.begin() as session:
                            if not await ConsultationRepository(session).renew(
                                generation.conversation_id, generation.token
                            ):
                                raise AppError(
                                    "generation_expired", "本次生成已失效，请重新发送", 409
                                )
                        last_renewed = asyncio.get_running_loop().time()
                    if not done:
                        yield ": heartbeat\n\n"
                finally:
                    if not get.done():
                        get.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await get
        except AppError as exc:
            logger.warning(
                "咨询生成未完成 request_id=%s conversation_id=%s code=%s knowledge_enabled=%s",
                generation.data.request_id,
                generation.conversation_id,
                exc.code,
                generation.data.knowledge_enabled,
            )
            yield event("error", {"code": exc.code, "message": exc.message})
        except Exception as exc:
            logger.error("咨询生成失败 type=%s", type(exc).__name__)
            yield event(
                "error", {"code": "generation_failed", "message": "生成暂时不可用，请稍后重试"}
            )
        finally:
            # StreamingResponse 断连时处于已取消的 AnyIO scope；清理也会反复收到取消。
            # 屏蔽外层取消，分别限时结束上游任务和提交占用释放，避免残留会话锁。
            with anyio.CancelScope(shield=True):
                task.cancel()
                try:
                    with anyio.fail_after(5):
                        await task
                except asyncio.CancelledError:
                    pass
                except Exception as exc:
                    # 已由主流程处理的任务异常不属于清理失败，重复 await 会再次抛出它。
                    if not task_result_observed:
                        logger.warning(
                            "咨询生成任务清理异常 request_id=%s type=%s code=%s",
                            generation.data.request_id,
                            type(exc).__name__,
                            exc.code if isinstance(exc, AppError) else "unknown",
                        )
                try:
                    with anyio.fail_after(5):
                        async with self.sessions.begin() as session:
                            await ConsultationRepository(session).release(
                                generation.conversation_id, generation.token
                            )
                except Exception as exc:
                    logger.warning("咨询生成占用释放延迟 type=%s", type(exc).__name__)
