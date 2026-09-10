"""
Financial calculation validation.

Design notes
------------
`extracted_data` (produced by extraction_service) is a dict of
    field_name -> {"value": <any>, "evidence": {...}, "confidence": optional}

Some fields represent a single period ("total_amount") and some represent a
value that repeats across comparative periods, encoded as
"<field_name>__<period_label>" (see extraction_service's prompt). This module:

  1. Flattens extracted_data into {period_label: {field_name: numeric_value}}.
  2. Resolves each concept (e.g. "total_assets") against a small alias table,
     so minor naming variation from the LLM doesn't silently break a check.
  3. Runs the Table-7 formulas for the given document_type, once per period.
  4. Returns NOT_APPLICABLE (never a guessed PASS/FAIL) whenever a required
     operand is missing, per the spec.

All comparisons use a combined absolute + relative tolerance so that minor
rounding in the source document doesn't cause spurious FAILs.
"""
import re
from numbers import Number

from app.core.config import get_settings
from app.core.logging import get_logger
from app.schemas.document import ValidationCheck, ValidationResult

logger = get_logger(__name__)

_DEFAULT_PERIOD = "current"


# ---------------------------------------------------------------------------
# Value parsing / flattening
# ---------------------------------------------------------------------------

def _to_number(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, Number):
        return float(value)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        negative = False
        if s.startswith("(") and s.endswith(")"):
            negative = True
            s = s[1:-1]
        s = re.sub(r"[,\s]", "", s)
        s = re.sub(r"^[A-Za-z$€£₹]+", "", s)  # strip leading currency symbol/code
        s = s.rstrip("%")
        try:
            num = float(s)
        except ValueError:
            return None
        return -num if negative else num
    return None


def _flatten_by_period(extracted_data: dict) -> dict[str, dict[str, float]]:
    """Returns {period_label: {field_name: numeric_value}}."""
    periods: dict[str, dict[str, float]] = {}
    for raw_key, field in extracted_data.items():
        if raw_key == "line_items" or not isinstance(field, dict):
            continue
        value = _to_number(field.get("value"))
        if value is None:
            continue
        if "__" in raw_key:
            field_name, period_label = raw_key.split("__", 1)
        else:
            field_name, period_label = raw_key, _DEFAULT_PERIOD
        periods.setdefault(period_label, {})[field_name] = value
    return periods


# ---------------------------------------------------------------------------
# Alias resolution (tolerates minor field-name variation from the LLM)
# ---------------------------------------------------------------------------

