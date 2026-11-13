# GLOBAL DEAL HUNTER — 全球羊毛情报中心 · 数据流水线

这个仓库是情报中心的数据后端。Muse 侧边栏里的 Space 页面每次打开时，
直接从这里读取最新数据（经 jsDelixir CDN），不需要 Muse 这边跑任何定时任务。

## 数据流

```
GitHub Actions（每 2 小时，GitHub 自己的服务器上跑）
  → collect.py 抓取 RSS/Atom + 检查官方定价页变动 + 过期归档
  → 提交 deals.json / seen.json / archive.json / last_run.json
  → 刷新 jsDelivr 缓存
  → Space 页面打开时拉取最新 deals.json 展示
```

## 数据接口（Space 页面读取）

- https://cdn.jsdelivr.net/gh/renshui0017/deal-hunter@main/deals.json
- https://cdn.jsdelivr.net/gh/renshui0017/deal-hunter@main/last_run.json

## 文件说明

| 文件 | 作用 |
| --- | --- |
| `collect.py` | 采集器：抓源、分类、去重、提取截止日期、过期归档、页面变动检测、链接轮查 |
| `sources.json` | 监控源清单（RSS + 官方页面 watchlist），改这里就能加源，不用改代码 |
| `deals.json` | 当前优惠数据库（Space 直接读取） |
| `seen.json` | 已见过的链接（去重用） |
| `archive.json` | 已过期活动档案 |
| `last_run.json` | 最近一次运行报告：各源状态、新发现、过期数、页面变动、链接检查 |
| `watchlist_state.json` | 官方页面内容哈希（变动检测用） |
| `.github/workflows/collect.yml` | 每 2 小时定时任务 |

## 诚实边界（请勿夸大）

- 采集器**没有 AI**：它只能按关键词分类、按正则提取日期。所有自动采集的
  条目默认状态都是 `unverified`（待核实），只有人工核实过的才是 `active`。
- `value_score` 是关键词启发式估算，不是真实价值评估。
- v1 的 RSS 源很少（几个 Reddit 板块 + 一个 GitHub releases 源），因为大多数
  优惠聚合站没有公开 RSS 或会封爬虫。想加源就改 `sources.json`。
- Reddit 等源可能返回 403，失败会记在 `last_run.json` 里，不会悄悄丢掉。
- 每次运行都会提交一次（含心跳时间戳），所以仓库保持活跃，GitHub 不会
  因 60 天无活动而停用定时任务。

## 本地测试

```bash
pip install feedparser requests
python collect.py
```
