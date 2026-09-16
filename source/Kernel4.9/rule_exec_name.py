"""P1/P2: pair pathname and opened-file checks by their shared restriction call."""

from dataclasses import dataclass

from dataflow import character_chains, contains, load, node_value_contains_call, number, split_addr
from errors import RepairGuide, Unsupported, explain_failure, one
from patch import AnalysisContext, Patch
from program import Flow

P1_GUIDE = RepairGuide(
    rule="P1",
    title="exec 打开文件前的 pathname 名称限制",
    principle="将已证明的 basename='su' 检查中首字符比较从 's' 改为 'w'，使原本针对 su 的名称匹配改为 wu，保留其余路径与限制函数。",
    locate=(
        "从 do_open_execat 的调用者中找同时调用 search_binary_handler 的共同 exec 函数，确认文件打开调用点唯一。",
        "沿打开文件之前的调用查找 strrchr(path, '/')，证明被比较的是从该结果派生的 basename，而非日志或无关字符串。",
        "跟踪逐字节加载与条件分支，证明连续检查 's'、'u' 和结尾 NUL，且匹配路径到达限制函数。",
        "再定位 P2 的已打开文件检查；两处必须共享唯一限制函数，用于排除内核中的其他 su 字符串比较。",
    ),
    modify=(
        "在上述字符链的首条 CMP Wn,#0x73 处，只把立即数改为 0x77；保留 Wn、指令宽度和后续条件分支。",
        "当前支持的 CMP immediate 编码满足 word & 0xFFC0001F == 0x7100001F；替换值为 (word & ~(0xFFF << 10)) | (0x77 << 10)，按小端写回 4 字节。必须先反汇编确认实际指令。",
        "若固件使用别的等价比较形式，应根据实际指令编码实现同一语义，不套用上述掩码，也不修改共享限制函数的入口。",
    ),
    pitfalls=(
        "缺少 do_open_execat、search_binary_handler 或 strrchr 时，先检查 kallsyms 恢复和 ELF/raw 对应关系；符号缺失不等于防护不存在。",
        "候选为 0 时检查调用是否被内联、basename 值是否经栈或别名传递、字符比较是否换序；候选大于 1 时补充调用上下文，不能选第一个。",
        "P1/P2 配对失败也可能来自 P2 或共享限制函数识别失败；逐一核对路径候选与文件候选。若原立即数已经是 'w'，检查是否输入了已修补内核。",
    ),
    verify=(
        "反汇编确认只改变首字符立即数；原 su 不再沿该字符链匹配，wu 才匹配，'u' 与 NUL 检查保持原样。",
        "核对 P1 在打开文件之前、P2 在打开文件之后，保留两者的共享限制调用证据；新增编译布局应加入正向样本和相似无关比较的反例。",
        "用已核对的 VA/raw 映射定位文件偏移，检查原字节、4 字节对齐和输出长度；不能把高位虚拟地址直接当作文件偏移。",
    ),
    sources=(
        "source/Kernel4.9/rule_exec_name.py: pathname_checks、exec_name_patches",
        "source/Kernel4.9/dataflow.py: character_chains、node_value_contains_call",
        "source/Kernel4.9/patch.py: compare_patch",
    ),
)

P2_GUIDE = RepairGuide(
    rule="P2",
    title="exec 打开文件后的 dentry 名称限制",
    principle="将已打开可执行文件的 dentry 名称检查中首字符 's' 改为 'w'，使长度为 2 的 su 不再命中这处限制，保留文件来源和长度检查。",
    locate=(
        "在 P1 使用的共同 exec 函数中，以 do_open_execat 调用为锚点，寻找由该调用支配的后续检查调用。",
        "证明检查函数的首参数来自这一次 do_open_execat 的原返回值；不能仅因寄存器相同就认为是同一个 file，必须考虑中间调用破坏和覆盖。",
        "从 file 参数追踪到 dentry、名称指针和名称长度；结构体成员偏移从本内核的加载关系推导，不能照抄其他固件。",
        "确认同一 dentry 的 32 位长度加载与常数 2 比较，且长度检查支配连续 's'/'u' 字符检查；匹配路径须与 P1 共享唯一限制函数。",
    ),
    modify=(
        "仅将已证明的首字符 CMP Wn,#0x73 改为 CMP Wn,#0x77；不要改长度常数 2、名称指针、后续 'u' 比较或 file 返回值。",
        "当前 CMP immediate 改法与 P1 相同：先核对 word & 0xFFC0001F == 0x7100001F，再仅替换 imm12 为 0x77，并按小端写回。",
    ),
    pitfalls=(
        "常见失败是无法证明 file 的原返回值、dentry 加载经由新的指令形式，或长度与字符检查被合并；应补齐对应数据流语义和 CFG 证据。",
        "长度 2 和字符串 su 单独出现都不充分；检查名称与长度是否属于同一 dentry，以及限制函数是否确实与 P1 相同。",
        "共同配对失败不能自动归因为 P2；先分别核对两个候选集合。已修补或部分修补输入也可能造成首字符原状态不再匹配。",
    ),
    verify=(
        "确认输出只改变该 CMP 的立即数，长度不是 2 的文件仍走原路径，长度为 2 的 su 不再命中这处字符匹配。",
        "保留打开调用支配关系、准确返回值来源、同一 dentry 的名称/长度与共享限制函数证据；添加原返回值被覆盖、名称长度来自不同对象的拒绝测试。",
        "通过匹配 ELF 的地址映射核对原字节和文件偏移，保持 raw 长度不变；不要对任意 su 字节序列做全局替换。",
    ),
    sources=(
        "source/Kernel4.9/rule_exec_name.py: dentry_checks、exec_name_patches",
        "source/Kernel4.9/dataflow.py: Values 的调用返回值与加载来源",
        "source/Kernel4.9/patch.py: compare_patch",
    ),
)


