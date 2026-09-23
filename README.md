# 显式节点的递归类型判定：equi-recursive 等价 + 结构子类型

一个零依赖、纯标准库的 Python 题库：输入**显式节点、可能含环**的有根类型图，
提供两个并列的判定入口：

1. **equi-recursive 等价**：按无限展开树逐路径同构，成对协同检查，返回等价
   关系（bisimulation）证书或**最短**分歧路径；
2. **结构子类型**（本次新增）：只读记录字段协变 + 宽度子类型、函数参数逆变 /
   返回协变、Sum 反向宽度，协递归检查，返回带极性的模拟关系证书或**最浅**
   违反类型路径。

构造期拒绝悬空边、错误元数，以及**无保护递归**（如 μX.X，只经过透明别名边
的环）。

- Python：**3.14.7**（仅使用 3.10+ 通用语法，不依赖任何第三方包）
- 依赖：**无**。安装 Python 后直接运行；核心、测试、演示全部离线。
- 不使用网络、账号、密钥、数据库、中间件、云 API 或 Docker。

## 运行命令

```bash
# 全部测试（90 个用例；保留原有 47 个，新增 43 个）
python -m unittest discover -s tests -v

# 固定输入演示（真实计算；本机实测 < 0.1 秒，远低于 90 秒要求）
python demo.py
```

## 公开数据结构

```python
from recursive_types import (
    TypeGraph, Field,
    IntNode, BoolNode, ProductNode, SumNode, FunctionNode, AliasNode,
    # 等价
    check_equivalence, are_equivalent, verify_certificate,
    EquivalenceCertificate, Divergence,
    # 结构子类型
    check_subtype, is_subtype, verify_subtype_certificate,
    SubtypingCertificate, SubtypeFailure,
)

TypeGraph(nodes, root)
# nodes: list/tuple，下标即节点编号；root: 严格 int，非 bool
IntNode()
BoolNode()
ProductNode((Field("a", 目标编号), ...))   # >=1 个字段，同节点内字段名唯一
SumNode((Field("x", 目标编号), ...))       # >=1 个字段，同节点内字段名唯一
FunctionNode((参数编号, ...), 结果编号)     # >=1 个有序参数 + 1 个返回
AliasNode(目标编号)                         # 透明别名（μ 变量使用点），恰好 1 条边
```

节点种类：`Int`、`Bool`（叶子）、`Product`、`Sum`（命名字段集合）、
`Function`（有序参数 + 返回）、`Alias`（**透明**：语义上等同其目标，不产生
结构层）。节点编号**只用于在单张图内表达边与回边**，不参与图间语义；
共享子图与复制子图不区分。

### 受保护递归（guarded / contractive recursion）

`Alias` 用来显式表示递归变量的使用点（μ 变量引用）。一个从根可达的环若
**只经过 Alias 边**（`μX. X`、或一条纯别名链绕回自身），展开后不产生任何
有限层结构，这样的类型没有合法的无限树，`TypeGraph` 构造时直接抛
`UnguardedRecursionError`，消息给出无保护环上的节点序列，例如

```
unguarded recursive type: alias-only cycle node 0 -> node 1 -> node 2 -> node 0; ...
```

环上含任一结构构造子即受保护：`μX. Product{a: X}`、`μX. X -> Int` 合法；
旧代码中直接用结构节点自指/互指表达递归的写法全部继续合法（等价于守卫内联）。
不可达部分的无保护环不影响根类型的树，允许存在；换一个能到达该环的根重新
构造则会被拒绝（不存在“半个图”状态）。

## 接口与返回值

### 等价

```python
result = check_equivalence(g1, g2, *, root1=None, root2=None, budget=90_000)
```

- 等价：返回 `EquivalenceCertificate`
  - `root_pair: (int, int)`；`related_pairs: frozenset[(int,int)]` 是检查中
    建立的 bisimulation：覆盖根对，每对子节点仍落在关系内。
  - `verify_certificate(g1, g2, cert) -> bool`：独立逐条复核；篡改返回
    `False`。
- 不等价：返回 `Divergence`，`path` 为从根对到分歧点的**最短**选择路径
  （`Step.selector` ∈ `field` / `param` / `result`），`depth` 为路径长度，
  `mismatch` 说明种类 / 字段名集合 / 参数元数分歧。
- `are_equivalent(...) -> bool`：布尔便捷封装。

### 结构子类型

```python
result = check_subtype(g_sub, g_super, *, root_sub=None, root_super=None,
                       budget=180_000)
```

判定 **`g_sub` 的根类型 <: `g_super` 的根类型**，逐层规则：

