# PDF 源工作流（文字版/扫描版判定、裁决清单与独立对账）

文字版 PDF（学术论文等）作为翻译源时的确定性准备与校验入口。普通 HTML
四类家族的路由与行为不在本文范围，不因本文改变。

## 工作流

勘察 → 主 Agent 对照原页裁决 → 物化 → 独立对账，四步缺一不可：

1. **勘察**（`scripts/prepare_pdf_source.py inspect <pdf> --pages <范围> --output <目录>`）：
   记录源身份（realpath、sha256、字节数、页数、逐页尺寸与旋转、坐标口径）
   与环境探测（解释器、PyMuPDF 版本、实际 API 兼容性；依赖缺失清晰报错，
   绝不自动安装）；逐页统计文本层覆盖、嵌入位图、矢量绘图、批注与链接
   （文件名/元数据声明不作事实依据）；给出正文类型判定与证据；逐页落盘
   保版面与通读两种文本快照；输出标题、图题、表格页、脚注候选及位图素材
   （D3）、文本层公式（D4）待处理项。首次运行生成 `adjudication_checklist.json`
   草稿；再次勘察保留既有裁决，只刷新身份、环境与候选。
   `figure_regions` 补充绘图/位图空间组、原文字行、题注备选、来源/范围、
   对象定位、实际行高参数及归属冲突；候选矩形为未旋转页面 pt，
   `display_rect` 为经 `rotation_matrix` 转换的渲染位置。仅相交的邻接文字
   保留原值和扩大边界备选，未可靠关联图区的图题保留 `rect: null` 与定位
   缺口。所有条目仍待原页裁决，不写 blocks、resolved 或人工顺序；
   `figure_regions_empty` 只表示本次未发现，不证明原页无图。
   `table_cells` 保存 PyMuPDF 线段/文字策略的原生二维格位、空文本、
   无独立边界格、多行表头与完整原文字行；与对象组相交时保留图/表归属
   冲突。`table_checks` 记录各策略的实际参数、版本、局部区域依据及 API
   检查缺口；未发现不证明无表。文字策略可能拆词或截断表头，保留备选
   并逐格回原页确认，不自动生成 Markdown 表格或选择正确策略。
   `reading_orders` 呈现原块、栏区、提取/建议序、具体重叠和跨栏图组，
   两快照区间按页标题为第1行的页内行号定位。阈值沿用原通读辅助，
   不写人工 reading_order；原页空候选或旋转/交织歧义均须另行回页裁决。
   `character_defects` 保留原码位、字形、上下文与font。无可靠映射时建议
   为null，数学字符和连字命中不表示错误；内嵌URI只证明目标地址，
   展示截断/换行需回页确认。候选不修改源、译文、缺陷裁决或golden。
2. **裁决**：候选不是权威。主 Agent 对照原页（可把页面渲染成 PNG 实际
   查看）逐项接受、修正或补充候选，解释排除项（页眉页脚、装饰为何不进入
   正文），裁定双栏/跨栏阅读顺序并记录依据；未解决项写入 pending，待定
   决策不取默认。候选为空的类别保持显式空标记，补充的候选须有页码位置
   与裁决依据。
3. **物化**（`prepare_pdf_source.py materialize <pdf> --checklist <清单.json> --output <源Markdown>`）：
   按清单 blocks 裁决顺序组织源 Markdown；正文/表格区域按页/矩形从 PDF
   重新提取（每块可回页）；已固化的 `code_region` 块由 golden 生成源围栏
   （语言信息取块的 `lang`，缺省裸围栏；弯引号等内容性字符原样保留）；
   未固化代码区域与图形区域、位图素材、公式等未闭合素材写入显式
   `[PENDING-*]` 标记（含 page 与 rect），不静默删除。
   正文类型为 scanned/undetermined 的源拒绝物化；mixed 源在需 OCR 区域
   未获用户明确处置前拒绝物化；本链路不自动执行 OCR、不自动提取位图、
   不自动重建公式；人工确认数学按下节合同物化，未知公式仍 pending，
   缺失不得按全文完成交付。