@dataclass
class NameCheck:
    flow: Flow
    characters: list[dict]
    restriction_calls: set[int]
    length_check: int | None = None
    file_result_call: int | None = None


def pathname_checks(context: AnalysisContext, execute: Flow, open_site: int) -> list[NameCheck]:
    program = context.program
    strrchr = program.symbol("strrchr")
    roots = set()
    for site, entry in execute.calls:
        if site == open_site or not execute.dominates(site, open_site):
            continue
        try:
            flow = program.function(entry)
            roots.add(entry)
            roots.update(callee for _, callee in flow.calls)
        except Unsupported:
            continue

    candidates = []
    for entry in sorted(roots):
        try:
            flow = program.function(entry)
            if not any(callee == strrchr for _, callee in flow.calls):
                continue
            values = context.values(entry)
            for characters in character_chains(flow, values, b"su\0"):
                if not node_value_contains_call(characters[0]["root"], strrchr):
                    continue
                if not any(
                    callee == strrchr and number(values.at(site, 1)) == ord("/")
                    for site, callee in flow.calls
                ):
                    continue
                restrictions = {
                    callee
                    for site, callee in flow.calls
                    if flow.reaches(characters[-1]["good"], site)
                }
                candidates.append(NameCheck(flow, characters, restrictions))
        except Unsupported:
            continue
    return candidates


def dentry_checks(
    context: AnalysisContext, execute: Flow, opened: int, open_site: int
) -> list[NameCheck]:
    execute_values = context.values(execute.entry)
    candidates = []
    for site, entry in execute.calls:
        if site == open_site or not execute.dominates(open_site, site):
            continue
        argument = execute_values.at(site, 0)
        if not (
            argument
            and argument[0] == "call"
            and argument[1] == opened
            and argument[2] == open_site
        ):
            continue
        flow, values = context.program.function(entry), context.values(entry)
        for characters in character_chains(flow, values, b"su"):
            name = characters[0]["root"]
            if not load(name, 64):
                continue
            dentry, _ = split_addr(name[2])
            if not load(dentry, 64) or not contains(dentry, ("arg", 0)):
                continue
            lengths = []
            for address, instruction in flow.instructions.items():
                if instruction.mnemonic != "cmp":
                    continue
                left, right = values.comparison(address)
                if (
                    load(left, 32)
                    and number(right) == 2
                    and split_addr(left[2])[0] == dentry
                    and flow.dominates(address, characters[0]["branch"])
                ):
                    lengths.append(address)
            if len(lengths) != 1:
                continue
            restrictions = {
                callee
                for address, callee in flow.calls
                if flow.reaches(characters[-1]["good"], address)
            }
            candidates.append(NameCheck(flow, characters, restrictions, lengths[0], site))
    return candidates


@explain_failure(P1_GUIDE, P2_GUIDE)
def exec_name_patches(context: AnalysisContext, selected: set[str]) -> list[Patch]:
    program = context.program
    opened = program.symbol("do_open_execat")
    binary_handler = program.symbol("search_binary_handler")
    execute = one(
        [
            flow
            for flow in program.callers(opened)
            if any(callee == binary_handler for _, callee in flow.calls)
        ],
        "exec common CFG anchored by do_open_execat/search_binary_handler",
    )
    open_site = one([site for site, callee in execute.calls if callee == opened], "file-open call")
    path_checks = pathname_checks(context, execute, open_site)
    file_checks = dentry_checks(context, execute, opened, open_site)
    pathname, dentry = one(
        [
            (pathname, dentry)
            for pathname in path_checks
            for dentry in file_checks
            if len(pathname.restriction_calls & dentry.restriction_calls) == 1
        ],
        "paired pathname/dentry su checks sharing a restriction callee",
    )
    common = one(pathname.restriction_calls & dentry.restriction_calls, "shared restriction callee")
    evidence = dict(
        exec_entry=hex(execute.entry), open_call=hex(open_site), restriction_callee=hex(common)
    )
    patches = []
    if "P1" in selected:
        patches.append(
            context.compare_patch(
                "P1",
                pathname.characters[0]["comparison"],
                "pathname su comparison",
                dict(
                    evidence,
                    function=hex(pathname.flow.entry),
                    comparisons=[hex(char["branch"]) for char in pathname.characters],
                ),
            )
        )
    if "P2" in selected:
        patches.append(
            context.compare_patch(
                "P2",
                dentry.characters[0]["comparison"],
                "opened dentry su comparison",
                dict(
                    evidence,
                    function=hex(dentry.flow.entry),
                    length_check=hex(dentry.length_check),
                    file_result_call=hex(dentry.file_result_call),
                    file_result_proof="open call dominates the original file-result use",
                ),
            )
        )
    return patches
