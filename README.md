# 个人数据权利请求处理系统

标准库实现的跨地区数据访问、更正、删除、撤回同意和限制处理请求后台，使用 SQLite 保存案件、数据位置、时限和审计时间线。

## 运行

要求 Python 3.11+（当前 Python 3.9 环境亦可）。

```bash
python3 app.py --init --seed
python3 app.py
```

默认地址 `http://127.0.0.1:8210`，数据库默认 `privacy_requests.db`。可用 `--db`、`--host`、`--port` 修改。

## 主要接口

使用 `X-User`、`X-Role` 请求头。角色有 `intake`、`privacy_officer`、`supervisor`、`auditor`。

- `GET /health`、`GET /api/state`、`GET /api/queue`、`GET /api/requests/{id}`
- `POST /api/jurisdictions`：配置处理时限、延期上限、未成年人和代理规则
- `POST /api/subjects`：保存不含明文联系方式的索引
- `POST /api/requests`：创建权利请求，支持幂等键和30天重复请求识别
- `POST /api/requests/verify`、`POST /api/requests/assign`
- `POST /api/locations`、`POST /api/locations/classify`：多系统定位和第三方/保留分类
- `POST /api/requests/extend`、`POST /api/requests/prepare`
- `POST /api/requests/fulfill`、`POST /api/requests/reject`
- `POST /api/requests/withdraw`：申请人或代理说明原因撤回请求
- `POST /api/requests/withdraw/review`：主管复核撤回申请

## 撤回流程

申请人或代理说明原因后登记撤回：尚未准备回复（received/verifying/processing）的案件直接关闭为 `withdrawn`；已准备回复（response_ready）或延期中（extended）的案件先进入 `withdrawal_pending`，由主管复核，通过后关闭，驳回则恢复原状态继续办理。撤回只改状态，原请求、处理人和数据位置全部保留，不再占用待办队列；同一主体再次提交同类请求时，已撤回的案件不参与重复判定。请求详情返回关闭原因（`withdrawal_reason`）、复核人（`withdrawal_reviewed_by`）和可重新申请状态（`can_reapply`）。

## 测试

```bash
python3 -m unittest discover -s tests -v
```

测试覆盖完整查阅请求、第三方遮蔽、未成年人/代理限制、重复与幂等、延期上限、删除法律保留、权限拒绝、版本冲突和撤回复核。

## 局限

身份依赖请求头，联系方式只存哈希；请求正文、证据文件和实际回复文件未实现加密存储；地区规则是可配置模板，不构成法律意见；删除是流程判定，不会自动调用外部业务系统执行清除。
