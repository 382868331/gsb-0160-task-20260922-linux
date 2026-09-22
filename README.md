# rectypes — 显式节点递归类型的 equi-recursive 等价检查

在有根、显式节点的类型图上判定两个类型按**无限展开树**是否等价
（equi-recursive equivalence），输出：

* 等价时：一个**互模拟关系证书**（节点对集合），并由独立验证器复核；
* 不等价时：一条**展开深度最短的分歧路径**及分歧原因。

纯 Python 标准库实现，核心算法从零书写，不调用任何第三方类型检查实现。

## 环境与依赖

* Python **3.14.7**（使用 3.14 可运行；开发与验证版本为 3.14.7），Linux 原生。
* **无第三方依赖**：不需要安装任何包，不需要网络、账号、密钥、数据库、
  中间件、云 API 或 Docker。
* 无浮点计算输出：判定完全是离散结构操作，不存在浮点误差/容差口径；
  作为输入约束，任何数值位置出现 `NaN`/`Infinity`/`-Infinity` 都会被拒绝。

## 准确命令

```bash
# 必要测试（49 个用例）
python -m unittest discover -s tests -v

# 固定输入演示（约 0.04 秒，远低于 8 秒）
python demo.py
```

## 数据结构与公开接口

节点是普通 `dict`，节点标识为任意 `str` 或非 `bool` 的 `int`
（标识只用于在图内定位边，**绝不参与语义**）：

| kind | 形式 |
|---|---|
| `Int` | `{"kind": "Int"}` |
| `Bool` | `{"kind": "Bool"}` |
| `Product` | `{"kind": "Product", "fields": [("a", 目标), ...]}` |
| `Sum` | `{"kind": "Sum", "fields": [("A", 目标), ...]}` |
| `Function` | `{"kind": "Function", "params": [目标, ...], "result": 目标}` |

构造：

```python
from rectypes import TypeGraph, check_equivalence, are_equivalent, verify_certificate

g = TypeGraph(nodes, root="r")          # 构造即完整校验
result = check_equivalence(g1, g2)      # EquivalenceResult
result.equivalent                       # bool
result.certificate                      # 等价时：Certificate
result.divergence                       # 不等价时：Divergence
verify_certificate(result.certificate, g1, g2)   # 独立验证器，合法返回 True
```

`EquivalenceResult` 字段：

* `equivalent: bool`；
* `certificate: Certificate | None`：`roots` 根对、`pairs` 关系全部节点对；
* `divergence: Divergence | None`：`steps`（每步含左右节点与访问子
  `root` / `("field", 名)` / `("param", 下标)` / `("result",)`）、
  `reason`、`depth`（根对为 0）、`clashing_pair`，`render()` 可打印；
* `work_units: int`：实际消耗的工作单元数。

便捷布尔接口：`are_equivalent(g1, g2)`。

### 对应规则（契约核心）

