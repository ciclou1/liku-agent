# 验收记录

每个 plan 只有在对应测试和验收证据完成后才可将任务清单从 `[ ]` 更新为 `[x]`。记录至少包含：执行命令、数据规模、结果、日期和残余风险。

当前状态：

- 前端 TypeScript/Vite 构建已通过。
- Compose 配置校验已通过。
- 后端测试已在 Python Docker 容器执行，当前全量回归为 51 项通过。
- 真实 LLM 联调接口已用 Anthropic 兼容 mock transport 验证；真实令牌仍需通过环境变量注入。
- 100,000 SKU 基准：同步 0.074 秒，预测 5.891 秒。
- Docker Compose 配置校验通过；完整 Compose 启动受 Python 3.11 基础镜像下载限制，尚未标记为通过。
- HTTP 冒烟通过：临时 API `/api/v1/health` 返回 `ok`，库存和预测接口返回数据，OpenAPI 含开放接口路由；前端 `http://localhost:5173` 返回 `200`。
- 当前预览服务：前端开发服务器 PID 16340；fixture API 容器 `liku-api-dev-20260908`，仅用于本地预览。
- 生产化修复回归：后端 54 项测试通过，前端 2 项测试和生产构建通过。
- 已切换：业务查询使用 SQLAlchemy 数据库表；采购建议、配置、审计和预测结果支持持久化；生产匿名请求返回 401；Celery runner、worker 状态文件、StatsForecast/LightGBM 入口和真实外部 provider 已接入。
- Compose：已重试 `docker compose up -d --build`，当前阻塞在 Docker Hub 镜像分片下载，未完成真实 MySQL/Redis/worker/beat 启动验收。

## 最新部署验收（2026-09-08）

- 后端镜像使用 Python 3.13 构建成功，StatsForecast 和 LightGBM 依赖安装成功。
- 后端回归：`docker run --rm ... agent-backend:latest python -m pytest tests -q`，55 项通过。
- 前端回归：`npm test -- --run`，2 项通过；`npm run build` 生产构建通过。
- 生产 Compose、SQLite 本地演示 Compose 和主机端口覆盖配置校验通过。
- 本机生产栈已运行：MySQL 8.4、Redis 7、API、Celery worker/beat、前端、Prometheus、Grafana、Alertmanager。
- API readiness、Prometheus readiness、Grafana health、Alertmanager readiness、前端均返回 HTTP 200。
- Prometheus 的 `liku-api` target 为 up，已加载 1 个告警规则组；Grafana 已发现 2 个 dashboard。
- MySQL 演示数据：5 个物料、4 个仓库、3 个供应商、6 条库存快照、3 条采购单、12 条领用、8 条价格、4 条库存流水。
- 业务冒烟：库存 6 行、预测 12 个点、预警 7 行、调剂查询成功，Celery 任务完成且进度 100%。
- 主机端口覆盖文件将 API 映射到 `http://localhost:18000`，用于宿主机 8000 已被占用的场景。
- 残余风险：甲方 ERP/EAM/WMS/IM/SSO 凭据和真实 LLM 网络仍需在目标环境做联调。
