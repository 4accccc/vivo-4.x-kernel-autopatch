"""P3/P4: encoded mount paths and shared mount-state checks."""

from collections import defaultdict
from dataclasses import dataclass

from aarch64 import reg, target
from dataflow import number, unchanged_between
from errors import RepairGuide, explain_failure, one, require
from patch import AnalysisContext, Patch
from program import Flow

P4_GUIDE = RepairGuide(
    rule="P4",
    title="mount 内联共享 check_flags 状态门控",
    principle="清零 mount 检查共用的 check_flags 并沿原零值路径继续，使后续 bit 0/1 及完整性检查使用一致的零状态，而不只跳过某一个分支。",
    locate=(
        "从 security_sb_mount 的调用者中恢复完整 mount CFG，寻找同一 verifier 的调用：X1 分别为 11、12、13，X0 为可恢复的校验对象地址。",
        "寻找支配全部三类校验调用的 CBZ/CBNZ；其非零边能到达校验，零边不能到达校验。必须先确定两条边各自的含义，不能仅按助记符猜成功方向。",
        "确认相同状态寄存器随后用于 bit 0 和 bit 1 的 TBZ/TBNZ，且从入口门控到这些检查之间寄存器值未被改写；当前补丁要求 32 位 W 寄存器。",
    ),
    modify=(
        "若门控是 CBNZ Wt,nonzero，零值路径就是下一条指令：将该 CBNZ 替换为 MOV Wt,#0（编码 0x52800000 | t），清零后自然落入原零值路径。",
        "若门控是 CBZ Wt,zero，零值路径在跳转目标：当前实现覆盖 8 字节为 MOV Wt,#0；B zero。第二条原指令必须只有来自门控的入边，且不是其他函数入口。",
        "CBZ 方案的 B 位移必须从新 B 自身地址 site+4 计算到原 zero 目标，检查 4 字节对齐及有符号 imm26 范围；没有可独占的第二条指令就不能使用此布局。",
        "保留其他 mount/LSM 检查及返回值路径。只 NOP 掉门控或直接 RET 可能遗留非零状态、跳过正常处理或破坏后续共享逻辑。",
    ),
    pitfalls=(
        "mount check_flags gate 无候选时分别核对校验 ID 参数、共同 verifier、零/非零可达性及 bit 0/1 的寄存器来源；内联布局或寄存器复制可能需要扩展证明。",
        "不要把其他版本的独立 do_mount_check 函数入口与这处内联共享状态当成同一修改位置；本工具当前只支持已证明的 4.9 布局。",
        "No exclusive second instruction 表示覆盖会影响其他路径；应重新设计可证明的控制流修改，不能删除入边检查强行写入。候选多个时也必须继续缩小上下文。",
    ),
    verify=(
        "分别用原状态为 0、bit0、bit1、bit0|bit1 的场景检查新状态恒为 0，进入的是原零值继续路径，其他路径没有跳入被覆盖指令的中部。",
        "反汇编核对 MOV 的目标寄存器、指令宽度，以及 CBZ 方案的 B 实际目标；检查只改变预定的 4 或 8 字节范围。",
        "复用 P4 的局部执行与寄存器存活验证；新增布局应同时覆盖零值路径方向、共享状态活跃及第二条指令有外部入边的反例。",
    ),
    sources=(
        "source/Kernel4.9/rule_mount.py: find_mount_gate、mount_patch",
        "source/Kernel4.9/dataflow.py: unchanged_between",
    ),
)


@dataclass
class MountGate:
    flow: Flow
    site: int
    register: int
    bit_tests: dict[int, int]
    verifier: int
    checks: list[tuple[int, int]]


def find_mount_gate(context: AnalysisContext) -> MountGate:
    candidates = []
    for flow in context.program.callers(context.program.symbol("security_sb_mount")):
        values = context.values(flow.entry)
        groups = defaultdict(list)
        for site, callee in flow.calls:
            check_id = number(values.at(site, 1))
            if check_id in (11, 12, 13) and number(values.at(site, 0)) is not None:
                groups[callee].append((site, check_id))
        for verifier, checks in groups.items():
            if {check_id for _, check_id in checks} != {11, 12, 13}:
                continue
            for address, instruction in flow.instructions.items():
                if instruction.mnemonic not in ("cbz", "cbnz"):
                    continue
                register = reg(instruction, instruction.operands[0])
                zero, nonzero = (
                    (target(instruction), address + 4)
                    if instruction.mnemonic == "cbz"
                    else (address + 4, target(instruction))
                )
                if not all(
                    flow.dominates(address, site)
                    and flow.reaches(nonzero, site)
                    and not flow.reaches(zero, site)
                    for site, _ in checks
                ):
                    continue
                bit_tests = {}
                for site, test in flow.instructions.items():
                    if (
                        test.mnemonic not in ("tbz", "tbnz")
                        or reg(test, test.operands[0]) != register
                    ):
                        continue
                    bit = test.operands[1].imm
                    if (
                        bit in (0, 1)
                        and flow.dominates(address, site)
                        and unchanged_between(flow, address, site, register)
                    ):
                        bit_tests[bit] = site
                if set(bit_tests) == {0, 1}:
                    candidates.append(
                        MountGate(flow, address, register, bit_tests, verifier, checks)
                    )
    return one(candidates, "mount check_flags gate")


