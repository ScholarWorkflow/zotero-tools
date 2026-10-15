# Issue #26：复用 agent-env-nix 的 Zotero 独立分包计划

- Requirement revision：2026-10-15 共享层替换版 [Issue #26](https://github.com/ScholarWorkflow/zotero-tools/issues/26)。
- Plan revision：issue26-plan-v4-2026-10-15。本文件直接替换旧完整方案，是唯一执行与最小测试计划，没有并行旧版本或附加测试清单。
- Target revision：业务基线 `7c39f03f0d6010e3e4ce8e51f7fc8ba761ef58d8`；替换前计划 head `eac90a39fc2eea33075fafb8deb721d4fe6d1256`。
- Shared revision：[agent-env-nix PR #1](https://github.com/RekiDunois/agent-env-nix/pull/1)，`760c1bf60e8ec19d1985660ec5e3276a8ef80b5a`，open、未合并，属于接口候选而非已发布稳定版本。
- Proposed review status: pending。仅改需求/计划，未实现、未测试；正式审核后在本 PR 同一分支实施。
- 规则：[Project Consensus](https://app.notion.com/p/rekidunois/Project-Consensus-3d60101a85f3815a8c43f271f2b4d91d)、[Plan Reviewer Rule](https://app.notion.com/p/rekidunois/Plan-Reviewer-Rule-3e80101a85f3817a94cbc6eca1a76a5c)、[Test Engineer Rule](https://app.notion.com/p/rekidunois/Test-Engineer-Rule-3d80101a85f380d8a8f5ce528141e253)。引用不新增本计划之外的测试。

## 1. 方案、依据与边界

需求是日常工具与破坏性 cleaner 分开、完整资源、固定依赖、原有角色确认和 APM 行为保留。当前 Python tagger/session 按模块目录向上查找 `.apm/skills`，进入 Nix Python 库后不能自然成立，技能也仍使用 uv/shell/PDF 命令。因此 producer 负责固定运行包、资源根和必要 Nix 调用适配，共享层负责声明式包、组合、复制和 Codex 角色/配置保护。仅复制 SKILL.md、给所有功能一个默认大包、每仓再建安装器均不满足这一职责分离。

关键事实来源：
- [pyproject.toml](https://github.com/ScholarWorkflow/zotero-tools/blob/7c39f03f0d6010e3e4ce8e51f7fc8ba761ef58d8/pyproject.toml)：Python >=3.11、三个 console scripts；[源技能/角色](https://github.com/ScholarWorkflow/zotero-tools/tree/7c39f03f0d6010e3e4ce8e51f7fc8ba761ef58d8/.apm)；[tagger.py](https://github.com/ScholarWorkflow/zotero-tools/blob/7c39f03f0d6010e3e4ce8e51f7fc8ba761ef58d8/zotero_tools/tagger.py)、[session.py](https://github.com/ScholarWorkflow/zotero-tools/blob/7c39f03f0d6010e3e4ce8e51f7fc8ba761ef58d8/zotero_tools/session.py) 的资源定位。
- 共享 [package.nix](https://github.com/RekiDunois/agent-env-nix/blob/760c1bf60e8ec19d1985660ec5e3276a8ef80b5a/lib/package.nix) 接受完整 files、exports.skills/agents、两类依赖；[project.nix](https://github.com/RekiDunois/agent-env-nix/blob/760c1bf60e8ec19d1985660ec5e3276a8ef80b5a/lib/project.nix) 递归组合并生成 apply/remove；[README](https://github.com/RekiDunois/agent-env-nix/blob/760c1bf60e8ec19d1985660ec5e3276a8ef80b5a/README.md) 明确生成物所有权、闭包与实际复制。
- [Codex skills](https://developers.openai.com/codex/skills)、[subagents](https://developers.openai.com/codex/subagents)：技能需进入发现位置；角色为 name、description、developer_instructions 的原生 TOML。共享库不会读取 APM frontmatter 并自动理解其宿主 variants，本仓仍须准确选取描述/正文。

预期变化：新增两独立 agent 包和共享 Codex 接入；保留：原四技能、源角色、三个 CLI 业务、APM/OpenCode/uv 非 Nix 路径、运行时端点参数、cleaner 确认。禁止：默认带 cleaner、真实数据写入测试、业务/schema 重构、虚构 Zotero MCP 服务、改消费者仓库或用户信任、秘密入 store。

## 2. 唯一接口及 producer 修改点

### 2.1 包声明与选择

新增 flake.nix/flake.lock、nix/，共享 input 固定上述 SHA 与实际 nixpkgs/平台。共享仓访问使用现有 Nix/Git 认证，不将 token 写进声明。仅对实际验证平台声明可消费。

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

消费者调用共享 `lib.mkProject { inherit pkgs; roots = [ ... ]; }`，构建环境后显式运行 `bin/agent-env apply --project <project>`。本仓只给可复用例子，不写本仓 installer/consumer-view。构建和 profile CLI 安装均不等于技能已发现；apply 生成实际 `.agents/skills/<name>` 文件和 `.codex/agents/<name>.toml`，Codex 是否信任由宿主既有配置决定。

共同职责全部复用共享层：递归依赖、同一包身份去重、导出碰撞拒绝、完整复制、原生 TOML、相关配置层检测、保活 GC roots、apply/remove。不同包同名 export 即使内容相同仍拒绝；项目已有等价未管理资源则复用不认领。不能用“所有等价来源都合并”替代这一真实合同。

已管理技能目录为生成物，用户应改源仓库；升级/移除允许整树替换/删除。其他来源技能不动。已管理 agent/config 若与上次生成值不同则保留并报告；其他配置/未知字段保留。共享 apply 不写全局配置、不改信任，无法读取的 managed/cloud/MDM 或后续会话覆盖不在保证内；不承诺整个项目原子性。冲突停止相应接入，不静默覆盖，不在本仓建设第二套保护实现。

## 4. 实施顺序和完成边界

1. 正式审核本完整计划；确认 producer/shared 精确 SHA、Nix/平台和直接调用。共享接口更新需分析影响再改锁，不能直接追浮动主分支。
2. 实现共享 flake 引用及两包声明；先完成日常固定资源/runtime/CLI，保留 default 不含 cleaner。
3. 完成 cleaner 独立声明及源角色到 description/body 的最小适配；不重造共享 TOML 投影或碰撞检测。
4. README 记录 build/profile CLI 与共享 mkProject/apply 的区别、两个包的资源/CLI、Codex-only override、APM 兼容、可写目录、外部 Zotero 前提与可引用 SHA。
5. 同 PR 按以下唯一最小清单记录结果。日常包先就绪可供 professor-research-core/explainer/contact 接入，cleaner 不阻塞；不修改消费者。两包完整后按现行合并审核，合并 Closes #26 关闭 issue。

## 5. 唯一最小测试计划

测试修订：test-v4.1（2026-10-15），完整替换原测试步骤。实现方案v4不变，不因本次文档SHA重开未受影响P1–P4。当前未执行，不声明测试通过。T1–T5是范围上限，重复观察合并，不把共享库的通用安装/配置/依赖图回归复制到本仓。

| 项 | 输入/场景 | 预期与检查方法 |
|---|---|---|
| T1 日常构建 | 固定实现SHA的zotero-tools | 构建成功；三完整技能、helpers/schema、Python模块、三个可安装CLI；不含cleaner |
| T2 独立cleaner | 同SHA的cleaner单root | 构建与共享部署成功；只带声明技能/角色，没有无依据的日常/研究依赖 |
| T3 角色与接入 | 两个独立consumer，经共享mkProject/apply | 实际Codex发现位置正确，角色三字段与同SHA源名称/描述/正文一致；不另测OpenCode Nix产物/通用投影算法 |
| T4 实际入口 | profile安装三CLI、隔离端点；受影响原源码路径 | 两help成功；真实mcp-session入口初始化获会话ID；无Nix资源根时原源码定位保留 |
| T5 工具与状态 | 复用上面安装和调用 | 固定工具/资源可用，不写store、不接触真实Zotero；日常无cleaner。合并T1/T3/T4观察，不再加独立测试层 |

### 5.1 准备参数与正式共享入口

以下是实施后的执行 recipe，本次只写计划，不执行。执行者从待测实现填入 `PRODUCER_SHA`、`SYSTEM`（例如 aarch64-darwin 或 x86_64-linux）；当前文档提交没有 Nix 产品，不得拿它运行后报产品失败。`SHARED_SHA` 使用 producer 实际锁定的共享实现，本文接口基准为 760c1bf60e8ec19d1985660ec5e3276a8ef80b5a；若仅文档提交更新，不因此重跑无影响结果。需要现成 Nix flakes、Python >=3.11 和正常仓库读取权限，缺失只暂停相关项，不安装新的通用测试工具。

```bash
set -euo pipefail
export PRODUCER_SHA='<待测实现的远端40位SHA>'
export SYSTEM='<已支持的平台>'
export SHARED_SHA=760c1bf60e8ec19d1985660ec5e3276a8ef80b5a
export REPO='ScholarWorkflow/zotero-tools'
export REF="github:$REPO/$PRODUCER_SHA"
export RUN="$(mktemp -d /tmp/issue26-nix-XXXXXX)"
mkdir -p "$RUN/compose" "$RUN/output" "$RUN/work" "$RUN/cache" "$RUN/state"
export XDG_CACHE_HOME="$RUN/cache" XDG_STATE_HOME="$RUN/state" TMPDIR="$RUN/work"
export SOURCE="$(nix eval --raw "$REF#outPath")"
```

不修改 HOME/CODEX_HOME、用户信任或已有 eval 服务。消费者位于仓库/worktree 外，所选路径须已获准用于隔离运行。实际需要Codex时通过既有eval命令显式传入 `--sandbox workspace-write`；不读取或审核eval服务的Codex信任名单，不增设预先信任检查，也不修改全局信任。只有真实执行返回权限问题时，才按运行环境结果处理。只记录实际 SHA、consumer 路径、安装命令和结果位置，不额外制作来源 manifest、hash 链或全环境快照。

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

下面直接读取本次正式安装文件及同SHA只读源；只做目标字段/资源断言，不调用APM转换，不运行整套projection测试，也不新增比较工具文件。

```bash
python3 - "$TOOLS_CONSUMER" "$CLEANER_CONSUMER" "$SOURCE" <<'PY'
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
python3 - "$ZOTERO_MCP_URL" <<'PY'
import sys,urllib.parse
u=urllib.parse.urlsplit(sys.argv[1])
assert u.scheme=='http' and u.hostname=='127.0.0.1' and u.port and u.path=='/mcp'
PY
"$RUN/profile-tools/bin/zotero-mcp-session" > "$RUN/output/session-id.txt"
test -s "$RUN/output/session-id.txt"
```

执行前确认该URL确是授权fixture；URL形状断言不代替授权。检查输出是非空会话标识，真实安装命令进入随包new-session.sh，只发送initialize，不执行业务读写/删除。空ID或命令失败不算通过；不以help/路径存在替代。T5直接复用这次及help的输出与可写TMPDIR，不加store全量快照。

源码兼容只在本次确实修改tagger/session资源根时执行：从同SHA源读取并使用其正常开发Python环境（已有固定pytest；不借机在线安装）。下面用干净进程环境不传任何Nix资源根变量，明确保留开发解释器需要的PATH/HOME和隔离endpoint；执行现有 `test/test_entrypoints.py::test_tagger_help_is_available_from_any_cwd` 的无副作用检查。session源码路径用同一已授权隔离endpoint执行原模块：

```bash
# PYTHON为已有开发环境的绝对Python入口，包含本项目既有测试依赖。
export PYTHON='<已有开发Python绝对路径>'
cd "$RUN/work"
env -i HOME="$HOME" PATH="$PATH" TMPDIR="$TMPDIR" PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH="$SOURCE" "$PYTHON" -m pytest -q -p no:cacheprovider \
  "$SOURCE/test/test_entrypoints.py::test_tagger_help_is_available_from_any_cwd"
env -i HOME="$HOME" PATH="$PATH" TMPDIR="$TMPDIR" PYTHONDONTWRITEBYTECODE=1 \
  ZOTERO_MCP_URL="$ZOTERO_MCP_URL" PYTHONPATH="$SOURCE" \
  "$PYTHON" -m zotero_tools.session \
  > "$RUN/output/source-session-id.txt"
test -s "$RUN/output/source-session-id.txt"
```

仅当该源码兼容行为受实现影响才运行，endpoint沿用上一个隔离fixture；源未改注明复用。这里的PYTHONPATH只用于既有源码兼容目标，不能用于安装CLI或修补消费者。无已备开发环境只阻塞对应兼容检查，不能用全套APM/endpoint测试替代。

### 5.5 权限、失败、清理和结果

[skills-test-fixtures PR #43](https://github.com/RekiDunois/skills-test-fixtures/pull/43) 只在实际使用既有fixture时约束隔离权限，不额外引入manifest/hash/信任来源/调用树检查。本计划无需启动Codex/OpenCode，无需读改全局信任。角色接入由正式安装文件判断，不要求模型调用cleaner。

缺Nix/依赖/端点/权限时仅相关项无法判断，其他独立项继续。环境错误最小诊断，同条件最多一次额外重试；产品断言失败不刷重试。必要输出留RUN，正式文件记T1–T5结果、未完成原因与复用记录，不新建证据平台。不调用真实Zotero、不实际清理/标签写入。

收尾可用两个各自环境的 `agent-env remove --project` 移除本次托管资源，解除临时profile引用后保留输出供复核；这只是清理，不新增共享生命周期验收。不终止外部负责人提供的fixture，不按进程名杀进程。源码/APM/OpenCode/uv未受影响的既有结果继续有效。

2026-10-15 独立计划复核已完成：test-v4.1 第一关口（范围）与第二关口（步骤）通过，覆盖本节完整recipe及引用边界；第三关必须等待实施后的真实结果，当前未执行。

## 6. 当前状态

v4 已用共享 mkAgentPackage/mkProject 替换旧 share 布局和每仓接入说明，保留包特有 Python/CLI/资源与角色适配。实现方案审核仍 pending；测试修订 test-v4.1 的独立计划复核已完成，第一/第二关口通过，第三关未执行；没有实现或测试结果通过结论。完成条件是两独立可固定包、共享接入、三个 CLI 和源兼容有效、角色正文保持、外部前提如实记录及 T1–T5 最小结果齐备。
