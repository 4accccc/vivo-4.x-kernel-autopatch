"""P5/P6: shared credential guards, path identity and native exec checks."""

from dataclasses import dataclass

from capstone.arm64 import ARM64_CC_NE

from aarch64 import conditional, isimm, isreg, reg, target
from dataflow import C, Values, character_chains, contains, load, number, split_addr
from errors import RepairGuide, Unsupported, explain_failure, one, require
from patch import AnalysisContext, Patch
from program import Flow


@dataclass
class PathCheck:
    name: tuple
    branch: int
    success: int
    checks: list[int]
    evidence: dict


@dataclass
class GuardCandidate:
    flow: Flow
    values: Values
    path: PathCheck
    syscall_compare: int
    exit_wrapper: int


@dataclass
class PidSplit:
    branch: int
    tgid_value: tuple
    helper: int
    member_offset: int


@dataclass
class CleanupPath:
    sites: list[int]
    common: int
    reject: int


P5_GUIDE = RepairGuide(
    rule="P5",
    title="非 PID 1 进程的执行文件目录检查",
    principle="把已证明的目录身份 CMP/CCMP 改为 CMP XZR,XZR，令原等值成功边成立并执行原计数器清理，绕过后续 system 目录名称限制而不重算跳转偏移。",
    locate=(
        "共同入口：从 do_group_exit 反查以参数 0 尾调用它的终止包装函数，再反查同时包含 system 名称检查和原生 execve 编号 221 比较的 guard；候选必须唯一。",
        "证明嵌套安全字段 SID=1 的入口门控，以及从 task 参数加载的 32 位 PID/TGID 与 1 的分流；非 PID 1 边到达目录检查，PID 1 边到达 syscall 检查，两者不能混淆。",
        "确认 system 检查使用的名称指针来自候选 dentry，支持直接字符链或已验证的内联 XOR；该字符串用于确认路径上下文，补丁不修改它。",
        "从参与身份比较的原 dentry 向后追踪 file → mm → task 参数的加载关系，即 task→mm→exe_file→dentry；每个成员偏移必须从当前内核推导。",
        "定位候选目录项与原 dentry 的 CMP/CCMP 及紧随其后的 B.EQ/B.NE；相等边进入原成功清理，不等边进入名称检查。若为 CCMP，还要证明前置候选空值比较、NE 条件及备用 NZCV 的 Z=1。",
        "证明 mm 与 exe_file 的空值检查仍支配修改点，空值路径到达拒绝；沿成功路径确认 SP_EL0 派生的同一 32 位计数器先加 1、后减 1，并继续到原共享 PF_KTHREAD bit 21 检查。",
    ),
    modify=(
        "仅将上述 64 位身份比较指令替换为 CMP XZR,XZR：指令字 0xEB1F03FF，小端字节 ff 03 1f eb，长度固定为 4。该比较设置 Z=1，原 B.EQ 取跳转边、B.NE 取落空边。",
        "保留原条件分支、分支位移、mm/exe_file 加载与空值检查、计数器加减和共享继续路径；替换 CCMP 时也须证明强制相等会进入同一成功清理。",
        "若相等边没有经过原清理、比较和分支间有改写标志位的指令，或分支有其他入边，则不能替换比较指令，应先重新分析布局。",
    ),
    pitfalls=(
        "credential guard 或 SID/PID 分流失败属于 P5/P6 共同前提；检查 do_group_exit 锚点、尾调用包装、system 直接/编码形式和 221 比较，不代表已证明 P5 不存在。",
        "path identity comparison 无候选时检查选中目录与原目录的操作数交换、CMP/CCMP 编译变化、空指针分支、成功清理前的填充指令及 task 加载来源。",
        "counter decrement/increment 失败时核对 MRS ...,SP_EL0、32 位加减回绕、同一内存地址和支配关系；修复 aarch64/dataflow 对新指令的语义，不能取消计数器平衡校验。",
        "成功清理必须匹配当前输入，不能照抄其他固件的 task/mm/file 偏移或跳转地址；已改成 CMP XZR,XZR 的输入也会被原状态证明拒绝。",
    ),
    verify=(
        "分别模拟原目录相同、不同或候选为空时的 NZCV 和原条件分支，确认替换后均进入已证明的相等成功边；mm/exe_file 为空的前置处理仍与原代码一致。",
        "沿新路径核对同一计数器加 1/减 1 成对，保持 PF_KTHREAD 后续检查、栈与返回路径；不能把跳过减计数器的开机偶然成功作为证明。",
        "反汇编确认只写入一条 CMP XZR,XZR，后续分支字节完全不变；用同一映射核对 VA/raw 偏移与原字节，保存推导成员、空值分支和计数器证据。",
        "扩展规则时增加目录加载链破坏、清理地址不同、计数器不平衡和 CMP/CCMP 两种布局的正反例；恢复后运行完整六处回归。",
    ),
    sources=(
        "source/Kernel4.9/rule_exec_guard.py: find_guard、find_pid_split、find_sid_gate、find_cleanup",
        "source/Kernel4.9/rule_exec_guard.py: path_success_compare、prove_balanced_counter",
        "source/Kernel4.9/rule_exec_guard.py: inline_system_checks",
        "source/Kernel4.9/dataflow.py、aarch64.py: SP_EL0、加载与标志位语义",
    ),
)


