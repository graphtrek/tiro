from __future__ import annotations

from sqlalchemy.orm import Session

from invoice_core.db import FizetesKalkulatorState

DEFAULT_NET_WAGE = 1_000_000.0
DEFAULT_REVENUE = 0.0


def get_state(db: Session) -> dict:
    """Return the saved calculator inputs, or the page's defaults if never saved."""
    record = db.query(FizetesKalkulatorState).order_by(FizetesKalkulatorState.id).first()
    if record is None:
        return {
            "net_wage": DEFAULT_NET_WAGE,
            "revenue": DEFAULT_REVENUE,
            "revenue_touched": False,
        }
    return {
        "net_wage": record.net_wage,
        "revenue": record.revenue,
        "revenue_touched": record.revenue_touched,
    }


def save_state(db: Session, net_wage: float, revenue: float, revenue_touched: bool) -> dict:
    """Upsert the single shared row holding the calculator's current inputs."""
    record = db.query(FizetesKalkulatorState).order_by(FizetesKalkulatorState.id).first()
    if record is None:
        record = FizetesKalkulatorState(
            net_wage=net_wage, revenue=revenue, revenue_touched=revenue_touched
        )
        db.add(record)
    else:
        record.net_wage = net_wage
        record.revenue = revenue
        record.revenue_touched = revenue_touched
    db.commit()
    db.refresh(record)
    return {
        "net_wage": record.net_wage,
        "revenue": record.revenue,
        "revenue_touched": record.revenue_touched,
    }
