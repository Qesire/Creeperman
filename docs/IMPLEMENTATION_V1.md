# Creeperman v0.1：离线差集与全球批次 Worker

## 范围

从已定位、获准使用的本地资料分片或候选清单开始，完成精确 hostname-year 缺口盘点、有限计划生成、批次分派、结果持久化和归并。核心六年基线为 merge261121-3，现有 140,073,629 行的 SHA-256、计数及 76,430,446.4446 EED 参照 audit/baseline_summary.json。

当前是候选与潜在 witness 流水线，**没有自动认定任何网站证据合格，也没有生成可提交年度主表**。此前已读 IA/WebBase 范围不得重新作为无条件新增源。完整基线、权重原件、candidate_pool 和真实资料分片不在 Git 仓库内，需要在本地执行机提供。

## 1. 离线差集摸底

采用旧 Creeper 年度 bitmap 的核心语义。利用已经核实排序的年度文件做六路流式合并，将同一 hostname 的年度按位 OR；在本地 SQLite 中仅保存候选联合及其来源统计，不把 1.40 亿基线行全部插入数据库或载入 Python 内存。逐一核对输入 SHA、排序、计数；任一基线或来源变动都拒绝发布。第一次全量扫描仍需读完基线，实际耗时未测。建议把待盘点来源合成一次输入清单，避免每批重新扫描基线。

安装 Python 3.11+：

    python -m pip install -e .

来源清单示例（每条 sha256 用 describe-source 生成；路径可以相对于清单文件，也可以为绝对路径）：

    {
      "sources": [
        {"source_id":"official-pool","origin_family":"competition-pool",
         "role":"existing_pool","format":"hosts","path":"/data/merge261121-3/candidate_pool.txt",
         "sha256":"REPLACE","allowed_by_competition":true},
        {"source_id":"usenet-01","origin_family":"usenet-original",
         "format":"observations","path":"/data/extracted/usenet-01.jsonl",
         "sha256":"REPLACE","allowed_by_competition":true}
      ]
    }

    creeperman describe-source --input /data/extracted/usenet-01.jsonl \
      --source-id usenet-01 --origin-family usenet-original \
      --format observations --allow-source

支持 hosts（每行一个 hostname）、urls（HTTP URL）、observations（JSONL，hostname 和/或 original_url、observed_year、kind）、cdxj（key timestamp JSON；URL 来自 JSON 原字段）以及 .gz。候选时间只作提示，不是证据。原始 mbox、WebKB tar 等格式需要独立提取适配器，当前不伪称已有全文或引用抽取器。禁止把 Common Crawl 作为候选来源；source/line、SHA 和 origin_family 保留。allowed_by_competition 是操作者确认，不是程序自动鉴定授权。

    creeperman census \
      --baseline /data/task/merge261121-3 \
      --audit audit/baseline_summary.json \
      --model /data/task/equivalent_english_domain_calculator/q2_tld_top_langs.json \
      --sources /data/sources.json --out work/census-001

如已有经过外部裁决的本地年度账本，可先取得 authority id：

    creeperman authority --audit audit/baseline_summary.json \
      --model /data/task/equivalent_english_domain_calculator/q2_tld_top_langs.json

在 sources.json 添加 local_qualified 对象：path、sha256、authority（上述 id）、rule_version；该 JSONL 每行需有精确 hostname、核心 year、validation_status=verified_web_year、evidence_id。它只用于抑制重复补证，裁决和见证真实性由上游负责；系统不凭标志自行产出正式成绩。

输出：

| 文件 | 内容 |
|---|---|
| report.json | 各来源、联合唯一 host、旧候选池重叠、缺年和带年份线索的缺口、TLD 分布、条件 EED 上界 |
| opportunities.jsonl | exact hostname、baseline_mask、本地已裁决 mask、missing_mask、hint_mask、来源抽样 URL/行号 |
| core_new_candidates.txt | 仅相对已提供核心基线、本地账本与候选池的新 hostname；不是正式活动候选导出（扩展年未接入） |
| rejected.jsonl | 无效或身份冲突行的来源和定位 |

年度位图第 0..5 位代表 1996..2001。missing_mask = 63 & ~(baseline_mask | local_qualified_mask)。本地缺口不是“网站存在”，all_missing_eed_ceiling_not_score 是极乐观的上界；hinted_missing_eed_ceiling_not_score 仅对有年份提示的集合做条件求和。各来源列不可相加，联合列已经全局精确去重。qualified_new_eed 固定为 null。此阶段不增加网络请求。

## 2. 真正的 Temporal 批次 Worker

    python -m pip install -e ".[worker,test]"

本地装有 Temporal CLI 时：

    temporal server start-dev

另一终端启动仅离线的计算 Worker：

    creeperman worker --role compute --queue creeperman-compute-local --store work/store

分派资料任务：

    creeperman discovery-job --store work/store --input /data/input.jsonl \
      --source-id example-source --origin-family actual-origin --format observations \
      --allow-source > work/job.json

    creeperman submit --queue creeperman-compute-local --job work/job.json --wait > work/result.json

也可以不启动 Temporal，直接复现同一个计算活动：

    creeperman run-local --store work/store --job work/job.json > work/result.json

result.json 中只有 manifest_ref（SHA-256 与字节数）；对象存储按 objects/<sha256> 寻址。使用 get 取得 manifest，再取得 manifest.result 指向的记录文件：

    creeperman get --store work/store --ref '{"sha256":"...","bytes":123}' --out work/manifest.json