@dataclass
class PathIdentity:
    comparison: int
    branch: int
    success: int
    null_guards: list[int]
    member_offsets: tuple[int, int, int]


@explain_failure(P5_GUIDE)
def path_success_compare(
    context: AnalysisContext, guard: GuardCandidate, pid_split: PidSplit, continuation: CleanupPath
) -> Patch:
    """Force the existing selected/original equality edge.

    The location, pointer members, null checks and counter address are
    recovered from the input. Only CMP XZR,XZR's ISA encoding is constant;
    no branch target or relative displacement is generated.
    """
    flow, values, path = guard.flow, guard.values, guard.path
    split, helper = pid_split.branch, pid_split.helper
    cleanup, common, reject = continuation.sites, continuation.common, continuation.reject
    name = path.name
    require(load(name, 64), "Path name must come from a dentry member")
    selected, _ = split_addr(name[2])
    candidates = []
    for branch, ins in flow.instructions.items():
        if ins.mnemonic not in ("b.eq", "b.ne"):
            continue
        success = target(ins) if ins.mnemonic == "b.eq" else branch + 4
        failure = branch + 4 if ins.mnemonic == "b.eq" else target(ins)
        if success not in cleanup:
            continue
        # A compiler may leave NOP padding on the fallthrough edge while
        # the equality edge targets the first real cleanup instruction.
        if any(
            flow.instructions[address].mnemonic != "nop"
            for address in cleanup[: cleanup.index(success)]
        ):
            continue
        flags = values.before[branch].get("flags")
        comparison = branch - 4
        compare = flow.instructions.get(comparison)
        conditional_compare = compare is not None and compare.mnemonic == "ccmp"
        if conditional_compare:
            prior = values.before[comparison].get("flags")
            if (
                compare.cc != ARM64_CC_NE
                or compare.operands[2].imm & 4 == 0
                or not prior
                or prior[:3] != ("cmp", selected, C(0))
            ):
                continue
            left, original = [
                values.operand(compare, o, values.before[comparison]) for o in compare.operands[:2]
            ]
        else:
            if not flags or flags[0] != "cmp":
                continue
            left, original, comparison = flags[1:]
        if original == selected:
            left, original = original, left
        if left != selected or original == selected or not load(original, 64):
            continue
        compare = flow.instructions[comparison]
        if (
            compare.mnemonic not in ("cmp", "ccmp")
            or not all(
                isreg(o) and compare.reg_name(o.reg).startswith("x") for o in compare.operands[:2]
            )
            or set(flow.graph.successors(comparison)) != {branch}
            or set(flow.graph.predecessors(branch)) != {comparison}
            or not flow.dominates(split, comparison)
            or not flow.reaches(helper, comparison)
            or not flow.dominates(branch, path.branch)
            or not flow.reaches(failure, path.branch)
            or flow.reaches(success, path.branch)
        ):
            continue
        # original dentry <- executable file <- mm <- task argument.
        file_value, dentry_offset = split_addr(original[2])
        if not load(file_value, 64):
            continue
        mm_value, file_offset = split_addr(file_value[2])
        if not load(mm_value, 64):
            continue
        task, mm_offset = split_addr(mm_value[2])
        if task != ("arg", 0):
            continue
        null_guards = []
        for value in (mm_value, file_value):
            guards = [
                address
                for address, instruction in flow.instructions.items()
                if instruction.mnemonic == "cbz"
                and values.at(address, reg(instruction, instruction.operands[0])) == value
                and flow.dominates(address, comparison)
                and flow.reaches(target(instruction), reject)
                and not flow.reaches(target(instruction), common)
            ]
            if len(guards) != 1:
                break
            null_guards.append(guards[0])
        if len(null_guards) == 2:
            candidates.append(
                PathIdentity(
                    comparison,
                    branch,
                    success,
                    null_guards,
                    (mm_offset, file_offset, dentry_offset),
                )
            )
    identity = one(candidates, "path identity comparison with existing success cleanup")

    increment, decrement, counter = prove_balanced_counter(guard, continuation, identity)
    return context.instruction_patch(
        "P5",
        identity.comparison,
        0xEB1F03FF,
        "force existing path-success branch with CMP XZR,XZR; retain mm/exe_file and cleanup",
        dict(
            original_comparison=flow.instructions[identity.comparison].mnemonic,
            success_branch=hex(identity.branch),
            success_cleanup=hex(identity.success),
            null_guards=[hex(address) for address in identity.null_guards],
            inferred_members=dict(
                zip(("task_mm", "mm_exe_file", "file_dentry"), map(hex, identity.member_offsets))
            ),
            counter_increment=hex(increment),
            counter_decrement=hex(decrement),
            counter_member_offset=hex(split_addr(counter)[1]),
            branch_displacement_rewritten=False,
        ),
    )


