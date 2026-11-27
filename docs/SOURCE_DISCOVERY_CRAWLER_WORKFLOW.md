# Creeperman：自主资料发现爬虫工作流

本文件是 2026-11-25 用户要求暂停外联、优先从学术文献与国际项目形成发现工作流之后的执行入口。取代 ACQUISITION_PRIORITY 的外联优先顺序，保留其已核实原件线索。不要发邮件、提交申请、购买数据、重复遍历旧 ISC/辅助年交集或恢复已停止的候选请求。当前核心剩余目标仍以冻结基线与本地结算为准；新模块不产生合格 EED。

## 1. 工作对象改变：发现资料对象，不是再扩大 hostname 池

两类前沿分开：

1. **资料前沿**：论文、数据集记录、项目目录、实际可定位文件。元数据和链接关系能够引出新的可处理物件。记录当代发现时间、原始研究中声称的年代、采集家族、原件版本及文件定位。
2. **历史证据前沿**：只有真实的历史观察、URL/日期/HTTP 记录、同期适格目录条目或带有明确定义的链接图，才能进入逐年差集与规则裁决。历史外链是线索，不从源页面日期推出目标页面响应。当前网页和当代仓库描述中的 1999、2000 等字符串不提供目标年的网站证据。

从资料对象进入历史观察是一道显式接合：下载已确认可公开使用的文件；验证 SHA、文件结构、日期语义和采集祖源；生成 SourceSlice 与现有 observations/证据账本。候选池仅辅助连接，不要求新证据目标先在候选池出现。全局以 exact hostname-year 求差，不按来源相加重复 EED。

## 2. 文献机制与可复用实现

