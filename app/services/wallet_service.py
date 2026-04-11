import httpx
from fastapi import HTTPException
from ..core.config import settings


async def _wallet_call(method: str, path: str, json: dict = None):
    """Make an internal call to wallet-service."""
    base_url = settings.WALLET_SERVICE_URL.rstrip('/')
    url = f"{base_url}{path}"
    headers = {
        "X-Internal-Token": settings.INTERNAL_SERVICE_TOKEN,
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.request(method, url, json=json, headers=headers)
            if resp.status_code == 200:
                return resp.json()
            raise HTTPException(
                status_code=resp.status_code,
                detail=f"wallet-service error: {resp.text}",
            )
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="wallet-service unavailable")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="wallet-service timed out")


async def credit_wallet(customer_id: str | int, amount: float, description: str) -> dict:
    return await _wallet_call("POST", "/internal/credit", json={
        "customer_id": str(customer_id),
        "amount": float(amount),
        "description": description,
    })


async def debit_wallet(customer_id: str | int, amount: float, description: str) -> dict:
    return await _wallet_call("POST", "/internal/debit", json={
        "customer_id": str(customer_id),
        "amount": float(amount),
        "description": description,
    })


async def get_balance(customer_id: str | int) -> float:
    try:
        result = await _wallet_call("GET", f"/internal/balance/{customer_id}")
        return float(result.get("balance", 0))
    except Exception:
        return 0.0