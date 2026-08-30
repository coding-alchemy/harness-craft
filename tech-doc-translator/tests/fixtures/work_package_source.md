# 1. Compute Kernel Basics

## 1.1. Thread Hierarchy

A CUDA kernel is executed by a grid of thread blocks.
Each thread block contains multiple threads.

- Threads within a warp execute in lock step.
- A warp has 32 threads.

```c
__global__ void kernel(int* data) {
    int tid = threadIdx.x;
}
```

## 1.2. Memory Model

CUDA exposes several memory spaces to the programmer.

1. Global memory is accessible by all threads.
2. Shared memory is shared within a block.
3. Registers are private to each thread.

> **ADMONITION [Note]**
> The memory model is crucial for performance tuning.

## 1.3. Warp Scheduling

The warp scheduler selects active warps each cycle.

| Term | Meaning |
| --- | --- |
| warp | A group of 32 threads |
| kernel | A function launched on the GPU |