| 原始工作 / 国际项目 | 真实实现或数据模型 | 本项目的迁移 |
|---|---|---|
| Chakrabarti et al., [Focused Crawling, WWW 1999](https://www.cse.iitb.ac.in/~soumen/doc/www1999f/pdf/www1999f.pdf), §3 | classifier + distiller + dynamic frontier；distiller 识别可以通向大量相关页面的入口 | 将资料目录、文件清单、论文方法节/数据节视为入口，而非要求它们本身提供 EED |
| Barbosa & Freire, [An Adaptive Crawler for Locating Hidden-Web Entry Points, WWW 2007](https://doi.org/10.1145/1242572.1242632), §3 | 利用内容、链接和带延迟价值的路径学习如何找到稀疏入口 | 按资料关系扩展，保留没有即时 EED 但能找到原始目录的页面；实际收益尚未测定，不假定论文中的提升倍数可迁移 |
| [ACHE](https://ache.readthedocs.io/en/latest/) 0.15.0 | SeedFinder、link classifier、frontier、按域多样性选择、online learning | 复用有限查询、分类、探索与利用、重用已取得响应的思想；现版本自有 Python 轻量前沿，不复制 Java 运行时或旧搜索引擎 HTML 抓取 |
| Noy et al., [Google Dataset Search, WebConf 2019](https://research.google/pubs/google-dataset-search-building-a-search-engine-for-datasets-in-an-open-web-ecosystem/) | 聚合、规范化和消歧数据集的结构化元数据 | 资料 ID、版本、分发文件和许可分别记录；现代记录发布时间不作历史抓取年 |
| [Scholix / OpenAIRE ScholeXplorer](https://scholexplorer.openaire.eu/documentation) | 按 PID 连接 publication/data/data，记录关系类型 | 从 Crossref 的参考文献/relations、DataCite 的 relatedIdentifiers、Zenodo 的 related_identifiers 递归发现对象；ODU 等旧资料未必有 DOI，因此还要解析文本 |
| [GROBID](https://github.com/grobidOrg/grobid) / [DataStet](https://github.com/kermitt2/datastet) | PDF→结构化 TEI，抽取引用上下文、数据集显式/隐式提及 | 复用其 TEI 或本地文本输出，不执行模型训练；当前导入器解析 ref/ptr/idno、HTML anchor 与文本 URL；隐式数据集的 NER 和 GROBID 服务部署仍未接入 |
| [IIPC collections access](https://netpreserve.org/projects/collections-access/) / Archives Unleashed 的 [derivative datasets as finding aids](https://doi.org/10.1080/23257962.2022.2100336) | 收藏元数据、轻量派生数据、原始 WARC 三层 | metadata→manifest→只取所需原件。IIPC 当代专题 collection 本身大多超出 1996–2001，仅视为工具/来源导航 |
| Holzmann et al., [Tempas v2, WebSci 2017](https://www.helgeholzmann.de/papers/WEBSCI_2017.pdf), §§4.1–4.3/6 | 时间锚文本索引、ArchiveSpark selective loading | 按实际观察年组织本地入链描述，查询命中后再决定取证。原实验索引源为 IA 提供的 1996–2013 德国网页，早年稀疏；不是新增独立档案，当前服务与数据可取性未绑定 |
| [OAI-PMH](https://www.openarchives.org/OAI/openarchivesprotocol.htm) §3.5 / [harvester guidelines](https://www.openarchives.org/OAI/2.0/guidelines-harvester.htm) | ListRecords/resumptionToken 与断点续取；datestamp 为 metadata 变更时间 | 作为后续机构库 adapter 规范；本版未实施 OAI-PMH 客户端，不能把它列为已支持 |
| [Protego](https://github.com/scrapy/protego) | robots.txt 匹配及 Crawl-delay/Request-rate | scoped page crawler 中真实使用；所有 robots GET 也计入预算 |

ACHE 固定版本 326f06779eb3d425deb48f5fe804942828298a99 的具体代码：
- [SeedFinder.java](https://github.com/VIDA-NYU/ache/blob/326f06779eb3d425deb48f5fe804942828298a99/ache/src/main/java/achecrawler/seedfinder/SeedFinder.java)：maxQueries、maxPages、minPrecision、QueryGenerator/QueryProcessor。其旧 Google/Bing/BingAzure 适配不直接复用。
- [MaximizeWebsitesLinkSelector.java](https://github.com/VIDA-NYU/ache/blob/326f06779eb3d425deb48f5fe804942828298a99/ache/src/main/java/achecrawler/link/frontier/selector/MaximizeWebsitesLinkSelector.java)：按 getTopLevelDomainName 的实现分组，组内有限优先队列再轮流选择；本题按观察家族探索而不是假定该分组就是采集血缘。
- [ForwardOnlineLearning.java](https://github.com/VIDA-NYU/ache/blob/326f06779eb3d425deb48f5fe804942828298a99/ache/src/main/java/achecrawler/link/classifier/online/ForwardOnlineLearning.java)：从 relevant URL 重新训练并替换 outlink classifier。没有本地合格产率训练数据之前不把相关性替代证据收益。

## 3. 当前可执行前沿

代码 source_frontier.py 与 source_pages.py，共享本地 SQLite，存储 tasks、proposals、edges、resources、observations、documents、bodies、attempts 与 provider cooldown；目录爬虫另存 page_tasks、page_edges、page_requests、robots_cache 等。源数据与发现账本存 work/，不要上传私人数据或竞赛候选。

### 3.1 公开学术/数据目录

实际支持：

- [Crossref REST](https://www.crossref.org/documentation/retrieve-metadata/rest-api/)：works search/detail，DOI、链接、relation、reference；不自动付费或调用搜索引擎页面。
- [DataCite REST](https://support.datacite.org/docs/how-do-i-query-the-rest-api-and-whats-in-the-response)：DOI search/detail、relatedIdentifiers、landing、contentUrl、rights/date claims。
- [Zenodo REST](https://developers.zenodo.org/) Records：search/detail、文件名/大小/checksum/links 与 related_identifiers。
- IA [item search](https://archive.org/developers/item-search-apis.html) 和 [MDAPI](https://archive.org/developers/md-read.html)：advancedsearch.php 的有限结果窗口及已观察 identifier 的 metadata/files。这里是 archive.org 的**资料物件**目录，而非 web.archive.org 的 hostname CDX 查询；不自动恢复先前被 503 中止的候选试验。

未在本环境获得 DataCite、Zenodo 和 IA 实际 API 响应（Web 读取失败），因此当前验证依赖文档与固定响应；本地真实首批需确认当前公开接口、速率、返回结构及访问许可。OpenAlex、OpenAIRE Graph、re3data、OAI-PMH 等可在后续根据实得收益接入，不虚构已经运行的适配器。

入口 config/source_frontier_seeds.json：原始爬网、HTTP 测量、历史目录、磁盘介质，英/法/德/西/葡/日/中区域检索。历史年份出现在检索内容而非把论文 publicationYear 限定于 1996–2001；后来研究可能公开更早物件。已知 Zenodo/DMOZ item 仅用于具体文件清单回收，若本地已处理则从 seed 清单去掉，不重开。

初始化与本地真实运行（先检查来源使用条款和授权窗口）：

    python -m pip install -e ".[source,test]"
    python -m creeperman.source_frontier --db work/source-frontier.sqlite init --seeds config/source_frontier_seeds.json
    python -m creeperman.source_frontier --db work/source-frontier.sqlite run --providers crossref datacite zenodo --max-requests 30 --interval 4 --max-depth 3 --max-pages 2 --max-children 6 --user-agent "Creeperman/0.3 (research; your contact)" --allow-public-catalog
    python -m creeperman.source_frontier --db work/source-frontier.sqlite export --out work/source-discovery-001

30/4/3/2/6 仅为演示 CLI 的有限窗口，非实际配额或预登记的实验样本数。先按本地实际服务条件选择适用 provider 和请求预算。archive.org 如获准使用可在独立有限窗口添加 ia；同一提供者不运行两个获取进程以放大预算。401/403 留为 access block，429/503 停止该提供者并尊重 Retry-After；没有自动盲重试。started 后进程退出属于未决，保留 raw/attempt，不自动重复请求。分页只是有限发现，不是全库检索完备证明。当前一个活动进程使用同一个 DB 锁；跨机 quota/租约未实施。

任务选择先按家族已尝试次数保持探索多样性，再按类型、关键词/年代提示和深度排序；不是训练模型或实测成功概率。每个返回页保存全部观察、候选扩展 proposals；只准入有限子任务，其余保留供审查。可将明确高价值 proposal 加入：

    python -m creeperman.source_frontier --db work/source-frontier.sqlite admit --proposal-id ID

### 3.2 文献与公开项目目录爬取

可将合法取得的论文 PDF 用 GROBID 本地转换为 TEI 或 pdftotext 转为文本；保存原 PDF/文本及原始文献 URL，不执行嵌入脚本。当前项目不安装/启动 GROBID：

    python -m creeperman.source_frontier --db work/source-frontier.sqlite import-document --input work/paper.tei.xml --format tei --source-url "https://PUBLIC_ORIGINAL_PAPER_URL" --family original-crawl

已有 HTML 用 --format html，纯文本 --format text。识别实际 URL 与 DOI，留存 anchor/上下文、位置、父对象 SHA；已识别的公开目录 ID 自动进入任务前沿。其他链接只是待检查 locator，不自动跨站跳转。现代网页的 HTML 解析不同于历史原件 replay URL 去壳；不要混用。

对官方项目目录、期次与已确认公开 finding aids，可以直接运行 scoped 爬虫。初始 scopes config/source_page_scopes.json 已绑定实际官方入口：Internet Scout、IIPC 工具/研究目录、Arquivo CDXJ 文件目录、Archive95 原件清单。根据现有覆盖删除已消费范围；只允许明确批准的 HTTPS host/path，默认不扩展含 query 的链接、自动跳转、外部 host、文件下载、登录、表单或浏览器执行。跨站链接仍保留，可审查后增加新的窄范围。

    python -m creeperman.source_pages --db work/source-frontier.sqlite init --scopes config/source_page_scopes.json
    python -m creeperman.source_pages --db work/source-frontier.sqlite run --max-requests 30 --interval 4 --max-depth 2 --max-children 15 --user-agent "Creeperman/0.3 (research; your contact)" --allow-public-pages
    python -m creeperman.source_pages --db work/source-frontier.sqlite export --out work/page-discovery-001

robots GET 也占预算，未知规则/解析失败或访问阻断停止该主机；同 host 缓存 robots 并遵守 crawl-delay/request-rate，拒绝转向未批准范围。实际保存响应字节及 SHA；页面解析生成共享 documents/resources/edges，后续继续运行 source_frontier 处理新出现的公开目录 ID。允许额外页面 scope 必须由本地操作者确认 URL、条款及实际公开访问，不能按候选根域无限扩展。页爬虫不自动下载二进制，非 HTML 响应只留待审查。

### 3.3 获取前核对本机库存

在同一个私有发现库中绑定本地文件总账。TSV 使用 `path / bytes / sha256` 或 `相对路径 / 字节 / SHA256` 列，路径相对于所给根目录。下载收据使用 JSON 数组，每条成功记录含 `url`、`state=downloaded`、数值 `status=200`、`bytes` 和 `sha256`，可带 `final_url`。重新绑定会在一个事务中替换旧索引，可重复指定 `--receipt`。

    python -m creeperman.source_frontier --db work/source-frontier.sqlite bind-local --inventory work/local-inventory.tsv --root work/materials --receipt work/retrieval_manifest.json
    python -m creeperman.source_frontier --db work/source-frontier.sqlite check-files --input work/new-files.jsonl --out work/precheck-001
    python -m creeperman.source_pages --db work/source-frontier.sqlite reuse-local

`check-files` 接收逐行文件描述符，例如 `{"url":"https://example.org/v1/collection.tgz","size":12345}`，可提供 `declared_checksum`（如带 `sha256:` 前缀的十六进制值）、`declared_sha1` 或 `declared_md5`。正常 `source_frontier export` 也会自动核对每一条文件观察。SHA-256 直接查总账索引，只有较短摘要时按已知大小缩小核对范围。回读命中的本地文件，验证它仍与总账相符，再检查来源声明的摘要。不同路径可复用相同内容。

| 预检结果 | 如何使用 |
|---|---|
| `reuse_local` | 直接从记录的本地路径核对原件、出处与日期。 |
| `review_local_snapshot` | 完整下载收据和本地字节支持复核同一 URL 的已保存版本。远端当前版本仍待确认。 |
| `needs_review` | 进入 `acquisition_queue.jsonl` 供人工复核。仅 HTTP/HTTPS 协议不同但其余地址相同，且能回读另一协议的副本时，条目附该收据 URL 和本地路径。 |
| `duplicate_in_batch` | 同一批次的等价获取请求共用一条待办。每次观察及其来源仍保存在 `precheck.jsonl`。 |

未绑定总账时，报告显示 `inventory_bound=false`，只进行批内查重。更新文件或收据后重新绑定，再导出到新目录。来源域、文件名或历史主机命中基线均不足以跳过一个新资料对象。年度差集仍使用原有 census 与结算流程。

单批试查用 `check-files`。持续接收新清单时，将每批 JSONL 通过 `import-document --format file-descriptors` 导入同一发现库，登记真实原始清单 URL 和来源家族，随后用常规 `export` 生成累计待办。相同清单重复导入后行数保持稳定。两份清单观察到同一请求时，预检记录保留两个出处和原始行号，获取队列仅保留一次。不同摘要或版本继续单列。导出目录包含本机文件定位和原始来源信息，仅供本地使用。

对已通过 `import-document --format html` 导入的本地快照，`reuse-local` 按确切页面 URL 展开已保存的链接。页面有多个不同内容版本时保留待办。正常页面 `run` 同样先复用本地页，实际 HTTP 请求与 `reused_local_this_run` 分列。每轮本地复用量可用 `--max-local-pages` 控制。

## 4. 形成真正循环的输入输出

阶段 A：seed family（资料生成机制）→ 有限查询 → 论文/数据集/收藏/期次。
阶段 B：论文引用和实际页面链接→ 资料对象图→ DOI/ID detail → manifest/文件候选。
阶段 C：file_review.jsonl、resources.jsonl、observations.jsonl、proposals.jsonl 与 page_tasks.jsonl → 按原始采集族、年代范围、权利、可访问状态审查真实可获取的物件。metadata_date、year_mentions、checksum 声明等只是线索；跨仓镜像有独立 URL 不等于独立采集。同样的 manifest 先去重；对于未准入候选从实际链接或已保存 proposals 恢复。
阶段 D：根据确认后的具体材料，人工/Agent 调用原有 extract/describe-source；保留原件、真实日期字段、原始 host 和 locator。已有 WebKB/Usenet/JISC/DMOZ/WARC 与文本 adapter 可用；DMOZ 提取器默认年份 null，需要版本证据绑定。对新的真实格式编写小 adapter，固定输入与字段测试，严禁单凭 file name 设置日期。只把真实观察传给 census/settle。
阶段 E：以现存基线和本地裁决账本求差，统计新增合格 EED 和成本。已有网页资料、合格同期目录可直接裁决；真实捕获元数据不足时再由现有验证层有限补证，当前 v0.2 不是完整 §XIII 年度分页验收器。
阶段 F：把原件中的实际资料链接与项目/目录实体回灌**资料前沿**，历史目标外链和锚文本回灌**历史证据前沿**。旧主机也可能指向有价值的新物件，因此不能用 baseline membership 阻断来源扩展。

输出 file_review.jsonl 是待取得/复核的**文件描述符**，不是“已经下载”、不是合格证据；resources.jsonl 是按 provider/kind/identity 汇总的实体视图；observations.jsonl 保留每个父节点独立记录；同一实体的不同观测、镜像或来源祖源仍须核对。通过 raw --sha256 HASH --out PATH 获取 SQLite 中的实际保存响应，用于复核解析与来源追溯。verified_new_eed 始终为 null，只有 settle 的真实本地裁决才计算增量。

## 5. 决策：以残余证据贡献驱动，不以搜索命中数量驱动

令 B 为冻结年度基线、A 为当前已裁决新增集合、D(a) 为资料扩展动作 a 后实际获得且适格的年度键集合，边际收益定义为：

    delta(a | A) = sum_{x in D(a) \ (B union A)} w(x)

若尚未取得 D(a)，用实测同类资料/路径的获取概率、实际净新增率、权重和成本构成有范围的估计；没有样本时保留探索预算，不编造 P。延迟收益可沿发现父边归因，用同一最终年度键全局只结算一次，不能将每个祖先节点各自的收益相加。重复文件、零净新增、已耗尽的来源族减少扩展；可独立核实且未处理的分片继续消费。

每个来源批次回传实际总请求（含失败/robots/分页）、字节、文件数、已取得且日期/权限可复核的原件数、合格 distinct host-year、基线外净 EED、人工/CPU 成本。区分找到资料的成功率与取得/裁决历史证据的成功率。优先真正完成至少一个「学术文献→文件→离线观察→净 EED」闭环并保留资产；无需对已有 24 对样本重复试验。只有取得实际收益反馈后，才考虑 ACHE 式学习重排或 Temporal 批次并行。当前工作流复用 v0.2 数据处理和 Temporal/S3 能力；source crawler 的分布式执行尚未接入，首版单进程运行。

## 6. 验收与未完成

tests/test_source_frontier.py 固定样例验证 IA search→item→files、四种 JSON 契约、DOI 关系、跨节点去重、fan-out 余项留存、暂停/重启的请求预算、文献相对链接、robots 与窄 scope、无历史日期误判。CI 与原有回归一并运行。真实接口与竞赛材料仅由本地 Agent 在合法、预算明确的窗口进行实际访问。原文阅读：Focused Crawling PDF 已取得首页截图；ACHE/Tempas 文本可读但截图返回 cache miss。学术结论与本实现迁移边界见上表。

本轮不发邮件、不申请受限数据、不购买服务，不下载大型语料、不发送候选、不报告新 EED。下一阶段不再把主要时间花在生成来源列表，而是运行有界发现循环，交付可复核的实际新资料对象和净增结果。
