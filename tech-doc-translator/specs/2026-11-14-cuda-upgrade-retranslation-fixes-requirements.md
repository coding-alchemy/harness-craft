# CUDA 13.5 升级重译问题修复需求

| 元数据 | 内容 |
| --- | --- |
| 文档版本 | V0.4 |
| 文档状态 | V0.4 于 2026-11-16 批准 |
| 创建 / 修订日期 | 2026-11-14 / 2026-11-16 |
| 适用范围 | `tech-doc-translator` 的多页面 API 解析、合章导航与核验，翻译约定，`SKILL.md` 的写权限与升级重译说明，共享安装的维护 |
| 需求来源 | [CUDA Programming Guide 13.5 升级重译复盘](/Users/nanzhang/knowledges/machine-learning/CUDA/cuda_programming_guide/docs/复盘-13.5升级重译-skill问题分析材料.md)；2026-11-14 对复盘的逐条源码核对和对照运行；编写执行计划时对 PG 13.5 全部站内链接的扫描（A.5） |
| 对应设计 | [CUDA 13.5 升级重译问题修复设计](./2026-11-14-cuda-upgrade-retranslation-fixes-design.md)，V0.6 对应本版，2026-11-16 批准 |
| 现行规格 | [CUDA/Sphinx 优化需求](./2026-10-23-cuda-practice-optimization-requirements.md)：R3 表格与格内代码、R6 与 §11 合章导航 |
| 勘察基线 | `main` @ `af470db`，组件目录内容与 `6748024` 相同，CHANGELOG 最新条目为 V1.6。共享安装于 2026-11-14 14:47 比对。本轮做了源码核对和对照运行，未运行测试套件 |

## 1. 用户结果与范围

下一次用本组件翻译或升级重译 CUDA 这类 Sphinx 多页面文档时，应做到：

- 按仓库重装后共享安装与仓库一致（合并主分支后由用户安装）；不改共享安装、不写项目补丁，解析、合章和核验就能完成；
- 翻译约定与核验口径一致，按约定写出的译文能通过核验；
- 一次合章就能看到所有页的全部问题及位置；
- 做升级重译的人能从 `SKILL.md` 找到已有的旧合章导航恢复，并知道它的限制。

只改仓库 `tech-doc-translator/` 下的脚本、`SKILL.md`、`references/` 和测试；共享安装里的改动收回仓库，按仓库重装由用户在合并主分支后进行，不在本次开发内。CUDA 各项目原件只读，验收用临时副本，运行产物写在 Git 工作区外。不新增产品版本号，不发布。各需求的优先级是建议，由用户确定。

文中用语：

| 用语 | 指什么 |
| --- | --- |
| PG | CUDA Programming Guide 13.5 升级重译项目，`/Users/nanzhang/knowledges/machine-learning/CUDA/cuda_programming_guide` |
| BPG、cuBLAS、cuSPARSE | 同期使用本组件的 CUDA Best Practices Guide、cuBLAS、cuSPARSE 13.5 翻译项目，在 `/Users/nanzhang/knowledges/machine-learning.local/CUDA/` 下 |
| 共享安装 | 各项目共用的已安装副本 `/Users/nanzhang/.agents/skills/tech-doc-translator` |
| 就地修改 | 项目会话直接改共享安装里的文件，仓库里没有对应提交 |
| 合章 | `merge_api.py` 按页面清单把译文页合成章节；带 `--navigation-record` 时同时转换链接、给锚点加命名空间 |
| 来源锚点 | 解析时写在对象前的 `<a id="原 id"></a>` 行；锚点绑定检查它后面紧跟的是不是原文里的那个对象 |
| 结构提示 | 解析稿里单独一行的 `[BLOCKQUOTE]`、`[DEF-LIST]` 等标记，表示原文的引用块、定义列表等结构 |
| 片段核验 | `verify_translation.py --fragment`，翻译 Agent 交回工作包前的自检 |

## 2. 基线与保障

### 2.1 可复用的现有能力

修复优先在这些能力上扩展，不另建平行机制。

| 现有能力 | 位置 | 用于 |
| --- | --- | --- |
| 安装脚本不带 `--force` 时，任一文件与仓库不同就报错停止，不写文件 | [`install_skill.py`](../install_skill.py) 第 109–143 行 | R1 核对安装与仓库一致 |
| 交付核验把核验脚本及其共享依赖的摘要绑进证据，脚本一变旧证据失效 | [`verify_delivery.py`](../skills/tech-doc-translator/scripts/verify_delivery.py) 第 457–490、2267–2272 行 | R1 重装后各项目据此重新登记；D3 可参照 |
| 合章的来源记录：快照、解析稿区间和页到章归属，合章时据此转换链接、给锚点加命名空间 | [`_api_navigation.py`](../skills/tech-doc-translator/scripts/_api_navigation.py) 第 378–462 行 | R3、R4 在这套记录上扩展 |
| 逐条豁免的先例：`--approved-extra-math` 按原文表达式逐条放行获准的译注公式 | [`SKILL.md`](../skills/tech-doc-translator/SKILL.md) 校验一节 | D2 方案 A 的登记可参照 |
| API 核验逐页收集问题，最后一起报告 | [`verify_api_translation.py`](../skills/tech-doc-translator/scripts/verify_api_translation.py) 第 110、137–167、396–399 行 | R7 合章报错沿用同样的做法 |
| 片段核验已有锚点比较（`compare_anchors`）和链接缺失检查 | [`verify_translation.py`](../skills/tech-doc-translator/scripts/verify_translation.py) 第 101–102、313–316 行 | R6 在此加顺序检查，不新增入口；R5 改的段落计数由这里和合章共用 |
| 存量合章导航恢复，11-10 在 CUDA 13.4 第 1–5 章副本上验收 | [`merge_api.py`](../skills/tech-doc-translator/scripts/merge_api.py) 第 217–247 行，用法见 [`workflow_helpers.md`](../skills/tech-doc-translator/references/workflow_helpers.md)“恢复当前合章导航” | R8 写进 `SKILL.md` |

### 2.2 必须保留的保障