| 构造子 | 规则 |
| --- | --- |
| `Int` / `Bool` | 仅自身是自身子类型；不同构造子之间无子类型关系 |
| `Product`（只读记录） | **字段协变 + 宽度子类型**：超类型要求的每个字段子类型都必须具备，且对应字段类型 `S.f <: T.f`；子类型可以**多出**字段 |
| `Sum`（变体） | **成分协变 + 反向宽度**：子类型提供的每个变体超类型都必须接受；超类型可以**多分**支 |
| `Function` | **参数逆变、返回值协变、元数不变**：元数相同；参数要求 `T.Pj <: S.Pj`，返回要求 `S.R <: T.R` |
| `Alias` | 透明，比较前沿别名链归一到结构节点，不计结构层、不计深度 |

- 成立：返回 `SubtypingCertificate`
  - `root_pair: (int, int)`（已归一到结构节点）；
  - `related_pairs: frozenset[(a, b, reversed)]` 是检查中建立的**带极性
    模拟关系**：`reversed=False` 表示已证 `g_sub[a] <: g_super[b]`，
    `True` 表示逆变位置产生的反向义务 `g_super[b] <: g_sub[a]`；
  - `verify_subtype_certificate(...) -> bool`：独立逐条复核根义务在关系中、
    每层规则成立、全部子义务（含逆变翻转后的极性）仍在关系内。
- 不成立：返回 `SubtypeFailure`
  - `path: (Step, ...)` 是从根到**最浅**违反点的类型路径
    （`field(名)` / `param(k)` / `result`）；`depth` 为长度；
  - `mismatch` 给出原因（种类不同 / Product 缺字段 / Sum 多分支 / 参数元数），
    两侧集合都列出，可直接定位。
- `is_subtype(g_sub, g_super, ...) -> bool`：布尔便捷封装。
- `root_sub/root_super` 可在同一图上另选比较起点（严格 int、须在范围内）。

两类证书、两类失败对象均有 `render()`，`demo.py` 展示输出形态。

### 子类型规则的一个手算例（逆变递归）

```
S = μX. X -> {a, b}      T = μY. Y -> {a}
```

`S <: T` 在根处要求参数位 `T <: S`（逆变），其返回位又要求 `{a} <: {a,b}`，
但窄记录缺字段 `b` —— 最浅违反恰在 `param(0) -> result`（depth 2）。
协递归检查靠“带极性义务的假设集”得到这一结论：同一带极性义务再次出现即
按假设成功；极性相反或结构不匹配则继续找最浅违反。

## 输入上限

| 边界 | 值 | 处理 |
| --- | --- | --- |
| 单图节点数 | 1..300 | 越界抛 `GraphSizeError` |
| 节点编号 | 严格 `int`，`0 <= i < n` | bool 抛 `InvalidNodeError`；越界/负数抛 `DanglingEdgeError` |
| Product/Sum 元数 | 字段数 >= 1，字段名非空 str、同节点唯一 | 否则 `ArityError` / `InvalidNodeError` / `DuplicateFieldError` |
| Function 元数 | 有序参数 >= 1，返回恰好 1 个 | 否则 `ArityError`；目标越界为 `DanglingEdgeError` |
| Alias | 恰好 1 个严格 int 目标且在范围内 | 越界为 `DanglingEdgeError`；bool/float 为 `InvalidNodeError` |
| 根 | 严格 int、非 bool、在范围内 | 否则 `InvalidRootError` |
| 根可达递归 | 不允许纯 Alias 环 | 抛 `UnguardedRecursionError`（消息含环上节点序列） |

所有错误都继承自 `RecTypeError`（构造期错误继承 `TypeGraphError`），
消息形如 `"node 1, field 0: ..."` / `"root: ..."`，**可定位、不静默纠正**。
`TypeGraph` 构造时完整校验并做防御性复制，非法输入直接抛错，不会留下
半构造对象。

数值口径：本算法是离散结构判定，**没有浮点结果、没有误差/容差**。
凡要求整数的位置（节点编号、根、预算）只接受严格 `int`：
`bool`（`True/False`）显式拒绝；`float`（包括 `NaN`、`Infinity`、`1.0`）
在类型层面一律拒绝。

## 搜索预算：与“证明无解”严格分开

- 等价检查 `budget` 默认 90 000（300×300 对图理论对数上界）。
- 子类型检查 `budget` 默认 180 000：带极性义务状态最多 2×300×300 个，
  接口边界内的合法输入不会因默认预算中断；常量为 `DEFAULT_SUBTYPE_BUDGET`。
- 预算均须为正的严格 int，限定“展开新义务对”的次数。
- 预算内得到结论：返回证书或失败路径（**已证明**）。
- 结论前耗尽：抛 `BudgetExceededError`（结果**未知**），带 `budget` 与已检查
  对数；它**绝不会**被报告成 `Divergence` / `SubtypeFailure`——预算耗尽 ≠
  证伪。
