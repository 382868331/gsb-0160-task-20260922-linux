# 显式节点的递归类型等价检查（equi-recursive type equivalence）

一个零依赖、纯标准库的 Python 题库：输入两张**显式节点、可能含环**的有根类型图，
按无限展开树的 **equi-recursive 等价**定义做成对协同检查，返回等价关系
（bisimulation）证书或**最短**分歧路径；构造期拒绝悬空边、错误元数等非法输入。
另提供**规范化入口**：把单张图内互为双模拟的节点合并成有限商图，
作为类型缓存的统一共享表示（缓存键）。

- Python：**3.14.7**（仅使用 3.10+ 通用语法，不依赖任何第三方包）
- 依赖：**无**。安装 Python 后直接运行；核心、测试、演示全部离线。
- 不使用网络、账号、密钥、数据库、中间件、云 API 或 Docker。

## 运行命令

```bash
# 必要测试（62 个用例）
python -m unittest discover -s tests -v

# 固定输入演示（真实计算；本机实测 < 0.1 秒，远低于约 8 秒要求）
python demo.py
```

## 公开数据结构

```python
from recursive_types import (
    TypeGraph, Field,
    IntNode, BoolNode, ProductNode, SumNode, FunctionNode,
    check_equivalence, are_equivalent, verify_certificate,
    EquivalenceCertificate, Divergence,
)

TypeGraph(nodes, root)
# nodes: list/tuple，下标即节点编号；root: 严格 int，非 bool
IntNode()
BoolNode()
ProductNode((Field("a", 目标编号), ...))   # >=1 个字段，同节点内字段名唯一
SumNode((Field("x", 目标编号), ...))       # >=1 个字段，同节点内字段名唯一
FunctionNode((参数编号, ...), 结果编号)     # >=1 个有序参数 + 1 个返回
```

节点种类：`Int`、`Bool`（叶子）、`Product`、`Sum`（命名字段集合）、
`Function`（有序参数 + 返回）。节点编号**只用于在单张图内表达边与回边**，
不参与两张图之间的语义；共享子图与复制子图不区分。

## 接口与返回值

```python
result = check_equivalence(g1, g2, *, root1=None, root2=None, budget=90_000)
```

- 等价：返回 `EquivalenceCertificate`
  - `root_pair: (int, int)`；`related_pairs: frozenset[(int,int)]` 是检查中建立的
    bisimulation：覆盖根对，且每对子节点仍落在关系内。
  - `verify_certificate(g1, g2, cert) -> bool`：独立逐条复核证书
    （根对在关系中、逐层骨架匹配、对子节点封闭），篡改后的证书返回 `False`。
- 不等价：返回 `Divergence`
  - `path: (Step, ...)`：从根对到分歧点的**最短**选择路径
    （`Step.selector` ∈ `field` / `param` / `result`，`detail` 为字段名或参数位置）；
  - `depth`：路径长度（根处分歧为 0）；
  - `mismatch: Mismatch`：种类不同 / 字段名集合不同 / 参数元数不同。
- `are_equivalent(...) -> bool`：布尔便捷封装。
- `root1/root2` 可在同一张图上另选比较起点（严格 int、须在范围内）。

两类结果对象均有 `render()`，`demo.py` 展示其输出形态。

## 规范化：把等价节点压成共享表示（缓存键）

缓存类型时，同一种无限展开类型可能有许多不同编号的图（共享方式不同、
子图被复制、环长不同但展开相同）。`canonicalize` 按同一等价语义把图内
互为双模拟的节点合并，返回确定编号的有限商图：

```python
from recursive_types import canonicalize

form = canonicalize(g)
form.graph      # TypeGraph：有限商图，根恒为 0，只含根可达部分
form.mapping    # tuple：mapping[旧编号] = 新编号；不可达旧节点为 None
form.classes    # tuple：classes[新编号] = 该合并类的旧节点成员（升序）
form.to_bytes() # bytes：商图的确定字节序列，可直接作缓存键
```

- **只处理根可达部分**：不可达节点不进入商图，映射为 `None`。
- **稳定等价划分**：在可达节点上按“一层标签 + 各后继所在类”迭代细分至
  不动点（最粗稳定划分 = 双模拟等价类）。不相同的类型不会因局部标签
  相同而合并。
- **确定编号**：从商图根 BFS，子节点顺序固定为“Product/Sum 字段按名排序、
  Function 参数按次序、返回最后”，首次遇到的类依次编号 0, 1, 2, …。
  编号完全由结构决定，**不用旧节点编号打破语义平局**：
  输入编号任意置换后 `to_bytes()` 字节序列不变。
- 不同共享方式、复制子图、环长不同但展开相同的图输出**同一**表示；
  原根与商图根在 `check_equivalence` 意义下等价（测试逐图复核）。

```python
>>> g1 = TypeGraph([FunctionNode((0,), 1), IntNode()], 0)          # 自环
>>> g2 = TypeGraph([FunctionNode((2,), 1), IntNode(),
...                 FunctionNode((0,), 1)], 0)                     # 双节点环
>>> canonicalize(g1).to_bytes() == canonicalize(g2).to_bytes()
True
>>> canonicalize(g2).mapping
(0, 1, 0)
```


## 输入上限

