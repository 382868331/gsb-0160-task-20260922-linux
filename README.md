# 显式节点的递归类型：equi-recursive 等价检查 + 结构子类型判断

一个零依赖、纯标准库的 Python 题库：输入**显式节点、可能含环**的有根类型图。

- **等价检查**：按无限展开树的 equi-recursive 等价做**成对协同检查**，
  返回等价关系（bisimulation）证书或**最短**分歧路径；
- **结构子类型判断**（本次新增）：记录只读字段协变、可写字段不变，
  函数参数逆变、返回值协变，记录支持宽度子类型；返回模拟关系证书或
  带可定位类型路径的失败；
- 构造期拒绝悬空边、错误元数与**无保护递归**（μX.X 型方程）。

- Python：**3.14.7**（仅使用 3.10+ 通用语法，不依赖任何第三方包）
- 依赖：**无**。安装 Python 后直接运行；核心、测试、演示全部离线。
- 不使用网络、账号、密钥、数据库、中间件、云 API 或 Docker。

## 运行命令

```bash
# 全部测试（84 个用例：原 47 个等价/模型用例 + 37 个子类型/递归有效性用例）
python -m unittest discover -s tests -v

# 固定输入演示（真实计算；本机实测约 0.1 秒，远低于 90 秒要求）
python demo.py
```

## 公开数据结构

```python
from recursive_types import (
    TypeGraph, Field,
    IntNode, BoolNode, ProductNode, SumNode, FunctionNode, AliasNode,
    check_equivalence, are_equivalent, verify_certificate,
    EquivalenceCertificate, Divergence,
    check_subtype, is_subtype, verify_subtype_certificate,
    SubtypeCertificate, SubtypeFailure,
    UnguardedRecursionError,
)

TypeGraph(nodes, root)
# nodes: list/tuple，下标即节点编号；root: 严格 int，非 bool
IntNode()
BoolNode()
ProductNode((Field("a", 目标编号), Field("v", 目标编号, readonly=False), ...))
SumNode((Field("x", 目标编号), ...))       # Sum 负载恒为只读
FunctionNode((参数编号, ...), 结果编号)     # >=1 个有序参数 + 1 个返回
AliasNode(目标编号)                         # 透明别名（非构造子），见下
```

节点种类：`Int`、`Bool`（叶子）、`Product`、`Sum`（命名字段集合）、
`Function`（有序参数 + 返回）、`Alias`（透明别名）。节点编号**只用于在单张
图内表达边与回边**，不参与两张图之间的语义；共享子图与复制子图不区分。

### 字段可变性与 Alias

- `Field(name, target, readonly=True)`：`readonly=True`（默认，旧构造调用
  完全不变）为只读字段；`readonly=False` 为可写字段。只接受严格 `bool`。
  Sum 的负载恒为只读，给 Sum 传可写字段在构造期拒绝。
- `AliasNode(target)` 是**透明**节点：唯一一条裸边，本身不是类型构造子，
  在等价与子类型检查中被直接穿透。它用于表达递归方程中“无构造子包裹”的
  位置；**只经过 Alias 的环即无保护递归**（μX.X），构造期拒绝，错误消息给出
  完整环路径（如 `1 -> 2 -> 1`）。环上只要经过任意 Product/Sum/Function
  构造子就是**受保护递归**，正常处理（μX. X→Int 这类无需 Alias，本身受保护）。

## 接口与返回值

### 等价（旧入口，行为保持兼容）

```python
result = check_equivalence(g1, g2, *, root1=None, root2=None, budget=90_000)
```

- 等价：返回 `EquivalenceCertificate`（`related_pairs` 为 bisimulation，
  `verify_certificate(...)` 独立逐条复核）；
- 不等价：返回 `Divergence`（BFS 给出的**最短**分歧路径 `path`/`depth`）；
- `are_equivalent(...) -> bool` 为布尔封装。
- 新增可变性后，等价要求同名字段的 `readonly` 标记也一致
  （只读字段与可写字段不等价；旧图全部默认只读，原有结果不变）。

### 结构子类型（本次新增入口）

```python
result = check_subtype(g_sub, g_super, *, root1=None, root2=None, budget=270_000)
```

判定 `g_sub[root1] <: g_super[root2]`（第一个参数是**子类型方**）。

