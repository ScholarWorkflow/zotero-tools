---
name: zotero-paper-tagger
description: 给 Zotero 教授分类下的论文条目批量打四类标签——大学名（全称）、教授名（照搬分类名）、`一作`（仅当条目第一作者就是这位教授）、`通讯作者`（优先按论文显式通讯记录判定，无记录时回落末位作者惯例且作者 ≥2 人）。姓名比对共 7 条规则：①②③精确全同类自动打；④⑤⑥缩略/颠倒形进待人工确认；⑦署名簿——从教授自己分类里攒「确认是他」的全名种子，长出同源缩略变体（`Surname A.` / 裸姓），分类内无冲突就自动打、有冲突降级存疑，落盘 _署名对照.json。打完后在 Zotero 左下角标签选择器点一个标签即可一次筛出：某学校全部论文 / 某教授全部论文 / 教授亲笔一作 / 教授压轴通讯。输入是 boshu_output 程序根（读 _zotero_collections.json 拿分类 key，读各教授 papers.json 只拿姓名），读走本地 API，写走 zotero-mcp 插件 write_tag。只增不删、幂等可重跑；纠错走两段式——分歧清单人工确认后用 remove-tags 子命令批量删。Use when 用户要求「给论文打学校/教授/一作/通讯作者标签」「按学校筛论文」「标记教授一作论文」「标记教授通讯作者论文」，或对某程序根/全库跑一遍打标。
compatibility: opencode
license: MIT
metadata:
  author: custom
  version: 1.0.0
---

# Skill: zotero-paper-tagger

## 解决什么问题

1. **没法按学校筛论文**：论文只挂在 `<大学>/<専攻>/<研究領域>/<教授>` 分类树上，想看「库里所有目标大学的论文」得逐校翻。→ 打大学名 tag。
2. **分不清教授是不是一作**：引用「教授本人一作」和「学生一作、教授挂名」说服力不同，现在要逐篇点开看作者顺序。→ 打 `一作` tag。
3. **分不清教授是亲自动笔还是压轴指导**：CS/ML 惯例末位作者 = 通讯作者（导师），前面是实际干活的学生。→ 打 `通讯作者` tag。

## 标签规则

| 标签 | 什么时候打 | 例子 |
|---|---|---|
| 大学名（全称） | 每篇都打 | `Target University A` |
| 教授名（照搬分类叶子名） | 每篇都打 | `Professor A`、`教授 B` |
| `一作`（裸词） | 仅当条目第一作者就是这位教授 | — |
| `通讯作者`（裸词） | **显式记录优先**（见「通讯作者判定顺序」节）：论文里白纸黑字写了他是通讯 → 打，不限作者位置；没写 → 回落旧规则：仅当条目**末位 author** 就是这位教授，且作者 ≥2 人（独著不打） | — |

- 裸名标签，不加前缀；中间层（専攻/研究領域）不打。
- 外国教授的名字 tag 照搬分类名（片假名），保证「点标签 = 点分类」。
- 教授分类下的**非论文条目**（webpage 等）也照打大学 + 教授 tag；附件/笔记/标注不算条目。
- **共享条目**（同一篇挂在多位教授分类下）：每位教授的名字 tag 都打；`一作`/`通讯作者` 对每位教授各判一次，命中才打；裸 `一作`、裸 `通讯作者` 全条目各最多一个。同一条目可以同时带 `一作` 和 `通讯作者`（两校合作时 A 教授一作、B 教授通讯）。

## 作者判定（一作 + 通讯作者共用，宁漏勿错）

- 第一作者 = creators 里第一个 `creatorType: author` 的 creator（编者 editor 不算）。
- 通讯作者 = creators 里**最后一个** `creatorType: author` 的 creator，且 author 总数 ≥2（独著不打）。
- 两个位置用同一套姓名比对规则：

| 规则 | 比对内容 | 处理 |
|---|---|---|
| ① 汉字全同 | 教授汉字名 = creators 署名（去空格/中点后全等） | 自动打标 |
| ② 异体字归一后全同 | `Variant Name A`→`Normalized Name A` | 自动打标 |
| ③ 罗马字全名，姓前姓后均可 | `Professor A` ↔ `A Professor`，大小写无关、重音无关、词序无关（多重集相等） | 自动打标 |
| ⑦ **署名簿变体** | 见下节：种子全名确认过 + 分类内无冲突的缩略形态（`Surname A.`、裸姓 `SurnameA`） | 自动打标 |
| ④ 姓氏全拼 + 名首字母 | `A. Surname` / `Surname A.`（署名簿没覆盖到的兜底） | **进「待人工确认」**，不当场打 |
| ⑤ 汉字姓名姓/名顺序颠倒 | `教授甲乙` ↔ `甲乙教授`（轮转同形） | 自动打标 |
| ⑥ 罗马字全名 + 恰好多出一个单字母缩写 | 未被署名簿覆盖时的兜底 | **进「待人工确认」** |

