from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from sqlalchemy import update as sa_update
from sqlalchemy.orm import selectinload
from sqlmodel import SQLModel, select

from app.db import engine, get_session
from app.domain import (
    MAX_NEIGHBOR_PEAK_GAP,
    RuleError,
    assert_can_set_status,
    boiling_neighbors,
    latest_peak,
)
from app.models import BoilStart, CookLog, Kettle, User, Workshop
from app.security import make_token, parse_token, verify_password
from app.seed import seed_demo


async def current_user(request: Request) -> User | None:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    username = parse_token(header.split(" ", 1)[1])
    if not username:
        return None
    with get_session() as session:
        return session.exec(select(User).where(User.username == username)).first()


def load_kettle(session, kettle_id: int) -> Kettle | None:
    return session.exec(
        select(Kettle).where(Kettle.id == kettle_id).options(selectinload(Kettle.cooks))
    ).first()


def load_workshop_kettles(session, workshop_id: int) -> list[Kettle]:
    kettles = session.exec(
        select(Kettle)
        .where(Kettle.workshop_id == workshop_id)
        .options(selectinload(Kettle.cooks))
    ).all()
    return sorted(kettles, key=lambda k: k.bench)


def neighbor_gap_json(kettle: Kettle, kettles: list[Kettle]) -> list[dict]:
    """本锅与相邻熬煮锅的峰值差（供抽屉与火候台画数字）。本锅无峰值则不可比。"""
    gaps = []
    peak = latest_peak(kettle)
    if peak is None:
        return gaps
    for peer in boiling_neighbors(kettle, kettles):
        peer_peak = latest_peak(peer)
        if peer_peak is None:
            continue
        gap = abs(peak - peer_peak)
        gaps.append(
            {
                "neighborCode": peer.code,
                "neighborPeakC": peer_peak,
                "gap": round(gap, 10),
                "overLimit": gap > MAX_NEIGHBOR_PEAK_GAP,
            }
        )
    return gaps


def kettle_json(kettle: Kettle, kettles: list[Kettle] | None = None) -> dict:
    return {
        "id": kettle.id,
        "code": kettle.code,
        "status": kettle.status,
        "bench": kettle.bench,
        "workshopId": kettle.workshop_id,
        "latestPeakC": latest_peak(kettle),
        "cookCount": len(kettle.cooks or []),
        "neighborGaps": neighbor_gap_json(kettle, kettles or [kettle]),
    }


async def health(request: Request):
    return JSONResponse({"status": "ok", "service": "GlueKettle"})


async def login(request: Request):
    body = await request.json()
    with get_session() as session:
        user = session.exec(select(User).where(User.username == body.get("username", ""))).first()
        if user is None or not verify_password(body.get("password", ""), user.password_hash):
            return JSONResponse({"detail": "用户名或密码错误"}, status_code=401)
        return JSONResponse(
            {"access_token": make_token(user.username), "user": {"username": user.username, "role": user.role}}
        )