| 边界 | 值 | 处理 |
| --- | --- | --- |
| 单图节点数 | 1..300 | 越界抛 `GraphSizeError` |
| 节点编号 | 严格 `int`，`0 <= i < n` | bool 抛 `InvalidNodeError`；越界/负数抛 `DanglingEdgeError` |
| Product/Sum 元数 | 字段数 >= 1，字段名非空 str、同节点唯一 | 否则 `ArityError` / `InvalidNodeError` / `DuplicateFieldError` |
| Function 元数 | 有序参数 >= 1，返回恰好 1 个 | 否则 `ArityError`；目标越界为 `DanglingEdgeError` |
| 根 | 严格 int、非 bool、在范围内 | 否则 `InvalidRootError` |

所有错误都继承自 `RecTypeError`（构造期错误继承 `TypeGraphError`），
消息形如 `"node 1, field 0: ..."` / `"root: ..."`，**可定位、不静默纠正**。
`TypeGraph` 构造时完整校验并做防御性复制，不存在“构造半个图”的部分变更。

数值口径：本算法是离散结构判定，**没有浮点结果、没有误差/容差**。
凡要求整数的位置（节点编号、根、预算）只接受严格 `int`：
`bool`（`True/False`）显式拒绝；`float`（包括 `NaN`、`Infinity`、`1.0`）
在类型层面一律拒绝。

## 搜索预算：与“证明无解”严格分开

`budget`（默认 90 000 = 300×300 对图理论对数上界，须为正的严格 int）限定
“展开新节点对”的次数。

- 预算内得到结论：返回证书或分歧（**已证明**）。
- 结论前耗尽：抛 `BudgetExceededError`（结果**未知**），异常中带 `budget`
  与已检查对数。它**绝不会**被报告成 `Divergence`——预算耗尽 ≠ 证伪。
- 实现为迭代式（无 Python 递归深度问题）。判定等价用带假设集的协同 DFS
  并收集 bisimulation；发现不匹配后，再用对图上的 BFS 定位**最浅**分歧。
  两个搜索阶段各自受同一 `budget` 上限约束。

## 设计取舍

1. **coinductive 成对检查**：维护“已假设相等的节点对”集合，再遇同一对即成功；
   完全通过时该集合本身即 bisimulation，证书无需另算。
2. **最短分歧**：DFS 只负责快速发现不匹配，深度不保证最短；契约要求最短路径，
   故失败证据统一由对图 BFS 给出（BFS 首达的结构不匹配即最浅，回溯得路径）。
3. **Product/Sum 按名对应**：比较字段名集合，再按名取子节点，字段声明顺序无语义；
   **Function 参数按有序位置**对应，交换参数位置可被检出。
4. **编号无语义 / 共享不区分**：对图状态是 `(g1 节点, g2 节点)` 的配对；
   共享一个子节点与复制同构子节点产生相同的配对关系。
5. **规范化的确定性**：稳定划分的结果（最粗划分）在数学上唯一，与细分
   顺序无关；商图编号只由“从根 BFS + 固定子节点顺序”决定，旧节点编号
   既不参与划分也不参与编号，因此表示对输入编号置换封闭。
6. **判据范围**：equi-recursive 树等价（bisimulation）。不实现 iso-recursive
   fold/unfold、参数化多态、行类型、子类型、递归类型有效性（收缩性/可操作性）
   等行业标准中的更大子集；不宣称与任何具体语言规范兼容。

## 测试与独立参考

- `tests/reference_unfold.py` 是**独立参考**：不 import 被测判定算法，
  自行把无环图完整展开为有限嵌套元组树比较，并自带独立的对图 BFS 分歧深度。
- 36 张确定性随机无环图（固定种子）两两比较，结论与分歧深度均与参考交叉核对；
  另有字段重排、下标布局反转等“同构不同表示”用例。
- 递归用例为手工固定构造：自递归等价（μX. X→Int 两种布局）、
  双节点互递归交换布局等价、`μX.P{a:X}` 与 `μX.P{a:P{a:X}}` 包装环等价、
  函数参数顺序、深层标签差异（精确深度）、有限链 vs 递归类型在链底分歧、
  300 节点规模、预算耗尽与证伪分离、证书篡改被复核拒绝。
- 规范化用例（`tests/test_canonicalize.py`）：自环 vs 双节点同构展开、
  互递归记录复制布局、函数参数交换不得同键、不可达垃圾丢弃、
  共享 vs 复制、环长 1/2/3 同表示、局部标签相同但展开不同不得合并；
  并独立复核每个合并类的标签与后继类一致性、原根与商图根交回
  `check_equivalence` 判定、输入编号任意置换后字节序列相同；
  无环图与展开参考交叉核对（字节序列相同 iff 参考判等价）。

## 已知限制

- 仅覆盖本题契约的五种节点构造子；不支持元组、递归变量绑定、泛型等。
- Product/Sum 字段名匹配区分大小写，按精确字符串相等。
- 证书/分歧中的节点号只用于指回输入图以便人工复核，不是类型身份。
- 对图最坏规模为两图节点数之积；本题 300+300 节点上限下最坏 90 000 对，
  默认预算即按此上界设定。

## 仓库结构

```
recursive_types/          # 本题库（可 import）
  __init__.py             # 公开接口
  model.py                # 节点/Field/TypeGraph 与严格校验
  equivalence.py          # 协同检查、bisimulation 证书、BFS 最短分歧、预算
  canonicalize.py         # 双模拟合并、有限商图、确定编号、缓存键
  errors.py               # 可定位错误层级与 BudgetExceededError
tests/
  reference_unfold.py     # 独立参考（不调用被测核心判定）
  test_model_validation.py
  test_equivalence.py
  test_canonicalize.py
demo.py                   # 固定输入：等价证书 + 最短分歧 + 构造期拒绝 + 规范化
```
