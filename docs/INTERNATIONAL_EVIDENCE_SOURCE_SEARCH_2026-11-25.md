# 国际历史网站证据源：2026-11-25 二次调查
　
## 目标与状态
剩余门槛 764,292.9033 EED。优先寻找 1996–2001 年独立抓取的原始 URL、HTTP 响应记录、可审核的同期网站目录，而非扩大无日期候选池。以下规模均为原文的页面、记录或站点统计，不能当成净新增 hostname-year 或 EED。未取得的新资料一律不预估产率。此次没有下载整库、发送本地候选、联系机构或执行在线验证。先与本地逐项来源账本核查是否已消费；IA 衍生资料与 WebBase 同源资料不算新采集家族。

## P0：追索历史研究副本与响应站点表

### SPIRIT / University of Waterloo mid-2001 crawl
- 原始出处：Joho & Sanderson, The SPIRIT collection: an overview of a large web collection, ACM SIGIR Forum 38(2), 2004, 57–61. DOI 10.1145/1041394.1041395。https://eprints.whiterose.ac.uk/id/eprint/4551/1/joho_sigirforum_2004d.pdf
- 论文记载 94,552,870 文档，约 1 TB，2001 年中 Waterloo 独立抓取，教育网站为初始种子；传给 Virginia Tech 的 Edward Fox，Sheffield 接收版本、转为 TREC 式记录，又用于 Dublin City University、Glasgow、Brighton 的研究。
- 原文 Fig.1 展示 DOCNO、DOCURL、DOCHDR（原 URL、长度及 HTTP 响应，如 200 OK 和 Date）、正文；表 3 是文档而非主机后缀分布。
- DCU 后续论文 Gurrin & Smeaton, Replicating Web Structure in Small-Scale Test Collections, §4.3，明确处理了约 21.33 亿链接，并区分约 5 亿 closed links。https://doras.dcu.ie/20906/1/DCU_IRJ_Final_formatted.pdf 。链接数量不等于独立主机，更不等于目标网站成功响应。
- 请求对象：当前是否仍有原始 crawl、SPIRIT 转换版、DOCNO↔DOCURL 字典、抓取日志/HTTP 元数据或当年处理形成的逐条链接表；先申请小索引或由保管方离线提取，不必先传 1 TB。逐条捕获日期若只有 HTTP Date 则另外核对记录语义；批次日期不能无条件代替单条响应日期。
- 可平行追查上述六校研究组/档案馆，副本只算一个原始采集家族。未定位现存可下载整库，访问与再分发许可未确认；不把历史使用记载说成目前仍持有。

### SecuritySpace / E-Soft（1998–2001 HTTP 网站调查）
- 同期 2000-09 调查 2,285,342 个响应网站；见 2000-10-04 新闻转载 https://apachetoday.com/news_story.php3?ltsn=2000-10-04-001-01-NW-CY-MR 。后缀统计含 .com 1,020,450、.uk 127,107、.net 111,073、.org 127,733；站点月度计数，不能跨月直接累加。
- 机构 https://www.securityspace.com/sspace/profile.html ，调查历史入口 https://secure1.securityspace.com/s_survey/archive.html ，数据入口 https://secure1.securityspace.com/s_survey/data/index.html 。旧历史/数据端点本次读取失败，不判定已关闭。
- 请求 1998–2001 月度响应原始名单（精确 host、观测日期、HTTP 响应状态或测量定义、原记录位置），以及允许提供组织者复核的条件。与 Netcraft 并列的独立测量路线，当前尚无行表或报价。报告的已知网站选择机制可能与现有基线高度重叠。

### 2001-01-22 DMOZ RDF 原件（Lehigh University）
- Wu, Goel & Davison, WWW 2006, §6.1 明确使用 2001-01-22 ODP RDF。https://archives.iw3c2.org/www2006/programme/files/xhtml/3115/fp3115-wu/fp3115-wu-xhtml.html
- Wu 学位论文 §7.6.4 进一步说明实验抽取 17 个主题并与 WebBase 对应。https://wume.cse.lehigh.edu/pubs/wu-dissertation.pdf
- 应索取当时使用的完整原始 RDF，而不是已经匹配 WebBase 的实验种子子集。保留快照日期、目录类别、原始条目和 URL，按现行同期权威目录条款审核。2015 年目录不能倒填 2001；未找到这个版本的可下载文件。

### Wolverhampton Academic Web Link Database（Mike Thelwall）
- A Free Database of University Web Links: Data Collection Issues, Cybermetrics 6/7 (2002/3), Appendix 4。https://www.academia.edu/709990/A_free_database_of_university_Web_links_Data_collection_issues ，PDF https://dialnet.unirioja.es/descarga/articulo/1231875.pdf 。
- 作者明确公布从 2000 年起多国大学网站的独立抓取链接数据库，曾提供 ZIP/按机构组织的文本原始链接；各国实际抓取日期不同，不能全部计入 2000–2001。2001 年英国 109 所大学网站批次曾用于独立学术研究，原始下载入口 http://cybermetrics.wlv.ac.uk/database/ 本次读取失败。
- 当前作者机构入口 https://sheffield.ac.uk/ijc/people/academic-staff/mike-thelwall 。请求 2000–2001 原始 ZIP、批次日期表、source URL 与 target URL 的角色定义、抓取站点列表。不要按大学域枚举子域，也不要将普通外链自动当网站成功响应。优先已抓取源页。

