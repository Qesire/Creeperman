# Creeperman

1996—2001 历史网站发现竞赛的项目解读、问题定义与证据审计。

本项目面向 Internet Digital Ark：持续发现历史主机名，为每一个入选的 hostname-year 保留确切的网站证据，形成可供后续历史网页采集使用的年度清单，并用来源收益与失败记录改进下一轮发现策略。

## v0.2 实现与移交

**下一位执行 Agent 首先阅读 [AGENTS.md](AGENTS.md) 和 [本地运行交接手册](docs/HANDOFF_LOCAL_AGENT.md)。** 已完成原始资料适配、联合差集、双馆在线查询/回放、全文反搜、来源追溯、Temporal 批次执行、结果导入和经裁决年度结算。

- [具体来源登记表](config/source_registry.json)：材料入口、祖源、格式、优先级、剩余范围及访问限制。
- 安装：python -m pip install -e ".[worker,archive,test]"。
- [v0.2 第一轮 CI](https://github.com/Qesire/Creeperman/actions/runs/45413440577)：15 项离线回归及 2 项真实 Temporal 集成测试通过（固定网络响应）。
- 2026-11-25 完成首轮本地全量统计。六个来源合计 89,165,782 个不同候选主机名，逐年举证后新增 18 条主机名年度记录，合计 11.5612 EED。按来源与年份拆分的缺口见[本地统计报告](docs/LOCAL_CENSUS_2026-11-25.md)。

## v0.1 实现（历史）

- [可执行代码、命令、样例和验收边界](docs/IMPLEMENTATION_V1.md)：离线差集摸底、真实 Temporal SDK 工作流与 Worker、内容寻址文件传输、有限 IA CDX 元数据补证、幂等结果归并。
- 安装：`python -m pip install -e ".[worker,test]"`；仅离线摸底可用 `python -m pip install -e .`。
- 真实基线与来源文件需在执行机提供；本地差集报告中的条件上界不等于可提交分数。网络操作须显式启用，默认的本地样例不访问档案馆。

## 阅读入口

最新来源获取与外联顺序见[可获取性优先清单](docs/ACQUISITION_PRIORITY_2026-11-25.md)。ODU 早期 DMOZ 研究副本、SPIRIT 元数据和 NII 正式申请并行；先检查明确可交付的公开小物件与既有本地导入原件，不把未核实早期 dump 作为已下载资产。

最新执行优先级见[交集与中止试验后的竞赛策略](docs/STRATEGY_AFTER_INTERSECTION_2026-11-25.md)：以原始证据供给和可交付物为核心；辅助年份交集与在线查询只作有限补充。

| 文档 | 内容 |
|---|---|
| [论文机制与发现操作](docs/LITERATURE_AND_DISCOVERY_OPERATORS.md) | 最新校准：引用提取、语义反搜、来源集合追溯；具体来源变体、两层时间、条件重试与存证字节域 |
| [发现与取证流水线](docs/DISCOVERY_AND_VERIFICATION_PIPELINE.md) | 当前入口：六类对象、历史文本来源、CDX 查询完整性、实际捕获年份、端点预算与全球执行契约 |
| [档案起源与剩余发现](docs/ARCHIVE_ORIGINS_AND_RESIDUAL_FRONTIER.md) | IA/WebBase 近乎读完后的来源判断、最初采集机制、可调查材料与容量缺口 |
| [归档项目源码审计](docs/OPEN_SOURCE_COMPONENT_AUDIT.md) | MemGator、MementoMap、ArchiveTeam、urx 等固定版本的实际机制与复用边界 |
| [研究复核后的方案](docs/EVIDENCE_LED_REDESIGN.md) | 来源生成代码、高效验证与 Temporal 全球批次通信；来源优先级已按最新覆盖情况修订 |
| [门槛估算与全球分布执行](docs/CAPACITY_AND_GLOBAL_EXECUTION.md) | 容量情景、请求/计算预算、成熟执行组件、数据放置与来源预算 |
| [全过程与剩余发现](docs/PROCESS_AND_RESIDUAL_DISCOVERY.md) | 对象、状态、完整流程、成熟方法和大基线下的发现策略 |
| [方案设计](docs/SOLUTION_DESIGN.md) | 核心门槛、主辅路线、组件边界与研究先行的推进依据 |
| [成熟方案与来源调查](docs/MATURE_APPROACHES_AND_SOURCES.md) | 批量索引、早期恢复、业界实践、实际访问与代码复用 |
| [项目关键总结](docs/PROJECT_SUMMARY.md) | 任务目标、最新规则、计分、已有资源、主要风险与工作优先级 |
| [问题定义](docs/PROBLEM_DEFINITION.md) | 研究对象、输入输出、集合与评分公式、证据状态、系统边界、验收条件 |
| [两个开放研究问题](docs/OPEN_RESEARCH_QUESTIONS.md) | 1996 年以前资料的规模化恢复；网站年份的准确判定；可检验的研究路线 |
| [来源与核查记录](docs/SOURCES_AND_AUDIT.md) | 本地来源定位、版本差异、已核查事项及结论边界 |
| [当前基线审计](docs/BASELINE_AUDIT.md) | 六年文件的本次本地计算、计分器局限与复现说明 |

## 关键判断

- 用户已说明 WebBase 2001 几乎读入、已使用的 IA 主体来源也几乎读完；不再把它们或同祖源镜像视为未开发主力。只有明确的未处理范围、新投影或证据补全依据才能重开任务。当前尚未证明有足够剩余材料跨过 1% 门槛。
- 来源先核到原始采集、日期、身份、生成代码和交付范围。提供者不同、信息投影不同与基线外新增分别判断；资料仍无法回答的问题才进入判别性执行。
- 新增三种有界发现操作：按类型抽取引用、按入链描述与实体线索反搜、从捕获追溯 item/文件。它们扩大目标、查询表示和材料范围；不把相关性、www 变体或冷门集合自动认定为合格增量。晚期资料可以提供线索，计分证据保留核心年份要求。
- 资料发现和在线补证分开调度。已取得的合格证据直接进入年度差集；在线补证只处理剩余缺口，全文发现和注册线索分别使用预算。Usenet、同期邮件和明确版本的论文已具体到材料入口，但残余容量尚未测得；RDAP 是辅助在线线索，不是网站证据或可靠的历史硬排除器。
- exact hostname 从 original URL 解析；SURT 只作检索键。CDX 相邻年份折叠不是 hostname-year 分组；空结果或无续取 token 不自动证明检索完整。实际捕获年、请求年、原件时间与转存时间分别保存。
- 已计入的 hostname-year 与已展开的资料分别记录：已知历史页面仍可能产生新外链、新检索入口或其他年份的证据。直接计分按基线求差，资料展开按来源版本和操作进度去重。
- 核心统计单位是 **hostname-year**。同年去重，跨年分别举证；裸域和 `www.` 形式分别处理。
- 年度主表要求目标年份、确切 hostname 的网站证据；DNS、注册、邮件或文本线索须保存在候选层。
- 使用固定 `CC-MAIN-2024-10` TLD 英语占比计算 Equivalent-English Domains（EED）。这是加权代理指标，不是逐站语言识别。
- 2026-10-20 版本的最低提交触发线为 **1%**，建议目标为 **2%**；达到门槛后仍需持续发现。排名使用时间加权分数。
- 优先发现未知可注册域和验证候选。Common Crawl 语料不进入本任务的活动候选池；其固定语言权重表仍用于计分。

## 本次交付范围

解读日期：2026-11-24（UTC+8）。依据本地 `1996-2001KnowledgeDiscoveryCompetition` 任务包，主规则版本为 `Internet_Digital_Ark_Project_1020_Update.docx`，基线目录为 `merge261121-3`。不同材料之间的差异已明确标注。

前期交付为分析文档与核查材料；v0.1 另提供实现与回归测试。当前未提交新的年度增量，也没有取得组织者的正式验收分数。原始巨量清单、受限来源和任务包原文不随这些总结上传。


## 方案进展

2026-11-24 初版来源与方案设计采用批量历史索引、定向补证及旧 Creeper 组件；当时的来源探针范围见[来源调查](docs/MATURE_APPROACHES_AND_SOURCES.md)。下述最新覆盖信息已改变这条路线的优先级，旧探针不代表当前新增结果。

同日完成全过程重构：用来源/资料待办和候选/缺年验证待办组织两个循环，统一证据、全局差集和收益反馈。补充 Heritrix、IIPC 路由实践、MementoMap、RSM 等机制；明确已计入记录不能被无条件从资料展开路径中删除。新的流程定义见[全过程与剩余发现](docs/PROCESS_AND_RESIDUAL_DISCOVERY.md)。

进一步完成[门槛估算与全球执行设计](docs/CAPACITY_AND_GLOBAL_EXECUTION.md)和[离线估算器](audit/estimate_capacity.py)。其中产率与吞吐为情景参数，旧小型控制进程的标价组合不是当前 Temporal 部署预算；未测得真实来源新增率或全球吞吐。

同日研究复核补充 WebBase URL2/Hasher/Converter、pywb、warcio 与 ArchiveSpark 的源码依据，区分 UKWA/Arquivo 的共同 IA 祖源。全球编排首选 Temporal＋各地批次 worker＋manifest 引用；撤下原定 72 次探测和自建租约层，并纠正 RSM 关键词模块的实现状态。

最新修订接受用户提供的 IA/WebBase 近乎读完前提，追溯 Alexa、WebBase、Kulturarw3 与 PANDORA 的原始生产链。研究重点转向具体历史观察库存、选择/拒绝记录、独立原件与已确认的未消费信息；同时审查用户列出的归档项目，明确默认来源、年份、身份、缓存和任务预算边界。本轮仅阅读资料、源码并修改文档，没有新增测试、扫描或部署。

进一步将候选发现与证据补全落实为[流水线契约](docs/DISCOVERY_AND_VERIFICATION_PIPELINE.md)：绑定 Usenet/W3C/arXiv 材料，区分候选库、缺年目标与合格证据；核查 CDX 折叠、扫描上限和分页完成语义，明确回放实际年份及替代 witness。全球任务仍用 Temporal，预算按真实提供者和端点统一管理，不采用“24 请求/分钟 × VPS 数”的容量推断。本轮仍只有资料和源码核查、文档修订，没有新增数据执行或提交结果。

本轮进一步完成[论文到操作的映射](docs/LITERATURE_AND_DISCOVERY_OPERATORS.md)：核读 Huurdeman、Bicho、Lerner、Hantke、Garg、Aturban 的原始资料和对应固定代码；纠正 TrackingExcavator 仓库归属、WebKB 原版与派生集混用、TUMBA 启动时间推定捕获年份等问题。11.8% 未绑定原文，不用于定参；88.45% 限于复合回放哈希变化。负缓存到期只恢复调度资格，全文搜索、来源元数据与复核请求分别受预算约束；没有新增语料下载、候选查询、测试或部署。