4. **独立对账**（`scripts/verify_pdf_source.py <pdf> --checklist <清单.json> --source-md <源Markdown>`）：
   独立于物化操作重新打开 PDF，核对源身份与范围，按清单逐块重读页面
   区域，与源 Markdown 对应行区间（`<源Markdown>.blocks.json` 仅作定位）
   对账：标题按裁决层级/原题/顺序，正文与表格区域按词归一逐词相等，
   代码围栏与 golden 按块逐字节一致（差异定位到行/列），
   `[PENDING-*]` 标记必须显式存在；源 Markdown 每个非空行都必须落在某个
   块区间内。未解释的缺失、多余或错位（含阅读顺序换块）FAIL 并定位
   页/区域与行号，阻断分派。源对账通过后才进入既有翻译、校验与交付流程。

快照、清单、golden 与源 Markdown 持久化到翻译项目 `source/`；过程报告
与页面检查图放工作区外临时位置。这些对照依据（含块映射）是源/译核验
与工作区恢复的保留输入，收尾清理按 `<SKILL目录>/references/cleanup.md`
的保护合同处理，不作为可重建过程产物删除。译文侧代码回填沿用既有
`splice_fences.py` 程序化回填（不重造）；图片来源身份绑定见
"图形裁剪与来源身份绑定"一节。

## 人工确认数学（confirmed-tex-v1）

在同一 version=1 清单中显式登记 `formula_contract: "confirmed-tex-v1"`。
当前支持 paragraph / formula、heading、figure_caption / table_caption、algorithm
和 list_item 的有序 `content`，table_region 的逐格 `cells`，以及脚注定义及子块。
未确认的形态保留待处理。候选提供原字形、原块线索和歧义，主 Agent 实际查看原页后
逐次决定数学所属、表达式、类型与可见式号；机器未命中可按同一合同补登记。
代码及图内数学继续消费 golden / 图片，货币和普通编号按原页排除。

- 每个内容项为 `type: "text"`、`"math"`、`"code"`、`"link"` 或 `"footnote_ref"`，均有 `origin`：`page`、未旋转
  `rect`、原值 `text`、`extraction: {pymupdf: <实际版本>, view: "rawdict"}`
  及有序 `fragments`。片段的 block / line / span 为原生零基序号，start / end
  为字符半开区间，text 保留该片段原值；跨原行在 origin.text 中保留换行。
- 数学项另有独立 `id`、`owner: {block: <块ID>, role: <块类型>}`、零基 `slot`、
  `kind: "inline"|"block"`、逐字 `tex`，以及显式空或含 `text` / `origin` 的
  `label`。TeX 不含 Markdown 定界或式号包装；同表达式、同号分别登记，
  不重复使用原字形。数学和标签原区域属于当前宿主，不能把邻栏同号移来。
  原页公式组的成员各自登记，可选非空字符串 `group` 指明同一必要关系；
  保留每个成员的 ID、原片段、类型和独立式号，不按相同内容或组父范围合并。
- `conversion: {source: <原字形完整原值>, target: <确认TeX>, basis: <具体原页依据>}`
  说明这次表示转换；没有全局 ASCII / glyph 替换。`confirmation` 记录实际回源
  basis、当前 source_sha256 / scope 及 fact_sha256（该数学项移除 confirmation
  后的排序键、紧凑 JSON、UTF-8、ensure_ascii=false 的 SHA-256）。摘要只绑定
  已作出的人工判断。清单 `formula_review` 记录同一 source_sha256 / scope 和
  本范围实际全量数学复核 basis；局部试点另明确 selection，不冒充全页或全文。

