"""Verify patched bytes and execute P4-P6 fragments before publishing output."""

import unicorn
from capstone.arm64 import ARM64_CC_NE
from unicorn import arm64_const as arm

from aarch64 import reg, target
from dataflow import Values
from errors import RuleAnalysisError, require
from rule_exec_guard import P5_GUIDE, P6_GUIDE
from rule_exec_name import P1_GUIDE, P2_GUIDE
from rule_mount import P3_GUIDE, P4_GUIDE

THREAD, TEXT = 0x500000, 0x510000


def xreg(number):
    return getattr(arm, f"UC_ARM64_REG_X{number}")


def engine(program, ranges, raw):
    machine = unicorn.Uc(unicorn.UC_ARCH_ARM64, unicorn.UC_MODE_ARM)
    pages = {
        page for start, end in ranges for page in range(start & ~4095, (end + 4095) & ~4095, 4096)
    }
    for page in sorted(pages):
        offset = page - program.base
        require(0 <= offset < len(raw), f"Code page outside kernel: {page:#x}")
        machine.mem_map(page, 4096)
        machine.mem_write(page, raw[offset : offset + 4096])
    for page in (0x400000, THREAD, TEXT):
        machine.mem_map(page, 4096)
    machine.reg_write(arm.UC_ARM64_REG_SP, 0x401000)
    machine.reg_write(arm.UC_ARM64_REG_SP_EL0, THREAD)
    return machine


def run_until(machine, start, stops):
    def stop_at_boundary(uc, address, size, data):
        if address in stops:
            uc.emu_stop()

    hook = machine.hook_add(unicorn.UC_HOOK_CODE, stop_at_boundary)
    try:
        machine.emu_start(start, 0, timeout=1_000_000, count=4096)
    finally:
        machine.hook_del(hook)
    pc = machine.reg_read(arm.UC_ARM64_REG_PC)
    require(pc in stops, f"Execution did not reach a boundary: {pc:#x}")
    return pc


def check_p4(program, patch, output):
    instruction = program.insn(patch.address)
    register = xreg(reg(instruction, instruction.operands[0]))
    zero, nonzero = (
        (target(instruction), patch.address + 4)
        if instruction.mnemonic == "cbz"
        else (patch.address + 4, target(instruction))
    )
    ranges = [(patch.address, patch.address + 8), (zero, zero + 4), (nonzero, nonzero + 4)]
    for patched, raw in ((False, program.raw), (True, output)):
        for flags in (0, 1, 2, 3, 0xFFFFFFFF):
            for nzcv in (0, 0xF0000000):
                machine = engine(program, ranges, raw)
                machine.reg_write(register, flags)
                machine.reg_write(arm.UC_ARM64_REG_NZCV, nzcv)
                machine.emu_start(
                    patch.address,
                    0,
                    timeout=1_000_000,
                    count=len(patch.after) // 4 if patched else 1,
                )
                require(
                    machine.reg_read(arm.UC_ARM64_REG_PC)
                    == (zero if patched or not flags else nonzero),
                    "Mount gate took an unexpected branch",
                )
                require(
                    machine.reg_read(register) == (0 if patched else flags),
                    "Mount check_flags has an unexpected value",
                )
                require(
                    machine.reg_read(arm.UC_ARM64_REG_NZCV) == nzcv,
                    "Mount gate changed NZCV",
                )


