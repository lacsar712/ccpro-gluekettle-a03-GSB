from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from sqlalchemy.orm import selectinload
from sqlmodel import SQLModel, select

from app.db import engine, get_session
from app.domain import STATUS_LABELS, RuleError, assert_can_set_status, heat_diff, latest_peak
from app.models import CookLog, Kettle, User, Workshop
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


def kettle_json(kettle: Kettle) -> dict:
    return {
        "id": kettle.id,
        "code": kettle.code,
        "status": kettle.status,
        "bench": kettle.bench,
        "latestPeakC": latest_peak(kettle),
        "cookCount": len(kettle.cooks or []),
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
        kettles = session.exec(
            select(Kettle)
            .where(Kettle.workshop_id == shop.id)
            .options(selectinload(Kettle.cooks))
        ).all()
        loaded = sorted(kettles, key=lambda k: k.bench)
        return JSONResponse(
            {"workshop": shop.name, "alley": shop.alley, "kettles": [kettle_json(k) for k in loaded]}
        )


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
        return JSONResponse(kettle_json(kettle))


async def set_status(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    kettle_id = int(request.path_params["kettle_id"])
    body = await request.json()
    new_status = body.get("status", "")
    with get_session() as session:
        # 行锁：两人同时抢改同一锅时串行，后到者看到最新状态
        kettle = session.exec(
            select(Kettle).where(Kettle.id == kettle_id).with_for_update()
        ).first()
        if kettle is None:
            return JSONResponse({"detail": "锅不存在"}, status_code=404)
        if kettle.status == new_status:
            label = STATUS_LABELS.get(new_status, new_status)
            return JSONResponse(
                {"detail": f"该锅已是「{label}」，可能刚被他人改过，请刷新后重试"},
                status_code=409,
            )
        peers = session.exec(
            select(Kettle)
            .where(Kettle.workshop_id == kettle.workshop_id)
            .where(Kettle.status == Kettle.STATUS_BOILING)
            .where(Kettle.id != kettle.id)
            .options(selectinload(Kettle.cooks))
        ).all()
        try:
            assert_can_set_status(kettle, new_status, peers)
        except RuleError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        kettle.status = new_status
        session.add(kettle)
        session.commit()
        kettle = load_kettle(session, kettle_id)
        return JSONResponse(kettle_json(kettle))


async def heat(request: Request):
    """火候台：只读，按坊列出各锅最近峰值与对邻熬煮锅的差值。"""
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    with get_session() as session:
        payload = []
        for shop in session.exec(select(Workshop)).all():
            kettles = session.exec(
                select(Kettle)
                .where(Kettle.workshop_id == shop.id)
                .options(selectinload(Kettle.cooks))
            ).all()
            ordered = sorted(kettles, key=lambda k: k.bench)
            peers = [k for k in ordered if k.status == Kettle.STATUS_BOILING]
            rows = []
            for k in ordered:
                peak = latest_peak(k)
                diff = None if peak is None else heat_diff(peak, peers)
                rows.append(
                    {
                        "id": k.id,
                        "code": k.code,
                        "status": k.status,
                        "bench": k.bench,
                        "latestPeakC": peak,
                        "diffC": None if diff is None else round(diff, 1),
                    }
                )
            payload.append({"workshop": shop.name, "alley": shop.alley, "kettles": rows})
        return JSONResponse({"workshops": payload})


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
