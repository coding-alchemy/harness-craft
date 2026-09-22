# 2. Nested Reference Manual

Calls use cudaMalloc and threadIdx.x.

## 2.1. Deep Heading Trail

### 2.1.1. Section

#### 2.1.1.1. Subsection

##### 2.1.1.1.1. Deep

Deep text.

###### 2.1.1.1.1.1. Deeper

Deeper text.

## 2.2. Nested Elements
  - list item with figure Fig 1. List caption

  [IMG: images/thread_hierarchy.png]
  [FIGURE] Fig 1. List caption

  ```
__global__ void listKernel() {}
  ```

[DEF-LIST]
  **Term** definition with figure Fig 2. Definition caption

  [IMG: images/thread_hierarchy.png]
  [FIGURE] Fig 2. Definition caption

  ```
__global__ void defKernel() {}
  ```

quoted text

[IMG: images/thread_hierarchy.png]
[FIGURE] Fig 3. Blockquote caption

```
__global__ void bqKernel() {}
```
