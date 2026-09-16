"""Coordinate rule groups; individual rules do not perform file I/O."""

from collections.abc import Callable

from errors import RuleFailure, Unsupported
from patch import AnalysisContext, Patch
from program import Program
from rule_exec_guard import guard_patches
from rule_exec_name import exec_name_patches
from rule_mount import mount_patch, system_path_patch


class Analyzer:
    def __init__(self, program: Program, log: Callable[[str], None] = lambda message: None):
        self.context = AnalysisContext(program, log)

    def operations(self, selected: set[str]):
        for ids, operation in (
            ({"P1", "P2"}, lambda: exec_name_patches(self.context, selected)),
            ({"P3"}, lambda: [system_path_patch(self.context)]),
            ({"P4"}, lambda: [mount_patch(self.context)]),
            ({"P5", "P6"}, lambda: guard_patches(self.context, selected)),
        ):
            if chosen := ids & selected:
                yield ",".join(sorted(chosen)), operation

    def analyze(self, selected: set[str]) -> list[Patch]:
        patches = []
        for name, operation in self.operations(selected):
            self.context.log(f"Matching {name}")
            patches.extend(operation())
        patches.sort(key=lambda patch: patch.id)
        return patches

    def diagnose(self, selected: set[str]) -> dict:
        """A failed proof means unsupported, not that a restriction is absent.

        P3 matches its byte pattern independently of P4. P1/P2 and
        P5/P6 each retain shared locating prerequisites.
        """
        groups = {}
        for name, operation in self.operations(selected):
            try:
                patches = operation()
                groups[name] = dict(
                    status="identified",
                    patches=[patch.record(self.context.program.base) for patch in patches],
                )
            except RuleFailure as error:
                groups[name] = error.record()
                error.emit(self.context.log)
            except Unsupported as error:
                groups[name] = dict(status="unsupported", error=str(error))
        return groups