标题须保留 `level` 和原英文标题，中文只能按既有标题合同附加。题注保留可见图/
表号；范围内需一起核对的资源用 `figure` / `table` 指向块ID，实际题注与资源的
相对所属进入源译、包和交付。算法父块采用 `type: "algorithm"`；直属说明、
条目、表格及 golden 代码块用 `algorithm` 指向该父块，须同页、区域包含且按原序
连续，代码不转写为正文数学。原列表标记直接保留；原段落明确转成说明条目时，
须有 `list_marker` 与 `list_conversion: {source_role: "paragraph", target_role:
"list_item", marker: <同一标记>, basis: <具体转换依据>}`。

行内 code 的原字节保持，跨行代码继续走 golden；link 另有 `target`，须由原页
原生URI覆盖标签字形，中文可翻译标签。普通阅读、代码叶子、链接目标与数学分别
检查，不能用普通文字空白归一吞掉代码空白或字面实体。

表格每个原格保存 `id`、一基 `row` / `column`、`rowspan` / `colspan`、布尔
`header`、未旋转 `rect` 和有序 `content`；空格仍有格记录及空内容。
`table_conversion` 保存具体原页 `basis`、目标 `rows` / `columns` 及完整
`cells: [{source: <源格ID>, row: <目标行>, column: <目标列>}]`。数学 `owner`
另含 `cell: <源格ID>`，slot 在该格内计数。原格网及目标格网须完整无重叠；
明确跨度展开可重复普通源格，含数学的源格只能映射一次。未知或缺失转换保持
pending；不以展平文本相等证明结构。输出实际GFM表格，仅数学跨度采用既有
可逆管道/实体/换行编码；独立端先读实际表格格位，再读取文字、叶子及数学。

脚注定义采用 `type: "footnote_def"`，保存 `footnote_label` 和原可见标签
的 `footnote_origin`；直属首段写入 `content`，没有直属文字时保留空 `content`，
首个代码、列表或表格子块仍用其原角色。正文引用项采用 `footnote_ref`，其 `label` 指向当前定义，
`origin` 绑定原页可见引用标记。定义续段、列表、表格和代码用 `footnote` 指向
定义块ID，按原序连续、同页且区域包含。代码仍从原提取 golden 程序化回填。
写出标准脚注后，独立端由实际插件确认定义边界，只撤销实际语法包装及四列
续行缩进（包括等价TAB），保留数学内部空白、代码字节和原字符定位。数学内
的 `[^b]` 不算实际引用；引用、完整定义和子块作为必要依赖保持，切断范围拒绝。

物化保留原值并写出确认 TeX；展示式的可见式号使用独立末尾
`\tag*{\text{…}}` 文本包装。源头声明 pdf_formula_contract 及相对清单的
JSON 字符串 pdf_checklist。源与实际派生映射先经独立原 PDF 核验，再同组发布；
失败恢复旧成员或撤销新成员。源块/数学映射仅定位实际字符范围，不能生成核验预期。
已有未关联源块映射的人工文件，以及原 PDF、清单、快照、golden、图片均受保护。
行内原号以相邻独立文本保留，字面字符按普通文本转义；同一出现映射的
label_range 记录实际追加的号范围，独立端从该数学结束处读取，不按首次同号搜索。

多行/矩阵/分式采用完整确认 TeX，首尾空白、内部空行和 LF / CRLF 逐字保持。
当前确认事实提供限定 SourceMathContext；普通 Markdown 的默认美元边界保持。
数学先保护后读取实际 Markdown 块，解析占位不改变原文或实际字符区间。
拆包保留完整表达式和必要公式组，较小 chars 目标允许整组超限；片段切断
数学宿主/前后正文或少组成员拒绝。独立端逐成员读取实际内容/类型/编号及
组内相对块间隔，译文插入无关正文使组关系失效。局部资格只投影相对组关系，
不绑定全篇组 ID、偏移或清单摘要。

