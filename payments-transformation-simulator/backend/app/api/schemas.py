"""Request and response models.

Requests are validated by Pydantic before any engine sees them; this is the
first line of input validation, in front of the payment rule book.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ApiModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True, extra="forbid")


class PartyInput(ApiModel):
    name: str = Field(default="", max_length=140)
    accountIdentifier: str = Field(default="", max_length=40)
    iban: str | None = Field(default=None, max_length=42)
    bic: str | None = Field(default=None, max_length=14)
    bankName: str = Field(default="", max_length=140)
    country: str = Field(default="", max_length=2)
    town: str = Field(default="", max_length=80)
    addressLines: list[str] = Field(default_factory=list, max_length=7)

    @field_validator("country")
    @classmethod
    def _upper_country(cls, v: str) -> str:
        return (v or "").upper()

    @field_validator("iban", "bic")
    @classmethod
    def _upper_strip(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v.replace(" ", "").replace("-", "").upper()


class FailureInjectionInput(ApiModel):
    code: str = Field(max_length=40)
    parameters: dict[str, Any] = Field(default_factory=dict)


class PaymentCreate(ApiModel):
    scheme: str = Field(default="SIC_INSTANT", max_length=30)
    amount: Decimal = Field(gt=Decimal("-1000000000"), le=Decimal("100000000000"))
    currency: str = Field(min_length=1, max_length=3)
    requestedExecutionDate: date | None = None
    debtor: PartyInput
    creditor: PartyInput
    # Matches the column. Well above every scheme's limit (140), so the
    # remittance-length rule still has room to fire before the database would.
    remittanceInformation: str = Field(default="", max_length=240)
    remittanceStructured: dict[str, Any] = Field(default_factory=dict)
    purposeCode: str | None = Field(default=None, max_length=10)
    categoryPurpose: str | None = Field(default=None, max_length=10)
    serviceLevel: str | None = Field(default=None, max_length=10)
    localInstrument: str | None = Field(default=None, max_length=35)
    clearingChannel: str | None = Field(default=None, max_length=35)  # ISO Max35Text
    chargeBearer: str | None = Field(default=None, max_length=10)
    priority: str | None = Field(default=None, max_length=10)
    instructionId: str | None = Field(default=None, max_length=40)
    endToEndId: str | None = Field(default=None, max_length=40)
    transactionId: str | None = Field(default=None, max_length=40)
    uetr: str | None = Field(default=None, max_length=40)
    debtorAccountNumber: str | None = Field(default=None, max_length=40)
    processingMode: Literal["IMMEDIATE", "SIMULATED"] = "SIMULATED"
    notes: str = Field(default="", max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=12)
    failureInjections: list[FailureInjectionInput] = Field(default_factory=list, max_length=10)
    createdBy: str = Field(default="simulator.operator", max_length=60)
    source: str = Field(default="UI", max_length=30)

    @field_validator("currency")
    @classmethod
    def _upper_currency(cls, v: str) -> str:
        return (v or "").upper()


class PaymentExecuteRequest(ApiModel):
    processingMode: Literal["IMMEDIATE", "SIMULATED"] | None = None
    waitForCompletion: bool = False
    waitTimeoutSeconds: Annotated[float, Field(ge=0, le=120)] = 30.0


class RetryRequest(ApiModel):
    reason: str = Field(min_length=3, max_length=500)
    actor: str = Field(default="payments.operations", max_length=60)
    processingMode: Literal["IMMEDIATE", "SIMULATED"] | None = None


class ResolveTimeoutRequest(ApiModel):
    accepted: bool
    reasonCode: str | None = Field(default=None, max_length=10)
    actor: str = Field(default="payments.operations", max_length=60)


class CancellationRequest(ApiModel):
    reasonCode: Literal["DUPL", "TECH", "FRAD", "CUST", "AGNT", "CUTA", "UPAY"] = "CUST"
    narrative: str = Field(default="", max_length=400)
    actor: str = Field(default="payments.operations", max_length=60)
    autoResolve: bool = True


class ReturnRequest(ApiModel):
    reasonCode: str = Field(default="AC04", max_length=10)
    narrative: str = Field(default="", max_length=400)
    returnedAmount: Decimal | None = None
    charges: Decimal | None = None
    actor: str = Field(default="clearing.system", max_length=60)


class InvestigationActionRequest(ApiModel):
    action: str = Field(min_length=2, max_length=60)
    note: str = Field(min_length=1, max_length=1000)
    actor: str = Field(default="payments.operations", max_length=60)
    status: Literal["OPEN", "IN_PROGRESS", "AWAITING_RESPONSE", "RESOLVED", "CLOSED_UNRESOLVED"] | None = None


class InvestigationResolveRequest(ApiModel):
    resolution: str = Field(min_length=3, max_length=1000)
    actor: str = Field(default="payments.operations", max_length=60)
    status: Literal["RESOLVED", "CLOSED_UNRESOLVED"] = "RESOLVED"


class RuleToggleRequest(ApiModel):
    enabled: bool
    reason: str = Field(default="", max_length=400)
    actor: str = Field(default="simulator.operator", max_length=60)


class ScenarioRunRequest(ApiModel):
    processingMode: Literal["IMMEDIATE", "SIMULATED"] = "IMMEDIATE"
    waitTimeoutSeconds: Annotated[float, Field(ge=0, le=120)] = 45.0


class TestCaseGenerateRequest(ApiModel):
    ruleId: str | None = Field(default=None, max_length=40)
    scheme: str = Field(default="SIC_INSTANT", max_length=30)
    suite: str = Field(default="", max_length=60)
    persist: bool = True


class TestCaseRunRequest(ApiModel):
    caseIds: list[str] = Field(default_factory=list, max_length=100)
    ruleId: str | None = Field(default=None, max_length=40)
    scheme: str | None = Field(default=None, max_length=30)


class BaPackageRequest(ApiModel):
    scenarioCode: str | None = Field(default=None, max_length=20)
    scheme: str = Field(default="SIC_INSTANT", max_length=30)


class ReconcileRequest(ApiModel):
    actor: str = Field(default="payments.operations", max_length=60)


class SearchRequest(ApiModel):
    query: str = Field(default="", max_length=200)
    limit: Annotated[int, Field(ge=1, le=50)] = 12


class StatementRequest(ApiModel):
    accountNumber: str = Field(max_length=40)