async def me(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    return JSONResponse({"username": user.username, "role": user.role})


async def board(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    with get_session() as session:
        shop = session.exec(select(Workshop)).first()
        if shop is None:
            return JSONResponse({"detail": "尚无熬胶坊"}, status_code=404)
        kettles = load_workshop_kettles(session, shop.id)
        return JSONResponse(
            {
                "workshop": shop.name,
                "alley": shop.alley,
                "kettles": [kettle_json(k, kettles) for k in kettles],
            }
        )


async def heat(request: Request):
    """火候台：只读专页数据，按坊列出各锅峰值与相邻熬煮锅差值。"""
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    with get_session() as session:
        shops = session.exec(select(Workshop).order_by(Workshop.id)).all()
        workshops = []
        for shop in shops:
            kettles = load_workshop_kettles(session, shop.id)
            workshops.append(
                {
                    "workshop": shop.name,
                    "alley": shop.alley,
                    "kettles": [
                        {
                            "code": k.code,
                            "status": k.status,
                            "bench": k.bench,
                            "latestPeakC": latest_peak(k),
                            "neighborGaps": neighbor_gap_json(k, kettles),
                        }
                        for k in kettles
                    ],
                }
            )
        return JSONResponse({"workshops": workshops})


async def add_cook(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    kettle_id = int(request.path_params["kettle_id"])
    body = await request.json()
    try:
        peak = float(body.get("peakTempC"))
    except (TypeError, ValueError):
        return JSONResponse({"detail": "峰值温度必须是数字"}, status_code=400)
    with get_session() as session:
        kettle = load_kettle(session, kettle_id)
        if kettle is None:
            return JSONResponse({"detail": "锅不存在"}, status_code=404)
        session.add(CookLog(kettle_id=kettle.id, peak_temp_c=peak, operator=user.username))
        session.commit()
        kettle = load_kettle(session, kettle_id)
        kettles = load_workshop_kettles(session, kettle.workshop_id)
        return JSONResponse(kettle_json(kettle, kettles))


def change_status(session, kettle_id: int, new_status: str, username: str) -> tuple[int, dict]:
    """状态变更核心（同步，可在一个事务/连接内调用）。

    并发开火两道保险：先 SELECT … FOR UPDATE 锁锅位行，再用条件
    UPDATE … WHERE status = 旧值 做原子闸门，命中行数非 1 即拒绝。
    """
    # 先锁锅位行（PostgreSQL SELECT … FOR UPDATE），并发抢交在此串行化。
    # 只取标量列，避免 selectinload 与 FOR UPDATE 不兼容。
    locked = session.exec(
        select(Kettle.id, Kettle.status)
        .where(Kettle.id == kettle_id)
        .with_for_update()
    ).first()
    if locked is None:
        return 404, {"detail": "锅不存在"}
    _, status_under_lock = locked

    kettle = load_kettle(session, kettle_id)
    kettles = load_workshop_kettles(session, kettle.workshop_id)

    # 锁内复核：已经在熬煮中，说明已有一笔开火入库，挡下重复抢交。
    if new_status == Kettle.STATUS_BOILING and status_under_lock == Kettle.STATUS_BOILING:
        return 409, {"detail": "该锅已在熬煮中，开火登记重复，本次未入库"}

    try:
        assert_can_set_status(kettle, new_status, kettles)
    except RuleError as exc:
        return 400, {"detail": str(exc)}

    # 原子闸门：仅当状态仍是锁内读到的旧值时才改状态。
    # 并发抢交时第二笔命中 0 行（FOR UPDATE 行锁先到先改），被拒绝。
    result = session.execute(
        sa_update(Kettle)
        .where(Kettle.id == kettle.id, Kettle.status == status_under_lock)
        .values(status=new_status)
    )
    if result.rowcount != 1:
        session.rollback()
        return 409, {"detail": "锅位状态已被他人更新，本次提交未入库"}

    # 开火台账：每次进入熬煮中落一笔，行锁 + 条件更新保证同锅并发只落一笔。
    if new_status == Kettle.STATUS_BOILING:
        session.add(
            BoilStart(
                kettle_id=kettle.id,
                operator=username,
                peak_temp_c=latest_peak(kettle),
            )
        )
    session.commit()
    kettle = load_kettle(session, kettle_id)
    kettles = load_workshop_kettles(session, kettle.workshop_id)
    return 200, kettle_json(kettle, kettles)


async def set_status(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    kettle_id = int(request.path_params["kettle_id"])
    body = await request.json()
    session = get_session()
    try:
        code, payload = change_status(session, kettle_id, body.get("status", ""), user.username)
        return JSONResponse(payload, status_code=code)
    finally:
        session.close()


def init() -> None:
    SQLModel.metadata.create_all(engine)
    seed_demo()


init()

app = Starlette(
    routes=[
        Route("/api/health", health),
        Route("/api/auth/login", login, methods=["POST"]),
        Route("/api/auth/me", me),
        Route("/api/board", board),
        Route("/api/heat", heat),
        Route("/api/kettles/{kettle_id:int}/cooks", add_cook, methods=["POST"]),
        Route("/api/kettles/{kettle_id:int}/status", set_status, methods=["POST"]),
    ],
    middleware=[Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])],
)
