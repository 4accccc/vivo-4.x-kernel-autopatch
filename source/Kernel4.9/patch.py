"""Per-kernel analysis context, patch construction and checked application."""

from collections.abc import Callable
from dataclasses import dataclass, field

from aarch64 import isimm
from dataflow import Values
from errors import require
from kernel import KernelRelease
from program import Program


@dataclass
class Patch:
    id: str
    address: int
    before: bytes
    after: bytes
    purpose: str
    evidence: dict = field(default_factory=dict)

    def record(self, base):
        return dict(
            id=self.id,
            address=hex(self.address),
            raw_offset=hex(self.address - base),
            before=self.before.hex(),
            after=self.after.hex(),
            purpose=self.purpose,
            evidence=self.evidence,
        )


def apply(raw: bytes, base: int, patches: list[Patch], selected: set[str]) -> bytes:
    require(
        bool(selected) and selected <= {f"P{i}" for i in range(1, 7)}, "Invalid patch selection"
    )
    require(
        [patch.id for patch in patches] == sorted(selected),
        "Generated patches must exactly match the selection",
    )
    occupied = set()
    for patch in patches:
        require(
            len(patch.before) == len(patch.after) and patch.before != patch.after,
            "Invalid patch lengths/state",
        )
        span = set(range(patch.address, patch.address + len(patch.before)))
        require(not span & occupied, "Overlapping patches")
        occupied |= span
    for patch in patches:
        offset = patch.address - base
        require(0 <= offset <= len(raw) - len(patch.before), "Patch outside raw input")
        require(
            raw[offset : offset + len(patch.before)] == patch.before, "Patch original bytes changed"
        )
    result = bytearray(raw)
    for patch in patches:
        offset = patch.address - base
        result[offset : offset + len(patch.after)] = patch.after
    return bytes(result)


@dataclass
class AnalysisContext:
    program: Program
    log: Callable[[str], None]
    _values: dict[int, Values] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        release = KernelRelease.read(self.program.raw)
        release.require_supported()
        release.verify_symbol(self.program)

    def values(self, entry: int) -> Values:
        """Cache belongs to this analysis, so it cannot retain other kernels."""
        if entry not in self._values:
            values = Values(self.program.function(entry))
            # Preserve the original resource bound without a global method LRU.
            if len(self._values) >= 2048:
                del self._values[next(iter(self._values))]
            self._values[entry] = values
        return self._values[entry]

    def instruction_patch(
        self, id: str, address: int, word: int, purpose: str, evidence: dict
    ) -> Patch:
        before = self.program.read(address, 4)
        after = word.to_bytes(4, "little")
        decoded = list(self.program.cs.disasm(after, address, count=1))
        require(len(decoded) == 1, "Replacement does not decode")
        instruction = decoded[0]
        evidence = dict(
            evidence, replacement_assembly=f"{instruction.mnemonic} {instruction.op_str}"
        )
        return Patch(id, address, before, after, purpose, evidence)

    def compare_patch(self, id: str, site: int, purpose: str, evidence: dict) -> Patch:
        """Change only the immediate of a proven W-register CMP against 's'."""
        instruction = self.program.insn(site)
        require(
            instruction.mnemonic == "cmp"
            and isimm(instruction.operands[1])
            and instruction.operands[1].imm == ord("s"),
            "Expected a comparison against s",
        )
        require(
            instruction.reg_name(instruction.operands[0].reg).startswith("w"),
            "Expected 32-bit character comparison",
        )
        word = int.from_bytes(instruction.bytes, "little")
        require(word & 0xFFC0001F == 0x7100001F, "Unsupported CMP encoding")
        replacement = (word & ~(0xFFF << 10)) | (ord("w") << 10)
        return self.instruction_patch(id, site, replacement, purpose, evidence)
