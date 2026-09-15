# 本机监控

Compose 启动后提供：

- Prometheus：`http://localhost:9090`
- Grafana：`http://localhost:3000`，默认账号由 `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD` 注入
- Alertmanager：`http://localhost:9093`
- 应用指标：`http://localhost:8000/metrics`

应用只负责暴露 Prometheus 指标和数据库就绪状态；告警规则、路由和通知渠道由监控部署层配置，便于后续接入企业微信、钉钉、邮件或现有告警平台。

首次登录 Grafana 后会自动加载“平衡利库运行概览”仪表盘。生产环境请通过环境变量修改默认管理员密码，并在 Alertmanager 配置中增加实际通知接收器。

## 本机已验收

生产化本机栈已验证 MySQL 8.4、Redis 7、Prometheus 3.5、Grafana 12.1、Alertmanager 0.28。API readiness 和三个监控服务的 readiness 均返回 HTTP 200，Prometheus 的 `liku-api` target 为 up。

使用 `docker-compose.local.yml` 可运行 SQLite 演示；宿主机 8000 被占用时，将 `docker-compose.yml` 与 `docker-compose.host.yml` 合并启动 MySQL 栈。
