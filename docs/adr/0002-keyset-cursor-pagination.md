# ADR 0002: Use Keyset Cursor Pagination

## Status
Accepted

## Context
Offset pagination can skip or repeat parcels when earlier parcels
change state while a client is requesting multiple pages.

## Decision
Order parcels by their creation sequence and issue an opaque cursor
that identifies the last returned sequence. The next page will contain
matching parcels with a greater sequence, rather than skipping an
offset within the current filtered results.

## Consequences
Changes to earlier parcels do not shift the pagination position of
later parcels. Invalid cursors return HTTP 400. The cursor registry
is stored in memory for this exercise, so it will not survive an
application restart.