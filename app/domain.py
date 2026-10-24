"""Parcel lifecycle rules for Tawseel.

Pure Python: do not import fastapi, starlette, pydantic or sqlalchemy here
(a hidden test checks). Keep the names below exactly as they are.
"""
from dataclasses import dataclass, replace
from enum import StrEnum

MAX_ATTEMPTS = 3


class ParcelState(StrEnum):
    CREATED = "created"
    OUT_FOR_DELIVERY = "out_for_delivery"
    FAILED_ATTEMPT = "failed_attempt"
    DELIVERED = "delivered"
    RETURNED = "returned"


class EventType(StrEnum):
    DISPATCH = "dispatch"
    DELIVER = "deliver"
    FAIL = "fail"
    RETURN = "return"


class InvalidTransition(Exception): ...


@dataclass(frozen=True)
class Parcel:
    id: str
    merchant_ref: str
    cod_amount_piastres: int
    address_text: str
    state: ParcelState = ParcelState.CREATED
    attempts: int = 0


def apply_event(parcel: Parcel, event: EventType) -> Parcel:
    """Return a new Parcel. Raise InvalidTransition if the event is not allowed.

    - created + dispatch -> out_for_delivery, attempts + 1
    - out_for_delivery + deliver -> delivered
    - out_for_delivery + fail -> failed_attempt
    - failed_attempt + dispatch -> out_for_delivery, attempts + 1, only if attempts < MAX_ATTEMPTS
    - failed_attempt + return -> returned
    - delivered and returned are final; every other combination raises InvalidTransition.
    Never mutate the input parcel.
    """
    if parcel.state == ParcelState.CREATED:
        if event == EventType.DISPATCH:
            return replace(
                parcel,
                state=ParcelState.OUT_FOR_DELIVERY,
                attempts=parcel.attempts + 1,
            )

    elif parcel.state == ParcelState.OUT_FOR_DELIVERY:
        if event == EventType.DELIVER:
            return replace(
                parcel,
                state=ParcelState.DELIVERED,
            )

        if event == EventType.FAIL:
            return replace(
                parcel,
                state=ParcelState.FAILED_ATTEMPT,
            )

    elif parcel.state == ParcelState.FAILED_ATTEMPT:
        if event == EventType.DISPATCH:
            if parcel.attempts < MAX_ATTEMPTS:
                return replace(
                    parcel,
                    state=ParcelState.OUT_FOR_DELIVERY,
                    attempts=parcel.attempts + 1,
                )

        if event == EventType.RETURN:
            return replace(
                parcel,
                state=ParcelState.RETURNED,
            )

    raise InvalidTransition(
        f"Event {event} is not allowed from state {parcel.state}"
    )
