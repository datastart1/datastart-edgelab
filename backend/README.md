# StrategyTool Licensing Backend Scaffold

This is a starter FastAPI backend for:
- login
- Stripe checkout / portal session creation
- license activation / validation
- device binding
- Stripe webhook entrypoint

## Start locally

1. Create a virtual environment.
2. Install requirements:
   pip install -r requirements.txt
3. Copy `.env.example` to `.env` and fill in values.
4. Run:
   uvicorn app.main:app --reload

## Notes

- The Stripe webhook handler is intentionally minimal in this scaffold.
- Password signup/reset is not included yet.
- Device deactivation is stubbed and should be expanded.
- Add migrations (Alembic) before production.
