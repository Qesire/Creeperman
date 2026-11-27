# 档案解析、年度差集与执行交接

2026-11-27。在冻结基线 `merge261121-3` 上，本地已裁决 **55 个主机年度，37.7812 EED**，其中本批 DMOZ 增加 11 项、5.7067 EED。分值使用任务包的官方计算器，组织者尚未复核。按冻结基线的 1% 门槛计算，仍差 764,266.683246 EED。公开收据包含原件、计算器和累计台账的指纹，执行机可据此定位正确版本。[汇总收据](../audit/archive_results_20261127.json)

| 实际读取的版本 | 年份 | 经项目主机解析后去重 | 同年已在基线 | 基线外 | 本批本地结算 |
|---|---:|---:|---:|---:|---:|
| LAW WebBase 全部 118,142,155 个 URL 节点 | 2001 | 738,469 | 738,468 | 1 | 0 项，0 EED |
| DMOZ 两份主目录的可读前缀 | 2000 | 13,834 | 13,828 | 6 | 6 项，3.2553 EED |
| DMOZ Kids & Teens 六月、十一月完整 RDF 合并 | 2001 | 8,988 | 8,983 | 5 | 5 项，2.4514 EED |

WebBase 原包为 720,229,219 字节，MD5 与发布方清单一致。唯一语法差项的后缀未通过顶级域复核，权重为零。图节点可以定位到原始 URL 的行号，逐条捕获日期和 HTTP 状态仍需其他材料支持。[LAW 数据说明](https://law.di.unimi.it/webdata/webbase-2001/) · [节点编号与 URL 顺序](https://law.di.unimi.it/tutorial.php)

DMOZ 主目录的两个归档对象各有 1,048,293 字节。实收正文摘要与 CDX 相符，gzip 在成员尾之前中断。两个前缀内的完整 XML 条目共覆盖 13,829 个主机，受损段内仍可准确解析的 URL 属性补出 5 个主机，它们均已在基线。2001 年的两份 Kids & Teens 子集通过了完整 gzip 和 XML 校验。这些观测支持表中的版本范围，整份早期主目录的净余量仍未知。11 项均能回到当年发布目录中的分类链接。10 项另有完整的条目标题和说明，余下 1 项的说明含损坏 XML，依据完整分类链接裁决。[2000 年发布目录](https://web.archive.org/web/20000815053601id_/http://dmoz.org:80/rdf/) · [2001 年发布目录](https://web.archive.org/web/20010610104128id_/http://dmoz.org:80/rdf/)

## 如何从本地原件复算

从仓库根目录安装 `python -m pip install -e ".[source,parquet]"`。以下命令使用执行机自己的输入和新建的输出目录。来源适配器保留原件指纹、确切主机及源内位置，原始证据由执行机保管。

1. **下载前核对本地库存。** 用 `source_frontier bind-local` 绑定文件总账及成功下载收据，`check-files` 检查新描述符。匹配时回读磁盘文件验证摘要。同一个原发布 URL 可能对应多个归档版本，核对快照时间、实收长度及完整性后再复用。[源码](../src/creeperman/source_precheck.py) · [命令与输入格式](SOURCE_DISCOVERY_CRAWLER_WORKFLOW.md#33-获取前核对本机库存)
2. **WebBase 节点。** 以下命令流式读取本机已有的完整 gzip，生成 `hosts.parquet`，保存源行和从零起算的节点号。[节点提取实现](../scripts/webbase_url_nodes.py)

   ```sh
   python scripts/webbase_url_nodes.py --input work/webbase-2001.urls.gz --out work/webbase-nodes
   ```

3. **DMOZ 历史快照。** 输入为归档实收的压缩字节及本地 JSON 收据。收据按文件名索引，每项含 `url`（回放 URL）、`sha256`（实收字节指纹）和 `capture`（CDX 的 `timestamp`、`statuscode`、`digest`）。解析器自行计算 CDX 用的 Base32 SHA-1 和本地 SHA-256，保存完整条目的起止行。损坏或截断的片段另存可复核的完整 URL 属性，并在 `node-audit.json` 中记录覆盖边界。这一入口针对历史 ODP 按行导出的 RDF 布局。[解析与边界恢复实现](../scripts/dmoz_snapshot.py)

   ```sh
   python scripts/dmoz_snapshot.py --receipts work/replays.json --out work/dmoz-nodes work/content.rdf.gz
   ```

   对这一批抽取结果，可用 DuckDB 建立用于求差的观测表。输出中的年份表示归档目录观察到条目的年份，保留 JSONL 供逐项复核。

   ```sql
   COPY (
       SELECT DISTINCT hostname, year
       FROM read_json(['work/dmoz-nodes/*.rows.jsonl','work/dmoz-nodes/boundary-attributes.jsonl'],
                      format='newline_delimited', columns={hostname:'VARCHAR', year:'INTEGER'})
   ) TO 'work/dmoz-host-years.parquet' (FORMAT parquet, COMPRESSION zstd);
   ```

4. **按年求差。** 以确切主机和年度扣除基线及传入的已裁决账本。复现表中的本批贡献使用先前的 **44 项**账本，评估下一批则使用最新 **55 项**账本。基线外权重是可取得合格证据时的上限。进入结算还需逐条裁决。[DuckDB 差集入口](../src/creeperman/parquet_difference.py)

   ```sh
   python -m creeperman.parquet_difference --source WebBase work/webbase-nodes/hosts.parquet --source DMOZ work/dmoz-host-years.parquet --baseline-dir work/merge261121-3 --reviewed work/cumulative/reviewed.jsonl --model work/q2_tld_top_langs.json --audit audit/baseline_summary.json
   ```

## 档案服务的分页与正文复用

**IA CDX 年度分页。** 参照 IA 的 ZipNum 分页 API，`annual-cdx` 先读页数，再按页核对同一年的确切主机、状态码及 MIME。SQLite 记录请求预算、页位、原始响应和摘要。429、503、截断或中断留下未完成状态。报告中的完成率以实际扫描的索引视图为准。每个输入 JSONL 项含 `hostname`、`year`、`baseline_mask`、`local_qualified_mask`、`source_locator`。只有来自独立来源、通过同年查重的确切主机进入验证。[IA 官方分页说明](https://github.com/internetarchive/wayback/tree/master/wayback-cdx-server#pagination-api) · [年度采集实现](../src/creeperman/annual.py)

```sh
creeperman annual-cdx --input work/independent-host-years.jsonl --state work/ia.sqlite --max-requests 50
```

默认执行离线预检。需要实际访问时加 `--allow-online`，使用同一个状态库续跑。代理由执行机配置。

**回放正文复用。** `followup --mode replay --reuse-payloads` 借鉴 urx 的 digest 去重思路。代码将经过摘要和身份核验的 HTML 存入缓存，每次按当前捕获的原 URL 和 HTML 的 `base` 重新解析相对链接。缓存命中产生发现线索，后续仍可用默认回放单独取得目标证据。在已测本地 HTML 的 8,677 次来源页观察中，仅有 40 次正文可复用，约 0.46%。项目以实测重复率评估收益。[urx 回放选项](https://urx.hahwul.com/guide/cli-options/) · [WARC 摘要规范](https://iipc.github.io/warc-specifications/specifications/warc-format/warc-1.1/#warc-payload-digest) · [回放实现](../src/creeperman/online.py)

**离线过滤与收益评估。** 列式分析参考 IIPC 的 CDX(J) 转 Parquet 工作坊，归并前过滤参考 Arquivo 的索引流水线。Creeperman 用本项目冻结的年度基线、模型和结算账本评估净余量。当前最值得取得的是有规模、可按原 URL 与观测年回查的独立原件。新版本先做本地差集，再据剩余权重与证据成本决定投入。[IIPC 2024 工作坊](https://netpreserve.org/ga2024/abstracts/) · [Arquivo 索引流水线](https://github.com/arquivo/replay-cdxj-indexing-tools)