1. 修复不削弱现有检查。锚点绑错对象、链接丢失或换序、格内代码错配、表头角色丢失，修复后仍被拒绝；每项修复带成对的合法样本和损伤样本。
2. 失败时不写出成品，旧成品和旧证据不变。
3. “源文本来就有的问题”只按原站快照判断，不看译文，译文的错误不能借此放过。

## 3. 需求

| 编号 | 一句话 | 依赖 | 优先级（建议） |
| --- | --- | --- | --- |
| R1 | 共享安装只读；现有就地修改收回仓库，合并主分支后由用户重装 | 安装被改时的提示随 D3 | P0 |
| R2 | 只有表头行的表能认领后面的格内代码 | — | P0 |
| R3 | 带 id 的引用块能作为链接目标 | 译文写法随 D1 | P0 |
| R4 | 源文本来就坏的链接有处置办法 | D2 | P0 |
| R5 | 按约定改写结构提示后，锚点绑定结果不变 | D1 | P1 |
| R6 | 链接顺序要求写进翻译约定，片段核验就检查 | — | P1 |
| R7 | 一次合章报出所有页、所有类别的问题和位置 | — | P1 |
| R8 | `SKILL.md` 说明升级重译可用的旧合章导航恢复及其限制 | — | P2 |
| R9 | figure 里的别名 id 能作为链接目标 | — | P0 |
| R10 | 脚注被引用多次时，解析稿把回链写成纯文字 | — | P0 |

除表中依赖外，各需求互不依赖，可以分开实施和验收。R9、R10 是编写执行计划时扫描 PG 全部站内链接发现的（A.5）：只做 R1–R8，PG 第 4、5 章不加项目补丁仍然合章失败，§1 的第一条结果达不到。

### R1 共享安装只读，就地修改收回（P0，建议）

现象：项目会话遇到组件缺陷时直接改共享安装，截至 11-14 14:47 已改了 6 个文件，其中 `verify_pdf.py` 11-14 下午还在改（A.1）。这份安装在 `~/.agents/skills`；安装脚本未设 `CODEX_HOME` 时默认装到 `~/.codex/skills`（A.4.1）。已造成两类后果：

- BPG 加的源侧脚注引用处理，对 PG 带方括号的脚注写法多套一层方括号，源侧记 `[[1]]`、译文侧记 `[1]`，PG 三页因此失败；同样不加项目补丁，仓库版这三页都通过。复盘把这个函数当成“V1.5 为姊妹项目新加的修复”，算作组件缺陷（A.2、A.4.7）。
- cuBLAS 改的 `link_targets` 在链接包裹图片时，把外层链接目标也丢了（A.2）。

要求：

1. `SKILL.md` 写权限一节写明：不改已安装的 Skill 目录。发现组件缺陷时，在项目 `scripts/` 用运行时包装处理，并在交付说明里记下缺陷、包装位置和复现样本，供回流组件。
2. 逐个处置 A.1 的就地修改，实施时重新比对；之后新增的就地修改按同样原则处置：
   - BPG 的对账修复合入仓库，源侧脚注引用只取编号，与渲染端一致；
   - cuBLAS 的 `link_targets` 修复合入仓库：跨空行的误配继续丢弃；链接包裹图片时计外层链接目标，不计图片地址；
   - `compare_anchors` 的放宽不合入，同一问题由 R5 解决；
   - 其余改动（`verify_translation.py` 的 H1 数量、`verify_pdf.py`、`export_pdf.py`）本文不评估、不合入；需要的项目自行改用项目级包装，要进组件的另提需求。
3. 合并主分支后，由用户按仓库重装，使共享安装与仓库逐字节一致；重装不在本次开发内。重装会让依赖就地修改的进行中项目失去这些改动，检查器摘要也会变化（2.1）。
4. 安装被改过时是否自动提示，按 D3 的决定。

### R2 只有表头行的表认领格内代码（P0，建议）

现象：Sphinx 选项卡里的单格代码表，解析成只有表头行的表（复盘称壳表）：一行内容为一个空格，接着是 `---` 分隔行、空行和 `[TABLE-CODE r=1 c=1#1]` 标记。认领标记时从最后一个表格行的下一行开始找，碰到分隔行就停，标记成了孤儿（A.4.2）。13.5 全站只有 async-barriers（14 张）和 pipelines（3 张）有这种表，两页解析对账都失败；async-barriers 的 13.4 快照同样失败，`b7542b8`（10-24 的 V1.4 更新）、`5baa705`（V1.5）、`6748024`（V1.6）结果相同（A.2）。

要求：没有数据行、只有表头行的表，其后的格内代码标记和围栏归属到该表；两页在不加项目补丁时解析对账通过，各格代码与源一致；格代码互换、删掉围栏、坐标越界仍被拒绝。

### R3 带 id 的引用块作为链接目标（P0，建议；译文写法随 D1）

现象：unified-memory 页把两段引文做成带 id 的引用块（`<blockquote id="um-legacy-memcpy-cit1">` 和 `cit2`），正文 5 处 `(1)`、`(2)` 链到它们。来源锚点只登记标题、表格、图片、段落、代码、提示框六类对象，不含引用块，合章时这 5 处报“来源目标缺失或无法定位”（A.4.3）。PG 项目补丁让它们原样通过；PG 已合出的第四章里这 5 处仍指向原片段，章内没有对应 id，点了不跳转（A.2）。

要求：带 id 的引用块成为可定位的来源对象；合章后这 5 处链接跳到对应引用块，改指另一个引用块的译文被拒绝。引用块在译文里的写法随 D1 的决定。

### R4 源文本来就坏的链接（P0，建议；按 D2）

现象：extended-gpu-memory 页有一处 `#virtual-memory-management`，这个 id 在本页快照里不存在，13.4 也一样，看上去是漏写了页路径。现在合章直接失败，组件里没有处置办法。PG 项目补丁让它原样通过，已合出的第四章里它同样点了不跳转（A.2）。

要求：