确认数学拆包显式传 `--project-context <项目上下文.json>`，沿用
[项目上下文与逐包复核](workflow_helpers.md)。source_record 仅引用当前 pdf-source
来源；全源先独立准入，再按包头实际字符区间核验。元数据留在包头，不生成可翻译
正文包。任务书的核验命令也携带该上下文，实际源包不得自改范围或清单引用。
缺项或冲突声明拒绝；旧清单未声明新合同且无新内容事实时继续使用既有人工路径。
源/译共同漏式、改字或错型，重算映射和产物摘要均不授予完成资格。

## 当前资格与实际 PDF 消费

再勘察沿用原清单、实际源包范围及既有恢复流程。局部资格绑定该包的有序内容、
数学/叶子角色、公式组、原格转换和脚注依赖；全局ID或绝对偏移不作局部内容依据。
仅别包改变或全篇重编号时，实际未变包可复用；相关来源/表示/依赖/口径改变须
重做回源及语义复核。刷新候选、重签摘要或删除stale不能追认旧PASS。

请求导出时，现行translation record先按当前源/译/检查口径实际复跑就绪。
导出与独立核验从该记录重新打开原PDF和清单，按实际输入覆盖核对全源后，
逐章消费完整确认序列；无数学章显式空序列，缺章、重复覆盖和未消费公式拒绝。
真实表格及脚注块事实贯通渲染；定义按首次引用序移到章末，数学内部空白、
TeX、原格位和golden字节保持。KaTeX不支持的确认表达式明确失败并保留旧成品。

显式获准的额外译注数学沿用`--approved-extra-math <表达式>`逐次选项：
正式PDF源/译核验仅在具体`【译注：…】`出现中消费对应次数，不扣除来源同式。
就绪记录的实际检查参数进入既有身份及导出投影；成品按现行译注视图排除该片段，
独立端重核当前授权并对账实际译注清单。未获准额外出现及来源遗漏仍拒绝。

真实成品由独立PDF读取检查实际绘字，主Agent仍须逐页逐式对照原页目检符号、
类型、式号和所属。字体/绘字存在不能证明局部运算符、矩阵行或分式完整；
机器通过而视觉未闭合时保持待复核。仅翻译任务继续不强制生成永久PDF。

## 代码 golden（文本型代码清单）

已裁决为代码清单的 `code_region` 块按页/矩形从文本层程序化提取
（`prepare_pdf_source.py extract-code <pdf> --checklist <清单.json> --output <golden目录>`）：

- **提取通道**：char 级重建，规避按行 clip 提取丢行首缩进的已知陷阱
  （R3）。行首缩进由首字符 x 偏移（相对区域最左列）按等宽字宽
  （区域内相邻字符步进的中位数）换算为空格；同基线的多个文本 run
  （行内右侧注释等）合并为一行并按字宽补足间隔（重叠或紧邻时隔一个
  空格，间隔宽度属排版差异）；文本层不产出空行，按行距（相邻行 y0 差
  中位数）重建区域内空行；区域外内容（页眉、分页符、邻栏）由裁剪矩形
  排除。逐字节保留字符与行序，不做任何行尾空白剥除。
- **对应关系**：块与 golden 的对应在清单中显式记录（块的 `golden`
  文件名，相对清单目录解析），不凭图号或出现顺序猜测；一个代码块
  拆多个 golden（如通栏图的 (a)/(b) 两段）须在清单中分块裁决。
- **固化**：golden 以 UTF-8 写入项目 `source/`，提取行数、字宽与取舍
  口径（`golden_extraction`）及 sha256（`golden_sha256`）回写清单；
  固化前主 Agent 必须把页面区域渲染成 PNG 实际查看，逐块核对内容、
  行序与缩进，并把回源确认结论记入该块的 `adjudication.basis`——
  机器提取与比较不能代替这一步（非目标：不自动证明文本层字符绝对
  正确）。
- **核验**：`verify_pdf_source.py` 从源 Markdown 取围栏正文原始字节
  （共享 `scan_code_fences` 切片，不经任何 rstrip/归一化通道），与
  golden 按块逐字节一致；改字符、弯引号、缩进、换行符（LF/CRLF）、
  换块或添加一处行尾空格均 FAIL 并定位块与差异行列（golden 与
  Markdown 一律按保留行尾原始字节的方式读取）。golden 摘要同时与
  清单固化记录核对，基准被改动须重新回源确认。
