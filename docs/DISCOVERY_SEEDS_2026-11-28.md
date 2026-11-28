# 从哪里起爬：原件、版次与未完成操作

2026-11-28；依据 `6831270` 的已公布结果及下列公开原文核验。本文件确定可执行入口和适配器契约，**没有运行这些材料的历史提取、年度差集或裁决；本次新增 EED 为 0，材料的实际残余收益未知**。本地 G 盘库存未在此核对，以下对象统一标记 `needs_inventory_match`，不宣称是未处理的新来源。

## 1. 国际项目怎样决定起点

| 项目与原文 | 实际起始集合 | 本任务应迁移的机制 |
|---|---|---|
| [ACHE focused-crawl 教程](https://ache.readthedocs.io/en/latest/tutorial-focused-crawl.html)、[SeedFinder](https://ache.readthedocs.io/en/latest/seed-finder.html) | 先收集相关/不相关页面训练目标分类器；相关页面可直接作种子。SeedFinder 输入分类器和初始查询，生成更多查询，对搜索结果筛选，并限制查询数、分页及最低精度。 | 把“包含可定位历史原件、manifest 或映射”的资料页作为目标；聚合统计与无原件定位的介绍页不能当证据。目录可以是通向目标的中间节点。当前没有收益训练集，先用可解释规则，不声称已训练分类器。 |
| [ArchiveTeam GeoCities URL Lists](https://wiki.archiveteam.org/index.php?title=GeoCities_URL_Lists&oldid=58443) | 共享现成 URL 清单：`ALL-GEO-SEEDS-20090730.txt.bz2` 与 IA 使用同一清单；另一清单声称超过 70 万个网站。 | 从已知枚举和原始路径映射开始，把可完成的清单分片交给执行器。共享种子不证明独立采集；这是 2009 年抢救的起点，不能成为 1996—2001 年证据。 |
| Arquivo，[Creating a billion-scale searchable web archive](https://sobre.arquivo.pt/wp-content/uploads/creating-a-billion-scale-searchable-web-archive-1.pdf)，PDF 第 14 页、幻灯片索引 13 | 约 50 万种子来自 `.PT/.CV/.AO` 名单、用户建议、网站目录和上轮抓取的首页；每日选择性抓取另由国家图书馆选定出版物。 | 复用已知入口并定向补充。其现网抓取始于 2007；PDF 第 10 页另述导入 IA 旧收藏和 1996 年光盘，说明历史原件接收与现网爬取必须分开。 |

[Barbosa 与 Freire（WWW 2007）](https://archives.iw3c2.org/www2007/papers/paper429.pdf)进一步用 URL、锚文本、邻近文本及通往目标的路径学习调整前沿。这里可迁移的是**允许目录页获得延迟价值**；论文没有证明我们的基线外产率。成熟项目均先定义目标和已知入口，再扩展可追踪关系，不能据此推出从任意网页全网爬取会产生稳定 EED。

## 2. 为什么任务单位必须是“版次 × 原件 × 操作”

已公布的 [WebBase 全量结果](ARCHIVE_ENGINEERING_2026-11-27.md)与 [DMOZ 版次结果](DMOZ_ARCHIVE_EDITIONS_2026-11-27.md)关闭的是实际处理范围。DMOZ 后取得完整版产生过增量，说明“这个来源看过了”不足以关闭其他版次；同一完整版完成处理后，也不能因找到新镜像再次记作新矿。

操作键至少包括 `origin_family / edition / artifact_sha256 / record_scope / operator_version`。分别记录取得原件、恢复 URL 映射、读取正文、提取外链和裁决的完成范围：有文件不等于做过全部操作，库存未知也不等于存在遗漏。先按 [库存预检](SOURCE_DISCOVERY_CRAWLER_WORKFLOW.md#33-获取前核对本机库存)核对收据、字节与摘要；能复用便只补缺失步骤。某原始主机已在基线，不应阻止其页面指向新资料；最终计分仍按同年 exact hostname 去重。

## 3. 四个已定位的入口及下一条真实边

优先顺序取决于身份映射、年代可复核性、可取得范围和增量处理成本，尚不具备估计产率的样本。先核以下小清单与映射，再决定是否取得数百 MB 容器；Archive95 是 finding aid，原始采集家族按各出版者登记。

### A. PC Press Internet CD：1996 年原 URL 映射

[复原说明](https://archive95.net/sources/pcpress)实际链接到 [原件 item](https://archive.org/details/pc-press-internet-cd)。[文件目录](https://archive.org/download/pc-press-internet-cd)列出 `PC_PRESS.ISO`；下一步是读取 [files.xml](https://archive.org/download/pc-press-internet-cd/pc-press-internet-cd_files.xml)，与本地库存核对，再定位每站的原 URL 映射文本。

输入为该版 ISO、映射文本和发行说明；输出为 `local_path → original_url`、正文定位及各自日期断言。说明记载部分映射损坏或缺失，孤儿文件保持未绑定。Archive95 声称采集于 1996-03-10 至 03-28、出版于 05 月；IA item 标 1996-03-27，须保留差异并查原件说明。优先理由是早期正文与显式映射同在一个对象中，可减少逐主机补证请求；尚无新增收益证据。

### B. Packard Bell Internet on a CD：保留下来的原链接属性

[复原说明](https://archive95.net/sources/netonacd)指向 [item](https://archive.org/details/internet-on-a-cd)；下一步 [files.xml](https://archive.org/download/internet-on-a-cd/internet-on-a-cd_files.xml)对应实际文件 `internet on a cd.cdr`。说明记载 Teleport Pro 把原链接保留在独立 HTML 属性中。

输入为容器原 HTML 和这些属性；输出为原 URL、实际保存正文及外链候选，抓取失败生成的错误页另标，不认作目标正文。Archive95 给出 1998-06-29 至 10-13 的采集区间，IA item 标出版日 1998-07-16；不能用单一日期覆盖冲突。优先理由是恢复规则明确，而不是 URL 数多。

### C. IUCr Nexus：出版方的四个目标版次

[Archive95 清单](https://archive95.net/sources)链接到 [IUCr 官方目录](https://www.iucr.org/__data/iucr/nexus/)，真实列出 [1997-01](https://www.iucr.org/__data/iucr/nexus/nexus_jan1997.iso)、[2000-07](https://www.iucr.org/__data/iucr/nexus/nexus_jul2000.iso)、[2000-10](https://www.iucr.org/__data/iucr/nexus/nexus_oct2000.iso)、[2001-10](https://www.iucr.org/__data/iucr/nexus/nexus_oct2001.iso) 四个 ISO。下一步只核这四项库存及容器发行说明、首页与镜像映射，不扩展到后期版次。

[项目作者的 IUCr 论文](https://journals.iucr.org/a/issues/2008/01/00/sc5001/sc5001.pdf)，§§2—3，说明 1996 年中起按晶体学研究、教学需要选择软件与网络资料，使用离线抓站工具制作光盘。这提供专业社群选择入口的实例。输入为特定 ISO 与其中的说明；输出为可绑定的镜像记录，映射尚未核定者保持待审。目录 2011 年修改时间是转存时间，文件名是版次线索，均不能自动设置正文观察年。其排序低于映射已明确的 A/B。

### D. World Online Digest Burgundy 3：可跟踪到正文的目录关系

[item](https://archive.org/details/wold_burgundy_30)的下一步是 [files.xml](https://archive.org/download/wold_burgundy_30/wold_burgundy_30_files.xml)；容器为 `World Online Digest - Burgundy Volume 3.0 (USA).zip`。[DiscMaster 展开目录](https://discmaster.textfiles.com/browse/39581)已能读取其中的目录原件。

已核关系是 `INSTALL.WLD → WOLD/HOME.HTM → 分类页`，并有 [WOLD/LINKS.HTM](https://discmaster.textfiles.com/view/39581/World%20Online%20Digest%20-%20Burgundy%20Volume%203.0%20%28USA%29/World%20Online%20Digest%20-%20Burgundy%20Volume%203.0%20%28USA%29.bin/WOLD/LINKS.HTM)按相同类别列当时网址。实例：Theodore Presser 条目给出 `www.presser.com`，Arts 分类连至 `WOLD/ARTS/PRESSER/INDEX.HTM`，正文写更新于 1999-03-17。这仅证明映射链可执行，不证明该主机在基线外，也不单凭自述更新日完成年度裁决。

输入为原始目录 HTML、链接表和本地正文；输出为带定位的映射及待裁决证据。IA item 标 1999-04、盘内安装文件标 1999-04-20，仍需核发行语义。DiscMaster 展示层会改写外链，应读原始字节。先完成这一个版次；[同系列卷期清单](https://discmaster.textfiles.com/cd-rom?search=world+online+digest)可提供后续真实边，不能把各卷文件数当独立主机数。

## 4. 接回现有流水线

适配器统一输出原件 SHA、容器内路径、原 URL、映射依据、日期值及语义、采集家族、操作版本与未决原因；再交给既有提取、年度差集、审查和 `settle`。需要在线补证的只是无法由原件完成的具体缺口，不能默认把全部外链送去 CDX。

本轮先采用透明顺序：本地可复用对象优先；新取得时 A/B 优先恢复明确映射，D 先读取小型目录验证绑定契约，C 先解决映射和年代。真实净 EED、重复比例、处理成本出来后再重排。零新增应关闭已完成的对象和操作，不能证明全球没有其他资料；正新增也不能外推整系列持续产率。这里确定了能反复推进并明确结束的工作流，稳定的正 EED 供应仍须以多批完整结算证明。