- 判定顺序：①②③ → ⑦ → ④⑤⑥。⑦ 能接管的缩略形就不落到 ④ 的待确认清单。
 - 判定材料：条目侧用 Zotero `creators` 字段（权威）；教授侧用 papers.json 的 `professor.name` + `professor.name_romaji`。name_romaji 里可能含括号别名，每个括号内名字都算一个比对变体。
- 规则④⑤⑥命中只进报告的「待人工确认」清单，绝不自动打。
- 无 name_romaji 的教授只有规则①②可用（没有种子就长不出署名簿），报告注明。

## 通讯作者判定顺序：显式记录优先，末位启发式兜底

数据来自 `_corresp_cache.json`（由 corresp_backfill.py 产出 / abstract-fetch 钩子增量写入；本 skill 只读不写它）。每条记录：

```json
"<itemKey 或 DOI>": {
   "names": ["Professor Example", "Author Example"],
   "emails": ["author@example.test"],
   "raw_text": "Corresponding author: Professor Example (author@example.test)",
  "channel": "pdf_footnote|springer_curl|crossref_api|browser_dom",
  "confidence": "high|low",
   "fetched_at": "YYYY-MM-DDThh:mm:ssZ"
}
```

对每位教授 × 每条目的通讯判定，按这个顺序走一遍：

```
该条目有显式记录？（cache 按 itemKey 命中；itemKey 缺失时按 DOI 兜底）
├─ 有 → 记录里的 names[] 逐个用署名簿规则①②③⑦④⑤⑥比对
│   ├─ 任一命中这位教授 → 打「通讯作者」（不限作者位置；一作兼通讯也覆盖）
│   ├─ names[] 全部命中"别人"且无歧义 → 不打（显式证据推翻末位启发式）
│   │   └─ 若旧版已按末位误打过 → 进「分歧清单」，两段式纠错（见下）
│   ├─ 比对不上（名字模糊/只有邮箱/空 names）→ 回落末位启发式 + 进「待人工确认」
│   └─ confidence=low 且结论是"打" → 打但报告标注来源存疑
└─ 无 → 现行末位规则原样（最后一个 author + ≥2 人）
```

- **宁漏勿错不变**：模糊就回落/待确认，绝不在证据不足时打或删。
- **主流程永不删标签**。显式反证要删旧标签时走两段式：①分歧清单列给用户 → ②用户确认编号后跑 `tagger.py remove-tags <itemKey> 通讯作者`（显式动作，脚本只提供弹药）。
- **疑似字母排序清单联动**：条目若有显式记录（无论结论打没打），自动从「疑似字母排序」清单销案——显式证据比姓氏排序猜测强。


## 署名簿（规则⑦）：把分类名跟论文署名联系起来

核心观察：教授自己的分类里，他本人会在很多论文的作者栏以**可确认的全名形态**出现（日文论文里的汉字名命中①②，英文论文里的全名命中③）。把这些「确认是他」的署名攒起来，就能认出同一批论文里他其余的缩略署名形态：

1. **攒种子**：扫他分类下全部条目的全部 creators（不限第一作者、含 editor），凡①②③命中的记为种子。连接词 and 一律过滤（只来自脏字段拼接）。
   2. **广义对齐长变体**：与教授罗马字全名逐词对齐——任意多个词缩成首字母、任意多个词缺失、双首字母挤一词、至多 1 个多余首字母、至多 1 个笔误词（编辑距离≤1 或字母换位乱序，词长≥4）。连字碎片先尝试拼回整词，整词也可反向拆成碎片。含教授全部全名词+额外噪声词的脏字段与名字自重复的垃圾格算中性证据，不当外人也不当种子。
   3. **逐候选判冲突**（不再全组连坐）：无法解释的同词异人只在「它的 given 与候选的 given 相撞」时拦该候选。
   4. **纯子集形态**（裸姓/纯缺词，没有自己的 given 信息）：只有某个异人的名字包含候选的全部词才算真撞车必拦；否则放行。
