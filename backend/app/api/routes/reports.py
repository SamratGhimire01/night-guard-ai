from datetime import date

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, require_role
from app.db.models.business import BusinessUser
from app.services.reporting import monthly_report_service, report_service
from app.services.reporting.excel_export import XLSX_MEDIA_TYPE, monthly_report_to_xlsx_bytes, report_to_xlsx_bytes

router = APIRouter()

# Reports expose real customer names/contact info and business performance
# data — same owner/admin bar as every other business-config write in this
# codebase (Phase 4), applied here to reads since this data is sensitive.
_REPORT_ROLES = ["owner", "admin"]


@router.get("/reports/daily")
def get_daily_report(
    report_date: date = Query(alias="date"),
    current_user: BusinessUser = Depends(require_role(_REPORT_ROLES)),
    db: Session = Depends(get_db),
) -> dict:
    return report_service.generate_daily_report(db, business_id=current_user.business_id, report_date=report_date)


@router.get("/reports/daily/excel")
def get_daily_report_excel(
    report_date: date = Query(alias="date"),
    current_user: BusinessUser = Depends(require_role(_REPORT_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    report = report_service.generate_daily_report(db, business_id=current_user.business_id, report_date=report_date)
    xlsx_bytes = report_to_xlsx_bytes(report)
    filename = f"daily_report_{report_date.isoformat()}.xlsx"
    return Response(
        content=xlsx_bytes,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/reports/daily/send")
def send_daily_report(
    report_date: date = Query(alias="date"),
    current_user: BusinessUser = Depends(require_role(_REPORT_ROLES)),
    db: Session = Depends(get_db),
) -> dict:
    """Real, callable action — not a scheduled job. No scheduler/cron
    infrastructure exists yet in this codebase; automatic daily delivery is an
    explicitly deferred later-infrastructure phase (see PHASE_STATUS.md)."""
    return report_service.send_daily_report_email(db, business_id=current_user.business_id, report_date=report_date)


@router.get("/reports/monthly")
def get_monthly_report(
    year: int = Query(ge=2000, le=2100),
    month: int = Query(ge=1, le=12),
    current_user: BusinessUser = Depends(require_role(_REPORT_ROLES)),
    db: Session = Depends(get_db),
) -> dict:
    return monthly_report_service.generate_monthly_report(
        db, business_id=current_user.business_id, year=year, month=month
    )


@router.get("/reports/monthly/excel")
def get_monthly_report_excel(
    year: int = Query(ge=2000, le=2100),
    month: int = Query(ge=1, le=12),
    current_user: BusinessUser = Depends(require_role(_REPORT_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    report = monthly_report_service.generate_monthly_report(
        db, business_id=current_user.business_id, year=year, month=month
    )
    xlsx_bytes = monthly_report_to_xlsx_bytes(report)
    filename = f"monthly_report_{year:04d}-{month:02d}.xlsx"
    return Response(
        content=xlsx_bytes,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/reports/monthly/send")
def send_monthly_report(
    year: int = Query(ge=2000, le=2100),
    month: int = Query(ge=1, le=12),
    current_user: BusinessUser = Depends(require_role(_REPORT_ROLES)),
    db: Session = Depends(get_db),
) -> dict:
    """Same real, callable-not-scheduled discipline as send_daily_report."""
    return monthly_report_service.send_monthly_report_email(
        db, business_id=current_user.business_id, year=year, month=month
    )
