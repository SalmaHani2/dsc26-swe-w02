
# """HTTP layer for the Tawseel parcel service.

# The HTTP layer translates requests into calls to app.domain; the domain decides.
# See README.md for the four operations, their operationIds and their errors.
# """
# from fastapi import FastAPI

# from app.domain import EventType, InvalidTransition, Parcel, ParcelState, apply_event  # noqa: F401


# def create_app() -> FastAPI:
#     """Return a NEW FastAPI app with its own empty in-memory store.

#     Tests call this once per test, so nothing may be shared between two apps
#     (no module-level dicts or counters for parcels).
#     """
#     raise NotImplementedError


# # `uvicorn app.api:app` needs a module-level app. Once create_app() works,
# # replace the line below with:  app = create_app()
# app = None
from __future__ import annotations

import secrets
from typing import Any

from fastapi import FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.domain import (
    EventType,
    InvalidTransition,
    Parcel,
    ParcelState,
    apply_event,
)


# ---------- Request and response models ----------

class CreateParcelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merchant_ref: str = Field(min_length=1, max_length=64)
    cod_amount_piastres: int = Field(
        ge=0, le=5_000_000, strict=True
    )
    address_text: str = Field(min_length=1, max_length=500)


class RecordEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: EventType


class ParcelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    merchant_ref: str
    cod_amount_piastres: int
    address_text: str
    state: ParcelState
    attempts: int


class ParcelListResponse(BaseModel):
    items: list[ParcelResponse]
    next_cursor: str | None


# ---------- Standard error responses ----------

def problem(
    status: int,
    title: str,
    errors: list[dict[str, Any]] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": "about:blank",
        "title": title,
        "status": status,
    }

    if errors is not None:
        body["errors"] = errors

    return JSONResponse(
        status_code=status,
        content=body,
        media_type="application/problem+json",
    )


# ---------- Application factory ----------

def create_app() -> FastAPI:
    app = FastAPI(
        title="Tawseel Parcel API",
        version="1.0.0",
    )

    # Each app instance owns its own data.
    parcels: dict[str, Parcel] = {}
    merchant_refs: dict[str, str] = {}
    sequence_by_id: dict[str, int] = {}
    next_sequence = 1

    # Each issued cursor maps to its last sequence and state filter.
    issued_cursors: dict[str, tuple[int, str | None]] = {}

    # ---------- Validation error handler ----------

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        errors = [
            {
                "loc": list(error["loc"]),
                "msg": error["msg"],
            }
            for error in exc.errors()
        ]

        return problem(
            422,
            "Unprocessable Content",
            errors,
        )

    # ---------- 1. Create parcel ----------

    @app.post(
        "/v1/parcels",
        operation_id="createParcel",
        status_code=201,
        response_model=ParcelResponse,
        responses={
            201: {"description": "Parcel created"},
            409: {
                "description": "Duplicate merchant_ref",
                "content": {"application/problem+json": {}},
            },
            422: {
                "description": "Invalid request body",
                "content": {"application/problem+json": {}},
            },
        },
    )
    def create_parcel(
        body: CreateParcelRequest,
        response: Response,
    ) -> Parcel | JSONResponse:
        nonlocal next_sequence

        if body.merchant_ref in merchant_refs:
            return problem(409, "Conflict")

        parcel_id = f"pcl_{next_sequence:06d}"

        parcel = Parcel(
            id=parcel_id,
            merchant_ref=body.merchant_ref,
            cod_amount_piastres=body.cod_amount_piastres,
            address_text=body.address_text,
        )

        parcels[parcel_id] = parcel
        merchant_refs[body.merchant_ref] = parcel_id
        sequence_by_id[parcel_id] = next_sequence

        next_sequence += 1

        response.headers["Location"] = (
            f"/v1/parcels/{parcel_id}"
        )

        return parcel

    # ---------- 2. Get parcel ----------

    @app.get(
        "/v1/parcels/{parcel_id}",
        operation_id="getParcel",
        response_model=ParcelResponse,
        responses={
            404: {
                "description": "Parcel not found",
                "content": {"application/problem+json": {}},
            },
        },
    )
    def get_parcel(
        parcel_id: str,
    ) -> Parcel | JSONResponse:
        parcel = parcels.get(parcel_id)

        if parcel is None:
            return problem(404, "Not Found")

        return parcel

    # ---------- 3. List parcels with cursor pagination ----------

    @app.get(
        "/v1/parcels",
        operation_id="listParcels",
        response_model=ParcelListResponse,
        responses={
            400: {
                "description": "Invalid cursor",
                "content": {"application/problem+json": {}},
            },
            422: {
                "description": "Invalid query parameters",
                "content": {"application/problem+json": {}},
            },
        },
    )
    def list_parcels(
        state: ParcelState | None = Query(default=None),
        limit: int = Query(default=20, ge=1, le=100),
        cursor: str | None = Query(default=None),
    ) -> dict[str, Any] | JSONResponse:
        state_value = state.value if state is not None else None
        last_sequence = 0

        if cursor is not None:
            cursor_data = issued_cursors.get(cursor)

            if cursor_data is None:
                return problem(400, "Invalid cursor")

            last_sequence, cursor_state = cursor_data

            if cursor_state != state_value:
                return problem(400, "Invalid cursor")

        # Continue after the last creation sequence, not an offset.
        ordered = sorted(
            (
                parcel
                for parcel_id, parcel in parcels.items()
                if sequence_by_id[parcel_id] > last_sequence
                and (
                    state is None
                    or parcel.state == state
                )
            ),
            key=lambda parcel: sequence_by_id[parcel.id],
        )

        page = ordered[: limit + 1]
        has_more = len(page) > limit
        items = page[:limit]

        next_cursor = None

        if has_more and items:
            last_id = items[-1].id
            token = secrets.token_urlsafe(24)

            issued_cursors[token] = (
                sequence_by_id[last_id],
                state_value,
            )

            next_cursor = token

        return {
            "items": [
                ParcelResponse.model_validate(parcel).model_dump(
                    mode="json"
                )
                for parcel in items
            ],
            "next_cursor": next_cursor,
        }

    # ---------- 4. Record parcel event ----------

    @app.post(
        "/v1/parcels/{parcel_id}/events",
        operation_id="recordParcelEvent",
        response_model=ParcelResponse,
        responses={
            404: {
                "description": "Parcel not found",
                "content": {"application/problem+json": {}},
            },
            409: {
                "description": "Invalid state transition",
                "content": {"application/problem+json": {}},
            },
            422: {
                "description": "Invalid event request",
                "content": {"application/problem+json": {}},
            },
        },
    )
    def record_parcel_event(
        parcel_id: str,
        body: RecordEventRequest,
    ) -> Parcel | JSONResponse:
        current = parcels.get(parcel_id)

        if current is None:
            return problem(404, "Not Found")

        try:
            updated = apply_event(current, body.type)
        except InvalidTransition:
            return problem(409, "Conflict")

        # Store the result only after a valid transition.
        parcels[parcel_id] = updated

        return updated

    return app


# Used by uvicorn.
app = create_app()
