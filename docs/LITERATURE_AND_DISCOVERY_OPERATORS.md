# 从论文机制到发现操作：引用、语义检索与来源追溯

资料与固定源码核查：2026-11-24（UTC+8）。本文承接[发现与取证流水线](DISCOVERY_AND_VERIFICATION_PIPELINE.md)，落实用户新提供的论文、来源和“非 IA 发现”方案。当前工作为原文、官方数据说明及固定代码阅读，没有下载新语料、运行项目、查询真实候选、执行来源测试或测得新增产率。规则与基线见[问题定义](PROBLEM_DEFINITION.md)。

## 1. 设计结论与仍未解决的门槛

**在同一观测账本上增加三个有界操作：提取有类型的引用、用入链描述和实体元数据反搜、从捕获记录追溯来源集合。** 三者分别扩大可见的目标、可用的检索表示和可调查的材料范围。它们产生线索与资料待办；已有材料足以构成网站证据时，可直接进入规则判定和年度差集。

WebBase 2001 与已使用 IA 主体来源近乎完成的前提保持不变。任何旧源重开都必须指明未处理的版本、记录角色或提取操作；不能预设正文外链尚未消费。“非 IA”改为检查**原始观察血缘**：IA 托管的 Usenet 或 ArchiveTeam 文件不因此变成 IA 爬取；被另一机构转售、索引或镜像的 IA 捕获也不因此成为独立观察。

以下三个命题分别记录，不互相替代：

1. **方法有依据：**论文或固定代码说明怎样从输入得到输出。
2. **材料可实施：**某个具体对象具备身份、时间、定位、交付方式及处理范围。
3. **容量足够：**这些材料经证据判定、exact host-year 差集和全局归并后，有足够剩余 EED。

本轮推进了前两项；第三项仍未证明。当前 1% 门槛为 764,304.4645 EED；平均新增权重为 0.6 的情景需要约 1,273,841 个合格新增 hostname-year。该权重不是实测残余分布。[L0]

## 2. 文献究竟提供了什么

| 原始工作 | 已核实的机制和研究范围 | 本项目采用与限制 |
|---|---|---|
| Huurdeman et al., IJDL 2015 | 从荷兰 KB 2012 ARC 提取非空锚文本和 URL 关系；用年度已归档索引区分目标，构造 page 与 host surrogate，做检索评估 [L1] | 建立目标的可检索描述；不能把描述当目标正文，也不能把该研究的“未归档”解释为所有馆都没有 |
| Ben-David, 2016 | 以四份 `.yu` 删除前 URL 清单取得快照并重建直接链接邻域；当前可读官方摘要支持此范围 [L2] | 历史清单驱动有界扩展。用户给出的 `digitalmethodsinitiative/Web-Archival-Discovery` 本轮 API 返回 404，未绑定现存作者实现；不声称不存在过 |
| Lerner et al., USENIX Security 2016 | 通过历史回放观察第三方请求；被阻断请求的目标仍可能可见，但其响应及后续请求不可见。分析中的六个月资源窗口以测量时间为基准 [L3] | 资源引用与尝试请求也是候选观察；静态四类标签提取不等于完整动态请求测量，六个月窗口不等于 exact year |
| Ware, Klein & Nelson, 2011；Klein & Nelson, 2010 | 利用标题、词汇签名及链接邻域重新寻找丢失页面；比较上下文、邻域深度、回链数和签名长度 [L4] | 查询表示和按需回退有依据；“固定 3–5 词”不是本题已验证常数，找到迁移地址也不继承旧 hostname 身份 |
| Bicho & Gomes, iPRES 2016 | CORDIS acronym + title 构造 Bing 查询，比较排除项与常见词等启发式；代码另有语料级词项分析 [L5] | 迁移“实体元数据 → 查询模板 → 候选 URL”；改用 Arquivo 和入链描述是本项目适配，不是论文已实现的逐目标 TF-IDF 反搜 |
| AlSum et al., TPDL 2013 / IJDL 2014 扩展 | 对档案覆盖画像与选择少数档案的收益作评估；国家档案并不只保存本国 TLD [L6] | TLD 是软排序特征；研究的任意捕获召回不能直接代入本题的基线外年度证据概率 |
| Hantke et al., CCS 2023 | 用 `x-archive-src` 和 IA 元数据调查捕获贡献者及采集差异 [L7] | 提供来源调查线索；论文未证明它能产生基线外容量，已读代码也未提供通用 item resolver |
| Aturban et al., PLOS ONE 2023 | 多次取得 composite memento 时比较含资源、URI、状态、headers 和 body 的聚合哈希 [L8] | 分开原件、回放响应和分析指纹；不能将 88.45% 变化解释为 WARC 原件损坏或未使用 `id_` |

