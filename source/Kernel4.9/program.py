"""Verified ELF mapping and instruction-level control-flow recovery."""

import bisect
import collections
import functools
import struct
from dataclasses import dataclass

import networkx as nx
from capstone import CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN, Cs
from elftools.elf.elffile import ELFFile

from aarch64 import conditional, target
from errors import Unsupported, one, require


@dataclass
class Flow:
    entry: int
    instructions: dict
    graph: nx.DiGraph
    calls: list
    tails: list

    @functools.cached_property
    def dominators(self):
        result = nx.immediate_dominators(self.graph, self.entry)
        result[self.entry] = self.entry
        return result

    def dominates(self, dominator, address):
        if address not in self.dominators:
            return False
        while address != dominator and self.dominators[address] != address:
            address = self.dominators[address]
        return dominator == address

    def reaches(self, start, destination):
        if start == destination:
            return True
        todo, seen = [start], set()
        while todo:
            address = todo.pop()
            if address in seen:
                continue
            seen.add(address)
            for successor in self.graph.successors(address) if address in self.graph else ():
                if successor == destination:
                    return True
                todo.append(successor)
        return False


class Program:
    """Instruction-level CFG recovery from symbols and decoded direct-call seeds.

    Symbols locate anchors, never substitute nearest-symbol guesses for a CFG.
    Numeric bounds are resource limits, not firmware addresses or signatures.
    """

    def __init__(self, raw, symbols, *, max_nodes=24000):
        self.raw = bytes(raw)
        self.symbols = symbols
        self.base = self.symbol("_text")
        self.ranges = [
            (self.symbol(address), self.symbol(end))
            for address, end in [("_stext", "_etext"), ("_sinittext", "_einittext")]
        ]
        require(
            all(self.base <= address < end <= self.base + len(raw) for address, end in self.ranges),
            "Executable symbol ranges do not map to this raw image",
        )
        self.cs = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
        self.cs.detail = True
        self.max_nodes = max_nodes
        self.refs = collections.defaultdict(list)
        self.entries = {
            address for values in symbols.values() for address in values if self.executable(address)
        }
        for start, end in self.ranges:
            for offset in range(start - self.base, end - self.base, 4):
                word = struct.unpack_from("<I", self.raw, offset)[0]
                if word & 0x7C000000 == 0x14000000:
                    delta = word & 0x3FFFFFF
                    if delta & (1 << 25):
                        delta -= 1 << 26
                    destination, site = self.base + offset + 4 * delta, self.base + offset
                    if self.executable(destination):
                        kind = "bl" if word & 0x80000000 else "b"
                        self.refs[destination].append((site, kind))
                        if kind == "bl":
                            self.entries.add(destination)
        self.sorted_entries = sorted(self.entries)
        # Known Linux non-returning routines (directly or via panic/do_exit).
        # Treating the instruction after a
        # stack-canary failure call as reachable creates spurious CFG loops in
        # GCC builds whose cold failure block precedes another basic block.
        self.noreturn = {
            address
            for name in ("__stack_chk_fail", "panic", "do_exit", "do_group_exit")
            for address in symbols.get(name, ())
        }

    @classmethod
    def from_elf(cls, raw, filename):
        symbols = collections.defaultdict(set)
        with open(filename, "rb") as stream:
            elf = ELFFile(stream)
            require(
                elf.elfclass == 64 and elf.little_endian and elf["e_machine"] == "EM_AARCH64",
                "Only little-endian AArch64 ELF is supported",
            )
            for section in elf.iter_sections():
                if section["sh_type"] == "SHT_SYMTAB":
                    for symbol in section.iter_symbols():
                        if symbol.name and symbol["st_value"]:
                            symbols[symbol.name].add(symbol["st_value"])
            if "_text" not in symbols:
                # CONFIG_KALLSYMS_ALL=n may omit the linker-defined _text.
                # The arm64 Image executes B stext from code0, or code1
                # after the EFI MZ-producing ADD. Decode that edge, not a
                # guessed virtual base or a fixed distance from _stext.
                symbols["_text"].add(cls.header_base(raw, symbols))
            base = one(symbols["_text"], "_text")
            # Match every file-backed ELF segment to the raw image. No known hash
            # or device-specific base is accepted as a substitute for this check.
            checked = 0
            for segment in elf.iter_segments():
                if segment["p_type"] != "PT_LOAD" or not segment["p_filesz"]:
                    continue
                offset = segment["p_vaddr"] - base
                require(
                    0 <= offset and offset + segment["p_filesz"] <= len(raw),
                    "ELF/raw mapping out of range",
                )
                require(
                    raw[offset : offset + segment["p_filesz"]] == segment.data(),
                    "ELF does not describe this raw input",
                )
                checked += segment["p_filesz"]
            require(checked > 0, "ELF contains no usable load segments")
        return cls(raw, dict(symbols))

    @staticmethod
    def header_base(raw, symbols):
        require(
            len(raw) >= 64 and raw[56:60] == b"ARMd",
            "Missing _text and no valid arm64 Image header",
        )
        code0, code1 = struct.unpack_from("<II", raw)
        if code0 == 0x91005A4D:  # add x13,x18,#0x16: Linux EFI MZ header
            site, word = 4, code1
        else:
            require(code1 == 0, "Missing _text: unsupported Image entry layout")
            site, word = 0, code0
        require(word & 0xFC000000 == 0x14000000, "Missing _text: Image entry is not a direct B")
        displacement = word & 0x3FFFFFF
        if displacement & (1 << 25):
            displacement -= 1 << 26
        offset = site + displacement * 4
        require(64 <= offset < len(raw), "Image entry target outside raw kernel")
        entry = one(symbols.get("stext", ()), "Image entry symbol stext")
        base = entry - offset
        require(base > 0 and base % 4096 == 0, "Unaligned Image entry-derived base")
        start = one(symbols.get("_sinittext", ()), "symbol _sinittext")
        end = one(symbols.get("_einittext", ()), "symbol _einittext")
        require(start <= entry < end, "Image entry symbol outside init text")
        return base  # caller still verifies every file-backed ELF PT_LOAD

    def symbol(self, name):
        return one(self.symbols.get(name, ()), "symbol " + name)

    def executable(self, address):
        return not address % 4 and any(start <= address < end for start, end in self.ranges)

    def read(self, address, size):
        offset = address - self.base
        require(0 <= offset <= len(self.raw) - size, f"Unmapped raw read at {address:#x}")
        return self.raw[offset : offset + size]

    @functools.lru_cache(maxsize=180000)
    def insn(self, address):
        require(self.executable(address), f"Non-executable instruction address {address:#x}")
        decoded = list(self.cs.disasm(self.read(address, 4), address, count=1))
        require(
            len(decoded) == 1 and decoded[0].mnemonic not in ("udf", ".byte"),
            f"Invalid instruction {address:#x}",
        )
        return decoded[0]

    @functools.lru_cache(maxsize=4096)
    def function(self, entry):
        todo, instructions, edges, calls, tails = [entry], {}, [], [], []
        while todo:
            address = todo.pop()
            if address in instructions:
                continue
            require(len(instructions) < self.max_nodes, "CFG resource limit exceeded")
            instruction = self.insn(address)
            instructions[address] = instruction
            if instruction.mnemonic in ("ret", "br", "eret", "brk", "hlt"):
                continue
            if instruction.mnemonic == "bl":
                calls.append((address, target(instruction)))
                if target(instruction) in self.noreturn:
                    continue
            if instruction.mnemonic == "b":
                successor = target(instruction)
                if successor != entry and successor in self.entries:
                    tails.append((address, successor))
                    continue
                successors = [successor]
            elif conditional(instruction):
                successors = [target(instruction), address + 4]
            else:
                successors = [address + 4]
            for successor in successors:
                require(self.executable(successor), "CFG escapes mapped text")
                if (
                    successor != entry
                    and successor in self.entries
                    and not conditional(instruction)
                    and instruction.mnemonic != "b"
                ):
                    # Crossing a distinct call/symbol entry by fallthrough is
                    # not silently treated as part of this function.
                    continue
                edges.append((address, successor))
                todo.append(successor)
        graph = nx.DiGraph()
        graph.add_nodes_from(instructions)
        graph.add_edges_from(edges)
        return Flow(entry, instructions, graph, sorted(calls), sorted(tails))

    @functools.lru_cache(maxsize=4096)
    def owner(self, site):
        end = bisect.bisect_right(self.sorted_entries, site)
        # A bounded reverse search followed by actual CFG reachability, not an
        # offset from the nearest symbol. Exceeding this bound is unsupported.
        for entry in reversed(self.sorted_entries[max(0, end - 256) : end]):
            try:
                flow = self.function(entry)
                if site in flow.instructions:
                    return flow
            except Unsupported:
                continue
        raise Unsupported(f"No recovered caller CFG contains {site:#x}")

    def callers(self, address):
        found = {}
        for site, kind in self.refs.get(address, []):
            try:
                flow = self.owner(site)
                if (site, address) in (flow.calls if kind == "bl" else flow.tails):
                    found[flow.entry] = flow
            except Unsupported:
                continue
        return list(found.values())
