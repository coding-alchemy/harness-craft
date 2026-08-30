> **原文**：Sample HPC Guide
> **来源**：tech-doc-translator/tests/fixtures/sample_single_page.html
> **译例说明**：单页 HTML 薄切端到端样本，保留代码与术语。

# 1. Compute Kernel Basics（计算内核基础）

kernel 是在 [GPU](https://docs.nvidia.com/cuda/cuda-c-programming-guide/) 上运行的函数。其启动语法为 `kernel<<<blocks, threads>>>(args)`。

> **注（Note）**
> 始终在主机代码中检查返回值。

## 1.1. Thread Hierarchy（线程层次结构）

线程被分组为 $N$ 个块。这是一个脚注示例[^1]。

- thread：一个执行单元
- block：一组线程

```cuda
__global__ void kernel(int* a) {
    int idx = threadIdx.x;
    a[idx] = idx;
}
```

### 1.1.1. Memory Model（内存模型）

| Memory | Scope |
| --- | --- |
| Shared | Block |
| Global | Grid |

![Thread hierarchy diagram](images/thread_hierarchy.png)

[^1]: 关于网格的脚注文本。
