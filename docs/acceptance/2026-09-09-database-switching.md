# 数据库切换验收

日期：2026-09-09

实现方式：管理员配置数据库档案，保存后重启 API、worker、beat 生效；不在线替换运行中的 SQLAlchemy 连接池，避免事务中断。

支持类型：

- SQLite：`sqlite+aiosqlite://`
- MySQL 8：`mysql+aiomysql://`
- PostgreSQL：`postgresql+asyncpg://`
- 达梦 DM：`dm+dmPython://` 或目标环境安装的 `asyncdm` 驱动 URL

接口：

- `GET /api/v1/admin/database`：管理员查看当前数据库类型、脱敏连接串和支持档案。
- `POST /api/v1/admin/database/switch`：管理员保存目标数据库类型和连接串，返回重启提示。

串行验收：

- `admin/admin` 登录成功，`GET /admin/database` 返回当前 `mysql` 和脱敏密码。
- 支持档案返回 SQLite、MySQL、PostgreSQL、达梦四种类型。
- 使用 MySQL 类型提交 PostgreSQL 连接串被正确拒绝。
- `asyncpg 0.30.0` 已包含在后端镜像。
- 前端增加管理员菜单“数据库连接”，连接密码不从服务端回显。

残余风险：达梦专有驱动属于客户环境依赖，不直接打入通用镜像；切换前必须确认目标库已建表、账号具备迁移权限，并重启所有 API/worker/beat 实例。
