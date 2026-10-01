# 1. Compute Kernel Basics

A kernel is a function that runs on the [GPU](https://docs.nvidia.com/cuda/cuda-c-programming-guide/). Its launch syntax is `kernel<<<blocks, threads>>>(args)`.

> **ADMONITION [Note]**
> Always check return codes in host code.

## 1.1. Thread Hierarchy

Threads are grouped into $N$ blocks. A footnote example [^1].
  - thread: one execution unit
  - block: a group of threads

```
__global__ void kernel(int* a) {
    int idx = threadIdx.x;
    a[idx] = idx;
}
```

### 1.1.1. Memory Model

[TABLE]
Memory | Scope
--- | ---
Shared | Block
Global | Grid

![Thread hierarchy diagram](images/thread_hierarchy.png)

[FOOTNOTE-LIST]
  [[1]] Footnote text about grids.
