from sqlmodel import select

from app.db import get_session
from app.models import BoilStart, CookLog, Kettle, User, Workshop
from app.security import hash_password

# 唯一一口熬煮中「沸口」峰值 96，夹在冷锅甲(100)与冷锅乙(118)之间：
#   甲与沸口差 4（≤12）可开火；乙与沸口差 22（>12）始终被挡。
# 丙、丁周边无相邻熬煮锅，开火不比；其峰值 <90，出胶仍被九十门槛挡住。
LAYOUT = [
    ("冷锅甲", Kettle.STATUS_COLD, 0, 100.0),
    ("沸口", Kettle.STATUS_BOILING, 1, 96.0),
    ("冷锅乙", Kettle.STATUS_COLD, 2, 118.0),
    ("冷锅丙", Kettle.STATUS_COLD, 3, 70.0),
    ("冷锅丁", Kettle.STATUS_COLD, 4, 85.0),
    ("胶锅戊", Kettle.STATUS_DRAWN, 5, 94.0),
]
REQUIRED_CODES = {code for code, _, _, _ in LAYOUT}


def _build_layout(session, shop: Workshop) -> None:
    for code, status, bench, peak in LAYOUT:
        kettle = Kettle(workshop_id=shop.id, code=code, status=status, bench=bench)
        session.add(kettle)
        session.flush()
        if peak is not None:
            session.add(CookLog(kettle_id=kettle.id, peak_temp_c=peak, operator="worker"))


def _reset_workshop_kettles(session, shop: Workshop) -> None:
    """把一个坊的锅位清掉重建为 A03 布局（一次性迁移旧快照用）。"""
    old = session.exec(select(Kettle).where(Kettle.workshop_id == shop.id)).all()
    for k in old:
        for log in session.exec(select(CookLog).where(CookLog.kettle_id == k.id)).all():
            session.delete(log)
        for start in session.exec(select(BoilStart).where(BoilStart.kettle_id == k.id)).all():
            session.delete(start)
        session.delete(k)
    session.flush()
    _build_layout(session, shop)


def seed_demo() -> None:
    with get_session() as session:
        admin = session.exec(select(User).where(User.username == "admin")).first()
        if admin is None:
            session.add(User(username="admin", password_hash=hash_password("123456"), role="admin"))
        else:
            admin.password_hash = hash_password("123456")
            admin.role = "admin"
        worker = session.exec(select(User).where(User.username == "worker")).first()
        if worker is None:
            session.add(User(username="worker", password_hash=hash_password("123456"), role="worker"))
        else:
            worker.password_hash = hash_password("123456")
            worker.role = "worker"

        shop = session.exec(select(Workshop)).first()
        if shop is None:
            shop = Workshop(name="骨巷熬胶坊", alley="西市骨巷")
            session.add(shop)
            session.flush()
            _build_layout(session, shop)
            session.commit()
            return

        codes = {k.code for k in session.exec(select(Kettle).where(Kettle.workshop_id == shop.id)).all()}
        if not codes:
            _build_layout(session, shop)
        elif not REQUIRED_CODES.issubset(codes):
            # 旧快照（锅-1… 或缺失关键锅）残留于已命名数据卷：迁移一次。
            _reset_workshop_kettles(session, shop)
        session.commit()
