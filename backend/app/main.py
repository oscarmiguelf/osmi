import os

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.application.auth_service import AuthError
from app.application.errors import AppError
from app.infrastructure.api import (
    access, appointments, auth, branches, calendar, cash, catalogs, customers, inventory, products, promotions, purchases, quotes, reports, sales, stocktakes, suppliers, transfers, users, expenses, product_images, settings, public_catalog, custom_fields, price_lists, benefits, clinical, offline_sales,
)

# The interactive docs map every endpoint: on only where asked (local development)
DOCS = os.environ.get("API_DOCS") == "1"
app = FastAPI(title="backend-api", docs_url="/docs" if DOCS else None, redoc_url=None, openapi_url="/openapi.json" if DOCS else None)
app.include_router(auth.router)
app.include_router(calendar.router)
app.include_router(access.router)
app.include_router(customers.router)
app.include_router(branches.router)
app.include_router(cash.router)
# After calendar: /users/search (calendar) must match before /users/{user_id}
app.include_router(users.router)
app.include_router(catalogs.router)
app.include_router(suppliers.router)
app.include_router(products.router)
app.include_router(product_images.router)
app.include_router(inventory.router)
app.include_router(purchases.router)
app.include_router(expenses.router)
app.include_router(transfers.router)
app.include_router(offline_sales.router)  # before sales: /sales/{sale_id} would take /sales/offline/...
app.include_router(sales.router)
app.include_router(quotes.router)
# After sales: its /promotions/active must match before /promotions/{promotion_id}
app.include_router(promotions.router)
app.include_router(stocktakes.router)
app.include_router(appointments.router)
app.include_router(reports.router)
app.include_router(settings.router)
app.include_router(public_catalog.router)
app.include_router(custom_fields.router)
app.include_router(price_lists.router)
app.include_router(benefits.router)
app.include_router(clinical.router)


@app.exception_handler(AuthError)
def auth_error(request, exc):
    return JSONResponse({"detail": "invalid credentials"}, status_code=401,
                        headers={"WWW-Authenticate": "Bearer"})


@app.exception_handler(AppError)
def app_error(request, exc):
    return JSONResponse(jsonable_encoder({"detail": exc.detail}), status_code=exc.status)


@app.get("/health")
def health():
    return {"status": "ok"}
