> **原文** / Programming Model / NVIDIA CUDA C++ Programming Guide
> **来源** / 本地测试样本 paginated_page1.html
> **译例说明** / 标题保留官方英文原题与编号，代码围栏由脚本从源文逐字节拼接。

# 1. Programming Model（编程模型）

CUDA 编程模型围绕线程层级组织并行计算。

## 1.1. Kernels（内核）

CUDA C++ 允许程序员定义*内核*函数，从而扩展了 C++。

⟦CODE⟧

- 内核由主机端发起调用。
- 线程被组织为线程块。

![Grid of thread blocks](images/grid_blocks.png)

> **注（Note）**
> 内核调用相对于主机是异步的。
