> **原文**：Math Reference
> **来源**：tech-doc-translator/tests/fixtures/math_reference.html
> **译例说明**：数学密集参考手册薄切样本，保留公式、代码与强 token。

# 1. Math Reference（数学参考手册）

能量表示为 $E=mc^2$。内联美元公式：$a+b=c$。

## 1.1. Formula Types（公式类型）

$$
\sum_{i=1}^{n} i = \frac{n(n+1)}{2}
$$

### 1.1.1. Code Example（代码示例）

```cuda
__global__ void kernel(int* a) {
    a[threadIdx.x] = 1;
}
```

#### 1.1.1.1. Parameters（参数）

| Parameter | Meaning |
| --- | --- |
| alpha | 缩放因子 |
| beta | 偏置项 |

##### 1.1.1.1.1. Deep Notes（深层注释）

cuBLAS 和 CUDA 使用 nvcc 编译。

###### 1.1.1.1.1.1. Even Deeper（更深）

- item one（条目一）
- item two（条目二）
  - nested item（嵌套条目）
