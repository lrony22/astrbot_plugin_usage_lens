"""Read Magpie's gateway usage summaries and preserve its pricing results."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx

CN_TIME = timezone(timedelta(hours=8))
TOKEN_FIELDS = ("input_other", "input_cached", "cache_write", "output")


def normalize_totals(item: dict) -> dict:
    """Map Magpie totals, chart points, and model groups to report fields.

    Args:
        item: A Magpie summary, series point, or model group.

    Returns:
        Token counters and Magpie's USD estimate without repricing.
    """
    return {
        "runs": int(item.get("calls", 0)),
        "input_other": int(item.get("input", 0)),
        "input_cached": int(item.get("cache_read", 0)),
        "cache_write": int(item.get("cache_write", 0)),
        "cache_unknown": int(item.get("cache_unknown", 0)),
        "output": int(item.get("output", 0)),
        "cost": Decimal(str(item.get("cost", 0))),
        "unpriced_runs": int(item.get("unpriced", 0)),
    }


async def collect_usage(
    base_url: str,
    api_key: str,
    days: int = 1,
    timeout: float = 15,
    now: datetime | None = None,
) -> dict:
    """Fetch a Magpie summary and collect its daily chart points.

    Args:
        base_url: Magpie gateway root URL, without a /v1 suffix.
        api_key: Gateway API key; empty for a local unauthenticated gateway.
        days: Calendar day count including today, from 1 to 30.
        timeout: HTTP timeout in seconds.
        now: Optional timezone-aware report time for deterministic callers.

    Returns:
        Magpie's daily and model totals with its USD cost estimates.

    Raises:
        ValueError: If the period, URL, or API response is invalid.
        httpx.HTTPError: If the gateway is unavailable or refuses the request.
    """
    if not 1 <= days <= 30:
        raise ValueError("查询天数须为 1–30。")
    if not base_url.startswith(("http://", "https://")):
        raise ValueError("请配置 Magpie 网关根地址，例如 http://127.0.0.1:3425。")
    now = now or datetime.now(CN_TIME)
    period = {1: "today", 7: "7d", 30: "30d"}.get(days)
    if period is None:
        start = now.astimezone(CN_TIME).date() - timedelta(days=days - 1)
        period = f"{start.isoformat()}..{now.astimezone(CN_TIME):%Y-%m-%d}"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    async with httpx.AsyncClient(
        base_url=base_url.rstrip("/"),
        headers=headers,
        timeout=timeout,
        trust_env=False,
    ) as client:
        response = await client.get("/v1/magpie/usage", params={"period": period})
        response.raise_for_status()
        payload = response.json()
    required = {
        "since",
        "calls",
        "input",
        "output",
        "cache_read",
        "cache_write",
        "cost",
        "unpriced",
        "series",
        "models",
    }
    if (
        not isinstance(payload, dict)
        or not required.issubset(payload)
        or not isinstance(payload["series"], list)
        or not isinstance(payload["models"], list)
    ):
        raise ValueError("Magpie 用量接口返回的数据不完整，请检查网关地址和版本。")

    start = datetime.fromisoformat(payload["since"].replace("Z", "+00:00"))
    if start.tzinfo is None:
        raise ValueError("Magpie 用量接口没有提供统计时区。")
    now = now.astimezone(start.tzinfo)
    offset = start.strftime("%z")
    zone = f"UTC{offset[:3]}:{offset[3:]}"
    daily = [
        {
            "date": (start.date() + timedelta(days=index)).isoformat(),
            **normalize_totals({}),
        }
        for index in range(days)
    ]
    by_date = {day["date"]: day for day in daily}
    # Today can be returned in hourly buckets; fold them into the same day.
    for point in payload["series"]:
        date = (
            datetime.fromisoformat(point["time"].replace("Z", "+00:00"))
            .astimezone(start.tzinfo)
            .date()
            .isoformat()
        )
        if date in by_date:
            for field, value in normalize_totals(point).items():
                by_date[date][field] += value

    models = [
        {
            "provider_id": item.get("provider", ""),
            "model": item.get("model") or item.get("id", "未知模型"),
            **normalize_totals(item),
        }
        for item in payload["models"]
    ]
    return {
        "daily": daily,
        "models": sorted(
            models,
            key=lambda item: sum(item[field] for field in TOKEN_FIELDS),
            reverse=True,
        ),
        "totals": normalize_totals(payload),
        "scope": "Magpie 全局",
        "timezone": zone,
        "period": f"{start:%m-%d} 至 {now:%m-%d %H:%M}（Magpie 时区 {zone}）",
    }


def format_report(report: dict, trend: bool = False) -> str:
    """Format Magpie's token usage, weighted cache rate, and USD estimate.

    Args:
        report: Aggregated data returned by collect_usage.
        trend: Whether to include daily rows instead of model details.

    Returns:
        A platform-neutral Chinese text report naming Magpie as its source.
    """
    totals = report["totals"]
    input_tokens = (
        totals["input_other"] + totals["input_cached"] + totals["cache_write"]
    )
    known_input = max(0, input_tokens - totals["cache_unknown"])
    cache_rate = f"{totals['input_cached'] / known_input:.1%}" if known_input else "—"
    lines = [
        f"用量透镜 · {report['scope']}",
        report["period"],
        f"调用次数：{totals['runs']:,}",
        f"Token（Magpie 口径，不含缓存）：{totals['input_other'] + totals['output']:,}",
        f"含缓存总 Token：{input_tokens + totals['output']:,}",
        f"输入：{input_tokens:,}（未缓存 {totals['input_other']:,}）",
        f"缓存读取：{totals['input_cached']:,} / 写入：{totals['cache_write']:,}",
        f"输出：{totals['output']:,}",
        f"缓存命中率：{cache_rate}",
    ]
    priced_runs = totals["runs"] - totals["unpriced_runs"]
    if priced_runs:
        label = "已定价部分费用估算" if totals["unpriced_runs"] else "费用估算"
        lines.append(f"{label}（Magpie）：USD {totals['cost']:.6f}")
    else:
        lines.append("费用估算：Magpie 暂无已定价数据")
    if totals["unpriced_runs"]:
        lines.append(f"Magpie 未定价：{totals['unpriced_runs']:,} 次调用。")
    if totals["cache_unknown"]:
        lines.append("缓存状态未知的输入已从命中率分母中排除。")
    if not totals["runs"]:
        lines.append("Magpie 本时段暂无用量记录。")

    if trend:
        lines.extend(["", "每日趋势（含缓存 Token / 缓存命中率 / 美元估算）"])
        maximum = max(
            sum(day[field] for field in TOKEN_FIELDS) for day in report["daily"]
        )
        for day in report["daily"]:
            count = sum(day[field] for field in TOKEN_FIELDS)
            bar = "█" * max(1, round(count / maximum * 10)) if count else "·"
            known_input = max(
                0,
                day["input_other"]
                + day["input_cached"]
                + day["cache_write"]
                - day["cache_unknown"],
            )
            hit = f"{day['input_cached'] / known_input:.0%}" if known_input else "—"
            cost = (
                f"USD {day['cost']:.6f}"
                if day["runs"] > day["unpriced_runs"]
                else "未定价"
                if day["runs"]
                else "—"
            )
            if day["unpriced_runs"] and day["runs"] > day["unpriced_runs"]:
                cost += "（部分）"
            lines.append(f"{day['date'][5:]} {bar} {count:,} / {hit} / {cost}")
    elif report["models"]:
        lines.extend(["", "模型用量（前 8 项，Token 含缓存）"])
        for model in report["models"][:8]:
            count = sum(model[field] for field in TOKEN_FIELDS)
            cost = "未定价" if model["unpriced_runs"] else f"USD {model['cost']:.6f}"
            lines.append(
                f"{model['provider_id']} · {model['model']}\n"
                f"  {model['runs']:,} 次 / {count:,} Token / {cost}"
            )
    return "\n".join(lines)
