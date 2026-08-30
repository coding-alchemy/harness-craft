> **原文** / Programming Interface / NVIDIA CUDA C++ Programming Guide
> **来源** / 本地测试样本 paginated_page2.html
> **译例说明** / 标题保留官方英文原题与编号，代码围栏由脚本从源文逐字节拼接。

# 2. Programming Interface（编程接口）

CUDA 编程接口支持编译、内存管理和执行控制。

## 2.1. Compilation（编译）

包含 CUDA C++ 内核的源文件使用 `nvcc` 进行编译。

⟦CODE⟧

| 选项 | 说明 |
| --- | --- |
| `-arch=sm_90` | 目标 SM 9.0 架构。 |
| `--use_fast_math` | 使用更快但精度较低的内建函数。 |

![Compilation flow](images/compilation_flow.png)
