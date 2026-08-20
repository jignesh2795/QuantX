# QuantX Plugin Contract — Working Draft

This document defines the intended plugin contract shape. It is a design draft, not yet a public API guarantee.

## Manifest

A plugin should declare:

- name
- version
- type
- supported QuantX API range
- provided capabilities
- required capabilities
- supported markets/instruments
- trust level
- license and maintainer metadata

## Runtime boundary

Plugins interact with QuantX through typed ports and service interfaces. A plugin should not reach into private core implementation details.

## Broker plugins

Broker adapters expose normalized account, instrument, market-data, order, position, margin and streaming capabilities according to their declared support.

## Strategy plugins

Strategy plugins produce normalized strategy output or trade intent. They do not bypass the risk and execution services.

## Research plugins

Research plugins operate on documented market-data and result interfaces and may use external research libraries.

## AI plugins

AI plugins may research, analyze and generate candidate strategies. Live execution remains subject to QuantX policies, risk and approval controls.
