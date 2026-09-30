import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, require_role
from app.db.models.business import BusinessUser, BusinessUserRole
from app.schemas.auth import TeamInviteRequest, TeamInviteResult, TeamMemberRead, TeamRoleUpdate
from app.services import account_service

router = APIRouter()

_MANAGERS = ["owner", "admin"]


@router.get("/team", response_model=list[TeamMemberRead])
def list_team(
    current_user: BusinessUser = Depends(require_role(_MANAGERS)), db: Session = Depends(get_db)
) -> list[TeamMemberRead]:
    return [TeamMemberRead.model_validate(u) for u in account_service.list_team(db, business_id=current_user.business_id)]


@router.post("/team", response_model=TeamInviteResult, status_code=201)
def invite_team_member(
    payload: TeamInviteRequest,
    current_user: BusinessUser = Depends(require_role(_MANAGERS)),
    db: Session = Depends(get_db),
) -> TeamInviteResult:
    """Adds a login for a colleague. Owners can add admins and staff; admins can add staff."""
    user, link = account_service.invite_member(
        db, actor=current_user, email=payload.email, role=BusinessUserRole(payload.role)
    )
    return TeamInviteResult(member=TeamMemberRead.model_validate(user), invite_link=link)


@router.patch("/team/{user_id}", response_model=TeamMemberRead)
def change_team_role(
    user_id: uuid.UUID,
    payload: TeamRoleUpdate,
    current_user: BusinessUser = Depends(require_role(_MANAGERS)),
    db: Session = Depends(get_db),
) -> TeamMemberRead:
    user = account_service.change_role(db, actor=current_user, user_id=user_id, role=BusinessUserRole(payload.role))
    return TeamMemberRead.model_validate(user)


@router.delete("/team/{user_id}", status_code=204)
def remove_team_member(
    user_id: uuid.UUID,
    current_user: BusinessUser = Depends(require_role(_MANAGERS)),
    db: Session = Depends(get_db),
) -> None:
    account_service.remove_member(db, actor=current_user, user_id=user_id)