@explain_failure(P4_GUIDE)
def mount_patch(context: AnalysisContext) -> Patch:
    gate = find_mount_gate(context)
    flow, site = gate.flow, gate.site
    instruction = flow.instructions[site]
    require(
        instruction.reg_name(instruction.operands[0].reg).startswith("w"),
        "Mount flag is not a W register",
    )
    evidence = dict(
        function=hex(flow.entry),
        anchor="security_sb_mount",
        bit_tests={str(bit): hex(address) for bit, address in gate.bit_tests.items()},
        integrity_verifier=hex(gate.verifier),
        integrity_calls=[hex(site) for site, _ in gate.checks],
    )
    clear_register = 0x52800000 | gate.register
    if instruction.mnemonic != "cbz":
        return context.instruction_patch(
            "P4", site, clear_register, "clear shared mount check_flags", evidence
        )

    # The zero path is out of line. The second instruction must have no other
    # incoming edge or function entry before it can become our direct branch.
    require(
        site + 4 in flow.instructions
        and site + 4 not in context.program.entries
        and list(flow.graph.predecessors(site + 4)) == [site],
        "No exclusive second instruction for inline CBZ state clearing",
    )
    displacement = target(instruction) - (site + 4)
    require(
        displacement % 4 == 0 and -(1 << 27) <= displacement < 1 << 27,
        "Inline mount success branch outside B range",
    )
    branch = 0x14000000 | ((displacement // 4) & 0x3FFFFFF)
    after = clear_register.to_bytes(4, "little") + branch.to_bytes(4, "little")
    return Patch(
        "P4",
        site,
        context.program.read(site, 8),
        after,
        "clear shared mount check_flags and take zero path",
        dict(
            evidence,
            strategy="inline-cbz-clear-and-branch",
            zero_target=hex(target(instruction)),
            replacement_assembly=[
                f"{ins.mnemonic} {ins.op_str}" for ins in context.program.cs.disasm(after, site)
            ],
        ),
    )


P3_GUIDE = RepairGuide(
    rule="P3",
    title="编码 /system 路径替换",
    principle="按 CSharp 版本的固定字节模式，将编码后的 /system 替换为 /syswxl，保持长度和前后 NUL 不变。",
    locate=(
        "在完整 raw 内核中查找 00 92 CF C2 C9 CD DD DA 00，前后两个 00 必须参与匹配。",
        "要求唯一命中；没有命中或多处命中都拒绝，不选择第一个结果。",
    ),
    modify=("将命中的 9 字节替换为 00 92 CF C2 C9 CE C0 DB 00。",),
    pitfalls=(
        "只有中间七字节相同不构成匹配；缺少边界、编码不同或已经修补的输入均不支持。",
        "固定模式只覆盖已知编码，不自动适配其他 XOR 密钥或算法。",
    ),
    verify=("确认命中位置的替换字节正确，前后 NUL、内核长度及其他位置保持不变。",),
    sources=("source/Kernel4.9/rule_mount.py: system_path_patch",),
)


@explain_failure(P3_GUIDE)
def system_path_patch(context: AnalysisContext) -> Patch:
    program = context.program
    before = bytes.fromhex("0092cfc2c9cdddda00")
    after = bytes.fromhex("0092cfc2c9cec0db00")
    offset = program.raw.find(before)
    require(offset >= 0, "P3 encoded /system pattern not found")
    require(
        program.raw.find(before, offset + 1) < 0,
        "P3 encoded /system pattern is not unique",
    )
    return Patch(
        "P3",
        program.base + offset,
        before,
        after,
        "encoded /system path replacement",
        dict(pattern=before.hex(), matches=1),
    )
