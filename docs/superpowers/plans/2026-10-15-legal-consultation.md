# AI 法律咨询实施计划

> 执行方式：superpowers:executing-plans，在本会话连续完成。用户已要求“开发”，不重复申请实施批准。用户停止测试的要求优先于技能的 TDD 步骤。

**Goal:** 完成配置入库、Redis 记忆、可切换模型的多模态流式法律咨询。

**Architecture:** FastAPI 模块化单体，Router → Service → Repository；异步 HTTP 模型适配；PostgreSQL 记录配置和完整历史，Redis 记录运行记忆。Vue/Naive UI 沿用现有布局。

**Tech Stack:** Python 3.13、SQLAlchemy 2、redis-py、httpx、cryptography、Vue 3、TypeScript、Axios、Node.js 26、pnpm。

**Spec:** ../specs/2026-10-15-legal-consultation-design.md

## Global Constraints

- 所有功能测试停止，仅运行 Ruff、vue-tsc、ESLint、Prettier 和静态审阅。
- 不运行数据库迁移、浏览器交互、API/模型/知识库联通检查。
- 配置存 PostgreSQL；最近 N 轮、摘要、关键词及进度存 Redis。
- 未命中知识库固定回复“知识库找不到对应信息”。
- 不安装 AI 编排框架，不扩展知识库建设、认证、支付等范围。
- 当前基础工程全部未跟踪，使用当前 checkout 的 codex 分支保留原文件，不创建缺失基础代码的独立 worktree。

## Review Focus

- 明文凭据不得经读取接口、错误或快照泄漏。
- Redis 不可用不得静默丢弃记忆；跨存储提交失败不得重复回答。
- 模型切换不得静默忽略附件；PDF 与图片能力分别检查。
- 取消与并发请求不得留下成功消息或覆盖较新记忆。
- 知识库异常不得被当作空库或转为模型自由回答。

## Tasks

- [x] 1. 配置：新增 system_config 的 models/schemas/repository/service/router、加密工具及迁移；提供模型、提示词版本、咨询策略维护，脱敏读取。
- [x] 2. AI：新增 providers 的 SSE/协议转换、retrieval 接口与空库分支、prompts 上下文模板；处理超时、结构验证及多模态能力。
- [x] 3. 咨询：新增 consultation 的 models/schemas/repository/attachments/memory/service/router；数据库完整历史、Redis 记忆、幂等和流式独立事务。
- [x] 4. 前端：增加配置与咨询 API/类型、三个配置页面、咨询工作台、菜单和首页入口；所有异常用统一弹窗。
- [x] 5. 工程交付：依赖锁文件、环境变量说明、启动与接入文档；运行静态检查，静态审阅并处理问题，更新完成记录。

## Execution notes

- 设计已由用户确认；后续“开发”授权按修订后的存储方案直接实施。
- 保留现有测试，未执行或新增功能测试。
- 静态检查：`uv run ruff check .`、`uv run ruff format --check .`、`pnpm typecheck`、`pnpm lint`、`pnpm format:check` 均通过。
- 独立只读审阅提出的约束命名、租约过期、错误流解码、空库记忆、附件压缩与首次事件取消问题已处理，复查没有新的重要问题。
- 本地 `.env` 已补充随机生成的加密主密钥，未输出或提交密钥。数据库迁移未执行，真实模型和外部知识库由用户通过菜单配置。
- 实现留在 `codex/legal-consultation` 工作分支；原始基础工程尚未跟踪，未将其整体代为提交。