方法复用不要求换掉既有格式解析器、索引和 Temporal。需要新写的是本题的观测类型、日期与身份解释、可恢复操作范围和证据裁决连接。具体固定文件见[源码审计](OPEN_SOURCE_COMPONENT_AUDIT.md)。

## 3. 三个操作的共同输入输出

沿用 `SourceSlice`、`Observation`、`Candidate`、`VerificationTarget`、`EvidenceBundle`、`OperationRun` 六个对象，不再增加一套并行候选系统。

| 操作 | 输入 | 输出 | 去重与停止条件 |
|---|---|---|---|
| 引用提取 | 明确版本的历史页面或其他文本、原 URL、日期语义、解析配置 | 引用观察、目标 URL、上下文、exact host 候选 | 同一原始记录与解析上下文只处理一次；没有新观察或新证据缺口时不继续扩展 |
| 语义反搜 | 一个目标 URL 的入链描述，或有来源的机构/项目元数据 | 查询记录、命中 URL、实体关系假说、待核验目标 | 查询指纹包含引擎、集合/时间范围、查询词和版本；有限模板与结果预算，只有新线索或索引版本等触发才重开 |
| 来源追溯 | 捕获定位、原始响应头及已有来源说明 | 已核对或未决的来源绑定、具体集合/文件 inventory | 按 item 与元数据版本缓存；没有新文件范围、未处理角色或可用信息则停止，不自动扫描整个集合 |

操作幂等键应包含输入版本、记录定位、operator/version 和 scope。引用解析另包含 original URL、`base` 及日期语义；相同 body 在不同 base 下会产生不同目标。保存原始对象和不可变输出分片，规则或基线变化通常只需重判与重新求差，不需要再次下载正文。

一个已有 hostname-year 可以提供新的外链或实体描述，所以**计分差集不能删去资料入口**。相反，同一链接在千张模板中出现，也不能变成千条独立证据或千次在线请求。

## 4. 操作一：有类型的引用提取

### 4.1 先分清三种观察

| 观察 | 能说明什么 | 不能直接说明什么 |
|---|---|---|
| 页面源码中有目标引用 | 该版本的页面包含这个 URL 或资源引用 | 目标在同年响应成功、其主页可用、引用不是失效或示例 |
| 回放执行时出现尝试请求 | 该回放执行链尝试访问目标；可记录触发者与阻断原因 | 当年的浏览器一定做了同样请求，或被阻断目标具有可取得正文 |
| 取得目标自身的历史响应或其他规则允许的 witness | 可以进一步核定 exact host、实际年份与网站语义 | 单凭 HTTP 200、相同 digest 或近似文本就自动合格 |

首版以静态解析为主。配置表明确列出支持的 `tag/attribute`，例如 `a[href]`、`area[href]`、`img[src/srcset]`、`script[src]`、`frame/iframe[src]`、`link[href]`、`object[data]`，分别标注 navigation、embedded resource 等角色。CSS URL、meta refresh 与动态请求使用独立解析器/操作版本；未实现部分必须可见，不能统称已完成“全标签”。这些是设计选择，不是某篇论文的统一实现。

最小记录包含 `source_record_locator`、`source_original_url`、实际观察日期及依据、`tag/attribute`、`target_raw`、`resolved_target_url`、`anchor_text`、上下文位置、parser/version、来源家族。上下文长度是配置，`±50 词` 不作为已被论文证明的常数。资源域也按原 hostname 保存，不用 PSL 第三方归并替代计分身份。

### 4.2 回放 URL 解包必须有来源上下文

只在识别出的档案来源上下文与回放路径语法上解包；保留原值、modifier、请求日期、解析步骤与结果。先区分原始引用与档案重写引用：原始 HTML 中的相对引用按源 original URL 和合法的原始 `base` 解析；根据 provider 语法和重写特征确认的相对回放地址，先按 replay 上下文识别并解包，再取得 original 目标。不能先将所有相对回放路径合并到源站，也不能把档案 host 当作所有原始引用的源站。

不要对所有字符串全局删除 `/web/十四位数字/`：真实站点可能含这个路径；各馆、相对路径、协议相对地址、修饰符和嵌套回放也不同。原页面主动链接到档案服务的情况，应保留这层引用语义。无法判明的地址保持 unresolved，不猜测精确目标。

TrackingExcavator 正确官方入口是 `UWCSESecurityLab/trackingExcavator`，由华盛顿大学项目页链接；不是用户列出的 UCSB 路径。固定代码能登记请求及 escape 阻断，但旧解析器与测量日期回退不能原样作本题证据解析器。[L3、L9]

