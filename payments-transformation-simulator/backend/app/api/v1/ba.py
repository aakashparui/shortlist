"""BA workbench endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Body

from app.api.deps import Ba, bad_request, not_found
from app.api.schemas import BaPackageRequest
from app.schemes.registry import list_schemes

router = APIRouter(prefix="/ba", tags=["ba-workbench"])


@router.get("/context", summary="What the workbench can build a package for")
def context() -> dict:
    return {
        "schemes": [
            {"code": s.code.value, "name": s.name, "shortName": s.short_name} for s in list_schemes()
        ],
        "artefactChain": [
            "Business Requirement",
            "Functional Requirement",
            "Business Rule",
            "Payment Flow",
            "ISO 20022 Message",
            "Test Case",
        ],
        "note": (
            "Every artefact is derived from the live scheme configuration, rule book and scenario "
            "library, so the documentation always matches the behaviour of the engine."
        ),
    }


@router.post("/package", summary="Generate the full BA artefact package")
def package(payload: BaPackageRequest = Body(default_factory=BaPackageRequest), service: Ba = None) -> dict:  # noqa: RUF013
    try:
        built = service.build_package(
            scheme_code=payload.scheme, scenario_code=payload.scenarioCode
        )
    except KeyError as exc:
        raise bad_request(f"Unknown scheme '{payload.scheme}'") from exc
    except LookupError as exc:
        raise not_found(str(exc)) from exc
    return built.data


@router.get("/package", summary="Generate the BA artefact package (query form)")
def package_get(service: Ba, scheme: str = "SIC_INSTANT", scenarioCode: str | None = None) -> dict:
    try:
        built = service.build_package(scheme_code=scheme, scenario_code=scenarioCode)
    except KeyError as exc:
        raise bad_request(f"Unknown scheme '{scheme}'") from exc
    except LookupError as exc:
        raise not_found(str(exc)) from exc
    return built.data


@router.get("/traceability", summary="Traceability matrix only")
def traceability(service: Ba, scheme: str = "SIC_INSTANT", scenarioCode: str | None = None) -> dict:
    try:
        built = service.build_package(scheme_code=scheme, scenario_code=scenarioCode)
    except KeyError as exc:
        raise bad_request(f"Unknown scheme '{scheme}'") from exc
    return {
        "scheme": scheme,
        "rows": built.data["traceabilityMatrix"],
        "businessRequirement": built.data["businessRequirement"]["id"],
    }
