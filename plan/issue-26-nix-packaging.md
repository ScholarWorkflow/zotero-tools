# Issue #26：复用 agent-env-nix 的 Zotero 独立分包计划

- Requirement revision：2026-10-16 [Issue #26](https://github.com/ScholarWorkflow/zotero-tools/issues/26) 已同步 `agent-env-nix` PR #3 的选中技能/角色整体替换、MCP 配置保护及失败重跑约定；原两包业务目标不变。
- Plan revision：`issue26-plan-v5-2026-10-16`，测试修订：`test-v5.1-2026-10-16`。本文件为 `plan/` 下唯一完整的执行与最小测试计划，代替 v4/test-v4.1；必测 T1–T5 上限不变。新版方案与步骤待独立复核。
- Target revision：原业务基线 `7c39f03f0d6010e3e4ce8e51f7fc8ba761ef58d8`；本轮修订前 PR #27 head `cefd1cb3943ccfef362a1e8fdddcdfa6b0494e34`（包含旧共享库实现）。本次先修计划，Nix 锁文件和 README 的产品改动尚待实施。
- Shared revision：升级目标为已合并的 [agent-env-nix PR #3](https://github.com/RekiDunois/agent-env-nix/pull/3)，固定 merge commit `ba2d0fe4ef4d1dc1d80ec628c3ecc6607829a76e`；旧实现锁定 `760c1bf60e8ec19d1985660ec5e3276a8ef80b5a`，只供历史记录引用，不视为新版本已验证。
- Implementation revision：旧版已实现并测试的 producer `ae4b9d411589cea8728ae371787196c894f0d642`；其原 T1–T5 结果在 §5.7 保留。升级后的 producer SHA 和结果在实际提交/执行后填写，不把旧版通过结论迁移为新版通过。
- 规则：[Project Consensus](https://app.notion.com/p/rekidunois/Project-Consensus-3d60101a85f3815a8c43f271f2b4d91d)、[Plan Reviewer Rule](https://app.notion.com/p/rekidunois/Plan-Reviewer-Rule-3e80101a85f3817a94cbc6eca1a76a5c)、[Test Engineer Rule](https://app.notion.com/p/rekidunois/Test-Engineer-Rule-3d80101a85f380d8a8f5ce528141e253)。引用不新增本计划之外的测试。

## 本轮平台与审核边界（2026-10-15 18:00 UTC）

首批支持与验收仅限 `aarch64-darwin`。Linux 不在本轮支持承诺、必测范围或合并前置内；不新增跨平台矩阵。既有 Linux 结果如有则保留为历史记录，不能替代 Mac 验收证据；已有且未受影响的 Mac PASS 直接复用，不因本次文档修订重复执行。

2026-10-15 平台范围的定向复核记录继续有效。本次因共享库合并而更新文件安装/失败语义和依赖版本，只复核受影响的方案决策与测试步骤；未受影响的结论沿用。MCP 初始化仍仅限原清单，不借升级扩大验证范围。

## 1. 方案、依据与边界

需求是日常工具与破坏性 cleaner 分开、完整资源、固定依赖、原有角色确认和 APM 行为保留。当前 Python tagger/session 按模块目录向上查找 `.apm/skills`，进入 Nix Python 库后不能自然成立，技能也仍使用 uv/shell/PDF 命令。因此 producer 负责固定运行包、资源根和必要 Nix 调用适配，共享层负责声明式包、组合、选中技能/角色复制以及所选 MCP 配置保护。仅复制 SKILL.md、给所有功能一个默认大包、每仓再建安装器均不满足这一职责分离。

关键事实来源：
- [pyproject.toml](https://github.com/ScholarWorkflow/zotero-tools/blob/7c39f03f0d6010e3e4ce8e51f7fc8ba761ef58d8/pyproject.toml)：Python >=3.11、三个 console scripts；[源技能/角色](https://github.com/ScholarWorkflow/zotero-tools/tree/7c39f03f0d6010e3e4ce8e51f7fc8ba761ef58d8/.apm)；[tagger.py](https://github.com/ScholarWorkflow/zotero-tools/blob/7c39f03f0d6010e3e4ce8e51f7fc8ba761ef58d8/zotero_tools/tagger.py)、[session.py](https://github.com/ScholarWorkflow/zotero-tools/blob/7c39f03f0d6010e3e4ce8e51f7fc8ba761ef58d8/zotero_tools/session.py) 的资源定位。
- 已合并共享 [package.nix](https://github.com/RekiDunois/agent-env-nix/blob/ba2d0fe4ef4d1dc1d80ec628c3ecc6607829a76e/lib/package.nix) 保留 files、exports.skills/agents、agentDependencies/runtimePackages 及 enableHarnesses；[project.nix](https://github.com/RekiDunois/agent-env-nix/blob/ba2d0fe4ef4d1dc1d80ec628c3ecc6607829a76e/lib/project.nix) 保留 mkProject，改为生成 shell 激活器；[activate.sh](https://github.com/RekiDunois/agent-env-nix/blob/ba2d0fe4ef4d1dc1d80ec628c3ecc6607829a76e/runtime/activate.sh) 直接替换选中叶子、保留名称清单并允许失败后重跑；[config.py](https://github.com/RekiDunois/agent-env-nix/blob/ba2d0fe4ef4d1dc1d80ec628c3ecc6607829a76e/runtime/config.py) 仅处理 MCP/TOML 配置，未选择 MCP 时不检查无关 CODEX_HOME 配置。
- [Codex skills](https://developers.openai.com/codex/skills)、[subagents](https://developers.openai.com/codex/subagents)：技能需进入发现位置；角色为 name、description、developer_instructions 的原生 TOML。共享库不会读取 APM frontmatter 并自动理解其宿主 variants，本仓仍须准确选取描述/正文。

预期变化：两独立 agent 包与共享 Codex 接入改用 PR #3 合并提交；选中技能/角色文件允许直接整体替换（包含同名未管理内容和用户直接编辑），MCP 配置仍按生成值保留用户改动并报告冲突；安装中断后允许部分文件已更新，修复后从正式入口重跑。保留：原四技能、源角色、三个 CLI 业务、APM/OpenCode/uv 非 Nix 路径、运行时端点参数、cleaner 执行前确认、未选中资源。禁止：默认带 cleaner、真实数据写入测试、业务/schema 重构、虚构 Zotero MCP 服务、改消费者仓库或用户信任、秘密入 store。批准的文件替换约定以当前 Issue #26 为准。

## 2. 唯一接口及 producer 修改点

### 2.1 包声明与选择

现有 flake.nix/flake.lock、nix/ 已在 PR #27 实现。本轮把 `flake.nix` 的共享 input 与 `flake.lock` 中该节点锁定到上述 PR #3 合并提交，避免追踪浮动分支；保持现有 nixpkgs 与其余输入的固定版本，除非新接口确实要求调整。共享仓访问使用现有 Nix/Git 认证，不将 token 写进声明。首批仅对 `aarch64-darwin` 声明可消费。

- `packages.<system>.zotero-tools`：共享 mkAgentPackage 结果，exports.skills 为 zotero-read、zotero-collections、zotero-paper-tagger；files 包含完整目录、scripts/schema 及所需附属资源；runtimePackages 引用固定 Python 应用与所需 shell/PDF 工具。无 cleaner export 或强制依赖。
- `packages.<system>.zotero-collection-cleaner`：独立 mkAgentPackage，完整 cleaner 技能，exports.agents.zotero-collection-cleaner 的 description/developer_instructions 来自同一源角色的既有 Codex variant；共享层生成 name/TOML。不另写 Codex 序列化器，不把 OpenCode permission/hidden/question 当权限字段。
- 两包 producer 参数暴露 `enableHarnesses ? [ "codex" ]`，透传共享库，可 `.override { enableHarnesses = []; }`。Nix 新路径只实现 Codex；APM 的既有 OpenCode 原角色/转换保留，不再在 Nix 输出或 Nix 测试新增 OpenCode 产物。
- `agentDependencies` 仅放真实依赖的 mkAgentPackage 结果；cleaner 只有实际复用日常 endpoint helper 时才依赖日常包，不能因输入来自 professor-collection-preparer 就依赖研究包。runtimePackages 只保留普通 derivation 闭包，不遍历其技能、不自动给 PATH/bin。

共享产物使用 `$out/payload`、`$out/codex/agents`、agent-env.json 和 passthru.agentEnv，不再定义旧 share/scholarworkflow 中间协议。files 用安全不重叠相对路径映射完整资源，exports.skills 指向其目录。

### 2.2 必须保留的本仓 runtime 工作

1. 固定 Python >=3.11 应用，安装全部 zotero_tools 模块及三个真实 console scripts。为 tagger/session 增加显式 Nix 资源根，未设置时保留原源码树/APM 定位，不依赖 cwd。
2. 共享 mkAgentPackage 本身不产出 `$out/bin`。本仓保持原三 CLI 作为 zotero-tools 包的可安装 bin：用 producer 专属 derivation 包装追加指向固定 runtime 的 bin 链接，并保留 mkAgentPackage 的完整输出与 passthru.agentEnv（例如对结果作局部 overrideAttrs）。不能只放 runtimePackages 就声称 profile 安装后已有 CLI；不在共享层添加通用 CLI 安装器。
3. 固定资源树与 runtime 构建关系须无循环：先从源构建 Nix 资源副本，再以该副本构建 Python/wrappers，最后 agent 包引用相同资源及 runtime。wrapper 的资源根指向实际脚本根而非未定义 share 路径。
4. 完整交付 zotero-read 的 new-session.sh、zotero_item_export.py、item_export_core.py，以及 tagger helpers 和 CORRESPONDENCE_SCHEMA.md。仅 Nix 副本/包装将 uv 动态执行改成固定解释器；保留源技能 `<skill_dir>` 找相对 helper 的含义及原 uv 用法。
5. 对真正执行技能的入口提供 bash、curl、grep、awk、tr、mktemp、pdftotext 等实际使用工具；保留 fitz 备用路径则提供固定 PyMuPDF。使用 producer wrapper/固定命令或 Nix 变体指令，不仅给 CLI 设置 PATH 却遗漏技能 shell 命令。
6. 保留 ZOTERO_HTTP_URL、ZOTERO_MCP_URL、ZOTERO_STORAGE_ROOT 运行时覆盖；导出、缓存、日志使用可写工作/程序根/显式目录。Zotero Desktop/插件/HTTP 与 Codex 原生 MCP 为外部前提，两包 mcp 默认空，不注册假的 Zotero server。
7. cleaner 描述及完整业务正文保持既有 plan→询问→执行、Tier-1/Tier-2、串行失败即停、映射文件保护和取消/部分完成语义；安装本身不运行 cleaner。

## 3. 共享接入及生命周期

消费者继续调用共享 `lib.mkProject { inherit pkgs; roots = [ ... ]; }`，构建环境后显式运行 `bin/agent-env apply --project <project>`。本仓只提供可复用示例，不另写 installer/consumer-view。包构建或 profile 安装不会使技能自动出现在项目；实际输出仍为 `.agents/skills/<name>` 和 `.codex/agents/<name>.toml`，宿主信任保持现状。

共享库负责递归 agentDependencies、包去重、导出名称碰撞拒绝、完整文件复制、原生角色 TOML、MCP 配置来源核对、GC roots 以及 apply/remove。本仓负责两包拆分、资源根、固定解释器、技能命令及三个 CLI；`runtimePackages` 仍只保留普通程序闭包，不自动提供 PATH/bin，也不展开其他技能。不同包同名 export 仍拒绝。

按已合并 PR #3 的合同，**本次 roots 选中的技能目录和角色文件一律由共享库替换整个目标叶子**：即使已有同名未管理资源或用户直接编辑，也不复用、不中断询问。用户要保留修改应先改 producer 源文件；安装器不保护这些编辑。未选中的其他技能/角色及相邻文件不动。`agent-env remove` 只清理此前记录的选中名称，不删除无关兄弟文件。

**MCP 配置的保护单独处理**：仅所选的 `mcp_servers` 项检查来源冲突；等价未管理定义复用且不认领；已生成值被用户改动时保留并报告。其他配置字段、全局信任及未知内容不改。本仓两个包默认 `mcp` 为空，新版配置辅助程序在没有所选 MCP 项时跳过对无关 `CODEX_HOME/config.toml` 的检查；原 T2/T3 的旧版路径阻断不代表新版已通过。

共享库现在用 shell 复制选中资源，Python 只处理 MCP/TOML，**无跨文件事务和回滚**。如果 apply 在复制途中失败，可能留下部分新版；保留部署名称清单及必要 GC roots，排除故障后从官方 `agent-env apply` 完整重跑，不直接修补 consumer。旧版的 `.agent-env-nix/pending.json` 若仍存在，先按旧版程序处理，不能强行绕过迁移检查。首轮测试使用独立全新 consumer，不为共享库通用升级/移除语义增加重复回归。

已知范围内的 macOS 大小写仅差别重命名风险由共享 PR #3 既有记录接受；本次已声明 export 名称无此类变化，不新增该风险的测试。共享 apply 不写全局配置、不改信任，不承诺整个项目原子性，也不宣称能判断不可读取的受管配置或后续会话覆盖。

## 4. 实施顺序和完成边界

1. 采用更新后的 Issue #26 与本版唯一正式计划；明确旧版结论只对原共享 SHA 有效。按规则对受影响的 P1（上游事实）、P3（文件替换/失败语义）和 P4（固定版本及交接）定向复核；P2 的包归属、接口与核心方案可沿用既有证据，未经复核不得自行将新计划标为 `APPROVED`。
2. 实现负责人在 PR #27 **同一分支**修改 `flake.nix` 与 `flake.lock`：共享库固定 `ba2d0fe4ef4d1dc1d80ec628c3ecc6607829a76e`，保留既有 nixpkgs/平台约束，不顺便更新无关依赖。核对两处锁定值与真实合并版本一致；旧版结果不声称新版本通过。
3. 依据新共享 `lib/package.nix`/`lib/project.nix` 核对已实现的 `nix/default.nix`、`nix/zotero-tools.nix`、`nix/zotero-collection-cleaner.nix`、`nix/skill-resources.nix`：接口、`passthru.agentEnv` 和 `buildCommand` 的行为保留时不重写业务或安装器；若构建给出具体不兼容事实，仅修复本仓调用点。三 CLI、资源根、源角色和非 Nix 路径仍按 §2 交付。
4. 更新 `README.md` 中引用的旧共享 SHA、技能/角色替换和失败重跑说明；继续区分 profile 提供 CLI 与 `mkProject/apply` 部署技能。无需改消费者仓库或用户配置。
5. 按 §5 的 **同一 T1–T5 清单**只复核受到共享版本变化影响的包构建和正式安装；未受影响的 CLI 帮助输出可复用，旧版未完成的隔离 MCP 初始化、源码兼容检查继续如实记录。全部必测结果有效后再独立申请合并审核；两包完成后由 PR 的 `Closes #26` 关闭问题。

## 5. 唯一最小测试计划

测试修订：`test-v5.1-2026-10-16`。保持已批准的 T1–T5 及原预期，不增加用户编辑覆盖、迁移/回滚、大小写重命名、共享库配置来源或平台矩阵等新用例。共享 PR #3 的选中叶子替换与失败重跑已有苹果芯片 Mac T1–T4 记录，本仓只检验自己的包与正式部署。旧 SHA 的正式结果见 §5.7；新版按 §5.8 的影响范围执行，不能混报。

| 项 | 输入/场景 | 预期与检查方法 |
|---|---|---|
| T1 日常构建 | 固定实现SHA的zotero-tools | 构建成功；三完整技能、helpers/schema、Python模块、三个可安装CLI；不含cleaner |
| T2 独立cleaner | 同SHA的cleaner单root | 构建与共享部署成功；只带声明技能/角色，没有无依据的日常/研究依赖 |
| T3 角色与接入 | 两个独立consumer，经共享mkProject/apply | 实际Codex发现位置正确，角色三字段与同SHA源名称/描述/正文一致；不另测OpenCode Nix产物/通用投影算法 |
| T4 实际入口 | profile安装三CLI、隔离端点；受影响原源码路径 | 两help成功；真实mcp-session入口初始化获会话ID；无Nix资源根时原源码定位保留 |
| T5 工具与状态 | 复用上面安装和调用 | 固定工具/资源可用，不写store、不接触真实Zotero；日常无cleaner。合并T1/T3/T4观察，不再加独立测试层 |

### 5.1 准备参数与正式共享入口

以下为 producer 更新锁文件**之后**的唯一执行步骤。本次仅修订计划、尚未执行新版正式测试。执行者填入包含新共享锁定值的 `PRODUCER_SHA`；平台固定 `aarch64-darwin`，`SHARED_SHA` 必须等于 producer 的 `flake.lock`：`ba2d0fe4ef4d1dc1d80ec628c3ecc6607829a76e`。只有计划文字变化不触发复验；上游构建输入真实变化时只复核受影响目标。原结果见 §5.7、新版判定见 §5.8。沿用现成 Nix flakes、`uv`、Python >=3.11 和仓库读取权限，缺失仅暂停相关项，不新建通用测试设施。

```bash
set -euo pipefail
export PRODUCER_SHA='<待测实现的远端40位SHA>'
export SYSTEM=aarch64-darwin
export SHARED_SHA=ba2d0fe4ef4d1dc1d80ec628c3ecc6607829a76e
export REPO='ScholarWorkflow/zotero-tools'
export REF="github:$REPO/$PRODUCER_SHA"
export RUN="$(mktemp -d /tmp/issue26-nix-XXXXXX)"
mkdir -p "$RUN/compose" "$RUN/output" "$RUN/work" "$RUN/cache" "$RUN/state" "$RUN/cache/nix"
export NIX_CACHE_HOME="$RUN/cache/nix"
export XDG_CACHE_HOME="$RUN/cache" XDG_STATE_HOME="$RUN/state" TMPDIR="$RUN/work"
export UV="$(command -v uv)" PYTHON="$(command -v python3)" UV_CACHE_DIR="$RUN/cache/uv"
```

源码目录只在 §5.3 的角色对照及适用时 §5.4 的源码兼容检查需要；公共准备不读取源码，避免源码路径获取失败阻断独立的构建与安装测试。

不修改 HOME/CODEX_HOME、用户信任或已有 eval 服务。共享新版在没有选中的 MCP 项时不必读取外部 CODEX_HOME 配置；若实测仍有拒绝访问，记录实际故障并将受影响项标为无法判断，不修改产品保护或通过人为改写 CODEX_HOME 求通过。独立 Nix 缓存目录只用于避免已有只读缓存问题；仍受沙箱限制时按原审批处理。消费者位于仓库/worktree 外，所选路径须已获准用于隔离运行。实际需要Codex时通过既有eval命令显式传入 `--sandbox workspace-write`；不读取或审核eval服务的Codex信任名单，不增设预先信任检查，也不修改全局信任。只有真实执行返回权限问题时，才按运行环境结果处理。只记录实际 SHA、consumer 路径、安装命令和结果位置，不额外制作来源 manifest、hash 链或全环境快照。

下面的 `flake.nix` 是消费者配置，不是安装脚本；`ROOTS_NIX` 按后续各项明确选择。本例直接调用共享库，不建立本仓 consumer-view、复制器或配置合并器。

```bash
export ROOTS_NIX='[ p.zotero-tools ]'
cat > "$RUN/compose/flake.nix" <<EOF_NIX
{
  inputs.producer.url = "$REF";
  inputs.shared.url = "github:RekiDunois/agent-env-nix/$SHARED_SHA";
  inputs.shared.inputs.nixpkgs.follows = "producer/nixpkgs";
  outputs = { producer, shared, ... }: let
    pkgs = producer.inputs.nixpkgs.legacyPackages."$SYSTEM";
    p = producer.packages."$SYSTEM";
  in { packages."$SYSTEM".default = shared.lib.mkProject {
    inherit pkgs; roots = $ROOTS_NIX;
  }; };
}
EOF_NIX
export ENV_OUT="$(nix build "path:$RUN/compose#default" --no-link --print-out-paths)"
export CONSUMER="$RUN/consumer"
mkdir -p "$CONSUMER"
"$ENV_OUT/bin/agent-env" apply --project "$CONSUMER"
```

后续改 roots 时只替换这个配置中的 roots 表达式，并通过同一 build/apply 入口部署到该项目；这是获批组合输入变化，不手改生成资源。需要独立选择断言时使用新的具名 consumer，其他项复用已有安装。不运行共享库 flake check/通用回归，也不在本仓重测共享配置冲突、并发、升级/卸载、GC、override 矩阵。

### 5.2 T1 / T2：构建及独立安装

首次 `ROOTS_NIX='[ p.zotero-tools ]'`。准备之后分别构建两个包，并通过正式profile入口保留日常三个CLI：

```bash
export TOOLS_OUT="$(nix build "$REF#zotero-tools" --no-link --print-out-paths)"
export CLEANER_OUT="$(nix build "$REF#zotero-collection-cleaner" --no-link --print-out-paths)"
nix profile install --profile "$RUN/profile-tools" "$REF#zotero-tools"
export TOOLS_CONSUMER="$CONSUMER"
find "$TOOLS_OUT/payload" -type f -print > "$RUN/output/tools-files.txt"
for name in zotero-paper-tagger zotero-mcp-session zotero-item-export; do
  test -x "$RUN/profile-tools/bin/$name" || exit 1
done
```

查看已声明payload的资源清单，要求三完整技能、zotero-read的new-session.sh/zotero_item_export.py/item_export_core.py、tagger三个helpers和CORRESPONDENCE_SCHEMA.md完整；Nix允许改写的调用说明/解释器不要求与源逐字相等。不要重做闭包来源认证或运行时下载追踪。

将5.1配置的roots仅替换为 `[ p.zotero-collection-cleaner ]`，运行：

```bash
export CLEANER_ENV="$(nix build "path:$RUN/compose#default" --no-link --print-out-paths)"
export CLEANER_CONSUMER="$RUN/consumer-cleaner"
mkdir -p "$CLEANER_CONSUMER"
"$CLEANER_ENV/bin/agent-env" apply --project "$CLEANER_CONSUMER"
```

这是第二包的独立选择，不是重复安装同一环境。default日常入口保持独立，不用聚合两包后猜cleaner是否默认带入。

### 5.3 T3 / T5：资源与源角色对照

下面直接读取本次正式安装文件及同SHA只读源；只做目标字段/资源断言，不调用APM转换，不运行整套projection测试，也不新增比较工具文件。同SHA源码根从 `nix flake metadata` 返回的 `path` 获取；若外部源码路径不可用，只将本段源角色对照及适用的源码兼容子项记为“无法判断”，不阻塞不依赖该路径的项目。

```bash
if SOURCE="$(nix flake metadata --json "$REF" | jq -er '.path')" && [ -d "$SOURCE" ]; then
  export SOURCE
  "$UV" run --no-project --python "$PYTHON" - "$TOOLS_CONSUMER" "$CLEANER_CONSUMER" "$SOURCE" <<'PY'
import pathlib,sys,tomllib
regular,cleaner,source=map(pathlib.Path,sys.argv[1:])
for name in ('zotero-read','zotero-collections','zotero-paper-tagger'):
    path=regular/'.agents/skills'/name
    assert path.is_dir() and not path.is_symlink()
    assert (path/'SKILL.md').is_file()
assert not (regular/'.agents/skills/zotero-collection-cleaner').exists()
assert not (regular/'.codex/agents/zotero-collection-cleaner.toml').exists()
assert (cleaner/'.agents/skills/zotero-collection-cleaner/SKILL.md').is_file()
assert not (cleaner/'.agents/skills/zotero-paper-tagger').exists()
a=tomllib.loads((cleaner/'.codex/agents/zotero-collection-cleaner.toml').read_text())
lines=(source/'.apm/agents/zotero-collection-cleaner.agent.md').read_text().splitlines()
end=lines.index('---',1)
desc=next(s.split(':',1)[1].strip() for s in lines[1:end] if s.startswith('description:'))
assert len(desc)>=2 and desc[0]==desc[-1] and desc[0] in ('"',"'")
assert set(a)=={'name','description','developer_instructions'}
assert a['name']=='zotero-collection-cleaner'
assert a['description']==desc[1:-1]
assert a['developer_instructions'].strip()=='\n'.join(lines[end+1:]).strip()
print('T3: installed resources and canonical role match')
PY
else
  unset SOURCE
  echo 'T3 source comparison: unable to judge; flake source path unavailable' >&2
fi
```

该源字段方法沿用当前 `test/apm_projection.py` 的已有比较规则；若实现时源角色格式确实改变，先修订这条比较方法，不靠APM通过结果替代Nix产物，也不把格式变化升级为业务/宿主认证。

### 5.4 T4：三个真实CLI与源码兼容

前两个命令从仓库外执行，输出应为原help且exit 0，成功同时确认其所用Python模块可加载与资源入口可用：

```bash
cd "$RUN/work"
"$RUN/profile-tools/bin/zotero-paper-tagger" --help > "$RUN/output/tagger-help.txt"
"$RUN/profile-tools/bin/zotero-item-export" --help > "$RUN/output/export-help.txt"
```

第三个命令必须使用已经获授权的独占隔离回环MCP endpoint。执行者提供完整URL，记录它属于哪个现有隔离fixture即可；无需重复fixture来源/身份认证，不新建测试服务，不用默认真实Zotero。端点及权限缺失时只将此子项记无法判断。

```bash
export ZOTERO_MCP_URL='http://127.0.0.1:<本轮隔离端口>/mcp'
"$UV" run --no-project --python "$PYTHON" - "$ZOTERO_MCP_URL" <<'PY'
import sys,urllib.parse
u=urllib.parse.urlsplit(sys.argv[1])
assert u.scheme=='http' and u.hostname=='127.0.0.1' and u.port and u.path=='/mcp'
PY
"$RUN/profile-tools/bin/zotero-mcp-session" > "$RUN/output/session-id.txt"
test -s "$RUN/output/session-id.txt"
```

执行前确认该URL确是授权fixture；URL形状断言不代替授权。检查输出是非空会话标识，真实安装命令进入随包new-session.sh，只发送initialize，不执行业务读写/删除。空ID或命令失败不算通过；不以help/路径存在替代。T5直接复用这次及help的输出与可写TMPDIR，不加store全量快照。

源码兼容只在本次确实修改tagger/session资源根时执行：从同SHA源读取。源码pytest子项需要执行环境提供 `DEV_PYTHON`：已有 pytest、版本不低于 3.11 的开发解释器绝对路径；不在线安装依赖。适用时从本机已存在的测试开发环境取得该绝对路径并设置 `DEV_PYTHON`，不要用 `command -v python3` 代选。只在该子项适用时预检路径、Python版本及pytest可运行性。若缺少该路径或其预检失败，只将源码pytest子项记为“无法判断／环境待准备”，继续session源码检查和其他独立必测项。若 §5.3 未取得 `SOURCE`，则跳过本段源码兼容命令，仅记受影响子项为“无法判断”；上面的三个 CLI 检查仍独立执行。下面用干净进程环境不传任何Nix资源根变量，明确保留开发解释器需要的PATH/HOME和隔离endpoint；执行现有 `test/test_entrypoints.py::test_tagger_help_is_available_from_any_cwd` 的无副作用检查。session源码路径用同一已授权隔离endpoint执行原模块：

```bash
# PYTHON用于源码session入口；UV与缓存路径在5.1中设置。
if [ -n "${SOURCE:-}" ]; then
cd "$RUN/work"
if [ -n "${DEV_PYTHON:-}" ] && [ "${DEV_PYTHON#/}" != "$DEV_PYTHON" ] && [ -x "$DEV_PYTHON" ] && \
  "$UV" run --no-project --python "$DEV_PYTHON" -- python -c \
    'import sys; assert sys.version_info >= (3, 11); print(sys.version.split()[0])' \
    > "$RUN/output/dev-python-version.txt" && \
  "$UV" run --no-project --python "$DEV_PYTHON" -- python -m pytest --version \
    > "$RUN/output/pytest-version.txt"; then
  env -i HOME="$HOME" PATH="$PATH" TMPDIR="$TMPDIR" UV_CACHE_DIR="$UV_CACHE_DIR" PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH="$SOURCE" "$UV" run --no-project --python "$DEV_PYTHON" -- python -m pytest -q -p no:cacheprovider \
    "$SOURCE/test/test_entrypoints.py::test_tagger_help_is_available_from_any_cwd"
else
  echo 'Source pytest compatibility: unable to judge; provide an existing Python >=3.11 absolute path with pytest.' >&2
fi
env -i HOME="$HOME" PATH="$PATH" TMPDIR="$TMPDIR" UV_CACHE_DIR="$UV_CACHE_DIR" PYTHONDONTWRITEBYTECODE=1 \
  ZOTERO_MCP_URL="$ZOTERO_MCP_URL" PYTHONPATH="$SOURCE" \
  "$UV" run --no-project --python "$PYTHON" -- python -m zotero_tools.session \
  > "$RUN/output/source-session-id.txt"
test -s "$RUN/output/source-session-id.txt"
else
  echo 'Source compatibility: unable to judge; flake source path unavailable' >&2
fi
```

仅当该源码兼容行为受实现影响才运行，endpoint沿用上一个隔离fixture；源未改注明复用。这里的PYTHONPATH只用于既有源码兼容目标，不能用于安装CLI或修补消费者。无已备开发环境只阻塞对应兼容检查，不能用全套APM/endpoint测试替代。

### 5.5 权限、失败、清理和结果

[skills-test-fixtures PR #43](https://github.com/RekiDunois/skills-test-fixtures/pull/43) 只在实际使用既有fixture时约束隔离权限，不额外引入manifest/hash/信任来源/调用树检查。本计划无需启动Codex/OpenCode，无需读改全局信任。角色接入由正式安装文件判断，不要求模型调用cleaner。

缺Nix/依赖/端点/权限时仅相关项无法判断，其他独立项继续。环境错误最小诊断，同条件最多一次额外重试；产品断言失败不刷重试。必要输出留RUN，正式文件记T1–T5结果、未完成原因与复用记录，不新建证据平台。不调用真实Zotero、不实际清理/标签写入。

收尾可用两个各自环境的 `agent-env remove --project` 移除本次托管资源，解除临时profile引用后保留输出供复核；这只是清理，不新增共享生命周期验收。不终止外部负责人提供的fixture，不按进程名杀进程。源码/APM/OpenCode/uv未受影响的既有结果继续有效。

历史记录：2026-10-15 的 `test-v4.1` 第一、第二关口通过，仅覆盖当时的旧共享库步骤。`test-v5.1` 的变化只涉及共享 SHA、受影响的项目接入及相应结果引用，修订后按测试规则复核；不能沿用旧版本对新增步骤的批准。

### 5.6 旧版准备预检（2026-10-15，历史记录）

- 基础运行时可用：Nix 2.34.8；启用 `nix-command` 与 `flakes` 后，本地纯表达式求值成功。`uv` 为 0.12.22；通过 `uv run` 使用现有 Python 3.14.7，标准库 `tomllib` 可导入。当前主机为 Darwin arm64。此检查没有读取远端 flake，也没有验证包输出或构建。
- 在本段预检发生时，PR head `2b55a5a403b19f1338e3ca33bb0b33d7121fa342` 和 `8cfaa600102f26ce8b9124cbb4c1455d7ebbcbeb` 都只有计划文件，当时无法填写实现 SHA、没有运行正式测试。其后的旧版实现结果已记录于 §5.7；该历史预检不代表新共享库版本的状态。
- T4 所需的已授权隔离回环 MCP fixture 及其 URL 尚未提供；没有启动 fixture，也没有连接 Zotero。源代码兼容检查仅在实现改动资源定位时适用，当前没有需要重跑的源代码检查。
- 工作树自动载入了缓存开发环境，但 `nix-direnv` 无法在只读布局中刷新 gcroot。没有运行 `nix build`，所以这条提示尚不能说明它是否会阻碍正式构建；执行前应在获准的隔离目录按上方 recipe 再检查。
- 本轮针对解释器选择作有限预检：`nix` 2.34.8、`uv` 0.12.22 可用；当前 shell 的 `python3` 为 3.14.7，但导入 `pytest` 失败，因此不能用它作为 `DEV_PYTHON`。`uv python list --only-installed` 因默认缓存目录权限不足而未能确认其他已安装解释器。尚未提供一个已安装 pytest、版本不低于 3.11 的开发解释器绝对路径；执行源码兼容步骤前须由执行环境提供该值。没有安装依赖，也没有运行正式测试。

### 5.7 旧共享版本实施测试结果（2026-10-16，历史记录）

- Producer SHA：`ae4b9d411589cea8728ae371787196c894f0d642`；平台：`aarch64-darwin`；共享 SHA：`760c1bf60e8ec19d1985660ec5e3276a8ef80b5a`；Nixpkgs：`55bfb4d7437bd4e09ab7cba58a43bd68eb310044`。结果目录：`/private/tmp/issue26-nix-CkxdxV`。
- T1 通过：固定 SHA 的日常包构建和独立 profile 安装成功；三个 CLI 均可执行；payload 包含三项完整技能、阅读脚本及导出辅助文件、标注脚本及对应 schema，不含 cleaner。包输出：`/nix/store/za8lm1h1x758a8q38cm0f5bi48vsp3kf-zotero-tools-0.1.0`。
- T2 部分通过：固定 SHA 的 cleaner 包构建成功；包清单仅声明 cleaner 技能和角色，`dependencies` 为空。共享 `apply` 无法判断：现有 `CODEX_HOME` 指向 `/tmp/test-codex-home/config.toml`，共享层的安全检查拒绝 `/tmp` 符号链接祖先；按计划未改 `CODEX_HOME`、配置或信任。
- T3 部分通过：日常包经共享 `mkProject/apply` 后，三个技能出现在消费者 `.agents/skills`，且没有 cleaner 技能或角色；cleaner 包生成的 TOML 三字段与同 SHA 源角色一致。cleaner 独立消费者未能完成 `apply`，原因同 T2，因此两消费者接入整体无法判断。
- T4 部分通过：从仓库外运行 `zotero-paper-tagger --help` 与 `zotero-item-export --help` 均成功。已授权隔离回环 MCP fixture 和 URL 未提供，随包及源码 `zotero-mcp-session` 初始化无法判断；源码 pytest 兼容子项也无法判断，当前没有已安装 pytest 且版本不低于 3.11 的开发解释器。未连接真实 Zotero。
- T5 部分通过：复用 T1/T4 结果确认 profile 中三个可执行 CLI、资源齐全且默认包不含 cleaner；help 调用从临时工作目录完成，未运行 Zotero 业务写入。endpoint/session 子项沿用 T4 的无法判断结果。
- 候选修正记录：初版 Python 3.11 与 PyMuPDF/NumPy 依赖不兼容，按项目声明改为 Python 3.12；随后发现共享 `runCommand` 忽略 `postBuild`，CLI 链接因此未进入 profile。最终版本将链接追加到 `buildCommand`，并在本条 SHA 通过 T1。

### 5.8 PR #3 升级影响与新版复核状态（2026-10-16，待执行）

- **变更原因和输入**：共享 [PR #3](https://github.com/RekiDunois/agent-env-nix/pull/3) 已合并；新的 `package.nix` / `project.nix` 保留调用接口，但选中技能/角色文件整体替换、配置保护只针对 MCP，且失败后无跨文件回滚。Issue #26 已同步该行为。旧共享输入 `760c1bf60e8ec19d1985660ec5e3276a8ef80b5a`、历史生产者 `ae4b9d411589cea8728ae371787196c894f0d642` 的已有结果仅在不受上游变化影响时复用。
- **T1（新版待执行）**：用生产者新 SHA 构建两个包、核对日常包资源/CLI 和 cleaner 独立性。新共享 `mkAgentPackage` 的 shell 文件复制替代旧路径；因此不能把 §5.7 旧版 T1 通过直接记为新版通过。仅沿用 §5.2 既有检查入口。
- **T2、T3（新版待执行）**：以新共享 SHA 的 `mkProject/apply` 分别部署两个全新隔离消费者，继续用 §5.3 的源角色三字段、技能目录位置及包独立性断言。旧版 cleaner 的 `CODEX_HOME` 路径拒绝是在旧版安装时出现的环境阻断；新版无需所选 MCP 配置，预期不读取该无关路径，但以实际 `apply` 结果决定通过或无法判断。不额外构造“用户编辑被覆盖”或重复共享层通用失败恢复测试。
- **T4（部分旧结果可复用）**：仅当产品三 CLI、Python 包装和资源定位未改变，复用 §5.7 已通过的 tagger/item-export `--help`；若这些文件随升级改变，只复核受影响命令。已授权的隔离 Zotero MCP endpoint 未提供，session 初始化仍为无法判断；需要 pytest 的源码兼容子项仍按 §5.4 所写的适用条件决定，不用上游合并作为重跑理由。
- **T5（新版待引用）**：按原定义直接采用新 T1–T3 的包/资源/独立性结果和仍有效的 T4 输出，不增加专用检查、不验证共享通用回滚、GC/迁移或额外平台。
- **已存在的上游证据**：共享库在 `aarch64-darwin` 的 T1–T4（含 38 个单元检查及集成安装）已有 [正式记录](https://github.com/RekiDunois/agent-env-nix/blob/ba2d0fe4ef4d1dc1d80ec628c3ecc6607829a76e/docs/validation.md)。按 Test Engineer Rule 不在本仓重复执行其通用校验。新 producer 构建/安装的业务结果必须由本仓正式入口确认；正式尝试与环境阻断按 §5.5 记录，仍不得连接真实 Zotero。
- **审核与交接**：旧计划关于包划分与固定 CLI 的决定不变，可沿用未受影响的审核依据；共享文件所有权/故障处理变化影响执行计划 P1、P3、P4，测试步骤第二关的共享 SHA 和 T1–T3 接入方式需要定向复核。无独立子代理审核结果，不声称新计划已批准。负责人：计划审核者复核受影响关口；产品实现负责人更新锁文件/README；本地测试工程师执行上述仍需结果。

## 6. 当前状态

执行计划 v5 和测试修订 `test-v5.1` 已写作待审候选，**Plan proposed review status: pending**；本次文档修改不代表独立审批、实现或测试通过。PR #27 现有产品仍锁定 `760c1bf60e8ec19d1985660ec5e3276a8ef80b5a`，等待实现负责人将 `flake.nix`/`flake.lock` 与 README 更新至 `ba2d0fe4ef4d1dc1d80ec628c3ecc6607829a76e`。旧版实施符合性和 T1–T5 结果保留在 §5.7；新共享库的 T1/T2/T3/T5 尚无正式执行结果。原 T4 两个 help 已通过，隔离 endpoint 初始化与源码 pytest 尚未判断。不得将共享库自身已通过的 Mac 测试当作本仓安装结果，或以旧版失败阻断冒充新版已失败。

