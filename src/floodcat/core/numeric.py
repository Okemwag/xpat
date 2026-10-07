import math
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from .errors import ModelError

def finite(value, field: str) -> float:
    if isinstance(value, bool):
        raise ModelError("invalid_number", f"{field} must be numeric, not boolean")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ModelError("invalid_number", f"{field} must be numeric") from None
    if not math.isfinite(number):
        raise ModelError("invalid_number", f"{field} must be finite")
    return number

def bounded(value, field: str, low=0., high=1.) -> float:
    number = finite(value, field)
    if not low <= number <= high:
        raise ModelError("out_of_range", f"{field} must be between {low} and {high}")
    return number

def money(value, field="tiv_kes") -> Decimal:
    finite(value, field)
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise ModelError("invalid_money", f"{field} is invalid") from None
    if number < 0:
        raise ModelError("negative_value", f"{field} cannot be negative")
    return number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def money_string(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")
