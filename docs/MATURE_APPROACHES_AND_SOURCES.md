# 成熟方案、业界实践与来源可行性

调查日期：2026-11-24（UTC+8）。本文件为[方案设计](SOLUTION_DESIGN.md)提供来源链。公开说明、实际读取、代码复核和待执行计划分别标注。竞赛规则沿用当前 Creeperman 文档；这里没有复核本地任务包原文，也没有取得新的组织者验收结果。

关于这些系统如何连接成完整流程，以及大规模已有覆盖如何改变搜索，先看[全过程与剩余发现](PROCESS_AND_RESIDUAL_DISCOVERY.md)。本文保留逐来源的资料依据、访问探针和适配细节。

最新用户信息说明 WebBase 2001 几乎读入、已使用的 IA 主体来源几乎读完；此前提升 WebBase 新增来源优先级的判断已撤下。当前入口为[档案起源与剩余发现](ARCHIVE_ORIGINS_AND_RESIDUAL_FRONTIER.md)；新列归档项目的代码能力见[组件审计](OPEN_SOURCE_COMPONENT_AUDIT.md)。本文件保留已有来源说明和历史探针，不因渠道不同便认定有新供给。

最新[论文机制与发现操作](LITERATURE_AND_DISCOVERY_OPERATORS.md)补充三种发现机制、WebKB 原始/派生版本、NCSA 镜像、晚期 DMOZ/GeoCities、档案实际年代和远程能力。该文的引用校准同时修正 Bicho 方法、TrackingExcavator 归属、11.8% 未绑定统计及 88.45% 的对象范围；本轮没有新增历史探针或真实候选请求。

## 调查带来的设计结论

1. **批量索引与按需回查已有成熟路径。** Arquivo 的官方 bulk 流程、ArchiveSpark 和 Webrecorder 可以直接提供方法和组件。
2. **来源契约是有意义差集的前提。** 先核定原始身份、逐年语义、生成过程与交付范围，再将合格年度键与最新 baseline 求差；抓取版本数、URL 数和 hostname-year 数不能互换。
3. **身份压缩会改变赛题对象。** SURT、Domain Graph、Archive95 展示层都可能合并 www/裸域，竞赛应读取原始 URL。
4. **早期恢复的门槛已被实践明确。** Archive95 的原文件—URL 映射和日期重建经验，比泛化的“找旧网页”更接近可执行工作。
5. **独立 HTTP 观测值得调查。** Netcraft 的月度观测与 DNS 调查具有不同证据含义；是否能取得早期行级记录，仍需具体数据契约。

## M1. Arquivo.pt：当前可读取的批量来源

官方资料：

