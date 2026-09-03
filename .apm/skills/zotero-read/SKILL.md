---
name: zotero-read
description: Read and search literature stored in the local Zotero library — browse collection trees, search by metadata / full-text / annotations, deep-read individual papers (metadata + abstract + PDF full text + notes + highlights) — and answer the user's questions with citations. Read-only, no API key, all via curl to the local zotero-mcp plugin (127.0.0.1:23120). Use when the user asks to find, summarize, explain, or quote papers stored in Zotero (e.g. "在Zotero里找关于X的文献", "帮我讲讲库里这篇论文", "哪些论文提到了Y概念"). Complement to zotero-save: zotero-save WRITES (search & import), this skill only READS.
---

# Skill: zotero-read

## What I do

读取与检索**本地 Zotero 库**中的文献(**只读,零写入**):浏览分类树、按元数据/全文/标注搜索、深读单篇文献(元数据+摘要+PDF 全文+笔记+高亮标注),并带引用(zoteroUrl)回答用户问题。全程 curl 直连本地 zotero-mcp 插件(127.0.0.1:23120),无 API key、不碰云。

与 zotero-save(写入:搜索/导入/归类)**互补**——本 skill 只用读工具,绝不调用 write_* 系列。

Pipeline:

1. **健康检查**:Zotero 在跑(23119 ping)+ MCP 插件通(23120)
2. **定位**:`get_collections`(递归分类树)/ `search_collections` / `get_collection_items`
3. **检索**:`search_library`(元数据)/ `search_fulltext`(全文)/ `search_annotations`(标注)
4. **深读**:`get_item_details`(元数据+笔记+标签)→ `get_content`(摘要+附件全文+本地 PDF 路径)→ `get_annotations`(高亮/注释)
5. **汇报**:标题/作者/年份/期刊/DOI/zoteroUrl,引用原文时保留原措辞

## When to use me

激活本 skill 当用户想要:

- 按主题/关键词在 Zotero 库中检索文献(如"在 Zotero 里找关于目标主题的论文")
- **全文检索**:哪篇论文提到了某个概念/方法(如"哪篇论文讲了混合关键性调度")
- 按分类浏览库(如"X 分类下有哪些文献""示例分类里存了什么")
- 深读/总结/讲解单篇论文(如"帮我总结这篇论文""这篇论文的方法是什么")
- 查看某篇论文的笔记与高亮标注(如"这篇论文我标注了什么")
- 回答问题时引用 Zotero 里存的文献(带标题/年份/DOI/zoteroUrl 引用)

不需要:写入 Zotero(建条目/导入 PDF/改元数据)→ 用 zotero-save。

## Prerequisites — 必须先检查(任何一步失败就停下来告诉用户)

### 1. Zotero 已打开 + cookjohn/zotero-mcp 插件已装并启用

```bash
curl -s --max-time 5 http://127.0.0.1:23119/connector/ping   # 期望 "Zotero is running"
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:23120/mcp   # 期望 4xx/200(有响应即通)
```

- 23120 不通 → Zotero 没开、或插件没启用(Preferences → Zotero MCP Plugin → Enable Server,默认端口 23120)

**无需**启动 translation-server(那是 zotero-save 写元数据用的;本 skill 只读不依赖)。

**也无需额外安装 `zotero-tools` Python 包来获得 `zotero-mcp-session` 命令**。建立 MCP session 的 helper 已随本 skill 打包在 `scripts/new-session.sh`。

## Zotero MCP 调用方式(curl 直连,唯一主路径)

Zotero 插件在 `http://127.0.0.1:23120/mcp` 提供 Streamable HTTP 传输的 MCP 服务器。用 curl 按 JSON-RPC 调用,分两步:

### 步骤 A:建立会话(拿 Mcp-Session-Id)

宿主加载本 skill 时已经知道本 `SKILL.md` 的实际路径。取其父目录作为 `<skill_dir>`，直接执行随 skill 打包的 helper；不要依赖当前工作目录，也不要假设某个环境变量已经存在:

