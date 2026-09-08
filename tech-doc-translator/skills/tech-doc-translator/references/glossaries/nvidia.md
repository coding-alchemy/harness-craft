# NVIDIA 术语库

| 元数据 | 内容 |
| --- | --- |
| 术语库标识 | nvidia |
| 来源范围 | 12 份已验收 NVIDIA 技术文档项目术语表 |
| 更新日期 | 2026-08-30 |

以下权威词条是无冲突候选或已获裁决的默认口径。源表中的 `译` 统一解释为“首现中英，后文中文”；明确要求首现译出、后文使用英文或缩写的词条统一为“首现中英，后文英文”。

裁决以 CUDA Programming Guide 已确立口径为默认，后续项目的特殊写法留在项目术语表中。其中 `kernel` 首现译为“核函数”、后文使用 `kernel`；`leading dimension` 默认译为“前导维度”，cuSPARSE 保留英文；`happens-before` 默认译为“先行”，Tile IR 保留英文；`peer access` 默认译为“点对点访问（P2P）”；`preprocessor directive` 默认译为“预处理指令”，PTX 语法语境使用“预处理伪指令”。整合报告中的其余分歧均以本表对应词条为已批准默认，其他写法明确不进入共享默认。源表仍标为“待定”的 `async / asynchronous` 与 `memcpy（API 名）` 也明确不进入共享默认。