1. 合章能识别“目标 id 在目标页快照里根本不存在”的链接，报告页、行和原目标；
2. 目标 id 在快照里存在、只是解析器没登记的（如 R3），仍按解析缺口失败；
3. 判断只依据原站快照；译文把正常链接改成不存在的目标，仍被拒绝；
4. 是否阻断、成品里怎么呈现，按 D2 的决定。

### R5 改写结构提示不改变锚点绑定（P1，建议；按 D1）

现象：翻译约定要求把 `[BLOCKQUOTE]`、`[DETAILS]`、`[FOOTNOTE-LIST]` 等结构提示改成可读写法。锚点绑定按“第几个顶层段落”认段落对象，结构提示的标记行本身算一个段落；改写后段落数变了，其后的段落锚点全部错绑（A.4.4）。mathematical-functions 实测：11 处 `[BLOCKQUOTE]` 中，段落锚点之前的 6 处改任何一处都报错绑（A.3）。复盘 §5 第 5 轮的 `[DEF-LIST]` 段落漂移，以及 cuBLAS 就地修改注释里的 `[DEF-LIST]`、`[FOOTNOTE-LIST]`，是同一类现象。PG 为通过核验把 10 处改回了 `[BLOCKQUOTE]`，成品里留着结构提示。

要求：

1. 翻译约定与锚点校验一致：按 D1 选定的写法写出的译文通过绑定校验和片段核验；
2. 锚点挪到别的对象前，包括同一节里别的段落，仍报错绑；
3. 已实测的 `[BLOCKQUOTE]` 直接覆盖；`[DEF-LIST]`、`[FOOTNOTE-LIST]` 等由设计阶段用真实页面复现，复现的按同样要求处理。复盘提到的缩进差异，先确认是否改变实际渲染，改变渲染的不算等价写法。

### R6 链接顺序要求前移（P1，建议）

现象：API 合章和 API 核验要求页内链接与原文顺序完全一致，但翻译约定只要求保留原链接目标，片段核验只查有没有缺链接（A.4.5）。复盘记录 7 页因中文语序调换了链接先后，到合章才发现。

要求：

1. 翻译约定写明 API 页面的链接按原文顺序出现，调整语序时不交换两个链接的先后；
2. 片段来自 API 解析稿时，片段核验检查链接顺序，报出第一处不同的位置和两侧目标；其他源家族的链接检查不变；
3. API 合章对链接顺序的要求不变。

### R7 一次合章报全问题（P1，建议）

现象：合章遇到第一个出错的页就退出；一页之内锚点不过就不查链接，链接不过就不查表格（A.4.6）。错绑只报锚点名，链接顺序只报页名。复盘 §5 第 3–6 轮报出的锚点错绑、链接顺序、表头角色，正是合章依次检查的这三类；复盘记录每轮全量合并加校验约 40 分钟。

要求：

1. 一次合章检查完所有页的锚点、链接和表格，汇总报出后以失败退出；表格问题沿用现有的表号、行号和格位；
2. 错绑报出锚点名、期望对象（类型和序号）、实际紧随的对象（类型、序号和译文行号）；
3. 链接顺序不符报出第几个链接、源目标、译文目标和译文行号。

### R8 升级重译的说明（P2，建议）