### 4.3 保留 observed www，不批量制造 observed www

`hostname_exact`、`surt_key`、`registrable_domain` 分开。Garg et al. 2025 确实报告了默认 SURT 的 www 归并及特殊名字误归一问题；作者采用去除受影响 URL 并提出规范化修正等处理，**没有据此证明自动加/去 www 是可信的新观察**。[L10]

原材料中观察到的两个形式分别保存。若以后加入 alias 探索，它应是明确标注的派生假说，单列预算，并通过新取得的 original 和年度证据确认；不能写回为原材料中已经出现的 URL。仍不从基线根域批量枚举子域。

## 5. 操作二：入链描述与实体元数据反搜

### 5.1 描述先保留 URL 与年份，再按需聚合

对目标 URL 保存入链锚文本、URL 词项、附近上下文、来源日期和来源家族，形成版本化 surrogate。去除模板重复并标明时间冲突，然后才生成 hostname 视图。Huurdeman 同时研究了 page 和 host surrogate；本项目保留两层，但不能把同一 ISP 的 `~alice/` 与 `~laboratory/` 混成一个机构。必要时保留多个主题描述。[L1]

“未归档”始终写成 `absent_from(collection, declared_time_scope, index_version)`；只有完成相应范围的查询，才有资格形成这个局部判断。一次错误或截断不能成为“全球无记录”标签。反搜可以由高价值实体线索触发，不必先向每个馆广播并取得一堆空响应。

### 5.2 使用少量可解释查询模板

有明确机构、项目名或 acronym 时先使用实体词和已知标题；缺乏结构化字段时，再从去重后的入链描述提取区分性词项。若使用 TF-IDF，保存语料版本、分词、停用词和查询模板；不把词频直接当实体真实性。

查询去向先考虑已有本地 Usenet、目录、文本索引；再考虑访问契约明确的 Arquivo 全文接口。使用时间与集合过滤后仍核对返回记录实际捕获时间。Arquivo 的全文 `q` 与 URL 历史查询是不同接口，不把 URL 字符串或 `siteSearch` 的 canonicalization 当 exact host 验证。[L5、L11]

查询命中输出：`query_id`、结果 URL、排名、可得捕获定位、实体匹配理由、观察时间和来源。它创建候选及关系假说，例如 `possible_mirror_of`、`possible_successor_of`；相关性分数不进入年度主表。

### 5.3 新地址独立取证，旧地址不继承

若旧 `h1` 的锚文本反搜得到 `h2`：对 `h2` 解析 exact identity、核对真实 capture 年并做差集；`h1` 仍保留自己的证据缺口。即使内容相同，也不互相填补 hostname-year。共享 ISP 目录的多个“网站”可能只贡献一个 hostname；这是竞赛计分单位造成的容量压缩，不是检索失败。

停止条件为：有限查询计划完成、已有足够证据、预算耗尽或只得到重复观察。保留 unresolved 和剩余范围，而不是无限增加查询词、年代与档案馆。

## 6. 操作三：捕获记录到来源集合

Hantke 支持保存 `x-archive-src` 并用元数据调查来源，但已读固定代码主要保存 headers、最终 URL、状态和内容哈希，没有绑定到通用的“header → item → 来源家族”实现。[L7]

固定 EDGI 客户端 fixture 展示了一种真实形态：`item_identifier/某文件.warc.gz`。MDAPI 需要 exact item identifier；因此不能将完整 header 原样拼入 `/metadata/{identifier}`。[L12]

具体流程为：

1. 原样保留 header 和它所属的响应/记录，缺失也记录。
2. 对已识别格式提取 item 候选和文件路径；未知格式保持未决。
3. 在共享预算下读取该 item 元数据，核对 identity 与文件列表；保存元数据快照、时间与解析版本。缺少文件映射时不强行绑定。
4. 分开记录 storage provider、item、collection、uploader/contributor、原始采集者与 `origin_family`；元数据 contributor 可由上传者填写，不自动等于采集者。
5. 形成具体文件清单，核定捕获年代、记录角色、取得条件及既有处理范围。只有相对于指定 `operation/version` 尚未消费的可用范围，才产生资料任务。

按 item 去重元数据读取，可把大量捕获共享同一来源的查询合并。不存在“每成功验证一页都重新请求 metadata”的规则。item 可查不等于原文件公开；同一捕获的 revisit payload 也可能来自其他记录，须分别定位。

“冷门集合”只是调查特征。不同捐赠者、item 名称或存储渠道不证明独立采集，更不证明基线遗漏。来源开启前继续检查 Common Crawl 语料排除要求；符合年代且新取得的原始观察仍需全局差集。