| 英文原词 | 中文译法/保留形式 | 处理方式 | 语境/备注 | 来源 |
| --- | --- | --- | --- | --- |
| (language) binding | 绑定(binding) | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:267 [第 15–21 章(收官批次)新确立] |
| -gencode / -arch / -ccbin / -Xcompiler | -gencode / -arch / -ccbin / -Xcompiler | 英文 |  | cuda_blackwell_compatibility_guide/术语表.md:46 [保留不译(产品/工具名)] |
| 16B aligned | 16B(16 字节)对齐 | 英文 |  | cublas/术语表.md:257 [第 1 章与 3.1–3.2(G7)] |
| 32-byte segments | 32 字节段 | 首现中英，后文中文 |  | cuda_blackwell_tuning_guide/术语表.md:20 [沿用既有译法(本章高频)] |
| 64-bit Integer Interface | 64 位整数接口(基线译法)【裁决:02d"整型接口"已统一】 | 首现中英，后文中文 |  | cublas/术语表.md:183 [2.8 类 BLAS 扩展(G3)] |
| [DEPRECATED]/[EXPERIMENTAL](表标签) | [已弃用]/[实验性](枚举常量本身保留) | 首现中英，后文中文 |  | cublas/术语表.md:126 [2.1–2.5 总论与 Level-1(G4)] |
| ABI (application binary interface) | ABI(应用二进制接口) | 英文 |  | cuda_best_practices_guide/术语表.md:234 [第 15–21 章(收官批次)新确立] |
| ABI / calling convention | ABI(应用二进制接口)/ 调用约定 | 首现中英，后文中文 |  | ptx_isa/术语表.md:178 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| abstract machine | 抽象机 | 首现中英，后文中文 |  | cutile_python/术语表.md:91 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)]; tile_ir/术语表.md:66 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| accelerator | 加速器 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:89 [第 5–6 章(Parallelizing / Getting Started)新确立] |
| access counter | 访问计数器 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:293 [4.1 统一内存] |
| access policy window | 访问策略窗口 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:162 [第 10 章(Memory Optimizations)新确立] |
| access policy window / evict | 访问策略窗口 / 驱逐 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:383 [4.7 / 4.8 / 4.13 / 4.17 / 4.20 其他] |
| accumulator | 累加器 | 首现中英，后文中文 |  | cublas/术语表.md:195 [3.3 cuBLASLt 数据类型参考(G5)] |
| accumulator / low / high group | 累加器 / 低组 / 高组 | 首现中英，后文中文 |  | ptx_isa/术语表.md:108 [矩阵乘累加与 TensorCore(9.7.15–9.7.17)] |
| acquire / release / relaxed | 获取 / 释放 / 松弛(relaxed) | 首现中英，后文中文 |  | tile_ir/术语表.md:19 [承接既有项目(本表只列本书高频承接词)] |
| acquire / release semantics;release/acquire pattern | 获取 / 释放语义;释放模式 / 获取模式 | 首现中英，后文中文 |  | ptx_isa/术语表.md:40 [内存模型(第 8 章 + 9.7.14,承 PG 5.7/5.8 与 09 块)] |
| acquire-release | 获取-释放 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:247 [硬件模型与执行(3.2)] |
| active mask / active thread | 活跃掩码 / 活跃线程 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:235 [硬件模型与执行(3.2)] |
| active threads | 活动线程 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:56 [第 3 章(Heterogeneous Computing)新确立] |
| address space | 地址空间 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:135 [第 6、8 章] |
| address space predicate / generic address / cache operator | 地址空间判定 / 通用地址 / 缓存运算符 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:447 [5.3 / 5.4 语言支持与扩展(两节同词已合并)] |
| address window / window base / size | 地址窗口 / 窗口基址 / 窗口尺寸 | 首现中英，后文中文 |  | ptx_isa/术语表.md:81 [数据搬运与类型(第 5 章 + 9.7.9)] |
| addressing logic | 寻址逻辑 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:107 [第 7 章(Getting the Right Answer)新确立] |
| Advanced Controls File (ACF) | 高级控制文件(ACF) | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:80 [第 4 章(选项描述正文术语;选项名本身不译)] |
| advanced indexing | 高级索引 | 首现中英，后文中文 |  | cutile_python/术语表.md:63 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| Advanced Vector Extensions (AVX) | 高级矢量扩展(AVX) | 首现中英，后文中文 |  | cublas/术语表.md:260 [第 1 章与 3.1–3.2(G7)] |
| advisory warning / info | 建议性警告 / 建议性信息 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:109 [第 4 章(选项描述正文术语;选项名本身不译)] |
| ahead-of-time (AOT) compilation | 提前编译(AOT) | 首现中英，后文中文 |  | cutile_python/术语表.md:128 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| alias (v.) | 互为别名 | 首现中英，后文中文 |  | cutile_python/术语表.md:127 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| alias group | 别名组 | 首现中英，后文中文 |  | cutile_python/术语表.md:133 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| alignment criteria | 对齐条件 | 首现中英，后文中文 |  | cublas/术语表.md:154 [2.7 Level-3(G2)] |
| allocation handle / shareable handle | 分配句柄 / 可共享句柄 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:325 [4.3 / 4.16 内存管理] |
| allocation node / free node | 分配节点 / 释放节点 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:309 [4.2 CUDA Graphs] |
| allocation unit size / aggregated size | 分配单元大小 / 聚合总大小 | 首现中英，后文中文 |  | ptx_isa/术语表.md:190 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| alternate floating point / sub-byte operations / link-compatible / weak linkage | 替代浮点格式 / 子字节操作 / 可链接兼容架构 / 弱链接 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:452 [5.3 / 5.4 语言支持与扩展(两节同词已合并)] |
| alternate floating-point data format | 替代浮点数据格式 | 首现中英，后文中文 |  | ptx_isa/术语表.md:90 [数据搬运与类型(第 5 章 + 9.7.9)] |
| Amdahl's Law | 阿姆达尔定律 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:30 [本章新确立术语] |
| amortized | 摊销 | 首现中英，后文中文 |  | cublas/术语表.md:268 [第 4 章(G8)] |
| annotated function | 带标注(annotated)函数 | 首现中英，后文中文 |  | cutile_python/术语表.md:40 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| annotation | 标注 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:50 [第 1-3 章] |
| API | API | 英文 |  | cusparse/术语表.md:12 [术语表] |
| API generalization | API 泛化(API generalization) | 首现中英，后文中文 |  | cublas/术语表.md:181 [2.8 类 BLAS 扩展(G3)] |
| APOD (Assess, Parallelize, Optimize, Deploy) | 评估、并行化、优化、部署(APOD) | 首现中英，后文英文 |  | cuda_best_practices_guide/术语表.md:26 [本章新确立术语] |
| application binary | 应用程序二进制文件 | 首现中英，后文中文 |  | cuda_blackwell_compatibility_guide/术语表.md:30 [本章新确立(第 1 章翻译 Agent 上报,2026-08-29 中心合并)] |
| application note | 应用说明 | 首现中英，后文中文 |  | cuda_blackwell_compatibility_guide/术语表.md:29 [本章新确立(第 1 章翻译 Agent 上报,2026-08-29 中心合并)]; hopper_compatibility_guide/术语表.md:21 [沿用既有项目译法] |
| approximate (.approx) | 近似(修饰符保留) | 首现中英，后文中文 |  | ptx_isa/术语表.md:146 [浮点与数值(9.7.3/9.7.4/9.7.5 + 各处)] |
| architecture capabilities | 架构能力 | 首现中英，后文中文 |  | cublas/术语表.md:153 [2.7 Level-3(G2)] |
| architecture conditional features | 架构条件特性 | 首现中英，后文中文 |  | cuda_blackwell_compatibility_guide/术语表.md:33 [本章新确立(第 1 章翻译 Agent 上报,2026-08-29 中心合并)]; hopper_compatibility_guide/术语表.md:27 [本文档新确立] |
| architecture family / target string | 架构家族 / 目标字符串 | 首现中英，后文中文 |  | ptx_isa/术语表.md:186 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| architecture identification / list macro | 架构标识宏 / 架构列表宏 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:111 [第 4 章(选项描述正文术语;选项名本身不译)] |
| architecture-specific | 面向特定架构的 | 首现中英，后文中文 |  | cutile_python/术语表.md:54 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| architecture-specific / family-specific / baseline feature set / compiler target | 架构专属 / 家族专属 / 基线特性集 / 编译目标 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:422 [5.1 / 5.5 计算能力与浮点] |
| argument reduction | 参数归约 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:200 [第 11–13 章(Execution Config / Instruction / Control Flow)新确立] |
| Argument-Dependent Lookup (ADL) | 实参依赖查找(ADL) | 首现中英，后文英文 |  | cuda_programming_guide/术语表.md:434 [5.3 / 5.4 语言支持与扩展(两节同词已合并)] |
| arithmetic engine | 算术引擎 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:54 [第 3 章(Heterogeneous Computing)新确立] |
| arithmetic promotion | 算术提升(arithmetic promotion) | 首现中英，后文中文 |  | cutile_python/术语表.md:47 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| array / global array | 数组 / 全局数组 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:57 [Tile 编程(CUDA 13 新增)] |
| array of pointers | 指针数组 | 首现中英，后文中文 |  | cublas/术语表.md:142 [2.6 Level-2(G1)] |
| array rank | 数组秩 | 首现中英，后文中文 |  | cutile_python/术语表.md:177 [API 参考批次(箱1:Load/Store~Selection;箱2:Math~JAX FFI;2026-08-29)] |
| arrival / wait | 到达 / 等待 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:249 [硬件模型与执行(3.2)] |
| arrive-on / complete-tx / expect-tx | 到达(arrive-on)操作 / complete-tx 操作 / 期望事务(expect-tx)操作 | 首现中英，后文中文 |  | ptx_isa/术语表.md:56 [内存模型(第 8 章 + 9.7.14,承 PG 5.7/5.8 与 09 块)] |
| as-is | 原样 | 首现中英，后文中文 |  | cuda_blackwell_compatibility_guide/术语表.md:32 [本章新确立(第 1 章翻译 Agent 上报,2026-08-29 中心合并)] |
| assembly format | 汇编格式 | 首现中英，后文中文 |  | tile_ir/术语表.md:160 [第 8 章 8.9–8.12 + 第 12 章附录(Agent C,2026-08-29)] |
| assess / parallelize / optimize / deploy | 评估 / 并行化 / 优化 / 部署 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:27 [本章新确立术语] |
| associative | 可结合(结合律) | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:115 [第 7 章(Getting the Right Answer)新确立] |
| assumption | 假定 | 首现中英，后文中文 |  | cutile_python/术语表.md:129 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| async copy | 异步复制(async-copy) | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:171 [第 10 章(Memory Optimizations)新确立] |
| async proxy / generic proxy | 异步代理 / 通用代理 | 首现中英，后文中文 |  | ptx_isa/术语表.md:49 [内存模型(第 8 章 + 9.7.14,承 PG 5.7/5.8 与 09 块)] |
| async thread | 异步线程 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:242 [硬件模型与执行(3.2)] |
| asynchronous copy / async-group / bulk | 异步复制 / 异步组 / 批量 | 首现中英，后文中文 |  | ptx_isa/术语表.md:72 [数据搬运与类型(第 5 章 + 9.7.9)] |
| asynchronous transaction barrier | 异步事务屏障 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:254 [硬件模型与执行(3.2)] |
| atomic | 原子 | 首现中英，后文中文 |  | cublas/术语表.md:26 [基准承接(沿用 CUDA Programming Guide 既有译法)]; tile_ir/术语表.md:70 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| atomic function / atomics | 原子函数 / 原子操作 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:156 [原子与同步(2.3、2.5)] |
| atomic read-modify-write | 原子读-改-写 | 首现中英，后文中文 |  | cutile_python/术语表.md:148 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| atomicity / single-copy atomicity | 原子性 / 单副本原子性 | 首现中英，后文中文 |  | ptx_isa/术语表.md:45 [内存模型(第 8 章 + 9.7.14,承 PG 5.7/5.8 与 09 块)] |
| attribute | 属性 | 首现中英，后文中文 |  | tile_ir/术语表.md:60 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| augment / augmentation | 增强(augmentation) | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:86 [第 4 章(选项描述正文术语;选项名本身不译)] |
| automatic dynamic precision framework | 自动动态精度框架 | 首现中英，后文中文 |  | cublas/术语表.md:237 [第 1 章与 3.1–3.2(G7)] |
| automatic NUMA balancing / AutoNUMA / NUMA node | 自动 NUMA 平衡 / NUMA 节点 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:180 [第 10 章(Memory Optimizations)新确立] |
| automatic variable | 自动变量 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:172 [第 10 章(Memory Optimizations)新确立] |
| autotuning | 自动调参 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:192 [Tile 编程(2.4)]; cutile_python/术语表.md:15 [承接既有项目(本书高频承接词)] |
| auxiliary output | 辅助输出 | 首现中英，后文中文 |  | cublas/术语表.md:248 [第 1 章与 3.1–3.2(G7)] |
| availability | 可用性 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:243 [第 15–21 章(收官批次)新确立] |
| backward compatible / compatibility | 向后兼容 / 兼容性 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:216 [第 15–21 章(收官批次)新确立] |
| banded matrix | 带状矩阵 | 首现中英，后文中文 |  | cublas/术语表.md:133 [2.6 Level-2(G1)] |
| bandwidth | 带宽 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:63 [第 3 章(Heterogeneous Computing)新确立] |
| bank conflict | bank 冲突 | 英文 |  | cuda_programming_guide/术语表.md:135 [内存(2.3、2.6)] |
| bare metal | 裸机 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:267 [驱动 API 与多 GPU(3.3–3.4)] |
| barrier phase / parity | 屏障阶段 / 奇偶性 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:338 [4.4 / 4.9 / 4.10 / 4.12 / 4.14 执行与同步] |
| base pointer | 基指针 | 首现中英，后文中文 |  | tile_ir/术语表.md:90 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| base relation | 基本关系 | 首现中英，后文中文 |  | tile_ir/术语表.md:69 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| basic block | 基本块(basic block) | 首现中英，后文中文 |  | tile_ir/术语表.md:135 [第 8 章 8.4–8.6(补译 Agent,2026-08-29)] |
| batch dimension | 批次维度 | 首现中英，后文中文 |  | cutile_python/术语表.md:173 [API 参考批次(箱1:Load/Store~Selection;箱2:Math~JAX FFI;2026-08-29)] |
| batch mode | 批量模式(3.3.9 注语境作"批处理模式") | 首现中英，后文中文 |  | cublas/术语表.md:225 [3.4 cuBLASLt API 参考(G6)] |
| batched / strided batched / grouped batched | 批量 / 跨步批量 / 分组批量(API 名本身不译) | 首现中英，后文中文 |  | cublas/术语表.md:78 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| batched matrix multiplication | 批量(batched)矩阵乘法 | 首现中英，后文中文 |  | tile_ir/术语表.md:207 [第 8 章 8.7–8.8(第三次补派 Agent,2026-08-29)] |
| batching | 批处理 / 批量 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:219 [启动与主机侧 API(3.1)] |
| batching / batch | 批处理 / 批量 | 首现中英，后文中文 |  | cublas/术语表.md:27 [基准承接(沿用 CUDA Programming Guide 既有译法)] |
| benchmark | 基准测试 | 首现中英，后文中文 |  | cublas/术语表.md:118 [2.1–2.5 总论与 Level-1(G4)] |
| best practices | 最佳实践 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:22 [本章新确立术语] |
| bias vector | 偏置向量 | 首现中英，后文中文 |  | cublas/术语表.md:220 [3.4 cuBLASLt API 参考(G6)] |
| bias(epilogue) | 偏置 | 首现中英，后文中文 |  | cublas/术语表.md:247 [第 1 章与 3.1–3.2(G7)] |
| bidirectional data rate | 双向数据速率 | 首现中英，后文中文 |  | hopper_tuning_guide/术语表.md:47 [本文档新确立] |
| binary / source compatibility | 二进制 / 源码兼容性 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:31 [沿用既有项目译法(预置进分发 prompt)] |
| binary compatibility | 二进制兼容性 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:91 [平台与工具链] |
| binary interface | 二进制接口 | 首现中英，后文中文 |  | cutile_python/术语表.md:136 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| bindless / pitch | 无绑定(bindless)/ 间距(pitch) | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:396 [4.15 / 4.19 互操作] |
| bisection bandwidth | 二分带宽 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:270 [驱动 API 与多 GPU(3.3–3.4)] |
| bit field / bitmask | 位域 / 位掩码 | 首现中英，后文中文 |  | ptx_isa/术语表.md:166 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| bit-flags | 位标志 | 首现中英，后文中文 |  | cublas/术语表.md:207 [3.3 cuBLASLt 数据类型参考(G5)] |
| bit-size type | 位大小类型 | 首现中英，后文中文 |  | ptx_isa/术语表.md:226 [语法与源码格式(第 4 章)] |
| bit-wise | 按位一致(bit-wise) | 首现中英，后文中文 |  | cublas/术语表.md:274 [第 4 章(G8)] |
| bit-wise reproducibility | 按位可复现性 | 首现中英，后文中文 |  | cusparse/术语表.md:18 [术语表] |
| bitcast | 按位转换(bitcast) | 首现中英，后文中文 |  | tile_ir/术语表.md:129 [第 8 章 8.4–8.6(补译 Agent,2026-08-29)] |
| bitmask | 位掩码(承 PG 4.6.5) | 首现中英，后文中文 |  | cublas/术语表.md:119 [2.1–2.5 总论与 Level-1(G4)] |
| bitwise identical | 按位一致(bitwise identical) | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:103 [第 7 章(Getting the Right Answer)新确立] |
| Blackwell / Ampere / Hopper / Volta / Turing / B200 / GB200 / H100 | (架构/产品名) | 英文 |  | cuda_blackwell_tuning_guide/术语表.md:26 [沿用既有译法(本章高频)] |
| Blackwell / Hopper / Pascal / Volta | (架构名) | 英文 |  | cuda_blackwell_compatibility_guide/术语表.md:22 [沿用基准项目既有译法(本章高频)] |
| BLAS (Basic Linear Algebra Subprograms) | 基本线性代数子程序(BLAS) | 首现中英，后文英文 |  | cublas/术语表.md:41 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| block index space | 块索引空间 | 首现中英，后文中文 |  | cutile_python/术语表.md:155 [API 参考批次(箱1:Load/Store~Selection;箱2:Math~JAX FFI;2026-08-29)] |
| block scale / block-scaled | 块缩放(因子) | 首现中英，后文中文 |  | cutile_python/术语表.md:172 [API 参考批次(箱1:Load/Store~Selection;箱2:Math~JAX FFI;2026-08-29)] |
| block scaling | 块缩放 | 首现中英，后文中文 |  | cublas/术语表.md:89 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)]; tile_ir/术语表.md:208 [第 8 章 8.7–8.8(第三次补派 Agent,2026-08-29)] |
| block(cuTile 逻辑线程块) | 块(block),首现后用 block | 首现中英，后文英文 |  | cutile_python/术语表.md:66 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| block-scaled (MMA) | 块缩放(MMA) | 首现中英，后文中文 |  | cutile_python/术语表.md:123 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| block-stride / grid-stride loop | 块步长 / 网格步长循环 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:346 [4.4 / 4.9 / 4.10 / 4.12 / 4.14 执行与同步] |
| blocking / non-blocking stream | 阻塞流 / 非阻塞流 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:163 [原子与同步(2.3、2.5)] |
| blocking / non-blocking transfer | 阻塞式 / 非阻塞传输 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:154 [第 10 章(Memory Optimizations)新确立] |
| blocking API | 阻塞式 API | 首现中英，后文中文 |  | cublas/术语表.md:272 [第 4 章(G8)] |
| boolean / single value / list option | 布尔选项 / 单值选项 / 列表选项 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:75 [第 4 章(选项描述正文术语;选项名本身不译)] |
| boolean mask | 布尔掩蔽 | 首现中英，后文中文 |  | cutile_python/术语表.md:156 [API 参考批次(箱1:Load/Store~Selection;箱2:Math~JAX FFI;2026-08-29)] |
| boot cycle | 开机周期 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:259 [第 15–21 章(收官批次)新确立] |
| bottleneck | 瓶颈 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:24 [本章新确立术语] |
| bounds / out-of-bounds | 边界 / 越界 | 首现中英，后文中文 |  | tile_ir/术语表.md:91 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| bounds checking | 边界检查 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:118 [kernel 与启动(2.1–2.2)] |
| bounds checking / out of bounds | 边界检查 / 越界 | 首现中英，后文中文 |  | cutile_python/术语表.md:157 [API 参考批次(箱1:Load/Store~Selection;箱2:Math~JAX FFI;2026-08-29)] |
| branch divergence | 分支分歧 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:238 [硬件模型与执行(3.2)] |
| broadcast | 广播 | 首现中英，后文中文 |  | cublas/术语表.md:191 [3.3 cuBLASLt 数据类型参考(G5)]; cuda_programming_guide/术语表.md:136 [内存(2.3、2.6)] |
| broadcast / broadcasting | 广播 | 首现中英，后文中文 |  | cutile_python/术语表.md:18 [承接既有项目(本书高频承接词)] |
| broadcast / multicast | 广播 / 多播 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:166 [第 10 章(Memory Optimizations)新确立] |
| broadcast / reduction / scan | 广播 / 归约 / 扫描 | 首现中英，后文中文 |  | tile_ir/术语表.md:26 [承接既有项目(本表只列本书高频承接词)] |
| broadcastable | 可广播 | 首现中英，后文中文 |  | cutile_python/术语表.md:109 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| broadcasting | 广播 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:181 [Tile 编程(2.4)] |
| build number | 构建号 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:252 [第 15–21 章(收官批次)新确立] |
| built-in variable | 内建变量 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:20 [核心概念] |
| bulk async-group | 批量异步组 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:357 [4.11 异步数据复制]; ptx_isa/术语表.md:73 [数据搬运与类型(第 5 章 + 9.7.9)] |
| bulk atomic | 批量原子 | 首现中英，后文中文 |  | cutile_python/术语表.md:120 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| bulk-asynchronous copy | 批量异步复制 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:255 [硬件模型与执行(3.2)] |
| butterfly addressing / inclusive plus-scan | 蝴蝶寻址 / 包含式加法扫描 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:445 [5.3 / 5.4 语言支持与扩展(两节同词已合并)] |
| by reference / by value | 按引用 / 按值 | 首现中英，后文中文 |  | cublas/术语表.md:65 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| bytecode | 字节码(bytecode) | 首现中英，后文中文 |  | tile_ir/术语表.md:54 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| bytes-in-flight | 在途字节 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:358 [4.11 异步数据复制] |
| C++ dialect | C++ 方言 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:87 [第 4 章(选项描述正文术语;选项名本身不译)] |
| C-contiguous layout | C 连续(C-contiguous)布局 | 首现中英，后文中文 |  | cutile_python/术语表.md:135 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| cache line / memory page | 缓存行 / 内存页 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:149 [内存(2.3、2.6)] |
| cache modifier | 缓存修饰符 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:104 [第 4 章(选项描述正文术语;选项名本身不译)] |
| cache operator / eviction priority / policy | 缓存运算符 / 逐出优先级 / 逐出策略 | 首现中英，后文中文 |  | ptx_isa/术语表.md:75 [数据搬运与类型(第 5 章 + 9.7.9)] |
| call frame / stack frame / call stack / stack overflow | 调用帧 / 栈帧 / 调用栈 / 栈溢出 | 首现中英，后文中文 |  | ptx_isa/术语表.md:174 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| callback callee | 回调被调用方 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:141 [第 6、8 章] |
| callback function | 回调函数 | 首现中英，后文中文 |  | cublas/术语表.md:224 [3.4 cuBLASLt API 参考(G6)]; cuda_programming_guide/术语表.md:166 [原子与同步(2.3、2.5)] |
| callee-save register | 被调用者保存(callee-save)寄存器 | 首现中英，后文中文 |  | ptx_isa/术语表.md:182 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| callgraph | 调用图(callgraph) | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:110 [第 4 章(选项描述正文术语;选项名本身不译)] |
| calling convention | 调用约定 | 首现中英，后文中文 |  | cutile_python/术语表.md:55 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| canonical / unspecified NaN | 规范 NaN / 未指定的 NaN | 首现中英，后文中文 |  | ptx_isa/术语表.md:143 [浮点与数值(9.7.3/9.7.4/9.7.5 + 各处)] |
| canonical layout | 规范化布局 | 首现中英，后文中文 |  | ptx_isa/术语表.md:112 [矩阵乘累加与 TensorCore(9.7.15–9.7.17)] |
| canonical NaN | 规范化 NaN | 首现中英，后文中文 |  | tile_ir/术语表.md:202 [第 8 章 8.7–8.8(第三次补派 Agent,2026-08-29)] |
| canonical synchronization pattern | 规范化同步模式 | 首现中英，后文中文 |  | ptx_isa/术语表.md:127 [矩阵乘累加与 TensorCore(9.7.15–9.7.17)] |
| capability attributes | 能力属性 | 首现中英，后文中文 |  | cublas/术语表.md:194 [3.3 cuBLASLt 数据类型参考(G5)] |
| carry-in/out、borrow-in/out | 进位输入/输出、借位输入/输出 | 首现中英，后文中文 |  | ptx_isa/术语表.md:162 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| carryless multiplication/addition | 无进位乘法 / 加法 | 首现中英，后文中文 |  | ptx_isa/术语表.md:163 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| carveout | 划分(carveout) | 首现中英，后文中文 |  | cuda_blackwell_tuning_guide/术语表.md:14 [沿用既有译法(本章高频)]; cuda_programming_guide/术语表.md:227 [启动与主机侧 API(3.1)]; hopper_tuning_guide/术语表.md:20 [沿用既有项目译法] |
| causality order / base causality order | 因果顺序 / 基础因果顺序 | 首现中英，后文中文 |  | ptx_isa/术语表.md:36 [内存模型(第 8 章 + 9.7.14,承 PG 5.7/5.8 与 09 块)] |
| CFT handle / logical endpoint / resource offset | CFT 句柄 / 逻辑端点(标识符)/ 资源偏移 | 首现中英，后文中文 |  | ptx_isa/术语表.md:194 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| CGA (cooperative group array) | 协作组数组 | 首现中英，后文英文 |  | cuda_programming_guide/术语表.md:190 [Tile 编程(2.4)] |
| changelog | 变更日志 | 首现中英，后文中文 |  | tile_ir/术语表.md:86 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| channel data type / channel order | 通道数据类型 / 通道次序 | 首现中英，后文中文 |  | ptx_isa/术语表.md:201 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| channelwise / rowwise scaling | 逐通道 / 逐行缩放 | 首现中英，后文中文 |  | cublas/术语表.md:249 [第 1 章与 3.1–3.2(G7)] |
| circular communication pipeline | 环形通信流水线 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:362 [4.11 异步数据复制] |
| clamp / wrap | 钳制 / 回绕 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:175 [第 10 章(Memory Optimizations)新确立]; cutile_python/术语表.md:141 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| clamping modifier / execution trap | 钳位修饰符 / 执行陷阱 | 首现中英，后文中文 |  | ptx_isa/术语表.md:203 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| clock domain / clock rate | 时钟域 / 时钟频率 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:260 [第 15–21 章(收官批次)新确立] |
| cluster dimension / grid launch configuration | 集群维度 / 网格启动配置 | 首现中英，后文中文 |  | ptx_isa/术语表.md:187 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| cluster shape | 集群形状 | 首现中英，后文中文 |  | cublas/术语表.md:189 [3.3 cuBLASLt 数据类型参考(G5)] |
| coalesce / coalescing | 合并(coalescing) | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:58 [第 3 章(Heterogeneous Computing)新确立] |
| coalesced (accesses) | 合并访问 | 首现中英，后文中文 |  | cuda_blackwell_tuning_guide/术语表.md:18 [沿用既有译法(本章高频)] |
| coalesced / coalescing | 合并(coalesced) | 首现中英，后文中文 |  | hopper_tuning_guide/术语表.md:21 [沿用既有项目译法] |
| coalesced memory access | 合并内存访问 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:134 [内存(2.3、2.6)] |
| coalescing buffer | 合并缓冲区(coalescing buffer) | 首现中英，后文中文 |  | cuda_blackwell_tuning_guide/术语表.md:37 [本章新确立(第 1 章翻译 Agent 上报,2026-08-29 中心合并)] |
| code base | 代码库 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:92 [第 5–6 章(Parallelizing / Getting Started)新确立] |
| code image / binary load image | 代码镜像 / 二进制加载镜像 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:97 [第 4 章(选项描述正文术语;选项名本身不译)] |
| code instance / translation stage | 代码实例 / 翻译阶段 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:121 [第 5、7 章] |
| code motion fence | 代码移动栅栏 | 首现中英，后文中文 |  | ptx_isa/术语表.md:128 [矩阵乘累加与 TensorCore(9.7.15–9.7.17)] |
| coding metaphor / idiom | 编码隐喻 / 习语 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:40 [本章新确立术语] |
| coefficient matrix | 系数矩阵 | 首现中英，后文中文 |  | cublas/术语表.md:135 [2.6 Level-2(G1)] |
| coherency (software / hardware) | 一致性(软件 / 硬件) | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:145 [内存(2.3、2.6)] |
| collective load/store | 集合式加载 / 存储 | 首现中英，后文中文 |  | ptx_isa/术语表.md:129 [矩阵乘累加与 TensorCore(9.7.15–9.7.17)] |
| collective operations | 集合通信操作 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:266 [驱动 API 与多 GPU(3.3–3.4)] |
| collector buffer | 收集缓冲区 | 首现中英，后文中文 |  | ptx_isa/术语表.md:122 [矩阵乘累加与 TensorCore(9.7.15–9.7.17)] |
| column-major | 列主序 | 首现中英，后文中文 |  | cusparse/术语表.md:22 [术语表] |
| command line utility | 命令行实用程序 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:256 [第 15–21 章(收官批次)新确立] |
| commit / wait | 提交 / 等待 | 首现中英，后文中文 |  | ptx_isa/术语表.md:74 [数据搬运与类型(第 5 章 + 9.7.9)] |
| commit(虚拟地址) | 提交 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:324 [4.3 / 4.16 内存管理] |
| common sub-expression elimination (CSE) | 公共子表达式消除(CSE) | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:205 [第 11–13 章(Execution Config / Instruction / Control Flow)新确立] |
| common subexpression elimination | 公共子表达式消除 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:418 [5.1 / 5.5 计算能力与浮点] |
| communication / observation / coherence order | 通信顺序 / 观察顺序 / 一致性顺序 | 首现中英，后文中文 |  | ptx_isa/术语表.md:37 [内存模型(第 8 章 + 9.7.14,承 PG 5.7/5.8 与 09 块)] |
| compare-and-swap | 比较并交换 | 首现中英，后文中文 |  | cutile_python/术语表.md:121 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)]; tile_ir/术语表.md:148 [第 8 章 8.9–8.12 + 第 12 章附录(Agent C,2026-08-29)] |
| compilation cache | 编译缓存(区别于编程指南 compute cache=计算缓存) | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:120 [第 5、7 章] |
| compilation phase | 编译阶段 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:59 [第 1-3 章] |
| compilation trajectory | 编译轨迹 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:12 [沿用既有项目译法(预置进分发 prompt)] |
| compile-time constant / run-time | 编译时常量 / 运行时 | 首现中英，后文中文 |  | cutile_python/术语表.md:179 [API 参考批次(箱1:Load/Store~Selection;箱2:Math~JAX FFI;2026-08-29)] |
| compiler builtin | 编译器内建函数 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:57 [第 1-3 章] |
| compiler driver | 编译器驱动程序 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:272 [第 15–21 章(收官批次)新确立]; cuda_compiler_driver_nvcc/术语表.md:42 [第 1-3 章] |
| compiler flag / switch | 编译器开关 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:206 [第 11–13 章(Execution Config / Instruction / Control Flow)新确立] |
| compiler hint / kernel hint | 编译器提示 / kernel 提示 | 首现中英，后文中文 |  | cutile_python/术语表.md:98 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| compiler instrumentation | 编译器插桩 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:103 [第 4 章(选项描述正文术语;选项名本身不译)] |
| compiler timeout | 编译器超时 | 首现中英，后文中文 |  | cutile_python/术语表.md:57 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| complementary error function | 补余误差函数 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:203 [第 11–13 章(Execution Config / Instruction / Control Flow)新确立] |
| Complete Example | 完整示例(Complete Example) | 首现中英，后文中文 |  | cutile_python/术语表.md:69 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| compressible memory | 可压缩内存 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:329 [4.3 / 4.16 内存管理]; hopper_tuning_guide/术语表.md:44 [本文档新确立] |
| compute cache | 计算缓存 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:94 [平台与工具链] |
| compute capability | 计算能力 | 首现中英，后文中文 |  | cublas/术语表.md:17 [基准承接(沿用 CUDA Programming Guide 既有译法)]; cuda_blackwell_compatibility_guide/术语表.md:10 [沿用基准项目既有译法(本章高频)]; cuda_blackwell_tuning_guide/术语表.md:15 [沿用既有译法(本章高频)]; cuda_compiler_driver_nvcc/术语表.md:14 [沿用既有项目译法(预置进分发 prompt)]; cutile_python/术语表.md:27 [承接既有项目(本书高频承接词)]; hopper_compatibility_guide/术语表.md:11 [沿用既有项目译法]; hopper_tuning_guide/术语表.md:11 [沿用既有项目译法]; tile_ir/术语表.md:36 [承接既有项目(本表只列本书高频承接词)] |
| Compute Capability (CC) | 计算能力(CC) | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:33 [硬件] |
| compute mode / persistence mode | 计算模式 / 持久化模式 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:263 [第 15–21 章(收官批次)新确立] |
| compute type | 计算类型 | 首现中英，后文中文 |  | cublas/术语表.md:69 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| compute_XX / sm_XX / sm_100a / compute_100a | (架构代号) | 英文 |  | cuda_blackwell_compatibility_guide/术语表.md:23 [沿用基准项目既有译法(本章高频)] |
| concurrent kernel execution | kernel 并发执行 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:190 [第 11–13 章(Execution Config / Instruction / Control Flow)新确立] |
| conditional node / body graph | 条件节点 / 体图 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:308 [4.2 CUDA Graphs] |
| confidence interval | 置信区间 | 首现中英，后文中文 |  | cutile_python/术语表.md:183 [API 参考批次(箱1:Load/Store~Selection;箱2:Math~JAX FFI;2026-08-29)] |
| conflict / data-race | 冲突 / 数据竞争 | 首现中英，后文中文 |  | ptx_isa/术语表.md:46 [内存模型(第 8 章 + 9.7.14,承 PG 5.7/5.8 与 09 块)] |
| conflicting action / potentially concurrent | 冲突动作 / 潜在并发 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:468 [5.6 / 5.2 / 5.7 / 5.8 设备 API、环境变量与形式化模型] |
| constant bank | 常量 bank | 英文 |  | cuda_compiler_driver_nvcc/术语表.md:145 [第 6、8 章] |
| constant cache | 常量缓存 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:72 [内存] |
| constant embedding / constant embedded | 常量嵌入 | 首现中英，后文中文 |  | cutile_python/术语表.md:93 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| constant expression / operator precedence / associativity | 常量表达式 / 运算符优先级 / 结合性 | 首现中英，后文中文 |  | ptx_isa/术语表.md:224 [语法与源码格式(第 4 章)] |
| constant folding / propagation | 常量折叠 / 常量传播 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:419 [5.1 / 5.5 计算能力与浮点] |
| constant-embedded | 常量内嵌 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:196 [Tile 编程(2.4)] |
| constantness | 常量性(constantness) | 首现中英，后文中文 |  | cutile_python/术语表.md:44 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| contention (cross-block / intra-block) | 竞争(跨块 / 块内) | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:187 [Tile 编程(2.4)] |
| context | 上下文 | 首现中英，后文中文 |  | cublas/术语表.md:60 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| context manager | 上下文管理器 | 首现中英，后文中文 |  | cutile_python/术语表.md:125 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| context switch | 上下文切换 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:51 [第 3 章(Heterogeneous Computing)新确立] |
| context(CUDA 上下文) | 上下文(与 context switch 上下文切换 区分) | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:295 [待定(已全部转正,2026-08-28 第 8–14 章定稿)] |
| context(CUDA) | 上下文 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:191 [第 11–13 章(Execution Config / Instruction / Control Flow)新确立] |
| contraction(浮点乘加) | 收缩 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:99 [第 4 章(选项描述正文术语;选项名本身不译)] |
| convenience notation | 便捷写法 | 首现中英，后文中文 |  | cutile_python/术语表.md:159 [API 参考批次(箱1:Load/Store~Selection;箱2:Math~JAX FFI;2026-08-29)] |
| convenience phase | 便利性阶段 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:65 [第 1-3 章] |
| convenience wrapper | 便利封装(convenience wrapper) | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:221 [第 15–21 章(收官批次)新确立] |
| convergent | 汇聚 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:443 [5.3 / 5.4 语言支持与扩展(两节同词已合并)] |
| conversion factor | 转换因子 | 首现中英，后文中文 |  | cublas/术语表.md:255 [第 1 章与 3.1–3.2(G7)] |
| Cooperative Grid / spin-loop | 协作网格 / 自旋循环 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:473 [5.6 / 5.2 / 5.7 / 5.8 设备 API、环境变量与形式化模型] |
| cooperative group handle | 协作组句柄 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:335 [4.4 / 4.9 / 4.10 / 4.12 / 4.14 执行与同步] |
| Cooperative Groups | 协作组 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:97 [平台与工具链] |
| coprocessor | 协处理器 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:49 [第 1-3 章] |
| copy engine | 复制引擎(copy engine) | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:153 [第 10 章(Memory Optimizations)新确立] |
| Copy Engine (CE) | 复制引擎 | 首现中英，后文英文 |  | cuda_programming_guide/术语表.md:220 [启动与主机侧 API(3.1)] |
| correctable / detectable errors | 可纠正 / 可检测错误 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:258 [第 15–21 章(收官批次)新确立] |
| corrective actions | 纠正措施 | 首现中英，后文中文 |  | cuda_blackwell_compatibility_guide/术语表.md:37 [本章新确立(第 1 章翻译 Agent 上报,2026-08-29 中心合并)] |
| CPU routine | CPU 例程 | 首现中英，后文中文 |  | cublas/术语表.md:96 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| CPU-GPU Hybridization | CPU-GPU 混合化 | 首现中英，后文中文 |  | cublas/术语表.md:275 [第 4 章(G8)] |
| cross compilation | 交叉编译 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:23 [沿用既有项目译法(预置进分发 prompt)] |
| cross compiler | 交叉编译器 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:142 [第 6、8 章] |
| cross-execution-space call | 跨执行空间调用(承"执行空间") | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:101 [第 4 章(选项描述正文术语;选项名本身不译)] |
| cross-proxy fence | 跨代理栅栏 | 首现中英，后文中文 |  | ptx_isa/术语表.md:50 [内存模型(第 8 章 + 9.7.14,承 PG 5.7/5.8 与 09 块)] |
| CTA (cooperative thread array) | 协作线程数组 | 首现中英，后文英文 |  | cuda_programming_guide/术语表.md:189 [Tile 编程(2.4)] |
| CTA rank | CTA 秩(rank)——注意与矩阵秩同形异义 | 首现中英，后文中文 |  | ptx_isa/术语表.md:131 [矩阵乘累加与 TensorCore(9.7.15–9.7.17)] |
| CTA-swizzling | CTA-swizzling | 英文 |  | cublas/术语表.md:193 [3.3 cuBLASLt 数据类型参考(G5)] |
| CU_MEM_ALLOCATION_COMP_GENERIC / CU_DEVICE_ATTRIBUTE_GENERIC_COMPRESSION_SUPPORTED 等 | CU_MEM_ALLOCATION_COMP_GENERIC / CU_DEVICE_ATTRIBUTE_GENERIC_COMPRESSION_SUPPORTED 等 | 英文 |  | hopper_tuning_guide/术语表.md:58 [保留不译] |
| cubin / CUDA binary | CUDA 二进制,简称 cubin | 首现中英，后文英文 |  | cuda_programming_guide/术语表.md:89 [平台与工具链] |
| cubin / PTX / fatbin | (产物名) | 英文 |  | hopper_compatibility_guide/术语表.md:13 [沿用既有项目译法] |
| cubin / PTX / fatbin / nvcc | (代码形态/工具名) | 英文 |  | cuda_blackwell_compatibility_guide/术语表.md:11 [沿用基准项目既有译法(本章高频)] |
| cuBLAS / cuBLASLt / cuBLASXt / cuBLASDx | 不译(产品名) | 英文 |  | cublas/术语表.md:42 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| cuBLAS / cuFFT / Thrust | cuBLAS / cuFFT / Thrust | 英文 |  | cuda_best_practices_guide/术语表.md:281 [保留不译(产品/工具/组织名)] |
| CUDA | CUDA | 英文 |  | cusparse/术语表.md:6 [术语表] |
| CUDA Array Interface | CUDA Array Interface(CUDA 数组接口) | 英文 |  | cutile_python/术语表.md:104 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| CUDA C++ | CUDA C++ | 英文 |  | cuda_best_practices_guide/术语表.md:286 [保留不译(产品/工具/组织名)] |
| CUDA C++ / NVIDIA® CUDA® | CUDA C++ / NVIDIA® CUDA® | 英文 |  | cuda_blackwell_compatibility_guide/术语表.md:47 [保留不译(产品/工具名)] |
| CUDA context / primary context | CUDA 上下文 / 主上下文 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:121 [kernel 与启动(2.1–2.2)] |
| CUDA device graph | CUDA 设备(端)图 | 首现中英，后文中文 |  | ptx_isa/术语表.md:192 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| CUDA driver / NVIDIA GPU device driver | CUDA 驱动 / NVIDIA GPU 设备驱动 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:224 [第 15–21 章(收官批次)新确立] |
| CUDA Dynamic Parallelism | CUDA 动态并行 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:98 [平台与工具链] |
| CUDA Enhanced Compatibility | (特性名) | 英文 |  | cuda_best_practices_guide/术语表.md:232 [第 15–21 章(收官批次)新确立] |
| CUDA event | CUDA 事件 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:165 [原子与同步(2.3、2.5)] |
| CUDA Fortran | CUDA Fortran | 英文 |  | cuda_best_practices_guide/术语表.md:282 [保留不译(产品/工具/组织名)] |
| CUDA Forward Compatible Upgrade | CUDA 向前兼容升级 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:231 [第 15–21 章(收官批次)新确立] |
| CUDA Graphs | CUDA Graphs | 英文 |  | cublas/术语表.md:32 [基准承接(沿用 CUDA Programming Guide 既有译法)]; cuda_programming_guide/术语表.md:169 [原子与同步(2.3、2.5)] |
| CUDA in Graphics (CiG) | 保留 | 英文 |  | cublas/术语表.md:116 [2.1–2.5 总论与 Level-1(G4)] |
| CUDA Runtime | CUDA Runtime(CUDA 运行时) | 首现中英，后文英文 |  | cuda_best_practices_guide/术语表.md:217 [第 15–21 章(收官批次)新确立]; cuda_blackwell_compatibility_guide/术语表.md:14 [沿用基准项目既有译法(本章高频)]; cuda_programming_guide/术语表.md:84 [平台与工具链]; hopper_compatibility_guide/术语表.md:15 [沿用既有项目译法] |
| CUDA runtime API / driver API | CUDA 运行时 API / 驱动 API | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:85 [平台与工具链] |
| CUDA runtime error | CUDA 运行时错误 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:126 [第 5、7 章] |
| CUDA Toolkit | CUDA 工具包 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:14 [沿用《CUDA Programming Guide》既有译法(本章已出现)]; cuda_blackwell_compatibility_guide/术语表.md:15 [沿用基准项目既有译法(本章高频)]; cuda_programming_guide/术语表.md:82 [平台与工具链] |
| CUDA User Objects / refcount | CUDA 用户对象 / 引用计数 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:314 [4.2 CUDA Graphs] |
| CUDA-GDB / Nsight Visual Studio Edition | (工具名) | 英文 |  | cuda_best_practices_guide/术语表.md:121 [第 7 章(Getting the Right Answer)新确立] |
| cuda::memcpy_async / cuda::barrier / cuda::pipeline | cuda::memcpy_async / cuda::barrier / cuda::pipeline | 英文 |  | hopper_tuning_guide/术语表.md:57 [保留不译] |
| CUDA_FORCE_PTX_JIT | CUDA_FORCE_PTX_JIT | 英文 |  | cuda_blackwell_compatibility_guide/术语表.md:45 [保留不译(产品/工具名)] |
| CUDA_FORCE_PTX_JIT / CUDA_MODULE_LOADING | CUDA_FORCE_PTX_JIT / CUDA_MODULE_LOADING | 英文 |  | hopper_compatibility_guide/术语表.md:42 [保留不译] |
| CUDA_R_32F / CUBLAS_OP_N 等枚举常量 | 不译 | 英文 |  | cublas/术语表.md:101 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| cuda_tile / tilefatbin / tilecubin / tilebc | 不译 | 英文 |  | tile_ir/术语表.md:42 [承接既有项目(本表只列本书高频承接词)] |
| cudaDeviceEnablePeerAccess() / cudaDeviceCanAccessPeer() | cudaDeviceEnablePeerAccess() / cudaDeviceCanAccessPeer() | 英文 |  | cuda_blackwell_tuning_guide/术语表.md:50 [保留不译(API/属性名)] |
| cudaFuncSetAttribute() / cudaFuncAttributeNonPortableClusterSizeAllowed / cudaFuncAttributePreferredSharedMemoryCarveout | cudaFuncSetAttribute() / cudaFuncAttributeNonPortableClusterSizeAllowed / cudaFuncAttributePreferredSharedMemoryCarveout | 英文 |  | cuda_blackwell_tuning_guide/术语表.md:49 [保留不译(API/属性名)] |
| cudaGetLastError() | cudaGetLastError() | 英文 |  | cuda_best_practices_guide/术语表.md:284 [保留不译(产品/工具/组织名)] |
| cudaOccupancyMaxActiveClusters | cudaOccupancyMaxActiveClusters | 英文 |  | cuda_blackwell_tuning_guide/术语表.md:48 [保留不译(API/属性名)] |
| cumsum / cumprod | 累积和 / 累积乘积 | 首现中英，后文中文 |  | cutile_python/术语表.md:168 [API 参考批次(箱1:Load/Store~Selection;箱2:Math~JAX FFI;2026-08-29)] |
| cumulativity | 累积性 | 首现中英，后文中文 |  | ptx_isa/术语表.md:53 [内存模型(第 8 章 + 9.7.14,承 PG 5.7/5.8 与 09 块)] |
| current phase / phase transition / parity | 当前阶段 / 阶段转换 / 奇偶性 | 首现中英，后文中文 |  | ptx_isa/术语表.md:58 [内存模型(第 8 章 + 9.7.14,承 PG 5.7/5.8 与 09 块)] |
| cuSPARSE | cuSPARSE | 英文 |  | cusparse/术语表.md:5 [术语表] |
| cuTile Python / cuda.tile | 不译 | 英文 |  | cutile_python/术语表.md:38 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| dangling edge (half edge) | 悬空边(半边) | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:304 [4.2 CUDA Graphs] |
| data layout | 数据布局 | 首现中英，后文中文 |  | tile_ir/术语表.md:79 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| data ordering | 数据排布 | 首现中英，后文中文 |  | cublas/术语表.md:221 [3.4 cuBLASLt API 参考(G6)] |
| data parallel primitives | 数据并行原语 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:82 [第 5–6 章(Parallelizing / Getting Started)新确立] |
| data race / hazard | 数据竞争 / 冒险 | 首现中英，后文中文 |  | tile_ir/术语表.md:21 [承接既有项目(本表只列本书高频承接词)] |
| data transfer | 数据传输 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:43 [本章新确立术语] |
| dead code | 死代码 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:108 [第 7 章(Getting the Right Answer)新确立] |
| dead code / stub library | 死代码 / stub 库 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:29 [沿用既有项目译法(预置进分发 prompt)] |
| debug info | 调试信息 | 首现中英，后文中文 |  | tile_ir/术语表.md:82 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| debugger | 调试器 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:110 [第 7 章(Getting the Right Answer)新确立] |
| declaration specifier | 声明修饰符 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:119 [kernel 与启动(2.1–2.2)] |
| decorator | 装饰器 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:123 [kernel 与启动(2.1–2.2)]; cutile_python/术语表.md:24 [承接既有项目(本书高频承接词)] |
| default stream / legacy default stream | 默认流 / 传统默认流 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:161 [原子与同步(2.3、2.5)] |
| default stream / NULL stream | 默认流 / NULL 流 | 首现中英，后文中文 |  | cublas/术语表.md:13 [基准承接(沿用 CUDA Programming Guide 既有译法)] |
| denormal / denormalized number | 非正规数(denormal) | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:196 [第 11–13 章(Execution Config / Instruction / Control Flow)新确立] |
| denormal / fast math / IEEE round-to-nearest | 非正规数 / 快速数学 / IEEE 最近舍入 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:28 [沿用既有项目译法(预置进分发 prompt)] |
| denormalized values | 次正规(denormalized)值(承 PG subnormal) | 首现中英，后文中文 |  | cublas/术语表.md:241 [第 1 章与 3.1–3.2(G7)] |
| dense / sparse | 稠密 / 稀疏 | 首现中英，后文中文 |  | ptx_isa/术语表.md:117 [矩阵乘累加与 TensorCore(9.7.15–9.7.17)] |
| dense constant | 稠密常量 | 首现中英，后文中文 |  | tile_ir/术语表.md:62 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| dense matrix | 稠密矩阵 | 首现中英，后文中文 |  | cusparse/术语表.md:9 [术语表] |
| dense matrix / vector | 稠密矩阵 / 向量 | 首现中英，后文中文 |  | cublas/术语表.md:55 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| dense vector | 稠密向量 | 首现中英，后文中文 |  | cusparse/术语表.md:11 [术语表] |
| dependency file / dependency generation | 依赖文件 / 依赖信息生成 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:76 [第 4 章(选项描述正文术语;选项名本身不译)] |
| dependent / prerequisite grid | 依赖网格 / 先决(前置)网格 | 首现中英，后文中文 |  | ptx_isa/术语表.md:60 [内存模型(第 8 章 + 9.7.14,承 PG 5.7/5.8 与 09 块)] |
| deprecated | 已弃用 | 首现中英，后文中文 |  | cublas/术语表.md:48 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| deprecation | 废弃 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:230 [第 15–21 章(收官批次)新确立] |
| Deprecation Note / Removal Note | 废弃说明 / 移除说明 | 首现中英，后文中文 |  | ptx_isa/术语表.md:238 [结构标签与版本说明(第 9/11/13 章固定短语)] |
| depth compare / layered / multi-sample texture | 深度比较 / 层叠 / 多重采样纹理 | 首现中英，后文中文 |  | ptx_isa/术语表.md:200 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| dequantize / dequantization | 反量化 | 首现中英，后文中文 |  | cublas/术语表.md:246 [第 1 章与 3.1–3.2(G7)] |
| descriptor | 描述符 | 首现中英，后文中文 |  | cublas/术语表.md:29 [基准承接(沿用 CUDA Programming Guide 既有译法)] |
| destination / source operand | 目标 / 源操作数 | 首现中英，后文中文 |  | ptx_isa/术语表.md:19 [核心概念(预置进分发规则,全书沿用)] |
| device function | 设备函数 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:46 [第 1-3 章] |
| device heap / format specifier | 设备堆 / 格式说明符 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:438 [5.3 / 5.4 语言支持与扩展(两节同词已合并)] |
| device link step | 设备链接步骤 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:68 [第 1-3 章] |
| device linker / host linker | 设备链接器 / 主机链接器 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:132 [第 6、8 章] |
| device memory | 设备内存 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:12 [核心概念] |
| device pointer | 设备指针 | 首现中英，后文中文 |  | cutile_python/术语表.md:138 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| device program | 设备程序 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:92 [第 4 章(选项描述正文术语;选项名本身不译)] |
| device runtime | 设备端运行时(与 4.18 "CUDA 设备运行时"同义) | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:460 [5.6 / 5.2 / 5.7 / 5.8 设备 API、环境变量与形式化模型] |
| device utilization | 设备利用率 | 首现中英，后文中文 |  | cublas/术语表.md:201 [3.3 cuBLASLt 数据类型参考(G5)]; cuda_blackwell_tuning_guide/术语表.md:33 [本章新确立(第 1 章翻译 Agent 上报,2026-08-29 中心合并)]; hopper_tuning_guide/术语表.md:28 [沿用既有项目译法] |
| device-debug mode | 设备调试(device-debug)模式 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:55 [第 1-3 章] |
| device-wide synchronization | 设备级同步 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:124 [kernel 与启动(2.1–2.2)] |
| diagnostic control | 诊断控制 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:58 [第 1-3 章] |
| diagonal / regular matrix | 对角矩阵 / 常规矩阵 | 首现中英，后文中文 |  | cublas/术语表.md:159 [2.7 Level-3(G2)] |
| dialect | 方言 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:125 [第 5、7 章]; tile_ir/术语表.md:40 [承接既有项目(本表只列本书高频承接词)] |
| dictionary unpacking | 字典解包 | 首现中英，后文中文 |  | cutile_python/术语表.md:149 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| directive | 伪指令(directive) | 首现中英，后文中文 |  | ptx_isa/术语表.md:14 [核心概念(预置进分发规则,全书沿用)] |
| directives | 指令(directives) | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:86 [第 5–6 章(Parallelizing / Getting Started)新确立] |
| discard / eviction | 丢弃 / 逐出 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:296 [4.1 统一内存] |
| discovery mode / dry run / backfill | 发现模式 / 干跑 / 回填(backfill) | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:375 [4.5 / 4.6 PDL 与绿色上下文] |
| display driver package | 显示驱动包 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:226 [第 15–21 章(收官批次)新确立] |
| Distributed Shared Memory | 分布式共享内存 | 首现中英，后文中文 |  | cuda_blackwell_tuning_guide/术语表.md:13 [沿用既有译法(本章高频)]; cuda_programming_guide/术语表.md:71 [内存]; hopper_tuning_guide/术语表.md:17 [沿用既有项目译法] |
| diverged execution | 发散执行 | 首现中英，后文中文 |  | cuda_blackwell_tuning_guide/术语表.md:34 [本章新确立(第 1 章翻译 Agent 上报,2026-08-29 中心合并)]; hopper_tuning_guide/术语表.md:22 [沿用既有项目译法] |
| divergent / uniform branch;divergence / convergence | 分歧 / 统一分支;分歧 / 汇聚 | 首现中英，后文中文 |  | ptx_isa/术语表.md:171 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| divisibility hints | 整除性提示 | 首现中英，后文中文 |  | cutile_python/术语表.md:53 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| domain-specific language (DSL) | 领域专用语言 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:99 [平台与工具链] |
| dot product | 点积 | 首现中英，后文中文 |  | cublas/术语表.md:122 [2.1–2.5 总论与 Level-1(G4)]; cutile_python/术语表.md:169 [API 参考批次(箱1:Load/Store~Selection;箱2:Math~JAX FFI;2026-08-29)] |
| dot product conjugated/unconjugated | 共轭/非共轭点积 | 首现中英，后文中文 |  | cublas/术语表.md:182 [2.8 类 BLAS 扩展(G3)] |
| double / multi-buffering | 双缓冲 / 多缓冲 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:252 [硬件模型与执行(3.2)] |
| double data rate | 双倍数据速率(double data rate) | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:140 [第 8–9、14 章(Optimizing / Performance Metrics / Deploying)新确立] |
| double extended precision | 双扩展精度 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:119 [第 7 章(Getting the Right Answer)新确立] |
| down / up-conversion | 降精度 / 升精度转换 | 首现中英，后文中文 |  | ptx_isa/术语表.md:148 [浮点与数值(9.7.3/9.7.4/9.7.5 + 各处)] |
| DPX | 动态规划扩展(DPX) | 首现中英，后文中文 |  | hopper_tuning_guide/术语表.md:25 [沿用既有项目译法] |
| DPX / clamping to zero (ReLU) | 动态规划扩展(DPX)/ 钳位到零 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:449 [5.3 / 5.4 语言支持与扩展(两节同词已合并)] |
| DRAM / on-chip memory | DRAM / 片上内存 | 英文 |  | cuda_programming_guide/术语表.md:34 [硬件] |
| DRAM traffic | DRAM 流量 | 首现中英，后文中文 |  | cutile_python/术语表.md:113 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| DRAM traffic / latency hint | DRAM 流量 / 延迟提示 | 英文 |  | cutile_python/术语表.md:160 [API 参考批次(箱1:Load/Store~Selection;箱2:Math~JAX FFI;2026-08-29)] |
| drive prefix | 驱动器前缀 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:78 [第 4 章(选项描述正文术语;选项名本身不译)] |
| driver | 驱动程序 | 首现中英，后文中文 |  | cuda_blackwell_compatibility_guide/术语表.md:19 [沿用基准项目既有译法(本章高频)] |
| driver entry point access | 驱动入口点访问 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:281 [特性巡礼(3.5)] |
| driver entry point access API | 驱动入口点访问 API | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:241 [第 15–21 章(收官批次)新确立] |
| driver stack | 驱动栈 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:223 [第 15–21 章(收官批次)新确立] |
| dtype / DType | dtype 保留 / DType 保留 | 英文 |  | cutile_python/术语表.md:28 [承接既有项目(本书高频承接词)] |
| dump / log buffer / rollover | 转储 / 日志缓冲区 / 回卷 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:384 [4.7 / 4.8 / 4.13 / 4.17 / 4.20 其他] |
| dynamic library | 动态库 | 首现中英，后文中文 |  | cublas/术语表.md:234 [第 1 章与 3.1–3.2(G7)] |
| dynamic loader | 动态加载器 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:253 [第 15–21 章(收官批次)新确立] |
| dynamic parallelism | 动态并行 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:34 [沿用既有项目译法(预置进分发 prompt)] |
| dynamic range | 动态范围 | 首现中英，后文中文 |  | cublas/术语表.md:242 [第 1 章与 3.1–3.2(G7)] |
| early-access | 早期访问 | 首现中英，后文中文 |  | tile_ir/术语表.md:159 [第 8 章 8.9–8.12 + 第 12 章附录(Agent C,2026-08-29)] |
| element space / tile space | 元素空间 / tile 空间 | 首现中英，后文中文 |  | cutile_python/术语表.md:43 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| element type | 元素类型 | 首现中英，后文中文 |  | tile_ir/术语表.md:76 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| element wise reduction | 逐元素归约 | 首现中英，后文中文 |  | hopper_tuning_guide/术语表.md:38 [本文档新确立] |
| element-space offset | 元素空间偏移 | 首现中英，后文中文 |  | cutile_python/术语表.md:163 [API 参考批次(箱1:Load/Store~Selection;箱2:Math~JAX FFI;2026-08-29)] |
| elementary reflector | 初等反射子 | 首现中英，后文中文 |  | cublas/术语表.md:174 [2.8 类 BLAS 扩展(G3)] |
| embedded | 内嵌 | 首现中英，后文中文 |  | cuda_blackwell_compatibility_guide/术语表.md:38 [本章新确立(第 1 章翻译 Agent 上报,2026-08-29 中心合并)] |
| emulation | 仿真 | 首现中英，后文中文 |  | cublas/术语表.md:50 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)]; tile_ir/术语表.md:81 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| emulation strategy / mantissa control | 仿真策略 / 尾数控制 | 首现中英，后文中文 |  | cublas/术语表.md:212 [3.3 cuBLASLt 数据类型参考(G5)] |
| encoding | 编码 | 首现中英，后文中文 |  | tile_ir/术语表.md:64 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| end user | 最终用户 | 首现中英，后文中文 |  | hopper_compatibility_guide/术语表.md:33 [本文档新确立] |
| End-User License Agreement (EULA) | 最终用户许可协议 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:250 [第 15–21 章(收官批次)新确立] |
| entry point / ABI | 入口点 / ABI 保留 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:387 [4.7 / 4.8 / 4.13 / 4.17 / 4.20 其他] |
| enumerant | 枚举值 | 首现中英，后文中文 |  | cublas/术语表.md:66 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| enumerate | 枚举 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:268 [第 15–21 章(收官批次)新确立] |
| environment variable | 环境变量 | 首现中英，后文中文 |  | cuda_blackwell_compatibility_guide/术语表.md:18 [沿用基准项目既有译法(本章高频)]; hopper_compatibility_guide/术语表.md:19 [沿用既有项目译法] |
| environment variables | 环境变量 | 首现中英，后文中文 |  | cutile_python/术语表.md:58 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| ephemeral pointer | 临时指针 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:221 [启动与主机侧 API(3.1)] |
| epilogue | 收尾操作(epilogue) | 首现中英，后文中文 |  | cublas/术语表.md:83 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| epilogue auxiliary buffer | 收尾辅助缓冲区 | 首现中英，后文中文 |  | cublas/术语表.md:199 [3.3 cuBLASLt 数据类型参考(G5)] |
| epsilon | epsilon(容差) | 英文 |  | cuda_best_practices_guide/术语表.md:104 [第 7 章(Getting the Right Answer)新确立] |
| error checking | 错误检查 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:37 [本章新确立术语] |
| error handling / error code / return code | 错误处理 / 错误码 / 返回码 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:244 [第 15–21 章(收官批次)新确立] |
| error state | 错误状态 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:122 [kernel 与启动(2.1–2.2)] |
| error status | 错误状态 | 首现中英，后文中文 |  | cublas/术语表.md:59 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| error-detection and recovery | 错误检测与恢复 | 首现中英，后文中文 |  | cuda_blackwell_tuning_guide/术语表.md:41 [本章新确立(第 1 章翻译 Agent 上报,2026-08-29 中心合并)]; hopper_tuning_guide/术语表.md:48 [本文档新确立] |
| Euclidean norm | 欧几里得范数 | 首现中英，后文中文 |  | cublas/术语表.md:123 [2.1–2.5 总论与 Level-1(G4)] |
| evict / evicted | 逐出(缓存语境;编程指南访问策略语境为"驱逐") | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:170 [第 10 章(Memory Optimizations)新确立] |
| evolutionary / revolutionary | 渐进式 / 革命式 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:143 [第 8–9、14 章(Optimizing / Performance Metrics / Deploying)新确立] |
| exception types | 异常类型 | 首现中英，后文中文 |  | cutile_python/术语表.md:56 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| exclusive process mode | 独占进程模式 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:193 [第 11–13 章(Execution Config / Instruction / Control Flow)新确立] |
| executable graph / capture graph | 可执行图 / 捕获图 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:305 [4.2 CUDA Graphs] |
| execution affinity | 执行亲和性 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:372 [4.5 / 4.6 PDL 与绿色上下文] |
| execution configuration | 执行配置 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:116 [kernel 与启动(2.1–2.2)]; cuda_programming_guide/术语表.md:19 [核心概念] |
| execution context | 执行上下文 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:240 [硬件模型与执行(3.2)] |
| execution environment / stream environment | 执行环境 / 流环境 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:313 [4.2 CUDA Graphs] |
| execution pipeline | 执行流水线 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:52 [第 3 章(Heterogeneous Computing)新确立] |
| execution search path | 执行搜索路径 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:52 [第 1-3 章] |
| execution space | 执行空间 | 首现中英，后文中文 |  | cutile_python/术语表.md:23 [承接既有项目(本书高频承接词)] |
| execution space / memory space / inlining specifier | 执行空间 / 内存空间 / 内联修饰符 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:428 [5.3 / 5.4 语言支持与扩展(两节同词已合并)] |
| exhaustive search | 穷举搜索 | 首现中英，后文中文 |  | cutile_python/术语表.md:143 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| experimental flag | 实验性标志 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:81 [第 4 章(选项描述正文术语;选项名本身不译)] |
| explicit memory management | 显式内存管理 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:130 [内存(2.3、2.6)] |
| exponent bias | 指数偏置 | 首现中英，后文中文 |  | cublas/术语表.md:254 [第 1 章与 3.1–3.2(G7)] |
| Extended GPU Memory (EGM) | 扩展 GPU 内存 | 首现中英，后文英文 |  | cuda_programming_guide/术语表.md:280 [特性巡礼(3.5)] |
| extended lambda / generic lambda | 扩展 lambda / 泛型 lambda | 英文 |  | cuda_programming_guide/术语表.md:430 [5.3 / 5.4 语言支持与扩展(两节同词已合并)] |
| extended precision / condition code (CC) | 扩展精度 / 条件码寄存器(CC) | 首现中英，后文中文 |  | ptx_isa/术语表.md:161 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| extensible whole program mode | 可扩展整程序(extensible whole program)模式 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:54 [第 1-3 章] |
| external / internal linkage | 外部 / 内部链接属性 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:24 [沿用既有项目译法(预置进分发 prompt)]; cuda_programming_guide/术语表.md:207 [编译器(2.7)] |
| f-string / string literal | f 字符串 / 字符串字面量 | 首现中英，后文中文 |  | cutile_python/术语表.md:186 [API 参考批次(箱1:Load/Store~Selection;箱2:Math~JAX FFI;2026-08-29)] |
| fabric / CUDA CFT | 网状互连(fabric)/ CUDA 计算网状互连传输 | 首现中英，后文中文 |  | ptx_isa/术语表.md:193 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| fabric / fabric memory | fabric 保留 / Fabric 内存 | 英文 |  | cuda_programming_guide/术语表.md:328 [4.3 / 4.16 内存管理] |
| factory function | 工厂函数 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:177 [Tile 编程(2.4)] |
| factory(操作分类) | 工厂(Factory)操作 | 首现中英，后文中文 |  | cutile_python/术语表.md:62 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| fall-through | 顺序落空执行(fall-through) | 首现中英，后文中文 |  | ptx_isa/术语表.md:170 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| fallback / fail gracefully | 回退 / 优雅地失败 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:237 [第 15–21 章(收官批次)新确立] |
| fallback value | 回退值 | 首现中英，后文中文 |  | cutile_python/术语表.md:112 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| false dependency | 虚假依赖 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:224 [启动与主机侧 API(3.1)] |
| false-y | 假值(false-y) | 首现中英，后文中文 |  | tile_ir/术语表.md:132 [第 8 章 8.4–8.6(补译 Agent,2026-08-29)] |
| family(GPU 家族) | 家族 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:107 [第 4 章(选项描述正文术语;选项名本身不译)] |
| family-specific architecture | 家族专属架构 | 首现中英，后文中文 |  | ptx_isa/术语表.md:88 [数据搬运与类型(第 5 章 + 9.7.9)] |
| fast accumulation | 快速累加 | 首现中英，后文中文 |  | cublas/术语表.md:197 [3.3 cuBLASLt 数据类型参考(G5)]; cutile_python/术语表.md:171 [API 参考批次(箱1:Load/Store~Selection;箱2:Math~JAX FFI;2026-08-29)] |
| fast math | 快速数学(fast math) | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:204 [第 11–13 章(Execution Config / Instruction / Control Flow)新确立] |
| fast math modes | 快速数学模式 | 首现中英，后文中文 |  | cublas/术语表.md:156 [2.7 Level-3(G2)] |
| fast path / slow path | 快速路径 / 慢速路径 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:199 [第 11–13 章(Execution Config / Instruction / Control Flow)新确立] |
| fatbin | fatbin | 英文 |  | cuda_programming_guide/术语表.md:90 [平台与工具链] |
| fatbin compression | fatbin 压缩 | 英文 |  | cuda_programming_guide/术语表.md:210 [编译器(2.7)] |
| fatbinary / fatbin image | fatbin 保留;镜像(image) | 英文 |  | cuda_compiler_driver_nvcc/术语表.md:27 [沿用既有项目译法(预置进分发 prompt)] |
| fault-and-migrate | 缺页即迁移 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:294 [4.1 统一内存] |
| feature testing macro | 特性测试宏 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:33 [沿用既有项目译法(预置进分发 prompt)] |
| fence | 栅栏 | 首现中英，后文中文 |  | tile_ir/术语表.md:71 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| fence / barrier | 栅栏(指令名保留)/ 屏障 | 首现中英，后文中文 |  | ptx_isa/术语表.md:43 [内存模型(第 8 章 + 9.7.14,承 PG 5.7/5.8 与 09 块)] |
| fence(D3D12/NvSciSync) | 围栏 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:400 [4.15 / 4.19 互操作] |
| Fence-SC order / axiom | Fence-SC 顺序 / 公理 | 英文 |  | ptx_isa/术语表.md:39 [内存模型(第 8 章 + 9.7.14,承 PG 5.7/5.8 与 09 块)] |
| FFTW / BLAS | (库名) | 英文 |  | cuda_best_practices_guide/术语表.md:94 [第 5–6 章(Parallelizing / Getting Started)新确立] |
| Fifth-Generation NVLink | 第五代 NVLink | 英文 |  | cuda_blackwell_tuning_guide/术语表.md:42 [本章新确立(第 1 章翻译 Agent 上报,2026-08-29 中心合并)] |
| filtering / normalized texture coordinates / addressing mode | 过滤 / 归一化纹理坐标 / 寻址模式 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:174 [第 10 章(Memory Optimizations)新确立] |
| fine-tune | 微调 | 首现中英，后文中文 |  | hopper_tuning_guide/术语表.md:35 [本文档新确立] |
| fine-tuning | 微调 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:129 [第 8–9、14 章(Optimizing / Performance Metrics / Deploying)新确立] |
| fire-and-forget launch | 即发即弃启动 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:311 [4.2 CUDA Graphs] |
| first-order / second-order view | 一阶 / 二阶视图 | 首现中英，后文中文 |  | tile_ir/术语表.md:188 [第 2/4/5/6 章(补派 Agent D,2026-08-29)] |
| fixed-point | 定点 | 首现中英，后文中文 |  | cublas/术语表.md:52 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| fixed-point data format | 定点数据格式 | 首现中英，后文中文 |  | ptx_isa/术语表.md:91 [数据搬运与类型(第 5 章 + 9.7.9)] |
| fixed-width / variable-width integer | 定宽整数 / 变宽整数(VarInt) | 首现中英，后文中文 |  | tile_ir/术语表.md:179 [第 2/4/5/6 章(补派 Agent D,2026-08-29)] |
| flag(rotm/rotmg 标志位) | 标志(flag) | 首现中英，后文中文 |  | cublas/术语表.md:125 [2.1–2.5 总论与 Level-1(G4)] |
| flat profile | 平坦的性能分析剖面(flat profile) | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:91 [第 5–6 章(Parallelizing / Getting Started)新确立] |
| floating context | "浮动"上下文 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:264 [驱动 API 与多 GPU(3.3–3.4)] |
| floating point emulation | 浮点仿真 | 首现中英，后文中文 |  | cublas/术语表.md:51 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| floating-point operation | 浮点运算 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:16 [沿用《CUDA Programming Guide》既有译法(本章已出现)] |
| flush to zero | 冲洗为零(保留符号) | 首现中英，后文中文 |  | cutile_python/术语表.md:175 [API 参考批次(箱1:Load/Store~Selection;箱2:Math~JAX FFI;2026-08-29)] |
| flush-to-zero (ftz) | 清零到零(ftz)/ 清零为保留符号的零 | 首现中英，后文中文 |  | ptx_isa/术语表.md:141 [浮点与数值(9.7.3/9.7.4/9.7.5 + 各处)] |
| FMA (Fused Multiply-Add) | 融合乘加 | 首现中英，后文中文 |  | cublas/术语表.md:24 [基准承接(沿用 CUDA Programming Guide 既有译法)] |
| formal parameter / caller / callee | 形式参数(形参)/ 调用者 / 被调用函数 | 首现中英，后文中文 |  | ptx_isa/术语表.md:177 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| Fortran bindings | Fortran 绑定 | 首现中英，后文中文 |  | cublas/术语表.md:98 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| forward / backward binary compatibility | 向前 / 向后二进制兼容 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:246 [第 15–21 章(收官批次)新确立] |
| forward / backward compatible | 向前兼容 / 向后兼容 | 首现中英，后文中文 |  | hopper_compatibility_guide/术语表.md:14 [沿用既有项目译法] |
| forward / backward pass | 前向传播 / 反向传播 | 首现中英，后文中文 |  | cublas/术语表.md:196 [3.3 cuBLASLt 数据类型参考(G5)] |
| forward / backward triangular solver | 前代与回代三角求解器 | 首现中英，后文中文 |  | cublas/术语表.md:171 [2.8 类 BLAS 扩展(G3)] |
| forward compatibility | 向前兼容性 | 首现中英，后文中文 |  | cublas/术语表.md:18 [基准承接(沿用 CUDA Programming Guide 既有译法)]; cuda_compiler_driver_nvcc/术语表.md:17 [沿用既有项目译法(预置进分发 prompt)] |
| forward compatibility / performance state (pstate) | 前向兼容性 / 性能状态 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:464 [5.6 / 5.2 / 5.7 / 5.8 设备 API、环境变量与形式化模型] |
| forward progress | 前向推进 | 首现中英，后文中文 |  | tile_ir/术语表.md:184 [第 2/4/5/6 章(补派 Agent D,2026-08-29)] |
| forward-compatible / backward compatible | 向前兼容 / 向后兼容 | 首现中英，后文中文 |  | cuda_blackwell_compatibility_guide/术语表.md:12 [沿用基准项目既有译法(本章高频)] |
| forward-compatible PTX assembly | 向前兼容的 PTX 汇编 | 首现中英，后文中文 |  | cuda_blackwell_compatibility_guide/术语表.md:31 [本章新确立(第 1 章翻译 Agent 上报,2026-08-29 中心合并)] |
| FP8 / FP4 / FP16 / BF16 / TF32 / INT8 / FP32 / FP64 等类型名 | 不译 | 英文 |  | cublas/术语表.md:99 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| fragment | 片段(fragment) | 首现中英，后文中文 |  | tile_ir/术语表.md:32 [承接既有项目(本表只列本书高频承接词)] |
| free-threading | 自由线程 | 首现中英，后文中文 |  | cutile_python/术语表.md:144 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| front-end / back-end (compilation target) | 前端 / 后端(编译目标) | 首现中英，后文中文 |  | hopper_compatibility_guide/术语表.md:29 [本文档新确立] |
| front-end / back-end (compilation) | 前端 / 后端(编译) | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:15 [沿用既有项目译法(预置进分发 prompt)] |
| front-end / back-end compilation target | 前端 / 后端编译目标 | 首现中英，后文中文 |  | cuda_blackwell_compatibility_guide/术语表.md:34 [本章新确立(第 1 章翻译 Agent 上报,2026-08-29 中心合并)] |
| frontend compiler | 前端编译器 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:56 [第 1-3 章] |
| frozen dataclass | 冻结 dataclass | 首现中英，后文中文 |  | cutile_python/术语表.md:146 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| full rank | 满秩 | 首现中英，后文中文 |  | cublas/术语表.md:177 [2.8 类 BLAS 扩展(G3)] |
| functional unit | 功能单元 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:30 [硬件] |
| functor | 仿函数 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:120 [kernel 与启动(2.1–2.2)] |
| fundamental / basic type | 基本类型 / 基本类别(两词刻意区分) | 首现中英，后文中文 |  | ptx_isa/术语表.md:92 [数据搬运与类型(第 5 章 + 9.7.9)] |
| funnel shift / rotate / clamp / wrap | 漏斗移位 / 循环移位 / 钳位 / 回绕 | 首现中英，后文中文 |  | ptx_isa/术语表.md:168 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| fused multiply-add | 融合乘加 | 首现中英，后文中文 |  | ptx_isa/术语表.md:119 [矩阵乘累加与 TensorCore(9.7.15–9.7.17)]; tile_ir/术语表.md:199 [第 8 章 8.7–8.8(第三次补派 Agent,2026-08-29)] |
| Fused Multiply-Add (FMA) | 融合乘加(FMA) | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:117 [第 7 章(Getting the Right Answer)新确立]; cuda_programming_guide/术语表.md:414 [5.1 / 5.5 计算能力与浮点] |
| gather / scatter | 聚集 / 散射 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:61 [Tile 编程(CUDA 13 新增)]; cutile_python/术语表.md:19 [承接既有项目(本书高频承接词)]; tile_ir/术语表.md:27 [承接既有项目(本表只列本书高频承接词)] |
| gather/scatter view | 聚集/散射视图 | 首现中英，后文中文 |  | tile_ir/术语表.md:161 [第 8 章 8.9–8.12 + 第 12 章附录(Agent C,2026-08-29)] |
| gather_scatter_view | 聚集/散射视图 | 首现中英，后文中文 |  | tile_ir/术语表.md:172 [第 2/4/5/6 章(补派 Agent D,2026-08-29)] |
| gating factor | 制约因素(gating factor) | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:137 [第 8–9、14 章(Optimizing / Performance Metrics / Deploying)新确立] |
| Gauss complexity reduction | 高斯复杂度消减【裁决:G5 初译"Gauss 复杂度归约"已统一为 2.2.11 先确立译法】 | 首现中英，后文中文 |  | cublas/术语表.md:209 [3.3 cuBLASLt 数据类型参考(G5)] |
| Gaussian complexity reduction (3M) | 高斯复杂度消减(3M) | 首现中英，后文中文 |  | cublas/术语表.md:111 [2.1–2.5 总论与 Level-1(G4)] |
| GEMM | GEMM | 英文 |  | tile_ir/术语表.md:88 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| GEMM (GEneral Matrix-to-matrix Multiply) | 通用矩阵乘法(GEMM) | 首现中英，后文英文 |  | cublas/术语表.md:43 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| generalized dot product | 广义点积 | 首现中英，后文中文 |  | cublas/术语表.md:251 [第 1 章与 3.1–3.2(G7)] |
| generic / async proxy | 通用代理 / 异步代理 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:243 [硬件模型与执行(3.2)] |
| generic addressing / generic address | 通用寻址 / 通用地址 | 首现中英，后文中文 |  | ptx_isa/术语表.md:79 [数据搬运与类型(第 5 章 + 9.7.9)] |
| Generic APIs | Generic API | 英文 |  | cusparse/术语表.md:14 [术语表] |
| GFLOPS | 保留 | 英文 |  | cublas/术语表.md:117 [2.1–2.5 总论与 Level-1(G4)] |
| Givens rotation | 吉文斯旋转(Givens rotation) | 首现中英，后文中文 |  | cublas/术语表.md:76 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| global / shared memory | 全局内存 / 共享内存 | 首现中英，后文中文 |  | tile_ir/术语表.md:16 [承接既有项目(本表只列本书高频承接词)] |
| global array | 全局数组 | 首现中英，后文中文 |  | cutile_python/术语表.md:30 [承接既有项目(本书高频承接词)] |
| global memory | 全局内存 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:69 [内存] |
| global memory coalescing | 全局内存合并 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:48 [执行模型] |
| GPU | GPU | 英文 |  | cusparse/术语表.md:7 [术语表] |
| GPU acceleration | GPU 加速 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:15 [沿用《CUDA Programming Guide》既有译法(本章已出现)] |
| GPU coverage | GPU 覆盖范围 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:119 [第 5、7 章] |
| GPU generation | GPU 世代(GPU Generations) | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:117 [第 5、7 章] |
| gradient(ReLU/GELU 梯度) | 梯度 | 首现中英，后文中文 |  | cublas/术语表.md:192 [3.3 cuBLASLt 数据类型参考(G5)] |
| granularity / sub-chunk / chunk | 粒度 / 子块(分块)/ 块 | 首现中英，后文中文 |  | ptx_isa/术语表.md:116 [矩阵乘累加与 TensorCore(9.7.15–9.7.17)] |
| graph / node / edge | 图 / 节点 / 边 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:303 [4.2 CUDA Graphs] |
| graphics / memory clock | 图形时钟 / 显存时钟 | 首现中英，后文中文 |  | cutile_python/术语表.md:119 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| graphics context | 图形上下文 | 首现中英，后文中文 |  | cublas/术语表.md:113 [2.1–2.5 总论与 Level-1(G4)] |
| Graphics Processing Cluster (GPC) | 图形处理簇(GPC) | 首现中英，后文英文 |  | cuda_programming_guide/术语表.md:29 [硬件] |
| Green Context | Green Context(绿色上下文,承 PG 3.5.2.1) | 首现中英，后文英文 |  | cublas/术语表.md:219 [3.4 cuBLASLt API 参考(G6)] |
| green context / execution context | 绿色上下文 / 执行上下文 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:278 [特性巡礼(3.5)] |
| grid | 网格 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:17 [核心概念] |
| grid size / block size | 网格尺寸 / 线程块尺寸 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:188 [第 11–13 章(Execution Config / Instruction / Control Flow)新确立] |
| grid(cuTile) | 网格(grid) | 首现中英，后文中文 |  | cutile_python/术语表.md:67 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| Gustafson's Law | 古斯塔夫森定律 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:31 [本章新确立术语] |
| half precision | 半精度 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:201 [第 11–13 章(Execution Config / Instruction / Control Flow)新确立] |
| half warp | 半 warp(与编程指南 half-warp 一致) | 英文 |  | cuda_best_practices_guide/术语表.md:168 [第 10 章(Memory Optimizations)新确立] |
| half word / quarter word / subword | 半字 / 四分之一字 / 子字 | 首现中英，后文中文 |  | ptx_isa/术语表.md:205 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| half-/single-/double-/quad-precision | 半精度 / 单精度 / 双精度 / 四精度 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:413 [5.1 / 5.5 计算能力与浮点] |
| half-warp / quarter-warp | 半 warp / 四分之一 warp | 英文 |  | cuda_programming_guide/术语表.md:234 [硬件模型与执行(3.2)] |
| half/single/double precision | 半精度 / 单精度 / 双精度 | 首现中英，后文中文 |  | cublas/术语表.md:25 [基准承接(沿用 CUDA Programming Guide 既有译法)] |
| halo / convolution filter footprint | halo(边界区)/ 卷积滤波器覆盖范围 | 首现中英，后文中文 |  | ptx_isa/术语表.md:100 [数据搬运与类型(第 5 章 + 9.7.9)] |
| handle | 句柄 | 首现中英，后文中文 |  | cublas/术语表.md:45 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| handle-based API | 基于句柄的 API | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:261 [驱动 API 与多 GPU(3.3–3.4)] |
| hanging kernel | 挂起的 kernel | 首现中英，后文中文 |  | cutile_python/术语表.md:140 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| happens-before | 先行(happens-before) | 首现中英，后文中文 |  | ptx_isa/术语表.md:32 [内存模型(第 8 章 + 9.7.14,承 PG 5.7/5.8 与 09 块)] |
| happens-before / sequenced before / synchronizes with | 先行(happens-before)/ 顺序先于 / 同步于(4.14 的 "synchronizes-with 关系"名词形态与此动词形态并存) | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:466 [5.6 / 5.2 / 5.7 / 5.8 设备 API、环境变量与形式化模型] |
| hardware generation | 硬件代际 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:242 [第 15–21 章(收官批次)新确立] |
| Hardware Memory Compression | Hardware Memory Compression | 英文 |  | cusparse/术语表.md:20 [术语表] |
| HBM3 / HBM3e / NVLink / PCIe | (产品/互连名) | 英文 |  | cuda_blackwell_tuning_guide/术语表.md:25 [沿用既有译法(本章高频)] |
| header / footer(字节码) | 文件头 / 文件尾 | 首现中英，后文中文 |  | tile_ir/术语表.md:98 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| helper function | 辅助函数 | 首现中英，后文中文 |  | cublas/术语表.md:58 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)]; cuda_best_practices_guide/术语表.md:254 [第 15–21 章(收官批次)新确立] |
| Hermitian | 埃尔米特(Hermitian) | 首现中英，后文中文 |  | cublas/术语表.md:73 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| heterogeneous system | 异构系统 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:21 [核心概念] |
| heuristic query | 启发式查询 | 首现中英，后文中文 |  | cublas/术语表.md:82 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| heuristics | 启发式 | 首现中英，后文中文 |  | cublas/术语表.md:81 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| heuristics cache | 启发式缓存 | 首现中英，后文中文 |  | cublas/术语表.md:243 [第 1 章与 3.1–3.2(G7)] |
| hidden visibility / enclosing namespace | 隐藏可见性 / 外围命名空间 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:93 [第 4 章(选项描述正文术语;选项名本身不译)] |
| high-priority recommendations | 高优先级建议 | 首现中英，后文中文 |  | cuda_blackwell_tuning_guide/术语表.md:35 [本章新确立(第 1 章翻译 Agent 上报,2026-08-29 中心合并)] |
| hit ratio / hitProp / missProp | 命中率(hitProp 等参数名保留) | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:165 [第 10 章(Memory Optimizations)新确立] |
| homogeneous / heterogeneous partition | 同构 / 异构分区 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:374 [4.5 / 4.6 PDL 与绿色上下文] |
| host / device | 主机 / 设备 | 首现中英，后文中文 |  | cublas/术语表.md:14 [基准承接(沿用 CUDA Programming Guide 既有译法)]; cuda_best_practices_guide/术语表.md:12 [沿用《CUDA Programming Guide》既有译法(本章已出现)]; cuda_compiler_driver_nvcc/术语表.md:25 [沿用既有项目译法(预置进分发 prompt)]; cuda_programming_guide/术语表.md:10 [核心概念]; hopper_tuning_guide/术语表.md:27 [沿用既有项目译法]; tile_ir/术语表.md:14 [承接既有项目(本表只列本书高频承接词)] |
| host / SIMT | 主机 / SIMT | 首现中英，后文中文 |  | cutile_python/术语表.md:25 [承接既有项目(本书高频承接词)] |
| host code / device code | 主机代码 / 设备代码 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:109 [第 7 章(Getting the Right Answer)新确立] |
| host code / SIMT code / tile code | 主机代码 / SIMT 代码 / tile 代码 | 首现中英，后文中文 |  | cutile_python/术语表.md:42 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| host compiler | 主机编译器 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:13 [沿用既有项目译法(预置进分发 prompt)]; cuda_programming_guide/术语表.md:204 [编译器(2.7)] |
| host memory / system memory | 主机内存 / 系统内存 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:11 [核心概念] |
| host object file | 主机目标文件 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:134 [第 6、8 章] |
| host process | 主机进程 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:44 [第 1-3 章] |
| host toolchain | 主机工具链 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:94 [第 4 章(选项描述正文术语;选项名本身不译)] |
| hotspot | 热点 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:28 [本章新确立术语] |
| Householder reflection | Householder 反射 | 首现中英，后文中文 |  | cublas/术语表.md:173 [2.8 类 BLAS 扩展(G3)] |
| huge page | 大页 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:292 [4.1 统一内存] |
| hybrid CPU-GPU computation | 混合 CPU-GPU 计算 | 首现中英，后文中文 |  | cublas/术语表.md:95 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| hyperbolic tangent / mantissa LSB | 双曲正切 / 尾数最低有效位 | 首现中英，后文中文 |  | ptx_isa/术语表.md:152 [浮点与数值(9.7.3/9.7.4/9.7.5 + 各处)] |
| identification macro | 标识宏 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:53 [第 1-3 章] |
| identity element | 单位元 | 首现中英，后文中文 |  | cutile_python/术语表.md:166 [API 参考批次(箱1:Load/Store~Selection;箱2:Math~JAX FFI;2026-08-29)] |
| IEEE 754 standard | IEEE 754 标准 | 英文 |  | cuda_best_practices_guide/术语表.md:118 [第 7 章(Getting the Right Answer)新确立] |
| ill-formed | 非良构 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:184 [Tile 编程(2.4)] |
| ill-formed / well-formed | 非良构 / 良构 | 首现中英，后文中文 |  | tile_ir/术语表.md:39 [承接既有项目(本表只列本书高频承接词)] |
| imaginary plane | 虚平面 | 首现中英，后文中文 |  | cublas/术语表.md:211 [3.3 cuBLASLt 数据类型参考(G5)] |
| IMEX channel / IMEX domain | IMEX 通道 / IMEX 域 | 英文 |  | cuda_programming_guide/术语表.md:326 [4.3 / 4.16 内存管理] |
| IMMA kernels | IMMA 保留 | 英文 |  | cublas/术语表.md:180 [2.8 类 BLAS 扩展(G3)] |
| immediate (operand) | 立即数 | 首现中英，后文中文 |  | ptx_isa/术语表.md:20 [核心概念(预置进分发规则,全书沿用)] |
| immediate argument | 立即数参数 | 首现中英，后文中文 |  | tile_ir/术语表.md:59 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| implementation-defined behavior / glvalue / automatic storage duration | 实现定义行为 / 泛左值(glvalue)/ 自动存储期 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:472 [5.6 / 5.2 / 5.7 / 5.8 设备 API、环境变量与形式化模型] |
| implementation-defined value | 由实现定义的值 | 首现中英，后文中文 |  | cutile_python/术语表.md:178 [API 参考批次(箱1:Load/Store~Selection;箱2:Math~JAX FFI;2026-08-29)] |
| implicit group / partition | 隐式组 / 划分 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:336 [4.4 / 4.9 / 4.10 / 4.12 / 4.14 执行与同步] |
| implicit initialization | 隐式初始化 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:220 [第 15–21 章(收官批次)新确立] |
| implicit promotion | 隐式提升 | 首现中英，后文中文 |  | cutile_python/术语表.md:106 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| import / export | 导入 / 导出 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:398 [4.15 / 4.19 互操作] |
| in-bounds | 界内 | 首现中英，后文中文 |  | cutile_python/术语表.md:134 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| in-flight | 在途 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:277 [特性巡礼(3.5)] |
| in-order stream | 按序流 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:164 [原子与同步(2.3、2.5)] |
| in-place / out-of-place | 原地 / 非原地 | 首现中英，后文中文 |  | cublas/术语表.md:160 [2.7 Level-3(G2)]; cublas/术语表.md:277 [第 4 章(G8)] |
| inclusive lower bound | 下界(含端点) | 首现中英，后文中文 |  | cutile_python/术语表.md:132 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| inclusive prefix | 包含式前缀 | 首现中英，后文中文 |  | cutile_python/术语表.md:124 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)]; cutile_python/术语表.md:167 [API 参考批次(箱1:Load/Store~Selection;箱2:Math~JAX FFI;2026-08-29)] |
| incomplete array / opaque type | 不完整数组 / 不透明类型 | 首现中英，后文中文 |  | ptx_isa/术语表.md:93 [数据搬运与类型(第 5 章 + 9.7.9)] |
| Independent Thread Scheduling | 独立线程调度 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:209 [第 11–13 章(Execution Config / Instruction / Control Flow)新确立]; cuda_blackwell_compatibility_guide/术语表.md:20 [沿用基准项目既有译法(本章高频)]; cuda_programming_guide/术语表.md:236 [硬件模型与执行(3.2)]; hopper_compatibility_guide/术语表.md:17 [沿用既有项目译法] |
| index space | 索引空间 | 首现中英，后文中文 |  | tile_ir/术语表.md:152 [第 8 章 8.9–8.12 + 第 12 章附录(Agent C,2026-08-29)] |
| induction variable | 归纳变量(induction variable) | 首现中英，后文中文 |  | tile_ir/术语表.md:137 [第 8 章 8.4–8.6(补译 Agent,2026-08-29)] |
| init-capture / capture by value/reference | 初始化捕获 / 按值捕获·按引用捕获 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:433 [5.3 / 5.4 语言支持与扩展(两节同词已合并)] |
| inline compression (ILC) | 内联压缩(inline compression,ILC) | 首现中英，后文中文 |  | hopper_tuning_guide/术语表.md:43 [本文档新确立] |
| inner / outer indices | 内层 / 外层索引 | 首现中英，后文中文 |  | cublas/术语表.md:256 [第 1 章与 3.1–3.2(G7)] |
| inner dot product | 内点积 | 首现中英，后文中文 |  | cublas/术语表.md:208 [3.3 cuBLASLt 数据类型参考(G5)] |
| inner shape | 内部形状 | 首现中英，后文中文 |  | cublas/术语表.md:202 [3.3 cuBLASLt 数据类型参考(G5)] |
| input file name suffix | 输入文件名后缀 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:60 [第 1-3 章] |
| instantiation (graph) | 实例化 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:168 [原子与同步(2.3、2.5)] |
| instruction / modifier / operand | 指令 / 修饰符 / 操作数 | 首现中英，后文中文 |  | ptx_isa/术语表.md:18 [核心概念(预置进分发规则,全书沿用)] |
| instruction-level parallelism (ILP) | 指令级并行性(ILP) | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:189 [第 11–13 章(Execution Config / Instruction / Control Flow)新确立] |
| Integer Notes / Floating Point Notes / Errata | 整数备注 / 浮点备注 / 勘误 | 首现中英，后文中文 |  | ptx_isa/术语表.md:235 [结构标签与版本说明(第 9/11/13 章固定短语)] |
| integrated CPU-GPU / CPU attached memory | 集成式 CPU-GPU / CPU 附属内存 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:385 [4.7 / 4.8 / 4.13 / 4.17 / 4.20 其他] |
| interconnect | 互连 | 首现中英，后文中文 |  | cuda_blackwell_tuning_guide/术语表.md:39 [本章新确立(第 1 章翻译 Agent 上报,2026-08-29 中心合并)]; hopper_tuning_guide/术语表.md:46 [本文档新确立] |
| interleave execution | 交错执行 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:131 [第 8–9、14 章(Optimizing / Performance Metrics / Deploying)新确立] |
| interleave(d) layout | 交错布局 | 首现中英，后文中文 |  | ptx_isa/术语表.md:99 [数据搬运与类型(第 5 章 + 9.7.9)] |
| intermediate assembly file | 中间汇编文件 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:61 [第 1-3 章] |
| intermediate code | 中间代码 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:67 [第 1-3 章] |
| intermediate representation | 中间表示 | 首现中英，后文中文 |  | ptx_isa/术语表.md:26 [核心概念(预置进分发规则,全书沿用)] |
| intermediate representation (IR) | 中间表示(IR) | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:88 [平台与工具链]; tile_ir/术语表.md:24 [承接既有项目(本表只列本书高频承接词)] |
| interoperability | 互操作 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:219 [第 15–21 章(收官批次)新确立] |
| intrinsic | 内建变量(intrinsic) | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:117 [kernel 与启动(2.1–2.2)] |
| intrinsic function | 内建函数 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:195 [第 11–13 章(Execution Config / Instruction / Control Flow)新确立] |
| Introduced in PTX ISA version X | 在 PTX ISA X 版中引入 | 首现中英，后文中文 |  | ptx_isa/术语表.md:236 [结构标签与版本说明(第 9/11/13 章固定短语)] |
| IPC handle / sub-allocation | IPC 句柄 / 子分配 | 英文 |  | cuda_programming_guide/术语表.md:401 [4.15 / 4.19 互操作] |
| issue granularity | 发出粒度 | 首现中英，后文中文 |  | ptx_isa/术语表.md:124 [矩阵乘累加与 TensorCore(9.7.15–9.7.17)] |
| item | 条目 | 首现中英，后文中文 |  | tile_ir/术语表.md:96 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| iterable / induction variable | 可迭代对象 / 归纳变量 | 首现中英，后文中文 |  | cutile_python/术语表.md:182 [API 参考批次(箱1:Load/Store~Selection;箱2:Math~JAX FFI;2026-08-29)] |
| iterative process | 迭代过程 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:127 [第 8–9、14 章(Optimizing / Performance Metrics / Deploying)新确立] |
| JAX FFI | JAX FFI(FFI=外部函数接口) | 英文 |  | cutile_python/术语表.md:50 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| JAX-traced graph | 经 JAX 追踪(traced)的图 | 首现中英，后文中文 |  | cutile_python/术语表.md:184 [API 参考批次(箱1:Load/Store~Selection;箱2:Math~JAX FFI;2026-08-29)] |
| JIT (just-in-time) compilation | 即时编译(JIT) | 首现中英，后文中文 |  | cuda_blackwell_compatibility_guide/术语表.md:13 [沿用基准项目既有译法(本章高频)] |
| JIT cache | JIT 缓存 | 首现中英，后文中文 |  | cutile_python/术语表.md:99 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| JIT linking | JIT 链接 | 英文 |  | cuda_compiler_driver_nvcc/术语表.md:138 [第 6、8 章] |
| job slot / jobserver / submake | 任务槽(job slot)/ jobserver 保留 / 子 make | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:89 [第 4 章(选项描述正文术语;选项名本身不译)] |
| jump table / case density | 跳转表(jump table)/ case 密度 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:100 [第 4 章(选项描述正文术语;选项名本身不译)] |
| just-in-time (JIT) | 即时编译(JIT) | 首现中英，后文中文 |  | cutile_python/术语表.md:26 [承接既有项目(本书高频承接词)] |
| just-in-time (JIT) compilation | 即时编译(JIT) | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:235 [第 15–21 章(收官批次)新确立]; cuda_compiler_driver_nvcc/术语表.md:16 [沿用既有项目译法(预置进分发 prompt)]; cuda_programming_guide/术语表.md:93 [平台与工具链]; hopper_compatibility_guide/术语表.md:16 [沿用既有项目译法] |
| K/MN/M/N-major / major-ness | K 主序 / MN 主序 / M 主序 / N 主序 / 主序性 | 首现中英，后文中文 |  | ptx_isa/术语表.md:110 [矩阵乘累加与 TensorCore(9.7.15–9.7.17)] |
| kernel | 核函数(kernel),后文多用 kernel | 首现中英，后文英文 |  | cuda_best_practices_guide/术语表.md:13 [沿用《CUDA Programming Guide》既有译法(本章已出现)]; cuda_programming_guide/术语表.md:13 [核心概念] |
| kernel function | 核函数(kernel function),后文 kernel | 首现中英，后文英文 |  | ptx_isa/术语表.md:23 [核心概念(预置进分发规则,全书沿用)] |
| kernel launch | kernel 启动 | 英文 |  | cuda_best_practices_guide/术语表.md:130 [第 8–9、14 章(Optimizing / Performance Metrics / Deploying)新确立] |
| kernel signature | kernel 签名 | 英文 |  | cutile_python/术语表.md:29 [承接既有项目(本书高频承接词)] |
| known issue | 已知问题 | 首现中英，后文中文 |  | tile_ir/术语表.md:85 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| known issues | 已知问题 | 首现中英，后文中文 |  | cutile_python/术语表.md:59 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| known-good | 已知正确(known-good) | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:102 [第 7 章(Getting the Right Answer)新确立] |
| L1 / L2 cache | L1 / L2 缓存 | 英文 |  | cuda_programming_guide/术语表.md:73 [内存] |
| L1 / L2 cache / texture cache | L1 / L2 缓存 / 纹理缓存 | 英文 |  | cuda_blackwell_tuning_guide/术语表.md:17 [沿用既有译法(本章高频)] |
| large scale group / cooperative launch | 大规模组 / 协作启动 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:337 [4.4 / 4.9 / 4.10 / 4.12 / 4.14 执行与同步] |
| latency hiding | 延迟隐藏 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:57 [第 3 章(Heterogeneous Computing)新确立] |
| launch | 启动 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:14 [核心概念] |
| launch arguments | 启动参数 | 首现中英，后文中文 |  | cutile_python/术语表.md:137 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| launch bounds | launch bounds 限定符 | 英文 |  | cuda_best_practices_guide/术语表.md:178 [第 10 章(Memory Optimizations)新确立] |
| launch overhead | 启动开销 | 首现中英，后文中文 |  | cublas/术语表.md:161 [2.7 Level-3(G2)] |
| launch slot / event slot / named limit | 启动槽 / 事件槽 / 命名限制 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:459 [5.6 / 5.2 / 5.7 / 5.8 设备 API、环境变量与形式化模型] |
| lazy / eager module loading | 惰性 / 急切模块加载 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:225 [启动与主机侧 API(3.1)] |
| lazy loading | 惰性加载(Lazy Loading,官方节名保留英文) | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:95 [平台与工具链] |
| lazy loading / End-of-Bytecode marker | 惰性加载 / 字节码结束标记 | 首现中英，后文中文 |  | tile_ir/术语表.md:183 [第 2/4/5/6 章(补派 Agent D,2026-08-29)] |
| LDGSTS / STAS / TMA | 不译(指令与单元名) | 英文 |  | cuda_programming_guide/术语表.md:253 [硬件模型与执行(3.2)] |
| leader thread / elect | 领导线程 / elect 指令保留 | 首现中英，后文中文 |  | ptx_isa/术语表.md:196 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| leading dimension | 前导维度 | 首现中英，后文中文 |  | cublas/术语表.md:19 [基准承接(沿用 CUDA Programming Guide 既有译法)]; cuda_programming_guide/术语表.md:141 [内存(2.3、2.6)] |
| leading dimension / stride | 前导维度 / 步长 | 首现中英，后文中文 |  | ptx_isa/术语表.md:111 [矩阵乘累加与 TensorCore(9.7.15–9.7.17)] |
| least squares | 最小二乘(least squares) | 首现中英，后文中文 |  | cublas/术语表.md:175 [2.8 类 BLAS 扩展(G3)] |
| legacy (API) | 传统(legacy API) | 首现中英，后文中文 |  | cublas/术语表.md:47 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| Legacy APIs | Legacy API | 英文 |  | cusparse/术语表.md:13 [术语表] |
| legacy atomic / compiler built-in atomic / atomic transaction | 传统原子函数 / 编译器内建原子函数 / 原子事务 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:442 [5.3 / 5.4 语言支持与扩展(两节同词已合并)] |
| legacy stream / per-thread default stream | 传统流 / 每线程默认流(承编程指南) | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:96 [第 4 章(选项描述正文术语;选项名本身不译)] |
| Level-1/2/3 | 一级 / 二级 / 三级(BLAS Level-1/2/3) | 首现中英，后文中文 |  | cublas/术语表.md:57 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| libcuda.so / PCIe / NVLink / HBM3 / HBM2e | libcuda.so / PCIe / NVLink / HBM3 / HBM2e | 英文 |  | hopper_tuning_guide/术语表.md:59 [保留不译] |
| lightweight / heavyweight (threads) | 轻量级 / 重量级(线程) | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:53 [第 3 章(Heterogeneous Computing)新确立] |
| linear algebra | 线性代数 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:80 [第 5–6 章(Parallelizing / Getting Started)新确立] |
| linear strong scaling | 线性强扩展 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:70 [第 4 章(Application Profiling)新确立] |
| linkage / external/internal | 链接属性 / 外部·内部链接属性 | 首现中英，后文中文 |  | ptx_isa/术语表.md:179 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| linker script | (主机)链接器脚本 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:84 [第 4 章(选项描述正文术语;选项名本身不译)] |
| litmus test | litmus 测试 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:469 [5.6 / 5.2 / 5.7 / 5.8 设备 API、环境变量与形式化模型]; ptx_isa/术语表.md:51 [内存模型(第 8 章 + 9.7.14,承 PG 5.7/5.8 与 09 块)] |
| little-endian | 小端 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:241 [硬件模型与执行(3.2)]; tile_ir/术语表.md:35 [承接既有项目(本表只列本书高频承接词)] |
| load / store | 加载 / 存储 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:60 [Tile 编程(CUDA 13 新增)] |
| load unbalance | 负载不均衡 | 首现中英，后文中文 |  | cublas/术语表.md:271 [第 4 章(G8)] |
| load/store performance hints | 加载/存储性能提示 | 首现中英，后文中文 |  | cutile_python/术语表.md:52 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| loader library / Display Driver | 加载器库 / 显示驱动 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:79 [第 4 章(选项描述正文术语;选项名本身不译)] |
| local memory | 局部内存 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:132 [内存(2.3、2.6)] |
| local shared memory | 本地共享内存 | 首现中英，后文中文 |  | cuda_blackwell_tuning_guide/术语表.md:32 [本章新确立(第 1 章翻译 Agent 上报,2026-08-29 中心合并)] |
| locality | 局部性 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:76 [内存] |
| location information | 位置信息 | 首现中英，后文中文 |  | tile_ir/术语表.md:83 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| lock step | 锁步(lock step) | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:45 [执行模型] |
| logging / logger | 日志 / 日志器 | 首现中英，后文中文 |  | cublas/术语表.md:92 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| logical / physical / remote domain | 逻辑域 / 物理域 / 远程域 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:350 [4.4 / 4.9 / 4.10 / 4.12 / 4.14 执行与同步] |
| logical thread block | 逻辑线程块 | 首现中英，后文中文 |  | cutile_python/术语表.md:92 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| long name / short name | 长名称 / 短名称 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:74 [第 4 章(选项描述正文术语;选项名本身不译)] |
| loop carried variable | 循环携带变量 | 首现中英，后文中文 |  | tile_ir/术语表.md:191 [第 2/4/5/6 章(补派 Agent D,2026-08-29)] |
| loop-carried value / variable | 循环携带值 / 循环携带变量 | 首现中英，后文中文 |  | tile_ir/术语表.md:136 [第 8 章 8.4–8.6(补译 Agent,2026-08-29)] |
| loosely / strictly typed | 宽松类型 / 严格类型 | 首现中英，后文中文 |  | cutile_python/术语表.md:94 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| lower (编译下沉) | 下沉(lower) | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:197 [Tile 编程(2.4)] |
| lower or upper mode | 下三角或上三角模式 | 首现中英，后文中文 |  | cublas/术语表.md:137 [2.6 Level-2(G1)] |
| lowering / lowered | 降级(lower) | 首现中英，后文中文 |  | cutile_python/术语表.md:100 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| LRU-like eviction policy | 类 LRU 逐出策略 | 首现中英，后文中文 |  | cublas/术语表.md:244 [第 1 章与 3.1–3.2(G7)] |
| LSB-only semantics | 仅最低有效位(LSB-only)语义 | 首现中英，后文中文 |  | tile_ir/术语表.md:211 [第 8 章 8.7–8.8(第三次补派 Agent,2026-08-29)] |
| LTO (Link-Time Optimization) | 链接时优化(LTO) | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:22 [沿用既有项目译法(预置进分发 prompt)]; cuda_programming_guide/术语表.md:208 [编译器(2.7)] |
| LTOIR | LTOIR(LTO 中间产物) | 英文 |  | cuda_compiler_driver_nvcc/术语表.md:137 [第 6、8 章] |
| LU factorization / factorization | LU 因子分解(factorization 首现标注) | 首现中英，后文英文 |  | cublas/术语表.md:167 [2.8 类 BLAS 扩展(G3)] |
| M/N/K-major | M/N/K 主序 | 首现中英，后文中文 |  | cublas/术语表.md:259 [第 1 章与 3.1–3.2(G7)] |
| machine representation | 机器表示 | 首现中英，后文中文 |  | cutile_python/术语表.md:49 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| magic number | 魔数 | 首现中英，后文中文 |  | tile_ir/术语表.md:181 [第 2/4/5/6 章(补派 Agent D,2026-08-29)] |
| magnitude / corner-case | 幅值 / 边界情形 | 首现中英，后文中文 |  | ptx_isa/术语表.md:150 [浮点与数值(9.7.3/9.7.4/9.7.5 + 各处)] |
| major / minor / release (patch) version | 主要版本 / 次要版本 / 发布(修补)版本 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:228 [第 15–21 章(收官批次)新确立] |
| major / minor revision (version) | 主要版本 / 次要版本 | 首现中英，后文中文 |  | cuda_blackwell_compatibility_guide/术语表.md:17 [沿用基准项目既有译法(本章高频)] |
| make dependency | make 依赖关系 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:64 [第 1-3 章] |
| managed memory | 托管内存 | 首现中英，后文中文 |  | cublas/术语表.md:114 [2.1–2.5 总论与 Level-1(G4)]; cuda_programming_guide/术语表.md:144 [内存(2.3、2.6)] |
| mangled name / demangle | 修饰名(mangled name)/ 名字解修饰(demangle) | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:98 [第 4 章(选项描述正文术语;选项名本身不译)] |
| mantissa | 尾数 | 首现中英，后文中文 |  | cublas/术语表.md:21 [基准承接(沿用 CUDA Programming Guide 既有译法)] |
| map / unmap | 映射 / 取消映射 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:395 [4.15 / 4.19 互操作] |
| mapped memory | 映射内存 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:75 [内存] |
| mapped pinned memory | 映射型 pinned 内存 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:151 [第 10 章(Memory Optimizations)新确立] |
| mask off | 掩蔽(mask off) | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:46 [执行模型] |
| masked / masking | 掩蔽 | 首现中英，后文中文 |  | cutile_python/术语表.md:22 [承接既有项目(本书高频承接词)] |
| masked variant | 掩蔽变体 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:179 [Tile 编程(2.4)] |
| masking / masked | 掩蔽 | 首现中英，后文中文 |  | tile_ir/术语表.md:28 [承接既有项目(本表只列本书高频承接词)] |
| math mode | 数学模式 | 首现中英，后文中文 |  | cublas/术语表.md:68 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| matrix / instruction / shared memory descriptor | 矩阵 / 指令 / 共享内存描述符 | 首现中英，后文中文 |  | ptx_isa/术语表.md:113 [矩阵乘累加与 TensorCore(9.7.15–9.7.17)] |
| matrix inversion | 矩阵求逆(matrix inversion) | 首现中英，后文中文 |  | cublas/术语表.md:172 [2.8 类 BLAS 扩展(G3)] |
| matrix layout | 矩阵布局 | 首现中英，后文中文 |  | cublas/术语表.md:84 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| matrix multiplication | 矩阵乘法 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:61 [第 3 章(Heterogeneous Computing)新确立] |
| matrix multiply-accumulate | 矩阵乘累加 | 首现中英，后文中文 |  | ptx_isa/术语表.md:106 [矩阵乘累加与 TensorCore(9.7.15–9.7.17)] |
| matrix of GPU threads | GPU 线程矩阵 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:45 [第 1-3 章] |
| matrix-matrix multiplication | 矩阵-矩阵乘法 | 首现中英，后文中文 |  | cublas/术语表.md:151 [2.7 Level-3(G2)] |
| matrix-vector multiplication | 矩阵-向量乘法 | 首现中英，后文中文 |  | cublas/术语表.md:132 [2.6 Level-2(G1)] |
| MAX_NORM / SAXPY / DLPack / ml_dtypes | 不译(SAXPY 首现附全称) | 英文 |  | tile_ir/术语表.md:193 [第 2/4/5/6 章(补派 Agent D,2026-08-29)] |
| maximum compatibility | 最大兼容性 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:245 [第 15–21 章(收官批次)新确立] |
| maximum/maximumNumber/minimum/minimumNumber(IEEE 754-2019) | 不译 | 英文 |  | tile_ir/术语表.md:203 [第 8 章 8.7–8.8(第三次补派 Agent,2026-08-29)] |
| mbarrier / tx-count / payload report | mbarrier 保留 / tx-count(事务计数)/ 载荷报告 | 英文 |  | ptx_isa/术语表.md:64 [内存模型(第 8 章 + 9.7.14,承 PG 5.7/5.8 与 09 块)] |
| memory access pattern | 内存访问模式 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:59 [第 3 章(Heterogeneous Computing)新确立] |
| memory clock rate / memory interface width | 内存时钟频率 / 内存接口宽度 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:139 [第 8–9、14 章(Optimizing / Performance Metrics / Deploying)新确立] |
| memory fence / flush | 内存栅栏 / 冲刷 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:348 [4.4 / 4.9 / 4.10 / 4.12 / 4.14 执行与同步] |
| memory footprint | 内存占用 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:321 [4.3 / 4.16 内存管理]; hopper_tuning_guide/术语表.md:45 [本文档新确立] |
| memory hierarchy | 内存层级结构 | 首现中英，后文中文 |  | ptx_isa/术语表.md:24 [核心概念(预置进分发规则,全书沿用)] |
| memory instruction | 内存指令 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:207 [第 11–13 章(Execution Config / Instruction / Control Flow)新确立] |
| memory location / overlap | 内存位置 / 重叠(完全/部分) | 首现中英，后文中文 |  | ptx_isa/术语表.md:47 [内存模型(第 8 章 + 9.7.14,承 PG 5.7/5.8 与 09 块)] |
| memory location(其余)、naturally aligned | 自然对齐 | 首现中英，后文中文 |  | ptx_isa/术语表.md:210 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| memory order | 内存顺序 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:188 [Tile 编程(2.4)] |
| memory order / memory scope | 内存顺序 / 内存作用域 | 首现中英，后文中文 |  | cutile_python/术语表.md:13 [承接既有项目(本书高频承接词)] |
| memory ordering | 内存顺序 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:246 [硬件模型与执行(3.2)]; tile_ir/术语表.md:18 [承接既有项目(本表只列本书高频承接词)] |
| memory pool | 内存池 | 首现中英，后文中文 |  | cublas/术语表.md:239 [第 1 章与 3.1–3.2(G7)] |
| memory pool / release threshold | 内存池 / 释放阈值 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:320 [4.3 / 4.16 内存管理] |
| memory reuse policy / opportunistic reuse | 内存复用策略 / 机会性复用 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:322 [4.3 / 4.16 内存管理] |
| memory set function | 内存置位(memory set)函数 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:155 [第 10 章(Memory Optimizations)新确立] |
| memory synchronization domain | 内存同步域 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:349 [4.4 / 4.9 / 4.10 / 4.12 / 4.14 执行与同步]; ptx_isa/术语表.md:59 [内存模型(第 8 章 + 9.7.14,承 PG 5.7/5.8 与 09 块)] |
| memory transaction | 内存事务 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:133 [内存(2.3、2.6)] |
| meta type | 元类型 | 首现中英，后文中文 |  | tile_ir/术语表.md:58 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| metaprogramming | 元编程 | 首现中英，后文中文 |  | cutile_python/术语表.md:60 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| microscaling (MX) | 微缩放(MX) | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:421 [5.1 / 5.5 计算能力与浮点] |
| Minimum Driver Version | 最低驱动版本 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:233 [第 15–21 章(收官批次)新确立] |
| misaligned / strided access / stride | 未对齐 / 跨步访问 / 步长 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:158 [第 10 章(Memory Optimizations)新确立] |
| misaligned memory access | 未对齐内存访问 | 首现中英，后文中文 |  | cublas/术语表.md:155 [2.7 Level-3(G2)] |
| miscompilation | 错误编译 | 首现中英，后文中文 |  | tile_ir/术语表.md:158 [第 8 章 8.9–8.12 + 第 12 章附录(Agent C,2026-08-29)] |
| mixed precision | 混合精度 | 首现中英，后文中文 |  | ptx_isa/术语表.md:154 [浮点与数值(9.7.3/9.7.4/9.7.5 + 各处)] |
| MLIR dialect | MLIR 方言 | 首现中英，后文中文 |  | tile_ir/术语表.md:55 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| mma (matrix multiply-accumulate) | 矩阵乘累加 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:185 [Tile 编程(2.4)]; tile_ir/术语表.md:31 [承接既有项目(本表只列本书高频承接词)] |
| MMIO | 内存映射 IO(MMIO) | 首现中英，后文中文 |  | ptx_isa/术语表.md:55 [内存模型(第 8 章 + 9.7.14,承 PG 5.7/5.8 与 09 块)] |
| modifier | 修饰符 | 首现中英，后文中文 |  | tile_ir/术语表.md:73 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| module scoped | 模块作用域 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:144 [第 6、8 章] |
| monolithic | 单体式(monolithic) | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:106 [第 7 章(Getting the Right Answer)新确立] |
| Monte Carlo simulation | 蒙特卡洛模拟 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:73 [第 4 章(Application Profiling)新确立] |
| moral strength | 道德强度(moral strength) | 首现中英，后文中文 |  | tile_ir/术语表.md:67 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| morally strong | 道义强(morally strong) | 首现中英，后文中文 |  | ptx_isa/术语表.md:35 [内存模型(第 8 章 + 9.7.14,承 PG 5.7/5.8 与 09 块)] |
| most significant N bits / high bits | 最高有效 N 位 / 高位 | 首现中英，后文中文 |  | tile_ir/术语表.md:213 [第 8 章 8.7–8.8(第三次补派 Agent,2026-08-29)] |
| MPI | MPI | 英文 |  | cuda_best_practices_guide/术语表.md:283 [保留不译(产品/工具/组织名)] |
| MPS | MPS(Multi-Process Service) | 英文 |  | cuda_programming_guide/术语表.md:226 [启动与主机侧 API(3.1)] |
| multi-GPU scalability | 多 GPU 可扩展性 | 首现中英，后文中文 |  | cuda_blackwell_tuning_guide/术语表.md:40 [本章新确立(第 1 章翻译 Agent 上报,2026-08-29 中心合并)]; hopper_tuning_guide/术语表.md:50 [本文档新确立] |
| Multi-Process Service (MPS) | (产品名) | 英文 |  | cuda_best_practices_guide/术语表.md:194 [第 11–13 章(Execution Config / Instruction / Control Flow)新确立] |
| multicore | 多核 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:90 [第 5–6 章(Parallelizing / Getting Started)新确立] |
| multimem (address) | multimem 保留 | 英文 |  | ptx_isa/术语表.md:87 [数据搬运与类型(第 5 章 + 9.7.9)] |
| multiphase model of accumulation | 多阶段累加模型 | 首现中英，后文中文 |  | cublas/术语表.md:124 [2.1–2.5 总论与 Level-1(G4)] |
| multiplicand / fragment / fragment layout | 被乘数 / 片段 / 片段布局 | 首现中英，后文中文 |  | ptx_isa/术语表.md:107 [矩阵乘累加与 TensorCore(9.7.15–9.7.17)] |
| multiply-accumulate | 矩阵乘加 | 首现中英，后文中文 |  | cutile_python/术语表.md:170 [API 参考批次(箱1:Load/Store~Selection;箱2:Math~JAX FFI;2026-08-29)] |
| multiply-add | 乘加 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:62 [第 3 章(Heterogeneous Computing)新确立] |
| multiprocessor | 多处理器 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:55 [第 3 章(Heterogeneous Computing)新确立] |
| mutable / immutable | 可变 / 不可变 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:58 [Tile 编程(CUDA 13 新增)] |
| name mangling | 名字修饰 | 首现中英，后文中文 |  | cutile_python/术语表.md:130 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| named barrier / barrier synchronization | 命名屏障 / 屏障同步 | 首现中英，后文中文 |  | ptx_isa/术语表.md:61 [内存模型(第 8 章 + 9.7.14,承 PG 5.7/5.8 与 09 块)] |
| named stream | 命名流(**裁决**:5.6 Agent 初译"具名流",已统一为 4.18 既有译法) | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:462 [5.6 / 5.2 / 5.7 / 5.8 设备 API、环境变量与形式化模型] |
| NaN | NaN | 英文 |  | tile_ir/术语表.md:95 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| NaN payload / payload | NaN 载荷 | 首现中英，后文中文 |  | ptx_isa/术语表.md:144 [浮点与数值(9.7.3/9.7.4/9.7.5 + 各处)] |
| narrow precision data types | 窄精度数据类型 | 首现中英，后文中文 |  | cublas/术语表.md:91 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| native (instruction) | 原生 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:198 [第 11–13 章(Execution Config / Instruction / Control Flow)新确立] |
| native cubin | 原生 cubin | 首现中英，后文中文 |  | cuda_blackwell_compatibility_guide/术语表.md:16 [沿用基准项目既有译法(本章高频)]; hopper_compatibility_guide/术语表.md:28 [本文档新确立] |
| negative index convention | 负索引约定 | 首现中英，后文中文 |  | cutile_python/术语表.md:158 [API 参考批次(箱1:Load/Store~Selection;箱2:Math~JAX FFI;2026-08-29)] |
| NETLIB documentation | NETLIB 文档 | 英文 |  | cublas/术语表.md:152 [2.7 Level-3(G2)] |
| nibble(little-endian nibble order) | 半字节(小端半字节顺序) | 首现中英，后文中文 |  | tile_ir/术语表.md:176 [第 2/4/5/6 章(补派 Agent D,2026-08-29)] |
| No Thin Air / out of thin air | 禁止凭空值 / 凭空出现 | 首现中英，后文中文 |  | ptx_isa/术语表.md:52 [内存模型(第 8 章 + 9.7.14,承 PG 5.7/5.8 与 09 块)] |
| no-thin-air | 无凭空值(no-thin-air) | 首现中英，后文中文 |  | tile_ir/术语表.md:68 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| non- or (conj.) transpose | 非转置或(共轭)转置 | 首现中英，后文中文 |  | cublas/术语表.md:70 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| non-coherent cache / texture cache | 非一致性缓存 / 纹理缓存 | 首现中英，后文中文 |  | ptx_isa/术语表.md:86 [数据搬运与类型(第 5 章 + 9.7.9)] |
| non-generic address | 非通用地址 | 首现中英，后文中文 |  | ptx_isa/术语表.md:80 [数据搬运与类型(第 5 章 + 9.7.9)] |
| non-pivot | 无主元 | 首现中英，后文中文 |  | cublas/术语表.md:170 [2.8 类 BLAS 扩展(G3)] |
| non-unit stride | 非单位步长 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:159 [第 10 章(Memory Optimizations)新确立]; cuda_blackwell_tuning_guide/术语表.md:19 [沿用既有译法(本章高频)]; hopper_tuning_guide/术语表.md:23 [沿用既有项目译法] |
| normalization-style kernel | 归一化类 kernel | 首现中英，后文中文 |  | cutile_python/术语表.md:97 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| normalized range | 规格化范围 | 首现中英，后文中文 |  | tile_ir/术语表.md:206 [第 8 章 8.7–8.8(第三次补派 Agent,2026-08-29)] |
| NTTP (non-type template parameter) | 非类型模板参数 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:195 [Tile 编程(2.4)] |
| NUMA node | NUMA 节点 | 英文 |  | cuda_programming_guide/术语表.md:222 [启动与主机侧 API(3.1)] |
| numerator / denominator / quadrant | 分子 / 分母 / 象限 | 首现中英，后文中文 |  | cutile_python/术语表.md:176 [API 参考批次(箱1:Load/Store~Selection;箱2:Math~JAX FFI;2026-08-29)] |
| numerical accuracy / precision | 数值准确性 / 精度 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:111 [第 7 章(Getting the Right Answer)新确立] |
| nvcc / -gencode= / -arch= / arch= / code= | nvcc / -gencode= / -arch= / arch= / code= | 英文 |  | hopper_compatibility_guide/术语表.md:40 [保留不译] |
| nvcc / cudaOccupancyMaxActiveClusters / cudaFuncAttributeNonPortableClusterSizeAllowed 等 API 名 | nvcc / cudaOccupancyMaxActiveClusters / cudaFuncAttributeNonPortableClusterSizeAllowed 等 API 名 | 英文 |  | hopper_tuning_guide/术语表.md:56 [保留不译] |
| NVCC / NVRTC | 不译 | 英文 |  | cuda_programming_guide/术语表.md:96 [平台与工具链] |
| NVIDIA Driver | NVIDIA 驱动 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:83 [平台与工具链] |
| NVIDIA Management Library (NVML) | NVIDIA 管理库 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:265 [第 15–21 章(收官批次)新确立] |
| NVIDIA System Management Interface | NVIDIA 系统管理接口 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:255 [第 15–21 章(收官批次)新确立] |
| NVIDIA® CUDA® | NVIDIA® CUDA® | 英文 |  | cuda_best_practices_guide/术语表.md:285 [保留不译(产品/工具/组织名)] |
| NVIDIA® CUDA® / CUDA C++ | NVIDIA® CUDA® / CUDA C++ | 英文 |  | cuda_blackwell_tuning_guide/术语表.md:51 [保留不译(API/属性名)] |
| NVIDIA® CUDA® / Hopper / H100 / A100 / Volta / Turing / Ampere | NVIDIA® CUDA® / Hopper / H100 / A100 / Volta / Turing / Ampere | 英文 |  | hopper_tuning_guide/术语表.md:61 [保留不译] |
| NVIDIA® CUDA® / Hopper / Volta / Pascal / Ampere | NVIDIA® CUDA® / Hopper / Volta / Pascal / Ampere | 英文 |  | hopper_compatibility_guide/术语表.md:43 [保留不译] |
| NVLink C2C (Chip-to-Chip) | NVLink 芯片间互连 | 英文 |  | cuda_programming_guide/术语表.md:150 [内存(2.3、2.6)] |
| object file | 目标文件 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:26 [沿用既有项目译法(预置进分发 prompt)] |
| object file archive | 目标文件归档 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:63 [第 1-3 章] |
| occupancy | 占用率 | 首现中英，后文中文 |  | cublas/术语表.md:34 [基准承接(沿用 CUDA Programming Guide 既有译法)]; cuda_best_practices_guide/术语表.md:186 [第 11–13 章(Execution Config / Instruction / Control Flow)新确立]; cuda_best_practices_guide/术语表.md:294 [待定(已全部转正,2026-08-28 第 8–14 章定稿)]; cuda_blackwell_tuning_guide/术语表.md:11 [沿用既有译法(本章高频)]; cuda_programming_guide/术语表.md:159 [原子与同步(2.3、2.5)]; hopper_tuning_guide/术语表.md:14 [沿用既有项目译法] |
| ODR-use / trivially copyable·constructible·destructible | ODR 使用 / 可平凡复制·构造·析构 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:437 [5.3 / 5.4 语言支持与扩展(两节同词已合并)] |
| offload | 卸载 | 首现中英，后文中文 |  | cublas/术语表.md:273 [第 4 章(G8)]; cuda_best_practices_guide/术语表.md:88 [第 5–6 章(Parallelizing / Getting Started)新确立] |
| offset in number of elements | 以元素数计的偏移量 | 首现中英，后文中文 |  | cublas/术语表.md:145 [2.6 Level-2(G1)] |
| one-sided synchronization | 单侧同步 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:342 [4.4 / 4.9 / 4.10 / 4.12 / 4.14 执行与同步] |
| one-time cost | 一次性开销 | 首现中英，后文中文 |  | hopper_compatibility_guide/术语表.md:34 [本文档新确立] |
| one-way synchronization / fused copy and fence | 单向同步 / 融合复制与栅栏的操作 | 首现中英，后文中文 |  | ptx_isa/术语表.md:197 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| onion layer model / baseline feature set | 洋葱层模型 / 基线特性集 | 首现中英，后文中文 |  | ptx_isa/术语表.md:185 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| OOB NaN / Out Of Bounds modifier | OOB NaN 保留 / 越界修饰符 | 首现中英，后文英文 |  | ptx_isa/术语表.md:155 [浮点与数值(9.7.3/9.7.4/9.7.5 + 各处)] |
| opaque handle | 不透明句柄 | 首现中英，后文中文 |  | cublas/术语表.md:30 [基准承接(沿用 CUDA Programming Guide 既有译法)]; cuda_programming_guide/术语表.md:262 [驱动 API 与多 GPU(3.3–3.4)] |
| opcode | 操作码(opcode) | 首现中英，后文中文 |  | tile_ir/术语表.md:63 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| OpenACC | (标准名) | 英文 |  | cuda_best_practices_guide/术语表.md:93 [第 5–6 章(Parallelizing / Getting Started)新确立] |
| OpenCL / Khronos Group Inc. | OpenCL / Khronos Group Inc. | 英文 |  | hopper_compatibility_guide/术语表.md:44 [保留不译] |
| operand cost / amortized cost | 操作数开销 / 摊销成本 | 首现中英，后文中文 |  | ptx_isa/术语表.md:213 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| Operands / Qualifiers / Conditions | 操作数 / 限定符 / 条件 | 首现中英，后文中文 |  | ptx_isa/术语表.md:239 [结构标签与版本说明(第 9/11/13 章固定短语)] |
| opt in | 选择启用 | 首现中英，后文中文 |  | cuda_blackwell_tuning_guide/术语表.md:23 [沿用既有译法(本章高频)] |
| opt-in | 选择启用 | 首现中英，后文中文 |  | cuda_blackwell_compatibility_guide/术语表.md:36 [本章新确立(第 1 章翻译 Agent 上报,2026-08-29 中心合并)]; hopper_compatibility_guide/术语表.md:31 [本文档新确立]; hopper_tuning_guide/术语表.md:40 [本文档新确立] |
| optimization hint | 优化提示 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:191 [Tile 编程(2.4)] |
| optimization pass / inlining | 优化遍(pass)/ 内联 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:83 [第 4 章(选项描述正文术语;选项名本身不译)] |
| optimizer constant bank | 优化器常量 bank | 英文 |  | cuda_compiler_driver_nvcc/术语表.md:105 [第 4 章(选项描述正文术语;选项名本身不译)] |
| optimizing backend compiler | 优化后端编译器 | 首现中英，后文中文 |  | ptx_isa/术语表.md:183 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| order of magnitude | 数量级 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:270 [第 15–21 章(收官批次)新确立] |
| ordered / unordered comparison | 有序 / 无序比较 | 首现中英，后文中文 |  | ptx_isa/术语表.md:151 [浮点与数值(9.7.3/9.7.4/9.7.5 + 各处)] |
| origin stream / captured event | 源流 / 被捕获事件 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:306 [4.2 CUDA Graphs] |
| out of bounds | 越界 | 首现中英，后文中文 |  | cublas/术语表.md:258 [第 1 章与 3.1–3.2(G7)] |
| out-of-core | 核外 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:295 [4.1 统一内存] |
| outer product / dot product | 外积 / 点积 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:167 [第 10 章(Memory Optimizations)新确立] |
| outer vector scaling | 外向量缩放 | 首现中英，后文中文 |  | cublas/术语表.md:88 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| output slot / in-place update / static argument | 输出槽位 / 就地更新 / 静态参数 | 首现中英，后文中文 |  | cutile_python/术语表.md:185 [API 参考批次(箱1:Load/Store~Selection;箱2:Math~JAX FFI;2026-08-29)] |
| over-fetch | 多取(over-fetch) | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:160 [第 10 章(Memory Optimizations)新确立] |
| overdetermined system | 超定方程组 | 首现中英，后文中文 |  | cublas/术语表.md:176 [2.8 类 BLAS 扩展(G3)] |
| overflow | 溢出 | 首现中英，后文中文 |  | tile_ir/术语表.md:94 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| overflow / underflow | 上溢 / 下溢 | 首现中英，后文中文 |  | cublas/术语表.md:53 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| overlap (data transfers with computation) | 重叠 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:128 [第 8–9、14 章(Optimizing / Performance Metrics / Deploying)新确立] |
| oversubscription | 超量分配 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:146 [内存(2.3、2.6)] |
| oversubscription(任务槽语境) | 过度订阅(内存语境编程指南作"超量分配",语境并存) | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:90 [第 4 章(选项描述正文术语;选项名本身不译)] |
| Ozaki Scheme | Ozaki 方案 | 首现中英，后文英文 |  | cublas/术语表.md:236 [第 1 章与 3.1–3.2(G7)] |
| pack / unpack;packed data type | 打包 / 解包;打包数据类型 | 首现中英，后文中文 |  | ptx_isa/术语表.md:82 [数据搬运与类型(第 5 章 + 9.7.9)] |
| packed format | 压缩格式 | 首现中英，后文中文 |  | cublas/术语表.md:136 [2.6 Level-2(G1)] |
| packed storage | 压缩存储 | 首现中英，后文中文 |  | cublas/术语表.md:75 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| packing format / container / padding | 打包格式 / 容器 / 填充 | 首现中英，后文中文 |  | ptx_isa/术语表.md:132 [矩阵乘累加与 TensorCore(9.7.15–9.7.17)] |
| packing order | 打包顺序 | 首现中英，后文中文 |  | tile_ir/术语表.md:177 [第 2/4/5/6 章(补派 Agent D,2026-08-29)] |
| padding | 填充 | 首现中英，后文中文 |  | cusparse/术语表.md:24 [术语表]; tile_ir/术语表.md:29 [承接既有项目(本表只列本书高频承接词)] |
| padding mode / padding value | 填充模式 / 填充值 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:180 [Tile 编程(2.4)]; cutile_python/术语表.md:17 [承接既有项目(本书高频承接词)] |
| padding value | 填充值 | 首现中英，后文中文 |  | tile_ir/术语表.md:174 [第 2/4/5/6 章(补派 Agent D,2026-08-29)] |
| page fault / first touch | 缺页 / 首次触碰 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:289 [4.1 统一内存] |
| page table / PTE | 页表 / 页表项 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:290 [4.1 统一内存] |
| page-locked / pinned memory | 页锁定内存 / 固定内存 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:150 [第 10 章(Memory Optimizations)新确立]; cuda_programming_guide/术语表.md:131 [内存(2.3、2.6)] |
| parallel / concurrent forward progress | 并行前进 / 并发前进 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:471 [5.6 / 5.2 / 5.7 / 5.8 设备 API、环境变量与形式化模型] |
| parallel library | 并行库 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:79 [第 5–6 章(Parallelizing / Getting Started)新确立] |
| parallelizing compiler | 并行化编译器 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:32 [本章新确立术语] |
| partial pivoting (with row interchanges) | 部分选主元(带行交换) | 首现中英，后文中文 |  | cublas/术语表.md:168 [2.8 类 BLAS 扩展(G3)] |
| partially in-bounds | 部分在界(partially in-bounds) | 首现中英，后文中文 |  | tile_ir/术语表.md:142 [第 8 章 8.4–8.6(补译 Agent,2026-08-29)] |
| partition view / tiled view | 分区视图 / 分块视图 | 首现中英，后文中文 |  | tile_ir/术语表.md:30 [承接既有项目(本表只列本书高频承接词)] |
| Pascal scheduling model | Pascal 调度模型 | 首现中英，后文中文 |  | hopper_compatibility_guide/术语表.md:32 [本文档新确立] |
| pass through(IOMMU) | 直通 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:268 [驱动 API 与多 GPU(3.3–3.4)] |
| pass-by-value / call-by-value | 按值传递 / 按值调用 | 首现中英，后文中文 |  | ptx_isa/术语表.md:173 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| pedantic(compute/math mode) | 严苛(pedantic) | 首现中英，后文中文 |  | cublas/术语表.md:109 [2.1–2.5 总论与 Level-1(G4)] |
| peer access | 点对点访问(P2P) | 首现中英，后文中文 |  | cuda_blackwell_tuning_guide/术语表.md:24 [沿用既有译法(本章高频)] |
| peer CTA / CTA pair | 对等 CTA / CTA 对 | 首现中英，后文中文 |  | ptx_isa/术语表.md:123 [矩阵乘累加与 TensorCore(9.7.15–9.7.17)] |
| peer-to-peer (P2P) | 点对点(P2P) | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:157 [第 10 章(Memory Optimizations)新确立]; cuda_programming_guide/术语表.md:265 [驱动 API 与多 GPU(3.3–3.4)] |
| pending count / expected arrival count | 待定计数 / 预期到达计数 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:458 [5.6 / 5.2 / 5.7 / 5.8 设备 API、环境变量与形式化模型]; ptx_isa/术语表.md:57 [内存模型(第 8 章 + 9.7.14,承 PG 5.7/5.8 与 09 块)] |
| pending memory access | 待完成内存访问 | 首现中英，后文中文 |  | tile_ir/术语表.md:192 [第 2/4/5/6 章(补派 Agent D,2026-08-29)] |
| per-batch | 逐批次 | 首现中英，后文中文 |  | cublas/术语表.md:245 [第 1 章与 3.1–3.2(G7)] |
| per-file / per-kernel | 按文件级 / 按 kernel | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:273 [第 15–21 章(收官批次)新确立] |
| per-thread default stream | 每线程默认流 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:162 [原子与同步(2.3、2.5)] |
| performance hints | 性能提示 | 首现中英，后文中文 |  | cutile_python/术语表.md:51 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| performance monitor event/counter | 性能监视器事件 / 性能计数器 | 首现中英，后文中文 |  | ptx_isa/术语表.md:209 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| performance monitoring counter | 性能监视计数器 | 首现中英，后文中文 |  | ptx_isa/术语表.md:189 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| performance state (pstate) | 性能状态(pstate) | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:261 [第 15–21 章(收官批次)新确立] |
| persistence (of data in L2) | 持久性 | 首现中英，后文中文 |  | cuda_blackwell_tuning_guide/术语表.md:21 [沿用既有译法(本章高频)] |
| persistent mode | 持久化模式 | 首现中英，后文中文 |  | cutile_python/术语表.md:118 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| persisting / streaming access | 持久化访问 / 流式访问 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:163 [第 10 章(Memory Optimizations)新确立]; cuda_programming_guide/术语表.md:381 [4.7 / 4.8 / 4.13 / 4.17 / 4.20 其他] |
| phony target | 伪目标(phony target) | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:77 [第 4 章(选项描述正文术语;选项名本身不译)] |
| pinned memory | 固定内存 | 首现中英，后文中文 |  | cublas/术语表.md:28 [基准承接(沿用 CUDA Programming Guide 既有译法)]; cuda_best_practices_guide/术语表.md:292 [待定(已全部转正,2026-08-28 第 8–14 章定稿)] |
| pinning / unpinning | 固定 / 解除固定 | 首现中英，后文中文 |  | cublas/术语表.md:276 [第 4 章(G8)] |
| pipeline | 流水线 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:250 [硬件模型与执行(3.2)] |
| pipeline depth | 流水线深度 | 首现中英，后文中文 |  | cublas/术语表.md:206 [3.3 cuBLASLt 数据类型参考(G5)] |
| pipelined / blocking instruction | 流水线化的 / 阻塞指令 | 首现中英，后文中文 |  | ptx_isa/术语表.md:125 [矩阵乘累加与 TensorCore(9.7.15–9.7.17)] |
| pivoting sequence | 主元序列 | 首现中英，后文中文 |  | cublas/术语表.md:169 [2.8 类 BLAS 扩展(G3)] |
| plan(FFTW 式计划) | 计划 | 首现中英，后文中文 |  | cublas/术语表.md:44 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| planar-complex | 平面复数 | 首现中英，后文中文 |  | cublas/术语表.md:210 [3.3 cuBLASLt 数据类型参考(G5)] |
| point of coherency | 一致性点 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:245 [硬件模型与执行(3.2)] |
| point-wise transform | 逐点变换 | 首现中英，后文中文 |  | cublas/术语表.md:190 [3.3 cuBLASLt 数据类型参考(G5)] |
| pointee type | 被指向类型 | 首现中英，后文中文 |  | tile_ir/术语表.md:157 [第 8 章 8.9–8.12 + 第 12 章附录(Agent C,2026-08-29)]; tile_ir/术语表.md:175 [第 2/4/5/6 章(补派 Agent D,2026-08-29)] |
| pointer mode | 指针模式 | 首现中英，后文中文 |  | cublas/术语表.md:67 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| pointer provenance | 指针来源(pointer provenance) | 首现中英，后文中文 |  | tile_ir/术语表.md:131 [第 8 章 8.4–8.6(补译 Agent,2026-08-29)] |
| polling | 轮询 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:170 [原子与同步(2.3、2.5)] |
| polling loop | 轮询循环 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:228 [启动与主机侧 API(3.1)] |
| population count / leading zeros | 置位计数 / 前导零 | 首现中英，后文中文 |  | ptx_isa/术语表.md:165 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| portable / nonportable cluster size | 可移植 / 不可移植集群尺寸 | 首现中英，后文中文 |  | cuda_blackwell_tuning_guide/术语表.md:22 [沿用既有译法(本章高频)]; hopper_tuning_guide/术语表.md:39 [本文档新确立] |
| position-independent code | 位置无关代码 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:106 [第 4 章(选项描述正文术语;选项名本身不译)] |
| post-increment | 后增量 | 首现中英，后文中文 |  | cutile_python/术语表.md:122 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| power draw / power limit | 功耗 / 功率限制 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:262 [第 15–21 章(收官批次)新确立] |
| power of two | 2 的幂 | 首现中英，后文中文 |  | cutile_python/术语表.md:164 [API 参考批次(箱1:Load/Store~Selection;箱2:Math~JAX FFI;2026-08-29)] |
| pragma | pragma 指令 | 英文 |  | cuda_best_practices_guide/术语表.md:87 [第 5–6 章(Parallelizing / Getting Started)新确立] |
| preamble / launch latency | 前导部分 / 启动延迟 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:368 [4.5 / 4.6 PDL 与绿色上下文] |
| predicate | 谓词(predicate) | 首现中英，后文中文 |  | tile_ir/术语表.md:93 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| predicate / guard predicate | 谓词 / 守护谓词 | 首现中英，后文中文 |  | ptx_isa/术语表.md:15 [核心概念(预置进分发规则,全书沿用)] |
| predicate(指令语境) | 谓词 | 首现中英，后文中文 |  | hopper_tuning_guide/术语表.md:41 [本文档新确立] |
| predicated execution | 谓词执行 | 首现中英，后文中文 |  | ptx_isa/术语表.md:16 [核心概念(预置进分发规则,全书沿用)] |
| predication | 谓词执行 / 分支谓词执行 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:296 [待定(已全部转正,2026-08-28 第 8–14 章定稿)] |
| predication / branch predication | 谓词执行 / 分支谓词执行 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:208 [第 11–13 章(Execution Config / Instruction / Control Flow)新确立] |
| preemption / low-tail effect | 抢占 / 低尾效应 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:345 [4.4 / 4.9 / 4.10 / 4.12 / 4.14 执行与同步] |
| preference | 偏好设置 | 首现中英，后文中文 |  | cublas/术语表.md:85 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| prefetch | 预取 | 首现中英，后文中文 |  | cublas/术语表.md:35 [基准承接(沿用 CUDA Programming Guide 既有译法)]; cuda_programming_guide/术语表.md:147 [内存(2.3、2.6)] |
| prefetch depth | 预取深度 | 首现中英，后文中文 |  | cutile_python/术语表.md:114 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| PrefixVarInt / LEB128 | 不译 | 英文 |  | tile_ir/术语表.md:180 [第 2/4/5/6 章(补派 Agent D,2026-08-29)] |
| premature optimization | 过早优化 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:35 [本章新确立术语] |
| preprocessor directive | 预处理指令 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:33 [本章新确立术语] |
| preprocessor directive | 预处理伪指令 | 首现中英，后文中文 | PTX 源码语法 | ptx_isa/术语表.md:220 [语法与源码格式(第 4 章)] |
| primary / secondary kernel | 主 kernel / 次 kernel | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:223 [启动与主机侧 API(3.1)] |
| primary / secondary process | 主进程 / 次进程 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:402 [4.15 / 4.19 互操作] |
| primary / trailing / preceding secondary range | 主范围 / 尾随次范围 / 前导次范围 | 首现中英，后文中文 |  | ptx_isa/术语表.md:77 [数据搬运与类型(第 5 章 + 9.7.9)] |
| primary context | 主上下文(primary context) | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:192 [第 11–13 章(Execution Config / Instruction / Control Flow)新确立] |
| principal value | 主值 | 首现中英，后文中文 |  | tile_ir/术语表.md:201 [第 8 章 8.7–8.8(第三次补派 Agent,2026-08-29)] |
| priority | 优先级 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:41 [本章新确立术语] |
| problem size | 问题规模 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:71 [第 4 章(Application Profiling)新确立] |
| processing pipeline | 处理流水线 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:134 [第 8–9、14 章(Optimizing / Performance Metrics / Deploying)新确立] |
| producer / consumer | 生产者 / 消费者 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:251 [硬件模型与执行(3.2)] |
| producer/consumer model | 生产者/消费者模型 | 首现中英，后文中文 |  | ptx_isa/术语表.md:66 [内存模型(第 8 章 + 9.7.14,承 PG 5.7/5.8 与 09 块)] |
| production | 生产(环境) | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:36 [本章新确立术语] |
| production mode | 生产模式 | 首现中英，后文中文 |  | tile_ir/术语表.md:162 [第 8 章 8.9–8.12 + 第 12 章附录(Agent C,2026-08-29)] |
| profiling | 性能分析 | 首现中英，后文中文 |  | cutile_python/术语表.md:110 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| profiling / profiler | 性能分析(profiling)/ 性能分析器(profiler) | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:23 [本章新确立术语] |
| program ordered / token ordered | 程序序 / 令牌序 | 首现中英，后文中文 |  | tile_ir/术语表.md:185 [第 2/4/5/6 章(补派 Agent D,2026-08-29)] |
| programmatic dependent kernel launch | 程序化依赖 kernel 启动 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:171 [原子与同步(2.3、2.5)] |
| prologue(工作窃取语境) | 前导代码 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:347 [4.4 / 4.9 / 4.10 / 4.12 / 4.14 执行与同步] |
| provision / time-slicing | 预配 / 时间切片 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:371 [4.5 / 4.6 PDL 与绿色上下文] |
| proxy fence | 代理栅栏 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:244 [硬件模型与执行(3.2)] |
| proxy object | 代理(proxy)对象 | 首现中英，后文中文 |  | cutile_python/术语表.md:180 [API 参考批次(箱1:Load/Store~Selection;箱2:Math~JAX FFI;2026-08-29)] |
| proxy-preserved base causality order | 代理保持基础因果顺序 | 首现中英，后文中文 |  | ptx_isa/术语表.md:38 [内存模型(第 8 章 + 9.7.14,承 PG 5.7/5.8 与 09 块)] |
| prune / pruning | 修剪 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:95 [第 4 章(选项描述正文术语;选项名本身不译)] |
| pseudo-operation | 伪操作 | 首现中英，后文中文 |  | ptx_isa/术语表.md:223 [语法与源码格式(第 4 章)] |
| PTX (Parallel Thread Execution) | 并行线程执行(PTX),后文 PTX | 首现中英，后文英文 |  | cuda_programming_guide/术语表.md:86 [平台与工具链]; ptx_isa/术语表.md:12 [核心概念(预置进分发规则,全书沿用)] |
| PTX / cubin / fatbin | 不译 | 英文 |  | cublas/术语表.md:33 [基准承接(沿用 CUDA Programming Guide 既有译法)]; tile_ir/术语表.md:25 [承接既有项目(本表只列本书高频承接词)] |
| PTX compatibility | PTX 兼容性 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:92 [平台与工具链] |
| PTX ISA Notes / Target ISA Notes | PTX ISA 备注 / 目标 ISA 备注 | 首现中英，后文中文 |  | ptx_isa/术语表.md:234 [结构标签与版本说明(第 9/11/13 章固定短语)] |
| ptxas / NVRTC / nvrtc | 不译 | 英文 |  | cuda_programming_guide/术语表.md:211 [编译器(2.7)] |
| pull-reduction / partial completion / counted completion | 拉取归约 / 部分完成机制 / 计数完成 | 首现中英，后文中文 |  | ptx_isa/术语表.md:195 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| Python subset | Python 子集 | 首现中英，后文中文 |  | cutile_python/术语表.md:45 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| quantization | 量化 | 首现中英，后文中文 |  | cublas/术语表.md:90 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| Queryable / Modifiable state | 可查询 / 可修改状态(节名保留原文) | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:257 [第 15–21 章(收官批次)新确立] |
| quiet / signaling NaN | 静默 NaN / 信令 NaN | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:416 [5.1 / 5.5 计算能力与浮点] |
| race condition / memory hazard | 数据竞争 / 内存冒险 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:142 [内存(2.3、2.6)] |
| race condition / non-aliasing | 竞争条件 / 互不别名 | 首现中英，后文中文 |  | tile_ir/术语表.md:189 [第 2/4/5/6 章(补派 Agent D,2026-08-29)] |
| range-based / fraction-based policy | 基于范围的 / 基于比例的策略 | 首现中英，后文中文 |  | ptx_isa/术语表.md:76 [数据搬运与类型(第 5 章 + 9.7.9)] |
| rank | 秩 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:183 [Tile 编程(2.4)]; tile_ir/术语表.md:154 [第 8 章 8.9–8.12 + 第 12 章附录(Agent C,2026-08-29)] |
| rank-1 / rank-2 update | 秩 1 / 秩 2 更新 | 首现中英，后文中文 |  | cublas/术语表.md:138 [2.6 Level-2(G1)] |
| rank-k / rank-2k update | 秩-k / 秩-2k 更新【裁决:02d 英文"rank-k"已统一】 | 首现中英，后文中文 |  | cublas/术语表.md:157 [2.7 Level-3(G2)] |
| rapid prototyping | 快速原型开发 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:84 [第 5–6 章(Parallelizing / Getting Started)新确立] |
| re-converge / divergent point | 重新收敛 / 分歧点 | 首现中英，后文中文 |  | ptx_isa/术语表.md:172 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| read-after-write dependency | 先写后读(read-after-write)依赖 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:177 [第 10 章(Memory Optimizations)新确立] |
| read-after-write 等 hazard | 写后读 / 读后写 / 写后写冒险 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:440 [5.3 / 5.4 语言支持与扩展(两节同词已合并)] |
| read-modify-write | 读-改-写 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:157 [原子与同步(2.3、2.5)]; tile_ir/术语表.md:149 [第 8 章 8.9–8.12 + 第 12 章附录(Agent C,2026-08-29)] |
| rebuild | 重新构建 | 首现中英，后文中文 |  | cuda_blackwell_compatibility_guide/术语表.md:39 [本章新确立(第 1 章翻译 Agent 上报,2026-08-29 中心合并)] |
| rebuild / recompile | 重新构建 | 首现中英，后文中文 |  | hopper_compatibility_guide/术语表.md:20 [沿用既有项目译法] |
| reciprocal square root | 倒数平方根 | 首现中英，后文中文 |  | tile_ir/术语表.md:212 [第 8 章 8.7–8.8(第三次补派 Agent,2026-08-29)] |
| reconverge | 重新收敛 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:210 [第 11–13 章(Execution Config / Instruction / Control Flow)新确立] |
| redistribution / redistribute | 再分发 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:249 [第 15–21 章(收官批次)新确立] |
| reduced precision reduction | 降精度归约 | 首现中英，后文中文 |  | cublas/术语表.md:80 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| reduction | 归约 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:62 [Tile 编程(CUDA 13 新增)] |
| reduction / scan | 归约 / 扫描 | 首现中英，后文中文 |  | cutile_python/术语表.md:20 [承接既有项目(本书高频承接词)] |
| reduction buffer | 归约缓冲区 | 首现中英，后文中文 |  | cublas/术语表.md:121 [2.1–2.5 总论与 Level-1(G4)] |
| reduction scheme | 归约方案 | 首现中英，后文中文 |  | cublas/术语表.md:93 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| reentrant | 可重入 | 首现中英，后文中文 |  | cublas/术语表.md:46 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| refactoring | 重构 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:34 [本章新确立术语] |
| reference comparison | 参考结果比对 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:101 [第 7 章(Getting the Right Answer)新确立] |
| register / unregister(资源) | 注册 / 注销 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:394 [4.15 / 4.19 互操作] |
| register dependency | 寄存器依赖 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:187 [第 11–13 章(Execution Config / Instruction / Control Flow)新确立] |
| register dependency / anti-dependency hazard | 寄存器依赖 / 反依赖冒险 | 首现中英，后文中文 |  | ptx_isa/术语表.md:126 [矩阵乘累加与 TensorCore(9.7.15–9.7.17)] |
| register file | 寄存器堆 | 首现中英，后文中文 |  | cuda_blackwell_tuning_guide/术语表.md:16 [沿用既有译法(本章高频)]; cuda_programming_guide/术语表.md:31 [硬件]; hopper_tuning_guide/术语表.md:24 [沿用既有项目译法]; tile_ir/术语表.md:17 [承接既有项目(本表只列本书高频承接词)] |
| register pool / setmaxnreg 语境 | 寄存器池 | 首现中英，后文中文 |  | ptx_isa/术语表.md:208 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| register pressure | 寄存器压力 | 首现中英，后文中文 |  | cutile_python/术语表.md:96 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| register spilling | 寄存器溢出 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:138 [内存(2.3、2.6)] |
| relaxed | 松弛语义 | 首现中英，后文中文 |  | ptx_isa/术语表.md:41 [内存模型(第 8 章 + 9.7.14,承 PG 5.7/5.8 与 09 块)] |
| relaxed / acquire / release | 松弛(relaxed)/ 获取 / 释放 | 首现中英，后文中文 |  | cutile_python/术语表.md:14 [承接既有项目(本书高频承接词)] |
| relaxed memory ordering | 松弛(relaxed)内存顺序 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:463 [5.6 / 5.2 / 5.7 / 5.8 设备 API、环境变量与形式化模型] |
| release cadence | 发布节奏 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:222 [第 15–21 章(收官批次)新确立] |
| release-acquire pattern | 释放-获取模式 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:361 [4.11 异步数据复制] |
| release/acquire fence / release sequence | 释放栅栏 / 获取栅栏 / 释放序列 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:467 [5.6 / 5.2 / 5.7 / 5.8 设备 API、环境变量与形式化模型] |
| release/acquire sequence | 释放序列 / 获取序列 | 首现中英，后文中文 |  | ptx_isa/术语表.md:63 [内存模型(第 8 章 + 9.7.14,承 PG 5.7/5.8 与 09 块)] |
| relocatable device code | 可重定位设备代码 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:20 [沿用既有项目译法(预置进分发 prompt)] |
| relocatable link | 可重定位链接 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:133 [第 6、8 章] |
| relocatable object | 可重定位对象 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:238 [第 15–21 章(收官批次)新确立] |
| relocation truncation error | 重定位截断错误 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:85 [第 4 章(选项描述正文术语;选项名本身不译)] |
| remark | 备注(remark) | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:82 [第 4 章(选项描述正文术语;选项名本身不译)] |
| remote SPMD procedure calling | 远程 SPMD 过程调用 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:47 [第 1-3 章] |
| report predicate / report value / report-on | 报告谓词 / 报告值 / 报告(report-on)操作 | 首现中英，后文中文 |  | ptx_isa/术语表.md:65 [内存模型(第 8 章 + 9.7.14,承 PG 5.7/5.8 与 09 块)] |
| Requires sm_XX or higher | 要求 sm_XX 或更高 | 首现中英，后文中文 |  | ptx_isa/术语表.md:237 [结构标签与版本说明(第 9/11/13 章固定短语)] |
| reserved shared memory region | 预留共享内存区域 | 首现中英，后文中文 |  | ptx_isa/术语表.md:191 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| reshape / transpose | reshape / transpose | 英文 |  | cuda_programming_guide/术语表.md:63 [Tile 编程(CUDA 13 新增)] |
| resolution(计时器语境) | 分辨率(resolution) | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:135 [第 8–9、14 章(Optimizing / Performance Metrics / Deploying)新确立] |
| resource descriptor / bitmask | 资源描述符 / 位掩码 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:373 [4.5 / 4.6 PDL 与绿色上下文] |
| restricted float dtype | 受限浮点 dtype | 首现中英，后文中文 |  | cutile_python/术语表.md:147 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| restricted pointer | 受限指针(restricted pointer) | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:197 [第 11–13 章(Execution Config / Instruction / Control Flow)新确立] |
| restricted pointer / pointer aliasing | 受限指针 / 指针别名 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:429 [5.3 / 5.4 语言支持与扩展(两节同词已合并)] |
| results reproducibility | 结果可复现性 | 首现中英，后文中文 |  | cublas/术语表.md:62 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| right-hand side | 右端项 | 首现中英，后文中文 |  | cublas/术语表.md:140 [2.6 Level-2(G1)] |
| RNE | RNE(就近舍入到偶数) | 英文 |  | cublas/术语表.md:253 [第 1 章与 3.1–3.2(G7)] |
| robustness | 健壮性 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:85 [第 5–6 章(Parallelizing / Getting Started)新确立] |
| root complex | 根复合体 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:269 [驱动 API 与多 GPU(3.3–3.4)] |
| round robin | 轮转(round robin) | 首现中英，后文中文 |  | cublas/术语表.md:269 [第 4 章(G8)] |
| round to nearest even | 舍入到最近偶数 | 首现中英，后文中文 |  | cublas/术语表.md:110 [2.1–2.5 总论与 Level-1(G4)] |
| round-to-nearest / ties-to-even | 最近舍入 / 就近偶数(平局取偶) | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:410 [5.1 / 5.5 计算能力与浮点] |
| rounding | 舍入 | 首现中英，后文中文 |  | cublas/术语表.md:23 [基准承接(沿用 CUDA Programming Guide 既有译法)]; cuda_best_practices_guide/术语表.md:113 [第 7 章(Getting the Right Answer)新确立] |
| rounding mode | 舍入模式 | 首现中英，后文中文 |  | cutile_python/术语表.md:16 [承接既有项目(本书高频承接词)]; tile_ir/术语表.md:34 [承接既有项目(本表只列本书高频承接词)] |
| rounding modifier / round-to-nearest-even | 舍入修饰符 / 就近舍入到偶数 | 首现中英，后文中文 |  | ptx_isa/术语表.md:139 [浮点与数值(9.7.3/9.7.4/9.7.5 + 各处)] |
| routine | 例程 | 首现中英，后文中文 |  | cublas/术语表.md:97 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| row / column broadcast | 行 / 列广播 | 首现中英，后文中文 |  | cublas/术语表.md:222 [3.4 cuBLASLt API 参考(G6)] |
| row-major | 行主序 | 首现中英，后文中文 |  | cusparse/术语表.md:21 [术语表] |
| row-major / column-major | 行主序 / 列主序 | 首现中英，后文中文 |  | cublas/术语表.md:20 [基准承接(沿用 CUDA Programming Guide 既有译法)]; cutile_python/术语表.md:103 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| row-major order | 行主序 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:140 [内存(2.3、2.6)] |
| RTTI / polymorphic class / closure type | 运行时类型信息 / 多态类 / 闭包类型 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:435 [5.3 / 5.4 语言支持与扩展(两节同词已合并)] |
| run phase | 运行阶段 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:51 [第 1-3 章] |
| run-to-run | 逐次运行 | 首现中英，后文中文 |  | cublas/术语表.md:63 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| runtime library | 运行时库 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:248 [第 15–21 章(收官批次)新确立] |
| SASS / ISA / ptxjitcompiler / NVRTC | (架构/库名) | 英文 |  | cuda_best_practices_guide/术语表.md:239 [第 15–21 章(收官批次)新确立] |
| satfinite / FTZ | 饱和到有限值 / FTZ(清零) | 首现中英，后文中文 |  | tile_ir/术语表.md:178 [第 2/4/5/6 章(补派 Agent D,2026-08-29)] |
| saturation / satfinite | 饱和 / 饱和到有限值 | 首现中英，后文中文 |  | ptx_isa/术语表.md:140 [浮点与数值(9.7.3/9.7.4/9.7.5 + 各处)] |
| saturation / saturating | 饱和 | 首现中英，后文中文 |  | tile_ir/术语表.md:74 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| saturation arithmetic / flush-to-zero | 饱和算术 / 清零(FTZ) | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:415 [5.1 / 5.5 计算能力与浮点] |
| scalar | 标量 | 首现中英，后文中文 |  | cutile_python/术语表.md:31 [承接既有项目(本书高频承接词)] |
| scalar / SIMD video instructions | 标量 / SIMD 视频指令 | 首现中英，后文中文 |  | ptx_isa/术语表.md:204 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| scalar parameters | 标量参数 | 首现中英，后文中文 |  | cublas/术语表.md:64 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| scale / scaled type | 缩放 / 缩放类型(scaled) | 首现中英，后文中文 |  | tile_ir/术语表.md:75 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| scale factor | 缩放因子 | 首现中英，后文中文 |  | tile_ir/术语表.md:209 [第 8 章 8.7–8.8(第三次补派 Agent,2026-08-29)] |
| scale factor / block scaling / scale matrix metadata | 缩放因子 / 块缩放 / 缩放矩阵元数据 | 首现中英，后文中文 |  | ptx_isa/术语表.md:114 [矩阵乘累加与 TensorCore(9.7.15–9.7.17)] |
| scaled block | 缩放块 | 首现中英，后文中文 |  | cublas/术语表.md:250 [第 1 章与 3.1–3.2(G7)] |
| scaled form | 经缩放后的形式 | 首现中英，后文中文 |  | cublas/术语表.md:158 [2.7 Level-3(G2)] |
| scaling factor | 缩放因子 | 首现中英，后文中文 |  | cublas/术语表.md:86 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| scaling mode | 缩放模式 | 首现中英，后文中文 |  | cublas/术语表.md:198 [3.3 cuBLASLt 数据类型参考(G5)] |
| scan / prefix-sum | 扫描 / 前缀和 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:186 [Tile 编程(2.4)] |
| scan / sort / reduce | 扫描(scan)/ 排序 / 归约 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:83 [第 5–6 章(Parallelizing / Getting Started)新确立] |
| scattered writes | 分散写(scattered writes) | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:142 [第 8–9、14 章(Optimizing / Performance Metrics / Deploying)新确立] |
| scheduling model | 调度模型 | 首现中英，后文中文 |  | cuda_blackwell_compatibility_guide/术语表.md:35 [本章新确立(第 1 章翻译 Agent 上报,2026-08-29 中心合并)] |
| scope | 作用域(.gpu/.sys 等保留) | 首现中英，后文中文 |  | ptx_isa/术语表.md:42 [内存模型(第 8 章 + 9.7.14,承 PG 5.7/5.8 与 09 块)] |
| scope / thread scope | 作用域 / 线程作用域 | 首现中英，后文中文 |  | tile_ir/术语表.md:20 [承接既有项目(本表只列本书高频承接词)] |
| scope metadata | 作用域元数据 | 首现中英，后文中文 |  | tile_ir/术语表.md:84 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| scoped atomics | 带作用域的原子操作 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:248 [硬件模型与执行(3.2)] |
| scratch memory | 暂存内存(PG 的 scratchpad 为"暂存区") | 首现中英，后文中文 |  | cublas/术语表.md:139 [2.6 Level-2(G1)] |
| scratchpad | 暂存区 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:139 [内存(2.3、2.6)] |
| search mode | 搜索模式 | 首现中英，后文中文 |  | cublas/术语表.md:203 [3.3 cuBLASLt 数据类型参考(G5)] |
| search space | 搜索空间 | 首现中英，后文中文 |  | cutile_python/术语表.md:116 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| secondary bus reset | 二次总线复位 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:264 [第 15–21 章(收官批次)新确立] |
| secondary operation / plus one mode | 第二操作 / 加一模式 | 首现中英，后文中文 |  | ptx_isa/术语表.md:206 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| section(二进制格式) | 节(section) | 首现中英，后文中文 |  | tile_ir/术语表.md:65 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| self-contained | 自包含 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:43 [第 1-3 章] |
| semantic versioning | 语义化版本 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:227 [第 15–21 章(收官批次)新确立] |
| semaphore / timeline semaphore | 信号量 / 时间线信号量 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:399 [4.15 / 4.19 互操作] |
| separate compilation | 分离编译 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:18 [沿用既有项目译法(预置进分发 prompt)]; cuda_programming_guide/术语表.md:205 [编译器(2.7)] |
| sequenced before / program order | 顺序先于 / 程序顺序 | 首现中英，后文中文 |  | ptx_isa/术语表.md:33 [内存模型(第 8 章 + 9.7.14,承 PG 5.7/5.8 与 09 块)] |
| sequentially consistent | 顺序一致 | 首现中英，后文中文 |  | ptx_isa/术语表.md:54 [内存模型(第 8 章 + 9.7.14,承 PG 5.7/5.8 与 09 块)] |
| serial code / coarse-grained / fine-grained | 串行代码 / 粗粒度 / 细粒度 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:38 [本章新确立术语] |
| serializer / deserializer | 序列化器 / 反序列化器 | 首现中英，后文中文 |  | tile_ir/术语表.md:182 [第 2/4/5/6 章(补派 Agent D,2026-08-29)] |
| serializing behavior | 串行化(serializing)行为 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:132 [第 8–9、14 章(Optimizing / Performance Metrics / Deploying)新确立] |
| set-aside | 预留 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:161 [第 10 章(Memory Optimizations)新确立]; cuda_programming_guide/术语表.md:382 [4.7 / 4.8 / 4.13 / 4.17 / 4.20 其他] |
| shape / row-major / column-major | 形状 / 行主序 / 列主序 | 首现中英，后文中文 |  | ptx_isa/术语表.md:109 [矩阵乘累加与 TensorCore(9.7.15–9.7.17)] |
| shape / stride | 形状 / 步长 | 首现中英，后文中文 |  | tile_ir/术语表.md:89 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| shared memory | 共享内存 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:70 [内存] |
| shared memory bank | 共享内存 bank | 英文 |  | cuda_programming_guide/术语表.md:49 [执行模型] |
| shared object file | 共享目标文件 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:62 [第 1-3 章] |
| short2 / half2 / int / FP32 | short2 / half2 / int / FP32 | 英文 |  | hopper_tuning_guide/术语表.md:60 [保留不译] |
| shorthand | 简写形式 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:122 [第 5、7 章]; hopper_compatibility_guide/术语表.md:30 [本文档新确立] |
| shuffle / permute | shuffle 保留 / 置换 | 英文 |  | ptx_isa/术语表.md:84 [数据搬运与类型(第 5 章 + 9.7.9)] |
| sign-extend / zero-extend | 符号扩展 / 零扩展 | 首现中英，后文中文 |  | ptx_isa/术语表.md:167 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| sign-preserving zero | 保留符号的零 | 首现中英，后文中文 |  | ptx_isa/术语表.md:145 [浮点与数值(9.7.3/9.7.4/9.7.5 + 各处)] |
| signed zero | 带符号零 | 首现中英，后文中文 |  | cublas/术语表.md:240 [第 1 章与 3.1–3.2(G7)] |
| signedness | 符号性 | 首现中英，后文中文 |  | tile_ir/术语表.md:200 [第 8 章 8.7–8.8(第三次补派 Agent,2026-08-29)] |
| significand / mantissa / fraction | 有效数字 / 尾数 / 小数部分 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:412 [5.1 / 5.5 计算能力与浮点] |
| signless | 无符号性(signless) | 首现中英，后文中文 |  | tile_ir/术语表.md:72 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| silent cast / automatic conversion | 静默转换 / 自动转换 | 首现中英，后文中文 |  | ptx_isa/术语表.md:211 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| SIMD (Single Instruction Multiple Data) | 单指令多数据 | 首现中英，后文英文 |  | cuda_programming_guide/术语表.md:44 [执行模型] |
| SIMT | 单指令多线程(SIMT) | 首现中英，后文英文 |  | ptx_isa/术语表.md:22 [核心概念(预置进分发规则,全书沿用)]; tile_ir/术语表.md:23 [承接既有项目(本表只列本书高频承接词)] |
| SIMT (single instruction multiple thread) | SIMT(单指令多线程) | 英文 |  | cuda_best_practices_guide/术语表.md:271 [第 15–21 章(收官批次)新确立] |
| SIMT (Single-Instruction Multiple-Threads) | 单指令多线程 | 首现中英，后文英文 |  | cuda_programming_guide/术语表.md:43 [执行模型] |
| simultaneous multithreading | 同时多线程 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:50 [第 3 章(Heterogeneous Computing)新确立] |
| single / double precision | 单精度 / 双精度 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:112 [第 7 章(Getting the Right Answer)新确立] |
| single-bit / set bits / element-wise multiplication | 单比特 / 置位 / 逐元素乘法 | 首现中英，后文中文 |  | ptx_isa/术语表.md:118 [矩阵乘累加与 TensorCore(9.7.15–9.7.17)] |
| singleton dimension | 单元素维度 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:182 [Tile 编程(2.4)] |
| singularity / near-singularity | 奇异性 / 近奇异性 | 首现中英，后文中文 |  | cublas/术语表.md:141 [2.6 Level-2(G1)] |
| sink node | 汇点节点 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:307 [4.2 CUDA Graphs] |
| sink symbol / bit bucket | 下沉符号(sink symbol)/ 位桶 | 首现中英，后文中文 |  | ptx_isa/术语表.md:83 [数据搬运与类型(第 5 章 + 9.7.9)] |
| SLI | 可伸缩链接互连(SLI) | 首现中英，后文英文 |  | cuda_programming_guide/术语表.md:397 [4.15 / 4.19 互操作] |
| slice | slice | 英文 |  | cusparse/术语表.md:25 [术语表] |
| slice(定点表示) | 切片 | 首现中英，后文中文 |  | cublas/术语表.md:238 [第 1 章与 3.1–3.2(G7)] |
| SM (Streaming Multiprocessor) | 流式多处理器(SM),后文 SM | 首现中英，后文英文 |  | cublas/术语表.md:16 [基准承接(沿用 CUDA Programming Guide 既有译法)] |
| SM count target | SM 数量目标 | 首现中英，后文中文 |  | cublas/术语表.md:120 [2.1–2.5 总论与 Level-1(G4)] |
| sm90 / sm10x / sm12x 等架构代号 | 不译 | 英文 |  | cublas/术语表.md:100 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| sm_86 / compute_80 等版本号 | 不译 | 英文 |  | cuda_programming_guide/术语表.md:100 [平台与工具链] |
| sm_90 / sm_100 / sm_120 等架构名 | 不译 | 英文 |  | tile_ir/术语表.md:41 [承接既有项目(本表只列本书高频承接词)] |
| sm_XX / compute_XX(sm_90a、compute_90a 等) | sm_XX / compute_XX(sm_90a、compute_90a 等) | 英文 |  | hopper_compatibility_guide/术语表.md:41 [保留不译] |
| Smith-Waterman | Smith-Waterman | 英文 |  | hopper_tuning_guide/术语表.md:62 [保留不译] |
| Snippet | 代码片段(Snippet) | 首现中英，后文中文 |  | cutile_python/术语表.md:68 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| socket identifier / ordinal | 插槽标识符 / 序号 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:386 [4.7 / 4.8 / 4.13 / 4.17 / 4.20 其他] |
| soname / rpath / install name / $ORIGIN | (链接器术语) | 英文 |  | cuda_best_practices_guide/术语表.md:240 [第 15–21 章(收官批次)新确立] |
| source / binary compatibility | 源码兼容性 / 二进制兼容性 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:229 [第 15–21 章(收官批次)新确立] |
| source lane / sub-segment | 源通道 / 子段 | 首现中英，后文中文 |  | ptx_isa/术语表.md:85 [数据搬运与类型(第 5 章 + 9.7.9)] |
| source module / source format | 源模块 / 源码格式 | 首现中英，后文中文 |  | ptx_isa/术语表.md:219 [语法与源码格式(第 4 章)] |
| source-level backward compatibility | 源代码级别向后兼容 | 首现中英，后文中文 |  | cusparse/术语表.md:19 [术语表] |
| source-level debugging / DWARF section | 源码级调试 / 节 | 首现中英，后文中文 |  | ptx_isa/术语表.md:184 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| sparse | 稀疏 | 首现中英，后文中文 |  | cublas/术语表.md:56 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| sparse dim / dense dim | 稀疏维度 / 稠密维度 | 首现中英，后文中文 |  | cutile_python/术语表.md:162 [API 参考批次(箱1:Load/Store~Selection;箱2:Math~JAX FFI;2026-08-29)] |
| sparse dimension / traversal strides | 稀疏维度 / 遍历步长 | 首现中英，后文中文 |  | tile_ir/术语表.md:173 [第 2/4/5/6 章(补派 Agent D,2026-08-29)] |
| sparse matrix | 稀疏矩阵 | 首现中英，后文中文 |  | cusparse/术语表.md:8 [术语表] |
| sparse matrix-matrix multiplication | 稀疏矩阵—矩阵乘法 | 首现中英，后文中文 |  | cusparse/术语表.md:16 [术语表] |
| sparse matrix-vector multiplication | 稀疏矩阵—向量乘法 | 首现中英，后文中文 |  | cusparse/术语表.md:15 [术语表] |
| sparse vector | 稀疏向量 | 首现中英，后文中文 |  | cusparse/术语表.md:10 [术语表] |
| special register | 特殊寄存器 | 首现中英，后文中文 |  | ptx_isa/术语表.md:17 [核心概念(预置进分发规则,全书沿用)] |
| special values | (浮点)特殊值 | 首现中英，后文中文 |  | cublas/术语表.md:54 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| specialization | 特化 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:47 [执行模型] |
| specialization(kernel 特化) | 特化 | 首现中英，后文中文 |  | cutile_python/术语表.md:65 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| speculatable | 可推测执行 | 首现中英，后文中文 |  | tile_ir/术语表.md:156 [第 8 章 8.9–8.12 + 第 12 章附录(Agent C,2026-08-29)] |
| speed-of-light | 光速级(speed-of-light,接近理论峰值) | 首现中英，后文中文 |  | cutile_python/术语表.md:101 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| speedup | 加速比 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:29 [本章新确立术语]; hopper_tuning_guide/术语表.md:36 [本文档新确立] |
| spill stores / loads | 溢出存储 / 溢出加载(承"寄存器溢出") | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:147 [第 6、8 章] |
| split compilation | 分割编译 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:88 [第 4 章(选项描述正文术语;选项名本身不译)]; cuda_programming_guide/术语表.md:209 [编译器(2.7)] |
| split-K | split-K | 英文 |  | cublas/术语表.md:79 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| SPMD | 单程序多数据(SPMD) | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:48 [第 1-3 章] |
| SSA / static single assignment | 静态单赋值(SSA) | 首现中英，后文中文 |  | tile_ir/术语表.md:57 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| SSA dominance | SSA 支配性 | 首现中英，后文中文 |  | tile_ir/术语表.md:187 [第 2/4/5/6 章(补派 Agent D,2026-08-29)] |
| stack canary | 栈金丝雀(stack canary) | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:102 [第 4 章(选项描述正文术语;选项名本身不译)] |
| stack frame | 栈帧 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:146 [第 6、8 章] |
| stage / stages | 阶段 | 首现中英，后文中文 |  | cublas/术语表.md:205 [3.3 cuBLASLt 数据类型参考(G5)] |
| staging | 中转(4.1 内存语境)/ 分段暂存(4.10 流水线语境) | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:297 [4.1 统一内存] |
| staging (buffer) | 暂存(缓冲区) | 首现中英，后文中文 |  | cublas/术语表.md:204 [3.3 cuBLASLt 数据类型参考(G5)] |
| stall | 停顿 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:133 [第 8–9、14 章(Optimizing / Performance Metrics / Deploying)新确立] |
| star "*" expression | 星号 "*" 表达式 | 首现中英，后文中文 |  | cutile_python/术语表.md:145 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| state space | 状态空间 | 首现中英，后文中文 |  | ptx_isa/术语表.md:13 [核心概念(预置进分发规则,全书沿用)] |
| statement / label / identifier / literal | 语句 / 标号 / 标识符 / 字面量 | 首现中英，后文中文 |  | ptx_isa/术语表.md:222 [语法与源码格式(第 4 章)] |
| static / dynamic shared memory allocation | 静态 / 动态共享内存分配 | 首现中英，后文中文 |  | cuda_blackwell_tuning_guide/术语表.md:38 [本章新确立(第 1 章翻译 Agent 上报,2026-08-29 中心合并)] |
| static evaluation / static_assert | 静态求值 / static_assert 保留 | 首现中英，后文中文 |  | cutile_python/术语表.md:61 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| static scheduling policy | 静态调度策略 | 首现中英，后文中文 |  | cublas/术语表.md:270 [第 4 章(G8)] |
| statically / dynamically linked | 静态链接 / 动态链接 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:247 [第 15–21 章(收官批次)新确立] |
| stencil / halo | stencil(模板计算)/ halo(边界区) | 英文 |  | cuda_programming_guide/术语表.md:359 [4.11 异步数据复制] |
| stochastic rounding | 随机舍入 | 首现中英，后文中文 |  | ptx_isa/术语表.md:147 [浮点与数值(9.7.3/9.7.4/9.7.5 + 各处)] |
| storage size | 存储大小 | 首现中英，后文中文 |  | tile_ir/术语表.md:78 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| stream | 流(stream) | 首现中英，后文中文 |  | cublas/术语表.md:12 [基准承接(沿用 CUDA Programming Guide 既有译法)]; cuda_programming_guide/术语表.md:160 [原子与同步(2.3、2.5)] |
| stream capture | 流捕获 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:167 [原子与同步(2.3、2.5)] |
| stream compaction / persistent thread block / co-residency | 流压缩 / 持久线程块 / 共同驻留 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:461 [5.6 / 5.2 / 5.7 / 5.8 设备 API、环境变量与形式化模型] |
| Stream Ordered Memory Allocator | 流序内存分配器(承 PG"stream-ordered allocator")【裁决:G8 初译"流有序"已统一】 | 首现中英，后文中文 |  | cublas/术语表.md:266 [第 4 章(G8)] |
| stream ordered pool allocator | 流序(stream ordered)池分配器 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:179 [第 10 章(Memory Optimizations)新确立] |
| stream-ordered allocation API | 流序分配 API(承 PG"流序内存分配器") | 首现中英，后文中文 |  | cublas/术语表.md:115 [2.1–2.5 总论与 Level-1(G4)] |
| stream-ordered allocator | 流序内存分配器 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:279 [特性巡礼(3.5)] |
| Streaming Multiprocessor (SM) | 流式多处理器(SM) | 首现中英，后文英文 |  | cuda_blackwell_tuning_guide/术语表.md:10 [沿用既有译法(本章高频)]; cuda_compiler_driver_nvcc/术语表.md:30 [沿用既有项目译法(预置进分发 prompt)]; cuda_programming_guide/术语表.md:28 [硬件]; hopper_tuning_guide/术语表.md:15 [沿用既有项目译法]; tile_ir/术语表.md:37 [承接既有项目(本表只列本书高频承接词)] |
| strength reduction | 强度削减(strength reduction) | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:202 [第 11–13 章(Execution Config / Instruction / Control Flow)新确立] |
| stride | 步长 | 首现中英，后文中文 |  | cublas/术语表.md:77 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| strided access | 跨步访问 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:137 [内存(2.3、2.6)] |
| strided memory layout / strides | 跨步内存布局 / 步长 | 首现中英，后文中文 |  | cutile_python/术语表.md:102 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| strided view | 跨步视图 | 首现中英，后文中文 |  | tile_ir/术语表.md:150 [第 8 章 8.9–8.12 + 第 12 章附录(Agent C,2026-08-29)]; tile_ir/术语表.md:171 [第 2/4/5/6 章(补派 Agent D,2026-08-29)] |
| strong scaling / weak scaling | 强扩展 / 弱扩展 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:69 [第 4 章(Application Profiling)新确立] |
| strongly happens before / weakly ordered memory model / sequentially consistent ordering | 强先行发生于 / 弱序内存模型 / 顺序一致排序 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:441 [5.3 / 5.4 语言支持与扩展(两节同词已合并)] |
| structured pointer | 结构化指针 | 首现中英，后文中文 |  | tile_ir/术语表.md:53 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| structured sparse / sparsity (metadata) / sparsity selector | 结构化稀疏 / 稀疏(性)元数据 / 稀疏(性)选择器 | 首现中英，后文中文 |  | ptx_isa/术语表.md:115 [矩阵乘累加与 TensorCore(9.7.15–9.7.17)] |
| stub function | 桩函数(stub function) | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:91 [第 4 章(选项描述正文术语;选项名本身不译)] |
| stub library | stub 库 | 英文 |  | cuda_best_practices_guide/术语表.md:266 [第 15–21 章(收官批次)新确立] |
| sub-byte type | 子字节类型 | 首现中英，后文中文 |  | ptx_isa/术语表.md:89 [数据搬运与类型(第 5 章 + 9.7.9)]; tile_ir/术语表.md:77 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| sub/super/main diagonal | 次/超/主对角线 | 首现中英，后文中文 |  | cublas/术语表.md:134 [2.6 Level-2(G1)] |
| subnormal | 次正规数 | 首现中英，后文中文 |  | cublas/术语表.md:22 [基准承接(沿用 CUDA Programming Guide 既有译法)] |
| subnormal / denormal | 次正规数 / 非正规数 | 首现中英，后文中文 |  | tile_ir/术语表.md:33 [承接既有项目(本表只列本书高频承接词)] |
| subnormal / denormal number | 次正规数 / 非正规数 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:411 [5.1 / 5.5 计算能力与浮点] |
| subnormal / normal number | 非正规数 / 正规数 | 首现中英，后文中文 |  | ptx_isa/术语表.md:142 [浮点与数值(9.7.3/9.7.4/9.7.5 + 各处)] |
| subnormal / sign-preserving zero | 次正规数 / 保号的零 | 首现中英，后文中文 |  | cutile_python/术语表.md:165 [API 参考批次(箱1:Load/Store~Selection;箱2:Math~JAX FFI;2026-08-29)] |
| subtile | 子 tile | 首现中英，后文中文 |  | cutile_python/术语表.md:174 [API 参考批次(箱1:Load/Store~Selection;箱2:Math~JAX FFI;2026-08-29)] |
| subtractive cancellation | 减法相消 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:417 [5.1 / 5.5 计算能力与浮点] |
| subview (type) | 子视图 | 首现中英，后文中文 |  | tile_ir/术语表.md:170 [第 2/4/5/6 章(补派 Agent D,2026-08-29)] |
| sum of absolute differences / dot product-accumulate | 绝对差之和 / 点积累加 | 首现中英，后文中文 |  | ptx_isa/术语表.md:164 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| surface / surface descriptor / surface memory | 表面 / 表面描述符 / 表面内存 | 首现中英，后文中文 |  | ptx_isa/术语表.md:202 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| surface-write | 表面写入(surface-write) | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:176 [第 10 章(Memory Optimizations)新确立] |
| swizzle / box | swizzle 保留 / box(盒)保留 | 英文 |  | cuda_programming_guide/术语表.md:360 [4.11 异步数据复制] |
| swizzle / swizzle mode / swizzle-atomicity | swizzle(交叉排布)保留 | 英文 |  | ptx_isa/术语表.md:98 [数据搬运与类型(第 5 章 + 9.7.9)] |
| symbol | 符号 | 首现中英，后文中文 |  | tile_ir/术语表.md:97 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| symbol resolution / object file | 符号解析 / 目标文件 | 首现中英，后文中文 |  | ptx_isa/术语表.md:181 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| symbol visibility | 符号可见性 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:136 [第 6、8 章] |
| symbolic math | 符号数学 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:116 [第 7 章(Getting the Right Answer)新确立] |
| symlink | 符号链接 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:251 [第 15–21 章(收官批次)新确立] |
| symmetric | 对称 | 首现中英，后文中文 |  | cublas/术语表.md:74 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| synchronizes with | 同步于 | 首现中英，后文中文 |  | ptx_isa/术语表.md:34 [内存模型(第 8 章 + 9.7.14,承 PG 5.7/5.8 与 09 块)] |
| Syntax / Description / Semantics / Notes / Examples | 语法 / 描述 / 语义 / 备注 / 示例 | 首现中英，后文中文 |  | ptx_isa/术语表.md:233 [结构标签与版本说明(第 9/11/13 章固定短语)] |
| syntax sugar | 语法糖 | 首现中英，后文中文 |  | cutile_python/术语表.md:108 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| synthesized host code | 综合生成的主机代码 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:66 [第 1-3 章] |
| system allocated memory / naturally-aligned | 系统分配内存 / 自然对齐 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:465 [5.6 / 5.2 / 5.7 / 5.8 设备 API、环境变量与形式化模型] |
| system-on-chip (SoC) | 片上系统 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:22 [核心概念] |
| tail launch / sibling launch | 尾部启动 / 兄弟启动 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:312 [4.2 CUDA Graphs] |
| target(执行环境) | 目标(target) | 首现中英，后文中文 |  | cutile_python/术语表.md:41 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| template function | 模板函数 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:140 [第 6、8 章] |
| template library | 模板库 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:81 [第 5–6 章(Parallelizing / Getting Started)新确立] |
| temporal / preemption / cycle counter | 时间性 / 抢占 / 周期计数器 | 首现中英，后文中文 |  | ptx_isa/术语表.md:188 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| temporary file | 临时文件 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:143 [第 6、8 章] |
| tensor | 张量 | 首现中英，后文中文 |  | hopper_tuning_guide/术语表.md:37 [本文档新确立] |
| tensor / tensor stride / tensor map / tensormap | 张量 / 张量步长 / 张量映射(tensormap 保留) | 首现中英，后文中文 |  | ptx_isa/术语表.md:95 [数据搬运与类型(第 5 章 + 9.7.9)] |
| tensor core | 张量核心 | 首现中英，后文中文 |  | cublas/术语表.md:15 [基准承接(沿用 CUDA Programming Guide 既有译法)]; cuda_programming_guide/术语表.md:194 [Tile 编程(2.4)]; tile_ir/术语表.md:15 [承接既有项目(本表只列本书高频承接词)] |
| tensor map / tiled-type tensor map | 张量映射 / 平铺类型张量映射 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:356 [4.11 异步数据复制] |
| Tensor Memory / tmem | 张量内存(tmem 保留) | 首现中英，后文中文 |  | ptx_isa/术语表.md:121 [矩阵乘累加与 TensorCore(9.7.15–9.7.17)] |
| Tensor Memory Accelerator (TMA) | 张量内存加速器(TMA) | 首现中英，后文英文 |  | hopper_tuning_guide/术语表.md:18 [沿用既有项目译法] |
| tensor memory access check | 张量内存访问检查(承 TMA) | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:108 [第 4 章(选项描述正文术语;选项名本身不译)] |
| tensor view | 张量视图(tensor view) | 首现中英，后文中文 |  | tile_ir/术语表.md:52 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| tensorwide scaling | 整张量缩放(tensorwide scaling) | 首现中英，后文中文 |  | cublas/术语表.md:87 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| terminator operation | 终结(terminator)操作 | 首现中英，后文中文 |  | tile_ir/术语表.md:133 [第 8 章 8.4–8.6(补译 Agent,2026-08-29)] |
| texel / bilerp / cubemap / mipmap / LOD | 纹素(承 BPG)/ bilerp(双线性插值)保留 / cubemap(立方体贴图)/ mipmap 保留 / 细节层次(LOD) | 首现中英，后文中文 |  | ptx_isa/术语表.md:198 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| textual representation | 文本表示 | 首现中英，后文中文 |  | tile_ir/术语表.md:56 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| texture / surface memory | 纹理内存 / 表面内存 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:143 [内存(2.3、2.6)] |
| texture cache | 纹理缓存 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:60 [第 3 章(Heterogeneous Computing)新确立] |
| texture fetch / texel | 纹理拾取 / 纹素 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:173 [第 10 章(Memory Optimizations)新确立] |
| texture reference | 纹理引用 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:218 [第 15–21 章(收官批次)新确立] |
| theoretical / effective bandwidth | 理论带宽 / 有效带宽 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:138 [第 8–9、14 章(Optimizing / Performance Metrics / Deploying)新确立] |
| thrashing | 抖动 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:164 [第 10 章(Memory Optimizations)新确立] |
| thread | 线程 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:15 [核心概念] |
| thread abstraction layer | 线程抽象层 | 首现中英，后文中文 |  | cublas/术语表.md:112 [2.1–2.5 总论与 Level-1(G4)] |
| thread block | 线程块 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:16 [核心概念] |
| thread block cluster | (线程块)集群 | 首现中英，后文中文 |  | cublas/术语表.md:31 [基准承接(沿用 CUDA Programming Guide 既有译法)]; cuda_programming_guide/术语表.md:18 [核心概念]; hopper_tuning_guide/术语表.md:16 [沿用既有项目译法] |
| Thread Block Clusters | 线程块集群 | 首现中英，后文中文 |  | cuda_blackwell_tuning_guide/术语表.md:12 [沿用既有译法(本章高频)] |
| thread of execution / forward progress guarantee / execution step | 执行线程 / 前进保证 / 执行步骤 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:470 [5.6 / 5.2 / 5.7 / 5.8 设备 API、环境变量与形式化模型] |
| thread safe | 线程安全 | 首现中英，后文中文 |  | cusparse/术语表.md:17 [术语表] |
| thread safety | 线程安全 | 首现中英，后文中文 |  | cublas/术语表.md:61 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| thread scope | 线程作用域 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:158 [原子与同步(2.3、2.5)] |
| threading model | 线程模型 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:49 [第 3 章(Heterogeneous Computing)新确立] |
| throughput | 吞吐量 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:25 [本章新确立术语]; hopper_tuning_guide/术语表.md:42 [本文档新确立] |
| ties away from zero / ties-to-even | 平局时远离零 / 平局取偶 | 首现中英，后文中文 |  | ptx_isa/术语表.md:153 [浮点与数值(9.7.3/9.7.4/9.7.5 + 各处)] |
| ties to even | 平局取偶 | 首现中英，后文中文 |  | cutile_python/术语表.md:107 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| tile | tile | 英文 |  | cuda_programming_guide/术语表.md:55 [Tile 编程(CUDA 13 新增)]; tile_ir/术语表.md:11 [承接既有项目(本表只列本书高频承接词)] |
| tile / tile kernel / tile grid | tile / tile kernel / tile 网格 | 英文 |  | cutile_python/术语表.md:11 [承接既有项目(本书高频承接词)] |
| tile block | tile block | 英文 |  | tile_ir/术语表.md:49 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| tile block thread | tile block 线程 | 英文 |  | tile_ir/术语表.md:51 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| tile block(逻辑线程块) | tile block | 英文 |  | cutile_python/术语表.md:12 [承接既有项目(本书高频承接词)] |
| tile function | tile 函数 | 首现中英，后文中文 |  | cutile_python/术语表.md:39 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)]; tile_ir/术语表.md:169 [第 2/4/5/6 章(补派 Agent D,2026-08-29)] |
| tile grid | tile 网格(tile grid) | 首现中英，后文中文 |  | tile_ir/术语表.md:50 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| Tile IR | Tile IR | 英文 |  | tile_ir/术语表.md:48 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| tile kernel / tile kernel instance | tile kernel / tile kernel 实例 | 英文 |  | tile_ir/术语表.md:168 [第 2/4/5/6 章(补派 Agent D,2026-08-29)] |
| Tile parser | Tile 解析器 | 英文 |  | cuda_compiler_driver_nvcc/术语表.md:124 [第 5、7 章] |
| tile partition space | tile 划分空间 | 首现中英，后文中文 |  | cutile_python/术语表.md:161 [API 参考批次(箱1:Load/Store~Selection;箱2:Math~JAX FFI;2026-08-29)] |
| tile programming model | tile 编程模型 | 英文 |  | cuda_programming_guide/术语表.md:56 [Tile 编程(CUDA 13 新增)] |
| tile space | tile 空间 | 英文 |  | cuda_programming_guide/术语表.md:59 [Tile 编程(CUDA 13 新增)] |
| tile 编程模型 | tile programming model | 英文 |  | tile_ir/术语表.md:12 [承接既有项目(本表只列本书高频承接词)] |
| tiled layout | 分块(tiled)布局 | 首现中英，后文中文 |  | cublas/术语表.md:235 [第 1 章与 3.1–3.2(G7)] |
| tiled mode / im2col / bounding box | 平铺模式(承 PG)/ im2col 保留 / 边界框(5.5)·包围盒(9.7.9) | 首现中英，后文中文 |  | ptx_isa/术语表.md:96 [数据搬运与类型(第 5 章 + 9.7.9)] |
| tiled view / partition view | 分块视图 / 分区视图 | 首现中英，后文中文 |  | cutile_python/术语表.md:21 [承接既有项目(本书高频承接词)] |
| tiling design approach | 分块设计方法 | 首现中英，后文中文 |  | cublas/术语表.md:94 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| time to solution | 求解时间 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:72 [第 4 章(Application Profiling)新确立] |
| timestamp | 时间戳 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:136 [第 8–9、14 章(Optimizing / Performance Metrics / Deploying)新确立] |
| TLB / TLB miss | 转译后备缓冲区 / TLB 未命中 | 首现中英，后文英文 |  | cuda_programming_guide/术语表.md:291 [4.1 统一内存] |
| TMA | TMA(张量内存加速器) | 英文 |  | cutile_python/术语表.md:115 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| TMA (Tensor Memory Accelerator) | 张量内存加速器 | 首现中英，后文英文 |  | cuda_programming_guide/术语表.md:193 [Tile 编程(2.4)] |
| token / arrival_token | 令牌 / 到达令牌对象 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:339 [4.4 / 4.9 / 4.10 / 4.12 / 4.14 执行与同步] |
| token / reserved token | 记号 / 保留记号 | 首现中英，后文中文 |  | ptx_isa/术语表.md:221 [语法与源码格式(第 4 章)] |
| token / token order | 令牌 / 令牌序 | 首现中英，后文中文 |  | tile_ir/术语表.md:22 [承接既有项目(本表只列本书高频承接词)] |
| token chain / token threading | 令牌链 / 令牌穿透 | 首现中英，后文中文 |  | tile_ir/术语表.md:186 [第 2/4/5/6 章(补派 Agent D,2026-08-29)] |
| token-ordered | 令牌序(token-ordered) | 首现中英，后文中文 |  | tile_ir/术语表.md:140 [第 8 章 8.4–8.6(补译 Agent,2026-08-29)] |
| tolerance | 容差(tolerance) | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:114 [第 7 章(Getting the Right Answer)新确立] |
| toolchain | 工具链 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:203 [编译器(2.7)] |
| total order | 全序 | 首现中英，后文中文 |  | ptx_isa/术语表.md:62 [内存模型(第 8 章 + 9.7.14,承 PG 5.7/5.8 与 09 块)] |
| total speedup | 总体加速比 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:144 [第 8–9、14 章(Optimizing / Performance Metrics / Deploying)新确立] |
| trade precision for speed | 以精度换速度 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:269 [第 15–21 章(收官批次)新确立] |
| trailing dimensions | 末尾维度 | 首现中英，后文中文 |  | cutile_python/术语表.md:105 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| trailing return type / lambda introducer | 尾置返回类型 / lambda 引导符 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:432 [5.3 / 5.4 语言支持与扩展(两节同词已合并)] |
| transaction count | 事务计数 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:340 [4.4 / 4.9 / 4.10 / 4.12 / 4.14 执行与同步] |
| translation unit | 翻译单元 | 首现中英，后文中文 |  | cublas/术语表.md:233 [第 1 章与 3.1–3.2(G7)]; cuda_compiler_driver_nvcc/术语表.md:123 [第 5、7 章] |
| translation unit / entry point | 翻译单元 / 入口点 | 首现中英，后文中文 |  | tile_ir/术语表.md:190 [第 2/4/5/6 章(补派 Agent D,2026-08-29)] |
| transparently | 透明地(对用户不可见地) | 首现中英，后文中文 |  | hopper_tuning_guide/术语表.md:49 [本文档新确立] |
| trap / mutex / exponential back-off | 陷阱 / 互斥锁 / 指数退避 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:448 [5.3 / 5.4 语言支持与扩展(两节同词已合并)] |
| trap(动词) | 陷入(trap) | 首现中英，后文中文 |  | tile_ir/术语表.md:139 [第 8 章 8.4–8.6(补译 Agent,2026-08-29)] |
| traversal stride / out of boundary access | 遍历步长 / 越界访问 | 首现中英，后文中文 |  | ptx_isa/术语表.md:97 [数据搬运与类型(第 5 章 + 9.7.9)] |
| traversal striding factors | 遍历步进因子 | 首现中英，后文中文 |  | tile_ir/术语表.md:151 [第 8 章 8.9–8.12 + 第 12 章附录(Agent C,2026-08-29)] |
| triangular packed format | 三角压缩存储格式 | 首现中英，后文中文 |  | cublas/术语表.md:178 [2.8 类 BLAS 扩展(G3)] |
| trip count / entry-function scope | 迭代次数 / 入口函数作用域 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:450 [5.3 / 5.4 语言支持与扩展(两节同词已合并)] |
| triple chevron notation | 三尖括号语法 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:115 [kernel 与启动(2.1–2.2)] |
| truncate (chop) | 截断(chop) | 首现中英，后文中文 |  | ptx_isa/术语表.md:227 [语法与源码格式(第 4 章)] |
| truncated division | 截断除法 | 首现中英，后文中文 |  | tile_ir/术语表.md:204 [第 8 章 8.7–8.8(第三次补派 Agent,2026-08-29)] |
| tuning / tune | 调优 | 首现中英，后文中文 |  | hopper_tuning_guide/术语表.md:34 [本文档新确立] |
| tuple | 元组 | 首现中英，后文中文 |  | cublas/术语表.md:252 [第 1 章与 3.1–3.2(G7)] |
| tuples / tuple comprehension | 元组 / 元组推导式 | 首现中英，后文中文 |  | cutile_python/术语表.md:48 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| two stage compilation model | 两阶段编译模型 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:118 [第 5、7 章] |
| two's complement | 二进制补码 | 首现中英，后文中文 |  | tile_ir/术语表.md:210 [第 8 章 8.7–8.8(第三次补派 Agent,2026-08-29)] |
| type annotations | 类型标注 | 首现中英，后文中文 |  | cutile_python/术语表.md:46 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| type equivalence | 类型等价 | 首现中英，后文中文 |  | tile_ir/术语表.md:80 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| type hint | 类型提示 | 首现中英，后文中文 |  | cutile_python/术语表.md:131 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| type signature / function prototype | 类型签名 / 函数原型 | 首现中英，后文中文 |  | ptx_isa/术语表.md:175 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| type traits / literal type / placeholder type | 类型萃取 / 字面类型 / 占位类型 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:431 [5.3 / 5.4 语言支持与扩展(两节同词已合并)] |
| typed functions | 带类型的函数 | 首现中英，后文中文 |  | cublas/术语表.md:179 [2.8 类 BLAS 扩展(G3)] |
| ulp | ulp(末位单位) | 首现中英，后文英文 |  | cuda_programming_guide/术语表.md:420 [5.1 / 5.5 计算能力与浮点]; ptx_isa/术语表.md:149 [浮点与数值(9.7.3/9.7.4/9.7.5 + 各处)] |
| ULP (Unit in the Last Place) | 末位单位 | 首现中英，后文中文 |  | tile_ir/术语表.md:205 [第 8 章 8.7–8.8(第三次补派 Agent,2026-08-29)] |
| undefined behavior | 未定义行为 | 首现中英，后文中文 |  | cublas/术语表.md:144 [2.6 Level-2(G1)]; cutile_python/术语表.md:126 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)]; tile_ir/术语表.md:92 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| unicast / multicast | 单播 / 多播 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:327 [4.3 / 4.16 内存管理] |
| unified / independent mode;texturing mode | 统一模式 / 独立模式;纹理模式 | 首现中英，后文中文 |  | ptx_isa/术语表.md:199 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| unified / partitioned pipeline | 统一流水线 / 分区流水线 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:343 [4.4 / 4.9 / 4.10 / 4.12 / 4.14 执行与同步] |
| unified data cache | 统一数据缓存 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:32 [硬件] |
| Unified Memory(特性名) | 统一内存 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:74 [内存] |
| unified virtual addressing (UVA) | 统一虚拟寻址(UVA) | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:156 [第 10 章(Memory Optimizations)新确立] |
| uniform (batch) | 均匀(uniform)【裁决:02c/02d"统一"已统一】 | 首现中英，后文中文 |  | cublas/术语表.md:143 [2.6 Level-2(G1)] |
| uniform cache / load uniform | uniform 缓存 / 统一加载 | 英文 |  | ptx_isa/术语表.md:207 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| union | 联合体 | 首现中英，后文中文 |  | ptx_isa/术语表.md:169 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| unit / non-unit diagonal | 单位对角 / 非单位对角 | 首现中英，后文中文 |  | cublas/术语表.md:72 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| unit attribute | 单位属性 | 首现中英，后文中文 |  | tile_ir/术语表.md:138 [第 8 章 8.4–8.6(补译 Agent,2026-08-29)] |
| unit stride / padding (pad) | 单位步长 / 填充(pad) | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:169 [第 10 章(Memory Optimizations)新确立] |
| unit testing | 单元测试 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:105 [第 7 章(Getting the Right Answer)新确立] |
| upper / lower (triangular part) | 上 / 下(三角部分) | 首现中英，后文中文 |  | cublas/术语表.md:71 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| upper bound | 上限 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:42 [本章新确立术语] |
| upstream / downstream kernel | 上游 / 下游 kernel | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:369 [4.5 / 4.6 PDL 与绿色上下文] |
| usage count | 使用计数 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:263 [驱动 API 与多 GPU(3.3–3.4)] |
| user-mode / kernel-mode | 用户态 / 内核态 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:225 [第 15–21 章(收官批次)新确立] |
| usual arithmetic conversions | 常规算术转换 | 首现中英，后文中文 |  | ptx_isa/术语表.md:225 [语法与源码格式(第 4 章)] |
| variadic | 可变参数(variadic) | 首现中英，后文中文 |  | tile_ir/术语表.md:61 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| variadic function / unsized array | 可变参数函数 / 无大小数组 | 首现中英，后文中文 |  | ptx_isa/术语表.md:176 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| variadic keyword parameters | 可变关键字参数 | 首现中英，后文中文 |  | cutile_python/术语表.md:139 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| variadic template / parameter pack | 可变参数模板 / 参数包 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:436 [5.3 / 5.4 语言支持与扩展(两节同词已合并)] |
| vector addition | 向量加法 | 首现中英，后文中文 |  | cutile_python/术语表.md:111 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)]; tile_ir/术语表.md:87 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| vector tuple / brace-enclosed vector expression | 向量元组 / 花括号括起的向量表达式 | 首现中英，后文中文 |  | ptx_isa/术语表.md:94 [数据搬运与类型(第 5 章 + 9.7.9)] |
| vector type / launch bounds / annotation | 向量类型 / 启动边界 / 注解 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:439 [5.3 / 5.4 语言支持与扩展(两节同词已合并)] |
| verification | 验证 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:100 [第 7 章(Getting the Right Answer)新确立] |
| version field | 版本字段 | 首现中英，后文中文 |  | tile_ir/术语表.md:99 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| vertex buffer object (VBO) | 顶点缓冲区对象(VBO) | 首现中英，后文英文 |  | cuda_programming_guide/术语表.md:393 [4.15 / 4.19 互操作] |
| view (partition view / tiled view) | 视图(分区视图 / 分块视图) | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:178 [Tile 编程(2.4)] |
| view space / view-space indices | 视图空间(索引) | 首现中英，后文中文 |  | tile_ir/术语表.md:153 [第 8 章 8.9–8.12 + 第 12 章附录(Agent C,2026-08-29)] |
| virtual / actual architecture | 虚拟架构 / 实际架构 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:236 [第 15–21 章(收官批次)新确立] |
| virtual / real architecture | 虚拟架构 / 实际架构 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:21 [沿用既有项目译法(预置进分发 prompt)] |
| virtual alias / alias proxy fence | 虚拟别名 / 别名代理栅栏 | 首现中英，后文中文 |  | ptx_isa/术语表.md:48 [内存模型(第 8 章 + 9.7.14,承 PG 5.7/5.8 与 09 块)] |
| virtual aliasing | 虚拟别名化 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:310 [4.2 CUDA Graphs] |
| virtual architecture / feature testing macro / pure function | 虚拟架构 / 特性测试宏 / 纯函数 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:446 [5.3 / 5.4 语言支持与扩展(两节同词已合并)] |
| virtual environment | 虚拟环境 | 首现中英，后文中文 |  | cutile_python/术语表.md:64 [本书预决新术语(中心预置,Agent 照用;有更优建议须上报)] |
| virtual ISA | 虚拟指令集架构 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:87 [平台与工具链]; ptx_isa/术语表.md:25 [核心概念(预置进分发规则,全书沿用)] |
| VRAM | 显存(VRAM) | 首现中英，后文中文 |  | cublas/术语表.md:223 [3.4 cuBLASLt API 参考(G6)] |
| wall-time timeout | 挂钟时间超时 | 首现中英，后文中文 |  | cutile_python/术语表.md:117 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| walrus operator | 海象运算符 | 首现中英，后文中文 |  | cutile_python/术语表.md:181 [API 参考批次(箱1:Load/Store~Selection;箱2:Math~JAX FFI;2026-08-29)] |
| warp | warp | 英文 |  | cuda_programming_guide/术语表.md:40 [执行模型] |
| warp / CTA / cluster / grid / lane | warp 保留 / CTA(线程块)/ 集群(线程块集群)/ 网格 / 通道(lane) | 英文 |  | ptx_isa/术语表.md:21 [核心概念(预置进分发规则,全书沿用)] |
| warp / lane | warp / warp 通道 | 英文 |  | tile_ir/术语表.md:38 [承接既有项目(本表只列本书高频承接词)] |
| warp / thread block | warp / 线程块 | 英文 |  | hopper_tuning_guide/术语表.md:13 [沿用既有项目译法] |
| warp / warp-synchronous | warp / warp 同步性 | 英文 |  | hopper_compatibility_guide/术语表.md:18 [沿用既有项目译法] |
| warp divergence | warp 分歧 | 英文 |  | cuda_programming_guide/术语表.md:42 [执行模型] |
| warp entanglement | warp 纠缠 | 英文 |  | cuda_programming_guide/术语表.md:344 [4.4 / 4.9 / 4.10 / 4.12 / 4.14 执行与同步] |
| warp lane | warp 通道 | 英文 |  | cuda_programming_guide/术语表.md:41 [执行模型] |
| warp matrix functions / fragment / accumulator / satf | warp 矩阵函数 / 片段 / 累加器 / 饱和到有限值 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:451 [5.3 / 5.4 语言支持与扩展(两节同词已合并)] |
| warp occupancy | warp 占用率 | 首现中英，后文中文 |  | cuda_blackwell_tuning_guide/术语表.md:36 [本章新确立(第 1 章翻译 Agent 上报,2026-08-29 中心合并)] |
| warp pair / thread-pair / quad | warp 对 / 线程对 / quad(四线程组) | 首现中英，后文中文 |  | ptx_isa/术语表.md:130 [矩阵乘累加与 TensorCore(9.7.15–9.7.17)] |
| warp scheduler | warp 调度器 | 英文 |  | cuda_programming_guide/术语表.md:239 [硬件模型与执行(3.2)] |
| warp specialization | warp 特化 | 英文 |  | cuda_programming_guide/术语表.md:341 [4.4 / 4.9 / 4.10 / 4.12 / 4.14 执行与同步] |
| warp specialization / warp specialized | warp 特化 | 英文 |  | hopper_tuning_guide/术语表.md:19 [沿用既有项目译法] |
| warp vote / match / reduce / shuffle 函数 | warp 表决 / 匹配 / 归约 / shuffle 函数(shuffle 保留;5.6 操作语境译"洗牌(shuffle)") | 英文 |  | cuda_programming_guide/术语表.md:444 [5.3 / 5.4 语言支持与扩展(两节同词已合并)] |
| warp-specialized kernel | warp 特化 kernel | 英文 |  | cutile_python/术语表.md:95 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| warp-synchronicity / warp-synchronous | warp 同步性 / warp 同步式 | 英文 |  | cuda_blackwell_compatibility_guide/术语表.md:21 [沿用基准项目既有译法(本章高频)] |
| warp-synchronous | warp 同步式 | 英文 |  | cuda_programming_guide/术语表.md:237 [硬件模型与执行(3.2)] |
| warpgroup | warp 组(warpgroup) | 首现中英，后文英文 |  | ptx_isa/术语表.md:120 [矩阵乘累加与 TensorCore(9.7.15–9.7.17)] |
| watermark | 水位标记 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:323 [4.3 / 4.16 内存管理] |
| wave count | wave 数 | 英文 |  | cublas/术语表.md:218 [3.4 cuBLASLt API 参考(G6)] |
| waves count | 波数 | 首现中英，后文中文 |  | cublas/术语表.md:200 [3.3 cuBLASLt 数据类型参考(G5)] |
| weak / strong memory operation | 弱 / 强内存操作 | 首现中英，后文中文 |  | ptx_isa/术语表.md:44 [内存模型(第 8 章 + 9.7.14,承 PG 5.7/5.8 与 09 块)] |
| weak function / non-weak | 弱函数 / 非弱函数 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:139 [第 6、8 章] |
| weak linkage | 弱链接 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:32 [沿用既有项目译法(预置进分发 prompt)] |
| weak symbol / common symbol | 弱符号 / 公共(common)符号 | 首现中英，后文中文 |  | ptx_isa/术语表.md:180 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| weak write / weak store | 弱写入 / 弱存储 | 首现中英，后文中文 |  | ptx_isa/术语表.md:78 [数据搬运与类型(第 5 章 + 9.7.9)] |
| whitepaper / webinar | 白皮书 / 网络研讨会 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:120 [第 7 章(Getting the Right Answer)新确立] |
| whole-program compilation | 整程序编译 | 首现中英，后文中文 |  | cuda_compiler_driver_nvcc/术语表.md:19 [沿用既有项目译法(预置进分发 prompt)]; cuda_programming_guide/术语表.md:206 [编译器(2.7)] |
| wide load/store / indirect call | 宽加载 / 宽存储 / 间接调用 | 首现中英，后文中文 |  | ptx_isa/术语表.md:212 [指令语义杂项(9.7 各组 + 第 6/7/10/11 章)] |
| word size | 字长(word size) | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:141 [第 8–9、14 章(Optimizing / Performance Metrics / Deploying)新确立] |
| work queue (WQ) | 工作队列(WQ) | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:370 [4.5 / 4.6 PDL 与绿色上下文] |
| work stealing | 工作窃取 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:276 [特性巡礼(3.5)] |
| workload | 负载 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:39 [本章新确立术语] |
| workload / workload sharing | 工作负载 / 工作负载分担 | 首现中英，后文中文 |  | cublas/术语表.md:267 [第 4 章(G8)] |
| workspace | 工作区 | 首现中英，后文中文 |  | cublas/术语表.md:49 [cuBLAS 总论术语(本表开译前中心预置,全体 Agent 必须照用)] |
| wrap-around | 回绕 | 首现中英，后文中文 |  | tile_ir/术语表.md:155 [第 8 章 8.9–8.12 + 第 12 章附录(Agent C,2026-08-29)] |
| wrapper | 包装器 | 首现中英，后文中文 |  | cutile_python/术语表.md:142 [主章批次(Agent A:01/02/03/06/07;Agent B:09/12;2026-08-29)] |
| yield(动词) | 交出(yield) | 首现中英，后文中文 |  | tile_ir/术语表.md:134 [第 8 章 8.4–8.6(补译 Agent,2026-08-29)] |
| zero copy | 零复制(zero copy);节名 Zero Copy 保留 | 首现中英，后文中文 |  | cuda_best_practices_guide/术语表.md:152 [第 10 章(Memory Optimizations)新确立]; cuda_best_practices_guide/术语表.md:293 [待定(已全部转正,2026-08-28 第 8–14 章定稿)] |
| zero-column mask descriptor / sub-mask | 零列掩码描述符 / 子掩码 | 首现中英，后文中文 |  | ptx_isa/术语表.md:133 [矩阵乘累加与 TensorCore(9.7.15–9.7.17)] |
| zero-copy memory | 零拷贝内存 | 首现中英，后文中文 |  | cuda_programming_guide/术语表.md:148 [内存(2.3、2.6)] |
| zero-extension / sign-extension | 零扩展 / 符号扩展 | 首现中英，后文中文 |  | tile_ir/术语表.md:130 [第 8 章 8.4–8.6(补译 Agent,2026-08-29)] |
| 原子操作族 atomic_add 等 | atomic_xxx 保留(描述译"原子") | 英文 |  | cutile_python/术语表.md:32 [承接既有项目(本书高频承接词)] |
| 舍入枚举 nearest_even/zero/negative_inf/...、overflow 枚举 none/no_signed_wrap/... | 不译 | 英文 |  | tile_ir/术语表.md:214 [第 8 章 8.7–8.8(第三次补派 Agent,2026-08-29)] |
