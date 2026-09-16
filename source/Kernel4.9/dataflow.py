"""Symbolic register data flow and shared instruction-pattern analysis."""

import collections

import networkx as nx
from capstone import CS_OP_MEM

from aarch64 import bitwise, isimm, isreg, memory_width, reg, register_name, target
from errors import require


def C(v):
    return ("const", v & ((1 << 64) - 1))


def number(v):
    return v[1] if v and v[0] == "const" else None


def add(a, b):
    if a is None or b is None:
        return None
    if number(a) is not None and number(b) is not None:
        return C(number(a) + number(b))
    if number(a) is not None:
        a, b = b, a
    if number(b) == 0:
        return a
    if a[0] == "add" and number(a[2]) is not None and number(b) is not None:
        return add(a[1], C(number(a[2]) + number(b)))
    return ("add", a, b)


def split_addr(v):
    if v and v[0] == "add" and number(v[2]) is not None:
        n = number(v[2])
        return v[1], n if n < 1 << 63 else n - (1 << 64)
    return v, 0


def contains(v, needle):
    if v == needle:
        return True
    return isinstance(v, tuple) and any(contains(x, needle) for x in v if isinstance(x, tuple))


def load(v, width=None):
    return bool(v and v[0] == "load" and (width is None or v[1] == width))


