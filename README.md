# GlueKettle-01 · 骨巷熬胶坊

一排熬锅作业台。登录后是横向锅位，点锅登记煮胶峰值并改状态。前端是原生 JS，没有 React/Vue/Svelte。

## 技术栈

| 层 | 技术 |
| --- | --- |
| Web API | Starlette 路由表（不是 FastAPI Depends） |
| 结构 | SQLModel 实体 + `domain.py` 门槛 |
| 数据 | SQLModel / SQLAlchemy · psycopg2 · PostgreSQL 15 |
| 前端 | 原生 ES Module · Vite 仅打包 |
| 部署 | Docker Compose |

## 路径与端口

- 前端：http://localhost:4790
- API：http://localhost:8790
- PostgreSQL：localhost:6190

## 演示账号

`admin` / `123456`，`worker` / `123456`

## 业务规则

- **出胶**：锅不可标「已出胶」，除非最近一次煮胶峰值 **≥ 90℃**。火候差不拦出胶。规则在 `backend/app/domain.py`。
- **开火（冷锅 → 熬煮中）**：只与相邻锅位（`bench ± 1`）中正在熬煮的锅比最近峰值；与任一邻锅差的绝对值 **> 12℃** 则中文挡住，没有相邻熬煮锅则不比。
- **并发开火**：`SELECT … FOR UPDATE` 行锁 + 锁内状态复核 + 条件 `UPDATE … WHERE status=旧值` 双重闸门，并落「开火台账」(`boil_start`)；同锅并发抢交只许一笔入库，重复一笔返回 409。
- **火候台**：顶栏「火候台」为只读专页（`GET /api/heat`），按坊列出各锅峰值与相邻熬煮锅差值。

## 快速启动

```bash
cd GlueKettle/GlueKettle-01
docker compose up --build
```