_ALIASES: dict[str, list[str]] = {
    "subtotal": ["subtotal", "sub_total"],
    "tax_amount": ["tax_amount", "tax", "gst", "vat"],
    "discount": ["discount", "discount_amount"],
    "total_amount": ["total_amount", "total", "grand_total", "amount_due", "total_due"],
    "cash_paid": ["cash_paid", "cash_tendered", "amount_paid", "amount_tendered"],
    "change": ["change", "change_due", "change_returned"],

    "total_assets": ["total_assets"],
    "total_liabilities": ["total_liabilities"],
    "total_equity": ["total_equity", "shareholders_equity", "equity", "total_capital"],
    "total_capital_and_liabilities": ["total_capital_and_liabilities", "total_equity_and_liabilities", "total_liabilities_and_equity"],

    "revenue": ["revenue", "total_revenue", "sales", "net_sales"],
    "cost_of_sales": ["cost_of_sales", "cogs", "cost_of_goods_sold"],
    "gross_profit": ["gross_profit"],
    "operating_expenses": ["operating_expenses", "opex"],
    "operating_profit": ["operating_profit", "operating_income", "ebit"],
    "tax": ["tax", "income_tax", "tax_expense"],
    "net_profit": ["net_profit", "net_income", "profit_after_tax", "pat"],

    "interest_earned": ["interest_earned"],
    "other_income": ["other_income"],
    "total_income": ["total_income"],
    "interest_expended": ["interest_expended"],
    "provisions_and_contingencies": ["provisions_and_contingencies", "provisions_contingencies"],
    "total_expenditure": ["total_expenditure", "total_expenses"],
    "net_profit_before_minority_interest": ["net_profit_before_minority_interest", "consolidated_net_profit_before_minority_interest"],
    "minority_interest": ["minority_interest"],
    "net_profit_after_minority_interest": ["net_profit_after_minority_interest", "consolidated_net_profit_attributable_to_group"],
    "brought_forward_profit": ["brought_forward_profit", "profit_brought_forward"],
    "total_available_for_appropriation": ["total_available_for_appropriation"],

    "operating_cash_flow": ["operating_cash_flow", "net_cash_flow_from_operating_activities", "cash_flow_from_operations"],
    "investing_cash_flow": ["investing_cash_flow", "net_cash_flow_from_investing_activities", "cash_flow_from_investing"],
    "financing_cash_flow": ["financing_cash_flow", "net_cash_flow_from_financing_activities", "cash_flow_from_financing"],
    "fx_adjustment": ["fx_adjustment", "fx_translation_adjustment", "effect_of_exchange_rate_changes"],
    "net_change_in_cash": ["net_change_in_cash", "net_increase_in_cash"],
    "opening_cash": ["opening_cash", "opening_cash_and_cash_equivalents", "cash_at_beginning_of_period"],
    "cash_acquired_or_other_adjustments": ["cash_acquired_or_other_adjustments", "cash_acquired_on_amalgamation"],
    "closing_cash": ["closing_cash", "closing_cash_and_cash_equivalents", "cash_at_end_of_period"],
}


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


def _lookup(period_values: dict[str, float], concept: str) -> float | None:
    normalized_values = {_normalize(k): v for k, v in period_values.items()}
    for alias in _ALIASES.get(concept, [concept]):
        key = _normalize(alias)
        if key in normalized_values:
            return normalized_values[key]
    return None


# ---------------------------------------------------------------------------
# Core comparison helper
# ---------------------------------------------------------------------------

def _compare(
    name: str,
    formula: str,
    operands: dict[str, float],
    calculated: float,
    reported: float | None,
    period: str | None,
) -> ValidationCheck:
    settings = get_settings()
    if reported is None:
        return ValidationCheck(
            name=name, formula=formula, period=period, operands=operands,
            calculated_value=round(calculated, 2), reported_value=None, variance=None,
            status="NOT_APPLICABLE", message="Reported value for this check was not found in the document.",
        )
    variance = round(calculated - reported, 2)
    tolerance = max(settings.VALIDATION_ABS_TOLERANCE, abs(reported) * settings.VALIDATION_REL_TOLERANCE)
    status = "PASS" if abs(variance) <= tolerance else "FAIL"
    return ValidationCheck(
        name=name, formula=formula, period=period, operands=operands,
        calculated_value=round(calculated, 2), reported_value=round(reported, 2), variance=variance,
        status=status,
    )


def _not_applicable(name: str, formula: str, period: str | None, missing: list[str]) -> ValidationCheck:
    return ValidationCheck(
        name=name, formula=formula, period=period, operands={},
        calculated_value=None, reported_value=None, variance=None,
        status="NOT_APPLICABLE", message=f"Required field(s) not present in extracted data: {', '.join(missing)}.",
    )


# ---------------------------------------------------------------------------
# Per-document-type check sets
# ---------------------------------------------------------------------------