def prove_balanced_counter(
    guard: GuardCandidate, continuation: CleanupPath, identity: PathIdentity
):
    flow, values, cleanup = guard.flow, guard.values, continuation.sites

    # Prove the successful edge still balances the per-task preemption
    # counter, rather than jumping directly out of a critical section.
    def counter_store(site, delta):
        ins = flow.instructions[site]
        if (
            ins.mnemonic != "str"
            or ins.writeback
            or not ins.reg_name(ins.operands[0].reg).startswith("w")
        ):
            return None
        address = values.memaddr(ins, ins.operands[1], values.before[site])
        root, _ = split_addr(address)
        if root != ("systemreg", "sp_el0"):
            return None
        value = values.at(site, reg(ins, ins.operands[0]))
        if value == ("add", ("load", 32, address), C(delta)):
            return address
        return None

    decrements = [(address, counter_store(address, -1)) for address in cleanup]
    decrement, counter = one(
        [(site, address) for site, address in decrements if address is not None],
        "successful cleanup counter decrement",
    )
    increments = [
        address
        for address in flow.instructions
        if counter_store(address, 1) == counter
        and flow.dominates(address, identity.comparison)
        and all(flow.dominates(address, n) for n in identity.null_guards)
    ]
    increment = one(increments, "matching dominating counter increment")
    return increment, decrement, counter


P6_GUIDE = RepairGuide(
    rule="P6",
    title="credential guard 的 PID 1 原生 exec 一次性标志",
    principle="将已证明的 PID 1 原生 exec 路径上 STRB 的来源改为 WZR，让该路径写入 0 而不再置位一次性标志，保留原全局地址和其他 guard 检查。",
    locate=(
        "先与 P5 共同定位 do_group_exit 终止包装、system 名称检查、SID=1 门控及 task PID/TGID=1 分流，确认 syscall 比较位于 PID 1 分支。",
        "跟踪同一 guard 中与常数 221 的比较和等值边；221 是这里识别的 AArch64 原生 execve 编号，不能把任意 221 常数或兼容执行路径当作锚点。",
        "当前实现要求等值边以无写回 STRB 开始；证明其源值就是上述 PID/TGID 加载值，且在此分流下等于 1，而非仅在附近看见 MOV #1。",
        "解析 STRB 的地址表达式，得到非代码区中的全局字节地址；再找到比较之前读取同一字节的 LDRB/CBNZ 链，非零边须到达终止拒绝，零边须能继续到 syscall 比较。",
    ),
    modify=(
        "保留已证明 STRB 的基址、偏移与寻址方式，仅把 Rt 改为 31（WZR），从写入 1 改为写入 0；不修改 syscall 编号、PID 条件或其他全局变量。",
        "当前支持无符号立即数 STRB 编码：先确认 word & 0xFFC00000 == 0x39000000，再计算 (word & ~31) | 31，按小端写回 4 字节。其他寻址形式须重新核对对应编码。",
        "不要只 NOP 该 store：它不能保证将该位置清零；也不要修改整个 guard 的入口或所有 STRB Wn 指令。",
    ),
    pitfalls=(
        "native exec equality branch 或 byte store 失败时，检查相等方向是否变化、store 前是否插入指令、寄存器是否复制或寻址模式变化；应扩展路径证明，不直接放宽为附近任意 store。",
        "Exec flag lacks resolved global address 常见于 ADRP/ADD/加载地址表达式不受支持；核对页内偏移、别名和数据区映射，不能套用别的固件全局地址。",
        "same PID 1 latch read/write 失败表示读取与写入的地址、支配关系或拒绝路径未被证明；缺少任意一端都不足以确认一次性标志。",
        "共同 guard 定位失败可能同时影响 P5/P6；仅选择 P6 时不执行 P5 专属比较和计数器证明。",
    ),
    verify=(
        "反汇编确认只有 STRB 的源寄存器变为 WZR，目标地址与 store 宽度不变；修改范围只在 Rt 字段，raw 长度不变。",
        "模拟 PID 1 的原生 exec 等值路径，确认该字节写入 0；再进入同一检查时不会因这次写入产生的非零标志而拒绝。非 PID 1 和非 221 路径应仍沿原 CFG。",
        "验证原读取拒绝路径、syscall 比较和 SID/PID 分流均保留；记录全局字节地址、读取点、写入点、比较点及终止包装。",
        "新增布局应包含读取写入指向不同字节、源值不再由 PID=1 证明、store 使用其他寻址和分支方向相反的正反例，不能仅以发现 STRB 作为通过。",
    ),
    sources=(
        "source/Kernel4.9/rule_exec_guard.py: 共同 guard、SID/PID 分流和终止路径证明",
        "source/Kernel4.9/rule_exec_guard.py: native_exec_patch",
        "source/Kernel4.9/dataflow.py: Values.memaddr、寄存器与加载来源",
    ),
)