## 7. 来源校准：把具体文件与同名派生集分开

| 来源 | 本轮明确的契约 | 使用决定与尚缺资料 |
|---|---|---|
| CMU 原版 WebKB | 官方说明 1997-01 采集 8,282 网页；文件名编码 original URL，保留页面和 MIME headers；约 80 页仅含重定向 [L13] | 已定位有意义的小型原始材料；未下载。批次月份不能冒充逐条精确时间；需核对 existing coverage 与证据可用性 |
| LINQS / NetKit WebKB | LINQS 当前 metadata 描述 877 documents、1,608 links 和词特征；NetKit 提供标签及 direct/cocitation 图，且说明仅分发标签和边 [L14] | 不能把它们当 8,282 页原始 HTML。用户旧 `lbc/WebKB.tgz` 对象未读取，不推定与当前 zip 字节相同 |
| NCSA What's New | 机构记录支持早期人工通告来源；本轮读到 1996-01 月镜像，包含日期、名称、描述与真实 URL [L15] | 候选材料具体，但完整月份、镜像保管链和版本未核全。日期是通告日期；1993—1995 通告不能直接填核心年 |
| DMOZ item `dmoz-rdf-20150327` | item 日期为 2015；上传者 Notes 称应包含 2004 年至下载时的数据，内部版本未逐一核实；未确认 1999—2000 dump [L16] | 属于较晚线索与目录语义材料。不能把 item 里所有文件都一律叫 2015，也不能据此声称已有目标期 dump |
| GeoCities ArchiveTeam | 项目记录 2009 年线上抢救 [L17] | 后期历史线索；页面自述成立于 1997、旧风格、版权日期均不能替代目标期观察 |
| Usenet / W3C / 版本化论文 | 前轮已经定位实际对象、日期语义和交付限制 | 继续作为不同原始观察机制；不用 IA 托管地址将它们排除。具体契约见主流水线 |
| WebBase / JISC / 已用 IA | 既有覆盖与祖源判断仍有效 | 只重开可指明的遗漏操作与范围，不以新论文或新镜像重置完成状态 |

原版 WebKB 的 **8,282 是网页数**。仅对这些源页面的 1997 年事实而言，新增 hostname-year 上界不超过 8,282，且在权重不超过 1 时 EED 也不超过 8,282；这至多约为所需 1% 门槛的 **1.08%**。这是极宽松的静态上界，未扣除同 host、基线与无效响应；它不限制外链带来、另行证实的新目标。WebKB 适合明确契约，不能凭此称门槛级主力。[L0、L13；上界为本项目推导]

### 7.1 线索日期与证据日期采用两层策略

允许来源契约认可的后期资料进入线索层，保留真实观察/版本时间；计分证据单独要求 1996—2001 的年度依据。若把所有发现输入都硬限制在核心期，会无理由丢弃 GeoCities 2009 和较晚目录的线索；若把旧外观或正文自述倒填成年份，又会制造假证据。

Hyphe 当前源码确有 archive mode 和日期窗口，但 `archive_date_obtained` 可沿用请求日期，普通 `timestamp` 是处理时间；窗口也可能跨年。Creeperman 保存请求日期、实际取得的 capture 日期和处理时间，使用适配器核验，不直接继承这些字段为年度证据。[L18]

## 8. 档案路由：先看具体收藏与访问能力

| 路由对象 | 已核实事实 | 决策 |
|---|---|---|
| IA | 覆盖广，来源多；同一查询结果仍需 original 和实际年份核验 | 有明确历史 URL 时的重要候选馆；已知本地记录优先，不把泛后缀固化为只查 IA |
| PANDORA / Trove | PANDORA 首两项于 1996-10 下载；是选择性澳大利亚出版物保存，并非全 `.au` 抓取 [L19] | `.au` 和澳大利亚关联是优先线索；公开检索/回放与可自动使用的 CDX/API 契约分别登记 |
| Arquivo / TUMBA | 官方历史将 2001 记作 TUMBA 项目开始，保存的 Tomba 资料范围写作 2002—2006 [L20] | 不能由项目启动推出独立 2001 捕获；Roteiro 等早期资料和 IA 转入记录分别核到具体收藏、年代与血缘 |
| Webarchiv.cz | 首次网页归档为 2001-09；完整 `.cz` 定期抓取从 2006 开始；远程公开受授权/许可约束 [L21] | 只对可访问、时间匹配的实际记录排任务；软件是 Wayback 不等于已核实公开 IA 兼容 CDX |
| Archive-It | 官方支持导入外部、遗留和捐赠的 WARC/ARC，另有公开 CDX/C 文档 [L22] | 平台 2006 年开始不构成对所有旧记录的时间排除；这也不证明已找到 1996—2001 的新增收藏 |
| EOT、HAW、SWAP、Kulturarw3 等 | 常规采集期、可访问性与具体捐赠物需分别核定；Kulturarw3 1997 起有年代相关资料但远程访问受限 [L23] | `out_of_period`、`remote_access_restricted`、`api_contract_unverified`、`already_processed` 分开；不一律永久删除 provider |

