# 平衡利库智能体

平衡利库智能体用于物料库存查询、AI 平衡分析、采购建议、库存健康度、预测、价格分析、风险预警和 Chatbot。生产数据通过 `jimu_erp` 适配器以只读方式访问积木 ERP，不在业务流程中生成 W1-W4 或其他模拟仓库数据。

## 当前运行入口

| 用途 | 地址 |
| --- | --- |
| Docker/Vite 前端 | `http://localhost:5173` |
| 宿主机回退前端 | `http://127.0.0.1:5177` |
| Docker API | `http://localhost:18000` |
| 宿主机回退 API | `http://127.0.0.1:18001` |
| API 文档 | `http://localhost:18000/docs` 或 `http://127.0.0.1:18001/docs` |

`agent2` 使用独立端口，请勿使用本项目的启动命令修改或停止它。

## 配置

复制 `.env.example` 为 `.env`，填写 ERP 只读连接信息：

```dotenv
ERP_DB_HOST=172.20.0.114
ERP_DB_PORT=3306
ERP_DB_USER=php_saas
ERP_DB_PASSWORD=<只读账号密码>
ERP_DB_NAME=php_saas
ERP_SITE_ID=PHP
DEMO_SEED=false
```

后端通过适配器 SPI 注册 `jimu_erp`。适配器只执行查询，不提供写入 ERP 的接口。可用以下接口检查状态：

```text
GET /api/v1/erp/adapter-status
GET /api/v1/warehouses
```

## 启动方式

### Docker 模式

适用于 Docker 可以访问 ERP，或已经在 Windows 宿主机配置了 `13306 -> 172.20.0.114:3306` 的端口转发：

```powershell
docker compose -p agent -f docker-compose.local.yml up -d --force-recreate
```

启动后打开 `http://localhost:5173`。Docker 后端使用 SQLite 本地缓存和 Redis，`DEMO_SEED=false` 时不会写入演示数据。

### ERP 内网不可由 Docker 访问时

Windows 宿主机通常可以直接访问 ERP，此时使用宿主机回退栈：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-host.ps1
```

脚本会启动 API `18001` 和前端 `5177`。Docker 前端 `5173` 的 API 地址也指向 `18001`，因此宿主机回退后端启动后两个前端入口都可以使用。检查：

```powershell
Invoke-RestMethod http://127.0.0.1:18001/api/v1/health/ready
Invoke-RestMethod http://127.0.0.1:18001/api/v1/erp/adapter-status
```

ERP 状态应返回 `name=jimu_erp`、`read_only=true` 和 `ok=true`。若 `ok=false`，先检查 ERP 网络、账号密码和端口，不要用模拟数据替代。

## 停止与重启

只重启 `agent`：

```powershell
docker compose -p agent -f docker-compose.local.yml restart backend frontend worker beat
```

重建前端或后端镜像后：

```powershell
docker compose -p agent -f docker-compose.local.yml up -d --build --force-recreate
```

宿主机回退进程可在任务管理器中结束对应的 `python.exe` 和 `node.exe` 后再次运行 `scripts/start-host.ps1`。不要执行 `docker compose down -v`，该命令会删除 Compose volume 中的本地数据库和监控数据。

## 验证

```powershell
docker compose -p agent -f docker-compose.local.yml ps
docker compose -p agent -f docker-compose.local.yml logs --tail=100 backend frontend
```

后端测试和前端测试：

```powershell
docker compose -p agent -f docker-compose.local.yml run --rm backend pytest tests
cd frontend
npm run build
npm test -- --run
```

监控服务需要显式启用：

```powershell
docker compose -p agent -f docker-compose.local.yml --profile monitoring up -d
```
