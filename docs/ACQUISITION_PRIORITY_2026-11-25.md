# 可获取性优先：DMOZ 原件追索、有限实物处理与外联清单

2026-11-25；承接 [国际来源调查](INTERNATIONAL_EVIDENCE_SOURCE_SEARCH_2026-11-25.md) 和 [实测交集后策略](STRATEGY_AFTER_INTERSECTION_2026-11-25.md)。本轮按用户的可获取性纠偏重排，不把历史存在、论文规模、当前交付三者混同。没有下载大型语料、发送候选或邮件、取得新 EED；本地 G 盘不在本会话可读环境。剩余门槛仍按已有已核实 11.5612 EED 为 764292.9033（以最新基线/本地结算为准）。

## 1. DMOZ：先确认目标年份文件，不下载错误年代

已核实的历史原件使用证据：

- Ainsworth et al., JCDL 2011, §3，[论文](https://www.cs.odu.edu/~mweigle/papers/ainsworth-jcdl11.pdf)，明确处理 100 份 2000-07-20 至 2010-10-03 的 DMOZ 快照；去除非 HTTP、无效 URI 后得到 9,415,486 不同 URI。这是十年联合 URI 数，不是 2000/2001 host 数。该论文还把 DMOZ 与 IA 采集来源联系起来；人工目录的生产独立，不等于其收录与 IA/基线统计独立。
- Alkwai, Nelson & Weigle, 2019 preprint / JCDL 2020, §3.1，[arXiv](https://arxiv.org/abs/1908.02819)、[可读全文](https://www.researchgate.net/publication/335094887_Making_Recommendations_from_Web_Archives_for_Lost_Web_Pages)，明确称归档 118 份 2001–2017 RDF。研究转换 SURT、从晚到早按 URI 去重且过滤类别，不能直接拿其训练集当逐年原始表。另见 [2019 学位论文](https://digitalcommons.odu.edu/computerscience_etds/90/)（DOI 10.25777/yk35-dd38）。这两项构成新的 ODU 原件保管追索线索，尚未确认今天仍留存。
- Wu, Goel & Davison, WWW 2006 §6.1，[原文](https://archives.iw3c2.org/www2006/programme/files/xhtml/3115/fp3115-wu/fp3115-wu-xhtml.html)，使用 2001-01-22 ODP RDF。Lehigh 是第二追索渠道。
- 2007 年 [NeOn D1.6.1](https://research-archive.stem.open.ac.uk/stemra-data/uploads/sites/136/2025/03/NeOn_2007_D1.6.1.pdf) 的叙述支持当年原站 archive/ 提供从 2001-01 起的历史 ontology snapshots；structure 层不能替代 content 中的真实网站 URL。

公开入口实查：

| 对象 | 核查结果 |
|---|---|
| [IA item dmoz-rdf-20150327](https://archive.org/details/dmoz-rdf-20150327) | 27.7 GB，Notes 声明预期覆盖 2004–2015；7 个 WARC 和 7 个小 CDX 索引，另有 item 级 CDX。可能有异常早期对象，需检查索引；未取得索引字节。 |
| [dmoz.co.uk archive](https://www.dmoz.co.uk/rdf-sub/rdf/archive/) | 实际返回目录最早为 2004-01-05，父目录文件标注 2017。不能作为目标期 dump。 |
| [Huihoo](https://download.huihoo.com/dmoz/) | 目录文件时间 2013；不认作目标期。 |
| 原 rdf.dmoz.org 历史 archive/、curlz.org 镜像 | 本轮未取得可用历史目录；不判定不存在。 |
| IA advancedsearch、MDAPI、item CDX 文件 | 当前 Web 工具读取失败；执行容器直接 HTTP 探测因 DNS 解析失败。未从失败推出数据不存在。 |

因此，2000–2001 的 DMOZ 原始历史 dump 曾公开、有实际使用记录；**当前完整公开可下载文件仍未绑定**。旧目录不能冒充早期资料。不得下载 27.7 GB 全集作为盲试。

### 本地 Agent 立即做的有限资料获取（不传本地候选）

1. 先查本地旧池导入原件是否已有 DMOZ，并恢复实际日期、源路径和 locator；有可复核的目标期原件便直接处理。
2. 若 IA 公开 item 可正常访问，先获取单个 item CDX：
   https://archive.org/download/dmoz-rdf-20150327/dmoz-rdf-20150327.cdx.gz
   只在 item CDX 不完整、且确有必要时补查页面明列的 dmoz-rdf-00000.warc.os.cdx.gz 至 dmoz-rdf-00006.warc.os.cdx.gz（14.2K、10.6K、9.3K、8.6K、7.9K、12.1K、20.0K）。目录与索引查询均是公开来源物件，不是竞赛候选查询；访问受限/429/503 则停止，不绕开。
3. 按实际 CDX header 的 original URL 字段检查是否存在目标期版本路径及 content 文件；记录完整范围和真实日期。区分 2015 转存 capture timestamp 与原 RDF snapshot version。只发现 structure 或晚期资料不进入核心年计分。若发现有效 locator，检查原始 WARC record/range 是否可取得以及 gzip 完整性、版本与授权，再决定读取。
4. 对确切早期 content.rdf(.u8).gz，记录原 URL、日期出处、许可、SHA-256 和 XML 实际条目。先用现有 extract --format dmoz-rdf 得到 ExternalPage 原 URL；其当前 observed_year 为 null，必须另外绑定经核实的快照版本和条目语义后，才能生成带年 observations/本地裁决。不能从下载日期、文件 mtime 或晚期网页的自述回填。逐年用现存年度索引求差；目录是否适格依任务书与实际记录裁决。保留 www 独立、URL 原始身份和条目定位；多个快照同一 host-year 只结算一次。
5. 若本轮未定位具体早期文件，记录此次范围，将 DMOZ 原件取得交给 ODU/Lehigh 询证；不无限重复同一搜索。

## 2. 不等待外联的两项小规模物件

- [Zenodo 8408539](https://zenodo.org/records/8408539) banners_output_20230930.json，215 MB，前轮记录 MD5 0b183aca59895cc1cb9ea96eae82ccfd；本轮页面返回 429，未下载。访问恢复后先核文件清单、版本、字节/摘要和结构，提取 appearances[].url + timestamp（源页面捕获线索）以及 hrefs（外链目标候选），与既有基线离线去重。IA 衍生投影只计未消费记录；它不是同期印刷黄页原件。不要将 77,747 书中入口或 138 万次抓取当公开 JSON 全量。不能按外链所在网页日期直接给目标网站计分。
- [Internet Scout](https://scout.wisc.edu/report) 的官方说明明确有 [按时间排列的旧期次](https://scout.wisc.edu/Reports/ScoutReport)；可从期次目录提取实际存在的 1996–2001 issue URL，本轮搜索已找到 1996-01-05、01-19、01-26、02-02、02-09、02-23、04-26、05-03、05-31、11-01、11-15 等出版方记录。按真实目录枚举，不盲猜每个日期。每期只解析原始编辑条目与相邻描述，排除现代页头、页脚、转发/订阅、邮件和 FTP。可先处理几个已取得期次检查本地差集，再消费未处理的完整目录范围。保留原文、日期和定位，遵守出版方 reproduction 规则；不必逐条 IA 复验满足同期权威目录条款的条目。该来源为可核实补充，不是已证明门槛主力。
- 旧候选池导入原始账本仍是 P0 本地资产。先读取已存在的 provenance、原 URL、日期、状态、文件位置；已知 12862376 个名称可与其他来源对上不等于知道最初入池渠道。不要重做 89M census 或辅助年富集，也不要用同名连接虚构原始记录。

## 3. 精简外联优先级：按可交付物而非论文规模

| 优先级 | 目标 | 先请求 |
|---|---|---|
| P0 | ODU DMOZ | 2000-07-20、2001 全部现存原 content RDF 或逐版本的 original URL/类别/快照日期/locator；不取 SURT 去重训练表代替 |
| P0 | SPIRIT | 2001 crawl 的 DOCURL+DOCHDR 摘要、批次/抓取日期、DOCNO，或 exact-host 分年响应表；可选独立 source/target 表，版权正文非必要 |
| P0 | NTCIR NW100G-01 | 按 NII 正式研究协议询证用途，先请求 sitelist/doclist/aliaslist/targetlist/linklist 的轻量交付及日期/角色说明 |
| P1 | Lehigh DMOZ | 精确 2001-01-22 原始 RDF，与 ODU 版本求同源去重 |
| P1 | Yellow Pages 作者与 Thelwall | 1999–2001 原始印刷目录逐条页码/URL；2000–2001 按批次的 source/target ZIP |
| P2 | SecuritySpace / Netcraft / AOLA / EVA / TodoCL / WebRelievo | 简短现存文件与许可询证，未获交付信息不阻塞主线、不投入大规模工程 |

SPIRIT 的 [Joho & Sanderson 2004 原文](https://eprints.whiterose.ac.uk/id/eprint/4551/1/joho_sigirforum_2004d.pdf) 确认 2001 年中 Waterloo 抓取和 Fig.1 的 DOCURL/DOCHDR；致谢所列项目合同号为 IST-2001-35047（更正先前用户转述的编号）。94,552,870 是文档数；未查到 distinct exact hostname 统计。不能用猜测的“几十万至百万”或 21.33 亿链接直接计分，也不能确认从未公开或现存副本概率。元数据请求优先；外链图不自动证明目标曾响应。SecuritySpace 的逐站表/正文保留机制没有已取得的公开材料；用户的商业访问风险判断纳入优先级，但不声称从未公开或只采头已被本轮证明。
NII [官方申请页](https://www.nii.ac.jp/dsc/idr/en/ntcir/ntcir-web-docdata.html) 明确免费、研究用途限定、提交 application、审核、纸质双方签署协议后 Web 下载，可能拒绝用途。先完整披露实际研究和竞赛用途、派生 hostname-year 及有限组织者复核需求，确认许可后才签约/下载；不是默认竞赛合规。协议样本链接本轮读取失败，须本地阅读。

## 4. 第一轮外联草稿（未发送；用户审核后使用）

学术联系入口均为公开机构资料；不推定仍持有副本。不代用户发信，不附本地候选或任务包。

**ODU DMOZ**：Michele Weigle (mweigle@odu.edu), Michael Nelson (mnelson@odu.edu)，[Weigle](https://www.odu.edu/directory/michele-weigle)、[Nelson](https://www.odu.edu/directory/michael-nelson)。

Subject: Early DMOZ RDF snapshots (2000–2001) used in your web archiving studies

Dear Professors Weigle and Nelson,

I am working on a historical web recovery research project and related knowledge discovery competition. Your 2011 JCDL paper describes DMOZ snapshots beginning on July 20, 2000, and the 2019 preprint with Lulwah Alkwai mentions 118 RDF files from 2001–2017.

Do any original 2000 or 2001 content RDF snapshots, or dated original-URL inventories derived from them, still survive? We only need the original URLs, snapshot dates, category or entry identifiers, and provenance. We would also appreciate guidance on permitted research use and whether derived hostname-year records and limited supporting evidence can be shared with competition organizers for audit. A reference to another custodian or a public download would be equally helpful.

Thank you for your time.

**SPIRIT**：Waterloo IR group Charles Clarke (claclark@plg.uwaterloo.ca) 或 Mark Sanderson (mark.sanderson@rmit.edu.au)，[Waterloo IR](https://cs.uwaterloo.ca/research/research-areas/information-retrieval)、[RMIT profile](https://www.rmit.edu.au/profiles/s/mark-sanderson)。第一封发给一个核心联系人即可；必要时再联系历史副本保管方，避免同一团队重复轰炸。

Subject: Metadata inventory of the 2001 Waterloo / SPIRIT web crawl

Dear Professor [Clarke or Sanderson],

I am investigating historical web coverage in 1996–2001 for a research project and related knowledge discovery competition. Joho and Sanderson's 2004 SIGIR Forum article describes the mid-2001 Waterloo crawl and the SPIRIT collection.

Does any copy of the crawl's URL inventory or response metadata survive? We do not request the archived HTML bodies. An existing extract of DOCNO, original URL, actual observation date or crawl-batch identifier, HTTP status and record locator would be sufficient; a host-level inventory retaining the observation year and response provenance would also help. If an original source/target link table exists, it would be useful separately.

Could you advise whether such metadata can be accessed under appropriate terms, including limited independent audit of derived historical hostname-year results? A referral to a surviving copy would be greatly appreciated.

Thank you for your time.

**NII**：idr@nii.ac.jp，官方 [NW100G-01 申请与协议页](https://www.nii.ac.jp/dsc/idr/en/ntcir/ntcir-web-docdata.html)。

Subject: Research-use eligibility and metadata access for NW100G-01

Dear IDR team,

I am interested in using the 2001 NW100G-01 web document collection to study historical website coverage and archival gaps. The study is also part of a historical web knowledge discovery competition. Before applying, could you confirm whether this use is compatible with the agreement, particularly the release of derived hostname-year lists and limited evidence to the organizers for independent audit?

If permitted, we would initially prefer the lightweight site, URL, alias, target and link lists, along with documentation of their crawl dates and observation roles, rather than the full document corpus. We would follow the formal agreement and would not redistribute restricted raw data.

Thank you for your guidance.

Lehigh 备用联系人：[Brian Davison](https://engineering.lehigh.edu/faculty/brian-d-davison)，bdd3@lehigh.edu；沿用 ODU 请求，将论文引用和日期换成 2001-01-22 原始 RDF，明确不要只索取与 WebBase 对齐后的实验子集。

## 5. 停止和验收

公开物件获取、旧池 provenance 恢复与高价值外联并行；没有真实文件或许可时不继续泛搜同一资料或建大规模爬虫。不凭 100/118 快照、94.5M 文档、11M 文档承诺 EED。下一次决策依据是本地实际 distinct source hostname-year、年度差集、合格证据、全局净 EED、可获得剩余范围及成本；若大源无具体交付且现有小材料净增不足，重新判断参赛投入。暂停原 24 对配对查询与集群扩容，现有实验停止条件有效。

本轮 PDF 原文文本阅读成功，部分截图请求缓存失败。IA 索引和 Zenodo 数据字节未取得；未对 G 盘真实数据求差。所有未取得对象都不计入新产出。