归并一行或多行 result JSONL：

    creeperman collect --store work/store --db work/results.sqlite --refs work/result.json

同一 manifest 重复导入幂等；不同尝试单独保留，潜在 witness 用 authority、exact hostname、时间、original、provider、digest 去重；按 authority 报告唯一潜在 hostname-year。此 catalog 尚不是竞赛资格裁决器。计算输出可用 get 下载后按 observations 输入 census（含 rejected 行会进入拒绝清单）。

## 3. 有界补证计划（需单独启用）

只从冻结 census 的未覆盖年度生成计划。默认只调度带核心年提示且该年仍未覆盖的目标；include-undated 可再加入没有对应缺年提示的候选；offset 支持消费下一个有界窗口。每个 hostname 在本批只出现一次。每个计划默认最多一次元数据请求/host，当前 **不是完整 CDX 遍历**。

    creeperman plan --store work/store --census work/census-001 \
      --limit 100 --batch-size 20 > work/plans.jsonl

每行是一个独立的小型 envelope，挑选其中一行保存为 job.json 后才提交。round-id 用于明确授权和重新规划的后续轮次；不能作为自动无限重查开关。检查历史结果和新线索后才开新轮次。不能把 offset 或轮次当成已完成查询范围。

显式启用 IA collector；先确认提供者允许的访问方式、身份、请求预算与实际适用条件。默认 2.5 秒间隔是保守本地客户端设置，非配额承诺。整个部署只允许一个活跃 IA 采集进程，不能跨地域重复启动以放大配额：

    creeperman worker --role ia --queue creeperman-ia \
      --store work/store --state work/ia-collector.sqlite \
      --interval 2.5 --allow-online --user-agent "Creeperman/0.1 (your project contact)"

    creeperman submit --queue creeperman-ia --job work/job.json --wait

查询优先 exact original URL，否则 same-host 范围；筛选 200/HTML 元数据、服务器 original host 过滤并本地再次解析。只请求 50 行，不 collapse、不 domain 子域扫查、不拉正文、不跟随 HTTP 重定向。所有结果仍为潜在证据；空、截断、错误、预算耗尽均不能写成全局无历史记录。原响应以不可变对象保存。429/503 共享冷却、剩余任务延后；SQLite 记录已完成目标及 ambiguous inflight，在线 Activity 不自动重试；同状态目录重放已完成结果不再次请求。跨区接管前先停止旧 collector 并迁移状态，v0.1 未实现跨机分布式限流或接管租约。

当前只实现 IA CDX 一种网络适配器；其他档案、路由、正文取证和裁决尚未实现。首次运行不应直接派发上百万计划。以真实离线 census 判定是否有足够缺口库存。

## 4. 全球执行与传输

计算 Worker 可以从多个地区主动连接同一个可访问的 Temporal 服务，在不同队列独立领取资料批次。共享 S3 bucket/prefix 作为 store（AWS SDK 读取本地凭据链，不在代码或 envelope 中传密钥）：

    export TEMPORAL_TLS=true
    # 如使用支持 API key 的 Temporal Cloud，在环境变量中安全配置 TEMPORAL_API_KEY
    creeperman worker --role compute --queue creeperman-compute-eu \
      --address YOUR_TEMPORAL_ADDRESS --namespace YOUR_NAMESPACE \
      --store s3://YOUR_BUCKET/creeperman

对象引用只含 SHA 和长度；所有 Worker 必须使用相同的 store 根。S3 条件写禁止覆盖；本地模式以原子硬链接发布；读回时验证完整长度与 SHA。单对象上限 512 MiB；源文件及解压后的输出必须预先切成更小分片，大语料不要塞进 Workflow 参数。工作流 ID 来自任务契约 hash，拒绝重复提交。离线活动失败可重新计算，在线活动禁止隐式重试；输出文件持久化后才发布最终 manifest，结果导入本地目录由 catalog 统一完成。

S3/真实跨区接入尚待部署验收；当前没有搭建公网 Temporal 服务，不能以本地行为保证跨区吞吐。首版不增加 PostgreSQL/PGMQ、NATS 或额外自建全局租约服务。

## 5. 固定样例与验收

    python -m pip install -e ".[test]"
    python examples/make_fixture.py work/synthetic
    creeperman census --baseline work/synthetic/synthetic-baseline \
      --audit work/synthetic/audit.json --model work/synthetic/model.json \
      --sources work/synthetic/sources.json --out work/synthetic-census
    python -m pytest -q

样例预期（合成，不是竞赛产率）：8 个全局不同 host，其中 5 个未出现在核心基线，39 个理论缺年，4 个带目标年线索的缺口；后者条件 EED 上界为 2.5284，qualified_new_eed 为 null。测试覆盖重复、裸域/www、已有候选池、已裁决缺年屏蔽、哈希失败不发布、CDX original/时间过滤、结果重放与重复导入。

启用真实本地 Temporal 测试服务（需要 SDK 测试 server 二进制或下载能力）：

    python -m pip install -e ".[worker,test]"
    RUN_TEMPORAL_SMOKE=1 python -m pytest -q tests/test_temporal.py

Windows PowerShell 设置环境变量用 $env:RUN_TEMPORAL_SMOKE="1"。测试服务仅执行合成离线活动，不访问外部档案。实际运行结果以 CI 或执行日志为准。