@explain_failure(P6_GUIDE)
def native_exec_patch(
    context: AnalysisContext, guard: GuardCandidate, split: PidSplit, cleanup: CleanupPath
) -> Patch:
    flow, values = guard.flow, guard.values
    syscall_cmp = guard.syscall_compare
    # The equality edge must write TGID, proven to equal 1 under this split.
    exec_branches = []
    for address, instruction in flow.instructions.items():
        flags = values.before[address].get("flags")
        if instruction.mnemonic in ("b.eq", "b.ne") and flags and flags[-1] == syscall_cmp:
            equal = target(instruction) if instruction.mnemonic == "b.eq" else address + 4
            exec_branches.append((address, equal))
    exec_branch, store_site = one(exec_branches, "native exec equality branch")
    store = flow.instructions[store_site]
    require(
        store.mnemonic == "strb" and not store.writeback,
        "Exec branch does not begin with byte store",
    )
    global_address = number(values.memaddr(store, store.operands[1], values.before[store_site]))
    require(
        global_address is not None and not context.program.executable(global_address),
        "Exec flag lacks resolved global address",
    )
    require(
        values.at(store_site, reg(store, store.operands[0])) == split.tgid_value,
        "Exec flag does not store TGID=1 value",
    )
    reads = []
    for address, instruction in flow.instructions.items():
        if instruction.mnemonic != "cbnz" or not flow.dominates(address, syscall_cmp):
            continue
        value = values.at(address, reg(instruction, instruction.operands[0]))
        if load(value, 8) and number(value[2]) == global_address:
            if flow.reaches(target(instruction), cleanup.reject) and flow.reaches(
                address + 4, syscall_cmp
            ):
                reads.append(address)
    flag_read = one(reads, "same PID 1 latch read/write and rejection path")
    store_word = int.from_bytes(store.bytes, "little")
    require(store_word & 0xFFC00000 == 0x39000000, "Unsupported STRB encoding")
    return context.instruction_patch(
        "P6",
        store_site,
        (store_word & ~31) | 31,
        "PID 1 native exec latch stores zero",
        dict(
            function=hex(flow.entry),
            exec_comparison=hex(syscall_cmp),
            exec_branch=hex(exec_branch),
            global_flag=hex(global_address),
            previous_flag_check=hex(flag_read),
            pid1_gate=hex(split.branch),
        ),
    )


# Known GCC loop: compare six bytes using key 0xA5 + index. Internal branch
# distances and registers are fixed; the table address and exit target are read
# from the surrounding instructions. Other layouts are intentionally rejected.
SYSTEM_LOOP = bytes.fromhex(
    "2400008b a7686038 08940211 e603002a 84044039 8400084a ff00046b "
    "a1000054 06040011 00040091 1f140071 a9feff54 df140071"
)