- 成立：返回 `SubtypeCertificate`
  - `entries: frozenset[(relation, node1, node2)]` 是检查中建立的模拟关系：
    `"sub" (a,b)` = g1[a] <: g2[b]；`"sup" (a,b)` = g2[b] <: g1[a]
    （函数参数逆变产生）；`"eq" (a,b)` = g1[a] ≡ g2[b]（可写字段的不变要求）。
  - 覆盖根义务 `("sub", root1, root2)`，每条义务的直接子义务仍在关系内；
  - `verify_subtype_certificate(g1, g2, cert) -> bool` 独立逐条复核，
    篡改后的证书返回 `False`。
- 不成立：返回 `SubtypeFailure`
  - `path: (Step, ...)`：从根对到规则违反点的**可定位类型路径**，
    每步为 `field(<字段名>)` / `param(<位置>)` / `result()`；`depth` 为长度；
  - `mismatch: Mismatch`：宽度缺字段、可变性不满足、种类不同、元数不同等。
  - 本迭代不要求最短失败路径证明；路径为 DFS 顺序找到的第一条违反路径。
- `is_subtype(...) -> bool` 为布尔封装；预算耗尽仍抛异常。

两类结果对象均有 `render()`，`demo.py` 展示其输出形态。

### 子类型规则（对无限展开树成立，equi-recursive）

| 构造子 | 规则 |
| --- | --- |
| Int / Bool | 同种类才可互为子类型 |
| Product（记录） | **宽度**：超类型字段必须都在子类型中（子类型可多出字段）；深度规则按**超类型字段**的可变性：只读 → 负载**协变**；可写 → 子侧该字段也必须可写且负载**不变**（子侧只读不能满足超类型可写） |
| Sum | 题面只给记录开宽度，故标签集合**精确一致**；负载只读，逐标签**协变** |
| Function | 参数个数相同；参数**逆变**、返回值**协变** |
| Alias | 透明穿透（无保护环已在构造期排除） |

递归类型用带假设集的协同检查判定：`sub/sup/eq` 三种关系义务再次遇到即封闭；
因此等价类型必然双向互为子类型，自反/传递性由规则本身保证（测试中有核对）。

## 输入上限

| 边界 | 值 | 处理 |
| --- | --- | --- |
| 单图节点数 | 1..300 | 越界抛 `GraphSizeError` |
| 节点编号 | 严格 `int`，`0 <= i < n` | bool 抛 `InvalidNodeError`；越界/负数抛 `DanglingEdgeError` |
| Product/Sum 元数 | 字段数 >= 1，字段名非空 str、同节点唯一 | 否则 `ArityError` / `InvalidNodeError` / `DuplicateFieldError` |
| 字段 readonly | 严格 `bool`；Sum 只允许 True | 否则 `InvalidNodeError` |
| Function 元数 | 有序参数 >= 1，返回恰好 1 个 | 否则 `ArityError`；目标越界为 `DanglingEdgeError` |
| Alias | 恰 1 个合法目标；不允许只经 Alias 成环 | 越界 `DanglingEdgeError`；无保护环 `UnguardedRecursionError`（带环路径） |
| 根 | 严格 int、非 bool、在范围内 | 否则 `InvalidRootError` |

所有错误都继承自 `RecTypeError`（构造期错误继承 `TypeGraphError`），
消息形如 `"node 1, field 0: ..."` / `"root: ..."`，**可定位、不静默纠正**。
`TypeGraph` 构造时完整校验（含全图无保护环检测）并做防御性复制，
校验失败直接抛错，不存在“构造半个图”的部分变更。

数值口径：本算法是离散结构判定，**没有浮点结果、没有误差/容差**。
凡要求整数的位置（节点编号、根、预算）只接受严格 `int`：
`bool`（`True/False`）显式拒绝；`float`（包括 `NaN`、`Infinity`、`1.0`）
在类型层面一律拒绝。

## 搜索预算：与“证明无解/不成立”严格分开

`budget` 限定“展开新关系-节点对”的次数。等价默认 90 000（300×300）；
子类型义务有 sub/sup/eq 三种标记，默认 270 000（3×300×300，覆盖接口上限
内的最坏情况）。预算须为正的严格 int。

- 预算内得到结论：返回证书或分歧/失败（**已证明**）。
- 结论前耗尽：抛 `BudgetExceededError`（结果**未知**），带 `budget`
  与已检查对数。它**绝不会**被报告成 `Divergence`/`SubtypeFailure`。