5. **落盘**：`<程序根>/教授研究/_署名对照.json`——种子数、自动变体、存疑变体（带原因）、冲突作者、脏字段清单。每次运行整体重建；单教授试跑不覆写。
6. **判定**：第一或末位作者命中「自动变体」→ 规则⑦自动打；命中「存疑变体」→ pending 并注明原因。

残余风险：同分类内另一位作者与教授同姓且同名首字母时，名字层面无法区分，报告的差异清单和 Zotero 条目可供复核。

### 疑似字母排序标注（通讯标签存疑）

数学/理论CS（STOC/FOCS 等）按姓氏字母排序，末位作者 ≠ 通讯作者。Zotero 元数据没有通讯标记，无法确证，只做启发式标注：**≥4 位作者且全部姓氏（罗马字）非降序排列** → 报告里标「疑似字母排序（通讯标签存疑）」，写入行为不变，人工抽查这些条目决定是否在 Zotero UI 里点掉标签。2~3 作者的碰巧升序不标（误报率高，且小团队论文惯例本来就是贡献序）。汉字姓氏无法比对，直接放过。

## 数据来源

| 来源 | 用途 | 实测结论 |
|---|---|---|
| `<程序根>/教授研究/_zotero_collections.json` | `university` 全称、`professors{}` 名字→分类路径、`collections{}` 路径→key | 唯一的教授名单来源；papers.json 的条目清单**不信任** |
| 每位教授 `papers.json` | 只取 `professor.name` / `professor.name_romaji`；另取全部非空 `item_key` 做差异对照 | 差异 = item_key 为空（failed/pending）或 key 不在库里的条目；旧版顶层 list 格式自动兼容（无 professor 元数据） |
| `<程序根>/教授研究/_corresp_cache.json`（只读） | 通讯作者显式记录：itemKey/DOI → {names, emails, raw_text, channel, confidence, fetched_at} | 由上游抓取流程产出；文件不存在时使用末位作者启发式 |
| 23119 本地 API（读） | `GET /api/users/0/collections/<key>/items?format=json&limit=100&start=N` | 分页按 `Total-Results` 头；creators 为 `{firstName,lastName,creatorType}`；返回含 attachment，必须按 itemType 过滤；脚本同时读取子分类并去重 |
| 23120 zotero-mcp 插件（写） | `write_tag {action:add/remove/set, itemKey, tags[]}` | 返回 beforeTags/afterTags/tagsModified；schema 无 manual/automatic 类型字段 |
| `<程序根>/教授研究/_署名对照.json`（本脚本产出） | 每位教授的署名簿：种子数、自动变体、存疑变体、冲突作者 | 每次全量运行重建；供人查阅与复核误判，脚本自身不读它（判定每次从库内数据现算） |

23120 会话建立方式与 zotero-read/zotero-save 相同：POST initialize → 响应头 `Mcp-Session-Id` → 后续请求带该头；响应 `content[].text` 是嵌套 JSON 字符串需二次 parse。

## 运行方式

```bash
# 单程序根
zotero-paper-tagger "boshu_output/Example University__Example Program"

# 全库一键（循环 boshu_output/ 下所有含 教授研究/_zotero_collections.json 的程序根）
zotero-paper-tagger --boshu-root boshu_output

# 试跑辅助
   --professor "Professor Example"     # 只跑一位教授
--dry-run              # 算标签写报告，但不写 Zotero

# 人工确认补打（agent 在对话里消化待确认清单时用）
python3 .../tagger.py add-tags <itemKey> 一作      # 或 通讯作者

# 两段式纠错（agent 在对话里消化分歧清单、用户确认编号后用）
python3 .../tagger.py remove-tags <itemKey> 通讯作者   # 显式删除动作，主流程永不自动调
```

脚本自己完成：连通检查（23119 ping + 23120 initialize，不通报错退出）→ 读映射 → 拉条目（父分类 + 子分类并集，按 key 去重，滤 attachment/note/annotation）→ 读现有 tags 跳过已带 → 判定 → `write_tag add`（每条目一次调用带上全部缺失标签）→ 写报告。agent 只负责跑脚本、解读报告、消化「待人工确认」清单。

## 幂等与重跑语义

