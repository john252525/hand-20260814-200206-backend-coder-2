from typing import List, Dict, Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Tender, Decision
from app.services.settings_service import get_section


def _train_sklearn(data: List[Dict[str, Any]]) -> dict:
    """Обучает логистическую регрессию на собранных данных."""
    try:
        from sklearn.linear_model import LogisticRegression
        import numpy as np
        X = np.array([[r["nmck"], r["positions_count"], int(r["has_license"])] for r in data])
        y = np.array([r["approved"] for r in data])
        if len(set(y)) < 2:
            approved = sum(y)
            accuracy = max(approved, len(y) - approved) / len(y)
            return {"model_type": "baseline", "samples": len(y), "accuracy": round(accuracy, 3), "note": "Only one class"}
        model = LogisticRegression(max_iter=1000)
        model.fit(X, y)
        acc = model.score(X, y)
        return {"model_type": "logistic_regression", "samples": len(y), "accuracy": round(acc, 3), "coef": model.coef_.tolist()}
    except Exception as e:
        return {"model_type": "error", "samples": len(data), "accuracy": None, "error": str(e)}


async def collect_training_data(db: AsyncSession) -> List[Dict[str, Any]]:
    """Собирает данные для обучения: фичи тендера + результат решения."""
    rows = []
    result = await db.execute(
        select(Tender)
        .join(Decision)
        .options(selectinload(Tender.positions))
        .where(Decision.decision.in_(["APPROVED", "REJECTED"]))
    )
    tenders = result.scalars().all()
    for tender in tenders:
        decision = (await db.execute(select(Decision).where(Decision.tender_id == tender.id))).scalar_one()
        rows.append({
            "nmck": float(tender.nmck or 0),
            "positions_count": len(tender.positions),
            "has_license": bool(tender.structured_data and tender.structured_data.get("requirements", {}).get("license_required", False)) if tender.structured_data else False,
            "approved": 1 if decision.decision == "APPROVED" else 0,
        })
    return rows


async def train_model(db: AsyncSession) -> dict:
    """Обучает модель на собранных данных.
    Возвращает метрики.
    """
    data = await collect_training_data(db)
    if len(data) < 2:
        return {"model_type": "baseline", "samples": len(data), "accuracy": None, "note": "Not enough data"}
    return _train_sklearn(data)
