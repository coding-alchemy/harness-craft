> **原文**：Nested Reference Manual
> **来源**：tech-doc-translator/tests/fixtures/nested_reference.html
> **译例说明**：深层嵌套参考手册薄切样本，保留嵌套图片、代码与强 token。

# 2. Nested Reference Manual（嵌套参考手册）

调用使用 cudaMalloc 和 threadIdx.x。

## 2.1. Deep Heading Trail（深层标题路径）

### 2.1.1. Section（节）

#### 2.1.1.1. Subsection（小节）

##### 2.1.1.1.1. Deep（深层）

Deep text（深层文本）。

###### 2.1.1.1.1.1. Deeper（更深）

Deeper text（更深文本）。

## 2.2. Nested Elements（嵌套元素）

- list item with figure（带图的列表项）

![List figure](images/thread_hierarchy.png)

**图 1. List caption（List caption）**

```cuda
__global__ void listKernel() {}
```

- **Term**（术语）：definition with figure（带图的定义）

![Definition figure](images/thread_hierarchy.png)

**图 2. Definition caption（Definition caption）**

```cuda
__global__ void defKernel() {}
```

> quoted text（引用文本）

![Blockquote figure](images/thread_hierarchy.png)

**图 3. Blockquote caption（Blockquote caption）**

```cuda
__global__ void bqKernel() {}
```
