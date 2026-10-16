# legal-ai

法律 AI 智能工作台。采用 Monorepo、前后端分离、模块化单体，包含基础开发环境、健康接口和 AI 法律咨询模块。咨询支持模型切换、知识库接入、流式输出、图片/PDF 和 Redis 会话记忆，配置通过独立菜单保存到 PostgreSQL。

新增模块的配置顺序、加密主密钥、数据库迁移及内部知识库配置与混合召回见 [法律咨询使用说明](docs/legal-consultation.md)。咨询通过多选内部知识库限定检索范围，使用 BM25 + 余弦向量召回及 RRF 融合；`0005_hybrid_retrieval.py` 为词频索引迁移。本次没有执行迁移或任何功能测试，实际使用新增模块前需先完成文档中的准备步骤。

## 技术栈

- 前端：Vue 3、TypeScript 5.9、Vite 8、pnpm 11、Vue Router 4、Pinia 3、Axios、Naive UI、ESLint、Prettier、Vitest。
- 后端：Python 3.13、uv、FastAPI、Pydantic 2/pydantic-settings、SQLAlchemy 2、psycopg 3、Alembic、redis-py、pytest、Ruff。
- 本地基础设施：pgvector/PostgreSQL 18（pg18-trixie）、Redis 8（8-alpine），复用本地镜像，持久化 Volume，仅绑定 127.0.0.1。

## 目录结构

```text
legal-ai/
├── AGENTS.md
├── README.md
├── package.json
├── pnpm-workspace.yaml
├── pnpm-lock.yaml
├── docs/architecture.md
├── infra/
│   ├── .env.example
│   └── compose.yaml
├── backend/
│   ├── .env.example
│   ├── .python-version
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── alembic.ini
│   ├── migrations/{env.py,script.py.mako,versions/0001_baseline.py}
│   ├── app/
│   │   ├── main.py
│   │   ├── api.py
│   │   ├── core/{config,database,redis,logging}.py
│   │   ├── common/{exceptions,responses}.py
│   │   └── modules/health/{router,service,schemas}.py
│   └── tests/
└── frontend/
    ├── .env.example
    ├── package.json
    ├── vite.config.ts
    ├── tsconfig.json
    ├── eslint.config.js
    └── src/
        ├── main.ts / App.vue / styles.css
        ├── api/{client.ts,client.test.ts}
        ├── router/index.ts
        ├── layouts/AppLayout.vue
        ├── components/AppIcon.vue
        ├── pages/NotFoundPage.vue
        └── modules/workspace/
            ├── api.ts / store.ts / features.ts
            ├── pages/HomePage.vue
            └── components/{FeatureEntry,ServiceStatus}.vue
```

上方为基础工程目录；新增后端 `modules/system_config`、`modules/consultation`、`ai/{providers,retrieval,prompts}` 与 `migrations/versions/0002_consultation.py`，前端新增 `modules/system-config`、`modules/consultation` 和 `api/stream.ts`。详细边界见 [架构文档](docs/architecture.md)。当前使用 Python namespace packages，不机械创建空 `__init__.py`。

## 环境要求