* `Int`/`Bool`：同种原子一致，异种冲突；
* `Product`/`Sum`：字段名/**标签名集合必须相同**，按名对应子节点
  （字段书写顺序无意义）；
* `Function`：参数个数相同、**按位置**有序对应，返回值单独对应；
* 本库只实现**结构相等**（equi-recursive equivalence），不实现子类型、
  不实现函数参数逆变/返回协变的变型规则，也不宣称任何行业标准类型系统兼容。

## 输入上限与校验错误语义

* 单图节点数上限 **300**（`rectypes.MAX_NODES`），超限抛
  `GraphTooLargeError`；
* 边目标/根必须存在，否则 `DanglingEdgeError`（错误信息含来源节点）；
* 元数错误抛 `ArityError`：空 `Product`/空 `Sum`、`Function` 无参数或缺返回；
* 同节点内字段/标签名重复抛 `DuplicateFieldError`；
* 存在根不可达节点抛 `UnreachableNodeError`（有根图不允许携带语义不明的
  冗余节点）；
* 键或字段类型错误、非法 kind、字段名非 `str`、节点标识为 `bool`/`float`
  等抛 `InvalidNodeError`；**整数参数显式拒绝 `bool`**（不静默当作 1）；
* 任何数值输入拒绝 `NaN`/`Infinity`/`-Infinity`（`InvalidNodeError`）；
* 所有校验异常继承 `RecTypeError`，且带 `location` 尽量定位到节点/字段。

构造是**原子的**：校验失败时不返回 `TypeGraph` 对象，输入映射不被修改，
不存在“建了一半”的图。库本身无全局可变状态。

### 预算：耗尽 ≠ 证明无解

`check_equivalence(g1, g2, budget=None)` 的预算以“处理的节点对数”为工作
单元。默认 `len(g1)*len(g2) + 1`，在 300 节点上限内数学上必然够用，
因此默认配置不会耗尽。显式传入更小预算时：

* 预算先于结论用完 → 抛 `BudgetExhaustedError`（带已用单元数与预算值），
  语义是**“无结论”**；
* 已发现头冲突 → 正常返回 `equivalent=False` 与 `Divergence`，即**证明无解**。

两者在类型与控制流上严格分开，调用方不会把“没算完”误判成“不等价”。

## 设计取舍

1. **乘积图上的有界关系（互模拟）**：从根对协同展开，头一致就把同名字段对/
   按位参数对/返回对作为义务加入；再次遇到已访问对即闭合（吸收递归）。
   访问过且无冲突的对集合本身就是互模拟，即等价证书。理论依据是正则无限树
   相等与互模拟一致（余归纳）。复杂度 O(n1·n2·k)（k 为节点元数）。
2. **BFS 保证最短分歧**：节点对按展开深度出队，第一个头冲突所在深度即最浅
   分歧深度；父链还原具体路径。遍历顺序确定（字段名按字典序、参数按位置、
   返回最后），输出可复现。
3. **证书独立可验证**：`verify_certificate` 在 `certificate.py` 中独立重写
   一致性规则，不导入 `checker`；checker 返回证书前也调用它自检。
4. **节点编号无语义**：比较只看 kind、字段名集合、位置结构；重命名节点、
   共享子图 vs 逐份复制子图结果相同（有测试覆盖）。
5. **无环图有限树展开作独立参考**：`tests/reference.py` 不导入 checker，
   把无环图展开成嵌套元组（字段用 `frozenset` 消除书写顺序）做结构相等，
   并独立 BFS 计算最浅分歧深度；差分测试固定种子生成 400 对随机无环图
   逐对核对结论与深度。循环图的自反/对称/改名往返只作补充性质测试。

## 模块布局

```
rectypes/
  __init__.py      公开名称统一导出
  model.py         TypeGraph、节点规范化与全部结构校验
  checker.py       协同 BFS、EquivalenceResult/Divergence/Step、预算
  certificate.py   Certificate 与独立验证器 verify_certificate
  errors.py        异常层级（均带定位信息）
tests/
  test_validation.py            校验/错误语义/上限边界
  test_checker.py               手写语义用例（自递归、互递归、参数顺序、深处标签…）
  test_reference_acyclic.py     对独立展开参考的差分测试
  test_properties.py            循环图上的补充性质
  reference.py                  独立参考（不依赖 checker）
demo.py                          固定输入演示
```

## 已知限制

* 仅 5 种节点构造（Int/Bool/Product/Sum/Function）；没有递归类型变量
  名、μ 绑定语法、多态、泛型、子类型或变型；
* 只判定 equi-recursive 结构相等，不做 iso-recursive fold/unfold；
* Product/Sum 字段按“同名对应”，不支持位置记录、字段重命名等价或重载；
* 图规模硬上限 300 节点（接口边界）；
* 证书是显式节点对关系（至多 n1·n2 对），不输出树文法或 SMT 编码。
