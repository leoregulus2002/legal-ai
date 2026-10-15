import asyncio
import contextlib
import json
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import UploadFile
from pydantic import ValidationError
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.prompts.context import SUMMARY_INSTRUCTION, consultation_system
from app.ai.providers.client import Provider, estimate_text_tokens
from app.ai.retrieval.client import retrieve
from app.common.exceptions import AppError
from app.core.config import Settings
from app.core.secrets import decrypt
from app.modules.consultation.attachments import AttachmentStorage
from app.modules.consultation.memory import MemoryStore, policy_version
from app.modules.consultation.models import Conversation, Turn
from app.modules.consultation.repository import ConsultationRepository
from app.modules.consultation.schemas import (
    AttachmentView,
    ConversationView,
    GenerateInput,
    Memory,
    MemoryTurn,
    SummaryResult,
    TurnView,
)
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
    knowledge_key: str
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
                knowledge_key=decrypt(policy_row.kb_key_encrypted, self.settings)
                if data.knowledge_enabled and policy.knowledge_url
                else "",
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

    async def _update_memory(self, generation: Generation, memory: Memory) -> Memory:
        policy = generation.policy
        count = max(0, len(memory.recent) - policy.recent_turns)
        older = memory.recent[:count]
        recent = memory.recent[count:]
        # 摘要仅覆盖移出窗口的轮次；关键词同时参考窗口内文本。
        instruction = (
            SUMMARY_INSTRUCTION
            + f"\n摘要最多 {policy.summary_chars} 字，关键词最多 {policy.keyword_count} 个。"
        )
        instruction += (
            "summary 只能合并此前摘要和待压缩轮次；近期背景只用于关键词，不写入摘要。"
            "没有待压缩轮次时原样返回此前摘要（可为空）。"
        )
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
            if not older and result.summary != memory.summary:
                raise ValueError
            if older and not result.summary.strip():
                raise ValueError
        except (ValidationError, ValueError) as exc:
            raise AppError(
                "invalid_memory", "记忆摘要生成失败，请调整模型配置或重新发送", 502
            ) from exc
        return Memory(
            history_version=memory.history_version,
            policy_version=policy_version(policy),
            covered_through=older[-1].sequence if older else memory.covered_through,
            summary=result.summary,
            keywords=result.keywords,
            recent=recent,
        )

    async def _load_memory(self, generation: Generation) -> Memory:
        ttl = generation.policy.memory_ttl_days * 86400
        memory = await self.memory.read(generation.conversation_id, ttl)
        if (
            memory
            and memory.history_version == generation.history_version
            and memory.policy_version == policy_version(generation.policy)
        ):
            return memory
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
                if len(memory.recent) >= generation.policy.recent_turns + 2:
                    memory = await self._update_memory(generation, memory)
            after = batch[-1].sequence
        if memory.recent:
            memory = await self._update_memory(generation, memory)
        await self.memory.write(generation.conversation_id, memory, ttl)
        return memory

    async def _generate(self, generation: Generation, queue: asyncio.Queue[str]) -> None:
        data, policy = generation.data, generation.policy
        cached = await self.memory.read(generation.conversation_id, policy.memory_ttl_days * 86400)
        if (
            data.knowledge_enabled
            and policy.knowledge_url
            and not (
                cached
                and cached.history_version == generation.history_version
                and cached.policy_version == policy_version(policy)
            )
        ):
            # 外部检索需要完整背景，不能用缺失的旧事实得出“未命中”。
            if generation.history_version:
                generation.provider = replace(
                    generation.provider,
                    api_key=decrypt(generation.model_key_encrypted, self.settings),
                )
            cached = await self._load_memory(generation)
        retrieval_summary = cached.summary if cached else ""
        retrieval_keywords = cached.keywords if cached else []
        if data.knowledge_enabled and policy.knowledge_url:
            async with self.sessions() as session:
                recent = await ConsultationRepository(session).turns(
                    generation.conversation_id,
                    max(0, generation.history_version - policy.recent_turns),
                    policy.recent_turns,
                )
                retrieval_summary += "\n近期用户问题：" + json.dumps(
                    [row.user_text for row in recent],
                    ensure_ascii=False,
                )
        sources = (
            await retrieve(
                data.text, retrieval_summary, retrieval_keywords, policy, generation.knowledge_key
            )
            if data.knowledge_enabled
            else []
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
            memory = await self._load_memory(generation)
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
                raise AppError("context_exceeded", "上下文过长，请减少记忆轮数或附件，或切换模型")
            answer = ""
            async for delta in generation.provider.stream(
                [{"role": "system", "content": system}, *messages]
            ):
                answer += delta
                if len(answer) > 500000:
                    raise AppError("answer_too_long", "回答过长，请缩小问题范围", 502)
                await queue.put(event("delta", {"text": delta}))
            if not answer.strip():
                raise AppError("empty_answer", "模型未返回回答，请重新发送", 502)
        current.answer = answer
        if memory:
            memory.recent.append(current)
            memory.history_version = current.sequence
        if no_hit:
            # 原文摘录仅表示会话背景，不生成模型输出或新的法律结论。
            if memory:
                older = memory.recent[: -policy.recent_turns]
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
                        memory.recent = memory.recent[-policy.recent_turns :]
                if memory:
                    words = re.findall(
                        r"[A-Za-z][A-Za-z0-9_-]{1,30}|[\u4e00-\u9fff]{2,20}|\d+(?:[./-]\d+)*",
                        data.text,
                    )
                    memory.keywords = list(dict.fromkeys([*words, *memory.keywords]))[
                        : policy.keyword_count
                    ]
        else:
            memory = await self._update_memory(generation, memory)
        snapshot = {
            "model": generation.model.model_dump(mode="json"),
            "prompt": generation.prompt.model_dump(mode="json") if generation.prompt else None,
            "knowledge_enabled": data.knowledge_enabled,
            "recent_turns": policy.recent_turns,
        }
        async with self.sessions.begin() as session:
            row = Turn(
                conversation_id=generation.conversation_id,
                request_id=data.request_id,
                user_text=data.text,
                answer=answer,
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
            yield event("error", {"code": exc.code, "message": exc.message})
        except Exception as exc:
            logger.error("咨询生成失败 type=%s", type(exc).__name__)
            yield event(
                "error", {"code": "generation_failed", "message": "生成暂时不可用，请稍后重试"}
            )
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
            with contextlib.suppress(Exception):
                async with self.sessions.begin() as session:
                    await ConsultationRepository(session).release(
                        generation.conversation_id, generation.token
                    )