现象：复盘认为组件没有旧版到新版的迁移工具，自写了槽位生成器（`build_trans_13_5.py`，796 行），又经 6 轮修复。V1.6 已有存量合章导航恢复（2.1），验收见 [CUDA 优化需求 §11.4](./2026-10-23-cuda-practice-optimization-requirements.md#114-最终验收结论2026-11-10)，但 `SKILL.md` 没在升级重译的场景下提到它。

要求：`SKILL.md` 说明，已有旧版译文、源升级时：

1. 旧合章缺来源锚点或导航的，可先用 `merge_api.py --recover-navigation-from` 按旧版快照把旧合章迁到当前合同；
2. 它只迁移锚点和导航，不处理源内容的变化，变化部分仍按正常流程翻译；旧译文里与当前表格合同不符的表会阻断恢复，CUDA 13.4 第 1–5 章实测有 55 张须先回源修正。

### R9 figure 里的别名 id 作为链接目标（P0，建议）

现象：docutils 给同一元素多个 id 时，第一个写在元素上，其余写成元素开头的空 `<span id>`。async-copies 的三幅图就是这种写法，如 `<figure id="id2"><span id="figure-swizzle-example1"></span>…`；正文 `Figure 51`、`Figure 52`、`Figure 53` 三处链到这些别名。来源锚点只把 figure 自身的 id 登记为其中的图片，别名没登记：译文按约定保留这 3 处链接时，合章报“来源目标缺失或无法定位”。section 开头、标题之前的同类别名，组件早已登记为标题（PG 13.5 的 section 开头共有 697 个这种别名），figure 的没有。PG 靠项目补丁的豁免清单放行，现有译文把这 3 处写成了纯文字（A.5）。

要求：figure 开头的别名 id 与 figure 自身的 id 一样，登记为其中的图片对象，解析稿在图片前写出别名锚点；合章后这 3 处链接跳到对应的图；锚点改到另一幅图前的译文被拒绝。

### R10 脚注多回链写成纯文字（P0，建议）

现象：同一脚注被正文引用多次时，Sphinx 在脚注定义里写一组回链 `(1, 2, 3)`，每个回链指回正文里的一处脚注引用。引用在行内，没有块边界，不能成为来源对象。解析稿把这组回链写成了链接 `([1](#id2), [2](#id3), [3](#id4))`，这些链接在合章时找不到对象：compute-fabric-transport、compute-capabilities 各 3 处，译文保留它们时报“来源目标缺失或无法定位”。只被引用一次的脚注，回链在标签里，解析时随标签一起去掉，不产生链接。PG 靠项目补丁的豁免清单放行，现有译文已写成纯文字 `(1, 2, 3)`（A.5）。

要求：

1. 解析稿把多个回链写成纯文字，如 `(1, 2, 3)`，和只引用一次的脚注一样不产生链接；脚注定义照常对账，删掉一处脚注引用仍被拒绝；
2. 有这种脚注的页按来源导航合章、核验通过；
3. 只处理 docutils 当前的 HTML5 写法（回链标为 `role="doc-backlink"`）；旧版 dl 写法不在范围内（§7）。

## 4. 方案决定

### D1 结构提示在译文里怎么写（R3、R5）

锚点绑定按“第几个顶层段落”认段落对象，结构提示的标记行本身也算一个段落。翻译约定要求把结构提示改成可读写法，一改，这个“段落”没了，后面的段落锚点就对不上（A.3、A.4.4）。

| 方案 | 做法 | 成品 | 改动 | 剩余风险 |
| --- | --- | --- | --- | --- |
| A（推荐） | 约定为每种结构提示指定可读写法（引用块、列表等，不新增顶层段落）；校验不把结构提示行及其续行算作段落 | 可读 | 约定文字和段落计数一起改 | 写法不在约定里时仍会报错，需回到约定 |
| B | API 页面保留结构提示原样 | 留着 `[BLOCKQUOTE]` 等结构提示 | 只改约定文字 | 与 reference 家族“成品必须消除标记”的规则不一致 |
| C | 段落锚点只比类型不比序号，即 cuBLAS 11-14 在共享安装 `compare_anchors` 里的改法 | 可读 | 一处比较逻辑 | 锚点挪到同节别的段落前不会被发现 |

推荐 A：成品可读，校验能力不降。2026-11-14 选定 A。

### D2 源文本来就坏的链接怎么处置（R4）

例子是 extended-gpu-memory 页的 `#virtual-memory-management`：本页没有这个 id，原站上点了也不跳转。现行规则有两条，方向不同：

- [CUDA 优化需求 §11.2](./2026-10-23-cuda-practice-optimization-requirements.md#112-修复需求) 第 2 条：来源导航所需记录缺失、目标缺失、歧义或无法证明归属时，报告译文文件、引用位置、原目标及缺少的依据，完成处置前阻断相应验收。
- [`SKILL.md`](../skills/tech-doc-translator/SKILL.md) 校验一节：源文原样包含的历史格式异常只有在译文新增或扩大差异时才判 FAIL。

组件现在没有任何处置手段，只能失败。

| 方案 | 合章 | 成品 | 改动 | 剩余风险 |
| --- | --- | --- | --- | --- |
| A（推荐） | 报告并阻断；主 Agent 回源确认后登记，登记过的放行 | 保留链接文字，去掉链接 | 新增登记（优先复用来源记录）和去链接改写 | 多一步登记，PG 目前只有这 1 处 |
| B | 同 A | 原样保留原片段，和原站一样点了不跳转 | 登记，另外 PDF 导出和核验要接受这一类 | PDF 里留一个点不动的链接 |
| C | 自动识别后直接放行，只报告 | 保留链接文字，去掉链接 | 去链接改写 | 改变 §11.2“处置前阻断”的已批准规则 |

推荐 A：符合 §11.2 已批准的规则，读者不会碰到点不动的链接，PDF 导出不用新增类别。2026-11-14 选定 A。

### D3 安装被改过时要不要自动提示（R1）

R1 的规则写进 `SKILL.md` 后，仍可能有会话不遵守。现在被改过的安装和正常安装看不出区别：安装目录里没有版本或摘要信息；安装脚本在仓库里，用安装的会话不一定知道仓库在哪。6 个文件在一天多里先后被改，各项目都没收到提示，PG 的复盘也因此把就地修改造成的失败当成了组件缺陷。现有的检查器摘要绑定（2.1）只能发现“和上次登记时不同”，分不出是不是发布版。

| 方案 | 做法 | 改动 | 剩余风险 |
| --- | --- | --- | --- |
| A（推荐） | 安装时把各文件摘要写进安装目录；解析、合章和核验运行时比对，不一致就在输出开头列出被改的文件，不阻断 | 安装脚本写清单，入口处比对一次 | 清单也能被一起改掉，只防不知情或无意的修改 |
| B | 只靠 R1 的规则，怀疑时人工用安装脚本核对 | 无 | 被改了也没人知道，直到有人去比对 |

推荐 A：PG 这次误判的那种情况，第一次解析就会看到提示。2026-11-14 选定 A。

## 5. 直接验收

验收用临时副本，产物写在 Git 工作区外；合法样本与损伤样本成对。测试通过、文件存在都不能单独证明完成。

| 编号 | 需求 | 用户可观察的成功证据 |
| --- | --- | --- |
| V1 | R1 | `SKILL.md` 写权限一节有新规则；设计文档逐项写明 A.1 每处改动的处置和理由；安装脚本装出的受管文件与仓库逐字节一致（安装测试，临时目标）。共享安装的实际重装与核对由用户在合并主分支后进行 |
| V2 | R1 | 仓库版不加任何项目补丁：BPG 13.5 单页 21 节逐节对账全部通过（现为 4 节失败）；PG cooperative-groups、unified-memory、compute-capabilities 解析对账通过；cuBLAS `wp_021` 片段核验的链接目标一项通过 |
| V3 | R1 | 链接包裹图片时 `link_targets` 返回外层目标、不含图片地址；跨空行不再误配；删掉外层链接的损伤样本被拒绝 |
| V4 | R2 | async-barriers、pipelines 的 13.5 快照和 async-barriers 的 13.4 快照，不加补丁解析对账通过，17 张表各格代码与源一致；格代码互换、删围栏的样本被拒绝 |
| V5 | R3 | unified-memory 合章后 5 处 `(1)`、`(2)` 链接指向对应引用块的命名空间锚点，API 核验通过；改指另一个引用块的译文被拒绝 |
| V6 | R4 | extended-gpu-memory 合章按 D2 的结果处置该链接，报告给出页、行和原目标；同页其他链接照常转换；把正常链接改成不存在目标的译文仍被拒绝 |
| V7 | R5 | mathematical-functions 11 处 `[BLOCKQUOTE]` 按 D1 选定的写法改写后绑定校验通过；把 `compiler-flags-and-optimizations` 锚点挪到相邻段落前报错绑；`[DEF-LIST]` 等复现样本同样成对通过与拒绝；advanced-kernel-programming、green-contexts 里含代码或表格的引用块按同一写法改写后，片段核验不报残留标记，绑定校验通过 |
| V8 | R6 | API 页面片段交换两处链接，片段核验报出第一处差异的位置和两侧目标；未交换的同一片段通过；其他源家族样本结果不变 |
| V9 | R7 | 临时章含两页，每页各有一处错绑、一处链接顺序不符、一处表头角色丢失：一次合章报出全部 6 处及位置并以失败退出，旧成品不变；修好后同一命令通过 |
| V10 | R8 | `SKILL.md` 的升级重译说明指向的命令和章节真实存在，所写限制与 §11.4 的记录一致 |
| V11 | R1（D3 选 A 时） | 改动共享安装里任一受管文件后运行解析或核验，输出开头列出该文件，结果照常产出；重装后提示消失 |
| V12 | 全部 | 新增测试全部通过；改动前后各跑一次全量回归，失败集合相同（本机改动前有 7 个 PDF 用例失败） |
| V13 | R9 | async-copies 按约定写的译文（保留 3 处图链接和别名锚点）合章后，3 处链接指向对应图片的命名空间锚点，API 核验通过；两个别名锚点互换的译文被拒绝 |
| V14 | R10 | compute-fabric-transport、compute-capabilities 不加补丁解析对账通过，解析稿里的回链是纯文字；含这种脚注的页合章、核验通过；删掉一处脚注引用的样本被拒绝 |
| V15 | 全部 | PG 13.5 工作区外副本：R3、R4、R9 涉及的 3 页按约定准备译文、来源记录按 D2 登记坏链接后，第 1–6 章不加项目补丁合章并通过 API 核验 |

## 6. 复盘条目对照

| 复盘条目 | 本文归属 | 与复盘的不同 |
| --- | --- | --- |
| A1 脚注 `[[N]]` | R1 | 不是发布版缺陷，由 11-13 对共享安装的就地修改造成 |
| A2 壳表代码标记 | R2 | — |
| A3 引文锚点 | R3 | — |
| A4 源文坏链接 | R4、D2 | — |
| （复盘未列）项目补丁豁免的另外 9 处链接 | R9、R10 | 复盘没有单列；PG 项目补丁把它们和 A3、A4 一起按“源缺陷断链”豁免。原快照里这些 id 都在，是解析缺口，不是源文坏链接（A.5） |
| A5 写法与绑定耦合 | R5、D1 | `[BLOCKQUOTE]` 已实测，其余结构提示由设计复现 |
| A6 表头角色报错 | R7 | 报错已有表号、行号和格位；缺的是一次只报一页 |
| A7 校验慢 | 非目标 | 见 §7 |
| A8 错绑报错无定位 | R7 | — |
| A9 表格展开拒绝覆盖 | 不改 | 有意的保护；本次是项目脚本删了映射文件、留下了解析稿 |
| B 没有迁移工具 | R8 | V1.6 已有存量合章导航恢复 |
| C10、E1 链接顺序 | R6 | 根因是翻译约定、片段核验与合章的口径不一致 |
| C1–C9、D、E2–E3 | 不涉及组件 | 执行流程、环境和模型因素 |

## 7. 非目标

- 通用的版本间迁移工具：先按 R8 用已有导航恢复，真实缺口另提需求。
- 校验结果缓存或增量校验：现行设计要求每次独立重做来源对账、不读预存结果（[`verify_delivery.py`](../skills/tech-doc-translator/scripts/verify_delivery.py) 的 `run_source_reconcile`）；R7 减少轮数后再按实测耗时决定。
- 让 `parse_api_html.py --expand-tables grid` 覆盖已有输出（复盘 A9）。
- 把旧写法批量转成约定写法的转换工具（复盘 A5 的建议）：D1 定下写法后不需要。
- 共享安装里与本文问题无关的就地修改的取舍，见 R1 第 2 条。
- 旧版 docutils dl 写法的脚注回链（`dt` 里的 `.fn-backref`，只引用一次的也写成链接）：BPG 有 1 条、cuBLAS 每页 3 条多回链用的是这种写法，两个项目都不按来源导航合章，本次不改，它们的解析稿不变；以后有多页面项目按导航合章遇到，再另提需求（A.5）。
- 复盘里的执行流程、环境、模型因素，以及复盘自身的数据口径。
- 产品版本号、发布，以及 README 当前版本说明的更新，随下次发布处理。

## 8. 最终验收结论（2026-11-16）

R1–R10、D1–D3（均方案 A）已全部实现并验收（`zn_dev` 提交 `bb0acd8`…`12bc3d3`，共 17 个提交；执行计划已按生命周期清理）。逐项结论：

- V2–V9、V11–V15 全部通过：不加任何项目补丁，仓库版组件通过 BPG 13.5 单页 21 节、PG 13.5 全部 54 页（恰好 4 页解析稿变化）及 13.4 async-barriers 的解析对账；PG 工作区外副本第 1–6 章合章与 API 核验全部通过（V15）——unified-memory、extended-gpu-memory、async-copies 与含多回链脚注的页按约定准备译文后，引文、图与坏链接各归其位，各项损伤样本逐个被拒；V7 为四页含片段核验（advanced-kernel-programming、green-contexts 的引用块按约定改写后无残留标记）；V10 所指命令、锚点与 55 张限制与现行记录一致；V11 改动安装副本即提示、重装后消失。
- V12 通过：新增 38 个测试用例全部通过；改动前后全量回归的失败集合相同（本机 7 个 PDF 用例在改动前同样失败；读 Git 历史的 1 个用例在工作区外副本上失败、真实 checkout 上通过），最后全量实测 1379 个通过。
- 验收后两处更正已并入最终行为：含代码或表格的引用块按 §D-1 选定写法去掉提示行、代码与表格留在列 0（`3a3cf4f`）；存量恢复按同一节内位置对应引用块，含带 id 引用块的那一节旧译文的 `>` 引用块须与原文一一对应（`52913f6`、`12bc3d3`；13.4/13.5 unified-memory 的 cit1、cit2 各自对到 host/device 两段引文已实测）。`CHANGELOG.md` 只有“未发布”条目，未发版。
- V1 未执行：共享安装重装待用户定时机、备份目录与通知对象后进行（R1 第 3 条）。执行口径：备份写到 Git 工作区外且不在 `~/.agents/skills/` 下的位置；通知 BPG、cuBLAS、cuSPARSE 和做 13.4 交付验证的会话；`CODEX_HOME=/Users/nanzhang/.agents` 用仓库版安装脚本 `--force` 重装后，不带 `--force` 复跑正常结束、受管文件与仓库逐字节一致、安装目录有 `.install-manifest.json` 且运行任一入口无“与安装清单不符”提示，即为 V1 通过；重装后各项目检查器摘要变化、交付证据按现有规则重新登记。重装完成前，共享安装与仓库不一致，附录 A.1 所列就地修改造成的问题仍在。

## 附录 A 证据

### A.1 共享安装与仓库的差异

2026-11-14 14:47 用 `diff -rq` 比对共享安装与仓库 `skills/tech-doc-translator`，排除缓存文件。“来源”取自改动处的注释。

| 文件 | 修改时间 | 来源 | 改动 | 初判 |
| --- | --- | --- | --- | --- |
| `scripts/_source_reconcile.py` | 11-13 11:47 | BPG 13.5 | 源侧脚注引用改读链接文字；定义首行跳过空白文本节点；正文里跟冒号的 `[^N]` 计为引用 | 缺陷修复，脚注引用写法有误 |
| `scripts/_verification.py` | 11-13 20:42 | cuBLAS 13.5 | `link_targets` 丢弃跨空行的匹配和与图片重叠的匹配 | 跨空行是修复；链接包裹图片时外层目标也丢了 |
| `scripts/verify_pdf.py` | 11-14 01:59、14:11、14:44 | cuSPARSE 13.5 冻结副本；cuBLAS 13.5 | 译注剩余文字分段匹配并回退到页文本；外链尾斜杠等价；标题随代码块移页记 relaxed；独立锚点到表格的允许间距放大；跨行格的链接共享注解时不再判为不可用 | 不在本文范围 |
| `scripts/verify_translation.py` | 11-14 02:38 | cuBLAS 13.5 | 完整文档的 H1 数量从“恰 1 个”改为“与源相同” | 不在本文范围 |
| `scripts/_api_navigation.py` | 11-14 06:25 | cuBLAS 13.5 | `compare_anchors` 中段落只比类型；译文多出的锚点放行 | 削弱核验，同 R5 |
| `scripts/export_pdf.py` | 11-14 07:42 | cuBLAS 13.5 | KaTeX 把 `\mathrm` 当 `\text` 渲染；超宽公式逐级缩小字号 | 不在本文范围 |

cuSPARSE 项目的冻结副本在 `/Users/nanzhang/knowledges/machine-learning.local/CUDA/cusparse/docs/skill-freeze/`，其中 `verify_pdf.py` 与共享安装 01:59 的版本相同。cuBLAS 对 `link_targets` 的修改说明见 [cuBLAS 复核记录](/Users/nanzhang/knowledges/machine-learning.local/CUDA/cublas/docs/review_notes.md)“校验器口径修订”一节，触发样本是该项目的 `wps/wp_021.md` 与 `trans/wp_021.md`。

### A.2 对照运行与成品核对

2026-11-14 用 `~/.venvs/tech-doc-translator/bin/python` 运行，不加载任何项目补丁，输出写在 Git 工作区外。

| 样本 | 仓库 HEAD | 共享安装 |
| --- | --- | --- |
| PG 13.5 cooperative-groups、unified-memory，`parse_api_html.py`；compute-capabilities 另加 `--expand-tables grid` | 3 页通过 | 3 页失败，如 compute-capabilities 的 `10.7 [[1]]` 对 `10.7 [1]` |
| PG 13.5 async-barriers、pipelines | 失败：14 + 3 处孤儿标记及对应格代码错配，共 28 + 6 条 | 同左 |
| PG 13.4 async-barriers | `b7542b8`（V1.4）、`5baa705`（V1.5）、`6748024`（V1.6）都在 L32 报孤儿标记 | — |
| [BPG 13.5 单页快照](/Users/nanzhang/knowledges/machine-learning.local/CUDA/cuda_best_practices_guide/source/index.html) 21 节，复刻项目 [`parse_sections.py`](/Users/nanzhang/knowledges/machine-learning.local/CUDA/cuda_best_practices_guide/scripts/parse_sections.py) 的节模式渲染与对账 | 4 节失败：heterogeneous-computing、deployment-infrastructure-tools 的定义首行读成空，performance-metrics 的提示框文字不符，instruction-optimization 的脚注引用 41 对 39 | 21 节通过 |
| `link_targets('见 [![示意图](images/a.png)](https://example.com/big.png) 图。')` | `['images/a.png']` | `[]` |
| 同一行用 API 家族的 `links()`（markdown-it） | `['https://example.com/big.png']` | 同左 |

PG 已合出的 [`04_CUDA_Features.md`](/Users/nanzhang/knowledges/machine-learning/CUDA/cuda_programming_guide/chapters/04_CUDA_Features.md)（11-14 01:38）里，`#um-legacy-memcpy-cit1` 2 处、`#um-legacy-memcpy-cit2` 3 处、`#virtual-memory-management` 1 处链接都还是原片段；章内 825 个来源锚点都已加命名空间，没有这三个 id。

### A.3 `[BLOCKQUOTE]` 改写实验

输入是 PG 13.5 `05-appendices/mathematical-functions` 的解析稿：11 处 `[BLOCKQUOTE]`，来源锚点里只有一个段落锚点 `compiler-flags-and-optimizations`。每次只把一处 `[BLOCKQUOTE]` 及其缩进内容改成 `> ` 引用，文字不变，用仓库 HEAD 的 `anchor_diffs` 检查。

| 改写位置 | 结果 |
| --- | --- |
| L202、L208、L214、L250、L256、L262，在段落锚点之前 | 各报 1 处“锚点目标错绑: compiler-flags-and-optimizations” |
| L271、L280、L286、L298、L921，在段落锚点之后 | 无差异 |

### A.4 源码摘录

以下除 A.4.7 第二段外均为仓库 HEAD 的现有代码。

#### A.4.1 安装目标

[`install_skill.py`](../install_skill.py) 第 32–40 行：

```python
def skill_target(environ, home):
    codex_home = environ.get("CODEX_HOME")
    try:
        base = (
            Path(codex_home).expanduser()
            if codex_home
            else Path(home) / ".codex"
        )
        return base.absolute() / "skills" / SKILL_NAME
```

已有文件内容不同且未带 `--force` 时，`preflight()` 报 `managed target differs; rerun with --force`（第 140 行），不写任何文件。

#### A.4.2 格内代码标记的认领

[`_source_reconcile.py`](../skills/tech-doc-translator/scripts/_source_reconcile.py) 第 1705–1708 行，表格行扫描跳过分隔行，分隔行不进 `row_lines`：

```python
            cells = line.split(' | ')
            if all(cell.strip() and _MD_TABLE_SEP_CELL_RE.match(cell.strip())
                   for cell in cells):
                continue  # 表头分隔行（单列 --- 同样适用）
```

同文件第 1751–1763 行，认领从最后一个表格行的下一行开始，遇到非空、非标记的行就结束：

```python
            record['group_end_line'] = max((line + merged_lines.get(line, '').count('\n')
                for line in record['row_lines']), default=record['start_line'])
            cursor = record['group_end_line'] + 1
            while cursor <= len(self.lines):
                raw = self.lines[cursor - 1].strip()
                if not raw:
                    cursor += 1
                    continue
                match = _TABLE_CODE_MARKER_RE.fullmatch(raw) or _TABLE_CODE_NOTE_RE.fullmatch(raw)
                if not match:
                    if record['codes'] and cursor in fences:
                        record.setdefault('errors', []).append('L%d 表格代码组多出无归属围栏' % cursor)
                    break
```

只有表头行的表，`group_end_line` 就是表头行，下一行是 `---`，循环在此结束。解析稿形态见 PG [`async-barriers.md`](/Users/nanzhang/knowledges/machine-learning/CUDA/cuda_programming_guide/source-13.5/04-special-topics/async-barriers.md) 第 28–32 行，`␠` 表示该行只有一个空格：

```text
[TABLE]
␠
---

[TABLE-CODE r=1 c=1#1]
```

#### A.4.3 来源锚点与目标解析

[`_api_navigation.py`](../skills/tech-doc-translator/scripts/_api_navigation.py) 第 109–112 行，figure 的 id 转给其中的图片；blockquote 没有对应分支，`target` 是 blockquote 自身，不属于六类对象，id 不登记：

```python
        elif node.name == 'figure':
            target=next((img for img in images if any(p is node for p in img.parents)),None)
        role=objects.get(id(target)) if node.name != 'pre' else None
        if role:result[name]=role
```

同文件第 436 行，片段不在登记表里就抛错，不区分“解析器没登记”和“原站本来没有”：

```python
    if fragment and fragment not in target['anchors']:raise ValueError('来源目标缺失或无法定位: %s → %s' % (page,href))
```

#### A.4.4 段落计数与结构提示

[`_api_navigation.py`](../skills/tech-doc-translator/scripts/_api_navigation.py) 第 128–136 行，只数顶层段落：

```python
def _markdown_paragraphs(text):
    from _source_reconcile import _TABLE_CAPTION_LINE_RE
    lines = text.splitlines()
    prose = '\n'.join('' if ANCHOR.fullmatch(line) else line for line in lines)
    tokens = _INLINE.parse(prose)
    return [(token.map[0]+1, tokens[index+1].content)
            for index, token in enumerate(tokens)
            if token.type == 'paragraph_open' and token.level == 0
            and not _TABLE_CAPTION_LINE_RE.match(lines[token.map[0]])]
```

[`parse_api_html.py`](../skills/tech-doc-translator/scripts/parse_api_html.py) 第 188–189 行，引用块前单独输出一行结构提示，这一行本身是顶层段落：

```python
        elif name == 'blockquote' and _has_block_content(child):
            out.append('\n[BLOCKQUOTE]')
```

[`translation_conventions.md`](../skills/tech-doc-translator/references/translation_conventions.md) 第 12 行节选：

> 翻译将 `[BLOCKQUOTE]`、`[DETAILS]`、`[FOOTNOTE-LIST]` 等源结构提示转为可读引用 / 折叠说明 / 脚注，不能只删提示而丢其正文、父属或面板关系。

[`verify_reference_translation.py`](../skills/tech-doc-translator/scripts/verify_reference_translation.py) 第 75–79 行，reference 家族要求成品消除这些标记：

```python
# 必须由主 Agent 在最终译文中消除的解析占位标记
_RESIDUAL_MARKERS = [
    '[TABLE]', '[DEF-LIST]', '[FOOTNOTE-LIST]', '[IMG:',
    '[FIGURE]', '[FIGCAP]', '[BLOCKQUOTE]', 'ADMONITION',
]
```

#### A.4.5 链接检查口径

[`verify_translation.py`](../skills/tech-doc-translator/scripts/verify_translation.py) 第 313–316 行，片段核验同样走这里，只查缺失：

```python
        missing_links = Counter(link_targets(src)) - Counter(link_targets(doc))
        if missing_links:
            fail += 1
            lines.append('链接目标缺失: %s FAIL' % dict(missing_links))
```

[`verify_api_translation.py`](../skills/tech-doc-translator/scripts/verify_api_translation.py) 第 167 行，API 核验比较完整顺序：

```python
            if links(src_text)!=links(trans_text):fails.append('页 %s 原链接目标或出现顺序改变' % page_rel)
```

#### A.4.6 合章的退出方式

[`merge_api.py`](../skills/tech-doc-translator/scripts/merge_api.py) 第 271–274 行与第 296–297 行，逐页转换，任一页出错即退出：

```python
        try:
            if navigation is not None:
                from _api_navigation import transform_page
                body = transform_page(body, p, navigation, out_path)
```

```python
        except (OSError, ValueError) as exc:
            sys.exit(str(exc))
```

[`_api_navigation.py`](../skills/tech-doc-translator/scripts/_api_navigation.py) 第 444–446 行与第 452–453 行，一页之内三类检查依次抛错：

```python
    diffs=anchor_diffs(facts['raw'],text,section_id=facts['section_id'],source=facts['source'])
    if diffs:raise ValueError('翻译页锚点无来源证明: '+'；'.join(diffs))
    if links(text)!=links(facts['source']):raise ValueError('翻译页改变原链接目标: '+page)
```

```python
    table_problems=compare_translation_tables(before,restored,exact=True,header_cells=facts.get('header_cells',()))
    if table_problems:raise ValueError('导航转换损伤表格: '+page+'；'+'；'.join(table_problems))
```

错绑信息只含锚点名，见同文件第 222 行：`diffs.append('锚点目标错绑: '+name);continue`。

#### A.4.7 脚注编号

[`_html_fidelity.py`](../skills/tech-doc-translator/scripts/_html_fidelity.py) 第 862–865 行，渲染端只取数字：

```python
        for ref in copied.find_all(class_='footnote-reference'):
            number = re.sub(r'\D', '', ref.get_text(strip=True))
            ref.replace_with(
                '[^%s]' % number if number else self._unknown_footnote)
```

共享安装 `scripts/_source_reconcile.py` 第 939–941 行，是就地修改，仓库里没有：

```python
        for anchor in list(el.find_all(class_='footnote-reference')):
            anchor.replace_with(NavigableString(
                '[%s]' % anchor.get_text(strip=True)))
```

PG 的脚注引用是 `<a class="footnote-reference brackets" …><span class="fn-bracket">[</span>1<span class="fn-bracket">]</span></a>`，`get_text` 取到 `[1]`，再套一层成 `[[1]]`；BPG 的是 `<a class="footnote-reference brackets" …>1</a>`，取到 `1`，结果正确。

### A.5 计划期的站内链接扫描（R9、R10 的依据）

2026-11-14 编写执行计划时，在工作区外副本上套用 R1–R8 的改动，逐个检查 PG 13.5 全部 53 个 API 页解析稿里的站内链接，按合章的 `target_for` 规则归类：

| 类别 | 处数 | 去向 |
| --- | --- | --- |
| 目标是已登记的来源对象 | 1,087 | 合章正常转换 |
| 目标页快照里没有这个 id | 1 | extended-gpu-memory 的 `#virtual-memory-management`，R4 |
| 快照里有这个 id，但它不是来源对象 | 9 | 下表，R9、R10 |

| 页 | 链接 | 原 DOM 里的目标 |
| --- | --- | --- |
| async-copies | `Figure 51`、`Figure 52`、`Figure 53` → `#figure-swizzle-example1`、`#figure-swizzle-example2`、`#figure-swizzle-overview` | figure 开头的空 span 别名 |
| compute-fabric-transport、compute-capabilities | 脚注定义里各 3 个回链 → `#id2`、`#id3`、`#id4` | 正文里的行内脚注引用 |

async-copies 的写法（PG `source-13.5/04-special-topics/async-copies.html`，节选）：

```html
<figure class="align-center" id="id2">
<span id="figure-swizzle-example1"></span><a class="reference internal image-reference" href="../_images/swizzle-example1.png"><img alt="The shared memory data layout without swizzle" src="../_images/swizzle-example1.png" style="width: 700px;"/>
</a>
```

compute-capabilities 的写法（`source-13.5/05-appendices/compute-capabilities.html`）。正文表格里的引用是 `10.7 <a class="footnote-reference brackets" href="#family2" id="id2" role="doc-noteref">[1]</a>`，脚注定义：

```html
<aside class="footnote brackets" id="family2" role="doc-footnote">
<span class="label"><span class="fn-bracket">[</span>1<span class="fn-bracket">]</span></span>
<span class="backrefs">(<a href="#id2" role="doc-backlink">1</a>,<a href="#id3" role="doc-backlink">2</a>,<a href="#id4" role="doc-backlink">3</a>)</span>
<p>Some families only contain a single member when they are created. They may be expanded in the future to include more devices.</p>
</aside>
```

现在的解析稿（`compute-capabilities.md` 第 144 行）：`  [[1]] ([1](#id2), [2](#id3), [3](#id4)) Some families only contain a single member …`。

两种写法在同期各项目原站快照里的分布：

| 源 | 页数 | 块开头的空 span 别名（section / figure） | 被链接指向的 figure 别名 | 多回链脚注 |
| --- | --- | --- | --- | --- |
| PG 13.5 | 54 | 697 / 3 | 3，都在 async-copies | 2 条，HTML5 写法（`role="doc-backlink"`） |
| PG 13.4 | 52 | 677 / 3 | 3，都在 async-copies | 1 条，HTML5 写法 |
| BPG 13.5 | 1 | 111 / 0 | 0 | 1 条，dl 写法（`.fn-backref`） |
| cuBLAS 13.5 | 2 | 48 / 0 | 0 | 每页 3 条，dl 写法 |
| cuSPARSE 13.5 | 1 | 237 / 0 | 0 | 0 |

dl 写法里，只被引用一次的回链也写成链接，如 BPG 解析稿的 `**[3](#id58)**`。

同一副本上的逐章实测：第 1、2、3、6 章不加项目补丁合章并通过 API 核验；第 4 章因 async-copies、compute-fabric-transport，第 5 章因 compute-capabilities 失败。unified-memory、extended-gpu-memory 按约定准备译文后，在只含这两页的临时章里合章、核验通过。PG 现有译文删掉了这 9 处链接，所以这次的报错是“翻译页改变原链接目标”。按约定保留这些链接时，报错是“来源目标缺失或无法定位”。

PG 项目补丁 `scripts/tdt_v15_patches.py` 的 `BROKEN_FRAGMENT_ALLOWLIST` 正好列着这 9 处，以及 unified-memory 的两个引文锚点（R3）和 extended-gpu-memory 的坏链接（R4）。
