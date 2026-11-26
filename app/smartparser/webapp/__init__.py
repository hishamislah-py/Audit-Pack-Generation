"""UC-042 Smart Parser browser application (single-user POC).

A thin presentation layer over the EXISTING services: PackageService / PackageStore (package lifecycle), review_api
(HITL review), reconciliation.uc042_adapter.run_reconciliation (the real UC-042 engine) and the hash-chained AuditLog.
Nothing in this package maps, validates, activates or reconciles by itself.
"""