def _validate_invoice(extracted_data: dict) -> list[ValidationCheck]:
    checks: list[ValidationCheck] = []
    periods = _flatten_by_period(extracted_data)
    values = periods.get(_DEFAULT_PERIOD, {})
    if not values and periods:
        values = next(iter(periods.values()))

    subtotal = _lookup(values, "subtotal")
    tax_amount = _lookup(values, "tax_amount")
    discount = _lookup(values, "discount") or 0.0
    total_amount = _lookup(values, "total_amount")

    if subtotal is not None and tax_amount is not None:
        calc = subtotal + tax_amount - discount
        checks.append(_compare(
            "invoice_total_check", "subtotal + tax_amount - discount",
            {"subtotal": subtotal, "tax_amount": tax_amount, "discount": discount},
            calc, total_amount, None,
        ))
    else:
        checks.append(_not_applicable(
            "invoice_total_check", "subtotal + tax_amount - discount", None,
            [f for f, v in [("subtotal", subtotal), ("tax_amount", tax_amount)] if v is None],
        ))

    # Line items -> subtotal/total reconciliation
    line_items = extracted_data.get("line_items")
    if isinstance(line_items, list) and line_items:
        line_total_sum = 0.0
        any_amount = False
        for item in line_items:
            if not isinstance(item, dict):
                continue
            qty = _to_number(item.get("quantity"))
            unit_price = _to_number(item.get("unit_price"))
            amount = _to_number(item.get("amount") or item.get("line_total"))
            if qty is not None and unit_price is not None and amount is not None:
                any_amount = True
                calc = qty * unit_price
                tolerance = max(1.0, abs(amount) * 0.01)
                item_status = "PASS" if abs(calc - amount) <= tolerance else "FAIL"
                checks.append(ValidationCheck(
                    name=f"line_item_check::{item.get('description', 'item')}",
                    formula="quantity * unit_price ≈ amount",
                    operands={"quantity": qty, "unit_price": unit_price},
                    calculated_value=round(calc, 2), reported_value=round(amount, 2),
                    variance=round(calc - amount, 2), status=item_status,
                ))
            if amount is not None:
                line_total_sum += amount
        target = subtotal if subtotal is not None else total_amount
        if any_amount and target is not None:
            checks.append(_compare(
                "line_items_reconciliation", "sum(line_item.amount)",
                {"line_item_count": len(line_items)}, line_total_sum, target, None,
            ))

    cash_paid = _lookup(values, "cash_paid")
    change = _lookup(values, "change")
    if cash_paid is not None and total_amount is not None:
        calc = cash_paid - total_amount
        checks.append(_compare(
            "cash_change_check", "cash_paid - total_amount", {"cash_paid": cash_paid, "total_amount": total_amount},
            calc, change, None,
        ))

    return checks


def _validate_balance_sheet(extracted_data: dict) -> list[ValidationCheck]:
    checks: list[ValidationCheck] = []
    periods = _flatten_by_period(extracted_data)
    for period, values in periods.items():
        total_assets = _lookup(values, "total_assets")
        total_liabilities = _lookup(values, "total_liabilities")
        total_equity = _lookup(values, "total_equity")
        total_cap_liab = _lookup(values, "total_capital_and_liabilities")

        if total_liabilities is not None and total_equity is not None:
            calc = total_liabilities + total_equity
            reported = total_assets if total_assets is not None else total_cap_liab
            checks.append(_compare(
                "balance_sheet_equation", "total_liabilities + total_equity ≈ total_assets",
                {"total_liabilities": total_liabilities, "total_equity": total_equity}, calc, reported, period,
            ))
        else:
            checks.append(_not_applicable(
                "balance_sheet_equation", "total_liabilities + total_equity ≈ total_assets", period,
                [f for f, v in [("total_liabilities", total_liabilities), ("total_equity", total_equity)] if v is None],
            ))
    return checks