- 两个判定均为迭代式实现（无 Python 递归深度问题）。

## 设计取舍

1. **coinductive 成对检查**：维护“已假设成立的关系-节点对”集合，再遇同一
   义务即成功；完全通过时该集合本身即模拟关系，证书无需另算。
2. **可写字段不变**：可写位置既可读又可写，协变或逆变都不能同时保证两个
   方向安全，故采用行业标准的不变（双侧等价）规则；子侧只读字段不能满足
   超类型的可写要求，反之可写字段满足只读要求（宽度/协变照常）。
3. **Sum 不开宽度**：题面只给记录开宽度子类型；Sum 标签集必须精确一致，
   避免把“少一个变体”误判成子类型。
4. **无保护递归用透明 Alias 表达**：原五种构造子的每条边都带构造子，
   无法表达 μX.X；新增唯一一种非构造子节点 Alias，使“受保护/无保护”可由
   图结构直接判定，且对旧数据完全无侵入。
5. **Product/Sum 按名对应**：字段名集合比较后按名取子节点，声明顺序无语义；
   **Function 参数按有序位置**对应。
6. **编号无语义 / 共享不区分**：对图状态是关系标记加 `(g1 节点, g2 节点)`。
7. **判据范围**：equi-recursive 结构等价与结构子类型。不实现 iso-recursive
   fold/unfold、参数化多态、行类型、深度子类型等更大子集；
   不宣称与任何具体语言规范兼容。

## 测试与独立参考

- `tests/reference_unfold.py`：等价的独立参考——不 import 被测判定，
  自行把无环图展开为有限嵌套元组树比较（已支持透明 Alias），并自带独立
  对图 BFS 分歧深度。
- `tests/reference_subtype.py`：子类型的独立参考——自行展开有限树后
  直接按题面规则（宽度/协变/不变/逆变）递归判定，不 import 被测算法。
- 30 张确定性随机无环图（固定种子，含 Alias、ro/rw 字段）两两比较，
  子类型结论与独立参考全部交叉核对，成立者还复核证书；
- 一个深度 ≤2 的有限类型宇宙（ro/rw 记录、Sum、单参函数的组合）
  **全枚举约 1400 对**与独立参考逐对核对；
- 手算固定用例：宽度双向、只读协变、可写不变、ro/rw 不可互换、
  函数逆变/协变与高阶双重逆变（失败路径精确定位 `param(0) -> param(0)`）、
  Sum 无宽度而负载协变、自递归与互递归子类型、受保护/无保护递归、
  Alias 透明、300 节点规模、预算耗尽与证伪分离、证书篡改被复核拒绝；
- 解析性质（自反性、传递性、等价⇒双向子类型）在随机图集合上额外核对。

## 已知限制

- 仅覆盖本题契约的六种节点构造子；不支持元组、递归变量绑定、泛型等。
- Product/Sum 字段名匹配区分大小写，按精确字符串相等。
- 证书/失败中的节点号只用于指回输入图以便人工复核，不是类型身份。
- 子类型失败路径可定位但**不保证最短**（本次题面不要求最短失败路径证明）；
  等价的分歧路径仍保证最短（BFS）。
- 可变性只有只读/可写两档，不支持“只写”字段或效果多态。
- 对图最坏规模：等价为两图节点数之积；子类型为 3 倍节点数之积，
  默认预算即按 300 节点上限设定。

## 仓库结构

```
recursive_types/          # 本题库（可 import）
  __init__.py             # 公开接口
  model.py                # 节点/Field(含 readonly)/Alias/TypeGraph 与严格校验、无保护环检测
  equivalence.py          # 协同等价检查、bisimulation 证书、BFS 最短分歧、预算
  subtyping.py            # 结构子类型协同检查、模拟关系证书、可定位失败路径
  errors.py               # 可定位错误层级、BudgetExceededError、UnguardedRecursionError
tests/
  reference_unfold.py     # 等价独立参考（不调用被测核心判定）
  reference_subtype.py    # 子类型独立参考（不调用被测核心判定）
  test_model_validation.py
  test_equivalence.py
  test_subtyping.py       # 子类型正常/边界/失败 + 全枚举 + 递归有效性
demo.py                   # 固定输入：等价、分歧、子类型成功/失败、构造期拒绝
```
