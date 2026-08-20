# QuantX Architecture Review Checklist

Before architecture work is merged and implementation begins, review:

- [ ] Core has no concrete broker/UI/AI dependencies
- [ ] Domain contracts cover equity, futures and options foundations
- [ ] Event lifecycle is explicit and replayable
- [ ] Backtest, sandbox, paper and live share domain semantics
- [ ] Broker/data adapters use ports and capability negotiation
- [ ] Plugin trust and permission boundaries are defined
- [ ] Strategy IR is sufficiently generic for Python, Flow, AI and webhooks
- [ ] Data/control/execution planes are separated
- [ ] Local-first deployment works without unnecessary infrastructure
- [ ] Distributed seams are explicit but not prematurely implemented
- [ ] Contract-test strategy is documented
- [ ] Roadmap milestones have exit criteria
- [ ] Existing open-source projects were checked before rebuilding equivalent functionality
