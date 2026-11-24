# 归档项目源码审计与 Creeperman 复用边界

核查日期：2026-11-24（UTC+8）。本文件对应用户提供的项目清单，阅读 README、关键实现及依赖责任位置；固定版本如下。没有运行这些项目、来源请求、测试或部署。这里的“可复用”指机制与代码入口已经定位，不表示已经集成或通过本项目验证。

当前来源前提是 WebBase 2001 和已使用的 IA 主体来源近乎处理完。以下组件主要降低访问、解析和调度成本；来源供给问题另见[档案起源与剩余发现](ARCHIVE_ORIGINS_AND_RESIDUAL_FRONTIER.md)。

最新[发现与取证流水线](DISCOVERY_AND_VERIFICATION_PIPELINE.md)将这些复用边界落实到对象、查询计划、证据与请求预算。本文 §§8—10 补充本轮新列工具及 CDX 服务端的固定源码审计；只读源码，没有运行工具。

## 1. 先按输入输出选组件

| 任务 | 有依据的复用对象 | Creeperman 保留的责任 |
|---|---|---|
| 对已知 URL 找其他档案中的捕获 | MemGator、TimeStitch；MementoMap 辅助路由 | 年份适用性、来源祖源、真实完成状态与提供者预算 |
| 读取明确索引范围 | cdx_toolkit、pywb | 来源白名单、原始 URL、完整分页、目标年与证据规则 |
| 读取和解释原始记录 | warcio、pywb、ArchiveSpark；现有复核文档已有代码依据 | exact hostname、时间角色、revisit 与证据组合 |
| 从历史资料提取关系 | AUT、维护中的 warc-indexer；urx 的部分适配器 | 保留站外链接与原始身份，明确过滤范围，保留记录定位 |
| 保存与查询海量捕获索引 | OutbackCDX | 年度基线、证据账本、全局精确去重与 EED |
| 对大量任务分片执行 | 复用现有 Temporal 设计；借鉴 ArchiveTeam 生产流程 | 来源任务定义、就近数据、幂等结果与全局预算 |
| 消费有限 CDX 查询 | GLAM-Workbench、CreepsoOff 下载器的部分客户端机制 | exact host、缺年位图、查询范围完整性、实际 capture 与替代 witness |
| 历史文本与索引 inventory | Usenet 消费者格式适配、cdx-summarize 的时间统计 | 消息/正文版本、original 身份、原始定位及全局差集 |
| 注册信息辅助 | domaincheck / domain-check 的 RDAP 解析和路由 | 保存事件类型、缺失与错误；不作历史网站资格或年代硬排除 |
| 内容辅助分组和复核 | OTMT、wayback-discover-diff 的特征计算 | 不将主题连续性、正文相似性当成年度网站资格 |

## 2. 多档案聚合与路由

### 2.1 MemGator：静态先验排序与并发聚合

