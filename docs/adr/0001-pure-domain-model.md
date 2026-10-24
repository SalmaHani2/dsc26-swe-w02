# ADR 0001: Keep Parcel Rules in a Pure Domain Module

## Status
Accepted

## Context
The parcel lifecycle contains business rules that may change over time.
These rules should be testable without starting an HTTP server or
depending on a web framework.

## Decision
Keep Parcel, ParcelState, EventType, InvalidTransition, and apply_event
in app/domain.py. This module will use Python standard-library features
only and will return a new immutable Parcel for every accepted event.

## Consequences
The domain rules can be tested independently from the API.
The HTTP layer is responsible for translating domain exceptions into
HTTP responses. This separation reduces coupling between business
logic and infrastructure.