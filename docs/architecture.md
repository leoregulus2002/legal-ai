# 架构与扩展边界

## 当前实现

采用 Monorepo + 前后端分离 + 模块化单体。`frontend` 是 Vue 应用，`backend` 是一个 FastAPI 进程，`infra` 仅启动 PostgreSQL/Redis。
Phase 1 建立配置、资源生命周期、健康接口、迁移和基础 UI；后续按用户授权新增 AI 法律咨询与系统配置，仍不包含认证或 Agent。

本地 Compose 使用已有的 `pgvector/pgvector:pg18-trixie` 和 `redis:8-alpine`，设置 `pull_policy: never`，不自动拉取镜像。PostgreSQL 18 使用独立数据卷挂载 `/var/lib/postgresql`，不复用旧 PostgreSQL 17 数据卷；Redis 使用密码认证、AOF、`appendfsync always` 和 `noeviction`。当前配置调整不自动执行容器重建、数据升级或功能测试。

后端链路：`app/api.py → modules/health/router.py → service.py → core 的依赖检查`。只有真实持久化业务才增加 Repository。
前端链路：`HomePage → Pinia health store → workspace/api → api/client → /api/v1/health`。
模块间优先显式调用 Service；不引入事件总线、微服务、通用 Repository 或过度分层。

## 基础设施与故障行为

Pydantic Settings 在应用工厂加载 `.env`/环境变量，连接地址必填，错误提示不暴露输入凭据。
应用导入不连接数据库或 Redis；lifespan 创建 engine/session factory 和 Redis 客户端。Redis 启动 ping 失败只记录脱敏警告，资源通过 AsyncExitStack 逆序关闭。
`GET /api/v1/health` 只确认请求处理进程存活，恒定轻量，不代表依赖健康。
`GET /api/v1/health/ready` 并发检查 PostgreSQL `SELECT 1` 和 Redis `PING`，每项最多 3 秒，失败返回 503 和依赖状态，不泄漏异常细节。

数据库使用 `postgresql+psycopg` AsyncEngine、AsyncSession、请求级依赖。Session 事务上下文成功提交、失败或取消回滚；依赖为 function scope，使提交发生在响应发送前。Service 不应自行提交，Repository 可 flush，需要不同事务范围时应明确设计。
Alembic 使用异步 online runner + `connection.run_sync`；离线支持 SQL 输出。扫描 `modules/*/models.py` 导入当前模型并统一到 `Base.metadata`。Phase 1 没有业务模型，0001 是空 schema 基线，仍建立 alembic_version。

错误响应：`{"error":{"code":"...","message":"..."},"request_id":"..."}`；健康成功响应保持 `{"status":"ok"}`。请求日志仅包含 method/path/status/duration/request_id，不记录 body、query、认证信息或连接串。
浏览器通过相对 API 前缀访问，Vite 仅在开发模式代理，生产必须配置同域反向代理或显式 API origin/CORS。服务状态仅反映 liveness。

## 后续业务与 AI

当前已实现的 AI 咨询边界：`modules/system_config` 管理模型、加密 API Key、提示词版本和咨询策略，所有业务配置存 PostgreSQL；`modules/consultation` 管理完整会话历史、附件、生成占用和流式业务。`ai/providers` 适配 Chat Completions/Responses，`ai/retrieval` 仅接入外部检索接口或明确空库，`ai/prompts` 组装咨询及记忆指令。完整历史在 PostgreSQL，最近 N 轮、摘要、关键词和版本在 Redis，不创建数据库记忆表。

`0002_consultation.py` 定义实际业务表；本次未执行迁移。流式业务使用应用 session factory 管理短事务，模型调用期间不持有数据库事务。完整回答先提交 PostgreSQL，再发布 Redis 记忆；跨存储失败由历史版本检测与重建处理。凭据在 PostgreSQL 中使用 Fernet 加密，主密钥仅由后端环境配置加载。附件异步存储在被 Git 忽略的数据目录，后台清理任务使用独立 Session，并在 lifespan 退出时取消。

未配置知识库 URL 时直接返回空库回复；外部知识库采用明确 HTTP 契约，检索故障与未命中区分。多模态能力按模型声明及真实供应商协议校验，不提供模拟法律输出。使用方式见 [法律咨询文档](legal-consultation.md)。

新增真实身份业务时创建 `modules/identity`，按需加入 router/service/repository/models/schemas，集中注册路由。SQLAlchemy 2 模型继承 Base，提交对应迁移，禁止生产运行自动建表。
前端同时增加 `modules/identity` 页面/API/状态；只把跨模块通用代码提取为公共组件。

业务依赖 AI 能力，而 AI 基础能力不依赖 FastAPI Router；以下仍说明未来扩展范围：

- `app/ai/providers`：模型供应商适配、异步调用、超时和规范化结果；通过配置注入凭据。
- `app/ai/agents`：实际需要时接入 LangGraph 等编排，避免将 Web 请求和状态机绑定。
- `app/ai/tools`：工具接口与执行边界，授权和审计由业务 Service 管理。
- `app/ai/retrieval`：Embedding、向量库、RAG 检索；镜像已提供 pgvector 扩展文件，后续通过迁移在数据库中启用 `vector` 扩展，当前不启用或实现检索。
- `app/ai/prompts`：版本化提示模板及元数据；禁止混入 API 密钥。

chat/knowledge/documents/agents 等业务模块拥有自己的数据和流程，普通业务模块与 AI 公共能力保持边界。跨模块复用在有明确重复后再提取。后续另行设计认证、隔离、审计、后台执行和法律来源追溯，不在 Phase 1 做假实现。

## 界面设计与验证

中文首页采用现代法律研究平台视觉：海军蓝侧栏、暖象牙白画布、古铜色细线、宋体标题与无衬线交互文字；主视觉使用独立生成的法典及司法立柱配图。服务状态压缩为页头区域，能力入口采用一个重点入口与三个列表行。工作台及 AI 法律咨询为可用业务导航；系统配置包含三个独立菜单，其余规划入口继续标注“即将开放”。移动端使用可开关侧栏，能力入口纵向排列；404 沿用同一品牌视觉并提供返回工作台。
参考图仅指导布局，交互、文本、图标与服务状态均是 Vue/CSS 原生实现；状态必须来自真实请求。

本次视觉重设计按用户要求不执行自动化测试、手动功能测试或浏览器验证；不得据此宣称已完成浏览器视觉一致性验证。功能入口使用原生司法立柱图标作为品牌水印，避免额外重复照片。
