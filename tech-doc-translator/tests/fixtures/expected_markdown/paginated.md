# 1. Programming Model

The CUDA programming model organizes parallel computation around a hierarchy of threads.

## 1.1. Kernels

CUDA C++ extends C++ by allowing the programmer to define kernel functions.

```
// kernel launch with triple chevrons
#include <cuda_runtime.h>

__global__ void vecAdd(const float* A, const float* B, float* C, int n) {
    int i = blockDim.x * blockIdx.x + threadIdx.x;
    if (i < n) {
        C[i] = A[i] + B[i];
    }
}

int main() {
    int N = 1 << 20;
    vecAdd<<<(N + 255) / 256, 256>>>(d_A, d_B, d_C, N);
    if (N > 0 && N < 1024) return 0;
    return 0;
}
```
  - Kernels are launched by the host.
  - Threads are grouped into thread blocks.

![Grid of thread blocks](images/grid_blocks.png)

> **ADMONITION [Note]**
> Kernel launches are asynchronous with respect to the host.