- **完成门禁（R3/A10/D3）**：候选对账只要求 `[PENDING-*]` 显式存在；
  交付完成路径（`verify_delivery`）在此基础上阻断未闭合素材——清单
  pending 中 bitmap/bitmap_region/formula 无 `resolved` 及依据
  （OCR 授权处置不是素材补全事实，对素材类无效），ocr_region 既无
  `resolved` 及依据也无 `user-resolved` 授权处置记录，或源 Markdown、
  该源链覆盖的交付译文输入仍含 `[PENDING-*]` 标记，拒绝发布完成证据
  并定位。显式为空或已回源解决的项（`resolved` 为布尔 true 且附非空
  `resolution_basis` 处理依据，宽松真值如字符串不算；pending 项的
  `basis` 是勘察机器写入的候选线索，不充当解决依据）、已按授权处置
  的 OCR 区域不阻断。
- **译文回填**：译文草稿用独占行的 `⟦CODE⟧` 占位，由既有
  `splice_fences.py` 按文档顺序从源文程序化回填（禁止手工转写）；
  回填后译文围栏与源围栏逐字节一致，再由译文校验器按既有规则核对。

## 图形裁剪与来源身份绑定（矢量图素材）

已裁决为图形型素材的 `figure_region` 块按记录的页面坐标与渲染口径
裁为 PNG（`prepare_pdf_source.py extract-figures <pdf> --checklist
<清单.json> --output <图片目录>`）：

- **裁剪与渲染口径**：按块 `rect` 与 `dpi`（缺省 200，写入记录）渲染；
  块 ↔ 图片对应在清单显式记录（块的 `image` 相对路径，不凭图号/顺序
  猜测）。图片进入项目既有资源目录（如 `images/pdf_source/`），不回
  溯覆盖同名旧产物。
- **归属覆盖核对**：提取时枚举区域内对象作为固定依据——矢量绘图按
  面积占比 ≥50% 落入区域归本图（零面积的轴线/刻度线按相交归属），
  文字行按行框中心落入区域归本图；同页其他图、表格边框、页眉装饰
  在区域外有独立归属，不计入本图，不因邻接误计遗漏。大面积绘图聚类
  只作候选，不作为强制算法。
- **来源身份**：每次图片出现绑定"PDF 身份（sha256）+ 页面/区域 +
  提取口径（dpi/rect）+ 已确认资源摘要（`image_sha256`）"，与对象
  普查（`figure_extraction.census`）一并回写清单块；核验侧从清单固定
  依据读取期望身份，不从待验文件重算。`verify_pdf_source.py` 对
  figure_region 块核对：块区间内恰一张图片引用（漏图/多余定位）、
  PNG 魔数有效、实际字节摘要与固化身份一致（同名换图 FAIL）、按当前
  PDF 区域重建的普查与固化普查一致（删目标绘图或文字标签 FAIL 并
  定位差异）。
- **显示尺寸**：块的 `figure_extraction.display_width_px` 按区域物理
  宽度换算（pt→CSS px，1 px = 0.75 pt，沿用 `references/
  images_display.md` 合同）；渲染 dpi 只影响栅格分辨率，不充当显示
  宽度；区域宽度不可确定时保留 `unresolved-size` 原因，不冒充已确定。
  交付级映射按"交付证据衔接"一节的两级映射合同接入。
- **目检**：裁剪后必须实际查看原页与裁剪 PNG，逐图核对目标绘图、
  图中文字标签与图例完整、图题对应，结论记入块 `adjudication.basis`；
  对象覆盖核对不能代替真实目检。

## 译文机器硬检查与论文交付口径

