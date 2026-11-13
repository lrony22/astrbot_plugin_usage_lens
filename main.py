"""Chat commands for Magpie gateway usage reports."""

import asyncio
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import httpx

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
from astrbot.api.web import error_response, json_response, request
from astrbot.core.utils.astrbot_path import get_astrbot_temp_path

from .chart import render_trend
from .quotas import collect_quotas, format_quotas
from .stats import CN_TIME, collect_usage, format_report

HELP = """用量透镜 · Usage Lens
/用量 [天数] — Magpie Token、缓存命中率、费用和模型排行
/用量趋势 — Magpie 近 7 个自然日趋势图与每日明细
/额度 [账号或厂商关键词] — 各账号剩余额度、已用比例和重置时间
/用量帮助 — 查看帮助
例：/用量、/用量 7、/用量趋势、/额度、/额度 codex
数据来自 Magpie 网关，覆盖其全部 Agent；用量和额度查询仅限 AstrBot 管理员。
天数支持 1–30，也可填写 今天、7天、30天。
费用直接使用 Magpie 返回的美元估算。
缓存命中率 = 缓存读取 ÷ 全部已知缓存状态的输入。"""


class UsageLens(Star):
    """Expose read-only usage reports from Magpie's gateway API."""

    def __init__(self, context: Context, config: AstrBotConfig):
        """Store dashboard-managed gateway connection settings.

        Args:
            context: Active AstrBot runtime.
            config: Magpie gateway URL, API key, and timeout settings.
        """
        super().__init__(context)
        self.config = config

    async def initialize(self):
        """Register authenticated endpoints used by the built-in plugin view."""
        for path, handler, description in (
            ("usage", self.page_usage, "Read Magpie usage dashboard"),
            ("quotas", self.page_quotas, "Read Magpie account allowances"),
        ):
            self.context.register_web_api(
                f"/astrbot_plugin_usage_lens/{path}", handler, ["GET"], description
            )

    async def page_usage(self):
        """Return usage data to the authenticated dashboard administrator.

        Returns:
            A usage report or a public validation or connection error.
        """
        admin = self.context.get_config().get("dashboard", {}).get("username")
        if not request.username or request.username != admin:
            return error_response(
                "仅 AstrBot 管理员可查看 Magpie 用量。", status_code=403
            )
        try:
            report = await collect_usage(
                str(self.config.get("magpie_url", "http://127.0.0.1:3425")).strip(),
                str(self.config.get("magpie_api_key", "magpie")).strip(),
                days=int(request.query.get("days", "7")),
                timeout=float(self.config.get("timeout_seconds", 15)),
            )
        except ValueError:
            return error_response("无法读取用量，请检查查询天数及 Magpie 配置。")
        except httpx.HTTPError:
            return error_response(
                "连接 Magpie 用量接口失败，请检查网关地址和密钥。", status_code=502
            )
        return json_response(
            {"report": report, "updated_at": datetime.now(CN_TIME).isoformat()},
            headers={"Cache-Control": "no-store"},
        )

    async def page_quotas(self):
        """Return only displayable allowance fields, with masked account emails.

        Returns:
            Account cards or a public connection error.
        """
        admin = self.context.get_config().get("dashboard", {}).get("username")
        if not request.username or request.username != admin:
            return error_response(
                "仅 AstrBot 管理员可查看 Magpie 账号额度。", status_code=403
            )
        try:
            accounts = await collect_quotas(
                str(self.config.get("magpie_url", "http://127.0.0.1:3425")).strip(),
                str(self.config.get("magpie_api_key", "magpie")).strip(),
                timeout=float(self.config.get("timeout_seconds", 15)),
            )
        except ValueError:
            return error_response("无法读取账号额度，请检查 Magpie 配置。")
        except httpx.HTTPError:
            return error_response(
                "连接 Magpie 额度接口失败，请检查网关地址和密钥。", status_code=502
            )
        cards = []
        for account in accounts:
            card = {
                field: account[field]
                for field in (
                    "provider",
                    "name",
                    "alias",
                    "user",
                    "plan",
                    "balance",
                    "asOf",
                    "readAt",
                    "readDeferred",
                )
                if field in account
            }
            if account.get("error"):
                card["error"] = "账号额度读取失败，请在 Magpie 中查看详情。"
            for field in ("name", "alias", "user"):
                value = str(card.get(field) or "")
                if "@" in value:
                    local, domain = value.rsplit("@", 1)
                    card[field] = f"{local[:2]}***@{domain}"
            card["windows"] = [
                {
                    field: window[field]
                    for field in (
                        "name",
                        "used",
                        "remaining",
                        "resetsAt",
                        "display",
                        "text",
                        "amount",
                        "limit",
                        "unit",
                        "pool",
                        "balance",
                        "unlimited",
                    )
                    if field in window
                }
                for window in account.get("windows", [])
            ]
            cards.append(card)
        return json_response(
            {"accounts": cards, "updated_at": datetime.now(CN_TIME).isoformat()},
            headers={"Cache-Control": "no-store"},
        )

    @filter.command("用量", alias={"usage"})
    async def usage(
        self, event: AstrMessageEvent, days: str = "1", scope: str = "全局"
    ):
        """Show usage totals and estimated costs for a calendar period.

        Args:
            event: Incoming chat command.
            days: Calendar day count or a supported Chinese period label.
            scope: Optional global scope retained for existing commands.
        """
        if days in {"全局", "global"}:
            days, scope = "1", "全局"
        period = {"今天": "1", "7天": "7", "30天": "30"}.get(days, days)
        try:
            count = int(period)
        except ValueError:
            yield event.plain_result("天数须为 1–30，例如 /用量 7。\n" + HELP)
            return
        async for result in self.send_report(event, count, scope):
            yield result

    @filter.command("用量趋势", alias={"usage_trend"})
    async def trend(self, event: AstrMessageEvent, scope: str = "全局"):
        """Show seven local calendar days as text and a stacked bar chart.

        Args:
            event: Incoming chat command.
            scope: Optional global scope retained for existing commands.
        """
        async for result in self.send_report(event, 7, scope, trend=True):
            yield result

    @filter.command("用量帮助", alias={"usage_help"})
    async def help(self, event: AstrMessageEvent):
        """Show available commands and the Magpie data source.

        Args:
            event: Incoming chat command.
        """
        yield event.plain_result(HELP)

    @filter.command("额度", alias={"账号额度", "magpie_quota"})
    async def quotas(self, event: AstrMessageEvent, keyword: str = ""):
        """Show account quota windows, remaining amounts, and reset clocks.

        Args:
            event: Incoming chat command and permission context.
            keyword: Optional account or provider substring.
        """
        if not event.is_admin():
            yield event.plain_result("Magpie 账号额度仅限 AstrBot 管理员查询。")
            return
        try:
            accounts = await collect_quotas(
                base_url=str(
                    self.config.get("magpie_url", "http://127.0.0.1:3425")
                ).strip(),
                api_key=str(self.config.get("magpie_api_key", "magpie")).strip(),
                timeout=float(self.config.get("timeout_seconds", 15)),
            )
            text = format_quotas(accounts, keyword)
        except ValueError as exc:
            yield event.plain_result(str(exc))
            return
        except httpx.TimeoutException:
            yield event.plain_result("读取 Magpie 账号额度超时，请稍后重试。")
            return
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in {401, 403}:
                text = "Magpie 拒绝访问，请检查网关密钥的额度读取权限。"
            elif status == 404:
                text = "Magpie 额度接口不存在，请检查网关根地址及 Magpie 版本。"
            else:
                text = f"Magpie 额度接口返回 HTTP {status}。"
        except httpx.RequestError:
            text = "连接 Magpie 失败，请检查插件中的网关地址。"
        except Exception:
            logger.exception("Usage Lens failed to read Magpie account quotas")
            text = "读取 Magpie 账号额度失败，请查看插件日志。"
        yield event.plain_result(text)

    async def send_report(
        self, event: AstrMessageEvent, days: int, scope: str, trend: bool = False
    ):
        """Check administrator access, query Magpie, and deliver a report.

        Args:
            event: Incoming chat command and permission context.
            days: Number of local calendar days to include.
            scope: Optional global scope name.
            trend: Whether to render a seven-day trend image.
        """
        if not event.is_admin():
            yield event.plain_result("Magpie 用量仅限 AstrBot 管理员查询。")
            return
        if scope not in {"全局", "global"}:
            yield event.plain_result(
                "当前数据源为 Magpie 全局用量，请使用 /用量 或 /用量 7。"
            )
            return
        try:
            report = await collect_usage(
                base_url=str(
                    self.config.get("magpie_url", "http://127.0.0.1:3425")
                ).strip(),
                api_key=str(self.config.get("magpie_api_key", "magpie")).strip(),
                days=days,
                timeout=float(self.config.get("timeout_seconds", 15)),
            )
        except ValueError as exc:
            yield event.plain_result(str(exc))
            return
        except httpx.TimeoutException:
            yield event.plain_result("读取 Magpie 用量超时，请确认网关正在运行。")
            return
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in {401, 403}:
                message = "Magpie 拒绝访问，请检查网关密钥和用量读取权限。"
            elif status == 404:
                message = "Magpie 用量接口不存在，请检查网关根地址及 Magpie 版本。"
            else:
                message = f"Magpie 用量接口返回 HTTP {status}。"
            yield event.plain_result(message)
            return
        except httpx.RequestError:
            yield event.plain_result("连接 Magpie 失败，请检查插件中的网关地址。")
            return
        except Exception:
            logger.exception("Usage Lens failed to read Magpie usage")
            yield event.plain_result("读取 Magpie 用量失败，请查看插件日志。")
            return

        yield event.plain_result(format_report(report, trend))
        if trend:
            output = (
                Path(get_astrbot_temp_path())
                / "usage_lens"
                / f"trend-{uuid4().hex}.png"
            )
            try:
                await asyncio.to_thread(render_trend, report, output)
                yield event.image_result(str(output))
            except Exception:
                logger.exception("Usage Lens failed to render the trend chart")
