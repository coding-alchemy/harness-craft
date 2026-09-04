# Style Brief — 内容清单枢纽

- Goal and audience: 面向维护该 Skill 的开发者；在一页内看清入口、平台适配、统一数据边界、三条自适应处理路径、输出和清理边界。
- Output scenario and canvas: 桌面阅读与仓库文档引用；横向自适应画布 `1440 × 900`，确保源码名和分支条件可读。
- Core message in one sentence: 三个平台先收敛为一个 `ContentManifest`，再由同一管线按质量选择“字幕直达、下载 ASR、逐图 OCR”，最终统一输出 Markdown。
- Chosen visual concept/metaphor: 以 `ContentManifest` 为中央“交换枢纽”，左侧三平台汇入，右侧三条处理路径分流后再汇聚到 Markdown。
- Primary visual focus: 页面中央的大型 `ContentManifest` 圆形节点和贯穿全页的左入右出数据流。
- Poster-level visual move: 用一条有宽度、有分叉的主数据脊柱贯穿平台、统一边界和输出；标题、节点和说明都锚定这条数据流，不做常规分层卡片墙。
- Visual DNA: 温和浅灰背景、深蓝主骨架、紫色平台输入、绿/橙/紫三条处理分支；细网格和小型源码标签提供工程感，但不做仪表盘。
- Primary visual medium and candidates compared: ①传统上下分层图最利于逐层扫描，但中央数据契约不够突出且容易像技术报告；②以 `ContentManifest` 为中央枢纽的放射式关系图最能表达“平台差异先收敛、公共处理后分流”，选用；③按三平台分别画泳道会重复字幕、下载和输出逻辑，信息容量低。
- Reading order and composition: 左上标题 → 左侧调用与平台适配 → 中央统一清单 → 右侧三条处理路径 → 最右 Markdown；底部横带补充外部依赖与临时数据清理。
- Color scheme and roles: 深蓝 `#102A43` 为主数据流；亮蓝 `#2F80ED` 为统一清单；紫 `#9B51E0` 为平台适配；绿 `#27AE60` 为可靠字幕；橙 `#F2994A` 为下载与 ASR；靛紫 `#6C5CE7` 为 OCR；红 `#EB5757` 只用于安全与失败关闭。
- Fonts: 中文使用 MiSans，英文与源码标签使用 Liter；标题 34–40 px，主节点 18–22 px，说明 12–15 px。
- Image selection and treatment: 本图不使用照片；系统结构本身是证据，全部节点、连线、标签和图例保持为可编辑 PPTD 元素。
- Graphics and connector language: 实线带箭头表示主数据流；虚线表示按需支撑或外部依赖；粗线只用于主路径；节点附近直接标注真实源码文件。
- Information density, whitespace, and alignment: 中央枢纽留出最大面积，平台与处理器围绕其相邻排布；说明文字不低于 12 px，底部支撑带与主图之间保留明显呼吸区。
- Tropes to avoid: 均匀圆角卡片墙、三平台重复泳道、装饰性图标、与实现无关的服务层/数据库/事件总线。
- Reason for choosing: 枢纽式构图把最重要的架构决策变成缩略图也能识别的视觉中心，同时保留真实源码映射。
- Main degeneration risk: 可能退化为普通“中心圆 + 卫星框”；检查时必须确保左入右出的主数据脊柱、分支条件和底部生命周期边界共同参与整体构图。