```bash
SID=$(bash "<skill_dir>/scripts/new-session.sh")
```

这里的 `<skill_dir>` 是当前已加载 `zotero-read` skill 的绝对目录占位符，执行前用实际路径替换。不要要求 PATH 中存在 `zotero-mcp-session`；该全局命令只是 `zotero-tools` Python 包提供的 convenience entry point，本 skill 自身运行不依赖它。

(等价的手写方式:POST initialize → 从响应头 `Mcp-Session-Id` 取值)

### 步骤 B:调工具(每条请求都带 Mcp-Session-Id 头)

```bash
curl -s --max-time 60 -X POST http://127.0.0.1:23120/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"<工具名>","arguments":<JSON参数>}}'
```

响应: `{"jsonrpc":"2.0","id":2,"result":{"content":[{"type":"text","text":"<JSON字符串>"}]}}` —— **注意 text 字段里是嵌套的 JSON 字符串,需要再 parse 一次**。

一次会话可连续复用(多条请求共用一个 SID);会话过期后重新运行本 skill 的 `scripts/new-session.sh`。

## 工具参考(只读工具,参数与返回)

| 工具 | 用途 | 参数(JSON) | 返回(text 内 JSON) |
|---|---|---|---|
| `get_libraries` | 列出库 | `{}` | 库列表 |
| `get_collections` | 全部(子)分类,树形 | `{"recursive":true,"limit":100}` | 分类数组(key/name/path/depth/subcollections) |
| `search_collections` | 按名搜分类 | `{"q":"作者/Professor Example"}` | 分类数组 |
| `get_collection_details` | 分类详情 | `{"collectionKey":"..."}` | 分类信息 |
| `get_subcollections` | 子分类 | `{"collectionKey":"...","recursive":true}` | 子分类数组 |
| `get_collection_items` | 分类下的条目 | `{"collectionKey":"...","limit":50}` | 条目数组(key/title/creators/date/attachments) |
| `search_library` | 元数据检索(高级:布尔、相关性、分页) | `{"q":"<topic>","limit":20}` | results(key/title/creators/date/attachments[])+ pagination |
| `get_item_details` | 单条完整元数据 | `{"itemKey":"ITEMKEY01"}` | title/creators/date/publicationTitle/DOI/tags/notes[](HTML)/zoteroUrl |
| `get_item_abstract` | 只取摘要 | `{"itemKey":"..."}` | abstract |
| `get_content` | **全文**:摘要+附件正文+本地文件路径 | `{"itemKey":"...","maxLength":20000}` | abstract + attachments[](filePath/type/content) |
| `search_fulltext` | **全文检索**,返回命中段落上下文 | `{"q":"<concept>","limit":10}` | results(itemKey/title/totalMatches/matches[](type/context)) |
| `fulltext_database` | 全文缓存库快查(比实时抽取快) | `{"action":"search","q":"..."}`;actions: list/search/get/stats | 缓存条目/段落/统计 |
| `search_annotations` | 搜标注(高亮/笔记/评论) | `{"q":"..."}` 或 `{"colors":["yellow"]}` 或 `{"tags":[...]}` | 标注数组(含原文引用) |
| `get_annotations` | 取指定条目/标注的标注 | `{"itemKey":"..."}` 或 `{"annotationId":"..."}` / `{"annotationIds":[...]}` | 标注数组(颜色/页码/选中文本/评论) |

## 工作流

### 模式 A:主题检索(元数据级)

```bash
curl -s --max-time 60 -X POST http://127.0.0.1:23120/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"search_library","arguments":{"q":"<关键词>","limit":15}}}'
```

给用户列候选表(标题/作者/年份/有无 PDF 附件),问/选哪些条目,再进模式 D 深读。分页参数见返回里的 `pagination`(total/hasMore/offset)。

### 模式 B:全文检索(找"哪篇论文提到了 X")