源对账通过后，`verify_pdf_source.py --translation <译文.md>` 追加
源 Markdown → 译文的机器硬检查（全部复用共享比较器，期望身份取自
清单固定依据，不从待验译文重算）：

- **标题**：权威清单裁决 (层级, 官方原题) 与译文按出现顺序对照
  （中文后缀按边界规则允许；官方原题裁决：PDF 小体大写字体的文本层
  全大写为排版样式，以官方题名式为准）；删标题、改层级、去英文原题
  FAIL 并定位。
- **代码**：译文围栏与源文按出现顺序逐块对照，正文逐字节一致
  （共享 `compare_code_fences`）。
- **图片**：译文每次图片出现的顺序与清单固化来源身份逐项核对，
  引用须在交付目录内、文件存在、魔数/类型有效；同名换图、乱序、漏图
  FAIL 并定位（`check_image_file` 共享判型）。
- **脚注**：清单登记权威标签（块 `footnote_label`）的引用与定义
  必须在译文出现——整对删除也检出，不以译文内部配对代替源覆盖。
- **强 token（D2）**：脚本从源文本生成候选（标识符、含单位数值），
  主 Agent 对照源文逐项裁决后写入 `conventions.strong_tokens`；检查
  按出现语义要求逐字命中（缺失即 FAIL），未配置时明示"未检查"
  （WARN，不构成数字复核完成的证据）。
- **文本层缺陷（R5）**：`conventions.defects` 记录缺陷（原提取值、
  更高保真证据如 PDF 内嵌链接目标、裁决值、译注要求）；只读源不静默
  改写，译文采用裁决值并加译注，硬检查核对裁决值落实。
- **论文口径（R6/D1）**：`conventions.references` 声明参考文献默认
  保留英文（可逐项目覆盖）；附录表头与分类标签中英对应、数值逐字
  保留，回源核对结论记入 `conventions.appendix_review`。
- **结论分层**：输出区分【产物】问题与【口径】问题；机器 PASS 只
  表示硬不变量通过，报告明确"人工语义复核未登记"，语义复核由主
  Agent 对照权威源独立登记（机器 PASS 不构成语义复核完成）。

项目核验脚本（如 torch.fx `scripts/verify_pdf_project.py`）是通用
入口的薄包装：固定项目路径（清单、源 Markdown、golden、图片身份、
强 token 全是清单数据），调用同一公共检查核心与真实参数解析；不复用
旧项目弱比较脚本（剥行尾空白、硬编码清单、计数语义不同）的规则。

## 交付证据衔接（verify_delivery 的 pdf-source 家族）

翻译交付走既有 `verify_delivery.py` 完成检查（目录允许清单、身份、
核验复跑、持久证据），交付记录 `sources[]` 增加 `family: "pdf-source"`
条目（记录版本与模式语义不变）：

```json
{"family": "pdf-source", "source_version": "<版本定位串>",
 "pdf": "<只读 PDF（相对交付根）>", "checklist": "<裁决清单>",
 "source_markdown": "<源 Markdown>", "block_map": "<缺省 <源Markdown>.blocks.json>",
 "layout_snapshot": "<保版面快照>", "reading_snapshot": "<通读快照>",
 "covers": ["<该源链覆盖的交付输入>"]}
```

- **消费点**：源链预检校验字段与文件、核对清单绑定 PDF 摘要（版本
  错配拒绝）、golden/图片实际摘要与清单固化身份一致（同路径换基准/
  同名换图拒绝）；独立源对账在进程内调用 `verify_pdf_source` 公共核心
  （不读取或补签预存对账结果）；图片事实按清单声明区域枚举已确认资源
  （PDF 身份 + 页面/区域 + 提取口径 + 资源摘要），不从待验产物重算期望
  身份；缺摘要不构成证明（两侧同为 None 不判相等），发布前完整性检查
  拒绝。