def _validate_profit_and_loss(extracted_data: dict) -> list[ValidationCheck]:
    checks: list[ValidationCheck] = []
    periods = _flatten_by_period(extracted_data)
    for period, values in periods.items():
        revenue = _lookup(values, "revenue")
        cost_of_sales = _lookup(values, "cost_of_sales")
        gross_profit = _lookup(values, "gross_profit")
        operating_expenses = _lookup(values, "operating_expenses")
        operating_profit = _lookup(values, "operating_profit")
        tax = _lookup(values, "tax")
        net_profit = _lookup(values, "net_profit")

        if revenue is not None and cost_of_sales is not None:
            checks.append(_compare(
                "gross_profit_check", "revenue - cost_of_sales ≈ gross_profit",
                {"revenue": revenue, "cost_of_sales": cost_of_sales}, revenue - cost_of_sales, gross_profit, period,
            ))
        else:
            checks.append(_not_applicable("gross_profit_check", "revenue - cost_of_sales ≈ gross_profit", period,
                                           [f for f, v in [("revenue", revenue), ("cost_of_sales", cost_of_sales)] if v is None]))

        if gross_profit is not None and operating_expenses is not None:
            checks.append(_compare(
                "operating_profit_check", "gross_profit - operating_expenses ≈ operating_profit",
                {"gross_profit": gross_profit, "operating_expenses": operating_expenses},
                gross_profit - operating_expenses, operating_profit, period,
            ))
        else:
            checks.append(_not_applicable("operating_profit_check", "gross_profit - operating_expenses ≈ operating_profit", period,
                                           [f for f, v in [("gross_profit", gross_profit), ("operating_expenses", operating_expenses)] if v is None]))

        if operating_profit is not None and tax is not None:
            checks.append(_compare(
                "net_profit_check", "operating_profit - tax ≈ net_profit",
                {"operating_profit": operating_profit, "tax": tax}, operating_profit - tax, net_profit, period,
            ))
        else:
            checks.append(_not_applicable("net_profit_check", "operating_profit - tax ≈ net_profit", period,
                                           [f for f, v in [("operating_profit", operating_profit), ("tax", tax)] if v is None]))

        # Bank/financial-institution style P&L (only runs if those fields exist)
        interest_earned = _lookup(values, "interest_earned")
        other_income = _lookup(values, "other_income")
        total_income = _lookup(values, "total_income")
        if interest_earned is not None and other_income is not None:
            checks.append(_compare(
                "total_income_check", "interest_earned + other_income ≈ total_income",
                {"interest_earned": interest_earned, "other_income": other_income},
                interest_earned + other_income, total_income, period,
            ))

        interest_expended = _lookup(values, "interest_expended")
        provisions = _lookup(values, "provisions_and_contingencies")
        total_expenditure = _lookup(values, "total_expenditure")
        if interest_expended is not None and operating_expenses is not None and provisions is not None:
            checks.append(_compare(
                "total_expenditure_check",
                "interest_expended + operating_expenses + provisions_and_contingencies ≈ total_expenditure",
                {"interest_expended": interest_expended, "operating_expenses": operating_expenses, "provisions_and_contingencies": provisions},
                interest_expended + operating_expenses + provisions, total_expenditure, period,
            ))

        net_profit_before_mi = _lookup(values, "net_profit_before_minority_interest")
        if total_income is not None and total_expenditure is not None:
            checks.append(_compare(
                "net_profit_before_minority_interest_check", "total_income - total_expenditure ≈ net_profit_before_minority_interest",
                {"total_income": total_income, "total_expenditure": total_expenditure},
                total_income - total_expenditure, net_profit_before_mi, period,
            ))

        minority_interest = _lookup(values, "minority_interest")
        net_profit_after_mi = _lookup(values, "net_profit_after_minority_interest")
        if net_profit_before_mi is not None and minority_interest is not None:
            checks.append(_compare(
                "net_profit_after_minority_interest_check", "net_profit_before_minority_interest - minority_interest ≈ net_profit_after_minority_interest",
                {"net_profit_before_minority_interest": net_profit_before_mi, "minority_interest": minority_interest},
                net_profit_before_mi - minority_interest, net_profit_after_mi, period,
            ))

        brought_forward = _lookup(values, "brought_forward_profit")
        total_appropriation = _lookup(values, "total_available_for_appropriation")
        current_profit = net_profit_after_mi if net_profit_after_mi is not None else net_profit
        if current_profit is not None and brought_forward is not None:
            checks.append(_compare(
                "appropriation_check", "current_profit + brought_forward_profit ≈ total_available_for_appropriation",
                {"current_profit": current_profit, "brought_forward_profit": brought_forward},
                current_profit + brought_forward, total_appropriation, period,
            ))

    return checks