def inline_system_checks(program, flow, values):
    found = []
    for address, instruction in flow.instructions.items():
        if instruction.bytes != bytes.fromhex("bf0000f1"):  # CMP X5,#0
            continue
        branch, entry, loop = address + 8, address + 12, address + 20
        end = loop + len(SYSTEM_LOOP)
        if not all(pc in flow.instructions for pc in range(address, end + 4, 4)):
            continue
        if (
            program.read(address + 4, 4) != bytes.fromhex("2018467a")  # CCMP W1,#6,#0,NE
            or program.read(loop, len(SYSTEM_LOOP)) != SYSTEM_LOOP
            or flow.instructions[branch].mnemonic != "b.ne"
            or flow.instructions[end].mnemonic != "b.hi"
            or target(flow.instructions[branch]) != end + 4
            or not all(flow.dominates(branch, pc) for pc in range(entry, end + 4, 4))
        ):
            continue
        page, add = flow.instructions[entry], flow.instructions[entry + 4]
        if (
            page.mnemonic != "adrp"
            or reg(page, page.operands[0]) != 1
            or add.mnemonic != "add"
            or reg(add, add.operands[0]) != 1
            or reg(add, add.operands[1]) != 1
            or not isimm(add.operands[2])
        ):
            continue
        name, size = values.at(address, 5), values.at(address + 4, 1)
        table = number(values.at(loop, 1))
        success, failure = target(flow.instructions[end]), end + 4
        if (
            not load(name, 64)
            or not load(size, 32)
            or split_addr(name[2])[0] != split_addr(size[2])[0]
            or values.at(entry, 0) != C(0)
            or table is None
            or success not in flow.instructions
            or address <= success <= end
            or flow.reaches(failure, success)
        ):
            continue
        pointer = table + 1  # The loop loads [table + index + 1].
        if any(start <= pointer < stop for start, stop in program.ranges):
            continue
        try:
            encoded = program.read(pointer, 6)
        except Unsupported:
            continue
        keys = list(range(0xA5, 0xAB))
        if bytes(byte ^ key for byte, key in zip(encoded, keys)) != b"system":
            continue
        found.append(
            PathCheck(
                name,
                branch,
                success,
                [branch, end],
                dict(
                    kind="inline-xor-template",
                    entry=hex(entry),
                    length_branch=hex(branch),
                    name_register=5,
                    encoded_address=hex(pointer),
                    encoded_bytes=encoded.hex(),
                    inferred_keys=keys,
                    success=hex(success),
                    failure=hex(failure),
                ),
            )
        )
    return found


def find_guard(context: AnalysisContext) -> GuardCandidate:
    exit_address = context.program.symbol("do_group_exit")
    wrappers = []
    for flow in context.program.callers(exit_address):
        values = context.values(flow.entry)
        if flow.calls:
            continue
        if any(
            callee == exit_address and number(values.at(address, 0)) == 0
            for address, callee in flow.tails
        ):
            wrappers.append(flow.entry)
    candidates = []
    for wrapper in wrappers:
        for flow in context.program.callers(wrapper):
            try:
                values = context.values(flow.entry)
                chains = character_chains(flow, values, b"system")
                paths = [
                    PathCheck(
                        c[0]["root"],
                        c[0]["branch"],
                        c[-1]["good"],
                        [test["branch"] for test in c],
                        dict(kind="direct-character-chain"),
                    )
                    for c in chains
                ]
                syscall_cmps = [
                    address
                    for address, instruction in flow.instructions.items()
                    if instruction.mnemonic == "cmp"
                    and number(values.comparison(address)[1]) == 221
                ]
                if len(syscall_cmps) == 1:
                    paths += inline_system_checks(context.program, flow, values)
                    if len(paths) == 1:
                        candidates.append(
                            GuardCandidate(flow, values, paths[0], syscall_cmps[0], wrapper)
                        )
            except Unsupported:
                continue
    return one(candidates, "credential guard with system path/native exec test")


def find_pid_split(guard: GuardCandidate) -> PidSplit:
    flow, values, path = guard.flow, guard.values, guard.path
    syscall_cmp = guard.syscall_compare
    splits = []
    for address, instruction in flow.instructions.items():
        if instruction.mnemonic not in ("b.eq", "b.ne"):
            continue
        flags = values.before[address].get("flags")
        if not flags or flags[0] != "cmp" or number(flags[2]) != 1 or not load(flags[1], 32):
            continue
        equal, other = (
            (target(instruction), address + 4)
            if instruction.mnemonic == "b.eq"
            else (address + 4, target(instruction))
        )
        if (
            flow.dominates(address, syscall_cmp)
            and flow.dominates(address, path.branch)
            and flow.reaches(equal, syscall_cmp)
            and not flow.reaches(equal, path.branch)
            and flow.reaches(other, path.branch)
            and not flow.reaches(other, syscall_cmp)
        ):
            task, task_offset = split_addr(flags[1][2])
            if task == ("arg", 0):
                splits.append(PidSplit(address, flags[1], other, task_offset))
    return one(splits, "PID 1/helper CFG split")