- Node.js 26（复用用户已有安装；`.node-version` 为 26），pnpm 11.25.0。
- uv，可通过 [uv 官方安装说明](https://docs.astral.sh/uv/getting-started/installation/) 安装。
- Python 3.13，由 `uv python install 3.13` 管理；不使用系统 Python 作为项目环境。
- Docker 和 Docker Compose v2，确保 Docker 守护进程正在运行。

如果终端仍指向旧版 Node，请先通过 nvm/fnm 等版本管理器切换到已有的 26，不要另行安装 24。Vite 的 Node 环境要求见 [官方文档](https://vite.dev/guide/)。

## 初始化

在仓库根目录执行；已有 `.env` 时保留自己的配置，不要覆盖。

```bash
cp -n infra/.env.example infra/.env
cp -n backend/.env.example backend/.env
cp -n frontend/.env.example frontend/.env
nvm use 26
npm install --global pnpm@11.25.0
pnpm install --frozen-lockfile
cd backend
uv python install 3.13
uv sync --locked
```

一般安装使用 `uv sync`，锁文件安装可以使用 `uv sync --locked`。依赖仅在 pyproject.toml 声明，uv.lock 和 pnpm-lock.yaml 纳入版本控制。

示例凭据仅用于本地开发。真实密码/API Key 必须在被 Git 忽略的 `.env` 或部署密钥系统中配置。前端所有 `VITE_` 变量会进入公开构建产物，禁止放密钥。
后端环境变量优先于 `.env`。`APP_ENV` 支持 development/test/production，`DEBUG` 控制开发 Swagger/ReDoc 页面；统一异常响应始终开启。配置错误会在启动时产生清晰校验错误。
`DATABASE_URL` 使用 `postgresql+psycopg://`，密码特殊字符需 URL 编码；`REDIS_URL` 使用 redis/rediss scheme；`CORS_ORIGINS` 是 JSON 数组，例如 `["http://localhost:5173"]`，不带尾斜线或路径。

## 启动 PostgreSQL 和 Redis

仓库根目录：

```bash
docker compose --env-file infra/.env -f infra/compose.yaml up -d --wait
docker compose --env-file infra/.env -f infra/compose.yaml ps
```

数据库和 Redis 密码分别配置在 infra/.env，必须与 backend/.env 连接串一致。端口冲突可改 POSTGRES_PORT/REDIS_PORT 并同步后端地址。
本次本地验证因默认端口被占用，在被 Git 忽略的 infra/.env/backend/.env 中使用 PostgreSQL 15432、Redis 16379；示例文件仍保留默认端口。

停止服务用 `docker compose --env-file infra/.env -f infra/compose.yaml down`，Volume 会保留；只有明确需要清空开发数据时才加 `-v`。
Compose 使用 pgvector 镜像，已提供扩展文件；Phase 1 不启用数据库 `vector` 扩展，后续需要时通过 Alembic 迁移启用。
PostgreSQL 18 使用独立的 `postgres18_data` Volume，挂载 `/var/lib/postgresql`，不复用上一版 PostgreSQL 17 的数据卷。旧数据卷保留，但数据不会自动迁入新数据库；有业务数据时需另行安排升级迁移。
更新上一版环境时，先用 `docker compose --env-file infra/.env -f infra/compose.yaml down` 停止旧服务，再执行上面的启动命令和 `uv run alembic upgrade head`。不要添加 `-v`。
Redis 保留密码认证，启用 AOF、`appendfsync always` 和 `noeviction`；两个服务均配置 `restart: unless-stopped`。
两个服务设置 `pull_policy: never`，启动时只使用本地已有的 `pgvector/pgvector:pg18-trixie` 和 `redis:8-alpine`，不会自动拉取或更新镜像。本地缺少对应镜像时会报错，需要用户自行明确选择导入或拉取镜像后再启动。

## 后端启动

```bash
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

- API：<http://127.0.0.1:8000/api/v1/health>，返回 `{"status":"ok"}`。
- readiness：<http://127.0.0.1:8000/api/v1/health/ready>，依赖全部正常返回 200，失败返回 503。
- Swagger：<http://127.0.0.1:8000/docs>；ReDoc：<http://127.0.0.1:8000/redoc>（DEBUG=true）。
- OpenAPI schema：<http://127.0.0.1:8000/openapi.json>。

lifespan 管理数据库/Redis 资源。不依赖真实数据库也能运行 liveness；Redis 启动连接失败会告警而不让进程崩溃，readiness 会报告不可用。
生产示例：设置 APP_ENV=production、DEBUG=false，使用 `uv run uvicorn app.main:app --host 0.0.0.0 --port 8000`，不要开启 reload；部署方案留待后续阶段。

## 前端启动

仓库根目录：

```bash
nvm use 26
pnpm dev
```

打开 <http://127.0.0.1:5173>。Vite 开发代理把 `/api` 转发至 API_PROXY_TARGET（仅服务器配置，默认 127.0.0.1:8000）。浏览器 Axios 统一以 VITE_API_BASE_URL=/api/v1 请求，10 秒超时；首页显示真实 liveness 状态，刷新按钮可重新检查。

```bash
pnpm build
pnpm --filter @legal-ai/frontend preview
```

生产构建不包含 Vite 开发代理。部署时配置同域 `/api` 反向代理到 FastAPI，并让未知前端路径回退 `index.html` 支持 History 路由。或者在构建前设置 VITE_API_BASE_URL 为完整 API 地址，同步配置后端 CORS_ORIGINS。
Vite 原生支持 `.env.development`、`.env.production` 等模式配置；修改 VITE 变量后需要重启开发服务或重新构建。

## 数据库迁移

```bash
cd backend
uv run alembic history
uv run alembic upgrade head
# 新增实际模型后：
uv run alembic revision --autogenerate -m "create identity tables"
# 在开发数据库需要回退时：
uv run alembic downgrade -1
# 无数据库情况下检查迁移 SQL：
uv run alembic upgrade head --sql
```

Phase 1 无业务表，0001 是空 schema 基线，升级仅建立 alembic_version。后续 `app/modules/<name>/models.py` 自动被发现，模型需继承 core.database.Base。生成脚本必须人工审阅再升级。禁止 create_all 替代迁移。实际自动生成需要可用 PostgreSQL。
数据库连接由 SQLAlchemy [psycopg 异步 dialect](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#module-sqlalchemy.dialects.postgresql.psycopg) 管理。

## 测试运行

当前所有功能测试已按用户要求停止，先前 Phase 1 测试授权已撤销。以下命令仅保留供用户明确恢复测试后使用；测试使用 Mock，不访问生产环境。

```bash
# 根目录：前端
pnpm test
# 后端
cd backend
uv run pytest
```

后端覆盖 liveness/readiness、配置加载、统一错误、请求 ID、CORS 和事务边界；前端覆盖基础组件状态/刷新和 API 客户端成功、网络、超时、HTTP 错误。

## 代码检查

```bash
# 根目录
pnpm typecheck
pnpm lint
pnpm format:check
pnpm build
# 格式化前端
pnpm --filter @legal-ai/frontend format
# 后端
cd backend
uv run ruff check .
uv run ruff format --check .
# 格式化后端
uv run ruff format .
```

## 常见问题

- **Node 版本太旧**：切换到已有的 Node 26 后安装依赖；不要使用 Node 14/16，也不要另行安装 24。
- **pnpm 找不到**：先执行 `nvm use 26`；若该 Node 环境尚未安装 pnpm，执行 `npm install --global pnpm@11.25.0`。nvm 下不同 Node 版本的全局工具相互独立，切换版本后需要使用对应环境中的 pnpm。
- **uv 不存在**：按官方说明安装后重开终端或把 `~/.local/bin` 加入 PATH。
- **Docker daemon 无法连接**：启动 Docker Desktop 或已有 Docker 服务后再执行 Compose。
- **首页服务不可用**：确认后端 8000 正在运行，Vite 的 API_PROXY_TARGET 正确；检查浏览器网络面板和请求 ID。状态正常只表示 liveness，不表示数据库/Redis ready。
- **readiness 返回 503**：启动 PostgreSQL/Redis，核对密码/端口和 URL 编码；不要把响应伪装成 200。
- **配置加载失败**：在 backend 目录运行命令并创建 backend/.env；CORS_ORIGINS 使用 JSON 数组，URL scheme 要正确。
- **迁移提示无新表**：Phase 1 本来没有业务模型；以后新增 models.py 继承 Base 并检查迁移内容。
- **生产页面 404 或 API 失败**：配置 SPA 回退和 `/api` 反向代理，Vite preview 不自动代理生产 API。

## Phase 边界

已按后续用户授权开发法律咨询、历史记录、模型接入、系统配置和 Redis 记忆；内部知识库包含资料录入、解析、人工审核发布、真实向量化，以及 BM25 + 余弦召回与 RRF 融合。咨询通过配置选择可用内部知识库，不再接入外部知识库 HTTP 服务。尚未实现用户注册登录、JWT、RBAC、自动法规/裁判文书采集、合同分析、文书生成、Agent、LangGraph、多智能体或支付；本次不接入重排序模型。