class Values:
    """Forward symbolic value propagation with conservative joins and call kills.

    Tracks register copies, arithmetic, loads, stack spills, constants, and call
    results. Unknown instructions kill written registers; unequal join values
    become unknown. It does not assume task/cred/structure member offsets.
    """

    def __init__(self, flow):
        self.flow = flow
        initial = {r: ("arg", r) for r in range(31)}
        initial["sp"] = ("stack",)
        self.before = {flow.entry: initial}
        after = {}
        widened = collections.defaultdict(set)
        queue = collections.deque([flow.entry])
        queued = {flow.entry}
        visits = 0
        while queue:
            address = queue.popleft()
            queued.discard(address)
            state = self.transfer(flow.instructions[address], self.before[address])
            visits += 1
            require(visits <= 100 * len(flow.instructions), "Value propagation did not converge")
            if after.get(address) == state:
                continue
            after[address] = state
            for successor in flow.graph.successors(address):
                incoming = [
                    after[predecessor]
                    for predecessor in flow.graph.predecessors(successor)
                    if predecessor in after
                ]
                if successor == flow.entry:
                    incoming.append(initial)
                merged = {}
                for key in set().union(*(incoming_state.keys() for incoming_state in incoming)):
                    incoming_values = [incoming_state.get(key) for incoming_state in incoming]
                    same = incoming_values[0] is not None and all(
                        value == incoming_values[0] for value in incoming_values
                    )
                    if len(incoming) > 1 and not same:
                        widened[successor].add(key)
                    if key not in widened[successor] and same:
                        merged[key] = incoming_values[0]
                    elif isinstance(key, int) or key == "sp":
                        # Phi identity belongs to a real CFG join, not to an
                        # intermediate iteration of a single predecessor.
                        merged[key] = ("join", successor, key)
                if self.before.get(successor) != merged:
                    self.before[successor] = merged
                    if successor not in queued:
                        queue.append(successor)
                        queued.add(successor)

    def get(self, state, register):
        return C(0) if register == "zero" else state.get(register)

    def operand(self, instruction, operand, state):
        if isimm(operand):
            value = C(operand.imm)
        elif isreg(operand):
            value = self.get(state, reg(instruction, operand))
        else:
            return None
        shift = getattr(operand, "shift", None)
        if shift and shift.value:
            return (
                C(number(value) << shift.value)
                if number(value) is not None
                else ("shift", value, shift.value)
            )
        return value

    def memaddr(self, instruction, operand, state):
        register = register_name(instruction.reg_name(operand.mem.base))
        address = add(self.get(state, register), C(operand.mem.disp))
        if operand.mem.index:
            return None
        return address

    def load_value(self, state, width, address):
        if address is None:
            return None
        saved = state.get(("mem", width, address))
        return saved if saved is not None else ("load", width, address)

    def transfer(self, instruction, original):
        state = original.copy()
        operands, mnemonic = instruction.operands, instruction.mnemonic
        if mnemonic in ("bl", "blr"):
            for register in list(range(19)) + [30, "flags"]:
                state.pop(register, None)
            if mnemonic == "bl":
                state[0] = (
                    "call",
                    target(instruction),
                    instruction.address,
                    original.get(0),
                    original.get(1),
                )
            return state
        _, written = instruction.regs_access()
        for register in written:
            name = instruction.reg_name(register)
            # Capstone 5 labels the first CMP/CMN/TST operand as written
            # (the underlying SUBS/ADDS/ANDS destination is actually ZR).
            if mnemonic in ("cmp", "cmn", "tst") and name != "nzcv":
                continue
            key = register_name(name)
            if key == "nzcv":
                key = "flags"
            state.pop(key, None)

        def get(operand):
            return self.operand(instruction, operand, original)

        value = None
        if mnemonic in ("adrp", "adr"):
            value = C(operands[1].imm)
        elif mnemonic in ("mov", "movz"):
            value = get(operands[1])
        elif mnemonic == "movk":
            prior = number(original.get(reg(instruction, operands[0])))
            shift = operands[1].shift.value
            if prior is not None:
                value = C((prior & ~(0xFFFF << shift)) | (operands[1].imm << shift))
        elif mnemonic in ("add", "sub", "adds", "subs", "and", "orr", "eor") and len(operands) >= 3:
            left, right = get(operands[1]), get(operands[2])
            if mnemonic.startswith("add"):
                value = add(left, right)
            elif mnemonic.startswith("sub") and number(right) is not None:
                value = add(left, C(-number(right)))
            elif number(left) is not None and number(right) is not None:
                value = C(bitwise(mnemonic, number(left), number(right)))
            elif left is not None and right is not None:
                value = (mnemonic, left, right)
        elif mnemonic in ("csel", "csinc", "csinv", "csneg", "cset", "csetm"):
            args = tuple(
                get(operand) for operand in operands[1:] if isreg(operand) or isimm(operand)
            )
            value = ("select", instruction.address, *args)
        elif mnemonic in ("uxtb", "uxth", "uxtw", "sxtw"):
            value = get(operands[1])
            if number(value) is not None and mnemonic.startswith("uxt"):
                value = C(
                    number(value) & ((1 << {"uxtb": 8, "uxth": 16, "uxtw": 32}[mnemonic]) - 1)
                )
        elif (
            mnemonic in ("ldr", "ldrb", "ldrh", "ldrsw", "ldur")
            and len(operands) > 1
            and operands[1].type == CS_OP_MEM
        ):
            width = memory_width(instruction)
            value = self.load_value(
                original, width, self.memaddr(instruction, operands[1], original)
            )
        elif mnemonic in ("str", "strb", "strh", "stur") and operands[1].type == CS_OP_MEM:
            width = memory_width(instruction)
            address = self.memaddr(instruction, operands[1], original)
            if address is not None and contains(address, ("stack",)):
                state[("mem", width, address)] = get(operands[0])
        elif mnemonic in ("stp", "ldp") and operands[2].type == CS_OP_MEM:
            self.transfer_pair(instruction, original, state)
        elif mnemonic == "mrs":
            value = ("systemreg", instruction.op_str.split(",")[-1].strip())
        if (
            value is not None
            and operands
            and isreg(operands[0])
            and mnemonic not in ("cmp", "cmn", "tst")
        ):
            # Limit recursive expression growth on loops without substituting
            # arbitrary concrete values.
            if len(repr(value)) < 2400:
                state[reg(instruction, operands[0])] = value
        if mnemonic in ("cmp", "cmn", "tst"):
            state["flags"] = (mnemonic, get(operands[0]), get(operands[1]), instruction.address)
        elif mnemonic in ("subs", "adds"):
            state["flags"] = (mnemonic, get(operands[1]), get(operands[2]), instruction.address)
        return {k: v for k, v in state.items() if v is not None}

    def at(self, address, register):
        return self.get(self.before.get(address, {}), register)

    def comparison(self, address):
        instruction = self.flow.instructions[address]
        if instruction.mnemonic not in ("cmp", "cmn", "tst"):
            return None
        state = self.before[address]
        return self.operand(instruction, instruction.operands[0], state), self.operand(
            instruction, instruction.operands[1], state
        )

    def transfer_pair(self, instruction, original, state):
        """Track paired stack spills/restores and the architectural SP update."""
        operands, mnemonic = instruction.operands, instruction.mnemonic
        address = self.memaddr(instruction, operands[2], original)
        width = memory_width(instruction)
        for index in (0, 1):
            addr = add(address, C(index * width // 8))
            if mnemonic == "ldp":
                state[reg(instruction, operands[index])] = self.load_value(original, width, addr)
            elif addr is not None and contains(addr, ("stack",)):
                state[("mem", width, addr)] = self.operand(instruction, operands[index], original)
        if instruction.writeback:
            base = (
                "sp"
                if instruction.reg_name(operands[2].mem.base) == "sp"
                else instruction.reg_name(operands[2].mem.base)
            )
            if base == "sp":
                state["sp"] = (
                    address
                    if len(operands) == 3
                    else add(original.get("sp"), self.operand(instruction, operands[3], original))
                )


def node_value_contains_call(expr, address):
    if isinstance(expr, tuple):
        return (len(expr) > 1 and expr[0] == "call" and expr[1] == address) or any(
            node_value_contains_call(e, address) for e in expr if isinstance(e, tuple)
        )
    return False


def character_chains(flow, values, word):
    """Match character chains through actual load/compare/branch data flow."""
    facts = []
    for address, instruction in flow.instructions.items():
        if instruction.mnemonic in ("b.eq", "b.ne"):
            flags = values.before[address].get("flags")
            if not flags or flags[0] != "cmp":
                continue
            _, left, right, cmp_site = flags
            if number(left) is not None:
                left, right = right, left
            char = number(right)
            if not load(left, 8) or char is None or not 0 <= char < 256:
                continue
            good, bad = (
                (target(instruction), address + 4)
                if instruction.mnemonic == "b.eq"
                else (address + 4, target(instruction))
            )
        elif instruction.mnemonic in ("cbz", "cbnz"):
            left = values.at(address, reg(instruction, instruction.operands[0]))
            if not load(left, 8):
                continue
            char, cmp_site = 0, None
            good, bad = (
                (target(instruction), address + 4)
                if instruction.mnemonic == "cbz"
                else (address + 4, target(instruction))
            )
        else:
            continue
        root, offset = split_addr(left[2])
        if root is not None:
            facts.append(
                dict(
                    branch=address,
                    comparison=cmp_site,
                    root=root,
                    offset=offset,
                    char=char,
                    good=good,
                    bad=bad,
                    load=left,
                )
            )
    matches = []
    for first in facts:
        if first["offset"] != 0 or first["char"] != word[0]:
            continue
        chain = [first]
        for site, char in enumerate(word[1:], 1):
            prev = chain[-1]
            candidates = [
                fact
                for fact in facts
                if fact["root"] == first["root"]
                and fact["offset"] == site
                and fact["char"] == char
                and flow.reaches(prev["good"], fact["branch"])
                and not flow.reaches(prev["bad"], fact["branch"])
                and flow.dominates(prev["branch"], fact["branch"])
            ]
            if len(candidates) != 1:
                break
            chain += candidates
        if len(chain) == len(word):
            matches.append(chain)
    return matches


def writes_reg(instruction, register):
    if instruction.mnemonic in ("cmp", "cmn", "tst"):
        return False  # aliases only update NZCV, despite Capstone 5 metadata
    if instruction.mnemonic in ("bl", "blr") and isinstance(register, int) and register <= 18:
        return True
    _, written = instruction.regs_access()
    for written_register in written:
        name = instruction.reg_name(written_register)
        if name.startswith(("x", "w")) and name[1:].isdigit() and int(name[1:]) == register:
            return True
    return False


def unchanged_between(flow, start, end, register):
    between = (nx.descendants(flow.graph, start) | {start}) & (
        nx.ancestors(flow.graph, end) | {end}
    )
    return all(not writes_reg(flow.instructions[site], register) for site in between - {start, end})
