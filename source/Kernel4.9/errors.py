"""Input refusals and rule failure diagnostics."""

from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from functools import wraps
from typing import ParamSpec, TypeVar

T = TypeVar("T")


class Unsupported(ValueError):
    """The patcher cannot prove that this input can be patched safely."""


def require(condition: object, message: str) -> None:
    if not condition:
        raise Unsupported(message)


def one(items: Iterable[T], description: str) -> T:
    candidates = list(items)
    require(len(candidates) == 1, f"{description}: expected one candidate, got {len(candidates)}")
    return candidates[0]


P = ParamSpec("P")
R = TypeVar("R")


@dataclass(frozen=True)
class RepairGuide:
    rule: str
    title: str
    principle: str
    locate: tuple[str, ...]
    modify: tuple[str, ...]
    pitfalls: tuple[str, ...]
    verify: tuple[str, ...]
    sources: tuple[str, ...]


class RuleFailure(Exception):
    """Keep the original cause and distinguish refusal from an analyzer bug."""

    status: str

    def __init__(self, cause: Exception, stage: str, guides: tuple[RepairGuide, ...]):
        message = (
            str(cause) if isinstance(cause, Unsupported) else f"{type(cause).__name__}: {cause}"
        )
        super().__init__(message)
        self.stage = stage
        self.guides = guides

    def record(self) -> dict:
        return dict(
            status=self.status,
            error=str(self),
            failed_rules=[guide.rule for guide in self.guides],
            failure_stage=self.stage,
            repair_guidance=[asdict(guide) for guide in self.guides],
        )

    def emit(self, log: Callable[[str], None]) -> None:
        label = "REFUSED" if self.status == "unsupported" else "ANALYZER ERROR"
        log(f"{label} [{', '.join(g.rule for g in self.guides)}]: {self}")
        log(f"失败位置: {self.stage}")
        log("以下是规则的人工修复指引，不代表已在当前输入中证明这些位置或机制；先核对原始错误。")
        if len(self.guides) > 1:
            log("此处属于共同分析，尚不能将失败归因于其中某一条规则。")
        for guide in self.guides:
            log(f"\n{guide.rule} — {guide.title}")
            log(f"修改原理: {guide.principle}")
            for title, steps in (
                ("定位与证明", guide.locate),
                ("手动修改", guide.modify),
                ("失败排查", guide.pitfalls),
                ("修改后验证", guide.verify),
                ("实现位置（相对项目根目录）", guide.sources),
            ):
                log(f"  {title}:")
                for index, step in enumerate(steps, 1):
                    log(f"    {index}. {step}")


class RuleUnsupported(RuleFailure, Unsupported):
    """Still catchable as Unsupported by callers of individual rules."""

    status = "unsupported"


class RuleAnalysisError(RuleFailure):
    status = "error"


def explain_failure(*guides: RepairGuide) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Add context without changing successful patches or candidate discovery."""

    def decorate(operation: Callable[P, R]) -> Callable[P, R]:
        @wraps(operation)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            try:
                return operation(*args, **kwargs)
            except RuleFailure:
                # A nested P5 or P6 failure is more precise than the shared guard.
                raise
            except Unsupported as cause:
                raise RuleUnsupported(cause, operation.__qualname__, guides) from cause
            except Exception as cause:
                raise RuleAnalysisError(cause, operation.__qualname__, guides) from cause

        return wrapped

    return decorate
