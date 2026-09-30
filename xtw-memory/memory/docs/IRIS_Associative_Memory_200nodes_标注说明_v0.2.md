# IRIS Associative Memory 200-node 标注样本 v0.2

- Nodes: **200**
- Directed edges: **784**
- Recall cases: **13**
- Source L2 memory IDs represented: **42**

## 定位

这是给 Codex 直接跑大图 Demo 的 **200 个认知节点**样本。

它不是严格 Blind-200-memory benchmark。内容来自 IRIS 备份中可核对的 L2 memory 及其显式组成部分；没有根据 Demo 输出调 Association Strength。

## Node types

```json
{
  "Person": 11,
  "Alias": 10,
  "Concept": 49,
  "Activity": 12,
  "Memory": 43,
  "Self": 1,
  "Role": 5,
  "Object": 6,
  "Location": 8,
  "Goal": 3,
  "Proposition": 33,
  "Process": 1,
  "Organization": 1,
  "Event": 1,
  "Time": 3,
  "Persona": 2,
  "Brand": 1,
  "Procedure": 1,
  "Cue": 9
}
```

## Dirty-data status

```json
{
  "CLEAN": 192,
  "SUBJECTLESS": 6,
  "MIXED": 2
}
```

## 固定边权

```text
VERY_STRONG = 0.95
STRONG      = 0.80
MEDIUM      = 0.60
WEAK        = 0.35
VERY_WEAK   = 0.15
```

## 使用

把 `iris_associative_memory_annotated_200nodes_v0.2.json` 交给 Codex，
让 Demo 直接加载。不要为了 case 通过回调权重。
