# Plan 09 · 非功能需求 + 技术方案

> 对应 PRD 4/5　|　适用所有子计划

## 1. 非功能需求
| 项 | 要求 |
|---|---|
| 性能 | 常规查询 < 2s；十万级 SKU 批量预测 ≤ 数小时（夜间任务） |
| 数据安全 | 数据不出企业内网的部署方案保留（私有化 LLM 路由预留）；敏感数据脱敏；操作审计日志 |
| 可用性 | 7×24 服务可用，同步任务失败自动重试 + 告警 |
| 可扩展性 | 支持多组织/多仓库水平扩展；算法模型可插拔替换 |
| 国产化 | 一期不强制信创，架构预留（MySQL 系可换达梦/OceanBase） |

## 2. 技术栈
| 层 | 选型 | 说明 |
|---|---|---|
| 前端 | React 18 + Ant Design 5 + ECharts | 管理后台 + 数据大屏；团队 AI 辅助开发，选生态最大方案 |
| 后端 | Python 3.11 + FastAPI | 与算法同栈，降低维护成本 |
| 任务调度 | Celery + Redis（或 APScheduler 起步） | 夜间批量预测、数据同步任务 |
| 数据库 | MySQL 8（主库）+ Redis（缓存） | 预留达梦/OceanBase 替换路径；预留 ClickHouse 做分析加速（十万级 SKU 聚合查询） |
| 预测算法 | Nixtla StatsForecast / mlforecast + LightGBM | GitHub 高星开源、工业界验证；备选 Darts |
| 价格预测 | Prophet / LightGBM + 行情特征 | 趋势 + 季节性建模 |
| LLM | 混合路由：Claude API（云端，通用分析/报告）+ 国产云端 API（DeepSeek/通义，合规兜底） | 抽象 LLM 网关层，私有化模型（Qwen）作为后续可选路由 |
| 消息/IM | 企业微信 / 钉钉 / 飞书开放平台 SDK | 机器人 + 预警推送 |
| 部署 | Docker Compose 起步 → K8s 演进 | 公有云 / 私有化双方案 |

## 3. 架构要点
1. **算法与 LLM 职责分离**：数值预测、利库计算全部由确定性算法完成；LLM 只负责自然语言交互、结果解释、报告生成——保证数值可审计、防幻觉。
2. **LLM 网关抽象**：统一接口 + 路由策略（数据敏感度 → 私有/国产/云端模型），应对"部署环境待定"。
3. **Text-to-SQL + Function Calling**：Chatbot 通过受控查询接口访问数据，不直接开放原始库。
4. **预测任务流水线**：数据同步 → 特征工程 → 批量预测 → 回测评估 → 结果入库，全链路可监控。

## 4. 关键风险与应对
| 风险 | 应对 |
|---|---|
| 数据质量差（编码不统一、Excel 数据脏） | 一期投入数据治理子模块；物料主数据归一是前置条件 |
| 偶发消耗备件预测天然不准 | 备件类采用 Croston/SBA 模型 + 安全库存兜底，输出置信区间而非点值 |
| LLM 幻觉 | 数值全部来自算法引擎；LLM 回答需引用数据来源 |
| 多源系统集成协调成本 | 优先库表直连只读账号；API 不通时用 Excel 模板过渡 |

## 5. 部署架构（双方案）
- **公有云方案**：Docker Compose/K8s + 云数据库 + 云端 LLM API
- **私有化方案**：客户内网 Docker Compose 起步 + 内网 MySQL/Redis + LLM 路由（私有化 Qwen 或国产 API 出口网关）
- 两者共用同一镜像与配置体系，仅环境配置不同

## 6. 验收记录
- 日期：2026-09-08
- 性能：100,000 条合成数据同步 0.074 秒，批量预测 5.891 秒；测试查询通过 API fixture 验证
- 安全：环境变量注入 LLM 密钥，敏感字段递归脱敏，SQL 白名单/只读/100 行限制，JWT、签名鉴权、限流和安全响应头已测试
- 可用性：Celery 任务配置 Redis broker/backend、失败自动重试和 beat 定时任务；任务结果文件遵守 worker 生命周期约定
- 扩展性：适配器注册表、模型池、LLM provider、IM provider 和 SSO provider 均可替换
- 部署：Compose 配置校验通过；Python 3.11 基础镜像首次拉取受网络限制，完整 Compose 启动未在当前环境完成
- 残余风险：真实 MySQL/Redis/worker/beat 启动验收受 Docker Hub 下载阻塞；真实 LLM、OIDC/LDAP/CAS 和 IM webhook 需填入环境变量后联调；生产监控尚需部署配置。
- 生产化修复：业务数据库读写、Celery runner、迁移入口、MySQL/Redis healthcheck 和环境变量配置已落地；完整 Compose 启动仍待镜像网络恢复。

## 部署验收补充（2026-09-08）

- 运行基线为 `backend/Dockerfile` 中的 Python 3.13。
- 使用迁移重试和 aiomysql 兼容连接池配置后，`docker compose -f docker-compose.yml -f docker-compose.host.yml up -d` 已在本机完成。
- 已验证 MySQL 8.4、Redis 7、API、Celery worker/beat、前端、Prometheus、Grafana、Alertmanager 全部运行。
- 已验证 Prometheus `liku-api` target 为 up、规则已加载、Grafana 数据源和 dashboard 自动配置成功、Alertmanager ready。
- 已验证 `liku_database_ready{database="primary"}=1` 和 `liku_redis_ready{redis="broker"}=1`。
- 残余风险限定为甲方外部凭据和真实 LLM/IM/SSO 联调。
