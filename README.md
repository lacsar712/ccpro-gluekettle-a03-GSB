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

- 前端：http://localhost:4850
- API：http://localhost:8850
- PostgreSQL：localhost:6250

## 演示账号

`admin` / `123456`，`worker` / `123456`

## 演示种子

一口「熬煮锅」熬煮中（峰值 96℃），「冷锅甲」冷锅（最近峰值 100℃），「冷锅乙」冷锅（最近峰值 118℃）。

## 业务规则

规则在 `backend/app/domain.py`：

- 锅不可标「已出胶」，除非最近一次煮胶峰值 **≥ 90℃**。火候差不拦出胶。
- 坊内已有熬煮锅时，改「熬煮中」须与邻熬煮锅的最近峰值比差：**差值 > 12℃ 中文挡住**；没有邻熬煮锅则不比。
- 两人同时抢改同一锅为「熬煮中」只许一笔入库：状态接口 `SELECT ... FOR UPDATE` 行锁串行，后到者看到已变更返回 409。

## 页面

- **锅位作业台**：横向锅位，点锅登记峰值、改状态，被挡的规则以中文提示。
- **火候台**：只读专页，按坊列出各锅最近峰值与对邻熬煮锅的差值。顶栏在两页间切换。

## 快速启动

```bash
docker compose up --build
```