- [开放数据与 CDXJ](https://sobre.arquivo.pt/en/collaborate/open-data-sets-for-research/)
- [实际 CDXJ 目录](https://arquivo.pt/datasets/cdxj/)
- [官方 API、配额与批量访问步骤](https://github.com/arquivo/pwa-technologies/wiki/APIs)
- [CDX API 字段与时间语义](https://github.com/arquivo/pwa-technologies/wiki/URL-search%3A-CDX-server-API)
- [PWA9609 TestCollection](https://github.com/arquivo/pwa-technologies/wiki/TestCollection)

### 已确认事实

官方建议先选择收藏、下载 CDXJ 索引，再筛选 URL 和取回资源。CDXJ 保存原始 `url`、捕获 `timestamp`、状态、MIME 和 ARC/WARC 定位。当前 CDX API 文档注明同一 IP 每 60 秒最多 250 请求；实现应留出余量并在 429 后退避。

PWA9609 描述中的历史分量为：Roteiro 1996 年约 75,000 文档版本；IA 1996—2000 年约 5,047,000 文档版本；IA 2000—2008 年约 118,842,000 文档版本。这些是该研究语料的资源统计，并非当前完整索引的唯一主机数。

### 此前来源探测轮的实际读取

对公开索引执行小范围只读请求，确认：

| 对象 | 原始对象大小 | 字段观察 |
|---|---:|---|
| `Roteiro.cdxj` | 13,585,912 bytes | 1996 年 capture 时间；原始 URL；ARC 文件名中出现 2009 年打包时间 |
| `IA.cdxj` | 48,994,912,989 bytes | 样本包含 2000 年记录、IP URL 和 404；需要逐字段筛选 |

两者的 Range 小请求得到 206。Roteiro 随后完成全量读取：44,379 行，均为 1996 年、status 200；按本次明确的 HTTP/ASCII hostname 筛选并保留 www 后，得到 4,955 个唯一 hostname-year，其中 HTML 200 子集为 939 个。该已解析集合即使全新、全权重 1，也仅能覆盖 1% 提交门槛的 0.6483%，适合作为小来源闭环。完整性与日期事实来自索引；尚未逐条查看网页正文或与比赛基线求差。目录上的约 13M/46G 是显示值；上表来自响应对象大小。ARC 文件名中的迁移/打包时间与记录捕获年应分别解释。可复现脚本和探针汇总位于 [probe_archive_sources.py](../audit/probe_archive_sources.py) 与 [source_probe_20261124.json](../audit/source_probe_20261124.json)；完成范围以 JSON 的记录为准。

### 对方案的作用

已有 Roteiro 观察可帮助明确格式和小来源容量。IA 路线先核查 collection、时间与记录语义，再决定后续确定的处理范围；其原始抓取与其他机构的 IA 派生收藏存在祖源关系，不把不同提供者当独立库存。PWA9609 链接投影和原 URL 映射的具体机制见[复核文档第 3.3 节](EVIDENCE_LED_REDESIGN.md)。

## M2. British Library / UKWA / JISC：按年提供 CDX 的成熟模式

官方资料：

- [JISC UK Web Domain Dataset 概览](https://britishlibrary.github.io/data.bl.uk/ukwa.ds.2/)
- [年度 Crawled URL Index 与 schema](https://britishlibrary.github.io/data.bl.uk/ukwa.ds.2/cdx/)
- [British Library 数据记录](https://bl.iro.bl.uk/entities/product/b416bac5-c94a-4789-933b-95ad3d44ce24)
- [Host Link Graph 与语义](https://britishlibrary.github.io/data.bl.uk/ukwa.ds.2/host-linkage/)
- [2026 年服务恢复公告](https://www.bl.uk/stories/news/uk-web-archive-restored)
- [研究数据/API 技术信息](https://www.webarchive.org.uk/en/ukwa/info/technical-information)

### 已确认事实

年度索引把原始大量小 CDX 合成 1996—2013 共 18 个年度包，包内未排序。字段包括 capture 时间、实际 URL、响应状态、MIME、digest、ARC/WARC 文件名和 offset。数据记录标示 Public Domain Mark。原始整体归档与派生开放数据的访问条件不同。

Host Link Graph 的行包含 crawl year、源 host、目标 host 和链接频数。源 host 的抓取与目标 host 的被链接事实应保留角色；图中年代绑定方式不能被默认为所有目标网页都被同年抓取。

### 此前探测与当前文档的取得程度

元数据和 schema 可读。旧下载 URL 在本轮 HTTP 访问返回 200，但内容是约 3.3 KB 的应用壳，未获得年度 CDX 文件；另一旧入口未取得有效数据。这是本次访问结果，不等于证明所有镜像均失效。恢复查询/阅览服务也不自动证明开放数据下载已恢复。

### 对方案的作用

先取得有效年包、镜像清单或提供者确认的交付方式，再实现大规模导入。`.uk` 的固定权重使真实新增具有较高 EED，但容量和 baseline 重叠必须实测。该收藏来自 IA，不能把其全量与 Arquivo-IA 全量直接相加。

## M3. Internet Archive / Webrecorder：检索、身份与归档读取

官方实现：

- [Wayback CDX Server](https://github.com/internetarchive/wayback/blob/master/wayback-cdx-server/README.md)
- [Webrecorder warcio](https://github.com/webrecorder/warcio)
- [Webrecorder cdxj-indexer](https://github.com/webrecorder/cdxj-indexer)
- [pywb Indexing](https://pywb.readthedocs.io/en/latest/manual/indexing.html)

CDX 可返回原始 URL、capture 时间、MIME、状态与 digest，并提供分页/续取机制。`warcio.ArchiveIterator` 支持 WARC/ARC 的单次流式遍历。`cdxj-indexer` 可为没有索引的归档建立 CDX/CDXJ。

这里最重要的适配是 exact hostname：官方例子中 `org,iana)/domains/example` 对应 `http://www.iana.org/domains/example`。从 urlkey 逆变换得到的 host 会改变竞赛身份。跨年 `collapse=urlkey` 还可能只保留某一年的捕获；应在原始记录中保留目标年 witness 后，再按 hostname-year 聚合。

按原始 hostname 核对返回结果，即使调用 `matchType=host` 也要检查原始 URL。任务书约束下，定向补证使用独立发现的确切 host，不以 baseline 根域为根进行大规模子域扩张。

## M4. ArchiveSpark：先筛元数据，再读取必要内容

- [作者仓库与 README](https://github.com/helgeho/ArchiveSpark/blob/master/README.md)
- [Generating_CDX notebook](https://github.com/helgeho/ArchiveSpark/blob/master/notebooks/Generating_CDX.ipynb)

已读 README 与 notebook 的说明和流程。该框架从归档数据派生目标语料，支持过滤、内容读取和来源链记录。值得首先迁移的是访问顺序：低成本索引筛选、分组与排序之后，再加载需要的归档内容。

Creeperman 可以用 Python、已有模块和流式差集实现这个顺序。真正取得需要多机处理的大批归档后，再考虑 Spark 运行时。来源不可取或 baseline 重叠高的问题，应由来源决策解决。

## M5. Archives Unleashed / ARCH：成熟派生平台与必要语义适配

- [ARCH 项目与 Internet Archive 合作](https://archivesunleashed.org/arch/)
- [Toolkit Link Analysis](https://aut.docs.archivesunleashed.org/docs/link-analysis)
- [ARCH Derivatives](https://aut.docs.archivesunleashed.org/docs/auk-derivatives)

ARCH 支持从归档生成文本、网络图和其他派生数据；Toolkit 提供原始 URL 链接结构与抓取日期。官方域图配方会执行 `removePrefixWWW` 并聚合边，有些示例还过滤低频链接。

竞赛应保留原始 URL/crawl_date 层，重新定义身份键。对 UMN、UKWA 及其他外部图数据，都要检查节点是否匿名、是否删除 www、年份绑定 source 还是 destination，以及能否回到来源记录。

## M6. 年份判定：沿用归档协议与保管链

- [Memento / RFC 7089](https://www.rfc-editor.org/rfc/rfc7089.html)
- [WARC 1.1](https://iipc.github.io/warc-specifications/specifications/warc-format/warc-1.1/)
- [WARC 实施与迁移指南](https://iipc.github.io/warc-specifications/guidelines/warc-implementation-guidelines/)

Memento 区分原始资源、历史状态与 TimeMap。年度归属要对应实际返回状态时间，不能由请求日期代替。WARC 的类型、目标 URI、日期、记录标识、关联记录和 digest 可以保留证据链；容器迁移、恢复与原始 HTTP 捕获的时间语义须明确。

建议最小记录：原始 URL、exact hostname、观测时间/区间、时间语义与依据、来源版本、原对象 hash、记录 locator、恢复时间、转换版本和证据状态。

这些标准解决定位、交换和表示；具体记录是否满足比赛的网站证据要求，由证据策略与组织者验收确定。

## M7. Archive95 / W3C / CERN：原始介质恢复的实际方法

入口：

- [Archive95 说明](https://archive95.net/about)
- [来源、损坏和修复清单](https://archive95.net/sources/)
- [公开数据](https://archive.org/details/archive95-dataset)
- [源码](https://github.com/WumboSpasm/archive95-server)
- [W3C 1992 服务器目录](https://www.w3.org/History/19921103-hypertext/hypertext/DataSources/WWW/Servers.html)
- [W3C 历史时间线](https://www.w3.org/History.html)
- [CERN Web 起源与恢复项目](https://home.cern/science/computing/the-birth-of-the-web)

Archive95 利用互联网光盘、离线镜像和浏览器缓存恢复早期网页，并逐来源描述 URL 改写与日期问题。它把“原文件能否关联回原 URL”和“日期的可信程度”明确列为主要困难。

| 具体来源 | 可复用资产 | 首轮核查 |
|---|---|---|
| `chipspiele` | 1996 年网页及 WebWhacker URL 映射日志 | 单条 URL/日期与原文件一致性 |
| `pcpress` | 1996 年逐站文件—URL 映射 | 损坏映射与修复标记 |
| `chipfun` | 日期修正实例 | 原日志偏差与修正依据 |
| 跨年介质 | 同一介质中的多个历史时间段 | 每条记录的日期范围 |

已复核 Archive95 server commit `0390d478c3c0c200b95fbdd7cead28a74d5345b4` 的 [build.js](https://github.com/WumboSpasm/archive95-server/blob/0390d478c3c0c200b95fbdd7cead28a74d5345b4/src/build.js) 和 [utils.js](https://github.com/WumboSpasm/archive95-server/blob/0390d478c3c0c200b95fbdd7cead28a74d5345b4/src/utils.js)：原始 manifest 提供 `entry.url` 与 `entry.archived`；缺失日期时展示层回退到来源日期；normalizeUrl 会合并 www 等形式。应直接读取原始字段，再核查日期的生成依据。MIT 许可对应代码，原始资料另看来源条件。

W3C 目录适合验证历史正文边界：页面有后加导航及多种协议/服务。CERN 的恢复实践提示应分别存原始内容年、备份年与恢复年。前 1996 的合格结果进入扩展年；这些恢复方法也可支持少量 1996—2001 的独立补充。

## M8. 独立来源与相关研究

### Netcraft：HTTP 调查的数据契约

- [月度 HTTP 调查方法](https://www.netcraft.com/resources/web-server-survey/active-sites)
- [Internet Data and Research](https://www.netcraft.com/solutions/other-solutions/internet-data-research)

官方说明 Web Server Survey 自 1995 年 8 月开始，按月发出 HTTP 请求识别服务器；当前产品包含历史分析和定制数据。这证明存在贴近网站响应的历史观测机制。

需要进一步取得的数据说明是：1996—2001 的行级 exact hostname、观测时间、真实响应信息、原记录定位、可取得范围与复核/使用条件。当前尚未取得行级样本、报价或批量授权。Netcraft 的 active-sites 统计还会按内容结构归并，竞赛应索取原始 hostname 观测而非直接使用聚合总数。

### UMN DRUM：先验证图节点与年度语义

- [官方数据说明](https://experts.umn.edu/en/datasets/link-lists-for-websites-tracking-the-development-of-the-early-web/)
- DOI：[10.13020/D62684](https://doi.org/10.13020/D62684)
- [数据 handle](https://hdl.handle.net/11299/200445)

官方元数据确认覆盖 1996—2000，包含 source、destination、frequency。目前只确认目录级身份；先补 README、文件清单、节点规范化和原始采集关系。尚不列为已可接入的独立原始网页库，也不据此假定其独立于已读 WebBase/IA 材料。

### IA / ODU / Filecoin 的纵向取样实践

论文：[Longitudinal Sampling of URLs From the Wayback Machine](https://arxiv.org/html/2507.14752v1)，2025；[作者代码](https://github.com/oduwsdl/nypw)。

作者从 ZipNum 索引出发构建跨 1996—2021 的 URL/TimeMap 数据，明确处理热门站点过度出现和早期稀疏性。全文说明早期 1996—2000 合并后约 120 万 URL；这不是 hostname-year、baseline 外增量或我们已可取得的数据量。

它为本方案提供的经验是：索引取样的单位与收集目标必须一致，热门站点和重复捕获会改变样本结构。我们按 exact hostname-year 和当前基线差集评价收益，并保留每个成立年度的证据。

## M9. 旧 Creeper：已有工程资产及迁移范围

已读版本：[Qesire/Creeper@9905a1897cb4e07fc2906cde68978449b7027659](https://github.com/Qesire/Creeper/tree/9905a1897cb4e07fc2906cde68978449b7027659)。

| 文件 | 本轮阅读/核查范围 | 迁移用途 |
|---|---|---|
| [baseline_index.py](https://github.com/Qesire/Creeper/blob/9905a1897cb4e07fc2906cde68978449b7027659/src/creeper/authority/baseline_index.py) | 代码读取：年度位图、批量查重、版本绑定 | 当前基线索引 |
| [host_year.py](https://github.com/Qesire/Creeper/blob/9905a1897cb4e07fc2906cde68978449b7027659/src/creeper/sources/archive/host_year.py) | 代码读取：连续 host 聚合、逐年 witness、差集及收益统计 | 局部压缩和证据引用；全局去重另行保证 |
| [cdxj.py](https://github.com/Qesire/Creeper/blob/9905a1897cb4e07fc2906cde68978449b7027659/src/creeper/sources/archive/cdxj.py) | 代码读取：原始 URL、时间、状态筛选 | 格式解析；证据判定按新规则 |
| `authority/eed.py`、`normalizer.py` | 独立阅读：Decimal 权重与官方规范化 | 精确计分；大批量避免全量 set |
| `storage/evidence_store.py`、`submission/streaming_exporter.py` | 目录与 README 确认，未逐行审查 | 后续证据库和导出参考 |
| `scripts/run_arquivo_cdxj_catalog_probe.py`、`run_arquivo_cdxj_sample.py` | 目录确认 | 后续复核来源探针，减少重写 |

可直接复用的部分集中在确定性数据处理。旧 5%/ZIP 规则更换为当前 1%/7z；解析层宽泛状态只作为初始观测，再经新证据策略。全局唯一键和多 witness 保留同时用于来源统计与最终导出，避免前端产率虚高。

## M10. Stanford WebBase / LAW：已近乎读入的独立图来源

- [LAW webbase-2001](https://law.di.unimi.it/webdata/webbase-2001/)：2001 年 Stanford WebBase 抓取衍生图；118,142,155 URL 节点，提供图与 URL 映射。
- [WebGraph 教程](https://law.di.unimi.it/tutorial.php)：URL 第 i 行与节点 i 对应；图和 URL 文件必须采用匹配版本；可用成熟 API 顺序访问邻接关系。
- 作者仓库固定 `2ffd9d9a7144c7024974e92379a05978fb97a8b5` 的 [WebBase 转换工具](https://github.com/vigna/webgraph/tree/2ffd9d9a7144c7024974e92379a05978fb97a8b5/src/it/unimi/dsi/webgraph/webbase)：URL2 未删除 www/子域；Hasher 以规范化 URL 哈希归并、保留首次输入标签；Converter 由源记录后继链接生成出度。

这条路线具有独立抓取祖源和具体交付物。正出度源节点可在版本、身份与 dated graph 规则成立时形成图证据；零出度节点保留候选。仍须补历史生产版本绑定和上游 hostname 处理，不能将现存代码直接当成 2001 文件的完整生成证明，也不能把节点数当新增 host-year。详情见[复核文档第 3.1 节](EVIDENCE_LED_REDESIGN.md)。

用户已说明主体几乎读入，上述机制保留作证据审计与有明确依据的缺口恢复。没有已处理范围清单支持时，不重新把该图列为未开发主力。

## M11. 复用能力必须核到实际代码

新增确认：pywb 的 ZipNum 二级定位与相邻索引块合并、BlockArcWarcRecordLoader 的局部归档读取、ResolvingLoader 的本次头/原 payload 分离，以及 ArchiveSpark DataSpecs 的两阶段加载。它们承担读取机制，竞赛资格由自身适配器判断。

两处研究代码不应直接视为可用的竞赛模块：RSM 所链接仓库的 keyword_sample_profiler.py 仍为 TODO；NYPW hydratewarc.py 以 digest 缓存并补 mime/status 的做法不能替代本次捕获身份和状态核验。固定源码位置与复用界限见[复核文档第 4—5 节](EVIDENCE_LED_REDESIGN.md)。

全球任务生命周期优先采用 Temporal；相比自建数据库租约协议，直接复用命名队列、活动心跳、超时与恢复。Activity 速率与 HTTP 配额分开，数据通过 manifest 引用传递。框架及替代方案的源码依据见[复核文档第 6 节](EVIDENCE_LED_REDESIGN.md)。

## M12. 历史文本与在线补证的最新核查

[发现与取证流水线](DISCOVERY_AND_VERIFICATION_PIPELINE.md)记录本轮新增的具体来源及接口边界。Usenet 官方目录已列出两个可定位分组 mbox 文件，W3C 有目标年代逐月 HTML 目录，arXiv 有 S3 批量与正文版本契约；没有下载这些材料，也尚未测得基线外产率。W3C mbox 有权限条件，arXiv Requester Pays 与历史版本需要单独核定，DMOZ 1999—2000 dump 尚未定位。

在线端新增核查区分了 CDX 的相邻折叠与年度分组、raw scan 上限与 output limit、回放请求时间与实际捕获时间。Arquivo 官方限额分别为全文/CDX 250、Memento 400、单列回放等端点 4000 请求/60 秒/IP；这些分类没有自动可相加的承诺。Wayback 24/min 是有维护者依据的客户端默认，不能作为全球节点线性容量。具体原始资料、固定源码与采用条件均见流水线 §§5—7 及 P7、P11—P16。

## 首轮决策所需的最小来源契约

每个新来源只需要先填清以下几项：

| 字段 | 具体问题 |
|---|---|
| 年代 | 哪些记录确实落在 1996—2001，时间来自何处？ |
| 身份 | 原始 exact hostname 是否保留，可否区分 www/裸域？ |
| 网站语义 | 是目标网页捕获、可信目录/图节点，还是弱线索？ |
| 可取得性 | 元数据、样本、完整分片分别取得到哪一步？ |
| 祖源 | 由谁提供、由谁原始抓取，与既有来源有什么关系？ |
| 容量 | 已证实唯一键和增量下界；剩余范围有什么依据？ |
| 成本 | 网络、磁盘、CPU、人工与失败重试各需多少？ |
| 复核 | 每条记录能回到哪个版本、文件与位置？ |

先完成这个契约，再决定具体适配器和规模。调查中需要联系提供者的事项目前仅整理了条件，未发送消息、购买数据或请求他人采取行动。