- 两个入口均为迭代式实现（无 Python 递归深度问题）：判定成立用带假设集的
  协同 DFS 收集关系；发现不成立后再用对图 BFS 定位**最浅**分歧/违反。
  两个搜索阶段各自受同一 `budget` 上限约束。

## 设计取舍

1. **coinductive 成对检查**：维护“已假设成立的（带极性）节点对”集合，
   再遇同一义务即成功；完全通过时该集合本身即证书，无需另算。
2. **最短分歧/违反**：DFS 只负责快速发现不匹配，深度不保证最短；契约要求
   最短路径，故失败证据统一由对图 BFS 给出（BFS 首达的不匹配即最浅）。
3. **Product/Sum 按名对应**：比较字段名集合，再按名取子节点，字段声明顺序
   无语义；**Function 参数按有序位置**对应。
4. **编号无语义 / 共享不区分**：对图状态是节点对；共享子节点与复制同构
   子节点产生相同的配对关系。
5. **Alias 透明但不沉默**：别名只用于显式表达 μ 变量引用，使“无保护递归”
   可被*定位*；比较与深度都在结构节点层进行（别名不计结构层）。
6. **字段极性**：本库的 `Field` 只表示**只读**字段，故字段一律协变；
   数据模型没有可变单元/可写字段构造子，因此**不实施**“可写字段不变”
   （invariant）规则——这是模型边界而非遗漏：若加入可变字段，其字段类型
   须同时满足 `S.f <: T.f` 与 `T.f <: S.f`（即不变）。本库不宣称覆盖含
   可写引用的命令式类型系统子集。
7. **判据范围**：equi-recursive 树等价（bisimulation）与上述结构子类型
   （simulation）。不实现 iso-recursive fold/unfold、参数化多态、行类型、
   深度可变性、递归类型有效性中超出“受保护性”的部分（如弱可操作性奇偶条件），
   不宣称与任何具体语言规范兼容。

## 测试与独立参考

- `tests/reference_unfold.py`：等价的独立参考（无环图完整展开为有限元组树 +
  独立 BFS 分歧深度），不 import 被测判定算法。
- `tests/reference_subtype.py`：子类型的独立参考（展开树上的独立子类型判据
  + 带极性的独立 BFS 最浅违反深度），同样不调用被测核心。
- 36 张确定性随机无环图（固定种子）两两比较，结论与（不）成立路径深度均与
  独立参考交叉核对；另有字段重排、下标布局反转等等价用例。
- 递归用例为手工固定构造：
  - 等价：自递归两种布局、双节点互递归交换布局、包装环、300 节点规模、
    有限链 vs 递归类型；
  - 子类型：宽度/反向宽度、字段协变、参数逆变、返回协变、元数不变、
    `μX.{a:X,b:Int} <: μY.{a:Y}` 协递归宽度、逆变递归两步反例（精确深度，
    与独立 BFS 核对）、300 节点宽度链；
  - 受保护性：μX.X 与多节点纯别名环拒绝、环上含守卫合法、守卫必须在环上、
    不可达环允许、换根拒绝、Alias 透明（深度不计别名层）；
  - 预算：耗尽与证伪严格分离、篡改证书被复核拒绝。

## 已知限制

- 仅覆盖契约内的六种节点构造子；不支持元组、递归变量绑定的其他形式、
  泛型、可变字段（只读模型，字段恒协变）。
- Product/Sum 字段名匹配区分大小写，按精确字符串相等。
- 证书/失败中的节点号只用于指回输入图以便人工复核，不是类型身份。
- 对图最坏规模：等价为两图节点数之积（90 000），子类型带极性为其两倍
  （180 000），默认预算按各自上界设定。
- 受保护性只拒绝“根可达的纯 Alias 环”；不对别名链长度做额外限制
  （单出边链解析为线性，并按图缓存）。

## 仓库结构

```
recursive_types/          # 本题库（可 import）
  __init__.py             # 公开接口
  model.py                # 节点/Field/Alias/TypeGraph、严格校验、受保护性检查
  equivalence.py          # 协同等价检查、bisimulation 证书、BFS 最短分歧、预算
  subtyping.py            # 结构子类型：带极性模拟关系、BFS 最浅违反、预算
  errors.py               # 可定位错误层级、UnguardedRecursionError、BudgetExceededError
tests/
  reference_unfold.py     # 等价独立参考（不调用被测核心判定）
  reference_subtype.py    # 子类型独立参考（展开树判据 + 独立 BFS）
  test_model_validation.py
  test_equivalence.py
  test_subtyping.py
  test_guarded_recursion.py
demo.py                   # 固定输入：等价、分歧、子类型成立/失败、构造期拒绝
```