Trove 官方 2023 年 API v3 介绍列明不包含 websites；因此不能把它的普通搜索 API 自动当成 AWA 批量索引。本轮没有绑定可供本项目自动操作的完整 AWA API 契约；这不是所有未来或其他接口都不存在的证明。[L19]

路由顺序采用：已有 locator/本地记录 → 收藏和实际时间范围 → 可访问操作 → 画像与 TLD/语言排序 → 有预算的备选。Top-K 是一次计划的请求上限，可以按已有结果调整；没有适用于所有目标的固定 K。已有研究的覆盖率衡量“是否有任意捕获”，本题需要的是 `P(形成新的合格(h,y) | 当前线索、基线、来源状态)`，二者不能互换。[L6；条件概率目标为本项目定义]

## 9. 验证、失败与存证的四项修正

### 9.1 查询投影不等于扫描优化

保留主流水线的规则：`collapse=timestamp:4` 折叠相邻同年前缀，不是每 host 六行；`matchType=domain` 扩展子域，不能作为默认 exact host 验证。返回后再次解析 original，缺年选择和查询完整性分别记录。

固定 Java Wayback 的字段选择发生在最终 writer 前；pywb 同样在索引处理后按 fields 输出。已读代码的 revisit resolver 由独立查询选项控制。省略 digest 可以减少输出字节，**没有依据保证省去扫描、revisit 处理或显著降低延迟**；也不能把输出字段选择与 `resolveRevisits` 混同。若补取证据仍需要 digest，一次保留字段可能比第二次索引请求更合适。[L24]

### 9.2 负缓存有作用域，过期只恢复调度资格

| 结果 | 保存范围 | 后续动作 |
|---|---|---|
| 429 / provider cooldown | provider/endpoint、Retry-After、发生时间、预算作用域 | 共享冷却；不通过换地区复制额度 |
| timeout / transient error | 具体尝试、错误类别及总重试预算 | 有界退避，防 HTTP 与 Activity 双层重试相乘 |
| scoped no-match | 已证明完整的 query scope、索引视图/版本、检查时间 | 过期后可重排；有新线索、索引版本或来源恢复等理由才优先激活 |
| blocked / restricted | 操作与访问依据 | 等访问能力或条件变化，不当成网站不存在 |
| truncated / budget exhausted | 已消费范围、cursor/检查点、剩余缺口 | 续取或重新规划，不登记完整负结果 |

“Bornand 2019 的 11.8% 波动率”本轮未能绑定到可核对原文及分母；已核实 Bornand 2016 路由研究和 Klein 等 2019 服务优化书目，不能将路由召回变化解释为 TimeMap 波动或重试成功率。该百分比不进入 TTL、产率或请求预算。[L25]

无限周期重查会使旧负结果持续占用容量。过期不是强制发请求；计划应受新证据、来源变化与有界复核预算驱动，详见[全球执行设计](CAPACITY_AND_GLOBAL_EXECUTION.md)。

### 9.3 88.45% 的统计对象与本项目哈希

Aturban 报告 16,627 个 composite memento 在 39 次下载中有 88.45% 出现多个聚合哈希。对提供 raw 的档案，研究已使用 raw 资源，并排除 rewritten HTML/CSS/JavaScript 正文等预期随回放变化的部分；不同档案实际纳入哈希的组件并不完全相同。它不是原 WARC 损坏率、CDX digest 错误率或 `id_` 修复前后的对比。方法部分明确日期为 2017-11-16—2019-01-11；摘要与方法的天数表述还存在差异，不能把其中一个数字无条件搬成参数。[L8]

本项目保存必要 witness，分开以下对象：

- `artifact_sha256`：实际保存文件的字节，注明是否含压缩容器。
- `replay_body_sha256`：本次客户端实际取得的 body，注明传输/内容解码处理。
- `archive_digest`：CDX 原字段、算法与已知的字节域；未知部分保留未知。
- 原始记录可取得时另存 block/payload 哈希及 locator；WARC revisit 的 payload 引用与当前记录身份、headers、日期分别记录。
- 分析用 normalized text hash / SimHash：仅用于缓存、聚类和复核，记录算法版本。

