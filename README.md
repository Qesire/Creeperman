# Creeperman

1996—2001 历史网站发现竞赛的项目解读、问题定义与证据审计。

本项目面向 Internet Digital Ark：持续发现历史主机名，为每一个入选的 hostname-year 保留确切的网站证据，形成可供后续历史网页采集使用的年度清单，并用来源收益与失败记录改进下一轮发现策略。

## 阅读入口

| 文档 | 内容 |
|---|---|
| [研究复核后的方案](docs/EVIDENCE_LED_REDESIGN.md) | 当前入口：具体来源、生成代码、可信发现、高效验证与 Temporal 全球批次通信 |
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

- 来源先核到原始采集、日期、身份、生成代码和交付范围。提供者不同、信息投影不同与基线外新增分别判断；资料仍无法回答的问题才进入判别性执行。
- 已计入的 hostname-year 与已展开的资料分别记录：已知历史页面仍可能产生新外链、新检索入口或其他年份的证据。直接计分按基线求差，资料展开按来源版本和操作进度去重。
- 核心统计单位是 **hostname-year**。同年去重，跨年分别举证；裸域和 `www.` 形式分别处理。
- 年度主表要求目标年份、确切 hostname 的网站证据；DNS、注册、邮件或文本线索须保存在候选层。
- 使用固定 `CC-MAIN-2024-10` TLD 英语占比计算 Equivalent-English Domains（EED）。这是加权代理指标，不是逐站语言识别。
- 2026-10-20 版本的最低提交触发线为 **1%**，建议目标为 **2%**；达到门槛后仍需持续发现。排名使用时间加权分数。
- 优先发现未知可注册域和验证候选。Common Crawl 语料不进入本任务的活动候选池；其固定语言权重表仍用于计分。

## 本次交付范围

解读日期：2026-11-24（UTC+8）。依据本地 `1996-2001KnowledgeDiscoveryCompetition` 任务包，主规则版本为 `Internet_Digital_Ark_Project_1020_Update.docx`，基线目录为 `merge261121-3`。不同材料之间的差异已明确标注。

这里交付的是分析文档与核查材料；没有执行新的大规模域名发现、没有提交新的年度增量，也没有取得组织者的正式验收分数。原始巨量清单、受限来源和任务包原文不随这些总结上传。


## 方案进展

2026-11-24 新增来源与方案设计：以批量历史索引的基线外证据供给为主线，定向补证为辅线；复用旧 Creeper 和成熟归档组件。首轮验证重点是来源剩余容量、exact hostname-year 身份与年份语义、全局去重后的边际 EED。实际探针范围与未完成事项见[来源调查](docs/MATURE_APPROACHES_AND_SOURCES.md)。

同日完成全过程重构：用来源/资料待办和候选/缺年验证待办组织两个循环，统一证据、全局差集和收益反馈。补充 Heritrix、IIPC 路由实践、MementoMap、RSM 等机制；明确已计入记录不能被无条件从资料展开路径中删除。新的流程定义见[全过程与剩余发现](docs/PROCESS_AND_RESIDUAL_DISCOVERY.md)。

进一步完成[门槛估算与全球执行设计](docs/CAPACITY_AND_GLOBAL_EXECUTION.md)和[离线估算器](audit/estimate_capacity.py)。其中产率与吞吐为情景参数，旧小型控制进程的标价组合不是当前 Temporal 部署预算；未测得真实来源新增率或全球吞吐。

同日根据研究复核修订当前方案：新增 WebBase 2001 独立图路线及 URL2/Hasher/Converter 源码依据；区分 UKWA/Arquivo 的共同 IA 祖源与不同投影；核实 pywb、warcio、ArchiveSpark 的验证机制。全球编排首选 Temporal＋各地批次 worker＋manifest 引用，来源请求在主采集区统一管理。撤下原定 72 次探测和初版自建租约层；纠正 RSM 所链接关键词模块仍为 TODO 的实现状态。本轮仅阅读资料、源码并修改文档，没有新增测试、扫描或部署。