- **只增不删**：手动删掉的标签重跑会被补回来；确需清空用 `write_tag remove` 手工处理。
- **幂等**：打标前先读条目现有 tags，已带的跳过——同一文件夹跑第二遍 = 0 次写入。
- 同一次运行内共享条目的标签写入会同步进内存缓存，后处理的教授不会重复写。

## 执行流程（agent 视角）

```
1. 跑 tagger.py <程序根>（或全库）
2. 读 stdout + <程序根>/教授研究/_论文标签报告.md
3. 把「待人工确认」清单列给用户（预计个位数）：编号 + 条目标题 + 作者 + 命中的规则依据 + 该补打的标签
4. 用户回编号 → 逐条 tagger.py add-tags <itemKey> <一作|通讯作者>
5. 把「分歧清单」（显式记录 vs 旧末位标签结论相反）列给用户：编号 + 条目 + 显式记录原文 + 建议动作（remove-tags）；用户确认后逐条 remove-tags
6. 「疑似字母排序」只剩无显式记录的条目——提请用户抽查；有显式记录的已自动销案不进此清单
7. 向用户汇报汇总数字
```

## 报告格式

路径：`<程序根>/教授研究/_论文标签报告.md`

```markdown
## Professor Example（Example Research Area）
- 条目 N 篇，全部带标签：Example University、Professor Example
- 一作 6 篇：
  - 《Example paper title》 zotero://select/library/items/ITEMKEY01
- 通讯作者 5 篇：
  - 《Another example paper》 zotero://select/library/items/ITEMKEY02
- 非一作 9 篇
- 署名簿: 种子 12 处；自动变体 2 个（规则⑦命中: 一作 3 / 通讯 5）；存疑变体 1 个
  - 存疑 `SurnameA`（bare ×3）— 同分类存在同词但无法解释的作者
- 疑似字母排序（通讯标签存疑，建议抽查）1 篇：
  - [ITEMKEY03] 《title》姓氏按字母顺序排列
- 显式通讯记录：命中 3 / 推翻末位 1 / 模糊回落 2（渠道: pdf_footnote 4, springer_curl 2）
- 分歧清单（显式记录 vs 已打标签结论相反，确认后 remove-tags）1 篇：
  - [ITEMKEY04] 《title》显式记录指向其他作者 → 教授非通讯；旧「通讯作者」标签待删
     - 补删: remove-tags KEY 通讯作者
- 待人工确认（一作）1 篇：
  - [ITEMKEY05] 《title》首位作者为缩写形式（规则④）→ 补打: add-tags ITEMKEY05 一作
- 待人工确认（通讯）0 篇
- papers.json 记了但库里没有 3 篇：（差异清单，含 zotero_status）
```

末尾汇总：新写标签 X 处、跳过 Y 处、一作共 Z 篇、通讯作者共 C 篇、显式记录命中/推翻/模糊 E1/E2/E3、疑似字母排序 S 篇、待确认 W 篇、差异共 V 篇。

## 边界与已知限制

- 两所学校有同名教授 → 标签混在一起；概率低，报告照常，不影响按学校筛选。
- 署名簿残余风险（两层）：a) 同分类内另一位作者与教授同姓且同名首字母时，存疑拦截，不会误自动；b) papers.json 罗马字整个错误、且分类里无任何全名可反驳时，可能按错名建簿（`_署名对照.json` 里 seeds=0 可复核）。
- 越南/韩国姓名姓、名顺序颠倒 → 规则③按词序无关的多重集比对已覆盖大部分；剩余靠规则④进待确认，宁漏勿错。
- 字母排序领域（数学/理论CS）末位 ≠ 通讯 → 有显式记录的条目自动按记录判定并从「疑似字母排序」清单销案；无记录的仍靠该清单标注兜底，确证只能翻 PDF 脚注；发现误打走分歧清单两段式删除。
- 「末位=通讯」是部分领域惯例；大合作组署名不适用，应由用户另行确认。
- 显式记录自身的局限（渠道数据来自上游抓取流程，本 skill 只消费）：a) 扫描版 PDF 无文本层 → 无记录，回落启发式；b) 脚注只有邮箱没名字 → names 空 → 回落启发式 + 待确认；c) 出版社标错 → 靠分歧清单人工兜底；d) cache 文件不存在 → 使用末位作者启发式。
- 映射文件里没有 `_zotero_collections.json` 的程序根在全库模式下跳过并在 stdout 注明。
- 集成方式：上游采集流程可在全部教授处理完成后，于程序根级别串行调用本脚本。跳过条件由上游流程决定；独立手动触发入口不变。