固定版本：[`oduwsdl/MemGator@6a222465b44503abe1bf80dc91109cef061a645b`](https://github.com/oduwsdl/MemGator/tree/6a222465b44503abe1bf80dc91109cef061a645b)。

实际输入是一个具体 URI-R，可附日期；输出聚合的 TimeMap/TimeGate 信息。关键实现在 [main.go](https://github.com/oduwsdl/MemGator/blob/6a222465b44503abe1bf80dc91109cef061a645b/main.go)：

- `Archive.Probability` 来自档案配置；`Archives.Less()` 降序比较，启动时排序，`aggregateTimemap()` 对选中的 top-k 并发请求。**这是静态配置先验，不是在线学习每个 URL 的命中率。**
- 网络初始化配置连接、响应头与 HTTP client 三种超时。TimeMap 走 `client.Do`，带日期 TimeGate 路径使用 `transport.RoundTrip`；不能称所有路径均受 client 总超时覆盖。
- hibernation 的 `tolerance=-1` 默认关闭；配置阈值后，网络请求错误才增加失败计数。HTTP 非成功状态与正文读取错误不等价于这个计数条件。

**采用：**档案适配、TimeMap 合并、显式选择档案、不同网络阶段预算。**补充：**按实际 provider 管理全局预算和失败类别；配置先验必须有来源依据。工具本身不枚举尚未知晓的全网 hostname。

### 2.2 TimeStitch：缓存与两类优先级

固定版本：[`lanl/TimeStitch-Memento-Aggregator@c782885a3620379694b5fcf14aecd91523677251`](https://github.com/lanl/TimeStitch-Memento-Aggregator/tree/c782885a3620379694b5fcf14aecd91523677251)。

| 主张 | 固定代码实际行为 |
|---|---|
| MySQL 缓存 | `cache/mysql/StorageImpl.java` 存取 URL、memento 日期、档案与更新时间 |
| 双队列 | README 区分即时请求和后台刷新；当前 `MyInitServlet` 创建一个 `PriorityBlockingQueue`，任务有两类优先级 |
| JSON 路由 | `CommonRuleMatcher` 读取 URL pattern 与 archives，按正则选择档案 |
| 年份路由 | 当前 matcher 没有读取规则中的 `time`；不能当作已实现的年度路由 |

关键路径：[MyInitServlet.java](https://github.com/lanl/TimeStitch-Memento-Aggregator/blob/c782885a3620379694b5fcf14aecd91523677251/agr-webapp/src/main/java/gov/lanl/agg/resource/MyInitServlet.java)、[RunMeBatchTask.java](https://github.com/lanl/TimeStitch-Memento-Aggregator/blob/c782885a3620379694b5fcf14aecd91523677251/agg-core/src/main/java/gov/lanl/agg/batch/RunMeBatchTask.java)、[CommonRuleMatcher.java](https://github.com/lanl/TimeStitch-Memento-Aggregator/blob/c782885a3620379694b5fcf14aecd91523677251/agg-core/src/main/java/gov/lanl/agg/utils/CommonRuleMatcher.java)。

可迁移的是缓存复用、即时请求优先和后台补全。当前代码使用的部分 `jobs`、`linkmaster` 字段未出现在所附 `conf/agg_tables.sql` 中，因此不能把公开代码直接描述为已验证的即用部署。其主入口同样需要 Original-URL。

### 2.3 MementoMap：覆盖画像不自动包含年份

固定版本：[`oduwsdl/MementoMap@21e37389eecfc74506339219c38e1975d9b46703`](https://github.com/oduwsdl/MementoMap/tree/21e37389eecfc74506339219c38e1975d9b46703)。

[mementomap/cli.py](https://github.com/oduwsdl/MementoMap/blob/21e37389eecfc74506339219c38e1975d9b46703/mementomap/cli.py) 的 `cdx2hxpx()` 只读取 CDX 第一列 SURT 并计频，没有解析捕获时间列；`compact()` 压缩 host/path 前缀，`lookup()` 做本地查找。

因此可直接学习批量画像查找和前缀压缩；若要路由“1998 年的这个 URL”，应先按真实捕获年划分索引，再建立 `archive × year × version` 画像或年度辅助表。普通跨年画像命中不证明目标年存在；不完整画像 miss 也不能判历史不存在。画像是路由信息，不是 exact hostname-year 的资格证据。

### 2.4 cdx_toolkit：分页与退避成立，总预算另管

固定版本：[`commoncrawl/cdx_toolkit@e87b1204993b77a4c41c03239baefa1c8462a6e1`](https://github.com/commoncrawl/cdx_toolkit/tree/e87b1204993b77a4c41c03239baefa1c8462a6e1)。

[`CDXFetcherIter`](https://github.com/commoncrawl/cdx_toolkit/blob/e87b1204993b77a4c41c03239baefa1c8462a6e1/cdx_toolkit/__init__.py) 支持分页。[myrequests.py](https://github.com/commoncrawl/cdx_toolkit/blob/e87b1204993b77a4c41c03239baefa1c8462a6e1/cdx_toolkit/myrequests.py) 对若干 HTTP 状态倍增等待、默认上限 60 秒；该分支没有套用连接错误分支的次数上限。不能将其描述为所有错误均有统一终点的重试系统。

可以复用 IA/pywb 适配和分页，外层明确总尝试数或总时限、冷却范围和查询完成状态。`CDXFetcher` 默认 `source='cc'`，本题必须显式选择 `source='ia'` 或获准来源；CLI 对应 `--ia`。复用 Common Crawl 仓库代码不等于采用其语料。

## 3. ArchiveTeam：原始档案生产与执行分工

### 3.1 terroroftinytown 的任务是短链编号区间

固定版本：[`ArchiveTeam/terroroftinytown@3cdb438e4a4adb85a73e3500a366010b324bbbfe`](https://github.com/ArchiveTeam/terroroftinytown/tree/3cdb438e4a4adb85a73e3500a366010b324bbbfe)。

它是 URLTeam 的短链归档工具。`services/base.py` 将编号转换为短码，通过响应跳转或正文规则得到目标 URL；`tracker/model.py` 分配区间并校验回传；`client/tracker.py` 调用 `/api/get`、`/api/done`、`/api/error`。

最值得迁移的是：**从来源自身可以枚举的空间产生有限任务，远端执行，中央确认结果并形成档案。**它不需要先知道所有目标域名。

其协议与数据模型围绕短链展开；Budget 的实现假定单实例，回收条件与项目配置相关。当前已读客户端协议没有通用工作流依赖、Activity 心跳或外部 manifest 协议。故用它学习生产方式，不将其当作当前 Temporal 设计的直接替换件。

具体入口：[services/base.py](https://github.com/ArchiveTeam/terroroftinytown/blob/3cdb438e4a4adb85a73e3500a366010b324bbbfe/terroroftinytown/services/base.py)、[tracker/model.py](https://github.com/ArchiveTeam/terroroftinytown/blob/3cdb438e4a4adb85a73e3500a366010b324bbbfe/terroroftinytown/tracker/model.py)、[client/tracker.py](https://github.com/ArchiveTeam/terroroftinytown/blob/3cdb438e4a4adb85a73e3500a366010b324bbbfe/terroroftinytown/client/tracker.py)。今天展开的短链仅提供今天的观察，不能自动支撑 1996—2001 的目标网站年份。

### 3.2 grab-site 的磁盘 frontier 由 wpull 承担

固定版本：[`ArchiveTeam/grab-site@0eaf88628f4d8ef5af4df4c13f594606a41de3cd`](https://github.com/ArchiveTeam/grab-site/tree/0eaf88628f4d8ef5af4df4c13f594606a41de3cd)。

grab-site 提供种子配置、动态忽略规则、WARC/CDX 输出配置和监控。`libgrabsite/main.py` 构造 `wpull.db` 参数后调用 wpull；`setup.py` 固定 `ArchiveTeam/ludios_wpull` 的 3.0.9 标签，本次解析到提交 `80c6f7d7327b0c4c4f9534d8a8f1dcef9f31badf`。

真正的 URL checkout/checkin/release 在 wpull 的 [database/sqltable.py](https://github.com/ArchiveTeam/ludios_wpull/blob/80c6f7d7327b0c4c4f9534d8a8f1dcef9f31badf/wpull/database/sqltable.py)，启动时回收未完成状态在 [application/tasks/database.py](https://github.com/ArchiveTeam/ludios_wpull/blob/80c6f7d7327b0c4c4f9534d8a8f1dcef9f31badf/wpull/application/tasks/database.py)。这是本地持久 frontier 的恢复，不是 dashboard 实现了全球派发。默认站外链接跟随深度也有范围限制。

可迁移的是保留 URL 状态、抓取边界、陷阱控制及原始响应。全球任务与本地 URL 队列分别管理；把当前活站重新抓进 WARC 不会产生早年证据。

## 4. OSINT 工具的适配价值与信息损失

### 4.1 urx：适合学习适配器，不宜原样作为证据库存

固定版本：[`hahwul/urx@9eddc9dbc7b2fb70c3add47f01a55a8b7de90cd3`](https://github.com/hahwul/urx/tree/9eddc9dbc7b2fb70c3add47f01a55a8b7de90cd3)。多来源、SQLite/Redis、正文回放及提取都是真实实现，但有下列本题关键边界：

| 位置 | 固定实现 | 必要适配 |
|---|---|---|
| `src/cli/mod.rs` | 默认 providers 为 `wayback,cc,otx` | 显式来源白名单，排除 CC |
| `src/app/pipeline.rs` | 默认 strict 的 host 过滤也用于正文提取；path scope 另行生效 | 历史跨站发现保留精确站外目标；不以基线根域扩枚子域 |
| `src/providers/wayback.rs`、`record.rs` | 查询含 `collapse=urlkey&sort=reverse`；同 URL 捕获合并成 first/last、最近状态等摘要 | 年度证据保留实际捕获序列及身份；不由区间填年 |
| `src/cache/types.rs`、`app/caching.rs` | 缓存 URL 清单、缓存时间与 baseline 标记；命中时不恢复捕获元数据 | 查询缓存与捕获证据分开；缓存写入时间不是历史日期 |
| `src/testers/archive_body.rs` | timestamp 可来自不同来源，实际正文回放固定为 Wayback | 按真实来源取记录；核实返回捕获时间，不能沿用请求时间 |
| `src/testers/body_archive.rs` | 正文文件名由 URL 决定，覆盖写文件，同时追加索引 | 用捕获身份或不可变对象命名，保留不同年份原件 |
| `src/readers/warc_reader.rs` | 扫描 `WARC-Target-URI:` 等文本行提取 URL | 正式证据读取复用记录级 WARC 解析器，关联时间/响应/正文 |

`--incremental` 比较的是 URL 字符串集合；已有 URL 的新增年份或正文不一定成为新 URL。`--archive-body` 遇到缓存命中也可能缺少可回放的捕获元数据。这些默认值服务于其资产枚举目标，不能直接代表 Creeperman 的资料处理进度、年度差集或证据完成状态。

`archive_body.rs::reserve` 还会在 digest 已被领取时跳过整个 URL。迁移时可按 digest 复用正文下载或特征计算，但要保留每个捕获的原始 URL、年份和来源，按相应 base 解释相对链接，分别记录观察及展开状态；仅修正落盘文件名不能修复这一提前跳过。

关键源码：[pipeline.rs](https://github.com/hahwul/urx/blob/9eddc9dbc7b2fb70c3add47f01a55a8b7de90cd3/src/app/pipeline.rs)、[record.rs](https://github.com/hahwul/urx/blob/9eddc9dbc7b2fb70c3add47f01a55a8b7de90cd3/src/providers/record.rs)、[cache/types.rs](https://github.com/hahwul/urx/blob/9eddc9dbc7b2fb70c3add47f01a55a8b7de90cd3/src/cache/types.rs)、[archive_body.rs](https://github.com/hahwul/urx/blob/9eddc9dbc7b2fb70c3add47f01a55a8b7de90cd3/src/testers/archive_body.rs)、[body_archive.rs](https://github.com/hahwul/urx/blob/9eddc9dbc7b2fb70c3add47f01a55a8b7de90cd3/src/testers/body_archive.rs)。

### 4.2 waybackwhen：按工具限流不等于按提供者限流

固定版本：[`DFC302/waybackwhen@a5af4a16c64fd655ea961eb05d6e429b866c5614`](https://github.com/DFC302/waybackwhen/tree/a5af4a16c64fd655ea961eb05d6e429b866c5614)，实现主要在 [waybackwhen](https://github.com/DFC302/waybackwhen/blob/a5af4a16c64fd655ea961eb05d6e429b866c5614/waybackwhen)。

它包装多个 URL 枚举工具并合并文本。默认空结果重入队一次，最多两轮，并非无限重试；注释所称指数退避实际按 `base × attempt` 增长。archive-lane 默认关闭；启用后只约束其中三类工具，其他工具仍可能请求相同档案后端。

任何来源产生结果便可结束“全空重排”，所以合并结果非空不证明所有来源完成。子进程与 FIFO 领取也没有统一总超时；这是从代码推导的阻塞风险，没有在本轮执行验证。

可学习有界重试与入口并发的思路；实际实现应按真实 provider 管预算，并保存每个来源的完成状态。它的合并 URL 文件不承担证据状态或全局配额职责。

## 5. 规范化、图谱与索引

### 5.1 SURT 默认会改变本题的 hostname 身份

固定版本：[`internetarchive/surt@45587ad855053dfce6612a534cbaaa835f88450e`](https://github.com/internetarchive/surt/tree/45587ad855053dfce6612a534cbaaa835f88450e)。

默认 `surt()` 使用 `DefaultIAURLCanonicalizer`，其 [IAURLCanonicalizer.py](https://github.com/internetarchive/surt/blob/45587ad855053dfce6612a534cbaaa835f88450e/surt/IAURLCanonicalizer.py) 默认 `host_massage=True`；`massageHost()` 删除开头匹配 `www\d*\.` 的部分，包括 www、www2 等。可显式改变配置，但已经归并的键不能可靠逆推出原始形式。

SURT 用作检索、路由和排序；竞赛身份从 original URL 提取。不能直接用默认 SURT 对裸域、www 与子域计数。

### 5.2 cc-webgraph 的 PLD 是分析投影

固定版本：[`commoncrawl/cc-webgraph@8a3a34e2f3bc16b865ee234eab83a4917086b814`](https://github.com/commoncrawl/cc-webgraph/tree/8a3a34e2f3bc16b865ee234eab83a4917086b814)。

[HostToDomainGraph.java](https://github.com/commoncrawl/cc-webgraph/blob/8a3a34e2f3bc16b865ee234eab83a4917086b814/src/main/java/org/commoncrawl/webgraph/HostToDomainGraph.java) 支持 registered-domain、private-domain、host-without-www 等映射；这些操作会归并节点与边。可以学习倒序标签、排序、映射和图处理；PLD 图不能替代 exact hostname 年表。

host 图生产脚本还调用 `cc-pyspark` 的代码，本次没有据此声称已经审完全部上游规范化。Common Crawl 数据仍被排除，算法复用不改变此约束。

### 5.3 OutbackCDX 是可读写的捕获索引

旧 `nla/outbackcdx` 已重定向到 [`iipc/outbackcdx@07978e1544ae15b4947c306ee7b08b0055cd0278`](https://github.com/iipc/outbackcdx/tree/07978e1544ae15b4947c306ee7b08b0055cd0278)。

[Webapp.java](https://github.com/iipc/outbackcdx/blob/07978e1544ae15b4947c306ee7b08b0055cd0278/src/outbackcdx/Webapp.java) 支持查询、写入和删除；secondary 默认只读，不能把整个产品称作只读索引。[Capture.java](https://github.com/iipc/outbackcdx/blob/07978e1544ae15b4947c306ee7b08b0055cd0278/src/outbackcdx/Capture.java) 保留 original 并重建检索键；[UrlCanonicalizer.java](https://github.com/iipc/outbackcdx/blob/07978e1544ae15b4947c306ee7b08b0055cd0278/src/outbackcdx/UrlCanonicalizer.java) 默认也删除 www 类前缀。

它可用于 CDX 增量索引、查询和复制，不自带 ARC/WARC→CDX 索引器，也不包含本题的年度基线和 EED。身份仍从 original 读取；alias 或 canonical 命中不说明两种 hostname 在竞赛里相同。

## 6. WARC 内容抽取与维护入口

### 6.1 webarchive-discovery 的 warc-indexer 已有新维护入口

固定版本：[`ukwa/webarchive-discovery@2eb4f08257d31f64faab7d5a4e8f19bad5ca1fdf`](https://github.com/ukwa/webarchive-discovery/tree/2eb4f08257d31f64faab7d5a4e8f19bad5ca1fdf)。README 明确将 **warc-indexer** 支持与维护转到 [netarchivesuite/warc-indexer](https://github.com/netarchivesuite/warc-indexer)，旧目录留作参考。迁移范围是该组件，不能扩大为整个 UKWA 仓库。

可复用已有内容索引和提取方式；如后续选用该组件，应在新维护入口固定版本。本轮没有进一步审计新仓库或执行安装。

### 6.2 AUT raw webgraph 也有明确筛选条件

固定版本：[`archivesunleashed/aut@57c9b5ed167f97c9ea5e08ebd1a4a958c6da1818`](https://github.com/archivesunleashed/aut/tree/57c9b5ed167f97c9ea5e08ebd1a4a958c6da1818)。

实际 `.webgraph()` 在 [package.scala](https://github.com/archivesunleashed/aut/blob/57c9b5ed167f97c9ea5e08ebd1a4a958c6da1818/src/main/scala/io/archivesunleashed/package.scala)，输出 `crawl_date, src, dest, anchor`。它先筛 200 与 HTML 类页面，再由 [ExtractLinks.scala](https://github.com/archivesunleashed/aut/blob/57c9b5ed167f97c9ea5e08ebd1a4a958c6da1818/src/main/scala/io/archivesunleashed/matchbox/ExtractLinks.scala) 解析 `<a href>`。这不是全部记录类型或全部引用种类的无损展开。

日期属于源页捕获；四字段还需关联来源版本、原归档及记录定位。`DomainGraphExtractor` 另会去 www、聚合并筛 `count > 5` 的边；这些操作不可用于本题身份或低频目标的排除。同目录 `app/WebGraphExtractor.scala` 在该提交只返回输入，不是实际 raw 抽取核心。

## 7. 主题偏移和正文指纹不决定网站存在资格

### 7.1 OTMT

固定版本：[`oduwsdl/off-topic-memento-toolkit@77cba436a6219fab8b8b7c773c3fc273388a8a2c`](https://github.com/oduwsdl/off-topic-memento-toolkit/tree/77cba436a6219fab8b8b7c773c3fc273388a8a2c)。

输入可为 Archive-It collection、TimeMap 或 WARC。[timemap_measures.py](https://github.com/oduwsdl/off-topic-memento-toolkit/blob/77cba436a6219fab8b8b7c773c3fc273388a8a2c/otmt/timemap_measures.py) 的 `compute_score_across_TimeMap()` 将同一 TimeMap 内各捕获与首个捕获比较，可使用文本、词频和 SimHash 等度量。

它适合发现主题变化与辅助复核。合法换站、转型或所有者变化也可能造成偏移，而 exact hostname 在该年仍有网站。故不以 off-topic 标签自动删除年度记录，也不把同一主题当作跨年存在证明。

### 7.2 wayback-discover-diff

固定版本：[`internetarchive/wayback-discover-diff@0060bdac8791634e919abfc307200b7eb747ccbf`](https://github.com/internetarchive/wayback-discover-diff/tree/0060bdac8791634e919abfc307200b7eb747ccbf)；核查时仓库已标记 archived。

服务处理给定 URL/year 的捕获，返回时间到 SimHash 的结果。[discover.py](https://github.com/internetarchive/wayback-discover-diff/blob/0060bdac8791634e919abfc307200b7eb747ccbf/wayback_discover_diff/discover.py) 提取 HTML 文本特征，并对相同 digest 复用计算。

可抽取纯特征计算与内容缓存机制。该服务不是已经实现的跨域停放页分类器；相同正文不等于相同 hostname-year。Under Construction、默认页、软错误等资格应由竞赛证据规则分别处理，不能把内容相似或主题变化当作统一自动否决条件。

## 8. CDX 选择、分页与回放客户端

### 8.1 Wayback CDX 服务端：折叠和完成语义要读到循环

固定提交：`internetarchive/wayback@a331f968c2a8b3ef56b82dc3a9faed11900e84b2`。

- [README](https://github.com/internetarchive/wayback/blob/a331f968c2a8b3ef56b82dc3a9faed11900e84b2/wayback-cdx-server/README.md) 和 [CollapseFieldFilter.java](https://github.com/internetarchive/wayback/blob/a331f968c2a8b3ef56b82dc3a9faed11900e84b2/wayback-cdx-server/src/main/java/org/archive/cdxserver/filter/CollapseFieldFilter.java)：collapse 比较相邻值，不按 hostname 重置。多个 collapse 是顺序过滤，不是复合键分组。年度位图必须自行按 original 的 exact host 构造。
- [CDXServer.java](https://github.com/internetarchive/wayback/blob/a331f968c2a8b3ef56b82dc3a9faed11900e84b2/wayback-cdx-server/src/main/java/org/archive/cdxserver/CDXServer.java) 的 `writeCdxResponse`：原始行读取计数先推进，日期/权限/regex/collapse 后才增加输出数。original regex 可在 output limit 前执行，但不能只在客户端过滤第一行就宣称无匹配。
- 非分页分支可能先触发配置的 `queryMaxLimit`；resumeKey 又以输出达到 writeLimit 为条件。故无 token 不构成通用的完整性证明。该源码不等于 2026 年生产后端配置，当前生产读上限未测量。
- ZipNum pageSize 是压缩块单位。限定视图中的全部页消费完成、限量选择出一条 witness、在预算内未命中，是三个不同结果。continuation 的同 key/同秒边界也需按用途审查。

已将静态反例、exact host 过滤、缺年 witness 和范围完成状态写入[流水线第 5 节](DISCOVERY_AND_VERIFICATION_PIPELINE.md#5-cdx-查询必须以证据目标为中心)。没有为确认文档已明确的语义安排实际查询测试。

### 8.2 GLAM-Workbench/web-archives：分页落盘与元数据缓存

固定提交：`e84fa145eb0a97efabfad69a8cd12e7d35ed6f4c`。

| 文件 | 可复用机制 | 必要适配 |
|---|---|---|
| [harvesting_domain_data.ipynb](https://github.com/GLAM-Workbench/web-archives/blob/e84fa145eb0a97efabfad69a8cd12e7d35ed6f4c/harvesting_domain_data.ipynb) | showNumPages、pageSize、requests-cache、按页 NDJSON 及查询元数据 | 记录具体索引视图、每页完成与预算；示例 domain 范围不能默认用于基线子域发现 |
| [find_all_captures.ipynb](https://github.com/GLAM-Workbench/web-archives/blob/e84fa145eb0a97efabfad69a8cd12e7d35ed6f4c/find_all_captures.ipynb) | IA/pywb 查询字段与过滤差异 | 保留 original，按规则解析 exact host-year；示例 collapse=urlkey 不提供年度完整性 |
| [getting_text_from_web_pages.ipynb](https://github.com/GLAM-Workbench/web-archives/blob/e84fa145eb0a97efabfad69a8cd12e7d35ed6f4c/getting_text_from_web_pages.ipynb) | 获取回放文本、处理跳转、避免明显落到活站 | 还需校验实际 capture 年；SURT 分组不是竞赛身份 |

这些 notebook 提供实际 API 消费模式，不是现成的 Creeperman 年度证据验收器。

### 8.3 CreepsoOff/wayback-machine-website-downloader：镜像能力与证据能力不同

固定提交：`75be75b6f696b73d55cad17f0a22f806f2f3b2bb`。下列文件均位于 [`src/wayback_machine_downloader/`](https://github.com/CreepsoOff/wayback-machine-website-downloader/tree/75be75b6f696b73d55cad17f0a22f806f2f3b2bb/src/wayback_machine_downloader)。

| 代码 | 已确认机制 | Creeperman 需要改变的地方 |
|---|---|---|
| `cdx.py` | CDX-first、查询指纹、续取 token 持久化、重复 token 检查 | 当前收集所有行后返回；无 token 即完成仍受上游语义限制。改为分块输出并明确查询范围状态 |
| `selection.py` | 按 original URL 选择 latest/nearest/before/after | 目标改为 exact host 缺年与同年替代 witness；不照搬单 URL 时间点镜像策略 |
| `http.py` | 退避、数字 Retry-After、SHA-1 Base32 digest 检查，考虑 gzip 解码 | 并入 provider 总预算；校验失败需要业务状态和替代证据，不能只留日志 |
| `mirror.py` 的 `download()` 与 `state.py` | 关闭自动重定向、保存状态/headers 与下载登记 | 不足以证明选中索引时间与实际回放捕获相同；当前 digest 校验失败仍可登记为已完成下载，后续报告错误，没有本题所需的替代 witness 闭环 |
| `mirror.py` | 外链允许列表、深度与预算 | 历史正文链接作为独立线索；不自动回填目标年份 |
| `warc.py` | 生成新的 resource WARC，使用选择出的 CDX timestamp | README 已说明不是 IA 原始 WARC；派生包装需绑定实际 capture，不变成新的历史观察 |

可复用获取与检查点机制。仅有“使用 CDX、下载 id_、再写 WARC”不足以提供本题完整保管链。[README](https://github.com/CreepsoOff/wayback-machine-website-downloader/blob/75be75b6f696b73d55cad17f0a22f806f2f3b2bb/README.md)与代码的镜像用途应保留。

## 9. 索引汇总与历史消息格式

### 9.1 ymaurer/cdx-summarize：适合盘点，不保留全部 witness

固定提交：`1ed55683921f55f2926d900be1b355130f956f47`。[README](https://github.com/ymaurer/cdx-summarize/blob/1ed55683921f55f2926d900be1b355130f956f47/README.md)、[CdxParser.py](https://github.com/ymaurer/cdx-summarize/blob/1ed55683921f55f2926d900be1b355130f956f47/CdxParser.py)、[cdx-summarize.py](https://github.com/ymaurer/cdx-summarize/blob/1ed55683921f55f2926d900be1b355130f956f47/cdx-summarize.py)。

可按 host 与 year/month 汇总记录及压缩 WARC 字节。默认的 second-level domain 实际取 SURT 两级标签，并非完整 PSL；`--fullhost` 仍基于 canonical/massaged key，不能恢复已经丢掉的 www。CDXJ 缺 status 时未由通常的 2xx 检查拒绝。汇总结果丢失 original 和原始记录定位。

借用其时间 inventory 思路；候选与合格证据由保留 original、年份和原件定位的解析结果构建。它不提供新的历史文本来源，也不是精确年度身份或证据完整性判定器。

### 9.2 alphalinux/mailing-list-archives：Usenet 数据格式参考

固定提交：`2c9b45193312840f20b219078630af617c3cf53b`。[来源记录](https://github.com/alphalinux/mailing-list-archives/blob/2c9b45193312840f20b219078630af617c3cf53b/SOURCES.md)、[fetch-usenet-archive-mbox.py](https://github.com/alphalinux/mailing-list-archives/blob/2c9b45193312840f20b219078630af617c3cf53b/fetch-usenet-archive-mbox.py)。

代码明确使用 `usenet-<hierarchy>/<group>.mbox.zip`，处理 `From <deja-id>`、多种 Date 形式和无日期记录。可用于了解 Google/Deja 消息包的格式，但整包入内存、缺时区默认 UTC、作者自定日期下限不能无条件迁移。Creeperman 保留原始字节位置、Date、时区不确定性和 Message-ID 缺失状态。

本轮在 IA 官方目录确认了示例 ZIP 名称列示，没有取 ZIP。作者报告处理范围与实际目标期容量分别记录，详见[流水线来源表](DISCOVERY_AND_VERIFICATION_PIPELINE.md)。

## 10. RDAP 工具不是历史年代筛选的完整实现

### 10.1 pepa65/domaincheck

固定提交：`01e3b20e2809b9c00997ccc676552c33424baac9`。[src/main.rs](https://github.com/pepa65/domaincheck/blob/01e3b20e2809b9c00997ccc676552c33424baac9/src/main.rs)。实现是 **Rust + Tokio**，并非 Go。

`extract_domain_info` 从顶层 registration 事件提取 creation_date；文件批量检查按 TLD 分组并用 semaphore 限制并发，JSON 可带 info。已读 CLI 没有历史年份阈值筛选参数。WHOIS fallback 返回可用性，不保证补全日期；缺失或错误不能当历史不存在。可以参考请求与解析，保留原始事件、来源与失败状态后才用于辅助排序。

### 10.2 jedarden/domain-check

固定提交：`1d48672cf586354a9888d3045066a211a71f3ea9`，Go 实现。

| 文件 | 静态核查结果 |
|---|---|
| [internal/rdap/rdap.go](https://github.com/jedarden/domain-check/blob/1d48672cf586354a9888d3045066a211a71f3ea9/internal/rdap/rdap.go) | `extractDates` 提取 registration，无此值时把 reregistration 也填入 Created，扁平输出丢失事件区别 |
| [internal/checker/checker.go](https://github.com/jedarden/domain-check/blob/1d48672cf586354a9888d3045066a211a71f3ea9/internal/checker/checker.go) | 内核结果可保留 Registration，支持 CheckBulk；需留意启用 DNS shortcut 的具体调用路径，不能说其默认跳过 RDAP |
| [internal/cli/bulk.go](https://github.com/jedarden/domain-check/blob/1d48672cf586354a9888d3045066a211a71f3ea9/internal/cli/bulk.go) | 批量 CLI JSON/CSV 不导出 Registration/Created，仅有 domain、available、tld、source、duration、error |
| [internal/ratelimit/ratelimit.go](https://github.com/jedarden/domain-check/blob/1d48672cf586354a9888d3045066a211a71f3ea9/internal/ratelimit/ratelimit.go) | Go rate limiter 与 weighted semaphore，属于进程内机制，不是全球共享预算服务 |

最小语义适配是保留 domain 顶层原始事件、补齐批量导出字段与缺失/失败状态。即便这些完成，registration 也只是注册线索；当前创建日期不能作为历史网站资格或安全排除依据。协议与当前 zone 的输入偏差见[流水线第 3.3 节](DISCOVERY_AND_VERIFICATION_PIPELINE.md#33-现代-zone-与-rdap-放到辅助路径)。

## 11. 实施边界

本轮确定的自写部分是：**exact hostname 与年份、来源祖源、证据规则、可替代 witness、年度差集、资料处理范围及查询完成语义。**归档格式解析、压缩索引、分布式任务生命周期和通用内容特征已有代码可用。

先有具体历史材料，再选择适配器和任务粒度。固定来源、规则、代码版本与可恢复输出后，才有明确对象可以核验；当前不因找到仓库便启动测试或全球扫描。

