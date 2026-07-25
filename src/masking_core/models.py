from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, model_validator


class Rule(BaseModel):
    name: str
    pattern_type: Literal["literal", "regex"]
    pattern: str
    mode: Literal["fixed", "sequential"]
    fixed_value: str | None = None
    prefix: str | None = None
    enabled: bool = True
    description: str | None = None

    @model_validator(mode="after")
    def check_mode_requirements(self) -> Rule:
        if self.mode == "fixed" and not self.fixed_value:
            raise ValueError(
                f"ルール '{self.name}': mode='fixed' の場合は 'fixed_value' が必須です"
            )
        if self.mode == "sequential" and not self.prefix:
            raise ValueError(
                f"ルール '{self.name}': mode='sequential' の場合は 'prefix' が必須です"
            )
        if self.pattern_type == "regex":
            try:
                re.compile(self.pattern)
            except re.error as exc:
                raise ValueError(
                    f"ルール '{self.name}': 'pattern' が正しい正規表現ではありません: {exc}"
                ) from exc
        return self


class RuleProfile(BaseModel):
    profile_name: str
    description: str | None = None
    rules: list[Rule] = Field(default_factory=list)


def format_validation_error(exc: ValidationError) -> str:
    """pydanticのValidationErrorから、人が書いたメッセージ本文だけを取り出して整形する。

    pydanticの`str(exc)`はtype=value_error/input_value=.../pydantic.devのURL等の
    内部実装情報を含み、input_valueには検証対象の全フィールド値(ユーザーが
    入力した実際の値)がそのままダンプされる。呼び出し側(GUI/CLI)はこの関数
    経由でのみエラー内容をユーザーに表示し、raw ValidationErrorを直接文字列化
    しない。
    """
    lines: list[str] = []
    # include_input=False/include_url=Falseでpydantic側にキー自体を含めさせない
    # (呼び出し側でキーを読まないことに頼るより、バージョン非依存で確実)。
    for err in exc.errors(include_input=False, include_url=False):
        ctx = err.get("ctx")
        ctx_error = ctx.get("error") if isinstance(ctx, dict) else None
        if ctx_error is not None:
            # model_validatorがraise ValueError(...)した場合、元のメッセージは
            # ctx.errorにpydanticの接頭辞なしで保持される。
            lines.append(str(ctx_error))
        else:
            msg = str(err.get("msg", ""))
            prefix = "Value error, "
            if msg.startswith(prefix):
                msg = msg[len(prefix):]
            lines.append(msg)
    return "\n".join(lines)
