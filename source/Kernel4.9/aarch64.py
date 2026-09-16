"""AArch64 register aliases and branch operands; no firmware-specific values."""

import operator

BITWISE = {"and": operator.and_, "orr": operator.or_, "eor": operator.xor}


def bitwise(mnemonic: str, left: int, right: int) -> int:
    return BITWISE[mnemonic](left, right)


def memory_width(instruction) -> int:
    """Width of the supported integer load/store instructions, in bits."""
    if instruction.mnemonic in ("ldrb", "strb"):
        return 8
    if instruction.mnemonic in ("ldrh", "strh"):
        return 16
    if instruction.mnemonic == "ldrsw" or instruction.reg_name(
        instruction.operands[0].reg
    ).startswith("w"):
        return 32
    return 64


def reg(instruction, operand):
    return register_name(instruction.reg_name(operand.reg))


def register_name(name):
    if name in ("xzr", "wzr"):
        return "zero"
    if name in ("sp", "wsp"):
        return "sp"
    if name in ("fp", "lr"):
        return 29 if name == "fp" else 30
    return int(name[1:]) if name[:1] in ("x", "w") and name[1:].isdigit() else name


def isreg(operand):
    return operand.type == 1


def isimm(operand):
    return operand.type == 2


def target(instruction):
    return (
        (instruction.operands[-1].imm & ((1 << 64) - 1))
        if instruction.operands and isimm(instruction.operands[-1])
        else None
    )


def conditional(instruction):
    return instruction.mnemonic.startswith("b.") or instruction.mnemonic in (
        "cbz",
        "cbnz",
        "tbz",
        "tbnz",
    )
