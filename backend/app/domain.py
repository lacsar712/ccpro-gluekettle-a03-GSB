"""熬锅门槛规则。

- 出胶（drawn）：最近一次煮胶峰值须 ≥ 90℃。火候差不得拦出胶。
- 开火（cold → boiling）：只与相邻锅位（bench ± 1）中正在熬煮的锅比峰值，
  与任一邻锅最近峰值差的绝对值大于 12℃ 则挡住；没有相邻熬煮锅则不比。
"""

from app.models import Kettle

MIN_PEAK = 90.0
MAX_NEIGHBOR_PEAK_GAP = 12.0


class RuleError(ValueError):
    pass


def latest_peak(kettle: Kettle) -> float | None:
    if not kettle.cooks:
        return None
    latest = max(kettle.cooks, key=lambda c: c.taken_at)
    return latest.peak_temp_c


def boiling_neighbors(kettle: Kettle, kettles: list[Kettle]) -> list[Kettle]:
    """同坊、相邻锅位（bench ± 1）且正在熬煮中的锅。"""
    return [
        k
        for k in kettles
        if k.id != kettle.id
        and k.workshop_id == kettle.workshop_id
        and k.status == Kettle.STATUS_BOILING
        and abs(k.bench - kettle.bench) == 1
    ]


def assert_can_start_boiling(kettle: Kettle, kettles: list[Kettle]) -> None:
    """冷锅 → 熬煮中 的邻锅火候差门槛。已经在熬煮中的锅不在此处判。"""
    peers = boiling_neighbors(kettle, kettles)
    if not peers:
        # 没有相邻熬煮锅则不比
        return
    peak = latest_peak(kettle)
    if peak is None:
        raise RuleError("该锅尚无煮胶峰值，无法与邻锅比对火候，不能开火")
    for peer in peers:
        peer_peak = latest_peak(peer)
        if peer_peak is None:
            continue
        gap = abs(peak - peer_peak)
        if gap > MAX_NEIGHBOR_PEAK_GAP:
            raise RuleError(
                f"与邻锅「{peer.code}」火候差 {gap:g}℃"
                f"（本锅峰值 {peak:g}℃、邻锅 {peer_peak:g}℃，阈值 {MAX_NEIGHBOR_PEAK_GAP:g}℃），不能开火"
            )


def assert_can_set_status(
    kettle: Kettle, new_status: str, kettles: list[Kettle] | None = None
) -> None:
    allowed = {Kettle.STATUS_COLD, Kettle.STATUS_BOILING, Kettle.STATUS_DRAWN}
    if new_status not in allowed:
        raise RuleError(f"无效状态：{new_status}")

    if new_status == Kettle.STATUS_DRAWN:
        # 出胶只认峰值 ≥ 90℃，不看邻锅火候差
        peak = latest_peak(kettle)
        if peak is None:
            raise RuleError("该锅尚无煮胶峰值，不能出胶")
        if peak < MIN_PEAK:
            raise RuleError(f"最近峰值 {peak}℃ 低于 {MIN_PEAK:.0f}℃，不能出胶")
        return

    if new_status == Kettle.STATUS_BOILING and kettle.status != Kettle.STATUS_BOILING:
        assert_can_start_boiling(kettle, kettles or [kettle])
