"""熬锅门槛：出胶认峰值 ≥ 90℃；改熬煮中须与邻熬煮锅峰值差 ≤ 12℃。"""

from app.models import Kettle

MIN_PEAK = 90.0
HEAT_DIFF_LIMIT = 12.0

STATUS_LABELS = {
    Kettle.STATUS_COLD: "冷锅",
    Kettle.STATUS_BOILING: "熬煮中",
    Kettle.STATUS_DRAWN: "已出胶",
}


class RuleError(ValueError):
    pass


def latest_peak(kettle: Kettle) -> float | None:
    if not kettle.cooks:
        return None
    latest = max(kettle.cooks, key=lambda c: c.taken_at)
    return latest.peak_temp_c


def heat_diff(peak: float, peers: list[Kettle]) -> float | None:
    """本锅峰值与邻熬煮锅峰值的最大差值；没有可比的邻熬煮锅则返回 None。"""
    refs = [p for k in peers if (p := latest_peak(k)) is not None]
    if not refs:
        return None
    return max(abs(peak - ref) for ref in refs)


def _fmt(value: float) -> str:
    return f"{value:g}"


def assert_can_set_status(
    kettle: Kettle,
    new_status: str,
    boiling_peers: list[Kettle] | None = None,
) -> None:
    allowed = {Kettle.STATUS_COLD, Kettle.STATUS_BOILING, Kettle.STATUS_DRAWN}
    if new_status not in allowed:
        raise RuleError(f"无效状态：{new_status}")
    if new_status == Kettle.STATUS_DRAWN:
        # 已出胶只认峰值 ≥ 90℃，火候差不拦出胶
        peak = latest_peak(kettle)
        if peak is None:
            raise RuleError("该锅尚无煮胶峰值，不能出胶")
        if peak < MIN_PEAK:
            raise RuleError(f"最近峰值 {peak}℃ 低于 {MIN_PEAK:.0f}℃，不能出胶")
        return
    if new_status == Kettle.STATUS_BOILING:
        peers = [k for k in (boiling_peers or []) if latest_peak(k) is not None]
        if not peers:
            return  # 坊内没有邻熬煮锅，不比
        peak = latest_peak(kettle)
        if peak is None:
            raise RuleError("该锅尚无煮胶峰值，无法与邻熬煮锅比火候")
        worst = max(peers, key=lambda k: abs(peak - latest_peak(k)))
        diff = abs(peak - latest_peak(worst))
        if diff > HEAT_DIFF_LIMIT:
            raise RuleError(
                f"与邻锅「{worst.code}」峰值相差 {_fmt(diff)}℃，"
                f"超过 {_fmt(HEAT_DIFF_LIMIT)}℃ 上限，不能改熬煮中"
            )