def check_p5(program, patch, output):
    evidence = patch.evidence
    flow = program.function(int(evidence["function"], 16))
    comparison = program.insn(patch.address)
    branch = program.insn(int(evidence["success_branch"], 16))
    success = target(branch) if branch.mnemonic == "b.eq" else branch.address + 4
    failure = branch.address + 4 if branch.mnemonic == "b.eq" else target(branch)
    continuation = int(evidence["continuation"], 16)
    increment = int(evidence["counter_increment"], 16)
    # Supported counter increments use MRS/LDR/ADD/STR.
    increment_start = increment - 12
    require(
        program.insn(increment_start).mnemonic == "mrs",
        "Unsupported counter increment sequence",
    )
    counter = THREAD + int(evidence["counter_member_offset"], 16)
    ranges = [(flow.entry, max(flow.instructions) + 4)]
    if comparison.mnemonic == "ccmp":
        require(
            comparison.cc == ARM64_CC_NE and comparison.operands[2].imm == 4,
            "Unsupported conditional path comparison",
        )
    else:
        require(comparison.mnemonic == "cmp", "Unsupported path comparison")
    for patched, raw in ((False, program.raw), (True, output)):
        for left, right in ((TEXT, TEXT), (TEXT, TEXT + 8), (0, TEXT)):
            for nzcv in (0, 0xF0000000):
                machine = engine(program, ranges, raw)
                machine.mem_write(counter, (7).to_bytes(4, "little"))
                run_until(machine, increment_start, {increment + 4})
                require(
                    int.from_bytes(machine.mem_read(counter, 4), "little") == 8,
                    "Thread counter was not incremented",
                )
                for operand, value in zip(comparison.operands[:2], (left, right)):
                    machine.reg_write(xreg(reg(comparison, operand)), value)
                machine.reg_write(arm.UC_ARM64_REG_NZCV, nzcv)
                equal = left == right or (comparison.mnemonic == "ccmp" and bool(nzcv & 1 << 30))
                pc = run_until(machine, patch.address, {success, failure})
                require(
                    pc == (success if patched or equal else failure),
                    "Path comparison took an unexpected branch",
                )
                if pc == success:
                    run_until(machine, pc, {continuation})
                    require(
                        int.from_bytes(machine.mem_read(counter, 4), "little") == 7,
                        "Successful path did not restore the thread counter",
                    )
                else:
                    require(
                        int.from_bytes(machine.mem_read(counter, 4), "little") == 8,
                        "Failure branch unexpectedly changed the thread counter",
                    )


def check_p6(program, patch, output):
    evidence = patch.evidence
    flow = program.function(int(evidence["function"], 16))
    values = Values(flow)
    gate = program.insn(int(evidence["pid1_gate"], 16))
    start = target(gate) if gate.mnemonic == "b.eq" else gate.address + 4
    branch = program.insn(int(evidence["exec_branch"], 16))
    bypass = branch.address + 4 if branch.mnemonic == "b.eq" else target(branch)
    reject = target(program.insn(int(evidence["previous_flag_check"], 16)))
    flag = int(evidence["global_flag"], 16)
    syscall = values.comparison(int(evidence["exec_comparison"], 16))[0]
    require(syscall[0] == "arg", "Syscall number is not a function argument")
    syscall_registers = [n for n in range(31) if values.at(start, n) == syscall]
    require(syscall_registers, "Cannot initialize the syscall register")
    store = program.insn(patch.address)
    ranges = [(flow.entry, max(flow.instructions) + 4)]
    for patched, raw in ((False, program.raw), (True, output)):
        for number in (221, 11, 281):
            for initial in (0, 1):
                machine = engine(program, ranges, raw)
                # The latch may live in BSS; avoid remapping a page already loaded as code.
                for page in range((flag - 1) & ~4095, (flag + 2 + 4095) & ~4095, 4096):
                    if not any(start <= page <= end for start, end, _ in machine.mem_regions()):
                        machine.mem_map(page, 4096)
                machine.mem_write(flag - 1, bytes((0xA5, initial, 0x5A)))
                latched = initial
                for _ in range(2):
                    machine.reg_write(xreg(reg(store, store.operands[0])), 1)
                    for register in syscall_registers:
                        machine.reg_write(xreg(register), number)
                    pc = run_until(machine, start, {patch.address + 4, bypass, reject})
                    expected = reject if latched else patch.address + 4 if number == 221 else bypass
                    require(pc == expected, "PID 1 exec check took an unexpected branch")
                    if not latched and number == 221:
                        latched = int(not patched)
                    require(
                        machine.mem_read(flag - 1, 3) == bytes((0xA5, latched, 0x5A)),
                        "Exec latch or its adjacent bytes have unexpected values",
                    )


def verify(program, patches, output, log):
    guides = {
        guide.rule: guide for guide in (P1_GUIDE, P2_GUIDE, P3_GUIDE, P4_GUIDE, P5_GUIDE, P6_GUIDE)
    }
    checks = {"P4": check_p4, "P5": check_p5, "P6": check_p6}
    results = {}
    for patch in patches:
        try:
            log(f"Verifying {patch.id}" + (" with Unicorn" if patch.id in checks else " bytes"))
            require(len(output) == len(program.raw), "Patched kernel size changed")
            offset = patch.address - program.base
            require(
                output[offset : offset + len(patch.after)] == patch.after,
                "Patched bytes do not match the planned replacement",
            )
            if patch.id in checks:
                checks[patch.id](program, patch, output)
            results[patch.id] = "unicorn-passed" if patch.id in checks else "bytes-passed"
        except Exception as cause:
            raise RuleAnalysisError(cause, f"verify.{patch.id}", (guides[patch.id],)) from cause
    return results
