# ADR-005: Indian-Market Domain First

Status: Accepted

## Context

QuantX is Indian-market-first and must support equities, futures and options without later rebuilding its domain model. Indian derivatives require first-class expiry, strike, lot, multiplier, margin, multi-leg and session concepts.

## Decision

The universal core remains venue-neutral, but the initial product domain models equities, ETFs, indices, futures and options from the beginning. F&O is implemented incrementally but influences the canonical Instrument, Contract, PositionGroup, Margin and OrderGroup abstractions from the start.

## Consequences

The first implementation is more deliberate than a stock-only engine, but later options/F&O capabilities can be added without breaking the fundamental trading lifecycle.

Crypto and international markets may reuse the universal core through adapters/extensions rather than defining the core around crypto assumptions.