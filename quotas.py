"""Read Magpie account allowances and render their reset clocks."""

from datetime import datetime
from math import isfinite

import httpx

from .stats import CN_TIME


async def collect_quotas(
    base_url: str, api_key: str, timeout: float = 15
) -> list[dict]:
    """Fetch the account, subscription, and wallet cards from Magpie.

    Args:
        base_url: Magpie gateway root URL, without a /v1 suffix.
        api_key: Existing Magpie gateway key.
        timeout: HTTP timeout in seconds.

    Returns:
        Account quota cards returned by Magpie.

    Raises:
        ValueError: If the URL or response structure is invalid.
        httpx.HTTPError: If the gateway is unavailable or refuses access.
    """
    if not base_url.startswith(("http://", "https://")):
        raise ValueError("请配置 Magpie 网关根地址，例如 http://127.0.0.1:3425。")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    async with httpx.AsyncClient(
        base_url=base_url.rstrip("/"),
        headers=headers,
        timeout=timeout,
        trust_env=False,
    ) as client:
        response = await client.get("/v1/magpie/quotas")
        response.raise_for_status()
        payload = response.json()
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("data"), list)
        or any(not isinstance(item, dict) for item in payload["data"])
    ):
        raise ValueError("Magpie 额度接口返回的数据不完整，请检查网关地址和版本。")
    return payload["data"]


def format_quotas(
    accounts: list[dict], keyword: str = "", now: datetime | None = None
) -> str:
    """Format per-account windows with percentages and Beijing reset times.

    Args:
        accounts: Magpie account, subscription, or wallet cards.
        keyword: Optional case-insensitive provider or account substring.
        now: Optional timezone-aware time for deterministic countdowns.

    Returns:
        A Chinese account report with masked email addresses.
    """
    now = (now or datetime.now(CN_TIME)).astimezone(CN_TIME)
    query = keyword.strip().casefold()
    selected = [
        item
        for item in accounts
        if not query
        or any(
            query in str(item.get(field, "")).casefold()
            for field in ("provider", "name", "user", "alias", "plan")
        )
    ]
    lines = [
        f"Magpie 账号额度 · {len(selected)} 项",
        f"查询时间：{now:%m-%d %H:%M:%S}（北京时间）",
    ]
    if not selected:
        lines.append(
            "未找到匹配账号，请使用 /额度 查看全部。"
            if query
            else "Magpie 暂无可查询的账号额度。"
        )
        return "\n".join(lines)

    for index, account in enumerate(selected, 1):
        name = str(
            account.get("alias")
            or account.get("name")
            or account.get("provider")
            or "未知账号"
        )
        user = str(account.get("user") or "")
        # Account names can also be email addresses; mask both displayed fields.
        labels = []
        for value in (name, user):
            if "@" in value:
                local, domain = value.rsplit("@", 1)
                value = f"{local[:2]}***@{domain}"
            if value and value not in labels:
                labels.append(value)
        plan = account.get("plan")
        title = f"{index}. {' · '.join(labels)}"
        if plan:
            title += f" [{plan}]"
        lines.extend(["", title])
        if account.get("balance"):
            lines.append(f"账户余额：{account['balance']}")
        if account.get("error"):
            lines.append("状态：账号额度读取失败，请在 Magpie 中查看详情。")
        if account.get("readDeferred"):
            lines.append("状态：Magpie 暂缓刷新，显示上次读数。")

        windows = account.get("windows") or []
        for window in windows:
            raw_name = str(window.get("name") or "额度窗口")
            name = {"5 hours": "5 小时", "7 days": "7 天", "Month": "月度"}.get(
                raw_name, raw_name
            )
            used = window.get("used")
            remaining = window.get("remaining")
            balance = window.get("balance")
            unit = str(window.get("unit") or "")
            if window.get("unlimited"):
                status = "剩余不限额｜已用比例不适用"
            elif balance is not None:
                status = f"剩余 {balance:g} {unit}｜已用比例未提供"
            elif window.get("text"):
                status = f"额度 {window.get('display') or '未提供'}｜已用比例未提供"
            else:
                used_known = isinstance(used, (int, float)) and isfinite(used)
                remaining_known = isinstance(remaining, (int, float)) and isfinite(
                    remaining
                )
                if used_known and not remaining_known:
                    remaining, remaining_known = max(0, 100 - used), True
                if remaining_known and not used_known:
                    used, used_known = max(0, 100 - remaining), True
                status = (
                    f"剩余 {remaining:g}%" if remaining_known else "剩余比例未提供"
                ) + (f"｜已用 {used:g}%" if used_known else "｜已用比例未提供")
                limit = window.get("limit")
                amount = window.get("amount", 0)
                if (
                    isinstance(limit, (int, float))
                    and limit > 0
                    and isinstance(amount, (int, float))
                ):
                    status += f"（剩余 {max(0, limit - amount):g}/{limit:g} {unit}）"
                elif window.get("display"):
                    status += f"（{window['display']}）"
            lines.append(f"{name}：{status}")

            reset = window.get("resetsAt")
            if reset:
                try:
                    reset_at = datetime.fromisoformat(str(reset).replace("Z", "+00:00"))
                    if reset_at.tzinfo is None:
                        raise ValueError("Reset time has no timezone")
                    reset_at = reset_at.astimezone(CN_TIME)
                    seconds = int((reset_at - now).total_seconds())
                    if seconds <= 0:
                        countdown = "时间已到，待 Magpie 更新"
                    else:
                        minutes = (seconds + 59) // 60
                        days, minutes = divmod(minutes, 1440)
                        hours, minutes = divmod(minutes, 60)
                        countdown = (
                            (f"{days}天" if days else "")
                            + (f"{hours}小时" if hours else "")
                            + (f"{minutes}分钟" if minutes else "")
                            + "后"
                        )
                    lines.append(f"  重置：{reset_at:%m-%d %H:%M:%S}（{countdown}）")
                except ValueError:
                    lines.append("  重置：时间格式无法识别")
            else:
                lines.append("  重置：未提供")
        if not windows and not account.get("balance"):
            lines.append("剩余额度和已用比例：Magpie 未提供。")

        read_at = account.get("asOf") or account.get("readAt")
        if read_at:
            try:
                stamp = datetime.fromisoformat(str(read_at).replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    raise ValueError("Read time has no timezone")
                label = "历史读数" if account.get("asOf") else "额度读取"
                lines.append(f"{label}：{stamp.astimezone(CN_TIME):%m-%d %H:%M:%S}")
            except ValueError:
                pass
    return "\n".join(lines)
