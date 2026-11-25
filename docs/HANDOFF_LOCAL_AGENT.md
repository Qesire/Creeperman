# Creeperman v0.2 本地 Agent 交接与执行手册

## 0. 交接边界

云端已完成实现、源码与论文对应关系、公开资料契约、测试及项目入口。2026-11-25 已在冻结基线 `merge261121-3` 上完成首轮联合差集和年度结算。继续同一轮工作时，先查看[本地统计报告](LOCAL_CENSUS_2026-11-25.md)及执行机保留的逐主机明细。

这是公共 GitHub 仓库；不要将任务包、候选、证据原件、访问凭据或临时数据提交到 Git。使用 work/ 或本地数据盘。

v0.2 首轮代码 563df05 通过 15 项离线回归和 2 项使用固定网络响应的 Temporal 测试服务集成。首轮本地结算获得 11.5612 EED。真实归档查询的批次产率、S3 与跨区服务仍待单独验证。[CI 45413440577](https://github.com/Qesire/Creeperman/actions/runs/45413440577)

## 1. 绑定本地数据（无需网络）

Python 3.11+，在仓库根目录执行：

    python -m pip install -e ".[worker,archive,test]"
    python -m pytest -q tests/test_v1.py tests/test_v2.py

已知任务包：1996-2001KnowledgeDiscoveryCompetition；既有审计绑定 merge261121-3 六年文件、q2_tld_top_langs.json 和 2026-10-20 任务书。不要假定磁盘位置。通过本地上下文定位。审计 SHA-256 是既有版本参照；若有变化，先查明实际更新原因，不绕过校验。

    mkdir -p work
    python scripts/preflight_local.py --task-root "/path/to/task" --out work/sources.json > work/preflight.json

Windows PowerShell 可用单行命令，按实际路径替换。preflight 校验模型指纹、六年文件存在及长度、登记官方 candidate_pool.txt、输出规则文件 SHA。census 完整检查六年度字节 SHA、排序及计数。对照 audit/source_manifest.json 的规则 SHA；有更新则重新确认口径。

准备新增候选资料时，创建 work/extra_sources.json：

    {"sources":[{"source_id":"actual-source-slice-001","origin_family":"actual-observation-family","format":"observations","path":"/path/to/extracted.jsonl","allowed_by_competition":true}]}

只登记获准使用且可追溯到具体文件的材料。以下命令将真实文件 SHA 与候选池组成联合清单：

    python scripts/preflight_local.py --task-root "/path/to/task" --extra-sources work/extra_sources.json --out work/sources-round1.json

具体来源入口和格式见 config/source_registry.json。它不是实际下载完成证明；不存在的材料不计入容量。优先定位 Usenet 具体分组、CMU 原版 WebKB、已有同期邮件、论文或离线原件。IA/WebBase 已近乎读完；JISC、Arquivo 的同祖源部分只在明确未消费范围时重开。较晚 DMOZ、GeoCities 只作线索。PANDORA 与 Webarchiv 先保留人工路由；自动 API 契约尚未绑定。

## 2. 候选提取与联合差集

| format | 输入 |
|---|---|
| hosts | 每行 exact hostname |
| urls | 每行 HTTP/HTTPS 原始 URL |
| observations | JSONL：hostname/original_url、observed_year（或 null）、kind；可附 locator、上下文 |
| cdxj | SURT + timestamp + JSON，使用原始 url 字段 |
| mbox | 标准 mbox |
| usenet-zip | ZIP 内 numeric-Deja separator 的 .mbox/.txt |
| webkb-tar | CMU 原版 webkb-data.gtar.gz，不是 LINQS/NetKit |
| jisc | 两列 TSV：year、sourcehost、targethost 以竖线分隔，第二列为链接数 |
| dmoz-rdf | XML/RDF ExternalPage，年份默认未知 |
| pages-jsonl | source_original_url、html、observed_year、locator、date_semantics；已明确改写回放可附 replay_provider 和 replay_url |
| text-jsonl | text、observed_year、locator |
| warc | warcio 支持的 HTML response；非全部 WARC 记录类型，不自动解决 revisit |

提取，无网络：

    creeperman extract --input "/path/to/source.mbox.zip" --format usenet-zip --out work/source-001.jsonl --allow-source

保存 CLI stdout（输入/输出 SHA、接受/拒绝数）与 .rejected.jsonl。大文件先在本地解析或依真实容器边界分片，不可任意字节切割 ZIP/tar/WARC。Worker 也可用 discovery-job 处理原始适配器。单对象上限 512 MiB（包括输出），根据实际膨胀率控制批次。

联合 census：

    creeperman census --baseline "/path/to/task/merge261121-3" --audit audit/baseline_summary.json --model "/path/to/task/equivalent_english_domain_calculator/q2_tld_top_langs.json" --sources work/sources-round1.json --out work/census-001

若只有旧候选池，使用 work/sources.json；这属于已有池摸底，不称为新来源容量。六路流式扫描全量基线，仅候选联合落盘。

输出 report.json：唯一候选、池重叠、各年缺口、TLD、各来源非加性条件 EED 上界及仅该来源提示的缺口权重。opportunities.jsonl 保存 baseline_mask、local_qualified_mask、missing_mask、hint_mask、sample URL、英语权重。core_new_candidates.txt 仅指未见于提供的核心基线、已裁决表和旧池的 hostname，不是正式完整候选导出。rejected.jsonl 保存不合格输入行。

参考 1% 最低值为 764304.4645；所有缺年 EED 是上界，带年份线索 EED 仍是条件上界，不是已证实贡献。若理论容量不足，优先找新材料；若容量足而证据未知，再进入有限在线批次。各来源非加性数据不能相加。

若已有本地审查通过的年度记录，extra_sources.json 可绑定 local_qualified：path、sha256、authority（preflight 的 authority.id）、rule_version。记录需有实际证据裁决的 hostname、year、evidence_id、validation_status=verified_web_year；不能将索引候选充作已裁决表。

## 3. 有限在线执行（先本地，再真实多地）

本地开发服务：

    temporal server start-dev

另开终端。计算 Worker 无网络采集权限；IA 与 Arquivo Collector 各一个活跃进程，每个 provider 的 lookup/replay/search/metadata 共用 SQLite 状态和请求预算。以下间隔只是起始客户端设置，实际访问条件须确认：

    creeperman worker --role compute --queue creeperman-compute --store work/store
    creeperman worker --role ia --queue creeperman-ia --store work/store --state work/ia-collector.sqlite --interval 2.5 --allow-online --user-agent "Creeperman/0.2 (real project contact)"
    creeperman worker --role arquivo --queue creeperman-arquivo --store work/store --state work/arquivo-collector.sqlite --interval 2.5 --allow-online --user-agent "Creeperman/0.2 (real project contact)"

不要通过增加同一 provider 的机器数增加配额；本地进程锁阻止同一状态被两进程同时使用。跨主机所有权仍由运维保证；旧实例未完全停止，不复制预算。429/503 触发共享冷却。没有自动跨区接管或分布式配额系统。

按 census 和提供者许可选择有限首批。以下 20 个候选只是示例，不是既定实际预算：

    creeperman route-plan --store work/store --census work/census-001 --limit 20 --batch-size 10 --round-id lookup-001 > work/lookup-001.jsonl
    creeperman dispatch --plans work/lookup-001.jsonl --limit-jobs 20 --max-inflight 2 --allow-online --out work/receipts-001.jsonl
    creeperman collect --store work/store --db work/catalog.sqlite --refs work/receipts-001.jsonl

route-plan 对 .pt 优先 Arquivo，其他主要 IA；部分欧洲/教育后缀有可选第二路。该软先验尚未用当前残余数据校准。默认只纳入有目标年线索且未覆盖的键；--include-undated 另行预算。当前排序按候选文件顺序，先 dated 再 undated；可据 opportunities.english_weight 和线索结构预选重点批次，通过 online-plan 提交。权重、频次不等于命中率。

每个计划最多 50 条在线操作；一次操作最多一次请求，不自动扩大范围或隐式重试。Activity failure 的 inflight 可能 ambiguous，不自动重复请求。dispatch 对相同 workflow ID 可附着已有任务；重跑用新 receipt 文件名，collect 按 manifest 幂等。检查失败、缺失回执后再规划。

跨区 Worker 使用实际 Temporal namespace、同一个获准的私有 S3 store。凭据用环境变量及 AWS 标准凭据链，绝不写入 Git。配置 TEMPORAL_TLS=true 与实际认证方式。Dockerfile 已提供，尚未实建容器验证；非 root 容器持久 state volume 需赋予 uid 10001 写权限，也可原生安装 Python 包。例如：

    creeperman worker --role compute --queue creeperman-compute --address YOUR_NAMESPACE_ENDPOINT --namespace YOUR_NAMESPACE --store s3://YOUR_PRIVATE_BUCKET/creeperman

dispatch 同样添加 --address 和 --namespace。真实 S3 条件写、认证、跨地区接入仍需验收，不由 CI 结果推定。未经用户授权不自动开通收费资源。

## 4. 补证、反馈与来源追溯

从 preflight 或 census report 读取 authority.id；以下用 AUTH 替代。每轮均执行 dispatch + collect，并用新 receipt 文件。仅发有必要的任务：

    creeperman followup --store work/store --db work/catalog.sqlite --authority AUTH --mode expand-host --provider ia --round-id expand-001 --limit 20 --batch-size 10 > work/expand-001.jsonl
    creeperman followup --store work/store --db work/catalog.sqlite --authority AUTH --mode replay --provider ia --round-id replay-001 --limit 20 --batch-size 10 > work/replay-001.jsonl

expand-host 只对 exact-URL 查询仍缺年者扩大到同一 host，不扫子域。fallback 对有软路由理由且仍有缺口者生成第二馆任务。replay 每个 host-year 选择尚未尝试的 witness；已 review-ready 的同馆年度不自动重复下载。明确拒绝后需替代 witness 时，用 online-plan 另列有界输入。Arquivo 可同样 followup。

回放不跟随重定向、不从活站取得、不运行历史脚本；核对实际 Memento-Datetime、original host 与目标年。缺少身份头、日期不符、截断均待处理。CDX digest 和实际响应 body 哈希分开。HTTP 200 和质量提示不等于最终资格。

IA 回放所得 x-archive-src 按 item 去重、核对 item 与文件名：

    creeperman followup --store work/store --db work/catalog.sqlite --authority AUTH --mode metadata --provider ia --round-id lineage-001 --limit 10 --batch-size 5 > work/metadata-001.jsonl

仅生成来源调查结果。冷门 item 不等于独立来源、基线遗漏或历史物件可取得。确认年代、保管链及未处理范围，再登记材料。

引用与锚文本回流：

    creeperman export-observations --store work/store --db work/catalog.sqlite --out work/feedback-001.jsonl
    creeperman signatures --observations work/feedback-001.jsonl --out work/queries-001.jsonl --limit 20 --words 5
    creeperman online-plan --store work/store --provider arquivo --action search --input work/queries-001.jsonl --authority AUTH --round-id text-001 --limit 20 --batch-size 10 > work/search-001.jsonl

反搜是候选与上下文，不将旧地址的证据移给新地址。反馈文件作为版本化来源，与旧源联合 census；大规模时按分片库存组织，不每处理一条 witness 就重扫全基线。

## 5. 证据裁决与年度结算

    creeperman review-export --db work/catalog.sqlite --authority AUTH --out work/review-001.jsonl

仅输出符合基本回放绑定的 pending_review 项；原响应按 response_ref 取得。真实内容、身份、时间、网站语义、来源定位与现行规则必须审查。高频 digest、主题漂移、模板/停放只作复核提示。不得自动把 pending_review 改成 verified_web_year。

本地裁决文件保留 review 输出字段；合格才增加（此为字段补充示例，不是完整决策行）：

    {"validation_status":"verified_web_year","evidence_type":"archive_replay","evidence_id":"unique-reviewed-witness","reviewer":"actual-reviewer","reason":"actual case-specific reason under rule","rule_version":"actual-rule-version"}

archive_replay 需要对应 manifest_hash、ordinal、authority、hostname、year、original_url、实际 catalog 记录和存储 body。可信同期目录、图、原件等用 historical_directory、historical_graph、original_archive_record 或 reviewed_original_material，记录 source_path、source_sha256、record_locator、date_semantics，说明该来源如何直接满足规则。多条弱线索不替代证据。拒绝和未决结果保留，不回填年份。

    creeperman settle --baseline "/path/to/task/merge261121-3" --audit audit/baseline_summary.json --model "/path/to/task/equivalent_english_domain_calculator/q2_tld_top_langs.json" --decisions work/reviewed-decisions.jsonl --rule-version actual-rule-version --db work/catalog.sqlite --store work/store --out work/settled-001

settle 对已裁决 exact hostname-year 去重、复核权威与存证字节或本地源文件 SHA，并与冻结基线求差，输出 1996.txt 至 2001.txt 的**本地新增量**和 Decimal EED。不是合并后完整主表，也不是组织者验收。正式包依据真实规则与官方计算器独立核对；扩展年及最终打包仍由本地 Agent 完成。

## 6. 交付判据与未完成项

首轮应交付真实任务包版本/指纹、实际来源物件与覆盖账本、联合 census report.json、首个有限批次计划与回执、请求计数、潜在 witness 与局部未完成范围、实际裁决和年度差集（若已形成）。真实容量报告优先于大集群。

两馆端点适配、回放与全文、元数据、编排、反馈、结算已经实现，但仅经固定网络响应验收。真实接口、访问条件、S3、多地区认证及性能需要在授权环境有限验收。未绑定的自动馆 API、完整 CDX 分页遍历、revisit 原件链、目标年历史 RDF 实际库存、全量 WARC 各类型、最终竞赛打包不是本版本已验收的功能。

来源和论文/代码依据见 docs/ 中既有文献与源码审计，以及 [Arquivo CDX](https://github.com/arquivo/pwa-technologies/wiki/URL-search%3A-CDX-server-API)、[Arquivo 全文 API](https://github.com/arquivo/pwa-technologies/wiki/Arquivo.pt-API)、[IA MDAPI](https://archive.org/developers/md-read.html)、[Temporal Python SDK](https://docs.temporal.io/develop/python/client/temporal-client)。本地 Agent 只需针对当前可用性及新版本变化核查，不再重复泛调研。