- **统一身份**：PDF 依据（PDF/清单/源 Markdown/双快照/块映射/golden/
  图片摘要与范围）进入同一 `compute_delivery_identity`；源对账/语义
  复核与视觉复核继续从其投影绑定（§1.2 重审结论：只向统一身份构造
  增加事实，不另建状态库或第二套摘要）。
- **两级映射**：`materialize` 写出 `<源Markdown>.images_display.json`
  解析期映射（逐次出现：来源页/区域 + dpi、资源摘要、确定显示宽度或
  `unresolved-size` 原因；代码清单转围栏不生成伪图片条目）；交付级
  映射固定 `export/images_display.json`，条目相对映射文件解析（注意：
  条目 `markdown`/`image` 都以映射文件所在目录为基点，不是交付根；
  路径写错不会报错，只会按自然尺寸静默回退——导出报告的
  `image_coverage.restored` 必须等于出现总数），出现数按输入覆盖核对。
- **核验记录**：`{"tool": "verify_pdf_source", "args": [pdf,
  --checklist, …, --source-md, …, --translation, <译文>]}`——受约束的
  已知入口（真实 parse_args + 公共检查核心），项目薄包装（如 torch.fx
  `scripts/verify_pdf_project.py`）从该入口复验；未知命令不能进入交付
  检查。
- **失效口径**：源 PDF、清单、区域（rect）、golden、图片资源或核验
  口径任一变化，统一身份随之变化，旧复核绑定不符即拒绝；旧 PDF 项目
  无该来源链时不自动补签通过记录，独立 Markdown 导出不强制补
  PDF 来源链。

## 坐标口径

全部位置为 PyMuPDF 页面坐标：单位 pt（1/72 英寸）、原点页面左上角、
x 向右、y 向下；矩形记 `[x0, y0, x1, y1]`。`rotation != 0` 的页面，
文本提取坐标遵循 PyMuPDF 未旋转页面空间，裁决裁剪前按页旋转换算；
渲染 PNG（如 `page.get_pixmap`）使用旋转后的页面朝向。对象序号（块 id、
位图 xref）只在同一 PDF 身份（sha256）下有效；源或范围变化后旧裁决
须重新核对。

## 正文类型判定口径

- `text`：范围内每页正文文本层可靠（字符量与可读占比双门槛达标；
  含嵌入位图仍为文字版）；`scanned`：正文需 OCR（无可用文本层、
  有版面对象），维持既有口径，仅用户明确要求且使用宿主 OCR 工具；
  `mixed`：可靠文本页与文本层不可用页并存（页级）。类型判定只依
  据文本层证据；页内嵌入位图区域一律记录为 pending 待裁决项，不
  参与类型判定（裁决为需 OCR 正文后的 mixed 迁移见下）。
- 位图区域待裁决项（kind `bitmap_region`）：文字版页面上**全部**嵌入
  位图区域一律入列，枚举不做任何"消失性"过滤（无面积下限、不因与
  文本块相交而跳过；整页级 ocr_region 已覆盖的页面不重复生成）。
  面积占比、是否与文本块相交只作线索写入 basis：区域是插图素材
  还是需 OCR 正文由主 Agent 对照原页裁决并记录依据——裁决为素材记
  `resolved: true` 并入素材清单；裁决为需 OCR 正文转为 `ocr_region`
  并把 `classification.type` 裁决为 `mixed`（A10 口径），工具强制
  一致性：存在 `ocr_region` 项但类型仍为 text 时 materialize 与
  verify_pdf_source 拒绝；未裁决前完成门禁阻断。
- `undetermined`：文本为空、乱码（可读占比过低）或证据不足；保留
  未确定状态，不能宣称全文准备完成。

判定只依据对象级核查与文本层质量证据；嵌入位图数量不参与正文是否
需 OCR 的判定。

## 裁决清单 schema（version=1 单一 JSON）

