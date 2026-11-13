# 用量透镜 · Magpie Usage Lens

独立安装在 AstrBot 中的 Magpie 用量查询插件。数据来自 Magpie 网关 `GET /v1/magpie/usage`，包括其记录的全部 Agent 和模型。费用沿用 Magpie 自己的模型价格、缓存计费和分时计费结果，金额单位为 USD。

支持账号额度查询，直接读取 `GET /v1/magpie/quotas`，展示各账号及额度窗口的剩余比例、已用比例、重置时间和读取时间。

支持 AstrBot 内置插件可视化看板。进入 **插件 → 用量透镜 → Magpie 用量看板**，也可从左侧扩展功能打开。聊天命令同时可用。

## 可视化看板

- 各账号额度卡片：独立窗口进度条、剩余与已用比例、重置时间及倒计时，展开查看全部窗口。
- 今天、近 7 天、近 30 天用量，费用、调用次数、含缓存 Token 和缓存命中率。
- 可切换 Token / 费用的交互趋势，模型费用分布和可搜索模型明细。
- 手动刷新、每分钟自动更新、账号搜索，跟随 AstrBot 深浅主题并适配窄屏。

页面使用 `views/overview/` 和 AstrBot 自动注入的 `AstrBotPluginView` bridge。网关密钥保留在后端；可视化接口验证 Dashboard 管理员身份，返回显示所需字段并遮罩账号邮箱。无需独立启动 Web 服务。

## 安装与升级

在 AstrBot 的 **插件管理 → 从链接安装** 中填写：

```text
https://github.com/lrony22/astrbot_plugin_usage_lens
```

也可下载 [源码 ZIP](https://github.com/lrony22/astrbot_plugin_usage_lens/archive/refs/heads/main.zip) 后上传安装。更新时使用插件管理中的更新按钮，保留原有配置。

需要 AstrBot >= 4.29.4 且 < 5，安装版本须提供内置插件页面和 `astrbot.api.web` API；Magpie 须提供 `/v1/magpie/usage` 和 `/v1/magpie/quotas`。使用 AstrBot 已有的 HTTPX 和 Pillow 依赖，无需额外服务或前端构建。

查询范围统一为 Magpie 全局，用量和额度命令均要求 AstrBot 管理员。`/用量 7 全局` 等写法也可用。

## 配置

| 配置 | 默认 | 说明 |
| --- | --- | --- |
| `magpie_url` | `http://127.0.0.1:3425` | 网关根地址，不带 `/v1` |
| `magpie_api_key` | `magpie` | 网关密钥，配置面板遮罩显示 |
| `timeout_seconds` | `15` | 请求超时秒数 |

Magpie 和 AstrBot 在同一台电脑时默认配置即可。AstrBot 在 Docker 中运行时，需要填写它实际能访问的 Magpie 主机地址。连接远程 Magpie 时，使用已开启共享的网关和允许读取全局用量的密钥；受模型、账号或预算限制的密钥可能无法读取全局汇总。

费用直接显示接口返回的 USD 估算。

## 命令

| 命令 | 功能 |
| --- | --- |
| `/用量` | Magpie 今日调用次数、Token、缓存命中率、费用及模型排行 |
| `/用量 7` | Magpie 近 7 个自然日汇总 |
| `/用量 30` | Magpie 近 30 个自然日汇总 |
| `/用量趋势` | Magpie 近 7 天堆叠柱状图和每日明细 |
| `/额度` | 全部账号的剩余额度、已用比例、重置时间 |
| `/额度 codex` | 筛选厂商或账号关键词，也可用账号名称、邮箱片段 |
| `/用量帮助` | 查看说明 |

英文别名为 `/usage`、`/usage_trend`、`/usage_help`。天数支持 1–30，也可填写 `今天`、`7天`、`30天`。

额度命令另有 `/账号额度`、`/magpie_quota` 别名，均仅限 AstrBot 管理员。账号邮箱在输出中遮罩显示；筛选使用原始账号字段。

## 账号额度

- 逐个展示 Magpie 返回的账号和窗口，例如 5 小时、7 天、月度和模型专属额度，不将不同窗口合并成一个比例。
- 重置时间统一转换为北京时间，并显示剩余时间；已到期的时间标注等待 Magpie 更新。
- 供应商返回积分上限及用量时显示实际剩余数量；钱包余额、仅文字额度和不限额窗口分别展示，不将其默认百分比当成真实使用比例。
- `readAt` 表示额度实际读取时间，`asOf` 表示历史读数；查询错误与历史读数会明确显示。缺失字段标为未提供。
- 使用现有网关地址和密钥，无需额外配置。查询只读取额度，不切换账号、不使用额度重置次数。
- 账号查询出错时仅显示固定提示，错误原文留在 Magpie 中查看，避免将其中的个人信息或凭证转发到聊天和看板。

## 统计口径

- 预设的今天、7 天和 30 天按 Magpie 服务器本地自然日统计，并展示接口时区。其他天数根据北京时间日期构建 Magpie 自定义日期范围。
- Magpie 的 `input` 不包含缓存读取和缓存写入。报告同时展示其原有的非缓存 Token 口径，以及加上缓存读写的总 Token；趋势图采用含缓存总量。
- 缓存命中率 = 缓存读取 ÷（未缓存输入 + 缓存读取 + 缓存写入 − 缓存状态未知的输入）。未知部分按 Magpie 返回值排除；分母为零显示 `—`。
- 直接使用 Magpie 返回的 `cost`，不再次计算模型单价。未定价次数按 `unpriced` 展示。订阅模型的标价折算也属于估算金额。
- 无记录日期补零；今天截至查询时刻。图例依次为未缓存输入、缓存读取、缓存写入、输出。
- 接口拒绝访问、超时或断开连接时返回连接错误，不使用本机统计替代。
- 查询只读用量接口，不调用模型。趋势 PNG 在本机 AstrBot 临时目录生成。

接口及字段依据：[Magpie 网关用量接口](https://github.com/yetone/magpie/blob/main/internal/gateway/usage_api.go)、[用量字段和费用定义](https://github.com/yetone/magpie/blob/main/internal/usage/usage.go)。

## 开源许可

作者：[lrony22](https://github.com/lrony22)。本插件以 [AGPL-3.0](LICENSE) 发布。
