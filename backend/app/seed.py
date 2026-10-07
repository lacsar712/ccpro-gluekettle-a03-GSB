from sqlmodel import select

from app.db import get_session
from app.models import CookLog, Kettle, User, Workshop
from app.security import hash_password

DEMO_CODES = {"熬煮锅", "冷锅甲", "冷锅乙"}

# 一口熬煮中峰值 96，冷锅甲最近峰值 100，冷锅乙最近峰值 118
LAYOUT = [
    ("熬煮锅", Kettle.STATUS_BOILING, 0, 96.0),
    ("冷锅甲", Kettle.STATUS_COLD, 1, 100.0),
    ("冷锅乙", Kettle.STATUS_COLD, 2, 118.0),
]


def ensure_users(session) -> None:
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


def seed_demo() -> None:
    with get_session() as session:
        ensure_users(session)
        existing = set(session.exec(select(Kettle.code)).all())
        if DEMO_CODES & existing:
            # 已是演示布局，保留运行中登记的数据
            session.commit()
            return
        # 旧布局（或空库）：清掉重排成演示三口锅
        for cook in session.exec(select(CookLog)).all():
            session.delete(cook)
        for kettle in session.exec(select(Kettle)).all():
            session.delete(kettle)
        for shop in session.exec(select(Workshop)).all():
            session.delete(shop)
        session.flush()
        shop = Workshop(name="骨巷熬胶坊", alley="西市骨巷")
        session.add(shop)
        session.flush()
        for code, status, bench, peak in LAYOUT:
            kettle = Kettle(workshop_id=shop.id, code=code, status=status, bench=bench)
            session.add(kettle)
            session.flush()
            session.add(CookLog(kettle_id=kettle.id, peak_temp_c=peak, operator="worker"))
        session.commit()