```bash
# search_fulltext 参数是 q(不是 query!)
{"name":"search_fulltext","arguments":{"q":"<concept>","limit":10}}
```

返回每条结果的 `matches[].context` 是命中段落上下文 → 直接摘录或按 itemKey 进模式 D。

**先试 `fulltext_database` 的 search action**(走缓存、秒回),命中不足再 `search_fulltext` 实时索引。

### 模式 C:按分类浏览

1. `get_collections {"recursive":true}` → 看 path(如 `Example Contact > Example Program > Example Collection`)定位目标 collectionKey
2. `get_collection_items {"collectionKey":"..."}` → 条目列表
3. 选中条目 → `get_item_details` → 按需 `get_content`

### 模式 D:单篇深读(核心)

```bash
# 1. 元数据 + 笔记 + 标签
{"name":"get_item_details","arguments":{"itemKey":"ITEMKEY01"}}
# 2. 摘要 + PDF 全文 + 本地文件路径
{"name":"get_content","arguments":{"itemKey":"ITEMKEY01","maxLength":30000}}
# 3. 高亮标注与评论
{"name":"get_annotations","arguments":{"itemKey":"ITEMKEY01"}}
```

`get_content` 的 attachments[].filePath 给的是**本地绝对路径**(例如 Zotero profile 下的附件路径)——可直接读取该 PDF 文件做精细引用(页码),或 `open "<filePath>"` 弹给用户。

### 模式 E:标注与笔记

- 全库搜标注:`search_annotations {"q":"<关键词>"}`(也可按 colors/tags 过滤)
- 单篇的标注:`get_annotations {"itemKey":"..."}`
- 笔记在 `get_item_details` 的 notes[] 字段(HTML);独立笔记可用 `search_library {"q":"..."}` 定位

## 汇报格式

回答用户问题时,凡引用 Zotero 文献,附:

```
标题(年份), 作者列表, 期刊/会议, DOI
zotero://select/library/items/<key>
```

- **引用标注/原文时保留原措辞**(尤其高亮标注,是用户自己的笔记,不能改写)
- 全文来自 OCR 时可能存在识别错误,引用长段落时提示用户核对
- 引用后指出本地 PDF 路径(便于用户打开核对)

## 注意事项

1. **只读**:本 skill 绝不调用 `write_item` / `write_metadata` / `write_tag` / `write_note` / `create_collection` / `delete_collection` 等写工具;要写入请走 zotero-save
2. 响应的 `text` 字段是**嵌套 JSON 字符串**,要二次 parse
3. `search_fulltext` 参数名是 **`q`**(写成 `query` 会报 "q (query) is required")
4. 会话复用同一个 SID;超时/报错后重新运行本 skill 的 `scripts/new-session.sh`
5. `get_annotations` 必须给 `itemKey` 或 `annotationId`/`annotationIds` 之一
6. `get_content` 返回的是附件全文,长文可能被截断(用 maxLength 控制);论文图表公式会丢失
7. 深读长论文时,可把 `get_content` 的全文存到临时文件再分段读,避免上下文爆炸
8. 完成后汇报:命中条目、选读的论文、引用段落、本地 PDF 路径

## Troubleshooting

- **23120 不通**:Zotero 没开 / 插件未启用(Preferences → Zotero MCP Plugin → Enable Server)/ 端口被改
- **initialize 无响应或超时**:插件内部出问题,重启插件服务
- **`zotero-mcp-session: command not found`**:不要额外安装包来补这个命令;直接执行当前 skill 自带的 `scripts/new-session.sh`
- **search_fulltext 报 "q (query) is required"**:参数名用 `q`
- **get_annotations 报 required**:必须给 itemKey 或 annotationId(s)
- **get_content 无附件内容**:该条目没有 PDF 附件(linkMode=1 才是已导入的;linked 文件可能未索引)
- **全文检索没结果**:先确认 Zotero 里对该 PDF 做过全文索引(Zotero 设置 → 搜索 → 全文索引);可改用 `fulltext_database` 查缓存状态(stats action)