不同字节域不直接互验。`id_` 有助于取得未重写内容，但不保证可获得完整原 WARC 或其 HTTP block；哈希固定“我们持有什么”，定位与时间证据说明“它代表哪个观察”。只有裁决依赖嵌入资源时才增加资源 witness，当前无需为每个 host 构建整页浏览器回放。[L8、L26]

### 9.4 主题漂移和高频 digest 是复核特征

OTMT 比较相对于基准捕获的主题偏离；正常改版、主题发展、易主和错误页都可能触发。固定代码从 TimeMap first 取基准，而首捕获也可能错误。`topic_drift`、`parking`、`archive_error` 与 `eligibility` 因此分别标注；高频 digest 或内容偏离不自动删除整个 host 或该年全部 witness。[L27]

## 10. 执行与验收顺序

1. **登记具体输入。** WebKB 原版与派生版本分开，NCSA 镜像标保管链缺口，晚期资料保留真实日期；已有 IA/WebBase 记录只登记已证实残余。
2. **落实三个操作契约。** 使用版本化观测、实体关系、来源绑定和处理范围；先把输出语义及停止条件确定，再实现适配器。
3. **承接现有全球执行。** 静态提取在数据附近；全文检索、元数据追溯和证据获取按各自 endpoint 预算；Temporal 只承接批次与 manifest，不跨洲同步每个标签或 URL。
4. **结算同一目标。** 对全局合格集合做 exact hostname-year 差集；发现来源与验证来源分别归因，最终只计一次 EED。
5. **在材料与接口已明确后再解决残余率未知。** 后续若需要执行，先明确具体输入、待判别解释、成本上限及会改变决策的判据。本轮没有提前执行数据测试。

对操作 a，令 O 为已有观测，O_a 为其带来的新增观测，Γ 为版本化证据规则，B 为竞赛基线，A = Γ(O) 为操作前本地已判定合格集合，则可兑现的边际价值定义为：

```text
ΔEED(a) = Σ w(tld(h)), 其中 (h,y) ∈ Γ(O ∪ O_a) \ (B ∪ A)
```

这是结算定义，不是当前产率预测。它允许多个线索共同补成证据，也防止把不同入口的重复 host-year 相加。成熟论文降低的是方法不确定性；门槛级供给仍需具体材料的精确结果来证明。

## 原始依据与固定版本