## P1：国家独立采集与同期目录（多源补充）

| 原始家族 | 已证实的历史观测 | 追索对象与当前状态 |
|---|---|---|
| 奥地利 AOLA | 2001-05-07至16 首轮约 666,000 URLs/1,210 sites/8.3 GB；2001-06-21 第二轮进行中约 2.7M pages/21,000 sites/150 GB，非最终总量 | https://www.ifs.tuwien.ac.at/~aola/description.html ；TU Wien/原项目负责人和奥地利国家图书馆查询 pilot 原始站点清单、抓取记录与日期。当前 ONB 开放档案始于 2009，不能据此推定 pilot 已转存。 |
| 芬兰 EVA / Nordic Web Index | 1998-03 首轮约 1.8M documents/7,500 .fi sites；1999 原报告注明 NWI 索引包含 checked date、last modified、URL、headers、内容类型、MD5 | https://extra.kansalliskirjasto.fi/tietolinja/0199/evaart.html ；国家图书馆与 Finnish CSC/FUNET 追查旧 NWI 索引备份、EVA 首轮和后续原件。2003 报告 https://extra.kansalliskirjasto.fi/tietolinja/0203/webarchive.html 记第一轮 11.7M files、40M locations，但本次未确定该轮确切日期，不计入目标年库存。第二轮 2002-09 已出界。 |
| 智利 TodoCL | 2000、2001 年约 7,468/21,204 crawled sites，独立搜索引擎抓取；不同论文对页面数略有差异 | Ricardo Baeza-Yates 作者入口 https://users.dcc.uchile.cl/~rbaeza/ 。追索两批实际抓取站点、URL 和日期；发现但未抓取的 sites 分开。现存文件与许可未确认。 |
| 比利时 PROMISE / KBR | 2019 RESAW 报告对 1997–1999 的九卷同期互联网目录数字化，89,084 原始 URL 记录，去重 34,413 URL；后续卷到 2000 年的原书另查 | 请求 KBR/Ghent PROMISE 研究组保留按原书卷、日期、页、条目组织的未跨年去重表及扫描定位。只用原书内容，不使用 Common Crawl 衍生查验列。具体开放数据下载未确认。检索题名 Unearthing the Belgian web of the 1990’s: a digitised reconstruction；原书 Net Directory ISSN 1374-6251。 |
| GE97 | 2026-09-08 研究指南称约 75,635 目录记录，来源含原始书刊、光盘、Usenet、Scout、1995 Lycos；不同日期页面显示不同库存数 | https://ge97.com/find-old-websites ，https://ge97.com/ 。查询是否有允许研究使用的 URL、同期来源、年代及条目定位导出，避免复制私人邮箱等个人字段。1995 Lycos 单独按扩展年处理；现代整理日期不等于历史见证。现未证实批量下载。 |

## 与上一轮路线衔接
NTCIR/NW100G-01 仍是有正式学术数据申请机制的首选之一，https://www.nii.ac.jp/dsc/idr/en/ntcir/ntcir-web-docdata.html 。不同文献所述采集年范围存在差异，必须按原始记录日期限制到 2001。Zenodo 黄页研究数据仍是明确可定位的下载物，但须区分独立印刷目录与 IA 衍生字段，详见上一轮策略。
TREC WT10g/VLC2 属 IA 原始观察链，不能当成独立爬取；GOV 和若干 LAW 图始于 2002，排除出核心计分。OCLC 随机 IPv4 测量的总体推计并非真实 hostname 名单，暂不投入。新国家档案的现行接口不能证明 1990 年代 pilot 数据已纳入。
　
## 获取流程（不自动发邮件）
1. 按原始采集 family 去重，优先 SPIRIT、SecuritySpace、2001 DMOZ、Thelwall；并行确认 NII 学术许可。
2. 向保管方询问是否保存具体版本，是否可提供轻量 URL/日期/HTTP 状态/原件定位表；若不能出库，询问在馆内或保管方环境按双方许可执行离线统计的可能。不得未经授权把本地候选或基线发送给第三方。
3. 得到材料后检查权利、摘要、日期语义与 exact hostname，保留观察记录和可审核出处，按年度与冻结基线离线求差；统计独立 hostname-year、重复率、合格 EED 和来源互补性，而不是以文档数估算收益。
4. 大规模线索在材料和权限未确定前，不建立空转采集任务；小型独立目录优先直接审核，不用 IA 逐条补证。保留既有停止条件。
　
## 通用询问文本（草稿，未发送）
Subject: Request for historical 1996–2001 web-crawl metadata or directory snapshot
　
I am investigating historical web coverage and preservation. Your publication documents a web collection or directory from the period 1996–2001. Does any original copy, URL inventory, crawl log, or dated directory export survive? We are particularly interested in the original URL, observation date or crawl batch, HTTP response metadata where available, and a record locator. A lightweight metadata extract, rather than the entire collection, would be sufficient for an initial study. Please advise on access, permitted research use, and whether limited evidence may be independently audited under the applicable license or agreement. We would not redistribute restricted raw content.
　
## 核查边界
此次实际阅读了同期报告、研究论文、机构入口；SPIRIT、DCU 的 PDF 文本可读，截图请求缓存失败。部分历史下载端点无法读取；这不证明文件已消失。没有新来源获得门槛级可审核交付，没有新产率。精确文献页、接洽入口与取证角色已给出供下一步人工追索。