def _validate_cash_flow(extracted_data: dict) -> list[ValidationCheck]:
    checks: list[ValidationCheck] = []
    periods = _flatten_by_period(extracted_data)
    for period, values in periods.items():
        operating = _lookup(values, "operating_cash_flow")
        investing = _lookup(values, "investing_cash_flow")
        financing = _lookup(values, "financing_cash_flow")
        fx = _lookup(values, "fx_adjustment") or 0.0
        net_change = _lookup(values, "net_change_in_cash")

        if operating is not None and investing is not None and financing is not None:
            calc = operating + investing + financing + fx
            checks.append(_compare(
                "net_change_in_cash_check",
                "operating_cash_flow + investing_cash_flow + financing_cash_flow + fx_adjustment ≈ net_change_in_cash",
                {"operating_cash_flow": operating, "investing_cash_flow": investing,
                 "financing_cash_flow": financing, "fx_adjustment": fx},
                calc, net_change, period,
            ))
        else:
            checks.append(_not_applicable(
                "net_change_in_cash_check",
                "operating_cash_flow + investing_cash_flow + financing_cash_flow + fx_adjustment ≈ net_change_in_cash",
                period,
                [f for f, v in [("operating_cash_flow", operating), ("investing_cash_flow", investing), ("financing_cash_flow", financing)] if v is None],
            ))

        opening_cash = _lookup(values, "opening_cash")
        adjustments = _lookup(values, "cash_acquired_or_other_adjustments") or 0.0
        closing_cash = _lookup(values, "closing_cash")
        if opening_cash is not None and net_change is not None:
            calc = opening_cash + net_change + adjustments
            checks.append(_compare(
                "closing_cash_check",
                "opening_cash + net_change_in_cash + cash_acquired_or_other_adjustments ≈ closing_cash",
                {"opening_cash": opening_cash, "net_change_in_cash": net_change, "adjustments": adjustments},
                calc, closing_cash, period,
            ))
        else:
            checks.append(_not_applicable(
                "closing_cash_check",
                "opening_cash + net_change_in_cash + cash_acquired_or_other_adjustments ≈ closing_cash",
                period,
                [f for f, v in [("opening_cash", opening_cash), ("net_change_in_cash", net_change)] if v is None],
            ))
    return checks


_VALIDATORS = {
    "invoice": _validate_invoice,
    "balance_sheet": _validate_balance_sheet,
    "profit_and_loss": _validate_profit_and_loss,
    "cash_flow_statement": _validate_cash_flow,
}


def run_financial_validation(document_type: str, extracted_data: dict) -> ValidationResult:
    validator = _VALIDATORS.get(document_type)
    if validator is None:
        return ValidationResult(checks=[], overall_status="NOT_APPLICABLE", issues=[f"No validator defined for document_type={document_type}"])

    checks = validator(extracted_data)
    if not checks:
        return ValidationResult(checks=[], overall_status="NOT_APPLICABLE", issues=["No validation checks could be evaluated for this document."])

    statuses = {c.status for c in checks}
    if "FAIL" in statuses:
        overall = "FAIL"
    elif "PASS" in statuses:
        overall = "PASS"
    else:
        overall = "NOT_APPLICABLE"

    issues = [f"{c.name} ({c.period or 'current'}): reported {c.reported_value} vs calculated {c.calculated_value} (variance {c.variance})"
              for c in checks if c.status == "FAIL"]

    return ValidationResult(checks=checks, overall_status=overall, issues=issues)
