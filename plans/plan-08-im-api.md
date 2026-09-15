# Plan 08 · F9 IM 机器人 + 系统嵌入

> 对应 PRD 3.9　|　里程碑：M3 用户触点

## 1. 目标
将产品能力延伸到企业 IM 与现有业务系统，覆盖非登录场景使用。

## 2. 需求
- **IM 机器人**（企业微信/钉钉/飞书均适配，实施时按甲方使用平台接入）：
  - 预警推送（接 Plan 05）
  - 自然语言问答（接 Plan 06）
  - 定时日报
- **统一认证**：支持标准 SSO 协议（OAuth2/OIDC/LDAP/CAS），同时内置账号体系兜底
- **开放 API**：供 ERP/物资系统嵌入查询与建议接口

## 3. 技术方案
- IM 适配层：统一消息抽象（发送文本/卡片/图表）+ 企微/钉钉/飞书三平台实现，回调消息统一入口转 Chatbot
- 认证中间件：OIDC/OAuth2 资源服务器模式 + LDAP/CAS 适配 + 内置账号（JWT）
- 开放 API：独立版本化路由（/api/v1/open/...），AppKey/AppSecret 签名鉴权，限流
- API 文档自动生成（FastAPI OpenAPI）

## 4. 任务清单
- [x] IM 消息抽象层 + 企微适配器
- [x] 钉钉适配器、飞书适配器
- [x] 机器人回调 → Chatbot 接入
- [x] 预警/日报推送任务
- [x] SSO：OAuth2/OIDC 对接
- [x] LDAP/CAS 适配
- [x] 内置账号体系（用户/角色/组织管理）
- [x] 开放 API 网关（签名鉴权、限流、版本化）
- [x] 开放 API 文档

## 5. 验收标准
- 三平台 IM 机器人收发消息、推送预警/日报可用
- SSO 登录与内置账号登录均可进入 Web 应用
- 第三方系统可通过开放 API 查询库存与建议

## 6. 验收记录
- 日期：2026-09-08
- 测试：后端 51 项通过；统一 IM provider、三平台回调、日报、SSO fixture、开放 API 签名与限流均有测试
- 证据：开放路由统一挂在 `/api/v1/open/...`，签名包含 AppKey、时间戳和密钥，过期请求拒绝；FastAPI 自动生成 OpenAPI 文档
- 风险：真实 IM webhook、OIDC/LDAP/CAS 服务需实施阶段注入地址和凭据；当前 provider 使用本地可替换实现
- 生产化修复：配置 webhook 时使用真实 HTTP provider；OIDC 校验 issuer/audience/JWKS，LDAP/CAS 使用远端验证接口；未配置时拒绝登录，不再接受任意 token。