清单是源转换的输入，不是执行状态库；权威资格来自针对当前 PDF 的
实际回源复核，不靠清单内布尔值。清单以 `adjudicated_against`（含
sha256 与 scope）记录既有裁决作出时绑定的源身份与范围（再次勘察时
继承；旧版清单回填为旧源身份/范围，全新清单不写该字段）。
`materialize` 与 `verify_pdf_source` 的拒绝
规则：存在 `stale` 字段，或 `adjudicated_against` 与当前清单
`source.sha256`/`scope` 不符且缺少覆盖该变化的有效 `revalidate`
记录（from 匹配旧绑定、to 匹配当前、basis 非空）——即使 `stale`
被人为删除也拒绝；无绑定记录（旧版清单）且无其他不一致证据时按
兼容口径放行。再次勘察继承 `stale` 与 `adjudicated_against`；重核
完成路径：逐项重核后写入 `revalidate`（from/to/basis 留痕）、把
`adjudicated_against` 更新为当前身份并移除 `stale`。pending 按稳定
区域身份 `(page, 规范化 rect)` 合并（kind 不参与键；无 rect 的项退回
`(kind, page)` 键）：同一物理区域已裁决的项（无论 kind，如已转为
`ocr_region`）抑制再次勘察对同一区域重新产生的候选，不作为新未裁决
项追加；rect 不同的位图出现是不同键，不误合并；旧项裁决状态保留、
新发现项追加、旧有键新勘察未再发现者保留（去留由重核裁决）。机器
`classify_pages` 的新判定只写入勘察报告与证据作候选，不回写清单：
`classification.adjudicated` 为真时再次勘察继承裁决类型值与依据（源/
范围变化时随 stale 冻结待重核）。六项内容与对应问题：

| 字段 | 回答的问题 |
| --- | --- |
| `source` / `environment` / `scope` | 哪份 PDF、哪些页/区域、何种文本与坐标口径、哪些工具版本产生本次依据（来源与环境） |
| `blocks[]` | 每个标题、正文区域、表格、图题、代码/图形区域、脚注来自何页何处，按何种顺序进入源 Markdown（页面块与结构） |
| `rejected[]` | 候选为何被排除（页眉页脚、装饰等），含排除理由（裁决与排除） |
| `pending[]` | 还有哪些未解决项：位图素材、文本层公式、需 OCR 区域及其处置状态（素材对应与未解决项） |
| `classification` / `reading_order` | 类型判定证据与跨栏/双栏顺序的裁决依据（转换与修正的输入） |
| `conventions` | 参考文献处理（D1 默认保留英文，可逐项目覆盖）、已裁决强 token（D2）等项目口径 |

`blocks[]` 条目：`id`、`order`（进入源 Markdown 的顺序）、`type`
（`heading` / `paragraph` / `figure_caption` / `table_region` /
`code_region` / `figure_region` / `bitmap` / `formula` / `ocr_region`）、
`page`、`rect`、`level`（标题）、`text`（裁决值；缺省由物化按区域提取）、
`adjudication`（`status` 与 `basis`）。`code_region` 另含 `golden`
（golden 文件相对路径，显式对应）与 `lang`（围栏语言，可缺省）；
`figure_region` 另含 `image`（图片相对路径，显式对应）与 `dpi`
（渲染口径，可缺省默认 200）；已固化 `code_region` 物化为 golden
内容的围栏，已裁剪 `figure_region` 物化为 `![标签](相对路径)` 图片
引用，未固化代码区域及其余未闭合素材块（`figure_region`（未裁剪）、
`bitmap`、`formula`、`ocr_region`）物化为
`[PENDING-<KIND> page=<p> rect=(...) …]` 显式标记。

## 依赖探测口径（D5）

PDF 源依赖独立声明于 `requirements-pdf-source.txt`（PyMuPDF），与普通
翻译依赖、PDF 导出依赖分离：普通 HTML 翻译不安装本文件。使用前由脚本
探测并记录解释器版本、PyMuPDF 版本与 API 兼容性；缺失时清晰报错退出，
绝不自动安装。环境事实写入勘察报告与清单，重跑对账时以清单记录核对。