- **L0**：[问题定义](PROBLEM_DEFINITION.md)、[基线审计](BASELINE_AUDIT.md)、[门槛估算](CAPACITY_AND_GLOBAL_EXECUTION.md)；IA/WebBase 近乎完成来自用户说明。
- **L1**：Huurdeman et al., *Lost but not forgotten: finding pages on the unarchived web*, IJDL 2015，[原文](https://ir.cwi.nl/pub/23462/23462D.pdf)，DOI 10.1007/s00799-015-0153-3，§§3.2—3.3、7。
- **L2**：Ben-David, *What does the Web remember of its deleted past?*, 2016，[出版者摘要](https://journals.sagepub.com/doi/10.1177/1461444816643790)。代码入口未核实的结论仅限本轮读取。
- **L3**：Lerner et al., *Internet Jones and the Raiders of the Lost Trackers*, USENIX Security 2016，[论文与正式书目](https://www.usenix.org/conference/usenixsecurity16/technical-sessions/presentation/lerner)、[作者项目及代码入口](https://trackingexcavator.cs.washington.edu/researchers.html)。
- **L4**：Klein & Nelson 2010，[Evaluating Methods to Rediscover Missing Web Pages from the Web Infrastructure](https://arxiv.org/pdf/0907.2268)；Ware, Klein & Nelson 2011，[An Evaluation of Link Neighborhood Lexical Signatures to Rediscover Missing Web Pages](https://arxiv.org/pdf/1102.0930)。
- **L5**：Bicho & Gomes 2016，[官方报告](https://sobre.arquivo.pt/wp-content/uploads/Preserving-Websites-Of-Research-Development-Projects.pdf)；`arquivo/Research-Websites-Preservation@8851fe47815d625e104a42cc6962166ff208c74b` 的 [recover_urls_bing.py](https://github.com/arquivo/Research-Websites-Preservation/blob/8851fe47815d625e104a42cc6962166ff208c74b/scripts/recover_urls_bing.py)、[extract_common_terms.py](https://github.com/arquivo/Research-Websites-Preservation/blob/8851fe47815d625e104a42cc6962166ff208c74b/scripts/extract_common_terms.py)。
- **L6**：AlSum et al., *Profiling Web Archive Coverage for Top-Level Domain and Content Language*，[TPDL 2013 全文](https://arxiv.org/pdf/1309.4008)；2014 IJDL 扩展 DOI [10.1007/s00799-014-0118-y](https://doi.org/10.1007/s00799-014-0118-y)。版本与样本范围须随数字一同引用；Thelwall & Vaughan 2004 [原始研究](https://www.sciencedirect.com/science/article/pii/S0740818804000246)说明国家覆盖偏差，不提供本题完备路由保证。
- **L7**：Hantke et al., CCS 2023，[原文](https://swag.cispa.saarland/papers/hantke2023archaeology.pdf) §3；`cispa/internet-archive-study@b0d7142ab1e7baf25f259bdc174a440a8ef84af7` 的 [collect_historical_data.py](https://github.com/cispa/internet-archive-study/blob/b0d7142ab1e7baf25f259bdc174a440a8ef84af7/collection/collect_historical_data.py)、[collect_cdx.py](https://github.com/cispa/internet-archive-study/blob/b0d7142ab1e7baf25f259bdc174a440a8ef84af7/collection/collect_cdx.py)。
- **L8**：Aturban et al., 2023，[Hashes are not suitable to verify fixity of the public archived web](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0286879)，方法与结果部分。
- **L9**：`UWCSESecurityLab/trackingExcavator@5b946b6fef48141c5e6ca6f9e1d6977b877177ab` 的 [Background.js](https://github.com/UWCSESecurityLab/trackingExcavator/blob/5b946b6fef48141c5e6ca6f9e1d6977b877177ab/platform/Background.js)、[Utils.js](https://github.com/UWCSESecurityLab/trackingExcavator/blob/5b946b6fef48141c5e6ca6f9e1d6977b877177ab/Measure/Utils.js)、[WaybackProcessing.js](https://github.com/UWCSESecurityLab/trackingExcavator/blob/5b946b6fef48141c5e6ca6f9e1d6977b877177ab/platform/WaybackProcessing.js)。发布代码还服务于后续研究，不等同于论文全部实验版本。
- **L10**：Garg et al. 2025，[arXiv:2507.14752v1](https://arxiv.org/html/2507.14752v1)，Appendix C；SURT 固定实现见[源码审计](OPEN_SOURCE_COMPONENT_AUDIT.md)。
- **L11**：[Arquivo 全文与 URL 查询文档](https://github.com/arquivo/pwa-technologies/wiki/Arquivo.pt-API)、[API 与配额](https://github.com/arquivo/pwa-technologies/wiki/APIs)；公开上限不作为本项目实际可用持续吞吐。
- **L12**：[IA MDAPI](https://archive.org/developers/md-read.html)、[元数据字段](https://archive.org/developers/metadata-schema/index.html)；`edgi-govdata-archiving/wayback@ff7955ea3d8017de380300d2c45b080beadb2b7f` 的 [固定回放 fixture](https://github.com/edgi-govdata-archiving/wayback/blob/ff7955ea3d8017de380300d2c45b080beadb2b7f/src/wayback/tests/cassettes/test_get_memento.yaml)。该 fixture 仅用于格式阅读，本轮未运行测试。
- **L13**：[CMU 原始 WebKB 说明](https://www.cs.cmu.edu/afs/cs/project/theo-20/www/data/)；其声明的包为 `webkb-data.gtar.gz`，本轮未下载。
- **L14**：[NetKit 数据说明](https://netkit-srl.sourceforge.net/data.html)；`linqs/linqs-website@92237e92d17f94941c087613372d415082c1f130` 的 [webkb.json](https://github.com/linqs/linqs-website/blob/92237e92d17f94941c087613372d415082c1f130/_data/datasets/metadata/webkb.json)；[作者技术报告](https://linqs.org/assets/resources/sen-techreport07.pdf) §6.5 说明页面任务，metadata 的泛化文本不能代替原始语料说明。
- **L15**：[Computer History Museum 的 1993 年 NCSA 通告记录](https://www.computerhistory.org/revolution/the-web/20/388/2129)、[本轮可读 1996-01 镜像](https://kitchencloset.com/realstuff/ncsa/whats_new-archive/1996/whats-new-9601.html)。镜像可读不等于完整来源链已核实。
- **L16**：[DMOZ 2015 item 与 Notes](https://archive.org/details/dmoz-rdf-20150327)。
- **L17**：[ArchiveTeam GeoCities 项目记录](https://wiki.archiveteam.org/index.php/GeoCities)。
- **L18**：`medialab/hyphe@0f59241dd57afeb82c4d791cc66505f024760fb9` 的 [pages.py](https://github.com/medialab/hyphe/blob/0f59241dd57afeb82c4d791cc66505f024760fb9/hyphe_backend/crawler/hcicrawler/spiders/pages.py)、[webarchives.py](https://github.com/medialab/hyphe/blob/0f59241dd57afeb82c4d791cc66505f024760fb9/hyphe_backend/lib/webarchives.py)、[linkextractor.py](https://github.com/medialab/hyphe/blob/0f59241dd57afeb82c4d791cc66505f024760fb9/hyphe_backend/crawler/hcicrawler/linkextractor.py)。
- **L19**：[PANDORA 历史](https://pandora.nla.gov.au/historyachievements.html)、[公开访问概览](https://pandora.nla.gov.au/overview.html)、[Trove 2023 API v3 介绍](https://trove.nla.gov.au/sites/default/files/2023-02/Introducing%20Trove%20API%20v3.pdf)。最后一份为当时官方材料，不宣称穷尽 2026 年所有访问方式。
- **L20**：[Arquivo 官方历史](https://sobre.arquivo.pt/en/about/press/history/)、[早期来源 FAQ](https://sobre.arquivo.pt/pt/ajuda/o-que-e-o-arquivo-pt/)。
- **L21**：[Webarchiv 官方 FAQ](https://webarchiv.cz/en/faq)。
- **L22**：[Archive-It 外部 WARC/ARC 导入](https://support.archive-it.org/hc/en-us/articles/360000651246-How-to-add-external-WARC-or-ARC-files-to-Archive-It-collections)、[API 与访问集成](https://support.archive-it.org/hc/en-us/articles/360001231286-About-Archive-It-APIs-and-access-integrations)。
- **L23**：[EOT](https://eotarchive.org/)、[HAW 官方介绍](https://haw.nsk.hr/wp-content/uploads/2020/07/HAW-letak-2020.pdf)、[新加坡 SWAP 官方回顾](https://biblioasia.nlb.gov.sg/all-sections/vol-14-issue-3-oct-dec-2018-archive-singapore-wide-web/)（项目始于 2006，不是 2008）、[Kulturarw3/IIPC 成员介绍](https://netpreserve.org/about-us/members/kungliga-biblioteket-national-library-sweden/)。
- **L24**：`internetarchive/wayback@a331f968c2a8b3ef56b82dc3a9faed11900e84b2` 的 [FieldSelectorProcessor.java](https://github.com/internetarchive/wayback/blob/a331f968c2a8b3ef56b82dc3a9faed11900e84b2/wayback-cdx-server/src/main/java/org/archive/cdxserver/processor/FieldSelectorProcessor.java)、[CDXServer.java](https://github.com/internetarchive/wayback/blob/a331f968c2a8b3ef56b82dc3a9faed11900e84b2/wayback-cdx-server/src/main/java/org/archive/cdxserver/CDXServer.java)；`webrecorder/pywb@28750e62b7c00d0bb72643b2ae68b6c2ea7a0abf` 的 [cdxops.py](https://github.com/webrecorder/pywb/blob/28750e62b7c00d0bb72643b2ae68b6c2ea7a0abf/pywb/warcserver/index/cdxops.py)。
- **L25**：Bornand et al. 2016，[Routing Memento Requests Using Binary Classifiers](https://arxiv.org/pdf/1606.09136)；Klein, Balakireva & Shankar 2019，[LANL 官方书目和摘要](https://laro.lanl.gov/esploro/outputs/conferenceProceeding/Evaluating-Memento-Service-Optimizations/9916369910503761)；[Archival Voids 2021](https://arxiv.org/pdf/2108.03311)。本轮未绑定“11.8% 波动率”的原始测量。
- **L26**：[WARC 1.1 specification](https://iipc.github.io/warc-specifications/specifications/warc-format/warc-1.1/)，block/payload digest 与 revisit 语义；[既有回放与 revisit 设计](DISCOVERY_AND_VERIFICATION_PIPELINE.md)。
- **L27**：[AlNoamany 2016 原文](https://www.cs.odu.edu/~mweigle/papers/alnoamany-ijdl16a.pdf)、[OTMT 2018 原文](https://www.cs.odu.edu/~mln/pubs/ipres-2018/ipres-2018-jones-off-topic.pdf)；`oduwsdl/off-topic-memento-toolkit@77cba436a6219fab8b8b7c773c3fc273388a8a2c` 的 [timemap_measures.py](https://github.com/oduwsdl/off-topic-memento-toolkit/blob/77cba436a6219fab8b8b7c773c3fc273388a8a2c/otmt/timemap_measures.py)。