def find_sid_gate(guard: GuardCandidate, split: int) -> int:
    flow, values = guard.flow, guard.values
    sid_gates = []
    for address, instruction in flow.instructions.items():
        if (
            instruction.mnemonic not in ("b.eq", "b.ne")
            or address == split
            or not flow.dominates(address, split)
        ):
            continue
        flags = values.before[address].get("flags")
        if flags and flags[0] == "cmp" and number(flags[2]) == 1 and load(flags[1], 32):
            equal, unequal = (
                (target(instruction), address + 4)
                if instruction.mnemonic == "b.eq"
                else (address + 4, target(instruction))
            )
            if (
                flow.reaches(equal, split)
                and not flow.reaches(unequal, split)
                and contains(flags[1], ("arg", 0))
            ):
                base, _ = split_addr(flags[1][2])
                if load(base, 64):
                    sid_gates.append(address)
    return one(sid_gates, "nested security SID=1 gate")


def find_cleanup(guard: GuardCandidate) -> CleanupPath:
    """Follow the successful name check to the shared PF_KTHREAD test."""
    flow, values, path = guard.flow, guard.values, guard.path
    wrapper = guard.exit_wrapper
    at, seen, common = path.success, set(), None
    cleanup = []
    while at not in seen and len(seen) < 128:
        seen.add(at)
        instruction = flow.instructions[at]
        next_instruction = flow.instructions.get(at + 4)
        if (
            instruction.mnemonic == "ldr"
            and next_instruction is not None
            and next_instruction.mnemonic in ("tbz", "tbnz")
            and reg(instruction, instruction.operands[0])
            == reg(next_instruction, next_instruction.operands[0])
            and next_instruction.operands[1].imm == 21
        ):
            common = at
            break
        if instruction.mnemonic == "b":
            common = target(instruction)
            break
        require(
            not conditional(instruction) and instruction.mnemonic not in ("bl", "ret"),
            "Ambiguous path-check success cleanup",
        )
        cleanup.append(at)
        at += 4
    require(common in flow.instructions, "No shared guard continuation")
    first = flow.instructions[common]
    tests = [
        b for b in flow.graph.successors(common) if flow.instructions[b].mnemonic in ("tbz", "tbnz")
    ]
    test = one(tests, "common task-flag check")
    flag_instruction = flow.instructions[test]
    require(
        first.mnemonic == "ldr"
        and first.reg_name(first.operands[0].reg).startswith("w")
        and reg(first, first.operands[0]) == reg(flag_instruction, flag_instruction.operands[0])
        and flag_instruction.operands[1].imm == 21,
        "Shared continuation is not PF_KTHREAD check",
    )
    mem = values.at(test, reg(flag_instruction, flag_instruction.operands[0]))
    require(
        load(mem, 32) and split_addr(mem[2])[0] == ("arg", 0), "Common flag is not loaded from task"
    )
    reject_calls = [address for address, callee in flow.calls if callee == wrapper]
    require(
        len(reject_calls) == 1 and flow.reaches(test + 4, reject_calls[0]),
        "Common failure does not terminate process",
    )
    return CleanupPath(cleanup, common, reject_calls[0])


@explain_failure(P5_GUIDE, P6_GUIDE)
def guard_patches(context: AnalysisContext, selected: set[str]) -> list[Patch]:
    guard = find_guard(context)
    split = find_pid_split(guard)
    sid = find_sid_gate(guard, split.branch)
    cleanup = find_cleanup(guard)
    patches = []
    if "P5" in selected:
        path_patch = path_success_compare(context, guard, split, cleanup)
        path_patch.evidence.update(
            function=hex(guard.flow.entry),
            sid_gate=hex(sid),
            tgid_member_offset=hex(split.member_offset),
            pid1_split=hex(split.branch),
            path_character_checks=list(map(hex, guard.path.checks)),
            path_decoder=guard.path.evidence,
            continuation=hex(cleanup.common),
            exit_wrapper=hex(guard.exit_wrapper),
        )
        patches.append(path_patch)
    if "P6" in selected:
        patches.append(native_exec_patch(context, guard, split, cleanup))
    return patches
