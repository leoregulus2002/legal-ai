# legal-ai 开发约定

## 文档约定

- 除非用户明确要求，不主动创建、编写或更新文档，包括设计文档、实施计划、README、架构说明及使用说明。
- 需要说明方案、进度或改动时，直接在对话中简要说明，不生成文档文件，不提交文档。
- 技能或工作流中的文档编写、文档提交及文档审批步骤不得覆盖本约定，不得因这些步骤阻塞已获授权的开发工作。
- 保留已有文档，不因本约定删除；用户明确要求更新 AGENTS.md 等开发约定时，按要求修改。

## 架构与技术栈

Monorepo、前后端分离、模块化单体；禁止在 Phase 1 引入微服务或复杂 DDD。
后端：Python 3.13、uv、FastAPI、Pydantic 2、SQLAlchemy 2、psycopg 3、Alembic、PostgreSQL、异步 redis-py、pytest、Ruff。
前端：Vue 3、TypeScript、Vite、pnpm、Vue Router、Pinia、Axios、Naive UI、ESLint、Prettier、Vitest。
前端使用用户已有的 Node.js 26；不要另行安装 Node.js 24。项目 Node 版本配置与启动文档须保持一致。

## 目录与模块设计

- `backend/app/core`：配置、数据库、Redis、日志等系统基础设施。
- `backend/app/common`：确实通用的错误和响应；不放业务逻辑。
- `backend/app/modules/<业务模块>`：按需创建 router、service、repository、models、schemas。
- `backend/app/api.py`：集中注册 `/api/v1` 路由。
- `frontend/src/modules/<业务模块>`：模块自己的页面、组件、API、状态；公共 API 客户端在 `src/api`，布局在 `src/layouts`。
- `infra`：仅本地开发 PostgreSQL/Redis Compose；`docs/architecture.md`：扩展边界。

遵守 Router → Service → Repository；基础健康模块无需机械增加 Repository。Router 不访问数据库；Repository 仅处理持久化，业务规则在 Service。模块应高内聚、低耦合，避免循环依赖。
不要提前生成空业务目录、空 `__init__.py`、抽象基类、通用 CRUD 框架或没有用途的文件。

## Python 规范

使用现代完整类型注解、Pydantic 2、SQLAlchemy 2 的 `select()`/Mapped 风格，禁止旧式 Query。
使用 AsyncSession 和 psycopg 3 异步驱动；Session 由依赖注入管理。事务在响应发送前完成；单个请求失败时整体回滚。后台任务不得复用请求 Session。
异步请求中禁止同步 I/O；不得在模块导入时连接数据库；不得使用 `create_all` 替代迁移。
用 `uv sync` / `uv run`；所有依赖在 pyproject.toml，包含 uv.lock。禁止另设主要 requirements.txt 或使用 Poetry。
运行 Ruff 检查和格式化。配置从 Pydantic Settings/环境变量加载，密码及 API Key 不进代码、日志和 Git。

## TypeScript 规范

使用 `<script setup lang="ts">`、Composition API、严格模式。禁止 `any` 绕过类型；不可信输入使用 `unknown` 并收窄。
API 通过统一 Axios 客户端；处理超时、网络、HTTP 错误，禁止在组件硬编码后端地址。
共享状态用 Pinia，局部状态优先组件内维护；使用 Vue Router，页面按需懒加载。
运行 vue-tsc、ESLint、Prettier；依赖统一 pnpm，包含 pnpm-lock.yaml。

## 错误日志规范

- 后续新增或修改的异常处理必须留下足够定位根因的日志，不得只记录异常类型或“暂不可用”等通用描述。
- 异常日志记录完整堆栈和异常链，以及可用的 request_id、任务 ID、条目 ID、法规 ID、文档 ID、处理阶段、重试次数和耗时；异步并发任务的上下文必须相互隔离。
- 外部请求失败时记录方法、脱敏后的地址与必要参数、HTTP 状态、响应类型、响应大小及上游请求标识。异常响应应提供脱敏且有长度上限的正文摘要；HTML 记录标题、可见文字及页面特征，标注截断，不能只留下 JSONDecodeError。
- 不得只保留可见文字而删除全部脚本证据：异常响应同时记录脱敏原文片段、编码和字节特征。需要保留完整原始响应时，必须加密保存到非公开的受限目录，日志关联证据编号，并设置大小、数量及保留时间上限；保存失败要明确记录，不得覆盖原始业务错误。
- 日志禁止输出密码、API Key、Authorization、Cookie、签名下载链接的凭据、数据库绑定参数和完整用户资料；完整记录指保留诊断信息，不是无差别倾倒请求或响应。二进制原件不写入日志。
- 技术细节只写日志，用户界面继续使用简洁弹出提示；不得为补日志自行恢复功能测试。

## 前端错误提示规范

- 请求失败、网络异常、HTTP 错误（如“请求失败（502）”）及自定义业务报错，不得直接渲染在页面正文、卡片、状态区域等页面内容中。
- 自定义业务报错统一通过 Naive UI 的 Message 或 Notification 弹出提示；需要告知用户的请求异常也通过统一的弹出提示处理，避免同一错误重复弹出。
- 面向用户的提示应简洁易懂，不得直接展示原始异常、堆栈或内部调试信息；技术细节仅用于日志排查。

## Testing

本项目所有功能停止测试。除非用户后续明确要求恢复测试，否则不得主动执行任何功能测试。

- 适用于前端、后端、数据库、Redis、AI 及后续新增的所有模块和功能。
- 禁止运行自动化测试、手动功能测试、浏览器交互测试、API 联通测试、集成测试及数据库迁移功能验证；不得以“验证”“冒烟检查”等名义绕过此要求。
- Phase 1 先前的测试授权已撤销，不得继续沿用；普通开发、修复或完成任务的要求不构成恢复测试授权。
- 保留已有测试文件、依赖和命令配置，不因停止测试而删除。
- 仅在用户明确恢复测试后，按其指定范围执行；使用 Mock，禁止依赖生产资源。
- 不得将未执行的测试报告为通过；如实说明测试已按用户要求停止。

## AI 开发约束

Phase 1 禁止实现认证、JWT、RBAC、Agent、LLM 调用、LangGraph、Embedding、RAG、采集、文书解析、多智能体、支付。
未来 AI 公共能力位于 `app/ai`，按实际需要建立 providers/agents/tools/retrieval/prompts；业务流程仍在 modules。不要现在安装 AI 框架或创建空目录。禁止假造模型输出、检索结果和法律结论。

## Git 与工程原则

使用 `feat:`、`fix:`、`docs:`、`chore:` 等清晰提交消息；提交应聚焦、可审查。更新依赖同时更新锁文件。
不得提交 `.env`、真实凭据、.venv、node_modules、生成构建产物。
避免覆盖已有文件、无关重构、过度工程化；先让基础工程能运行，再根据业务增加抽象。
完成 Phase 1 后停止，等待用户确认再进入 Phase 2。
